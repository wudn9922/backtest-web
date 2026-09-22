from __future__ import annotations

"""Deterministic numerical MA_STRUCTURE_V1 analysis.

This module is deliberately independent from :mod:`app.backtest.engine`.
It observes OHLC bars and emits audit events; it never creates a portfolio,
position, execution or production strategy state.  The rolling optimiser is
responsible for running the canonical engine separately for reference and
for the out-of-sample test segment.
"""

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from app.backtest.execution import EntryZoneDecision, evaluate_entry_zone
from app.backtest.indicators import moving_average
from app.backtest.models import BacktestError, BacktestRequest
from app.data.base import STANDARD_COLUMNS, validate_daily_ohlcv


SPEC_PATH = Path(__file__).with_name("ma_structure_v1_spec.json")


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Return the committed spec's stable UTF-8 JSON representation."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


with SPEC_PATH.open("r", encoding="utf-8", newline="") as _spec_file:
    STRUCTURE_SPEC: dict[str, Any] = json.load(_spec_file)

STRUCTURE_SPEC_VERSION = str(STRUCTURE_SPEC.get("version", "MA_STRUCTURE_V1"))
STRUCTURE_SPEC_HASH = hashlib.sha256(_canonical_json_bytes(STRUCTURE_SPEC)).hexdigest()
# The machine-readable frozen specification is unchanged.  This independent
# implementation revision invalidates selector/ranking caches produced by the
# pre-isolation implementation without creating a new strategy specification.
STRUCTURE_IMPLEMENTATION_REVISION = "MA_STRUCTURE_V1_IMPL_2"
# Friendly aliases used by integrations and tests.
MA_STRUCTURE_V1 = STRUCTURE_SPEC_VERSION
SPEC_VERSION = STRUCTURE_SPEC_VERSION
SPEC_HASH = STRUCTURE_SPEC_HASH


class StructureValidationError(BacktestError):
    """A candidate that cannot produce a valid structure observation."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(code, message, status_code=422, details=details)


def structure_spec_hash() -> str:
    return STRUCTURE_SPEC_HASH


def canonical_structure_spec_bytes() -> bytes:
    """Return the exact canonical bytes used to derive the frozen hash."""
    return _canonical_json_bytes(STRUCTURE_SPEC)


def wilson_lower_bound(successes: int | float, trials: int | float, *, confidence: float = 0.95) -> float:
    """Two-sided 95% Wilson lower confidence bound, without correction.

    ``confidence`` is accepted for a convenient statistical helper API but the
    frozen analyzer contract permits only 95%.
    """
    if confidence != 0.95:
        raise ValueError("MA_STRUCTURE_V1 fixes the Wilson confidence level at 95%.")
    x = int(successes)
    n = int(trials)
    if n <= 0:
        return 0.0
    x = max(0, min(x, n))
    p = x / n
    z = 1.959963984540054
    z2 = z * z
    denominator = 1.0 + z2 / n
    numerator = p + z2 / (2.0 * n) - z * math.sqrt(max(0.0, p * (1.0 - p) / n + z2 / (4.0 * n * n)))
    return max(0.0, min(1.0, numerator / denominator))


wilson95_lower = wilson_lower_bound
wilson_lower = wilson_lower_bound


def _average_rank_percentiles(values: Sequence[float]) -> list[float]:
    """Average-rank percentiles in the input order.

    Ranks are one-based and ties receive their average rank.  A single
    candidate, or a completely tied candidate set, receives the specified
    neutral percentile 0.5.
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1 or all(value == values[0] for value in values):
        return [0.5] * n
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * n
    cursor = 0
    while cursor < n:
        end = cursor + 1
        while end < n and ordered[end][1] == ordered[cursor][1]:
            end += 1
        # Average of the one-based ranks cursor+1 ... end.
        rank = ((cursor + 1) + end) / 2.0
        for position in range(cursor, end):
            ranks[ordered[position][0]] = rank
        cursor = end
    denominator = n - 1
    return [max(0.0, min(1.0, (rank - 1.0) / denominator)) for rank in ranks]


def average_rank_percentiles(values: Sequence[float] | Mapping[Any, float]) -> list[float] | dict[Any, float]:
    """Compute frozen average-rank percentiles for a sequence or mapping."""
    if isinstance(values, Mapping):
        keys = list(values.keys())
        ranks = _average_rank_percentiles([float(values[key]) for key in keys])
        return dict(zip(keys, ranks))
    return _average_rank_percentiles([float(value) for value in values])


percentile_ranks = average_rank_percentiles
percentile_rank = average_rank_percentiles
compute_percentile_ranks = average_rank_percentiles
compute_wilson_lower_bound = wilson_lower_bound


