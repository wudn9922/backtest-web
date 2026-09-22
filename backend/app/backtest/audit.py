from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from app.backtest.models import BacktestRequest, Execution, Event, StrategyName
from app.backtest.strategies import AdvancedMABreakout
from app.backtest.strategies.base import Bar
from app.backtest.validation_audit import is_close_validation


def _number(value: Any) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def _state_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def capture_strategy_snapshot(strategy: Any, quantity: int) -> dict[str, Any]:
    if isinstance(strategy, AdvancedMABreakout):
        state = strategy.s
        return {
            "state": _state_value(state.state),
            "quantity": quantity,
            "q0": state.q0,
            "entry_price": state.entry_price,
            "entry_day": state.entry_day.isoformat() if state.entry_day else None,
            "first_tp_triggered": state.first_tp_triggered,
            "break_day_low": state.break_day_low,
            "break_day": state.break_day.isoformat() if state.break_day else None,
            "bias_extreme_active": state.bias_extreme_active,
            "atr_extreme_active": state.atr_extreme_active,
        }
    return {
        "state": _state_value(strategy.state.state),
        "quantity": quantity,
        "q0": None,
        "entry_price": None,
        "entry_day": None,
        "first_tp_triggered": False,
        "break_day_low": None,
        "break_day": None,
        "bias_extreme_active": False,
        "atr_extreme_active": False,
    }


def _fresh_position_open_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return the audit-visible state at the start of a newly opened position.

    ``AdvancedMABreakout`` deliberately keeps the last closed position's
    dataclass instance until a new entry is armed.  That is safe for strategy
    execution, but the engine captures an audit snapshot just before processing
    the entry bar.  Consequently, copying that raw snapshot into the new
    position's inspector would leak fields such as ``first_tp_triggered`` and
    ``break_day_low`` from the predecessor.

    This is an audit boundary only: it never reaches the strategy or portfolio.
    A position that opens on the current bar starts with its own clean runtime
    state, regardless of the prior closed position's residual state.
    """
    return {
        **snapshot,
        "state": "FLAT",
        "quantity": 0,
        "q0": None,
        "entry_price": None,
        "entry_day": None,
        "first_tp_triggered": False,
        "break_day_low": None,
        "break_day": None,
        "bias_extreme_active": False,
        "atr_extreme_active": False,
    }


def _position_scoped_snapshots(
    open_snapshot: dict[str, Any],
    close_snapshot: dict[str, Any],
    executions: list[Execution],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Scope audit state to the position represented by this daily row.

    A BUY while flat creates a fresh position.  Its raw pre-bar snapshot can
    belong to a previous, already closed position, so it must not participate
    in any threshold activation calculation.  The post-bar snapshot is the
    strategy's freshly reset state and remains the authoritative record for the
    new position.  Existing-position bars retain their actual open/close
    snapshots unchanged.
    """
    opened_new_position = open_snapshot.get("quantity", 0) == 0 and any(
        execution.side == "BUY" for execution in executions
    )
    if opened_new_position:
        return _fresh_position_open_snapshot(open_snapshot), close_snapshot
    return open_snapshot, close_snapshot


_EVENT_EXECUTION_TYPES: dict[str, tuple[str | None, str | None]] = {
    "ENTRY_STOP_FILLED": ("ENTRY", None),
    "BREAK_HALF_TRIGGERED": ("MA_HALF_EXIT", None),
    "FIRST_TP_TRIGGERED": ("FIRST_TP", None),
    "EXTREME_TP_EXECUTED": ("EXTREME_TP", None),
    "PROTECTIVE_STOP_TRIGGERED": ("PROTECTIVE_STOP", None),
    "DAY1_FULL_STOP": ("DAY1_FULL_STOP", "DAY1_FULL_STOP"),
    "BREAK_LOW_BROKEN": ("BREAK_LOW_EXIT", None),
    "MA_EXIT": ("FINAL_EXIT", "MA_EXIT"),
    "VOLUME_CONFIRMATION_FAIL": (None, "VOLUME_CONFIRMATION_FAIL"),
    "DAY2_CLOSE_CONFIRMATION_FAIL": (None, "DAY2_CLOSE_CONFIRMATION_FAIL"),
    "DAY2_CONFIRMATION_FAIL": (None, "DAY2_CLOSE_CONFIRMATION_FAIL"),
}

_DISPLAY_EVENTS = {
    "BREAK_HALF_TRIGGERED": "MA_BREAK_HALF_EXIT",
    "BREAK_LOW_BROKEN": "BREAK_DAY_LOW_BROKEN",
}


