from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any


def classify_stop_execution(*, open_price: float, low_price: float, stop_price: float) -> dict[str, float | str | None]:
    """Describe an already-recorded daily stop without changing its execution.

    Gap-through is defined against the active stop, never against the reference
    moving average.  This helper is presentation-only and deliberately returns
    no fill when the daily range did not touch the stop.
    """
    opening, low, stop = float(open_price), float(low_price), float(stop_price)
    if opening <= stop:
        return {"trigger_type": "GAP_THROUGH", "raw_fill_price": opening}
    if low <= stop:
        return {"trigger_type": "INTRADAY_STOP", "raw_fill_price": stop}
    return {"trigger_type": "NOT_TRIGGERED", "raw_fill_price": None}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _position_was_active(day: dict[str, Any]) -> bool:
    if int(day.get("current_quantity_at_open") or 0) > 0 or int(day.get("current_quantity_at_close") or 0) > 0:
        return True
    return any(event.get("source_event") == "ENTRY_STOP_FILLED" for event in day.get("events", []))


def present_position_audit(audit: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """Return an enriched copy of a stored audit for the Inspector UI.

    Stored audit JSON, executions, strategy state, thresholds, quantities and
    historical backtest results remain byte-identical.  Only deterministic
    explanatory values derived from that audit and its saved request are added.
    """
    output = deepcopy(audit)
    request = record.get("parameters") or {}
    parameters = request.get("parameters") or {}
    strategy = str(record.get("strategy") or output.get("strategy") or "")
    slippage_pct = float(request.get("slippage_pct") or 0.0)
    is_simple = strategy == "simple"
    stop_pct = float(parameters.get("exit_below_ma_pct", 1.5) if is_simple else parameters.get("ma_risk_pct", 1.5))
    multiplier = 1.0 - stop_pct / 100.0

    output["presentation"] = {
        "ma_stop": {
            "kind": "SIMPLE_FULL_STOP" if is_simple else "ADVANCED_HALF_STOP",
            "percent_below_ma": stop_pct,
            "multiplier": multiplier,
            "formula": f"MA(t-1) × {multiplier:g}",
        },
        "sell_slippage_pct": slippage_pct,
        "source": "DERIVED_FROM_STORED_AUDIT_AND_SAVED_REQUEST",
        "persisted_audit_modified": False,
    }

    threshold_by_date: dict[str, float | None] = {}
    for day in output.get("timeline", []):
        thresholds = day.setdefault("thresholds", {})
        reference_ma = _number(day.get("previous_day_ma"))
        if is_simple:
            active_stop = reference_ma * multiplier if reference_ma is not None and _position_was_active(day) else None
            thresholds["simple_ma_exit_stop"] = active_stop
        else:
            active_stop = _number(thresholds.get("ma_half_stop"))
            thresholds.setdefault("simple_ma_exit_stop", None)
        threshold_by_date[str(day.get("date"))] = active_stop

        for event in day.get("events", []):
            source_event = str(event.get("source_event") or "")
            is_ma_stop_event = source_event == "MA_EXIT" if is_simple else source_event == "BREAK_HALF_TRIGGERED"
            if not is_ma_stop_event:
                continue
            event_stop = _number(event.get("trigger_level")) or active_stop
            opening = _number(day.get("open"))
            low = _number(day.get("low"))
            if event_stop is None or opening is None or low is None:
                continue
            classification = classify_stop_execution(open_price=opening, low_price=low, stop_price=event_stop)
            event["stop_execution"] = {
                **classification,
                "reference_ma": reference_ma,
                "active_stop_price": event_stop,
                "open_price": opening,
                "low_price": low,
                "actual_execution_price": _number(event.get("execution_price")),
                "sell_slippage_pct": slippage_pct,
                "formula": f"MA(t-1) × {multiplier:g}",
            }

    for row in output.get("chart", {}).get("daily_data", []):
        day = str(row.get("timestamp", ""))[:10]
        # Explicit nulls outside the holding timeline prevent chart libraries
        # from extending the last active stop into post-exit context bars.
        row["simple_ma_exit_stop"] = threshold_by_date.get(day) if is_simple else None
        row["ma_half_stop"] = threshold_by_date.get(day) if not is_simple else None

    return output

