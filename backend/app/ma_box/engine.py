from __future__ import annotations

"""MA_BOX_LONG_V1 implementation.

This module is deliberately independent from the legacy strategy selector. It
composes the project's canonical entry-zone, stop, Portfolio and OHLC policy
helpers while keeping the box state machine and its audit trail local to this
namespace.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.backtest.execution import evaluate_entry_zone, execution_policy
from app.backtest.indicators import moving_average, wilder_atr
from app.backtest.metrics import calculate_metrics, drawdown_details, monthly_returns
from app.backtest.models import Execution, StrategyParameters, StrategyState
from app.backtest.portfolio import Portfolio, initial_quantity
from app.backtest.strategies.simple_ma_breakout import SimpleMABreakout
from app.backtest.strategies.base import Bar, EventRecorder


SPEC_PATH = Path(__file__).resolve().parents[3] / "research" / "specs" / "MA_BOX_LONG_V1_REVISION_3.md"
STRATEGY_REVISION = "MA_BOX_LONG_V1"
SPEC_REVISION = "MA_BOX_LONG_V1_REVISION_3"
SPEC_REVISION_NUMBER = 3

REASONS = {
    "NORMAL_MA_ENTRY", "MA_STOP_EXIT", "MA_ENTANGLEMENT_START", "BOX_ACTIVE",
    "BOX_BOUNDARY_UPDATE", "BOX_UP_BREAKOUT", "BOX_DOWN_BREAK",
    "BOX_DIRECT_BREAKOUT_ENTRY", "NO_ENTRY_BOX_RISK_GT_5",
    "NO_ENTRY_BOX_RISK_NOT_POSITIVE", "NO_ENTRY_GAP_RISK_GT_5",
    # Master-spec spelling retained as a compatibility/audit vocabulary
    # entry; Revision 2's more specific BOX_RISK code is used by V1 paths.
    "NO_ENTRY_RISK_DISTANCE_GT_5",
    "NO_ENTRY_OPEN_AT_OR_BELOW_STOP", "WAIT_RETEST", "MA_RETEST_TOUCH",
    "MA_RETEST_REBOUND", "BOX_BREAKOUT_RETEST_ENTRY", "FAILED_BOX_BREAKOUT",
    "BOX_REACTIVATED", "BOX_INVALIDATED", "FILTERED_BY_BOX", "COUNTERFACTUAL_ENTRY",
    "COUNTERFACTUAL_EXIT", "FORCED_END_OF_TEST_EXIT", "BOX_FORMING_NOT_READY_ATR",
    "BOX_CONSUMED_BY_ENTRY", "NO_ENTRY_ALREADY_LONG", "STUDY_END_UNFILLED",
    "ENTRY_ZONE_MISSED", "BREAKOUT_TRIGGERED",
    "DIRECT_ENTRY_ELIGIBLE",
}

# Public, deterministic state-machine contract used by the audit/UI layer.
# Position state is intentionally orthogonal and is not encoded in this map.
SETUP_STATES = (
    "TREND_ELIGIBLE", "BOX_FORMING", "BOX_ACTIVE", "BREAKOUT_CONFIRMED",
    "DIRECT_ENTRY_ELIGIBLE", "WAIT_RETEST", "RETEST_CONFIRMED", "FAILED_BREAKOUT",
    "BEAR_BOX_BREAK", "BOX_INVALIDATED",
)
ALLOWED_SETUP_TRANSITIONS = {
    "TREND_ELIGIBLE": {"TREND_ELIGIBLE", "BOX_FORMING"},
    "BOX_FORMING": {"BOX_ACTIVE"},
    "BOX_ACTIVE": {"BOX_ACTIVE", "BREAKOUT_CONFIRMED", "BEAR_BOX_BREAK", "BOX_INVALIDATED"},
    "BREAKOUT_CONFIRMED": {"DIRECT_ENTRY_ELIGIBLE", "WAIT_RETEST", "BOX_INVALIDATED"},
    "DIRECT_ENTRY_ELIGIBLE": {"WAIT_RETEST", "BOX_INVALIDATED"},
    "WAIT_RETEST": {"WAIT_RETEST", "RETEST_CONFIRMED", "FAILED_BREAKOUT", "BEAR_BOX_BREAK", "BOX_INVALIDATED"},
    "RETEST_CONFIRMED": {"RETEST_CONFIRMED", "BOX_INVALIDATED", "WAIT_RETEST"},
    "FAILED_BREAKOUT": {"BOX_ACTIVE"},
    "BEAR_BOX_BREAK": {"BOX_INVALIDATED"},
    "BOX_INVALIDATED": {"TREND_ELIGIBLE", "BOX_FORMING", "BOX_ACTIVE", "BOX_INVALIDATED"},
}


def spec_sha256() -> str:
    return hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()


def config_sha256(config: "MABoxConfig", *, spec_hash: str, data_fingerprint: str | None) -> str:
    """Canonical study identity hash shared by API persistence and engine."""
    return hashlib.sha256(json.dumps(
        {"config": config.as_dict(), "spec_hash": spec_hash, "data_fingerprint": data_fingerprint},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MABoxConfig:
    ticker: str
    selected_ma: int
    nearby_range: int = 5
    step: int = 1
    start_date: date = date(2021, 1, 1)
    end_date: date = date(2026, 1, 1)
    initial_capital: float = 100_000.0
    position_size_pct: float = 100.0
    commission_pct: float = 0.05
    slippage_pct: float = 0.02
    force_close_at_end: bool = True
    ma_type: str = "sma"
    atr_period: int = 14
    boundary_contact_tolerance_multiplier: float = 0.10
    boundary_contact_tolerance_mode: str = "ATR_NORMALIZED"

    def periods(self) -> list[int]:
        if self.step < 1:
            raise ValueError("step must be >= 1")
        if self.nearby_range < 0:
            raise ValueError("nearby_range must be >= 0")
        lower = max(2, self.selected_ma - self.nearby_range)
        upper = min(500, self.selected_ma + self.nearby_range)
        periods = list(range(lower, upper + 1, self.step))
        if lower <= self.selected_ma <= upper and self.selected_ma not in periods:
            periods.append(self.selected_ma)
            periods.sort()
        return periods

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker.upper(), "selected_ma": self.selected_ma,
            "nearby_range": self.nearby_range, "step": self.step,
            "start_date": self.start_date.isoformat(), "end_date": self.end_date.isoformat(),
            "initial_capital": self.initial_capital, "position_size_pct": self.position_size_pct,
            "commission_pct": self.commission_pct, "slippage_pct": self.slippage_pct,
            "force_close_at_end": self.force_close_at_end, "ma_type": self.ma_type,
            "atr_period": self.atr_period,
            "boundary_contact_tolerance_multiplier": self.boundary_contact_tolerance_multiplier,
            "boundary_contact_tolerance_mode": self.boundary_contact_tolerance_mode,
            "periods": self.periods(),
        }


@dataclass
class Contact:
    bar_index: int
    date: str
    field: str
    price: float
    side: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class BoundaryEvidence:
    level: float
    contacts: list[Contact] = field(default_factory=list)
    mad: float = 0.0

    @property
    def count(self) -> int:
        return len(self.contacts)

    @property
    def distinct_bars(self) -> int:
        return len({x.bar_index for x in self.contacts})

    def as_dict(self) -> dict[str, Any]:
        return {"level": self.level, "contact_count": self.count,
                "distinct_bars": self.distinct_bars, "mad": self.mad,
                "contacts": [x.as_dict() for x in self.contacts]}


@dataclass
class BoxContext:
    box_id: str
    formation_indices: list[int]
    formation_dates: list[str]
    high: float
    low: float
    midpoint: float
    tolerance: float
    tolerance_mode: str
    tolerance_atr_period: int
    tolerance_multiplier: float
    contacts: list[Contact] = field(default_factory=list)
    upper_evidence: BoundaryEvidence | None = None
    lower_evidence: BoundaryEvidence | None = None
    breakout_attempt_id: str | None = None
    breakout_index: int | None = None
    breakout_box_high: float | None = None
    breakout_stop: float | None = None
    boundary_updates: list[dict[str, Any]] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "box_id": self.box_id, "BoxHigh": self.high, "BoxLow": self.low,
            "initial_midpoint": self.midpoint, "tolerance": self.tolerance,
            "tolerance_mode": self.tolerance_mode, "tolerance_atr_period": self.tolerance_atr_period,
            "tolerance_multiplier": self.tolerance_multiplier,
            "breakout_attempt_id": self.breakout_attempt_id,
        }


def _date(ts: Any) -> str:
    return pd.Timestamp(ts).date().isoformat()


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    if frame.empty or not required.issubset(frame.columns):
        raise ValueError("Daily OHLCV columns are required")
    out = frame.copy().sort_index()
    if out.index.tz is None:
        raise ValueError("Daily timestamps must be timezone-aware")
    out = out[sorted(required)].apply(pd.to_numeric, errors="coerce")
    if out[list(required)].isna().any().any():
        raise ValueError("Daily OHLCV contains non-numeric values")
    if not np.isfinite(out.to_numpy(dtype=float)).all():
        raise ValueError("Daily OHLCV contains non-finite values")
    return out


def _event(*, ts: Any, period: int, reason: str, setup_before: str, setup_after: str,
           position_before: int, position_after: int, row: pd.Series,
           current_ma: float | None, reference_ma: float | None, box: BoxContext | None = None,
           attempt_id: str | None = None, position_id: str | None = None,
           phase: str = "CLOSE", trigger: float | None = None,
           raw_fill: float | None = None, actual_fill: float | None = None,
           metadata: dict[str, Any] | None = None, event_id: str | None = None) -> dict[str, Any]:
    if reason not in REASONS:
        raise ValueError(f"unknown MA_BOX reason code: {reason}")
    meta = dict(metadata or {})
    is_transaction = raw_fill is not None or actual_fill is not None
    result = {
        "event_id": event_id or f"{STRATEGY_REVISION}-{period}-{_date(ts)}-{reason}", "timestamp": pd.Timestamp(ts).isoformat(),
        "date": _date(ts), "phase": phase, "strategy_revision": STRATEGY_REVISION,
        "period": period, "sma_period": period, "visual_ma": current_ma, "execution_ma": reference_ma,
        "open": _finite(row.get("open")), "high": _finite(row.get("high")),
        "low": _finite(row.get("low")), "close": _finite(row.get("close")),
        "position_state_before": "LONG_POSITION" if position_before else "FLAT",
        "position_state_after": "LONG_POSITION" if position_after else "FLAT",
        "setup_state_before": setup_before, "setup_state_after": setup_after,
        "box_id": box.box_id if box else None,
        "breakout_attempt_id": attempt_id or (box.breakout_attempt_id if box else None),
        "position_id": position_id, "BoxHigh": box.high if box else None,
        "BoxLow": box.low if box else None, "trigger_price": trigger,
        "raw_fill": raw_fill, "actual_fill": actual_fill,
        # Stable audit-schema fields.  Transaction-specific values are
        # supplied by callers in metadata; non-transaction events retain
        # explicit nulls rather than silently inventing execution data.
        "BoxHigh_before": meta.get("BoxHigh_before", box.high if box else None),
        "BoxHigh_after": meta.get("BoxHigh_after", box.high if box else None),
        "BoxLow_before": meta.get("BoxLow_before", box.low if box else None),
        "BoxLow_after": meta.get("BoxLow_after", box.low if box else None),
        "stop": meta.get("stop", trigger if reason == "MA_STOP_EXIT" else None),
        "planned_entry": meta.get("planned_entry", trigger if "ENTRY" in reason and is_transaction else None),
        "risk_distance": meta.get("risk_distance"),
        "quantity": meta.get("quantity", abs(position_after - position_before) if is_transaction else None),
        "commission": meta.get("commission"),
        "slippage": meta.get("slippage"),
        "supporting_contacts": meta.get("supporting_contacts"),
        "source_cutoff": meta.get("source_cutoff", pd.Timestamp(ts).isoformat()),
        "reason_code": reason, "metadata": meta,
    }
    if box:
        result["tolerance"] = box.tolerance
        result["tolerance_mode"] = box.tolerance_mode
        result["boundary_evidence"] = {
            "upper": box.upper_evidence.as_dict() if box.upper_evidence else None,
            "lower": box.lower_evidence.as_dict() if box.lower_evidence else None,
        }
    return result


def _contacts_for_bar(index: int, ts: Any, row: pd.Series, ma: float, midpoint: float, side: str) -> list[Contact]:
    values = {"open": float(row["open"]), "high": float(row["high"]), "low": float(row["low"]), "close": float(row["close"])}
    fields = ("high", "open", "close") if side == "upper" else ("low", "open", "close")
    output: list[Contact] = []
    for field_name in fields:
        price = values[field_name]
        if (side == "upper" and price >= midpoint) or (side == "lower" and price <= midpoint):
            output.append(Contact(index, _date(ts), field_name, price, side))
    return output


def _cluster(points: list[Contact], seed: Contact, tolerance: float) -> BoundaryEvidence:
    selected = [point for point in points if abs(point.price - seed.price) <= tolerance]
    level = float(np.median([point.price for point in selected])) if selected else seed.price
    selected = [point for point in points if abs(point.price - level) <= tolerance]
    prices = np.asarray([point.price for point in selected], dtype=float)
    mad = float(np.median(np.abs(prices - np.median(prices)))) if len(prices) else 0.0
    return BoundaryEvidence(level=level, contacts=selected, mad=mad)


def _best_evidence(points: list[Contact], current: BoundaryEvidence, tolerance: float, side: str) -> BoundaryEvidence | None:
    if not points:
        return None
    candidates = [_cluster(points, seed, tolerance) for seed in points]
    candidates = [candidate for candidate in candidates if candidate.distinct_bars >= 2]
    if not candidates:
        return None
    candidates.sort(key=lambda x: (-x.count, -x.distinct_bars, x.mad,
                                   abs(x.level - current.level),
                                   -x.level if side == "upper" else x.level))
    return candidates[0]


def _strictly_improves_boundary(candidate: BoundaryEvidence | None, current: BoundaryEvidence | None) -> bool:
    """Frozen boundary update gate: contact count must strictly increase."""
    return candidate is not None and current is not None and candidate.count > current.count


def _initial_box(enriched: pd.DataFrame, indices: list[int], qualifying: list[int], period: int,
                 atr_period: int, multiplier: float) -> BoxContext | None:
    atr = _finite(enriched.iloc[indices[-1]].get("atr"))
    if atr is None or atr <= 0:
        return None
    high = max(float(enriched.iloc[i]["high"]) for i in qualifying)
    low = min(float(enriched.iloc[i]["low"]) for i in qualifying)
    if not math.isfinite(high) or not math.isfinite(low) or high <= low:
        return None
    midpoint = (high + low) / 2
    tolerance = multiplier * atr
    contacts: list[Contact] = []
    for i in qualifying:
        row = enriched.iloc[i]
        contacts.extend(_contacts_for_bar(i, enriched.index[i], row, float(row["ma"]), midpoint, "upper"))
        contacts.extend(_contacts_for_bar(i, enriched.index[i], row, float(row["ma"]), midpoint, "lower"))
    upper_points = [x for x in contacts if x.side == "upper"]
    lower_points = [x for x in contacts if x.side == "lower"]
    dummy_upper = BoundaryEvidence(high)
    dummy_lower = BoundaryEvidence(low)
    return BoxContext(
        box_id=f"box-{period}-{_date(enriched.index[indices[-1]])}", formation_indices=qualifying,
        formation_dates=[_date(enriched.index[i]) for i in qualifying], high=high, low=low,
        midpoint=midpoint, tolerance=tolerance, tolerance_mode="ATR_NORMALIZED",
        tolerance_atr_period=atr_period, tolerance_multiplier=multiplier,
        contacts=contacts, upper_evidence=_best_evidence(upper_points, dummy_upper, tolerance, "upper") or dummy_upper,
        lower_evidence=_best_evidence(lower_points, dummy_lower, tolerance, "lower") or dummy_lower,
    )


def evaluate_box_structural_gate(box_high: float, stop_next: float) -> dict[str, Any]:
    """Revision 2 Stage A gate; intentionally independent of breakout Close."""
    risk = (box_high - stop_next) / box_high if box_high else math.inf
    if 0 < risk <= 0.05:
        return {"eligible": True, "reason": "DIRECT_ENTRY_ELIGIBLE", "risk_distance": risk}
    if risk > 0.05:
        return {"eligible": False, "reason": "NO_ENTRY_BOX_RISK_GT_5", "risk_distance": risk}
    return {"eligible": False, "reason": "NO_ENTRY_BOX_RISK_NOT_POSITIVE", "risk_distance": risk}


def evaluate_box_execution_gate(bar_open: float, stop_next: float, slippage_pct: float) -> dict[str, Any]:
    """Revision 2 Stage B next-open safety recheck."""
    actual_entry = bar_open * (1 + slippage_pct / 100)
    risk = (actual_entry - stop_next) / actual_entry if actual_entry else math.inf
    if actual_entry <= stop_next:
        reason = "NO_ENTRY_OPEN_AT_OR_BELOW_STOP"
        eligible = False
    elif risk > 0.05:
        reason = "NO_ENTRY_GAP_RISK_GT_5"
        eligible = False
    else:
        reason = "DIRECT_ENTRY_ELIGIBLE"
        eligible = True
    return {"eligible": eligible, "reason": reason, "actual_entry": actual_entry, "risk_distance": risk}


def _entanglement(enriched: pd.DataFrame, i: int, evaluation_start_i: int) -> tuple[list[int], list[int]] | None:
    if i - 3 < evaluation_start_i:
        return None
    indices = list(range(i - 3, i + 1))
    qualifying = [j for j in indices if float(enriched.iloc[j]["low"]) <= float(enriched.iloc[j]["ma"]) <= float(enriched.iloc[j]["high"])]
    if len(qualifying) < 3:
        return None
    sides = []
    for j in qualifying:
        close, ma = float(enriched.iloc[j]["close"]), float(enriched.iloc[j]["ma"])
        if close > ma:
            sides.append("ABOVE")
        elif close < ma:
            sides.append("BELOW")
    if "ABOVE" not in sides or "BELOW" not in sides:
        return None
    if not any(a != b for a, b in zip(sides, sides[1:])):
        return None
    return indices, qualifying


def _raw_execution_price(execution: Execution) -> float:
    """Recover the canonical raw fill from the recorded execution.

    The Portfolio object records the absolute slippage cost on every
    execution.  Using that execution-level value (rather than re-splitting an
    aggregate position fee) keeps the counterfactual audit exactly aligned
    with the authoritative ledger.
    """
    if execution.quantity <= 0:
        return float(execution.price)
    if execution.side == "BUY":
        return float(execution.price - execution.slippage / execution.quantity)
    return float(execution.price + execution.slippage / execution.quantity)


def _execution_audit_fields(execution: Execution, prefix: str) -> dict[str, Any]:
    return {
        f"{prefix}_date": execution.timestamp.isoformat(),
        f"{prefix}_raw_fill": _raw_execution_price(execution),
        f"{prefix}_actual_fill": float(execution.price),
        f"{prefix}_quantity": int(execution.quantity),
        f"{prefix}_commission": float(execution.commission),
        f"{prefix}_slippage_cost": float(execution.slippage),
    }


def _positions(executions: list[Execution], daily: pd.DataFrame) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for execution in executions:
        if execution.side == "BUY":
            current = {
                "position_id": f"position-{len(result) + 1}",
                "entry_date": execution.timestamp.isoformat(), "entry_price": execution.price,
                "initial_shares": execution.quantity, "total_shares_sold": 0,
                "sell_proceeds": 0.0, "sell_execution_value": 0.0,
                "fees": execution.commission, "final_exit_date": None,
                "exit_final_close_reason": None,
            }
            current.update(_execution_audit_fields(execution, "entry"))
            current["entry_quantity"] = int(execution.quantity)
        elif current is not None:
            current["total_shares_sold"] += execution.quantity
            current["sell_proceeds"] += execution.gross_value - execution.commission
            current["sell_execution_value"] += execution.price * execution.quantity
            current["fees"] += execution.commission
            if execution.position_remaining == 0:
                entry_dt = datetime.fromisoformat(current["entry_date"])
                exit_dt = execution.timestamp
                entry_price = float(current["entry_price"])
                entry_day, exit_day = entry_dt.date(), exit_dt.date()
                sliced = daily[(daily.index.date >= entry_day) & (daily.index.date <= exit_day)]
                buy_cost = entry_price * current["initial_shares"] + current["fees"] - execution.commission
                sell_proceeds = current["sell_proceeds"]
                net = sell_proceeds - buy_cost
                current.update({
                    "final_exit_date": execution.timestamp.isoformat(),
                    "exit_final_close_reason": execution.reason,
                    "gross_pnl": current["sell_execution_value"] - current["initial_shares"] * entry_price,
                    "net_pnl": net, "realized_pnl": net,
                    "q0": current["initial_shares"],
                    "final_return": net / buy_cost if buy_cost else None,
                    "return_pct": net / buy_cost * 100 if buy_cost else None,
                    "holding_days": max(0, (exit_day - entry_day).days),
                    "maximum_favorable_excursion": float(sliced["high"].max() / entry_price - 1) if len(sliced) else None,
                    "maximum_adverse_excursion": float(sliced["low"].min() / entry_price - 1) if len(sliced) else None,
                })
                current.update(_execution_audit_fields(execution, "exit"))
                current["exit_date"] = execution.timestamp.isoformat()
                current["exit_reason"] = execution.reason
                current["mfe"] = current["maximum_favorable_excursion"]
                current["mae"] = current["maximum_adverse_excursion"]
                for key in ("sell_proceeds", "sell_execution_value"):
                    current.pop(key, None)
                result.append(current)
                current = None
    return result


def _ledger_row(ts: Any, row: pd.Series, portfolio: Portfolio, *, setup_state: str | None = None,
                realized_pnl: float | None = None) -> dict[str, Any]:
    """Take an immutable end-of-day portfolio snapshot.

    The row is deliberately materialized while the simulation is at the end
    of the session.  It must never be reconstructed later from the final
    portfolio state (which would erase all historical position exposure).
    """
    close = float(row["close"])
    quantity = int(portfolio.quantity)
    cash = float(portfolio.cash)
    market_value = quantity * close
    result: dict[str, Any] = {
        "timestamp": pd.Timestamp(ts).isoformat(),
        "date": _date(ts),
        "cash_end_of_day": cash,
        "quantity_end_of_day": quantity,
        "close_price": close,
        "market_value_close": market_value,
        "equity_close": cash + market_value,
        "position_state": "LONG_POSITION" if quantity else "FLAT",
    }
    if setup_state is not None:
        result["setup_state"] = setup_state
    if realized_pnl is not None:
        result["daily_realized_pnl"] = float(realized_pnl)
    return result


def _ledger_series(ledger: list[dict[str, Any]]) -> pd.Series:
    if not ledger:
        raise ValueError("MA_BOX track produced no daily ledger")
    return pd.Series(
        [float(row["equity_close"]) for row in ledger],
        index=pd.DatetimeIndex([row["timestamp"] for row in ledger]),
        dtype=float,
    )


def _initial_capital_anchored(equity: pd.Series, initial_capital: float) -> pd.Series:
    """Prepend the initial cash anchor used for drawdown calculations."""
    first = pd.Timestamp(equity.index[0])
    anchor = first - pd.Timedelta(microseconds=1)
    return pd.concat([
        pd.Series([float(initial_capital)], index=pd.DatetimeIndex([anchor])),
        equity,
    ])


def _summary(equity: pd.Series, positions: list[dict[str, Any]], initial_capital: float,
             exposure_days: int, total_days: int, portfolio: Portfolio, benchmark: pd.Series) -> tuple[dict[str, Any], pd.Series]:
    # Metrics must see the initial capital as the peak before the first EOD
    # mark; this preserves a first-day commission/slippage drawdown.
    metrics_equity = _initial_capital_anchored(equity, initial_capital)
    metrics_benchmark = _initial_capital_anchored(benchmark, initial_capital)
    summary, drawdown = calculate_metrics(
        metrics_equity, metrics_benchmark, positions, initial_capital, exposure_days, total_days,
        portfolio.total_commission, portfolio.total_slippage_cost,
        sum(item.side == "SELL" for item in portfolio.executions),
    )
    summary["drawdown_recovery_status"] = summary.get("recovery_date") or "UNRECOVERED"
    pnls = [float(x["net_pnl"]) for x in positions]
    summary["loss_rate"] = sum(x < 0 for x in pnls) / len(pnls) if pnls else 0
    summary["breakeven_rate"] = sum(x == 0 for x in pnls) / len(pnls) if pnls else 0
    # The study contract uses an explicit unavailable value rather than the
    # legacy display sentinel 999 when no gross loss exists.
    if not any(x < 0 for x in pnls):
        summary["profit_factor"] = None
    summary["median_holding_days"] = float(np.median([x["holding_days"] for x in positions])) if positions else None
    # ``drawdown_details`` reports the *maximum-depth* drawdown.  The study
    # contract also requires the longest underwater duration, which can be a
    # different episode, so calculate every contiguous underwater interval.
    running_max = metrics_equity.cummax()
    underwater = (metrics_equity < running_max).to_numpy()
    longest_sessions = 0
    longest_calendar = 0
    i = 0
    while i < len(metrics_equity):
        if not underwater[i]:
            i += 1
            continue
        under_start = i
        while i + 1 < len(metrics_equity) and underwater[i + 1]:
            i += 1
        under_end = i
        peak_value = float(running_max.iloc[under_start])
        peak_candidates = np.flatnonzero(metrics_equity.iloc[:under_start + 1].to_numpy() >= peak_value - 1e-12)
        peak_pos = int(peak_candidates[-1]) if len(peak_candidates) else under_start
        recovery_pos = next((j for j in range(under_end + 1, len(metrics_equity)) if float(metrics_equity.iloc[j]) >= peak_value - 1e-12), None)
        end_pos = recovery_pos if recovery_pos is not None else len(metrics_equity) - 1
        sessions = end_pos - peak_pos + 1
        calendar = int((pd.Timestamp(metrics_equity.index[end_pos]) - pd.Timestamp(metrics_equity.index[peak_pos])).days)
        if sessions > longest_sessions:
            longest_sessions, longest_calendar = sessions, calendar
        i += 1
    summary["longest_drawdown_trading_days"] = longest_sessions
    summary["longest_drawdown_calendar_days"] = longest_calendar
    summary["selected_ma"] = None
    return summary, drawdown


def _result_from_track(*, track: str, period: int, cfg: MABoxConfig, frame: pd.DataFrame,
                       portfolio: Portfolio, events: list[dict[str, Any]], exposure_days: int,
                       daily_ledger: list[dict[str, Any]],
                       chart_state: list[dict[str, Any]] | None = None,
                       extra: dict[str, Any] | None = None) -> dict[str, Any]:
    if len(daily_ledger) != len(frame):
        raise ValueError("MA_BOX daily ledger must contain exactly one row per evaluation session")
    equity = _ledger_series(daily_ledger)
    first_close = float(frame.iloc[0]["close"])
    benchmark = cfg.initial_capital * pd.Series(
        [float(row["close_price"]) for row in daily_ledger], index=equity.index,
    ) / first_close
    positions = _positions(portfolio.executions, frame)
    summary, drawdown = _summary(equity, positions, cfg.initial_capital, exposure_days, len(frame), portfolio, benchmark)
    summary["selected_ma"] = period
    position_ranges = [
        (pd.Timestamp(item["entry_date"]).date(), pd.Timestamp(item["final_exit_date"]).date())
        for item in positions if item.get("entry_date") and item.get("final_exit_date")
    ]
    output = {
        "track": track, "sma_period": period, "summary": summary,
        "canonical_engine": True, "execution_policy": "ohlc_heuristic",
        "commission_pct": cfg.commission_pct, "slippage_pct": cfg.slippage_pct,
        "position_size_pct": cfg.position_size_pct, "force_close_at_end": cfg.force_close_at_end,
        "equity_curve": [{"timestamp": row["timestamp"], "equity": float(row["equity_close"]), "close": float(row["close_price"])} for row in daily_ledger],
        "drawdown_curve": [{"timestamp": ts.isoformat(), "drawdown": float(value)} for ts, value in drawdown.items() if ts in equity.index],
        "daily_ledger": daily_ledger,
        "executions": [x.as_dict() for x in portfolio.executions], "positions": positions,
        "events": events, "monthly_returns": monthly_returns(equity),
        "data": [{
            "timestamp": pd.Timestamp(ts).isoformat(),
            **{key: _finite(row.get(key)) for key in ["open", "high", "low", "close", "volume", "ma", "reference_ma", "atr"]},
            # The stop is an execution reference (SMA(t-1)), not the visual
            # completed-bar SMA.  It is exposed for chart/audit consumers;
            # events still identify whether it was active for a position.
            "stop": (_finite(row.get("reference_ma")) * 0.985
                      if _finite(row.get("reference_ma")) is not None else None),
            "active_stop": (
                _finite(row.get("reference_ma")) * 0.985
                if _finite(row.get("reference_ma")) is not None
                and any(start <= pd.Timestamp(ts).date() <= end for start, end in position_ranges)
                else None
            ),
            **(chart_state[i] if chart_state and i < len(chart_state) else {}),
        } for i, (ts, row) in enumerate(frame.iterrows())],
    }
    if extra:
        output.update(extra)
    return output


def _simple_parameters(period: int) -> StrategyParameters:
    return StrategyParameters(ma_type="sma", ma_period=period, breakout_trigger_pct=1.0,
                              entry_stop_pct=1.5, exit_below_ma_pct=1.5)


def _run_baseline(frame: pd.DataFrame, cfg: MABoxConfig, period: int) -> dict[str, Any]:
    p = _simple_parameters(period)
    policy = execution_policy("ohlc_heuristic")
    recorder = EventRecorder()
    strategy = SimpleMABreakout(p, recorder, policy)
    portfolio = Portfolio(cfg.initial_capital, cfg.commission_pct, cfg.slippage_pct)
    exposure_days = 0
    daily_ledger: list[dict[str, Any]] = []
    for idx, (ts, row) in enumerate(frame.iterrows()):
        bar = Bar(pd.Timestamp(ts).to_pydatetime(), *(float(row[x]) for x in ["open", "high", "low", "close", "volume"]))
        before = portfolio.quantity
        execution_start = len(portfolio.executions)
        ref_ma = float(row["reference_ma"])
        entry_level = ref_ma * 1.015
        entry_raw = max(bar.open, entry_level)
        buy_qty = initial_quantity(portfolio.equity(bar.open), cfg.position_size_pct, entry_raw, cfg.slippage_pct, cfg.commission_pct)

        def fill(side: str, raw: float, qty: int, event_type: str, reason: str, timestamp: datetime) -> None:
            if side == "BUY":
                portfolio.buy(timestamp, raw, qty, event_type, reason)
            else:
                portfolio.sell(timestamp, raw, qty, event_type, reason)

        strategy.process_bar(bar, ref_ma, portfolio.quantity, buy_qty, fill)
        strategy.end_day()
        if idx == len(frame) - 1 and portfolio.quantity and cfg.force_close_at_end:
            before_force_close = portfolio.quantity
            force_execution = portfolio.sell(bar.timestamp, bar.close, portfolio.quantity, "FINAL_EXIT", "FORCED_END_OF_TEST_EXIT")
            strategy.state.state = StrategyState.CLOSED
            recorder.add(timestamp=bar.timestamp, reference_ma=ref_ma, event="FORCED_END_OF_TEST_EXIT",
                         trigger=bar.close, current=force_execution.price, before_qty=before_force_close,
                         after_qty=0, before_state=StrategyState.LONG_NORMAL, after_state=StrategyState.CLOSED)
        if before or portfolio.quantity or any(x.side == "BUY" for x in portfolio.executions[execution_start:]):
            exposure_days += 1
        # Snapshot only after all executions and the completed-close work for
        # this session.  This is the immutable source for historical equity.
        daily_ledger.append(_ledger_row(ts, row, portfolio, setup_state="TREND_ELIGIBLE"))
    events = []
    baseline_position_sequence = 0
    baseline_active_position_id: str | None = None
    for event_index, item in enumerate(recorder.events, start=1):
        row = dict(item.as_dict())
        row["reason_code"] = "MA_STOP_EXIT" if row["event"] == "MA_EXIT" else row["event"]
        row["strategy_revision"] = "MA_LONG_BASELINE"
        row["event_id"] = f"MA_LONG_BASELINE-{period}-{event_index:05d}"
        row["date"] = _date(row["timestamp"])
        row["phase"] = row.get("metadata", {}).get("phase", "INTRADAY")
        row["sma_period"] = period
        frame_row = frame.loc[pd.Timestamp(row["timestamp"])] if pd.Timestamp(row["timestamp"]) in frame.index else None
        row["visual_ma"] = _finite(frame_row.get("ma")) if frame_row is not None else None
        row["execution_ma"] = row.get("daily_reference_ma")
        if frame_row is not None:
            for field_name in ("open", "high", "low", "close"):
                row[field_name] = _finite(frame_row.get(field_name))
        row["position_state_before"] = "LONG_POSITION" if row.get("position_before", 0) else "FLAT"
        row["position_state_after"] = "LONG_POSITION" if row.get("position_after", 0) else "FLAT"
        row["setup_state_before"] = "TREND_ELIGIBLE"
        row["setup_state_after"] = "TREND_ELIGIBLE"
        row["source_cutoff"] = row["timestamp"]
        if row["event"] == "ENTRY_STOP_FILLED":
            baseline_position_sequence += 1
            baseline_active_position_id = f"position-{baseline_position_sequence}"
        row["position_id"] = baseline_active_position_id
        row["planned_entry"] = row.get("trigger_price") if row["event"] == "ENTRY_STOP_FILLED" else None
        row["stop"] = row.get("trigger_price") if row["event"] == "MA_EXIT" else None
        event_ts = pd.Timestamp(row["timestamp"])
        if row["event"] in {"ENTRY_STOP_FILLED", "MA_EXIT", "FORCED_END_OF_TEST_EXIT"}:
            side = "BUY" if row["event"] == "ENTRY_STOP_FILLED" else "SELL"
            execution = next((item for item in portfolio.executions
                               if item.side == side and pd.Timestamp(item.timestamp) == event_ts), None)
            if execution is not None:
                row["raw_fill"] = execution.price / (1 + cfg.slippage_pct / 100) if side == "BUY" else execution.price / (1 - cfg.slippage_pct / 100)
                row["actual_fill"] = execution.price
                row["quantity"] = execution.quantity
                row["commission"] = execution.commission
                row["slippage"] = execution.slippage
        if row["event"] in {"MA_EXIT", "FORCED_END_OF_TEST_EXIT"}:
            baseline_active_position_id = None
        events.append(row)
    return _result_from_track(track="MA_LONG_BASELINE", period=period, cfg=cfg, frame=frame, portfolio=portfolio, events=events, exposure_days=exposure_days,
                              daily_ledger=daily_ledger)


def _run_buy_hold(frame: pd.DataFrame, cfg: MABoxConfig) -> dict[str, Any]:
    portfolio = Portfolio(cfg.initial_capital, cfg.commission_pct, cfg.slippage_pct)
    first = frame.iloc[0]
    qty = initial_quantity(portfolio.cash, cfg.position_size_pct, float(first["open"]), cfg.slippage_pct, cfg.commission_pct)
    portfolio.buy(pd.Timestamp(frame.index[0]).to_pydatetime(), float(first["open"]), qty, "BUY_AND_HOLD_ENTRY", "BUY_AND_HOLD_ENTRY")
    daily_ledger: list[dict[str, Any]] = []
    for idx, (ts, row) in enumerate(frame.iterrows()):
        if idx == len(frame) - 1 and cfg.force_close_at_end and portfolio.quantity:
            portfolio.sell(pd.Timestamp(ts).to_pydatetime(), float(row["close"]), portfolio.quantity,
                           "BUY_AND_HOLD_EXIT", "FORCED_END_OF_TEST_EXIT")
        daily_ledger.append(_ledger_row(ts, row, portfolio, setup_state="TREND_ELIGIBLE"))
    return _result_from_track(track="BUY_AND_HOLD", period=0, cfg=cfg, frame=frame, portfolio=portfolio, events=[], exposure_days=len(frame),
                              daily_ledger=daily_ledger)


def _buy_for_custom(portfolio: Portfolio, cfg: MABoxConfig, row: pd.Series, ts: Any, reason: str, stop: float) -> tuple[Execution, float]:
    actual = float(row["open"]) * (1 + cfg.slippage_pct / 100)
    risk = (actual - stop) / actual if actual else math.inf
    qty = initial_quantity(portfolio.equity(float(row["open"])), cfg.position_size_pct, float(row["open"]), cfg.slippage_pct, cfg.commission_pct)
    return portfolio.buy(pd.Timestamp(ts).to_pydatetime(), float(row["open"]), qty, "ENTRY", reason), risk


def _run_box(frame: pd.DataFrame, cfg: MABoxConfig, period: int, baseline: dict[str, Any]) -> dict[str, Any]:
    policy = execution_policy("ohlc_heuristic")
    portfolio = Portfolio(cfg.initial_capital, cfg.commission_pct, cfg.slippage_pct)
    simple = SimpleMABreakout(_simple_parameters(period), EventRecorder(), policy)
    events: list[dict[str, Any]] = []
    event_sequence = 0
    setup = "TREND_ELIGIBLE"
    box: BoxContext | None = None
    pending: dict[str, Any] | None = None
    exposure_days = 0
    daily_ledger: list[dict[str, Any]] = []
    chart_state: list[dict[str, Any]] = []
    rearm_after_i: int | None = None
    position_sequence = 0
    active_position_id: str | None = None
    # frame is already sliced to the common evaluation start; all four bars must
    # be inside this slice, so detection starts at local index three.
    eval_start_i = 0
    baseline_by_day: dict[str, dict[str, Any]] = {}
    baseline_exit_by_day: dict[str, list[dict[str, Any]]] = {}
    for position in baseline.get("positions", []):
        baseline_by_day[_date(position["entry_date"])] = position
        if position.get("final_exit_date"):
            baseline_exit_by_day.setdefault(_date(position["final_exit_date"]), []).append(position)
    counterfactuals: list[dict[str, Any]] = []
    counterfactual_ids: set[str] = set()

    def append(reason: str, ts: Any, before_setup: str, after_setup: str, row: pd.Series,
               trigger: float | None = None, phase: str = "CLOSE", metadata: dict[str, Any] | None = None,
               raw: float | None = None, actual: float | None = None,
               position_before_qty: int | None = None, position_id: str | None = None) -> None:
        if before_setup != after_setup and after_setup not in ALLOWED_SETUP_TRANSITIONS.get(before_setup, set()):
            raise RuntimeError(f"invalid MA_BOX_LONG_V1 setup transition: {before_setup} -> {after_setup}")
        if position_before_qty is None:
            position_before_qty = day_position_before
        nonlocal event_sequence
        event_sequence += 1
        events.append(_event(ts=ts, period=period, reason=reason, setup_before=before_setup,
                             setup_after=after_setup, position_before=position_before_qty, position_after=portfolio.quantity,
                             row=row, current_ma=_finite(row.get("ma")), reference_ma=_finite(row.get("reference_ma")),
                             box=box, attempt_id=box.breakout_attempt_id if box else None,
                             position_id=position_id or active_position_id,
                             phase=phase, trigger=trigger, raw_fill=raw, actual_fill=actual, metadata=metadata,
                             event_id=f"{STRATEGY_REVISION}-{period}-{event_sequence:05d}"))

    for i, (ts, row) in enumerate(frame.iterrows()):
        bar = Bar(pd.Timestamp(ts).to_pydatetime(), *(float(row[x]) for x in ["open", "high", "low", "close", "volume"]))
        ref_ma = float(row["reference_ma"])
        # Invalidation is effective after the invalidating completed bar.  A
        # flat strategy can resume the canonical normal-entry path on the
        # following session, while a live position remains orthogonal to the
        # setup state until its normal MA stop/forced exit.
        if (setup == "BOX_INVALIDATED" and box is None and portfolio.quantity == 0
                and rearm_after_i is not None and i > rearm_after_i):
            setup = "TREND_ELIGIBLE"
        # Session-start snapshot is authoritative for chart shading and
        # breakout decisions.  Any boundary update below becomes effective at
        # t+1, never retroactively on this candle.  Capture it only after the
        # previous session's invalidation/rearm transition has been applied.
        session_chart_state = {
            "box_high_effective": _finite(box.high) if box is not None else None,
            "box_low_effective": _finite(box.low) if box is not None else None,
            "box_id": box.box_id if box is not None else None,
            "setup_state": setup,
        }
        before_setup = setup
        day_position_before = portfolio.quantity
        had_position = portfolio.quantity > 0
        box_blocked_entry = setup == "BOX_ACTIVE" and portfolio.quantity == 0
        bought_today = False
        consumed_box_today = False

        # Pending direct/retest actions are evaluated at the next Open.
        if pending is not None and portfolio.quantity == 0:
            stop = float(pending["stop"])
            stage_b = evaluate_box_execution_gate(bar.open, stop, cfg.slippage_pct)
            actual = float(stage_b["actual_entry"])
            risk = float(stage_b["risk_distance"])
            if actual > stop and risk <= 0.05:
                reason = "BOX_DIRECT_BREAKOUT_ENTRY" if pending["kind"] == "direct" else "BOX_BREAKOUT_RETEST_ENTRY"
                execution, _ = _buy_for_custom(portfolio, cfg, row, ts, reason, stop)
                bought_today = True
                consumed_box_today = True
                position_sequence += 1
                active_position_id = f"position-{position_sequence}"
                setup = "BOX_INVALIDATED"
                if box:
                    append(reason, ts, before_setup, setup, row, trigger=stop, phase="OPEN", raw=float(row["open"]), actual=execution.price,
                           metadata={"risk_distance": risk, "stop": stop, "entry_kind": pending["kind"],
                                     "planned_entry": float(row["open"]), "quantity": execution.quantity,
                                     "commission": execution.commission, "slippage": execution.slippage})
                    append("BOX_CONSUMED_BY_ENTRY", ts, setup, setup, row, trigger=stop, phase="CLOSE",
                           position_before_qty=portfolio.quantity,
                           metadata={"reason": "BOX_CONSUMED_BY_ENTRY", "consuming_position": True})
                box = None
                pending = None
                rearm_after_i = i
                simple.state.state = StrategyState.LONG_NORMAL
            else:
                reason = str(stage_b["reason"])
                pending = None
                setup = "WAIT_RETEST"
                append(reason, ts, before_setup, setup, row, trigger=stop, phase="OPEN", metadata={"actual_entry": actual, "stop": stop, "risk_distance": risk})
                append("WAIT_RETEST", ts, setup, setup, row, phase="OPEN",
                       metadata={"cause": reason, "actual_entry": actual,
                                 "stop": stop, "risk_distance": risk})

        # Existing position and a newly bought position always use the
        # authoritative canonical stop. For a newly bought custom entry, call
        # the canonical Simple strategy in position mode to preserve exact
        # OHLC-heuristic same-day stop ordering.
        if portfolio.quantity > 0:
            qty_before = portfolio.quantity

            def fill(side: str, raw: float, qty: int, event_type: str, reason: str, timestamp: datetime) -> None:
                if side == "BUY":
                    portfolio.buy(timestamp, raw, qty, event_type, reason)
                else:
                    portfolio.sell(timestamp, raw, qty, event_type, reason)

            simple.process_bar(bar, ref_ma, portfolio.quantity, 0, fill)
            simple.end_day()
            if qty_before and not portfolio.quantity:
                execution = portfolio.executions[-1]
                append("MA_STOP_EXIT", ts, setup, setup, row, trigger=ref_ma * 0.985, phase="INTRADAY",
                       raw=policy.downward_fill(bar.open, ref_ma * 0.985), actual=execution.price,
                       position_before_qty=qty_before,
                       metadata={"stop": ref_ma * 0.985, "quantity": execution.quantity,
                                 "commission": execution.commission, "slippage": execution.slippage})
                active_position_id = None
        elif pending is None and setup == "TREND_ELIGIBLE":
            # Use the canonical Simple implementation for the non-box path.
            execution_start = len(portfolio.executions)
            entry_level = ref_ma * 1.015
            entry_raw = max(bar.open, entry_level)
            buy_qty = initial_quantity(portfolio.equity(bar.open), cfg.position_size_pct, entry_raw, cfg.slippage_pct, cfg.commission_pct)

            def fill(side: str, raw: float, qty: int, event_type: str, reason: str, timestamp: datetime) -> None:
                if side == "BUY":
                    portfolio.buy(timestamp, raw, qty, event_type, reason)
                else:
                    portfolio.sell(timestamp, raw, qty, event_type, reason)

            simple.process_bar(bar, ref_ma, portfolio.quantity, buy_qty, fill)
            simple.end_day()
            buy_execution = next((x for x in portfolio.executions[execution_start:] if x.side == "BUY"), None)
            if buy_execution is not None:
                position_sequence += 1
                active_position_id = f"position-{position_sequence}"
                append("NORMAL_MA_ENTRY", ts, setup, setup, row, trigger=entry_level, phase="INTRADAY", raw=entry_level,
                       actual=buy_execution.price, metadata={"planned_entry": entry_level,
                       "quantity": buy_execution.quantity, "commission": buy_execution.commission,
                       "slippage": buy_execution.slippage})
                bought_today = True
                same_day_exit = next((x for x in portfolio.executions[execution_start:] if x.side == "SELL"), None)
                if same_day_exit is not None:
                    stop_level = ref_ma * 0.985
                    raw_stop = same_day_exit.price / (1 - cfg.slippage_pct / 100)
                    append("MA_STOP_EXIT", ts, setup, setup, row, trigger=stop_level, phase="INTRADAY",
                           raw=raw_stop, actual=same_day_exit.price, position_before_qty=buy_execution.quantity,
                           metadata={"stop": stop_level, "quantity": same_day_exit.quantity,
                                     "commission": same_day_exit.commission, "slippage": same_day_exit.slippage})
                    active_position_id = None
            else:
                decision = evaluate_entry_zone(bar_open=bar.open, bar_high=bar.high, reference_ma=ref_ma, breakout_trigger_pct=1.0, entry_stop_pct=1.5)
                if decision.missed:
                    append("ENTRY_ZONE_MISSED", ts, setup, setup, row, trigger=decision.upper_entry, phase="INTRADAY", metadata={"lower_entry": decision.lower_entry, "upper_entry": decision.upper_entry, "open": bar.open})
        # If the box blocked a baseline entry, retain the exact baseline trade
        # as a shadow object. It is never booked to this portfolio.
        if box_blocked_entry and _date(ts) in baseline_by_day:
            shadow = dict(baseline_by_day[_date(ts)])
            source_position_id = str(shadow.get("position_id", shadow.get("entry_date", _date(ts))))
            # Counterfactuals are an execution-level view of the authoritative
            # baseline position.  Keep the explicit names required by the
            # persistence/API contract while preserving the baseline fields
            # used by existing consumers.
            shadow.update({
                "counterfactual_trade_id": f"counterfactual-{source_position_id}",
                "source_baseline_position_id": source_position_id,
                "sma_period": period,
                "entry_quantity": int(shadow.get("entry_quantity", shadow.get("initial_shares", 0))),
                "exit_reason": shadow.get("exit_reason", shadow.get("exit_final_close_reason")),
                "mfe": shadow.get("mfe", shadow.get("maximum_favorable_excursion")),
                "mae": shadow.get("mae", shadow.get("maximum_adverse_excursion")),
            })
            shadow["reason_code"] = "FILTERED_BY_BOX"
            counterfactuals.append(shadow)
            shadow_id = source_position_id
            counterfactual_ids.add(shadow_id)
            append("FILTERED_BY_BOX", ts, setup, setup, row, phase="CLOSE",
                   metadata={"counterfactual_entry": shadow.get("entry_date")})
            append("COUNTERFACTUAL_ENTRY", ts, setup, setup, row, phase="CLOSE",
                   metadata={"position_id": shadow_id, "baseline_position": shadow})

        # Counterfactual exits are reporting-only audit events.  They are
        # emitted on the baseline's actual exit session and never touch the
        # MA_BOX portfolio, position, cash or equity ledger.
        for shadow in baseline_exit_by_day.get(_date(ts), []):
            shadow_id = str(shadow.get("position_id", shadow.get("entry_date", _date(ts))))
            if shadow_id in counterfactual_ids:
                append("COUNTERFACTUAL_EXIT", ts, setup, setup, row, phase="CLOSE",
                       metadata={"position_id": shadow_id, "baseline_position": shadow})

        # Completed-close state machine. A newly bought position consumes the
        # box and cannot create a retroactive box on the same close.
        # A box-consumed entry must not recreate or update its just-consumed
        # box on the same completed close.  A normal MA entry, however, does
        # not suppress end-of-day entanglement detection: the box becomes
        # active on the next session and LONG_POSITION + BOX_ACTIVE is valid.
        if consumed_box_today:
            pass
        elif box is None and setup in {"TREND_ELIGIBLE", "BOX_INVALIDATED"}:
            formation = _entanglement(frame, i, eval_start_i)
            if formation:
                indices, qualifying = formation
                if rearm_after_i is not None and not all(j > rearm_after_i for j in qualifying):
                    formation = None
                if formation is not None:
                    new_box = _initial_box(frame, indices, qualifying, period, cfg.atr_period, cfg.boundary_contact_tolerance_multiplier)
                    if new_box is None:
                        append("BOX_FORMING_NOT_READY_ATR", ts, setup, setup, row, metadata={"atr_period": cfg.atr_period, "tolerance_multiplier": cfg.boundary_contact_tolerance_multiplier})
                    else:
                        box = new_box
                        setup = "BOX_FORMING"
                        append("MA_ENTANGLEMENT_START", ts, before_setup, "BOX_FORMING", row,
                               position_before_qty=portfolio.quantity,
                               metadata={"formation_indices": qualifying, "formation_dates": new_box.formation_dates})
                        setup = "BOX_ACTIVE"
                        append("BOX_ACTIVE", ts, "BOX_FORMING", setup, row,
                               position_before_qty=portfolio.quantity,
                               metadata={"initial_box": new_box.snapshot()})
        elif box is not None and setup == "BOX_ACTIVE":
            box_high, box_low = box.high, box.low
            if float(row["close"]) > box_high:
                box.breakout_attempt_id = f"attempt-{period}-{i}"
                box.breakout_index = i
                box.breakout_box_high = box_high
                stop_next = float(row["ma"]) * 0.985
                box.breakout_stop = stop_next
                append("BOX_UP_BREAKOUT", ts, setup, "BREAKOUT_CONFIRMED", row, trigger=box_high, metadata={"box_high_snapshot": box_high, "stop_next": stop_next})
                stage_a = evaluate_box_structural_gate(box_high, stop_next)
                box_risk = float(stage_a["risk_distance"])
                if bool(stage_a["eligible"]) and portfolio.quantity == 0:
                    setup = "DIRECT_ENTRY_ELIGIBLE"
                    pending = {"kind": "direct", "stop": stop_next, "signal_index": i}
                    append("DIRECT_ENTRY_ELIGIBLE", ts, "BREAKOUT_CONFIRMED", setup, row,
                           metadata={"box_risk_distance": box_risk, "risk_distance": box_risk,
                                     "stop": stop_next, "pending": True})
                elif portfolio.quantity > 0:
                    setup = "BOX_INVALIDATED"
                    append("NO_ENTRY_ALREADY_LONG", ts, "BREAKOUT_CONFIRMED", setup, row,
                           metadata={"box_risk_distance": box_risk, "risk_distance": box_risk,
                                     "stop": stop_next})
                    box = None
                    rearm_after_i = i
                else:
                    setup = "WAIT_RETEST"
                    reason = str(stage_a["reason"])
                    append(reason, ts, "BREAKOUT_CONFIRMED", setup, row,
                           metadata={"box_risk_distance": box_risk, "risk_distance": box_risk,
                                     "stop": stop_next})
                    append("WAIT_RETEST", ts, setup, setup, row,
                           metadata={"cause": reason, "box_risk_distance": box_risk,
                                     "risk_distance": box_risk, "stop": stop_next})
            elif float(row["close"]) < box_low:
                append("BOX_DOWN_BREAK", ts, setup, "BEAR_BOX_BREAK", row, trigger=box_low)
                setup = "BOX_INVALIDATED"
                append("BOX_INVALIDATED", ts, "BEAR_BOX_BREAK", setup, row, trigger=box_low)
                box = None
                rearm_after_i = i
            else:
                # Boundary update uses only the bar after testing both breaks.
                new_contacts: list[Contact] = []
                current_ma = float(row["ma"])
                new_contacts.extend(_contacts_for_bar(i, ts, row, current_ma, box.midpoint, "upper"))
                new_contacts.extend(_contacts_for_bar(i, ts, row, current_ma, box.midpoint, "lower"))
                box.contacts.extend(new_contacts)
                old_high, old_low = box.high, box.low
                upper_points = [x for x in box.contacts if x.side == "upper"]
                lower_points = [x for x in box.contacts if x.side == "lower"]
                upper = _best_evidence(upper_points, box.upper_evidence or BoundaryEvidence(old_high), box.tolerance, "upper")
                lower = _best_evidence(lower_points, box.lower_evidence or BoundaryEvidence(old_low), box.tolerance, "lower")
                updates = []
                if _strictly_improves_boundary(upper, box.upper_evidence) and upper.level > box.low:
                    box.high = upper.level; box.upper_evidence = upper
                    updates.append({"side": "upper", "old": old_high, "new": box.high, "evidence": upper.as_dict()})
                if _strictly_improves_boundary(lower, box.lower_evidence) and lower.level < box.high:
                    box.low = lower.level; box.lower_evidence = lower
                    updates.append({"side": "lower", "old": old_low, "new": box.low, "evidence": lower.as_dict()})
                if box.high <= box.low:
                    box.high, box.low = old_high, old_low
                    updates = []
                if updates:
                    update = {
                        "date": _date(ts), "tolerance": box.tolerance,
                        "updates": updates, "reason": "CONTACT_COUNT_SUPERIOR",
                        # Keep the top-level audit fields aligned with the
                        # per-side update records.  Consumers can therefore
                        # reconstruct the exact session-start boundary and
                        # the boundary that becomes effective on t+1.
                        "BoxHigh_before": old_high, "BoxHigh_after": box.high,
                        "BoxLow_before": old_low, "BoxLow_after": box.low,
                        "supporting_contacts": [item["evidence"] for item in updates],
                    }
                    box.boundary_updates.append(update)
                    append("BOX_BOUNDARY_UPDATE", ts, setup, setup, row, metadata=update)
        elif box is not None and setup == "WAIT_RETEST":
            close, low = float(row["close"]), float(row["low"])
            if close < box.low:
                append("BOX_DOWN_BREAK", ts, setup, "BEAR_BOX_BREAK", row, trigger=box.low)
                setup = "BOX_INVALIDATED"
                append("BOX_INVALIDATED", ts, "BEAR_BOX_BREAK", setup, row, trigger=box.low)
                box = None; pending = None; rearm_after_i = i
            elif low <= float(row["ma"]) and close > float(row["ma"]):
                setup = "RETEST_CONFIRMED"
                append("MA_RETEST_TOUCH", ts, "WAIT_RETEST", setup, row, trigger=float(row["ma"]))
                append("MA_RETEST_REBOUND", ts, setup, setup, row, trigger=float(row["ma"]))
                pending = {"kind": "retest", "stop": float(row["ma"]) * 0.985, "signal_index": i}
            elif close <= box.high:
                setup = "FAILED_BREAKOUT"
                append("FAILED_BOX_BREAKOUT", ts, "WAIT_RETEST", setup, row, trigger=box.high)
                pending = None
                setup = "BOX_ACTIVE"
                append("BOX_REACTIVATED", ts, "FAILED_BREAKOUT", setup, row, trigger=box.high)
        # Revision 3 deliberately has no WAIT_RETEST -> new-box supersession
        # branch.  A new lifecycle can begin only after an actual invalidation
        # has returned the setup to TREND_ELIGIBLE.

        # Final-session close/forced exit is part of this session's ledger,
        # not a post-simulation reconstruction.
        if i == len(frame) - 1:
            if portfolio.quantity and cfg.force_close_at_end:
                before_force_close = portfolio.quantity
                force_execution = portfolio.sell(bar.timestamp, bar.close, portfolio.quantity, "FINAL_EXIT", "FORCED_END_OF_TEST_EXIT")
                append("FORCED_END_OF_TEST_EXIT", ts, setup, setup, row, phase="CLOSE", raw=float(row["close"]), actual=force_execution.price,
                       position_before_qty=before_force_close,
                       metadata={"quantity": force_execution.quantity, "commission": force_execution.commission,
                                 "slippage": force_execution.slippage})
                active_position_id = None
            elif pending is not None or setup == "WAIT_RETEST":
                append("STUDY_END_UNFILLED", ts, setup, setup, row, metadata={"pending": bool(pending)})
        if portfolio.quantity or had_position or bought_today:
            exposure_days += 1
        daily_ledger.append(_ledger_row(ts, row, portfolio, setup_state=setup))
        chart_state.append(session_chart_state)

    extra = {"box_context": {"last_box": box.snapshot() if box else None, "boxes": _box_history(events)}, "counterfactual_trades": counterfactuals,
             "boundary_tolerance": {"mode": cfg.boundary_contact_tolerance_mode, "atr_period": cfg.atr_period, "multiplier": cfg.boundary_contact_tolerance_multiplier}}
    result = _result_from_track(track="MA_BOX_LONG_V1", period=period, cfg=cfg, frame=frame, portfolio=portfolio, events=events, exposure_days=exposure_days,
                                daily_ledger=daily_ledger, chart_state=chart_state, extra=extra)
    result["counterfactual_summary"] = _counterfactual_summary(counterfactuals)
    return result


def _box_history(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build a read-only lifecycle index for chart consumers from audit events."""
    by_id: dict[str, dict[str, Any]] = {}
    for event in events:
        box_id = event.get("box_id")
        if not box_id:
            continue
        metadata = event.get("metadata") or {}
        item = by_id.setdefault(str(box_id), {
            "box_id": str(box_id), "start_date": event.get("date"), "end_date": event.get("date"),
            "BoxHigh": event.get("BoxHigh"), "BoxLow": event.get("BoxLow"),
            "tolerance": event.get("tolerance"), "formation_dates": metadata.get("formation_dates", []),
            "updates": [], "invalidated": False,
        })
        item["end_date"] = event.get("date") or item["end_date"]
        if event.get("BoxHigh") is not None:
            item["BoxHigh"] = event.get("BoxHigh")
        if event.get("BoxLow") is not None:
            item["BoxLow"] = event.get("BoxLow")
        if event.get("reason_code") == "BOX_BOUNDARY_UPDATE":
            item["updates"].append(metadata)
        if event.get("reason_code") in {"BOX_INVALIDATED", "BOX_CONSUMED_BY_ENTRY"}:
            item["invalidated"] = True
    return list(by_id.values())