def _event_rows(events: list[Event], executions: list[Execution], open_snapshot: dict[str, Any], close_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    used_executions: set[int] = set()
    for event in events:
        matched: Execution | None = None
        expected = _EVENT_EXECUTION_TYPES.get(event.event)
        if expected:
            expected_type, expected_reason = expected
            for index, execution in enumerate(executions):
                if index in used_executions:
                    continue
                if expected_type is not None and execution.event_type != expected_type:
                    continue
                if expected_reason is not None and execution.reason != expected_reason:
                    continue
                matched = execution
                used_executions.add(index)
                break
        if matched:
            shares_before = matched.position_remaining - matched.quantity if matched.side == "BUY" else matched.position_remaining + matched.quantity
            shares_sold = matched.quantity if matched.side == "SELL" else 0
            shares_remaining = matched.position_remaining
        else:
            shares_before = event.position_before
            shares_sold = max(0, event.position_before - event.position_after)
            shares_remaining = event.position_after
        output.append({
            "event": _DISPLAY_EVENTS.get(event.event, event.event),
            "source_event": event.event,
            "trigger_level": event.trigger_price,
            "execution_price": matched.price if matched else None,
            "shares_before": shares_before,
            "shares_sold": shares_sold,
            "shares_remaining": shares_remaining,
            "state_before": _state_value(event.state_before),
            "state_after": _state_value(event.state_after),
            "metadata": event.metadata,
        })
    for index, execution in enumerate(executions):
        if index in used_executions:
            continue
        shares_before = execution.position_remaining - execution.quantity if execution.side == "BUY" else execution.position_remaining + execution.quantity
        output.append({
            "event": execution.reason if execution.reason else execution.event_type,
            "source_event": execution.event_type,
            "trigger_level": None,
            "execution_price": execution.price,
            "shares_before": shares_before,
            "shares_sold": execution.quantity if execution.side == "SELL" else 0,
            "shares_remaining": execution.position_remaining,
            "state_before": open_snapshot["state"],
            "state_after": close_snapshot["state"],
            "metadata": {"side": execution.side},
        })
    return output


def make_daily_audit(
    *,
    request: BacktestRequest,
    bar: Bar,
    current_ma: float | None,
    reference_ma: float,
    reference_atr: float | None,
    bias_sigma: float | None,
    previous_day_volume: float | None,
    open_snapshot: dict[str, Any],
    close_snapshot: dict[str, Any],
    events: list[Event],
    executions: list[Execution],
) -> dict[str, Any]:
    # The raw engine snapshot predates ``process_bar``.  Normalize its
    # position-local runtime values when this bar opens a fresh position, then
    # derive every displayed threshold/state from the scoped pair below.
    position_open_snapshot, position_close_snapshot = _position_scoped_snapshots(
        open_snapshot, close_snapshot, executions
    )
    p = request.parameters
    is_advanced = request.strategy != StrategyName.SIMPLE
    has_day1_stop = request.strategy == StrategyName.ADVANCED_DAY1_STOP
    source_events = {event.event for event in events}
    entry_related = "ENTRY_STOP_FILLED" in source_events or any(item.side == "BUY" for item in executions)
    entry_missed = "ENTRY_ZONE_MISSED" in source_events
    entry_relevant = entry_related or entry_missed or "BREAKOUT_TRIGGERED" in source_events
    lower_entry = reference_ma + reference_ma * p.breakout_trigger_pct / 100
    upper_entry = reference_ma + reference_ma * p.entry_stop_pct / 100
    had_position = bool(position_open_snapshot["quantity"] or position_close_snapshot["quantity"] or executions)
    entry_price = position_close_snapshot.get("entry_price") or position_open_snapshot.get("entry_price")
    first_tp_was_active = bool(
        position_open_snapshot.get("first_tp_triggered")
        or position_close_snapshot.get("first_tp_triggered")
    )
    break_low = (
        position_open_snapshot.get("break_day_low")
        if position_open_snapshot.get("break_day_low") is not None
        else position_close_snapshot.get("break_day_low")
    )

    thresholds: dict[str, float | None] = {
        "breakout_trigger": lower_entry if entry_relevant else None,
        "entry_level": upper_entry if entry_relevant else None,
        "day1_stop": reference_ma * (1 - p.day1_stop_pct / 100) if has_day1_stop and entry_related else None,
        "ma_half_stop": None,
        "break_day_low": _number(break_low),
        "first_tp_price": None,
        "protective_stop": None,
        "bias_extreme_threshold_price": None,
        "atr_extreme_threshold_price": None,
    }
    if is_advanced and had_position and entry_price is not None:
        thresholds["first_tp_price"] = float(entry_price) * (1 + p.first_tp_pct / 100)
        if not position_open_snapshot.get("first_tp_triggered") and position_open_snapshot.get("break_day_low") is None and not (has_day1_stop and entry_related):
            thresholds["ma_half_stop"] = reference_ma * (1 - p.ma_risk_pct / 100)
        if first_tp_was_active:
            thresholds["protective_stop"] = max(float(entry_price), reference_ma * (1 - p.ma_risk_pct / 100))
            if bias_sigma is not None:
                thresholds["bias_extreme_threshold_price"] = reference_ma * (1 + p.bias_sigma_multiple * bias_sigma)
            if reference_atr is not None:
                thresholds["atr_extreme_threshold_price"] = reference_ma + p.atr_multiple * reference_atr

    validations: dict[str, Any] = {"entry_day_volume": None, "day2_confirmation": None}
    volume_event = next((event for event in events if is_close_validation(
        event.event, event.metadata, "entry_day_volume"
    )), None)
    if volume_event:
        increase = None if not previous_day_volume else (bar.volume / previous_day_volume - 1) * 100
        validations["entry_day_volume"] = {
            "current_volume": bar.volume,
            "previous_day_volume": previous_day_volume,
            "increase_pct": increase,
            "required_pct": p.volume_increase_pct,
            "status": "PASS" if volume_event.event.endswith("PASS") else "FAIL",
        }
    day2_event = next((event for event in events if is_close_validation(
        event.event, event.metadata, "day2_confirmation"
    )), None)
    if day2_event:
        validations["day2_confirmation"] = {
            "day1_close": day2_event.trigger_price,
            "day2_close": day2_event.current_price,
            "status": "PASS" if day2_event.event.endswith("PASS") else "FAIL",
        }

    daily_events = _event_rows(events, executions, position_open_snapshot, position_close_snapshot)
    ambiguity_events = [item for item in daily_events if item["source_event"] == "DAILY_INTRABAR_AMBIGUITY"]
    ambiguity_policy = ambiguity_events[0]["metadata"].get("policy") if ambiguity_events else None
    chosen_path = ambiguity_events[0]["metadata"].get("chosen_path") if ambiguity_events else None
    conditions: list[str] = []
    for item in ambiguity_events:
        for condition in item["metadata"].get("simultaneous_conditions", []):
            if condition not in conditions:
                conditions.append(condition)
    return {
        "date": bar.timestamp.date().isoformat(),
        "timestamp": bar.timestamp.isoformat(),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "previous_day_ma": reference_ma,
        "current_day_ma": current_ma,
        "previous_day_atr": reference_atr,
        "bias_sigma": bias_sigma,
        "current_quantity_at_open": position_open_snapshot["quantity"],
        "current_quantity_at_close": position_close_snapshot["quantity"],
        "strategy_state_at_open": position_open_snapshot["state"],
        "strategy_state_at_close": position_close_snapshot["state"],
        "entry_zone": {
            "lower_entry": lower_entry if entry_relevant else None,
            "upper_entry": upper_entry if entry_relevant else None,
            "entry_allowed": (not entry_missed) if entry_relevant else None,
            "entry_missed": entry_missed if entry_relevant else None,
            "entry_execution_price": next((item.price for item in executions if item.side == "BUY"), None),
            "intrabar_assumption": request.execution_policy,
        },
        "thresholds": thresholds,
        "validations": validations,
        "events": daily_events,
        "ambiguity": {
            "applied": bool(ambiguity_events),
            "message": f"Daily OHLC ambiguity — {ambiguity_policy} assumption applied" if ambiguity_events else None,
            "policy": ambiguity_policy,
            "chosen_path": chosen_path,
            "simultaneous_conditions": conditions,
        },
    }


def build_position_audits(
    *,
    backtest_id: str | None,
    ticker: str,
    strategy: str,
    positions: list[dict[str, Any]],
    daily_audits: list[dict[str, Any]],
    enriched: pd.DataFrame,
    executions: list[Execution],
) -> dict[str, dict[str, Any]]:
    audits: dict[str, dict[str, Any]] = {}
    enriched_dates = [timestamp.date() for timestamp in enriched.index]
    for position in positions:
        entry_day = datetime.fromisoformat(str(position["entry_date"])).date()
        exit_day = datetime.fromisoformat(str(position["final_exit_date"])).date()
        timeline = [item for item in daily_audits if entry_day <= datetime.fromisoformat(item["timestamp"]).date() <= exit_day]
        entry_index = next(index for index, value in enumerate(enriched_dates) if value == entry_day)
        exit_index = next(index for index, value in enumerate(enriched_dates) if value == exit_day)
        threshold_by_date = {item["date"]: item["thresholds"] for item in timeline}
        chart_daily: list[dict[str, Any]] = []
        for timestamp, row in enriched.iloc[max(0, entry_index - 10): min(len(enriched), exit_index + 6)].iterrows():
            day = timestamp.date().isoformat()
            thresholds = threshold_by_date.get(day, {})
            chart_daily.append({
                "timestamp": timestamp.isoformat(),
                **{key: _number(row.get(key)) for key in ["open", "high", "low", "close", "volume", "ma", "reference_ma"]},
                "break_day_low": thresholds.get("break_day_low"),
                "day1_stop": thresholds.get("day1_stop"),
                "first_tp_price": thresholds.get("first_tp_price"),
                "protective_stop": thresholds.get("protective_stop"),
            })
        position_executions = [execution.as_dict() for execution in executions if entry_day <= execution.timestamp.date() <= exit_day]
        audits[position["position_id"]] = {
            "backtest_id": backtest_id,
            "position_id": position["position_id"],
            "ticker": ticker,
            "strategy": strategy,
            "position": position,
            "timeline": timeline,
            "chart": {"daily_data": chart_daily, "executions": position_executions},
        }
    return audits
