from __future__ import annotations

"""Causal breakout, target and Day-2 failure-path event study.

This module intentionally has no portfolio, order, fee or trade-ledger code.
The only MA_BOX dependency is its frozen read-only entanglement/box observer
helpers, used to label a Day-1 cohort without running the trading strategy.
"""

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable
import uuid

import numpy as np
import pandas as pd

from app.backtest.indicators import moving_average, wilder_atr
from app.ma_box.engine import (
    BoundaryEvidence,
    _best_evidence,
    _contacts_for_bar,
    _entanglement,
    _initial_box,
    _strictly_improves_boundary,
)


ANALYTICS_REVISION = "MA_BREAKOUT_ANALYTICS_V1"
SPEC_REVISION = "MA_BREAKOUT_ANALYTICS_V1_REVISION_3"
SPEC_REVISION_NUMBER = 3
EXPECTED_SPEC_SHA256 = "0ac4a0fad9cbbc747b104b19e420e35368937e3359fd462786bd6317ad0d7647"
SPEC_PATH = Path(__file__).resolve().parents[3] / "research" / "specs" / "MA_BREAKOUT_ANALYTICS_V1_REVISION_3.md"
WILSON_Z = 1.959963984540054


def spec_sha256() -> str:
    if not SPEC_PATH.exists():
        raise RuntimeError("MA_BREAKOUT_ANALYTICS_V1 frozen specification artifact is missing")
    actual = hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()
    if actual != EXPECTED_SPEC_SHA256:
        raise RuntimeError("MA_BREAKOUT_ANALYTICS_V1 frozen specification artifact hash mismatch")
    return actual


@dataclass(frozen=True)
class AnalyticsConfig:
    ticker: str
    selected_ma: int
    nearby_range: int
    step: int
    start_date: date
    end_date: date
    direction_mode: str = "LONG_SHORT_SPLIT"
    entanglement_mode: str = "ALL"

    def periods(self) -> list[int]:
        if not 2 <= self.selected_ma <= 500:
            raise ValueError("selected_ma must be between 2 and 500")
        if self.nearby_range < 0 or self.step < 1:
            raise ValueError("nearby_range must be non-negative and step must be positive")
        low, high = max(2, self.selected_ma - self.nearby_range), min(500, self.selected_ma + self.nearby_range)
        result = list(range(low, high + 1, self.step))
        if low <= self.selected_ma <= high and self.selected_ma not in result:
            result.append(self.selected_ma)
            result.sort()
        return result

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker.upper(), "selected_ma": self.selected_ma,
            "nearby_range": self.nearby_range, "step": self.step,
            "start_date": self.start_date.isoformat(), "end_date": self.end_date.isoformat(),
            "periods": self.periods(), "direction_mode": self.direction_mode,
            "entanglement_mode": self.entanglement_mode,
        }


def _safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, (date,)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    return value


def _date(frame: pd.DataFrame, i: int) -> str:
    return pd.Timestamp(frame.index[i]).date().isoformat()


def wilson(successes: int, resolved: int) -> dict[str, Any]:
    if resolved <= 0:
        return {"probability": None, "wilson_lower": None, "wilson_upper": None,
                "status": "NOT_EVALUABLE", "low_sample_size": False}
    p = successes / resolved
    z2 = WILSON_Z * WILSON_Z
    denom = 1 + z2 / resolved
    center = (p + z2 / (2 * resolved)) / denom
    half = WILSON_Z * math.sqrt((p * (1 - p) + z2 / (4 * resolved)) / resolved) / denom
    return {"probability": p, "wilson_lower": max(0.0, center - half),
            "wilson_upper": min(1.0, center + half), "status": "EVALUABLE",
            "low_sample_size": resolved < 20}


