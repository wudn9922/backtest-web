from __future__ import annotations

from typing import Any


POLICY_ORDER = ("conservative", "ohlc_heuristic", "favorable")
STRATEGY_ORDER = ("advanced", "advanced_day1_stop")


def _date(value: Any) -> str:
    return str(value)[:10]


def _positions_by_entry(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {_date(position["entry_date"]): position for position in result["positions"]}


def _event_count(result: dict[str, Any], event_name: str) -> int:
    return sum(event.get("event") == event_name for event in result["events"])


def analyze_legacy_entry_chasing(record: dict[str, Any] | None) -> dict[str, Any]:
    """Classify saved v1 BUY executions that chased an Open above UpperEntry."""
    if not record or not record.get("result"):
        return {"legacy_backtest_id": None, "count": 0, "entries": [], "available": False}
    params = record["parameters"]["parameters"]
    upper_pct = float(params.get("entry_stop_pct", 1.5))
    daily = {_date(row["timestamp"]): row for row in record["result"].get("daily_data", [])}
    entries = []
    for execution in record["result"].get("executions", []):
        if execution.get("side") != "BUY":
            continue
        day = _date(execution["timestamp"])
        row = daily.get(day)
        if not row or row.get("reference_ma") is None:
            continue
        reference_ma = float(row["reference_ma"])
        upper_entry = reference_ma + reference_ma * upper_pct / 100
        day_open = float(row["open"])
        if day_open > upper_entry:
            entries.append({
                "date": day,
                "entry_price": float(execution["price"]),
                "open": day_open,
                "reference_ma": reference_ma,
                "upper_entry": upper_entry,
                "gap_above_upper_entry_pct": (day_open / upper_entry - 1) * 100,
            })
    return {"legacy_backtest_id": record["id"], "count": len(entries), "entries": entries, "available": True}


def _matrix_row(strategy: str, policy: str, record: dict[str, Any]) -> dict[str, Any]:
    result = record["result"]
    summary = result["summary"]
    return {
        "strategy": strategy,
        "policy": policy,
        "backtest_id": record["id"],
        "strategy_version": result.get("strategy_version"),
        "positions": summary["number_of_positions"],
        "entry_zone_missed_count": _event_count(result, "ENTRY_ZONE_MISSED"),
        "ambiguous_positions": summary["ambiguous_positions"],
        "day1_full_stop_count": _event_count(result, "DAY1_FULL_STOP"),
        "total_return": summary["total_return"],
        "cagr": summary["cagr"],
        "max_drawdown": summary["max_drawdown"],
        "sharpe": summary["sharpe_ratio"],
    }


def _matched_delta(advanced: dict[str, Any], variant: dict[str, Any], policy: str) -> dict[str, Any]:
    advanced_positions = _positions_by_entry(advanced["result"])
    variant_positions = _positions_by_entry(variant["result"])
    dates = sorted(set(advanced_positions) & set(variant_positions))
    pnl_deltas = [float(variant_positions[day]["net_pnl"]) - float(advanced_positions[day]["net_pnl"]) for day in dates]
    return {
        "policy": policy,
        "advanced_backtest_id": advanced["id"],
        "day1_stop_backtest_id": variant["id"],
        "matched_positions": len(dates),
        "advanced_only_positions": len(set(advanced_positions) - set(variant_positions)),
        "day1_stop_only_positions": len(set(variant_positions) - set(advanced_positions)),
        "matched_net_pnl_delta": sum(pnl_deltas),
        "total_return_delta": variant["result"]["summary"]["total_return"] - advanced["result"]["summary"]["total_return"],
    }


def build_ambiguity_sensitivity(
    *,
    records: dict[tuple[str, str], dict[str, Any]],
    legacy_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    conservative = records[("advanced_day1_stop", "conservative")]
    matrix = [_matrix_row(strategy, policy, records[(strategy, policy)]) for strategy in STRATEGY_ORDER for policy in POLICY_ORDER]
    return {
        "ticker": conservative["ticker"],
        "start_date": conservative["start_date"],
        "end_date": conservative["end_date"],
        "strategy_version": conservative["result"].get("strategy_version"),
        "matrix": matrix,
        "policies": [row for row in matrix if row["strategy"] == "advanced_day1_stop"],
        "matched_deltas": [_matched_delta(records[("advanced", policy)], records[("advanced_day1_stop", policy)], policy) for policy in POLICY_ORDER],
        "legacy_entry_chasing": analyze_legacy_entry_chasing(legacy_record),
    }