def _counterfactual_summary(trades: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [float(x.get("net_pnl", 0)) for x in trades]
    gross = [float(x.get("gross_pnl", 0)) for x in trades]
    return {
        "filtered_count": len(trades), "avoided_losing_trades": sum(x < 0 for x in pnls),
        "missed_winning_trades": sum(x > 0 for x in pnls), "breakeven_trades": sum(x == 0 for x in pnls),
        "avoided_gross_loss": abs(sum(x for x in gross if x < 0)),
        "missed_gross_gain": sum(x for x in gross if x > 0),
        "net_counterfactual_effect": -sum(pnls),
    }


def _local_robustness(runs: dict[str, dict[str, Any]], periods: list[int], selected_ma: int) -> dict[str, Any]:
    """Return the frozen local-radius robustness contract.

    A radius is complete only when every expected integer period was actually
    run.  Incomplete radii are explicitly unavailable rather than silently
    summarized from a smaller set.
    """
    metrics = ("total_return", "cagr", "max_drawdown", "calmar_ratio", "exposure_pct", "number_of_positions")
    output: dict[str, Any] = {"selected_ma": selected_ma, "periods": periods, "metrics": {}, "radii": {}}
    available_set = set(periods)
    for metric in metrics:
        values: list[dict[str, Any]] = []
        finite: list[float] = []
        for period in periods:
            raw = runs[str(period)]["MA_BOX_LONG_V1"]["summary"].get(metric)
            value = _finite(raw)
            values.append({"period": period, "value": value})
            if value is not None:
                finite.append(value)
        output["metrics"][metric] = {
            "values": values,
            "median": float(np.median(finite)) if finite else None,
            "min": float(min(finite)) if finite else None,
            "max": float(max(finite)) if finite else None,
        }
    for radius in (1, 2, 3, 5):
        expected = list(range(max(2, selected_ma - radius), min(500, selected_ma + radius) + 1))
        available = [period for period in expected if period in available_set and str(period) in runs]
        status = "COMPLETE" if available == expected else "UNAVAILABLE_PERIODS_NOT_RUN"
        radius_metrics: dict[str, Any] = {}
        for metric in ("total_return", "cagr", "max_drawdown", "calmar_ratio"):
            # A partial radius is explicitly unavailable.  Do not expose
            # medians/minima/maxima computed from an incomplete neighbourhood,
            # because consumers could accidentally treat them as a complete
            # robustness summary.  The available/expected lists remain in the
            # payload for transparent diagnostics.
            finite = [] if status != "COMPLETE" else [
                value for period in available
                if (value := _finite(runs[str(period)]["MA_BOX_LONG_V1"]["summary"].get(metric))) is not None
            ]
            radius_metrics[metric] = {
                "median": float(np.median(finite)) if finite else None,
                "min": float(min(finite)) if finite else None,
                "max": float(max(finite)) if finite else None,
            }
        output["radii"][str(radius)] = {
            "radius": radius,
            "available_periods": available,
            "expected_periods": expected,
            "status": status,
            "metrics": radius_metrics,
        }
    return output


def _common_frame(daily: pd.DataFrame, cfg: MABoxConfig) -> tuple[pd.DataFrame, int, list[int]]:
    raw = _frame(daily)
    periods = cfg.periods()
    out = raw.copy()
    out["ma"] = moving_average(out["close"], max(periods), "sma")
    # Recalculate each requested MA for run-local values; the common start only
    # needs to find the latest valid reference for every requested period.
    for period in periods:
        out[f"ma_{period}"] = moving_average(out["close"], period, "sma")
        out[f"ref_{period}"] = out[f"ma_{period}"].shift(1)
    out["atr"] = wilder_atr(out, cfg.atr_period)
    requested = out[(out.index.date >= cfg.start_date) & (out.index.date <= cfg.end_date)]
    if requested.empty:
        raise ValueError("No daily bars overlap the requested period")
    valid = requested.dropna(subset=[f"ref_{p}" for p in periods])
    if valid.empty:
        raise ValueError("Not enough MA lookback for the requested nearby range")
    start_ts = valid.index[0]
    start_pos = int(out.index.get_loc(start_ts))
    # Use maximum-period MA as the canonical columns for initial slicing; each
    # period is copied into its own run below.
    return out, start_pos, periods


def run_ma_box_study(daily: pd.DataFrame, config: MABoxConfig, *, provider: str = "synthetic",
                     data_fingerprint: str | None = None, spec_hash: str | None = None) -> dict[str, Any]:
    frozen_values = {
        "initial_capital": 100_000.0, "position_size_pct": 100.0,
        "commission_pct": 0.05, "slippage_pct": 0.02,
        "force_close_at_end": True, "ma_type": "sma", "atr_period": 14,
        "boundary_contact_tolerance_mode": "ATR_NORMALIZED",
        "boundary_contact_tolerance_multiplier": 0.10,
    }
    for name, expected in frozen_values.items():
        if getattr(config, name) != expected:
            raise ValueError(f"MA_BOX_LONG_V1 frozen configuration mismatch: {name}")
    if config.ma_type != "sma":
        raise ValueError("MA_BOX_LONG_V1 supports SMA only")
    canonical_spec_hash = spec_sha256()
    if spec_hash is not None and spec_hash != canonical_spec_hash:
        raise ValueError("MA_BOX_LONG_V1 specification hash mismatch")
    enriched, start_pos, periods = _common_frame(daily, config)
    eval_start = enriched.index[start_pos]
    requested_end = enriched[(enriched.index.date >= config.start_date) & (enriched.index.date <= config.end_date)].index[-1]
    runs: dict[str, dict[str, Any]] = {}
    for period in periods:
        local = enriched.copy()
        local["ma"] = local[f"ma_{period}"]
        local["reference_ma"] = local[f"ref_{period}"]
        local = local.iloc[start_pos:]
        local = local[local.index <= requested_end].dropna(subset=["ma", "reference_ma"])
        baseline = _run_baseline(local, config, period)
        box = _run_box(local, config, period, baseline)
        runs[str(period)] = {"MA_LONG_BASELINE": baseline, "MA_BOX_LONG_V1": box}
    bh_frame = enriched.iloc[start_pos:]
    bh_frame = bh_frame[bh_frame.index <= requested_end]
    bh = _run_buy_hold(bh_frame, config)
    config_payload = config.as_dict()
    config_hash = config_sha256(config, spec_hash=canonical_spec_hash, data_fingerprint=data_fingerprint)
    selected = runs[str(config.selected_ma)] if str(config.selected_ma) in runs else None
    for bundle in runs.values():
        for track, run in bundle.items():
            # Keep the track identity visible in persisted provenance.  The
            # study revision remains MA_BOX_LONG_V1, while the independent
            # baseline ledger retains its own explicit revision.
            run_revision = "MA_LONG_BASELINE" if track == "MA_LONG_BASELINE" else STRATEGY_REVISION
            run.update({"strategy_revision": run_revision, "spec_revision": SPEC_REVISION,
                        "spec_revision_number": SPEC_REVISION_NUMBER,
                        "spec_hash": canonical_spec_hash, "config_hash": config_hash,
                        "data_fingerprint": data_fingerprint})
            for event in run.get("events", []):
                event.update({"spec_revision": SPEC_REVISION,
                              "spec_revision_number": SPEC_REVISION_NUMBER,
                              "spec_hash": canonical_spec_hash,
                              "config_hash": config_hash, "data_fingerprint": data_fingerprint})
            for trade in run.get("counterfactual_trades", []):
                trade.update({"spec_revision": SPEC_REVISION,
                              "spec_revision_number": SPEC_REVISION_NUMBER,
                              "spec_hash": canonical_spec_hash,
                              "config_hash": config_hash, "data_fingerprint": data_fingerprint})
    bh.update({"strategy_revision": "BUY_AND_HOLD", "spec_revision": SPEC_REVISION,
               "spec_revision_number": SPEC_REVISION_NUMBER,
               "spec_hash": canonical_spec_hash, "config_hash": config_hash,
               "data_fingerprint": data_fingerprint})
    return {
        "study_revision": STRATEGY_REVISION, "spec_revision": SPEC_REVISION,
        "spec_revision_number": SPEC_REVISION_NUMBER, "spec_hash": canonical_spec_hash,
        "config_hash": config_hash, "config": config_payload, "canonical_engine": True,
        "data_provenance": {"ticker": config.ticker.upper(), "provider": provider, "fingerprint": data_fingerprint,
                             "data_start": _date(enriched.index[0]), "data_end": _date(enriched.index[-1]),
                             "evaluation_start": _date(eval_start), "evaluation_end": _date(requested_end),
                             "bars": int(len(enriched))},
        "evaluation_start": _date(eval_start), "evaluation_end": _date(requested_end),
        "periods": periods, "selected_ma": config.selected_ma, "buy_and_hold": bh,
        "runs": runs,
        "local_robustness": _local_robustness(runs, periods, config.selected_ma),
        "selected_summary": {
            "baseline": selected["MA_LONG_BASELINE"]["summary"] if selected else None,
            "box": selected["MA_BOX_LONG_V1"]["summary"] if selected else None,
            "buy_and_hold": bh["summary"],
        },
    }