def _validated_frame(daily: pd.DataFrame) -> pd.DataFrame:
    required = ["open", "high", "low", "close", "volume"]
    if daily is None or daily.empty or not set(required).issubset(daily.columns):
        raise ValueError("Daily OHLCV data is missing required columns")
    frame = daily[required].copy().sort_index()
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("Daily timestamps must be timezone-aware")
    if frame.index.duplicated().any() or pd.Series(frame.index.date).duplicated().any():
        raise ValueError("Daily bars contain duplicate sessions")
    frame = frame.apply(pd.to_numeric, errors="coerce")
    # Volume can be missing/nonfinite for analytics: volume-conditioned sets
    # then become not evaluable while price-based events remain usable.
    price = frame[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(price).all() or (price <= 0).any():
        raise ValueError("Daily OHLC contains invalid prices")
    if (frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any() or (
        frame["low"] > frame[["open", "close", "high"]].min(axis=1)
    ).any():
        raise ValueError("Daily OHLC bounds are invalid")
    return frame


def _event_id(study_id: str, period: int, direction: str, seq: int, day: str) -> str:
    return f"{study_id}:SMA{period}:{direction}:{seq:05d}:{day}"


def _read_only_entanglement_snapshots(frame: pd.DataFrame, period: int) -> list[dict[str, Any]]:
    """Run the causal MA_BOX Rev3 visual-box state without any trade engine.

    This intentionally follows session-start boundaries, close-confirmed
    invalidation and t+1 boundary effectiveness. The MA_BOX pure helper
    functions are shared so the cohort cannot drift from the frozen predicate.
    """
    snapshots: list[dict[str, Any]] = []
    box = None
    rearm_after: int | None = None
    for i, (_, row) in enumerate(frame.iterrows()):
        active_start = box is not None
        start_box_id = box.box_id if box is not None else None
        start_box_high = float(box.high) if box is not None else None
        start_box_low = float(box.low) if box is not None else None
        formed = False
        if box is not None:
            close = float(row["close"])
            if close > box.high or close < box.low:
                box = None
                rearm_after = i
            else:
                ts = frame.index[i]
                new_contacts = []
                ma = float(row["ma"])
                new_contacts.extend(_contacts_for_bar(i, ts, row, ma, box.midpoint, "upper"))
                new_contacts.extend(_contacts_for_bar(i, ts, row, ma, box.midpoint, "lower"))
                box.contacts.extend(new_contacts)
                old_high, old_low = box.high, box.low
                upper_points = [x for x in box.contacts if x.side == "upper"]
                lower_points = [x for x in box.contacts if x.side == "lower"]
                upper = _best_evidence(upper_points, box.upper_evidence or BoundaryEvidence(old_high), box.tolerance, "upper")
                lower = _best_evidence(lower_points, box.lower_evidence or BoundaryEvidence(old_low), box.tolerance, "lower")
                if _strictly_improves_boundary(upper, box.upper_evidence) and upper.level > box.low:
                    box.high, box.upper_evidence = upper.level, upper
                if _strictly_improves_boundary(lower, box.lower_evidence) and lower.level < box.high:
                    box.low, box.lower_evidence = lower.level, lower
                if box.high <= box.low:
                    box.high, box.low = old_high, old_low
        elif i >= 3:
            formation = _entanglement(frame, i, 0)
            if formation:
                indices, qualifying = formation
                if rearm_after is not None and not all(j > rearm_after for j in qualifying):
                    formation = None
                if formation is not None:
                    box = _initial_box(frame, indices, qualifying, period, 14, 0.10)
                    formed = box is not None
        snapshots.append({
            "box_active_at_session_start": active_start,
            "box_id_at_session_start": start_box_id,
            "box_high_at_session_start": start_box_high,
            "box_low_at_session_start": start_box_low,
            "box_formed_on_day1_close": formed,
            "box_active_after_day1_close": box is not None,
            "entanglement_cohort": "ENTANGLED_AT_SIGNAL" if active_start or formed else "CLEAN",
            "box_id": box.box_id if box is not None else None,
            "box_high": float(box.high) if box is not None else None,
            "box_low": float(box.low) if box is not None else None,
        })
    return snapshots


def _volume_state(frame: pd.DataFrame, i: int) -> dict[str, Any]:
    current = frame.iloc[i]["volume"]
    previous = frame.iloc[i - 1]["volume"] if i > 0 else np.nan
    try:
        current, previous = float(current), float(previous)
    except (TypeError, ValueError):
        current, previous = math.nan, math.nan
    evaluable = math.isfinite(current) and current >= 0 and math.isfinite(previous) and previous > 0
    # Difference-before-division keeps exact threshold inputs such as 120/100
    # from falling just below 20% due to subtractive binary-float rounding.
    change = (current - previous) / previous if evaluable else None
    return {
        "volume_current": current if math.isfinite(current) else None,
        "volume_previous": previous if math.isfinite(previous) else None,
        "volume_change": change,
        "volume_evaluable": bool(evaluable),
        "vol_lt_10": bool(evaluable and change < 0.10),
        "vol_ge_10": bool(evaluable and change >= 0.10),
        "vol_ge_20": bool(evaluable and change >= 0.20),
        "vol_ge_30": bool(evaluable and change >= 0.30),
    }


def _path_result(direction: str, row: pd.Series, stop: float, target: float) -> tuple[str | None, str]:
    op, hi, lo, cl = (float(row[x]) for x in ("open", "high", "low", "close"))
    if direction == "LONG":
        if op <= stop:
            return "FAIL_STOP_FIRST", "OPEN_GAP_STOP"
        if op >= target:
            return "SUCCESS_TARGET_FIRST", "OPEN_GAP_TARGET"
        stop_hit, target_hit = lo <= stop, hi >= target
    else:
        if op >= stop:
            return "FAIL_STOP_FIRST", "OPEN_GAP_STOP"
        if op <= target:
            return "SUCCESS_TARGET_FIRST", "OPEN_GAP_TARGET"
        stop_hit, target_hit = hi >= stop, lo <= target
    if stop_hit and target_hit:
        green = cl >= op
        if direction == "LONG":
            return ("FAIL_STOP_FIRST", "OHLC_HEURISTIC") if green else ("SUCCESS_TARGET_FIRST", "OHLC_HEURISTIC")
        return ("SUCCESS_TARGET_FIRST", "OHLC_HEURISTIC") if green else ("FAIL_STOP_FIRST", "OHLC_HEURISTIC")
    if stop_hit:
        return "FAIL_STOP_FIRST", "INTRADAY_STOP"
    if target_hit:
        return "SUCCESS_TARGET_FIRST", "INTRADAY_TARGET"
    return None, "NO_TOUCH"


def _target_levels(direction: str, reference: float, atr: Any) -> list[dict[str, Any]]:
    targets = [{"target_type": "PCT_3", "target_level": reference * (1.03 if direction == "LONG" else 0.97), "atr_target": False}]
    try:
        atr_value = float(atr)
    except (TypeError, ValueError):
        atr_value = math.nan
    for multiple in (0.5, 1.0, 1.5, 2.0, 3.0):
        level = reference + multiple * atr_value if direction == "LONG" else reference - multiple * atr_value
        targets.append({"target_type": f"ATR_{multiple:g}", "target_level": level if math.isfinite(atr_value) and atr_value > 0 else None, "atr_target": True})
    return targets


def _scan_target(frame: pd.DataFrame, *, event: dict[str, Any], target: dict[str, Any], condition: str,
                 origin: str, known_i: int, start_i: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    direction = event["direction"]
    atr_target = bool(target["atr_target"])
    base = {
        "event_id": event["event_id"], "target_type": target["target_type"],
        "target_level": target["target_level"], "condition_type": condition,
        "observation_origin": origin, "condition_known_date": _date(frame, known_i),
        "observation_start_date": _date(frame, start_i) if start_i < len(frame) else None,
        "first_dynamic_stop": None, "atr_snapshot": event["atr14_d1"] if atr_target else None,
        "resolution_date": None, "resolution_state": None, "target_or_stop_first": None,
        "censor_reason": None, "eligible": True,
    }
    if atr_target and (event["atr14_d1"] is None or not math.isfinite(float(event["atr14_d1"])) or float(event["atr14_d1"]) <= 0):
        base.update({"resolution_state": "TARGET_NOT_EVALUABLE_ATR", "eligible": False,
                     "censor_reason": "ATR14_D1_INVALID"})
        return _safe(base), []
    if start_i >= len(frame):
        base.update({"resolution_state": "RIGHT_CENSORED", "censor_reason": "STUDY_END_BEFORE_OBSERVATION_START"})
        return _safe(base), []
    level = float(target["target_level"])
    first_stop = float(frame.iloc[start_i - 1]["ma"]) * (0.985 if direction == "LONG" else 1.015)
    base["first_dynamic_stop"] = first_stop
    audit: list[dict[str, Any]] = []
    for session_index, i in enumerate(range(start_i, len(frame))):
        stop = float(frame.iloc[i - 1]["ma"]) * (0.985 if direction == "LONG" else 1.015)
        resolution, touch = _path_result(direction, frame.iloc[i], stop, level)
        audit.append({
            "study_id": event["study_id"], "event_id": event["event_id"],
            "target_type": target["target_type"], "session_index": session_index,
            "condition_type": condition, "observation_origin": origin,
            "date": _date(frame, i), "open": float(frame.iloc[i]["open"]),
            "high": float(frame.iloc[i]["high"]), "low": float(frame.iloc[i]["low"]),
            "close": float(frame.iloc[i]["close"]), "previous_completed_ma": float(frame.iloc[i - 1]["ma"]),
            "stop_level": stop, "target_level": level, "touch_resolution": touch,
            "resolution_state": resolution, "source_cutoff": pd.Timestamp(frame.index[i]).isoformat(),
        })
        if resolution:
            base.update({"resolution_date": _date(frame, i), "resolution_state": resolution,
                         "target_or_stop_first": "TARGET" if resolution == "SUCCESS_TARGET_FIRST" else "STOP"})
            return _safe(base), [_safe(x) for x in audit]
    base.update({"resolution_state": "RIGHT_CENSORED", "censor_reason": "STUDY_END"})
    return _safe(base), [_safe(x) for x in audit]


def _failure_path(frame: pd.DataFrame, event: dict[str, Any], d2_i: int | None) -> dict[str, Any]:
    if d2_i is None or d2_i + 1 >= len(frame):
        return {
            "event_id": event["event_id"], "terminal_outcome": "RIGHT_CENSORED",
            "terminal_date": None, "terminal_precedence_revision": "REVISION_3",
            "trend_definition_revision": "REVISION_3", "sideways_definition_revision": "REVISION_3",
            "retest_zone_history": [],
            "censor_reason": "STUDY_END_BEFORE_D3",
        }
    d3_i = d2_i + 1
    direction = event["direction"]
    d1_close = float(event["d1_close"])
    retest_zone_history: list[dict[str, Any]] = []
    for i in range(d3_i, len(frame)):
        row = frame.iloc[i]
        ma = float(row["ma"])
        close = float(row["close"])
        zone_low, zone_high = ma * 0.999, ma * 1.001
        retest_zone_history.append({
            "date": _date(frame, i), "ma": ma,
            "retest_zone_low": zone_low, "retest_zone_high": zone_high,
            "low": float(row["low"]), "high": float(row["high"]), "close": close,
            "intersects": float(row["low"]) <= zone_high and float(row["high"]) >= zone_low,
        })
        terminal: str | None = None
        details: dict[str, Any] = {}
        # Frozen terminal precedence: return, retest, trend-away, sideways.
        if direction == "LONG" and close <= ma * 0.998:
            terminal = "RETURN_TO_BEAR"
            details = {"return_close": close, "return_ma": ma, "return_distance_pct": (close / ma - 1) * 100}
        elif direction == "SHORT" and close >= ma * 1.002:
            terminal = "RETURN_TO_BULL"
            details = {"return_close": close, "return_ma": ma, "return_distance_pct": (close / ma - 1) * 100}
        else:
            intersects = float(row["low"]) <= zone_high and float(row["high"]) >= zone_low
            if direction == "LONG" and intersects and close > ma:
                terminal = "MA_RETEST_REBOUND"
            elif direction == "SHORT" and intersects and close < ma:
                terminal = "MA_RETEST_REJECTION"
            if terminal:
                details = {"retest_zone_low": zone_low, "retest_zone_high": zone_high,
                           "retest_low": float(row["low"]), "retest_high": float(row["high"]), "retest_close": close}
            elif direction == "LONG" and close >= ma * 1.002 and close > d1_close:
                terminal = "TREND_CONTINUATION_AWAY"
                details = {"trend_close": close, "trend_ma": ma, "day1_close_reference": d1_close,
                           "trend_distance_pct": (close / ma - 1) * 100}
            elif direction == "SHORT" and close <= ma * 0.998 and close < d1_close:
                terminal = "TREND_CONTINUATION_AWAY"
                details = {"trend_close": close, "trend_ma": ma, "day1_close_reference": d1_close,
                           "trend_distance_pct": (close / ma - 1) * 100}
            elif i >= d3_i + 3:
                start = i - 3
                window = frame.iloc[start:i + 1]
                atr_ref = frame.iloc[start - 1]["atr"] if start > 0 else np.nan
                try:
                    atr_ref = float(atr_ref)
                except (TypeError, ValueError):
                    atr_ref = math.nan
                if math.isfinite(atr_ref) and atr_ref > 0:
                    window_high, window_low = float(window["high"].max()), float(window["low"].min())
                    window_range = window_high - window_low
                    normalized = window_range / atr_ref
                    if normalized <= 1.5:
                        terminal = "SIDEWAYS"
                        details = {
                            "sideways_window_bars": 4,
                            "sideways_window_start": _date(frame, start),
                            "sideways_window_end": _date(frame, i),
                            "sideways_window_dates": [_date(frame, j) for j in range(start, i + 1)],
                            "sideways_window_high": window_high, "sideways_window_low": window_low,
                            "sideways_window_range": window_range,
                            "sideways_atr_reference_date": _date(frame, start - 1),
                            "sideways_atr14": atr_ref,
                            "sideways_range_atr": normalized,
                            "sideways_threshold_atr": 1.5,
                        }
        if terminal:
            return _safe({
                "event_id": event["event_id"], "terminal_outcome": terminal,
                "terminal_date": _date(frame, i), "terminal_precedence_revision": "REVISION_3",
                "trend_definition_revision": "REVISION_3", "sideways_definition_revision": "REVISION_3",
                "observation_start_date": _date(frame, d3_i), "observation_start_index": d3_i,
                "day1_close_reference_for_trend": d1_close,
                "retest_zone_history": retest_zone_history,
                "terminal_close": close, "terminal_ma": ma, **details,
            })
    return {
        "event_id": event["event_id"], "terminal_outcome": "RIGHT_CENSORED",
        "terminal_date": _date(frame, len(frame) - 1), "terminal_precedence_revision": "REVISION_3",
        "trend_definition_revision": "REVISION_3", "sideways_definition_revision": "REVISION_3",
        "observation_start_date": _date(frame, d3_i), "observation_start_index": d3_i,
        "day1_close_reference_for_trend": d1_close,
        "retest_zone_history": retest_zone_history, "censor_reason": "STUDY_END",
    }


def _directions(mode: str) -> list[str]:
    return {"LONG_ONLY": ["LONG"], "SHORT_ONLY": ["SHORT"], "LONG_SHORT_SPLIT": ["LONG", "SHORT"]}[mode]


def _cohort_groups(events: list[dict[str, Any]], mode: str) -> list[tuple[str, list[dict[str, Any]]]]:
    if mode == "ALL":
        return [("ALL", events)]
    if mode == "EXCLUDE_ENTANGLED":
        return [("CLEAN", [e for e in events if e["entanglement_cohort"] == "CLEAN"])]
    if mode == "ONLY_ENTANGLED":
        return [("ENTANGLED_AT_SIGNAL", [e for e in events if e["entanglement_cohort"] == "ENTANGLED_AT_SIGNAL"])]
    return [("ENTANGLED_AT_SIGNAL", [e for e in events if e["entanglement_cohort"] == "ENTANGLED_AT_SIGNAL"]),
            ("CLEAN", [e for e in events if e["entanglement_cohort"] == "CLEAN"])]


def _make_probability_aggregates(events: list[dict[str, Any]], config: AnalyticsConfig) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for period in config.periods():
        period_events = [e for e in events if e["sma_period"] == period]
        for direction in _directions(config.direction_mode):
            directional = [e for e in period_events if e["direction"] == direction]
            for cohort, group in _cohort_groups(directional, config.entanglement_mode):
                conditions: list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]] = []
                conditions.append(("BREAKOUT", group, group))
                d2_eligible = [e for e in group if e["d2_evaluable"]]
                conditions.append(("DAY2_SUCCESS", d2_eligible, [e for e in d2_eligible if e["d2_success"]]))
                vol_eligible = [e for e in group if e["volume_evaluable"]]
                conditions.append(("VOLUME_GE_10", vol_eligible, [e for e in vol_eligible if e["vol_ge_10"]]))
                conditions.append(("VOLUME_GE_20", vol_eligible, [e for e in vol_eligible if e["vol_ge_20"]]))
                conditions.append(("VOLUME_GE_30", vol_eligible, [e for e in vol_eligible if e["vol_ge_30"]]))
                for threshold in (10, 20, 30):
                    both_eligible = [e for e in group if e["d2_evaluable"] and e["volume_evaluable"]]
                    both = [e for e in both_eligible if e["d2_success"] and e[f"vol_ge_{threshold}"]]
                    conditions.append((f"DAY2_AND_VOL_GE_{threshold}", both_eligible, both))
                for name, eligible, success in conditions:
                    ids = {e["event_id"] for e in success}
                    stats = wilson(len(success), len(eligible))
                    output.append({
                        "aggregate_id": f"P:{period}:{direction}:{cohort}:{name}",
                        "study_id": None, "period": period, "direction": direction,
                        "entanglement_cohort": cohort, "aggregate_type": "PROBABILITY",
                        "condition_type": name, "eligible_count": len(eligible),
                        "resolved_count": len(eligible), "success_count": len(success),
                        "censored_count": len(group) - len(eligible), "not_evaluable_count": len(group) - len(eligible),
                        **stats,
                        "members": ([{"event_id": e["event_id"], "membership_type": "ELIGIBLE"} for e in eligible]
                                    + [{"event_id": e["event_id"], "membership_type": "RESOLVED"} for e in eligible]
                                    + [{"event_id": e["event_id"], "membership_type": "NUMERATOR"} for e in success]),
                    })
    return output


def _make_target_aggregates(events: list[dict[str, Any]], outcomes: list[dict[str, Any]], config: AnalyticsConfig) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    by_event = {e["event_id"]: e for e in events}
    for period in config.periods():
        for direction in _directions(config.direction_mode):
            period_ids = {e["event_id"] for e in events if e["sma_period"] == period and e["direction"] == direction}
            for cohort, ev_group in _cohort_groups([e for e in events if e["event_id"] in period_ids], config.entanglement_mode):
                cohort_ids = {e["event_id"] for e in ev_group}
                keys = sorted({(x["target_type"], x["condition_type"], x["observation_origin"]) for x in outcomes
                               if x["event_id"] in cohort_ids and by_event[x["event_id"]]["sma_period"] == period
                               and by_event[x["event_id"]]["direction"] == direction})
                for target_type, condition, origin in keys:
                    rows = [x for x in outcomes if x["event_id"] in cohort_ids and x["target_type"] == target_type
                            and x["condition_type"] == condition and x["observation_origin"] == origin
                            and by_event[x["event_id"]]["sma_period"] == period and by_event[x["event_id"]]["direction"] == direction]
                    eligible = [x for x in rows if x.get("eligible", True)]
                    resolved = [x for x in eligible if x["resolution_state"] in {"SUCCESS_TARGET_FIRST", "FAIL_STOP_FIRST"}]
                    success = [x for x in resolved if x["resolution_state"] == "SUCCESS_TARGET_FIRST"]
                    censored = [x for x in eligible if x["resolution_state"] == "RIGHT_CENSORED"]
                    not_eval = [x for x in rows if not x.get("eligible", True)]
                    stats = wilson(len(success), len(resolved))
                    output.append({
                        "aggregate_id": f"T:{period}:{direction}:{cohort}:{condition}:{target_type}:{origin}",
                        "study_id": None, "period": period, "direction": direction,
                        "entanglement_cohort": cohort, "aggregate_type": "TARGET",
                        "condition_type": condition, "target_type": target_type,
                        "observation_origin": origin, "eligible_count": len(eligible),
                        "resolved_count": len(resolved), "success_count": len(success),
                        "censored_count": len(censored), "not_evaluable_count": len(not_eval), **stats,
                        "members": ([{"event_id": x["event_id"], "membership_type": "ELIGIBLE"} for x in eligible]
                                    + [{"event_id": x["event_id"], "membership_type": "RESOLVED"} for x in resolved]
                                    + [{"event_id": x["event_id"], "membership_type": "NUMERATOR"} for x in success]
                                    + [{"event_id": x["event_id"], "membership_type": "CENSORED"} for x in censored]
                                    + [{"event_id": x["event_id"], "membership_type": "NOT_EVALUABLE"} for x in not_eval]),
                    })
    return output


def _make_failure_aggregates(events: list[dict[str, Any]], failures: list[dict[str, Any]], config: AnalyticsConfig) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    by_id = {e["event_id"]: e for e in events}
    terminal_types = ["MA_RETEST_REBOUND", "MA_RETEST_REJECTION", "RETURN_TO_BEAR", "RETURN_TO_BULL", "SIDEWAYS", "TREND_CONTINUATION_AWAY"]
    for period in config.periods():
        for direction in _directions(config.direction_mode):
            period_ids = {e["event_id"] for e in events if e["sma_period"] == period and e["direction"] == direction and e["d2_status"] == "FAILURE"}
            for cohort, ev_group in _cohort_groups([e for e in events if e["event_id"] in period_ids], config.entanglement_mode):
                ids = {e["event_id"] for e in ev_group}
                group_failures = [f for f in failures if f["event_id"] in ids]
                volume_conditions = [("ALL_FAILURES", lambda e: True)]
                volume_conditions.extend((f"VOL_GE_{t}", lambda e, t=t: e["volume_evaluable"] and e[f"vol_ge_{t}"]) for t in (10, 20, 30))
                volume_conditions.append(("VOL_LT_10", lambda e: e["volume_evaluable"] and e["vol_lt_10"]))
                for condition, predicate in volume_conditions:
                    eligible_events = [e for e in ev_group if predicate(e)]
                    f_by_id = {f["event_id"]: f for f in group_failures}
                    included = [f_by_id[e["event_id"]] for e in eligible_events if e["event_id"] in f_by_id]
                    resolved = [f for f in included if f["terminal_outcome"] != "RIGHT_CENSORED"]
                    censored = [f for f in included if f["terminal_outcome"] == "RIGHT_CENSORED"]
                    counts = {name: sum(f["terminal_outcome"] == name for f in resolved) for name in terminal_types}
                    resolved_n = len(resolved)
                    stats = wilson(sum(counts.get(x, 0) for x in ("MA_RETEST_REBOUND", "MA_RETEST_REJECTION", "RETURN_TO_BEAR", "RETURN_TO_BULL", "SIDEWAYS")), resolved_n)
                    combined = sum(counts.get(x, 0) for x in ("MA_RETEST_REBOUND", "MA_RETEST_REJECTION", "RETURN_TO_BEAR", "RETURN_TO_BULL", "SIDEWAYS"))
                    output.append({
                        "aggregate_id": f"F:{period}:{direction}:{cohort}:{condition}",
                        "study_id": None, "period": period, "direction": direction,
                        "entanglement_cohort": cohort, "aggregate_type": "FAILURE_PATH",
                        "condition_type": condition, "eligible_count": len(eligible_events),
                        "resolved_count": resolved_n, "success_count": combined,
                        "censored_count": len(censored), "not_evaluable_count": len(ev_group) - len(eligible_events),
                        "terminal_counts": counts, "combined_retest_return_sideways_count": combined,
                        "combined_probability": combined / resolved_n if resolved_n else None,
                        "trend_count": counts.get("TREND_CONTINUATION_AWAY", 0),
                        "trend_probability": counts.get("TREND_CONTINUATION_AWAY", 0) / resolved_n if resolved_n else None,
                        **stats,
                        "members": ([{"event_id": f["event_id"], "membership_type": "ELIGIBLE"} for f in included]
                                    + [{"event_id": f["event_id"], "membership_type": "RESOLVED"} for f in resolved]
                                    + [{"event_id": f["event_id"], "membership_type": "NUMERATOR"} for f in resolved if f["terminal_outcome"] in {"MA_RETEST_REBOUND", "MA_RETEST_REJECTION", "RETURN_TO_BEAR", "RETURN_TO_BULL", "SIDEWAYS"}]
                                    + [{"event_id": f["event_id"], "membership_type": "CENSORED"} for f in censored]),
                    })
    return output


def _analyze_period(raw: pd.DataFrame, period: int, config: AnalyticsConfig, *, study_id: str,
                    provider: str, fingerprint: str, config_hash: str, frozen_hash: str) -> dict[str, Any]:
    frame = raw.copy()
    frame["ma"] = moving_average(frame["close"], period, "sma")
    frame["atr"] = wilder_atr(frame, 14)
    dates = np.array([x.date() for x in frame.index])
    eval_mask = (dates >= config.start_date) & (dates <= config.end_date)
    eval_positions = [i for i, valid in enumerate(eval_mask) if valid and i > 0 and
                      math.isfinite(float(frame.iloc[i]["ma"])) and math.isfinite(float(frame.iloc[i - 1]["ma"]))]
    if not eval_positions:
        raise ValueError(f"Not enough warm-up data for SMA{period} in requested range")
    eval_start, eval_end = eval_positions[0], eval_positions[-1]
    # Event-study arrays are restricted to the requested evaluation range;
    # the previous bar remains present to initialize the latch and references.
    sliced = frame.iloc[eval_start - 1:eval_end + 1].copy()
    eval_offset = 1
    eval_frame = sliced.iloc[1:].copy()
    # Build the causal MA_BOX cohort snapshot from all available warm-up bars,
    # then read only the evaluation-date snapshots.  Starting the observer at
    # evaluation_start would incorrectly label a breakout immediately after a
    # pre-roll box as CLEAN.
    entanglement = _read_only_entanglement_snapshots(frame, period)
    events: list[dict[str, Any]] = []
    latches = {
        "LONG": float(sliced.iloc[0]["close"]) <= float(sliced.iloc[0]["ma"]),
        "SHORT": float(sliced.iloc[0]["close"]) >= float(sliced.iloc[0]["ma"]),
    }
    sequence = {"LONG": 0, "SHORT": 0}
    previous_volumes = []
    for direction in _directions(config.direction_mode):
        latch = latches[direction]
        for local_i, (_, row) in enumerate(eval_frame.iterrows()):
            close, ma = float(row["close"]), float(row["ma"])
            latch_before = latch
            threshold = ma * (1.002 if direction == "LONG" else 0.998)
            is_breakout = close >= threshold if direction == "LONG" else close <= threshold
            if latch and is_breakout:
                i = local_i + eval_offset
                d1_close = close
                d1_prev_ma = float(sliced.iloc[i - 1]["ma"])
                reference = d1_prev_ma * (1.01 if direction == "LONG" else 0.99)
                atr_value = row["atr"]
                try:
                    atr_value = float(atr_value)
                    atr_value = atr_value if math.isfinite(atr_value) else None
                except (TypeError, ValueError):
                    atr_value = None
                vol = _volume_state(sliced, i)
                snap = entanglement[eval_start + local_i]
                sequence[direction] += 1
                event = {
                    "event_id": _event_id(study_id, period, direction, sequence[direction], _date(sliced, i)),
                    "study_id": study_id, "ticker": config.ticker.upper(), "sma_period": period,
                    "direction": direction, "provider": provider, "data_fingerprint": fingerprint,
                    "analytics_revision": ANALYTICS_REVISION, "spec_revision": SPEC_REVISION,
                    "spec_revision_number": SPEC_REVISION_NUMBER, "spec_hash": frozen_hash,
                    "config_hash": config_hash, "d1_date": _date(sliced, i),
                    "breakout_definition_revision": "COMPLETED_CLOSE_VS_SMA_T_PLUS_MINUS_0_2_PERCENT",
                    "two_day_rule_revision": "STRICT_D2_CLOSE_VS_D1_CLOSE",
                    "reference_entry_definition_revision": "PRIOR_COMPLETED_SMA_PLUS_MINUS_1_PERCENT",
                    "d1_open": float(row["open"]), "d1_high": float(row["high"]),
                    "d1_low": float(row["low"]), "d1_close": close,
                    "d1_volume": vol["volume_current"], "ma_d1": ma,
                    "ma_d1_previous": d1_prev_ma, "atr14_d1": atr_value,
                    "atr14_snapshot_date": _date(sliced, i),
                    "breakout_threshold_price": ma * (1.002 if direction == "LONG" else 0.998),
                    "breakout_distance_pct": (close / ma - 1) * 100,
                    "breakout_distance_atr": ((close - ma) / atr_value) if atr_value and atr_value > 0 else None,
                    "latch_before": bool(latch_before), "latch_after": False,
                    "reference_entry": reference, "volume_previous": vol["volume_previous"],
                    "volume_change": vol["volume_change"], "volume_evaluable": vol["volume_evaluable"],
                    "vol_lt_10": vol["vol_lt_10"], "vol_ge_10": vol["vol_ge_10"],
                    "vol_ge_20": vol["vol_ge_20"], "vol_ge_30": vol["vol_ge_30"],
                    "box_active_at_session_start": snap["box_active_at_session_start"],
                    "box_formed_on_day1_close": snap["box_formed_on_day1_close"],
                    "box_active_after_day1_close": snap["box_active_after_day1_close"],
                    "entanglement_cohort": snap["entanglement_cohort"],
                    "entanglement_box_id": snap["box_id"],
                    "entanglement_box_high": snap["box_high"], "entanglement_box_low": snap["box_low"],
                    "day1_close_reference_for_trend": d1_close,
                    "censor_state": None, "audit_cutoff": pd.Timestamp(sliced.index[i]).isoformat(),
                    "d2_evaluable": i + 1 < len(sliced), "d2_status": "NOT_EVALUABLE",
                    "d2_date": None, "d2_open": None, "d2_high": None, "d2_low": None,
                    "d2_close": None, "d2_success": False, "d2_volume_evaluable": False,
                }
                d2_i = i + 1 if i + 1 < len(sliced) else None
                if d2_i is not None:
                    d2 = sliced.iloc[d2_i]
                    event.update({"d2_date": _date(sliced, d2_i), "d2_open": float(d2["open"]),
                                  "d2_high": float(d2["high"]), "d2_low": float(d2["low"]),
                                  "d2_close": float(d2["close"]),
                                  "d2_success": float(d2["close"]) > d1_close if direction == "LONG" else float(d2["close"]) < d1_close,
                                  "d2_status": "SUCCESS" if (float(d2["close"]) > d1_close if direction == "LONG" else float(d2["close"]) < d1_close) else "FAILURE"})
                    event["d2_volume_evaluable"] = _volume_state(sliced, d2_i)["volume_evaluable"]
                else:
                    event["d2_status"] = "RIGHT_CENSORED"
                    event["censor_state"] = "STUDY_END_BEFORE_D2"
                events.append(_safe(event))
                latch = False
            elif not latch and (close <= ma if direction == "LONG" else close >= ma):
                latch = True
        latches[direction] = latch

    # The chart payload is authoritative, but contains only indicator and event
    # overlays; the client never recomputes signal or terminal logic.
    event_by_date = {e["d1_date"]: [] for e in events}
    for event in events:
        event_by_date.setdefault(event["d1_date"], []).append(event["event_id"])
    chart = []
    for i, (_, row) in enumerate(eval_frame.iterrows()):
        snap = entanglement[eval_start + i]
        chart.append(_safe({
            "date": _date(eval_frame, i), "open": row["open"], "high": row["high"],
            "low": row["low"], "close": row["close"], "volume": row["volume"],
            "sma": row["ma"], "atr14": row["atr"],
            "long_day1_threshold": row["ma"] * 1.002,
            "short_day1_threshold": row["ma"] * 0.998,
            "event_ids": event_by_date.get(_date(eval_frame, i), []),
            "box_active_at_session_start": snap["box_active_at_session_start"],
            "box_id_at_session_start": snap["box_id_at_session_start"],
            "box_high_at_session_start": snap["box_high_at_session_start"],
            "box_low_at_session_start": snap["box_low_at_session_start"],
            "box_formed_on_close": snap["box_formed_on_day1_close"],
            "box_active_after_close": snap["box_active_after_day1_close"],
            "box_id_after_close": snap["box_id"],
            "box_high_after_close": snap["box_high"],
            "box_low_after_close": snap["box_low"],
            "entanglement_cohort": snap["entanglement_cohort"],
        }))

    targets: list[dict[str, Any]] = []
    target_audit: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for event in events:
        i = next(j for j in range(len(sliced)) if _date(sliced, j) == event["d1_date"])
        d2_i = i + 1 if i + 1 < len(sliced) else None
        conditions_d1 = ["BREAKOUT"]
        if event["volume_evaluable"]:
            if event["vol_ge_10"]: conditions_d1.append("VOL_GE_10")
            if event["vol_ge_20"]: conditions_d1.append("VOL_GE_20")
            if event["vol_ge_30"]: conditions_d1.append("VOL_GE_30")
            if event["vol_lt_10"]: conditions_d1.append("VOL_LT_10")
        levels = _target_levels(event["direction"], float(event["reference_entry"]), event["atr14_d1"])
        for condition in conditions_d1:
            for target in levels:
                outcome, audit = _scan_target(sliced, event=event, target=target, condition=condition,
                                              origin="POST_D1", known_i=i, start_i=i + 1)
                targets.append(outcome); target_audit.extend(audit)
        if d2_i is not None and event["d2_success"]:
            conditions_d2 = ["DAY2_SUCCESS"]
            d2_volume = _volume_state(sliced, d2_i)
            for threshold in (10, 20, 30):
                if event["volume_evaluable"] and event[f"vol_ge_{threshold}"]:
                    conditions_d2.append(f"DAY2_SUCCESS_AND_VOL_GE_{threshold}")
            for condition in conditions_d2:
                for target in levels:
                    outcome, audit = _scan_target(sliced, event=event, target=target, condition=condition,
                                                  origin="POST_D2_SUCCESS", known_i=d2_i, start_i=d2_i + 1)
                    targets.append(outcome); target_audit.extend(audit)
        elif d2_i is not None:
            failure = _failure_path(sliced, event, d2_i)
            volume_flags = _volume_state(sliced, i)
            failure.update({"study_id": study_id, "sma_period": period, "direction": event["direction"],
                            "entanglement_cohort": event["entanglement_cohort"],
                            "d1_volume_evaluable": volume_flags["volume_evaluable"],
                            "vol_ge_10": volume_flags["vol_ge_10"], "vol_ge_20": volume_flags["vol_ge_20"],
                            "vol_ge_30": volume_flags["vol_ge_30"], "vol_lt_10": volume_flags["vol_lt_10"]})
            failures.append(_safe(failure))
    return {"period": period, "events": events, "target_outcomes": targets,
            "target_session_audit": target_audit, "failure_outcomes": failures, "chart": chart}


def analyze_study(daily: pd.DataFrame, config: AnalyticsConfig, *, provider: str = "synthetic",
                  data_fingerprint: str | None = None, study_id: str | None = None) -> dict[str, Any]:
    frame = _validated_frame(daily)
    periods = config.periods()
    if config.direction_mode not in {"LONG_ONLY", "SHORT_ONLY", "LONG_SHORT_SPLIT"}:
        raise ValueError("direction_mode is invalid")
    if config.entanglement_mode not in {"ALL", "EXCLUDE_ENTANGLED", "ONLY_ENTANGLED", "SPLIT_ENTANGLED_CLEAN"}:
        raise ValueError("entanglement_mode is invalid")
    if config.end_date <= config.start_date:
        raise ValueError("end_date must be after start_date")
    study_id = study_id or str(uuid.uuid4())
    frozen_hash = spec_sha256()
    if data_fingerprint is None:
        canonical = frame.copy()
        hashed = pd.util.hash_pandas_object(canonical, index=True).to_numpy().tobytes()
        data_fingerprint = hashlib.sha256(hashed).hexdigest()
    config_hash = hashlib.sha256(json.dumps(config.as_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    runs = [_analyze_period(frame, p, config, study_id=study_id, provider=provider,
                            fingerprint=data_fingerprint, config_hash=config_hash, frozen_hash=frozen_hash)
            for p in periods]
    events = [e for run in runs for e in run["events"]]
    targets = [x for run in runs for x in run["target_outcomes"]]
    target_audit = [x for run in runs for x in run["target_session_audit"]]
    failures = [x for run in runs for x in run["failure_outcomes"]]
    aggregates = _make_probability_aggregates(events, config)
    aggregates += _make_target_aggregates(events, targets, config)
    aggregates += _make_failure_aggregates(events, failures, config)
    provenance = {
        "study_id": study_id,
        "analytics_revision": ANALYTICS_REVISION,
        "spec_revision": SPEC_REVISION,
        "spec_revision_number": SPEC_REVISION_NUMBER,
        "spec_hash": frozen_hash,
        "config_hash": config_hash,
        "data_fingerprint": data_fingerprint,
    }
    # Persist provenance on every first-class study, event, outcome and
    # aggregate. Per-session audit rows retain their study/event foreign-key
    # identities and inherit the frozen provenance through the parent outcome.
    for collection in (events, targets, failures, aggregates):
        for record in collection:
            record.update(provenance)
    for aggregate in aggregates:
        aggregate["members"] = _safe(aggregate.get("members", []))
    requested = frame[(np.array([x.date() for x in frame.index]) >= config.start_date) &
                      (np.array([x.date() for x in frame.index]) <= config.end_date)]
    return _safe({
        "study_id": study_id, "analytics_revision": ANALYTICS_REVISION,
        "spec_revision": SPEC_REVISION, "spec_revision_number": SPEC_REVISION_NUMBER,
        "spec_hash": frozen_hash, "config_hash": config_hash, "config": config.as_dict(),
        "ticker": config.ticker.upper(), "provider": provider,
        "data_fingerprint": data_fingerprint,
        "evaluation_start": requested.index[0].date().isoformat() if len(requested) else None,
        "evaluation_end": requested.index[-1].date().isoformat() if len(requested) else None,
        "bars": int(len(requested)), "periods": periods,
        "events": events, "target_outcomes": targets,
        "target_session_audit": target_audit, "failure_outcomes": failures,
        "aggregates": aggregates,
        "charts": {str(run["period"]): run["chart"] for run in runs},
        "period_summary": _period_summary(events, targets, failures, config),
        "reference_entry_label": "統計基準進場價，不是實際策略成交價",
    })


def _period_summary(events: list[dict[str, Any]], targets: list[dict[str, Any]], failures: list[dict[str, Any]], config: AnalyticsConfig) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for period in config.periods():
        for direction in _directions(config.direction_mode):
            rows = [e for e in events if e["sma_period"] == period and e["direction"] == direction]
            d2 = [e for e in rows if e["d2_evaluable"]]
            d2_success = sum(bool(e["d2_success"]) for e in d2)
            vol = [e for e in rows if e["volume_evaluable"]]
            failure_rows = [f for f in failures if f.get("sma_period") == period and f.get("direction") == direction]
            resolved_failures = [f for f in failure_rows if f["terminal_outcome"] != "RIGHT_CENSORED"]
            retest = sum(f["terminal_outcome"] in {"MA_RETEST_REBOUND", "MA_RETEST_REJECTION"} for f in resolved_failures)
            returns = sum(f["terminal_outcome"] in {"RETURN_TO_BEAR", "RETURN_TO_BULL"} for f in resolved_failures)
            sideways = sum(f["terminal_outcome"] == "SIDEWAYS" for f in resolved_failures)
            trend = sum(f["terminal_outcome"] == "TREND_CONTINUATION_AWAY" for f in resolved_failures)
            summaries.append({
                "period": period, "direction": direction, "event_count": len(rows),
                "day2_evaluable": len(d2), "day2_success_count": d2_success,
                "day2_success": wilson(d2_success, len(d2)),
                "volume_evaluable": len(vol),
                "volume_ge_10_count": sum(e["vol_ge_10"] for e in vol),
                "volume_ge_20_count": sum(e["vol_ge_20"] for e in vol),
                "volume_ge_30_count": sum(e["vol_ge_30"] for e in vol),
                "day2_failure_events": len(failure_rows),
                "failure_resolved": len(resolved_failures),
                "failure_censored": len(failure_rows) - len(resolved_failures),
                "failure_retest_count": retest, "failure_return_count": returns,
                "failure_sideways_count": sideways, "failure_trend_count": trend,
                "failure_combined_count": retest + returns + sideways,
                "failure_combined_probability": (retest + returns + sideways) / len(resolved_failures) if resolved_failures else None,
                "target_outcome_count": sum(x["event_id"] in {e["event_id"] for e in rows} for x in targets),
            })
    return summaries
