from __future__ import annotations

from copy import deepcopy
from statistics import mean, median
from typing import Any

from app.backtest.models import BacktestRequest, StrategyName


FORWARD_HORIZONS = (1, 5, 10, 20)


def comparable_request_signature(raw_request: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy/default fields and ignore only the variant-specific input."""
    normalized = BacktestRequest.model_validate(raw_request).model_dump(mode="json")
    normalized.pop("strategy", None)
    normalized["parameters"].pop("day1_stop_pct", None)
    return normalized


def find_matching_advanced(variant: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    target = comparable_request_signature(variant["parameters"])
    for candidate in candidates:
        if candidate["status"] != "COMPLETED" or candidate["strategy"] != StrategyName.ADVANCED.value:
            continue
        if candidate.get("strategy_version") != variant.get("strategy_version"):
            continue
        if comparable_request_signature(candidate["parameters"]) == target:
            return candidate
    return None


def _date(value: Any) -> str:
    return str(value)[:10]


def _position_outcome(position: dict[str, Any] | None) -> dict[str, Any] | None:
    if position is None:
        return None
    return {
        "position_id": position.get("position_id"),
        "entry_date": position.get("entry_date"),
        "entry_price": position.get("entry_price"),
        "final_exit_date": position.get("final_exit_date"),
        "exit_reason": position.get("exit_final_close_reason"),
        "net_pnl": position.get("net_pnl"),
        "return_pct": position.get("return_pct"),
    }


def _group_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def values(key: str) -> list[float]:
        return [float(row[key]) for row in rows if row.get(key) is not None]

    return {
        "count": len(rows),
        "average_stop_loss_pct": mean(values("loss_pct")) if values("loss_pct") else None,
        "median_5_day_forward_return_pct": median(values("forward_5d_pct")) if values("forward_5d_pct") else None,
        "median_10_day_forward_return_pct": median(values("forward_10d_pct")) if values("forward_10d_pct") else None,
        "median_20_day_forward_return_pct": median(values("forward_20d_pct")) if values("forward_20d_pct") else None,
    }


def build_day1_stop_diagnostic(
    *,
    variant_record: dict[str, Any],
    baseline_record: dict[str, Any],
) -> dict[str, Any]:
    variant_result = variant_record["result"]
    baseline_result = baseline_record["result"]
    request = BacktestRequest.model_validate(variant_record["parameters"])
    if request.strategy != StrategyName.ADVANCED_DAY1_STOP:
        raise ValueError("Day1 Stop diagnostic requires an Advanced + Day1 3% Stop backtest.")

    daily_rows = variant_result["daily_data"]
    daily_index = {_date(row["timestamp"]): index for index, row in enumerate(daily_rows)}
    daily_by_date = {_date(row["timestamp"]): row for row in daily_rows}
    events_by_date: dict[str, list[dict[str, Any]]] = {}
    for event in variant_result["events"]:
        events_by_date.setdefault(_date(event["timestamp"]), []).append(event)
    executions_by_date: dict[str, list[dict[str, Any]]] = {}
    for execution in variant_result["executions"]:
        executions_by_date.setdefault(_date(execution["timestamp"]), []).append(execution)

    stops: list[dict[str, Any]] = []
    for position in variant_result["positions"]:
        if position.get("exit_final_close_reason") != "DAY1_FULL_STOP":
            continue
        entry_date = _date(position["entry_date"])
        daily = daily_by_date[entry_date]
        execution = next(
            item for item in executions_by_date.get(entry_date, [])
            if item["side"] == "SELL" and item["reason"] == "DAY1_FULL_STOP"
        )
        ambiguity = any(
            event["event"] == "DAILY_INTRABAR_AMBIGUITY"
            and "DAY1_FULL_STOP" in event.get("metadata", {}).get("simultaneous_conditions", [])
            for event in events_by_date.get(entry_date, [])
        )
        row_index = daily_index[entry_date]
        forward: dict[int, float | None] = {}
        for horizon in FORWARD_HORIZONS:
            target_index = row_index + horizon
            forward[horizon] = (
                (float(daily_rows[target_index]["close"]) / float(execution["price"]) - 1) * 100
                if target_index < len(daily_rows) else None
            )
        reference_ma = float(daily["reference_ma"])
        entry_price = float(position["entry_price"])
        execution_price = float(execution["price"])
        stops.append({
            "position_id": position["position_id"],
            "entry_date": entry_date,
            "previous_day_ma": reference_ma,
            "entry_price": entry_price,
            "day1_stop_price": reference_ma * (1 - request.parameters.day1_stop_pct / 100),
            "day1_open": daily["open"],
            "day1_high": daily["high"],
            "day1_low": daily["low"],
            "day1_close": daily["close"],
            "execution_price": execution_price,
            "loss_pct": (execution_price / entry_price - 1) * 100,
            "daily_intrabar_ambiguity": ambiguity,
            "next_day_close_return_pct": forward[1],
            "forward_5d_pct": forward[5],
            "forward_10d_pct": forward[10],
            "forward_20d_pct": forward[20],
            "backtest_id": variant_record["id"],
        })

    baseline_by_entry = {_date(position["entry_date"]): position for position in baseline_result["positions"]}
    variant_by_id = {position["position_id"]: position for position in variant_result["positions"]}
    comparisons: list[dict[str, Any]] = []
    for stop in stops:
        variant_position = variant_by_id[stop["position_id"]]
        baseline_position = baseline_by_entry.get(stop["entry_date"])
        baseline_pnl = float(baseline_position["net_pnl"]) if baseline_position is not None else None
        variant_pnl = float(variant_position["net_pnl"])
        comparisons.append({
            "entry_date": stop["entry_date"],
            "match_status": "MATCHED_ENTRY_DATE" if baseline_position is not None else "NO_BASELINE_POSITION_ON_ENTRY_DATE",
            "baseline_backtest_id": baseline_record["id"],
            "variant_backtest_id": variant_record["id"],
            "original_advanced": _position_outcome(baseline_position),
            "day1_stop_strategy": _position_outcome(variant_position),
            "pnl_difference": variant_pnl - baseline_pnl if baseline_pnl is not None else None,
        })

    matched = [row for row in comparisons if row["pnl_difference"] is not None]
    damage = [row for row in matched if row["pnl_difference"] < 0]
    improvements = [row for row in matched if row["pnl_difference"] > 0]
    unambiguous = [row for row in stops if not row["daily_intrabar_ambiguity"]]
    ambiguous = [row for row in stops if row["daily_intrabar_ambiguity"]]
    return {
        "ticker": variant_record["ticker"],
        "start_date": variant_record["start_date"],
        "end_date": variant_record["end_date"],
        "strategy": variant_record["strategy"],
        "variant_backtest_id": variant_record["id"],
        "baseline_backtest_id": baseline_record["id"],
        "day1_full_stop_count": len(stops),
        "daily_intrabar_ambiguity_count": len(ambiguous),
        "stops": stops,
        "group_statistics": {
            "unambiguous": _group_stats(unambiguous),
            "ambiguous": _group_stats(ambiguous),
        },
        "backtest_comparison": {
            "existing_advanced_total_return": baseline_result["summary"]["total_return"],
            "day1_stop_total_return": variant_result["summary"]["total_return"],
            "total_return_difference": variant_result["summary"]["total_return"] - baseline_result["summary"]["total_return"],
            "existing_advanced_final_equity": baseline_result["summary"]["final_equity"],
            "day1_stop_final_equity": variant_result["summary"]["final_equity"],
            "final_equity_difference": variant_result["summary"]["final_equity"] - baseline_result["summary"]["final_equity"],
        },
        "comparison": {
            "matched_count": len(matched),
            "unmatched_count": len(comparisons) - len(matched),
            "all_divergences": comparisons,
            "largest_return_damage": sorted(deepcopy(damage), key=lambda row: row["pnl_difference"])[:10],
            "largest_improvements": sorted(deepcopy(improvements), key=lambda row: row["pnl_difference"], reverse=True)[:10],
        },
    }