def _as_date(value: date | datetime | pd.Timestamp | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _iso(timestamp: Any) -> str:
    if isinstance(timestamp, pd.Timestamp):
        return timestamp.isoformat()
    if isinstance(timestamp, datetime):
        return timestamp.isoformat()
    return str(timestamp)


def _bar_payload(timestamp: Any, row: Mapping[str, Any], reference_ma: float | None, *, ma: float | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "timestamp": _iso(timestamp),
        "date": _iso(timestamp)[:10],
        "open": _finite(row.get("open")),
        "high": _finite(row.get("high")),
        "low": _finite(row.get("low")),
        "close": _finite(row.get("close")),
        "volume": _finite(row.get("volume")),
        "ma": _finite(ma),
        "reference_ma": _finite(reference_ma),
        "ma_t_minus_1": _finite(reference_ma),
    }
    return payload


@dataclass(frozen=True)
class _Observation:
    position: int
    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
    ma: float | None
    reference_ma: float | None
    side: str

    def as_bar(self) -> dict[str, Any]:
        return _bar_payload(
            self.timestamp,
            {"open": self.open, "high": self.high, "low": self.low, "close": self.close, "volume": self.volume},
            self.reference_ma,
            ma=self.ma,
        )


def _request_parameter(request: BacktestRequest | Mapping[str, Any] | None, name: str, default: float) -> float:
    if request is None:
        return float(default)
    if isinstance(request, BacktestRequest):
        return float(getattr(request.parameters, name, default))
    parameters = request.get("parameters", request)
    if isinstance(parameters, Mapping):
        try:
            return float(parameters.get(name, default))
        except (TypeError, ValueError):
            return float(default)
    return float(default)


def _validate_input(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or not isinstance(frame, pd.DataFrame):
        raise StructureValidationError("INVALID_DATA_SCHEMA", "Structure analysis requires a daily OHLCV DataFrame.")
    valid, issue = validate_daily_ohlcv(frame)
    if not valid:
        code = "DATA_TIMEZONE_MISMATCH" if issue and "timezone" in issue else "INVALID_DATA_SCHEMA"
        raise StructureValidationError(code, issue or "Invalid daily OHLCV data.")
    out = frame.loc[:, STANDARD_COLUMNS].copy().sort_index()
    values = out.apply(pd.to_numeric, errors="coerce")
    if values.isna().any().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
        raise StructureValidationError("INVALID_DATA_SCHEMA", "Daily OHLCV contains non-finite values.")
    out.loc[:, STANDARD_COLUMNS] = values
    return out


def _side(close: float, reference: float | None, previous: str | None) -> str:
    if reference is None:
        return previous or "NEUTRAL"
    if close > reference:
        return "ABOVE"
    if close < reference:
        return "BELOW"
    return previous if previous in {"ABOVE", "BELOW"} else "NEUTRAL"


def _event(
    observation: _Observation,
    event_type: str,
    status: str,
    *,
    trigger: float | None = None,
    target: float | None = None,
    direction: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload = observation.as_bar()
    payload.update({
        "event_type": event_type,
        "event": event_type,
        "status": status,
        "event_status": status,
        "direction": direction,
        "trigger": _finite(trigger),
        "trigger_price": _finite(trigger),
        "target": _finite(target),
        "target_price": _finite(target),
        "reference_ma": _finite(observation.reference_ma),
        "ma_t_minus_1": _finite(observation.reference_ma),
    })
    payload.update(extra)
    return payload


def _execution_annotation(
    observation: _Observation,
    base: float,
    direction: str,
    request: BacktestRequest | Mapping[str, Any] | None,
) -> dict[str, Any]:
    if direction == "BULL":
        decision: EntryZoneDecision = evaluate_entry_zone(
            bar_open=observation.open,
            bar_high=observation.high,
            reference_ma=float(observation.reference_ma),
            breakout_trigger_pct=_request_parameter(request, "breakout_trigger_pct", 1.0),
            entry_stop_pct=_request_parameter(request, "entry_stop_pct", 1.5),
        )
        missed = bool(decision.missed)
        filled = bool(decision.filled)
        gap = bool(observation.open > base)
        execution_status = "ENTRY_ZONE_MISSED" if missed else "CANONICAL_EXECUTABLE" if filled else "ARMED_BUT_UNFILLED"
        return {
            "gap_breakout": gap,
            "normal_crossing": not gap,
            "breakout_classification": "GAP_BREAKOUT" if gap else "NORMAL_CROSSING",
            "strategy_executable": filled,
            "entry_zone_missed": missed,
            "armed_unfilled": bool(decision.armed and not filled and not missed),
            "canonical_execution_status": execution_status,
            "execution_classification": execution_status,
            "entry_zone": {
                "lower_entry": float(decision.lower_entry),
                "upper_entry": float(decision.upper_entry),
                "entry_allowed": bool(decision.entry_allowed),
                "armed": bool(decision.armed),
                "filled": filled,
                "missed": missed,
                "fill_price": _finite(decision.fill_price),
            },
        }
    gap = bool(observation.open < base)
    return {
        "gap_breakout": gap,
        "normal_crossing": not gap,
        "breakout_classification": "GAP_BREAKOUT" if gap else "NORMAL_CROSSING",
        "strategy_executable": False,
        "entry_zone_missed": False,
        "armed_unfilled": False,
        "canonical_execution_status": "NOT_APPLICABLE_BEAR",
        "execution_classification": "NOT_APPLICABLE_BEAR",
        "entry_zone": None,
    }


def _regime_analysis(observations: list[_Observation], train_start: date, train_end: date) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    train = [item for item in observations if train_start <= item.timestamp.date() <= train_end]
    pre = [item for item in observations if item.timestamp.date() < train_start]
    events: list[dict[str, Any]] = []
    bull_count = bull_success = bear_count = bear_success = 0
    previous_side: str | None = None
    for item in pre:
        if item.side in {"ABOVE", "BELOW"}:
            previous_side = item.side

    current: dict[str, Any] | None = None
    previous_train: _Observation | None = None

    def finish(item: _Observation | None) -> None:
        nonlocal bull_count, bull_success, bear_count, bear_success
        if current is None or not current["eligible"] or item is None:
            return
        start_close = float(current["start_close"])
        end_close = float(item.close)
        result = end_close / start_close - 1.0 if start_close else 0.0
        side = current["side"]
        success = result > 0 if side == "ABOVE" else result < 0
        direction = "BULL" if side == "ABOVE" else "BEAR"
        status = f"{'BULL' if side == 'ABOVE' else 'BEAR'}_REGIME_{'SUCCESS' if success else 'FAIL'}"
        event = {
            "timestamp": _iso(current["start_timestamp"]),
            "date": _iso(current["start_timestamp"])[:10],
            "event_type": "STRUCTURE_ABOVE_MA_REGIME" if side == "ABOVE" else "STRUCTURE_BELOW_MA_REGIME",
            "event": "STRUCTURE_ABOVE_MA_REGIME" if side == "ABOVE" else "STRUCTURE_BELOW_MA_REGIME",
            "status": status,
            "event_status": status,
            "direction": direction,
            "start_close": start_close,
            "end_close": end_close,
            "regime_return": result,
            "start_date": _iso(current["start_timestamp"])[:10],
            "end_date": item.timestamp.date().isoformat(),
            "reference_ma": _finite(current["reference_ma"]),
            "train_eligible": True,
        }
        events.append(event)
        if side == "ABOVE":
            bull_count += 1
            bull_success += int(success)
        else:
            bear_count += 1
            bear_success += int(success)

    for item in train:
        side = item.side
        if side == "NEUTRAL":
            previous_train = item
            continue
        if current is None:
            inherited = previous_side == side
            current = {
                "side": side,
                "eligible": not inherited,
                "start_timestamp": item.timestamp,
                "start_close": item.close,
                "reference_ma": item.reference_ma,
            }
        elif side != current["side"]:
            finish(previous_train)
            current = {
                "side": side,
                "eligible": True,
                "start_timestamp": item.timestamp,
                "start_close": item.close,
                "reference_ma": item.reference_ma,
            }
        previous_side = side
        previous_train = item
    finish(previous_train)

    bull_rate = bull_success / bull_count if bull_count else None
    bear_rate = bear_success / bear_count if bear_count else None
    raw = ((bull_rate if bull_rate is not None else 0.0) + (bear_rate if bear_rate is not None else 0.0)) / 2.0
    summary = {
        "bull_regime_count": bull_count,
        "bull_success_count": bull_success,
        "bull_success_rate": bull_rate,
        "bear_regime_count": bear_count,
        "bear_success_count": bear_success,
        "bear_success_rate": bear_rate,
        "regime_separation_raw": raw,
        "regime_separation_score": raw,
        "regime_component": raw,
        "raw": raw,
    }
    return summary, events


def _retest_analysis(observations: list[_Observation], train_start: date, train_end: date) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    bull_count = bull_success = bear_count = bear_success = 0
    for pos, item in enumerate(observations):
        if not train_start <= item.timestamp.date() <= train_end or pos < 2:
            continue
        previous = observations[pos - 1]
        previous_previous = observations[pos - 2]
        if previous.close > (previous_previous.ma if previous_previous.ma is not None else math.inf) and item.low <= (item.reference_ma if item.reference_ma is not None else -math.inf):
            success = item.close > float(item.reference_ma)
            status = "BULL_RETEST_SUCCESS" if success else "BULL_RETEST_FAIL"
            events.append(_event(item, "STRUCTURE_BULL_RETEST", status, direction="BULL", touch=True, retest_success=success, prior_side="ABOVE"))
            bull_count += 1
            bull_success += int(success)
        elif previous.close < (previous_previous.ma if previous_previous.ma is not None else -math.inf) and item.high >= (item.reference_ma if item.reference_ma is not None else math.inf):
            success = item.close < float(item.reference_ma)
            status = "BEAR_RETEST_SUCCESS" if success else "BEAR_RETEST_FAIL"
            events.append(_event(item, "STRUCTURE_BEAR_RETEST", status, direction="BEAR", touch=True, retest_success=success, prior_side="BELOW"))
            bear_count += 1
            bear_success += int(success)
    resolved = bull_count + bear_count
    successes = bull_success + bear_success
    raw = successes / resolved if resolved else None
    summary = {
        "bull_retest_count": bull_count,
        "bull_retest_success_count": bull_success,
        "bull_retest_success_rate": bull_success / bull_count if bull_count else None,
        "bear_retest_count": bear_count,
        "bear_retest_success_count": bear_success,
        "bear_retest_success_rate": bear_success / bear_count if bear_count else None,
        "retest_success_count": successes,
        "retest_resolved_count": resolved,
        "retest_raw": raw,
        "retest_success_rate": raw,
        "retest_wilson_lower": wilson_lower_bound(successes, resolved),
        "retest_component": wilson_lower_bound(successes, resolved),
        "raw": raw,
    }
    return summary, events


def _breakout_analysis(
    observations: list[_Observation],
    train_start: date,
    train_end: date,
    request: BacktestRequest | Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[_Observation]]:
    train = [item for item in observations if train_start <= item.timestamp.date() <= train_end]
    pre = [item for item in observations if item.timestamp.date() < train_start]
    if not train or not all(item.reference_ma is not None for item in train):
        raise StructureValidationError("NOT_ENOUGH_MA_LOOKBACK", "Not enough completed MA reference history in the train window.")

    bull_state: str | None
    bear_state: str | None
    # Initialization is based on the actual last completed session before the
    # Train boundary.  Falling back to an earlier finite MA would silently
    # skip a missing boundary state and violate the frozen candidate-validation
    # rule.
    last_pre = pre[-1] if pre else None
    if last_pre is None or last_pre.reference_ma is None:
        # The frozen boundary is STATE_ONLY_NO_SCORE, not a reset.  Without a
        # completed pre-Train reference close, the independent breakout state
        # cannot be initialized deterministically, so this candidate is
        # invalid rather than silently starting a new state on Train day one.
        raise StructureValidationError(
            "NOT_ENOUGH_MA_LOOKBACK",
            "A completed pre-Train MA reference state is required for breakout initialization.",
        )
    bull_state = "ARMED" if last_pre.close <= last_pre.reference_ma else "DISARMED"
    bear_state = "ARMED" if last_pre.close >= last_pre.reference_ma else "DISARMED"

    bull_events: list[dict[str, Any]] = []
    bear_events: list[dict[str, Any]] = []
    active_bull: dict[str, Any] | None = None
    active_bear: dict[str, Any] | None = None

    for item in train:
        reference = float(item.reference_ma)  # validated above
        if active_bull is not None:
            if item.high >= float(active_bull["target"]):
                active_bull["status"] = "BREAKOUT_3PCT_SUCCESS"
                active_bull["event_status"] = active_bull["status"]
                active_bull["resolved"] = True
                active_bull["success"] = True
                bull_state = "DISARMED"
                active_bull = None
            elif item.close < reference:
                active_bull["status"] = "BREAKOUT_3PCT_FAIL"
                active_bull["event_status"] = active_bull["status"]
                active_bull["resolved"] = True
                active_bull["success"] = False
                bull_state = "ARMED"
                active_bull = None
        elif bull_state == "ARMED":
            base = reference * 1.01
            target = base * 1.03
            if item.high >= base:
                annotation = _execution_annotation(item, base, "BULL", request)
                active_bull = _event(
                    item,
                    "STRUCTURE_BULL_STRUCTURAL_BREAKOUT",
                    "ACTIVE",
                    trigger=base,
                    target=target,
                    direction="BULL",
                    base=base,
                    breakout_base=base,
                    structural_breakout=True,
                    resolved=False,
                    success=False,
                    **annotation,
                )
                bull_events.append(active_bull)
                if item.high >= target:
                    active_bull["status"] = "BREAKOUT_3PCT_SUCCESS"
                    active_bull["event_status"] = active_bull["status"]
                    active_bull["resolved"] = True
                    active_bull["success"] = True
                    bull_state = "DISARMED"
                    active_bull = None
                elif item.close < reference:
                    active_bull["status"] = "BREAKOUT_3PCT_FAIL"
                    active_bull["event_status"] = active_bull["status"]
                    active_bull["resolved"] = True
                    active_bull["success"] = False
                    bull_state = "ARMED"
                    active_bull = None
        elif bull_state == "DISARMED" and item.close < reference:
            # Rearm only after the completed close; this day's high cannot
            # retroactively start a second event.
            bull_state = "ARMED"

        if active_bear is not None:
            if item.low <= float(active_bear["target"]):
                active_bear["status"] = "BREAKOUT_3PCT_SUCCESS"
                active_bear["event_status"] = active_bear["status"]
                active_bear["resolved"] = True
                active_bear["success"] = True
                bear_state = "DISARMED"
                active_bear = None
            elif item.close > reference:
                active_bear["status"] = "BREAKOUT_3PCT_FAIL"
                active_bear["event_status"] = active_bear["status"]
                active_bear["resolved"] = True
                active_bear["success"] = False
                bear_state = "ARMED"
                active_bear = None
        elif bear_state == "ARMED":
            base = reference * 0.99
            target = base * 0.97
            if item.low <= base:
                annotation = _execution_annotation(item, base, "BEAR", request)
                active_bear = _event(
                    item,
                    "STRUCTURE_BEAR_STRUCTURAL_BREAKOUT",
                    "ACTIVE",
                    trigger=base,
                    target=target,
                    direction="BEAR",
                    base=base,
                    breakout_base=base,
                    structural_breakout=True,
                    resolved=False,
                    success=False,
                    **annotation,
                )
                bear_events.append(active_bear)
                if item.low <= target:
                    active_bear["status"] = "BREAKOUT_3PCT_SUCCESS"
                    active_bear["event_status"] = active_bear["status"]
                    active_bear["resolved"] = True
                    active_bear["success"] = True
                    bear_state = "DISARMED"
                    active_bear = None
                elif item.close > reference:
                    active_bear["status"] = "BREAKOUT_3PCT_FAIL"
                    active_bear["event_status"] = active_bear["status"]
                    active_bear["resolved"] = True
                    active_bear["success"] = False
                    bear_state = "ARMED"
                    active_bear = None
        elif bear_state == "DISARMED" and item.close > reference:
            bear_state = "ARMED"

    if active_bull is not None:
        active_bull["status"] = "UNRESOLVED"
        active_bull["event_status"] = "UNRESOLVED"
        active_bull["unresolved"] = True
    if active_bear is not None:
        active_bear["status"] = "UNRESOLVED"
        active_bear["event_status"] = "UNRESOLVED"
        active_bear["unresolved"] = True

    def counts(events: list[dict[str, Any]]) -> tuple[int, int, int, int]:
        success = sum(bool(item.get("success")) for item in events)
        unresolved = sum(item.get("status") == "UNRESOLVED" for item in events)
        fail = len(events) - success - unresolved
        return len(events), int(success), int(fail), int(unresolved)

    bull_total, bull_success, bull_fail, bull_unresolved = counts(bull_events)
    bear_total, bear_success, bear_fail, bear_unresolved = counts(bear_events)
    resolved = bull_success + bull_fail + bear_success + bear_fail
    success = bull_success + bear_success
    raw = success / resolved if resolved else None
    summary = {
        "bull_breakout_count": bull_total,
        "bull_breakout_success_count": bull_success,
        "bull_breakout_fail_count": bull_fail,
        "bull_breakout_unresolved_count": bull_unresolved,
        "bear_breakout_count": bear_total,
        "bear_breakout_success_count": bear_success,
        "bear_breakout_fail_count": bear_fail,
        "bear_breakout_unresolved_count": bear_unresolved,
        "breakout_count": bull_total + bear_total,
        "breakout_success_count": success,
        "breakout_fail_count": bull_fail + bear_fail,
        "breakout_unresolved_count": bull_unresolved + bear_unresolved,
        "breakout_resolved_count": resolved,
        "breakout_raw": raw,
        "breakout_success_rate": raw,
        "breakout_wilson_lower": wilson_lower_bound(success, resolved),
        "breakout_component": wilson_lower_bound(success, resolved),
        "bull_breakout_wilson_lower": wilson_lower_bound(bull_success, bull_success + bull_fail),
        "bear_breakout_wilson_lower": wilson_lower_bound(bear_success, bear_success + bear_fail),
        "raw": raw,
        "bull_executable_breakout_count": sum(bool(item.get("strategy_executable")) for item in bull_events),
        "bull_gap_breakout_count": sum(bool(item.get("gap_breakout")) for item in bull_events),
        "bull_entry_zone_missed_count": sum(bool(item.get("entry_zone_missed")) for item in bull_events),
        "bull_armed_unfilled_count": sum(bool(item.get("armed_unfilled")) for item in bull_events),
        "bear_gap_breakout_count": sum(bool(item.get("gap_breakout")) for item in bear_events),
        "strategy_executable_breakout_count": sum(bool(item.get("strategy_executable")) for item in bull_events),
        "gap_breakout_count": sum(bool(item.get("gap_breakout")) for item in bull_events + bear_events),
        "entry_zone_missed_count": sum(bool(item.get("entry_zone_missed")) for item in bull_events),
        "execution_feasibility_ratio": (sum(bool(item.get("strategy_executable")) for item in bull_events) / bull_total) if bull_total else None,
    }
    return summary, bull_events + bear_events, train


def _confirmation_analysis(
    breakout_events: list[dict[str, Any]],
    train: list[_Observation],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    by_date = {item.timestamp: position for position, item in enumerate(train)}
    events: list[dict[str, Any]] = []
    eligible = confirmed = not_confirmed = retest_safe = violations = ambiguous = unresolved = 0
    for breakout in breakout_events:
        timestamp_text = str(breakout.get("timestamp"))
        timestamp = pd.Timestamp(timestamp_text)
        position = by_date.get(timestamp)
        if position is None:
            # Timezone-normalised lookup for callers that serialise timestamps.
            position = next((idx for idx, item in enumerate(train) if _iso(item.timestamp) == timestamp_text), None)
        if position is None or position + 1 >= len(train):
            breakout["confirmation_status"] = "NO_D2_UNRESOLVED"
            breakout["day2_status"] = "NO_D2_UNRESOLVED"
            unresolved += 1
            events.append({
                "timestamp": breakout.get("timestamp"), "date": str(breakout.get("date")),
                "event_type": "STRUCTURE_CONFIRMATION", "event": "STRUCTURE_CONFIRMATION",
                "status": "NO_D2_UNRESOLVED", "event_status": "NO_D2_UNRESOLVED",
                "direction": breakout.get("direction"), "breakout_timestamp": breakout.get("timestamp"),
                "train_eligible": False,
            })
            continue
        d2 = train[position + 1]
        direction = str(breakout.get("direction"))
        high = float(breakout["high"])
        low = float(breakout["low"])
        if direction == "BULL":
            is_confirmed = d2.close > high
        else:
            is_confirmed = d2.close < low
        eligible += 1
        if is_confirmed:
            confirmed += 1
            breakout["confirmation_status"] = "DAY2_CONFIRMED"
            breakout["day2_status"] = "DAY2_CONFIRMED"
            events.append(_event(d2, "STRUCTURE_DAY2_CONFIRMATION", "DAY2_CONFIRMED", direction=direction, breakout_timestamp=breakout.get("timestamp"), day2=True, confirmation_eligible=True))
            continue
        not_confirmed += 1
        breakout["confirmation_status"] = "DAY2_NOT_CONFIRMED"
        breakout["day2_status"] = "DAY2_NOT_CONFIRMED"
        events.append(_event(d2, "STRUCTURE_DAY2_CONFIRMATION", "DAY2_NOT_CONFIRMED", direction=direction, breakout_timestamp=breakout.get("timestamp"), day2=True, confirmation_eligible=True))

        outcome: str | None = None
        outcome_item: _Observation | None = None
        # Waiting starts strictly after D2.  D2 itself is not reinterpreted as
        # a touch or violation.
        for item in train[position + 2:]:
            reference = item.reference_ma
            if reference is None:
                continue
            touch = item.low <= reference if direction == "BULL" else item.high >= reference
            violation = item.high > high if direction == "BULL" else item.low < low
            if touch and violation:
                outcome = "SEQUENCE_AMBIGUOUS"
                outcome_item = item
                break
            if touch:
                outcome = "RETEST_SAFE"
                outcome_item = item
                break
            if violation:
                outcome = "CONFIRMATION_VIOLATION"
                outcome_item = item
                break
        if outcome is None:
            outcome = "UNRESOLVED_WAIT"
            unresolved += 1
        elif outcome == "RETEST_SAFE":
            retest_safe += 1
        elif outcome == "CONFIRMATION_VIOLATION":
            violations += 1
        elif outcome == "SEQUENCE_AMBIGUOUS":
            ambiguous += 1
        if outcome_item is not None:
            events.append(_event(outcome_item, "STRUCTURE_CONFIRMATION_LIFECYCLE", outcome, direction=direction, breakout_timestamp=breakout.get("timestamp"), confirmation_eligible=True))
        else:
            events.append({
                "timestamp": breakout.get("timestamp"), "date": breakout.get("date"),
                "event_type": "STRUCTURE_CONFIRMATION_LIFECYCLE", "event": "STRUCTURE_CONFIRMATION_LIFECYCLE",
                "status": outcome, "event_status": outcome, "direction": direction,
                "breakout_timestamp": breakout.get("timestamp"), "confirmation_eligible": True,
            })
        breakout["confirmation_status"] = outcome if outcome != "RETEST_SAFE" else "RETEST_SAFE"
    resolved = confirmed + retest_safe + violations
    violation_rate = violations / resolved if resolved else None
    raw = (1.0 - violation_rate) if violation_rate is not None else None
    summary = {
        "confirmation_eligible_events": eligible,
        "confirmation_confirmed_events": confirmed,
        "confirmation_not_confirmed_events": not_confirmed,
        "confirmation_retest_safe_events": retest_safe,
        "confirmation_violation_events": violations,
        "confirmation_ambiguous_events": ambiguous,
        "confirmation_unresolved_events": unresolved,
        "confirmation_resolved_count": resolved,
        "confirmation_violation_rate": violation_rate,
        "confirmation_raw": raw,
        "confirmation_score": raw,
        "confirmation_consistency_score": raw,
        "confirmation_component": raw if raw is not None else 0.0,
        "raw": raw,
    }
    return summary, events


def analyze_ma_structure(
    frame: pd.DataFrame,
    ma_period: int,
    ma_type: str = "sma",
    *,
    train_start: date | datetime | pd.Timestamp | str | None = None,
    train_end: date | datetime | pd.Timestamp | str | None = None,
    evaluation_start: date | datetime | pd.Timestamp | str | None = None,
    evaluation_end: date | datetime | pd.Timestamp | str | None = None,
    request: BacktestRequest | Mapping[str, Any] | None = None,
    strategy_request: BacktestRequest | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Analyze one MA candidate on a Train-only OHLCV frame.

    ``frame`` may contain pre-roll bars, but event counts and all chart rows
    are strictly bounded by ``train_start``/``train_end``.  The same function
    is useful in tests with no explicit boundary; in that case the complete
    input frame is the observation window.
    """
    if int(ma_period) < 2 or int(ma_period) > 500:
        raise StructureValidationError("INVALID_MA_PERIOD", "MA period must be between 2 and 500.")
    if ma_type not in {"sma", "ema"}:
        raise StructureValidationError("INVALID_MA_TYPE", "MA type must be SMA or EMA.")
    daily = _validate_input(frame)
    start = _as_date(train_start if train_start is not None else evaluation_start)
    end = _as_date(train_end if train_end is not None else evaluation_end)
    if start is None:
        start = daily.index[0].date()
    if end is None:
        end = daily.index[-1].date()
    if end < start:
        raise StructureValidationError("INVALID_TRAIN_RANGE", "Structure train end must be on or after train start.")

    ma = moving_average(daily["close"], int(ma_period), ma_type)
    reference = ma.shift(1)
    raw_records: list[dict[str, Any]] = []
    previous_side: str | None = None
    for position, (timestamp, row) in enumerate(daily.iterrows()):
        value_ma = _finite(ma.loc[timestamp])
        value_reference = _finite(reference.loc[timestamp])
        current_side = _side(float(row["close"]), value_reference, previous_side)
        raw_records.append({
            "position": position, "timestamp": timestamp, "open": float(row["open"]), "high": float(row["high"]),
            "low": float(row["low"]), "close": float(row["close"]), "volume": float(row["volume"]),
            "ma": value_ma, "reference_ma": value_reference, "side": current_side,
        })
        if current_side in {"ABOVE", "BELOW"}:
            previous_side = current_side
    observations = [_Observation(**item) for item in raw_records]
    train_observations = [item for item in observations if start <= item.timestamp.date() <= end]
    if not train_observations:
        raise StructureValidationError("NO_DAILY_BARS", "No daily bars overlap the structure train window.")
    if not any(item.reference_ma is not None for item in train_observations):
        raise StructureValidationError("NOT_ENOUGH_MA_LOOKBACK", "Not enough completed MA reference history for the structure train window.")

    chosen_request = strategy_request if strategy_request is not None else request
    regime, regime_events = _regime_analysis(observations, start, end)
    retest, retest_events = _retest_analysis(observations, start, end)
    breakout, breakout_events, train = _breakout_analysis(observations, start, end, chosen_request)
    confirmation, confirmation_events = _confirmation_analysis(breakout_events, train)

    total_resolved = (
        int(regime["bull_regime_count"]) + int(regime["bear_regime_count"])
        + int(retest["retest_resolved_count"]) + int(breakout["breakout_resolved_count"])
        + int(confirmation["confirmation_resolved_count"])
    )
    events = sorted(regime_events + retest_events + breakout_events + confirmation_events, key=lambda item: str(item.get("timestamp", "")))
    train_data = [item.as_bar() for item in train_observations]
    artifact = {
        "structure_spec_version": STRUCTURE_SPEC_VERSION,
        "structure_spec_hash": STRUCTURE_SPEC_HASH,
        "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
        "ma_period": int(ma_period),
        "ma_type": ma_type,
        "train_start": start.isoformat(),
        "train_end": end.isoformat(),
        "ohlc": train_data,
        "daily_data": train_data,
        "reference_ma": [{"timestamp": row["timestamp"], "value": row["reference_ma"]} for row in train_data],
        "events": events,
        "event_markers": events,
    }
    result: dict[str, Any] = {
        "valid": True,
        "ma_period": int(ma_period),
        "ma_type": ma_type,
        "structure_spec_version": STRUCTURE_SPEC_VERSION,
        "structure_spec_hash": STRUCTURE_SPEC_HASH,
        "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
        "train_start": start.isoformat(),
        "train_end": end.isoformat(),
        "pre_roll": {
            "bars": sum(item.timestamp.date() < start for item in observations),
            "first_date": observations[0].timestamp.date().isoformat() if observations else None,
            "last_date": next((item.timestamp.date().isoformat() for item in reversed(observations) if item.timestamp.date() < start), None),
            "state_only_no_score": True,
        },
        "regime": regime,
        "retest": retest,
        "breakout": breakout,
        "confirmation": confirmation,
        "total_resolved_structural_events": total_resolved,
        "events": events,
        "chart_artifact": artifact,
        "artifact": artifact,
        # Flat aliases make the JSON convenient for the table/API while the
        # nested component objects remain the canonical audit representation.
        **regime,
        **retest,
        **breakout,
        **confirmation,
        "regime_raw": float(regime["regime_separation_raw"]),
        "retest_raw_value": retest["retest_raw"],
        "breakout_raw_value": breakout["breakout_raw"],
        "confirmation_raw_value": confirmation["confirmation_raw"],
        "regime_component_raw": float(regime["regime_component"]),
        "retest_component_value": float(retest["retest_component"]),
        "breakout_component_value": float(breakout["breakout_component"]),
        "confirmation_component_value": float(confirmation["confirmation_component"]),
    }
    # The analyzer is a pure numerical observer.  Do not leak a strategy's
    # Train PnL/Sharpe into this object; runner attaches reference rows only
    # after selection has been computed.
    return result


analyze_structure = analyze_ma_structure
analyze = analyze_ma_structure


class MAStructureAnalyzer:
    """Small state-free facade for callers that prefer an analyzer object."""

    version = STRUCTURE_SPEC_VERSION
    spec_hash = STRUCTURE_SPEC_HASH

    def __init__(self, frame: pd.DataFrame | None = None, ma_period: int | None = None, ma_type: str = "sma", **kwargs: Any):
        self.frame, self.ma_period, self.ma_type, self.kwargs = frame, ma_period, ma_type, kwargs

    def analyze(self, frame: pd.DataFrame | None = None, ma_period: int | None = None, ma_type: str | None = None, **kwargs: Any) -> dict[str, Any]:
        source_frame = frame if frame is not None else self.frame
        source_period = ma_period if ma_period is not None else self.ma_period
        if source_frame is None or source_period is None:
            raise TypeError("frame and ma_period are required for Structure analysis")
        options = {**self.kwargs, **kwargs}
        return analyze_ma_structure(source_frame, int(source_period), ma_type or self.ma_type, **options)


StructureAnalyzer = MAStructureAnalyzer


_SELECTOR_COMPONENT_NAMES = ("regime", "retest", "breakout", "confirmation")
_SELECTOR_ALLOWED_FIELDS = {
    "ma_period", "candidate_index", "structure_spec_version", "structure_spec_hash",
    "structure_implementation_revision", "selector_components", "breakout_wilson_lower",
    "total_resolved_structural_events", "confirmation_violation_rate", "valid", "skipped",
    "invalid_reason",
}
_RANKING_OUTPUT_FIELDS = {
    "structure_ranking", "regime_percentile", "retest_percentile", "breakout_percentile",
    "confirmation_percentile", "ma_structure_score", "structure_score", "structure_percentile",
    "structure_components", "structure_rank", "rank", "tie_break_reason",
}
_PROHIBITED_SELECTOR_FIELDS = {
    "train_reference", "backtest_id", "train_return", "train_sharpe", "total_return", "cagr",
    "sharpe", "sharpe_ratio", "sortino", "sortino_ratio", "calmar", "calmar_ratio",
    "max_drawdown", "mdd", "net_pnl", "gross_pnl", "number_of_positions", "trade_count",
    "number_of_trades", "win_rate", "exposure", "exposure_pct", "average_holding_days",
    "total_commission", "commission", "fees", "slippage", "slippage_cost",
    "estimated_slippage_cost", "final_equity", "cache_reused", "pnl", "return",
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool)


def _is_integer_number(value: Any) -> bool:
    return _is_number(value) and math.isfinite(float(value)) and float(value).is_integer()


def _find_prohibited_selector_field(value: Any) -> str | None:
    """Find performance/train data at any nesting level (fail closed)."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            key_lower = key_text.lower()
            if key_lower in _PROHIBITED_SELECTOR_FIELDS or key_lower.startswith("train_"):
                return key_text
            if any(token in key_lower for token in ("backtest_id", "performance_", "pnl", "drawdown", "sharpe", "sortino", "calmar")):
                return key_text
            found = _find_prohibited_selector_field(child)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for child in value:
            found = _find_prohibited_selector_field(child)
            if found is not None:
                return found
    return None


def validate_structure_selector_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and defensively copy the structure-only selector contract.

    This is intentionally stricter than the historical flat candidate helper:
    selector code may consume only authoritative structure components and never
    infer a value from raw/value/score aliases or Train performance fields.
    """
    if not isinstance(candidate, Mapping):
        raise StructureValidationError("INVALID_STRUCTURE_SELECTOR_CANDIDATE", "Structure selector candidate must be an object.")
    copied = copy.deepcopy(dict(candidate))
    prohibited = _find_prohibited_selector_field(copied)
    if prohibited is not None:
        raise StructureValidationError(
            "INVALID_STRUCTURE_SELECTOR_CANDIDATE",
            f"Structure selector candidate contains prohibited performance field: {prohibited}.",
            {"field": prohibited},
        )
    unexpected = sorted(set(copied) - _SELECTOR_ALLOWED_FIELDS - _RANKING_OUTPUT_FIELDS)
    if unexpected:
        raise StructureValidationError(
            "INVALID_STRUCTURE_SELECTOR_CANDIDATE",
            "Structure selector candidate contains fields outside the frozen selector contract.",
            {"fields": unexpected},
        )
    required = {
        "ma_period", "candidate_index", "structure_spec_version", "structure_spec_hash",
        "structure_implementation_revision", "selector_components", "breakout_wilson_lower",
        "total_resolved_structural_events", "confirmation_violation_rate",
    }
    missing = sorted(field for field in required if field not in copied)
    if missing:
        raise StructureValidationError(
            "INVALID_STRUCTURE_SELECTOR_CANDIDATE",
            "Structure selector candidate is missing authoritative fields.",
            {"missing": missing},
        )
    if copied["structure_spec_version"] != STRUCTURE_SPEC_VERSION or copied["structure_spec_hash"] != STRUCTURE_SPEC_HASH:
        raise StructureValidationError("STRUCTURE_SPEC_MISMATCH", "Structure selector candidate uses a different frozen specification.")
    if copied["structure_implementation_revision"] != STRUCTURE_IMPLEMENTATION_REVISION:
        raise StructureValidationError(
            "STRUCTURE_IMPLEMENTATION_REVISION_MISMATCH",
            "Structure selector candidate was produced by an invalidated implementation revision.",
            {"expected": STRUCTURE_IMPLEMENTATION_REVISION, "actual": copied["structure_implementation_revision"]},
        )
    if not _is_integer_number(copied["ma_period"]) or not 2 <= int(copied["ma_period"]) <= 500:
        raise StructureValidationError("INVALID_STRUCTURE_SELECTOR_CANDIDATE", "MA period is not a finite supported number.")
    if not _is_integer_number(copied["candidate_index"]) or int(copied["candidate_index"]) < 0:
        raise StructureValidationError("INVALID_STRUCTURE_SELECTOR_CANDIDATE", "Candidate index is not a finite non-negative number.")
    components = copied["selector_components"]
    if not isinstance(components, Mapping) or set(components) != set(_SELECTOR_COMPONENT_NAMES):
        raise StructureValidationError(
            "INVALID_STRUCTURE_SELECTOR_CANDIDATE",
            "selector_components must contain exactly regime, retest, breakout and confirmation.",
        )
    for name in _SELECTOR_COMPONENT_NAMES:
        value = components[name]
        if not _is_number(value) or not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
            raise StructureValidationError("INVALID_STRUCTURE_SELECTOR_CANDIDATE", f"selector_components.{name} must be finite in [0, 1].")
    for field in ("breakout_wilson_lower", "confirmation_violation_rate"):
        value = copied[field]
        if value is not None and (not _is_number(value) or not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0):
            raise StructureValidationError("INVALID_STRUCTURE_SELECTOR_CANDIDATE", f"{field} must be finite in [0, 1] or null.")
    if not _is_number(copied["breakout_wilson_lower"]) or not math.isfinite(float(copied["breakout_wilson_lower"])):
        raise StructureValidationError("INVALID_STRUCTURE_SELECTOR_CANDIDATE", "breakout_wilson_lower must be finite.")
    if not _is_integer_number(copied["total_resolved_structural_events"]) or int(copied["total_resolved_structural_events"]) < 0:
        raise StructureValidationError("INVALID_STRUCTURE_SELECTOR_CANDIDATE", "total_resolved_structural_events must be a non-negative integer.")
    if "valid" in copied and not isinstance(copied["valid"], bool):
        raise StructureValidationError("INVALID_STRUCTURE_SELECTOR_CANDIDATE", "valid must be boolean when provided.")
    if "skipped" in copied and not isinstance(copied["skipped"], bool):
        raise StructureValidationError("INVALID_STRUCTURE_SELECTOR_CANDIDATE", "skipped must be boolean when provided.")
    # Ranking output is trusted only when it has the exact new namespace.
    if "structure_ranking" in copied:
        ranking = copied["structure_ranking"]
        if not isinstance(ranking, Mapping) or set(ranking) != {"ranking_values", "percentiles", "composite"}:
            raise StructureValidationError("INVALID_STRUCTURE_SELECTOR_CANDIDATE", "structure_ranking has an invalid schema.")
        for key in ("ranking_values", "percentiles"):
            values = ranking[key]
            if not isinstance(values, Mapping) or set(values) != set(_SELECTOR_COMPONENT_NAMES):
                raise StructureValidationError("INVALID_STRUCTURE_SELECTOR_CANDIDATE", f"structure_ranking.{key} has an invalid schema.")
            for name in _SELECTOR_COMPONENT_NAMES:
                if not _is_number(values[name]) or not math.isfinite(float(values[name])):
                    raise StructureValidationError("INVALID_STRUCTURE_SELECTOR_CANDIDATE", f"structure_ranking.{key}.{name} must be finite.")
        if not _is_number(ranking["composite"]) or not math.isfinite(float(ranking["composite"])):
            raise StructureValidationError("INVALID_STRUCTURE_SELECTOR_CANDIDATE", "structure_ranking.composite must be finite.")
    return copied


def build_structure_selector_candidate(analysis: Mapping[str, Any], candidate_index: int) -> dict[str, Any]:
    """Build a selector-only object from one analyzer result.

    Analyzer/UI/audit data remains outside this object.  In particular, the
    pooled Wilson lower bounds are the sole retest/breakout selector values.
    """
    if not isinstance(analysis, Mapping):
        raise StructureValidationError("INVALID_STRUCTURE_SELECTOR_CANDIDATE", "Analyzer result must be an object.")
    try:
        regime = analysis["regime"]
        retest = analysis["retest"]
        breakout = analysis["breakout"]
        confirmation = analysis["confirmation"]
        components = {
            "regime": regime["regime_component"],
            "retest": retest["retest_component"],
            "breakout": breakout["breakout_component"],
            "confirmation": confirmation["confirmation_component"],
        }
        candidate = {
            "ma_period": int(analysis["ma_period"]),
            "candidate_index": int(candidate_index),
            "structure_spec_version": analysis["structure_spec_version"],
            "structure_spec_hash": analysis["structure_spec_hash"],
            "structure_implementation_revision": analysis["structure_implementation_revision"],
            "selector_components": components,
            "breakout_wilson_lower": breakout["breakout_wilson_lower"],
            "total_resolved_structural_events": int(analysis["total_resolved_structural_events"]),
            "confirmation_violation_rate": confirmation["confirmation_violation_rate"],
            "valid": bool(analysis.get("valid", True)),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise StructureValidationError("INVALID_STRUCTURE_SELECTOR_CANDIDATE", "Analyzer result lacks authoritative structure fields.") from exc
    return validate_structure_selector_candidate(candidate)


# Descriptive alias for callers/tests that use the word "normalize".
normalize_structure_selector_candidate = build_structure_selector_candidate


def rank_structure_candidates(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Rank structure-only candidates without mutating inputs or raw fields."""
    normalized = [validate_structure_selector_candidate(item) for item in candidates]
    output = [item for item in normalized if item.get("valid", True) is not False and not item.get("skipped")]
    raw_values = {name: [float(item["selector_components"][name]) for item in output] for name in _SELECTOR_COMPONENT_NAMES}
    percentiles = {name: _average_rank_percentiles(values) for name, values in raw_values.items()}
    for index, item in enumerate(output):
        ranking_values = {name: raw_values[name][index] for name in _SELECTOR_COMPONENT_NAMES}
        ranking_percentiles = {name: percentiles[name][index] for name in _SELECTOR_COMPONENT_NAMES}
        composite = sum(ranking_percentiles[name] * 0.25 for name in _SELECTOR_COMPONENT_NAMES)
        item["structure_ranking"] = {
            "ranking_values": ranking_values,
            "percentiles": ranking_percentiles,
            "composite": float(composite),
        }
        # Read-only compatibility aliases.  Analyzer *_raw fields are not
        # present in the selector object and are never overwritten here.
        item["regime_percentile"] = ranking_percentiles["regime"]
        item["retest_percentile"] = ranking_percentiles["retest"]
        item["breakout_percentile"] = ranking_percentiles["breakout"]
        item["confirmation_percentile"] = ranking_percentiles["confirmation"]
        item["ma_structure_score"] = float(composite)
        item["structure_score"] = float(composite)
        item["structure_percentile"] = dict(ranking_percentiles)
        item["structure_components"] = copy.deepcopy(item["structure_ranking"])
    return output


def _tie_violation(candidate: Mapping[str, Any]) -> float:
    value = candidate["confirmation_violation_rate"]
    return float(value) if value is not None else math.inf


def _breakout_wilson(candidate: Mapping[str, Any]) -> float:
    return float(candidate["selector_components"]["breakout"])


def _resolved_structural_events(candidate: Mapping[str, Any]) -> int:
    return int(candidate["total_resolved_structural_events"])


def _ranking_composite(candidate: Mapping[str, Any]) -> float:
    ranking = candidate.get("structure_ranking")
    if not isinstance(ranking, Mapping) or not _is_number(ranking.get("composite")):
        raise StructureValidationError("INVALID_STRUCTURE_SELECTOR_CANDIDATE", "Candidate has no validated structure ranking namespace.")
    value = float(ranking["composite"])
    if not math.isfinite(value):
        raise StructureValidationError("INVALID_STRUCTURE_SELECTOR_CANDIDATE", "Structure ranking composite must be finite.")
    return value


def _structure_only_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Return only selector/ranking data; never attach Train performance."""
    safe = _SELECTOR_ALLOWED_FIELDS | _RANKING_OUTPUT_FIELDS
    return {key: copy.deepcopy(value) for key, value in candidate.items() if key in safe}


def structure_candidate_sort_key(candidate: Mapping[str, Any]) -> tuple[float, float, int, float, int, int]:
    """Return the frozen score/tie-break ordering from the new namespace."""
    return (
        -_ranking_composite(candidate),
        -_breakout_wilson(candidate),
        -_resolved_structural_events(candidate),
        _tie_violation(candidate),
        int(candidate["ma_period"]),
        int(candidate["candidate_index"]),
    )


def _first_decisive_tie_break(winner: Mapping[str, Any], runner_up: Mapping[str, Any] | None) -> str:
    if runner_up is None:
        return "CANONICAL_CANDIDATE_ORDER"
    checks = (
        (_ranking_composite(winner), _ranking_composite(runner_up), "STRUCTURE_SCORE", lambda a, b: a != b),
        (_breakout_wilson(winner), _breakout_wilson(runner_up), "HIGHER_BREAKOUT_WILSON", lambda a, b: a != b),
        (_resolved_structural_events(winner), _resolved_structural_events(runner_up), "MORE_RESOLVED_EVENTS", lambda a, b: a != b),
        (_tie_violation(winner), _tie_violation(runner_up), "LOWER_CONFIRMATION_VIOLATION", lambda a, b: a != b),
        (int(winner["ma_period"]), int(runner_up["ma_period"]), "SMALLER_MA_PERIOD", lambda a, b: a != b),
        (int(winner["candidate_index"]), int(runner_up["candidate_index"]), "CANONICAL_CANDIDATE_ORDER", lambda a, b: a != b),
    )
    for left, right, reason, differs in checks:
        if differs(left, right):
            return reason
    return "CANONICAL_CANDIDATE_ORDER"


def select_structure_ma(candidates: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], str]:
    """Select MA using only structure-only values and the frozen tie-break key."""
    ranked = rank_structure_candidates(candidates)
    if not ranked:
        raise StructureValidationError("NO_VALID_STRUCTURE_CANDIDATE", "No MA candidate has a valid structure observation.")
    ranked.sort(key=structure_candidate_sort_key)
    best = ranked[0]
    reason = _first_decisive_tie_break(best, ranked[1] if len(ranked) > 1 else None)
    for index, candidate in enumerate(ranked, start=1):
        candidate["structure_rank"] = index
        candidate["rank"] = index
        candidate["tie_break_reason"] = reason if candidate.get("ma_period") == best.get("ma_period") else None
    return _structure_only_candidate(best), reason


select_best_structure = select_structure_ma
rank_candidates = rank_structure_candidates
select_ma_by_structure = select_structure_ma
compute_structure_score = rank_structure_candidates


def structure_required_warmup_start(train_start: date, ma_period: int) -> date:
    """Candidate-specific MA-only pre-roll boundary.

    Advanced ATR/Bias warm-up is intentionally excluded: those indicators
    belong to canonical reference backtests and must not delay Structure's
    first Train observation.
    """
    from datetime import timedelta

    return train_start - timedelta(days=max(2, int(ma_period) * 2) + 20)
