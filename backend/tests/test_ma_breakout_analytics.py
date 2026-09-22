from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.ma_breakout_analytics.engine as analytics_engine
from app.api.ma_breakout_analytics import AnalyticsStudyRequest, router
from app.data.base import DataProvider
from app.ma_breakout_analytics.engine import (
    AnalyticsConfig,
    _failure_path,
    _path_result,
    _read_only_entanglement_snapshots,
    _scan_target,
    _target_levels,
    analyze_study,
    spec_sha256,
    wilson,
)
from app.ma_breakout_analytics.repository import AnalyticsRepository


def bars(closes: list[float], *, volumes: list[float] | None = None,
         opens: list[float] | None = None, highs: list[float] | None = None,
         lows: list[float] | None = None) -> pd.DataFrame:
    c = np.asarray(closes, dtype=float)
    n = len(c)
    o = np.asarray(opens if opens is not None else c, dtype=float)
    h = np.asarray(highs if highs is not None else np.maximum(o, c) + 0.4, dtype=float)
    l = np.asarray(lows if lows is not None else np.minimum(o, c) - 0.4, dtype=float)
    v = np.asarray(volumes if volumes is not None else [100.0] * n, dtype=float)
    idx = pd.date_range("2021-01-01", periods=n, tz="UTC", freq="D")
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}, index=idx)


def breakout_bars(*, d2_close: float = 104.0, d2_high: float = 104.5, d2_low: float = 102.7,
                  day1_volume: float = 135.0, day2_volume: float = 135.0) -> pd.DataFrame:
    close = [100.0] * 30
    close[15], close[16], close[17], close[18] = 99.0, 103.0, d2_close, 103.2
    close[19:] = [103.2] * (len(close) - 19)
    volume = [100.0] * 30
    volume[16], volume[17] = day1_volume, day2_volume
    frame = bars(close, volumes=volume)
    frame.iloc[17, frame.columns.get_loc("high")] = d2_high
    frame.iloc[17, frame.columns.get_loc("low")] = d2_low
    frame.iloc[17, frame.columns.get_loc("open")] = 103.0
    frame.iloc[18, frame.columns.get_loc("open")] = 103.1
    frame.iloc[18, frame.columns.get_loc("high")] = 103.4
    frame.iloc[18, frame.columns.get_loc("low")] = 102.7
    frame.iloc[19:, frame.columns.get_loc("high")] = 103.4
    frame.iloc[19:, frame.columns.get_loc("low")] = 102.7
    return frame


def config(*, start: date = date(2021, 1, 5), end: date = date(2021, 1, 30),
           period: int = 2, direction: str = "LONG_ONLY", cohort: str = "ALL") -> AnalyticsConfig:
    return AnalyticsConfig("FIXTURE", period, 0, 1, start, end, direction, cohort)


def event_for(result: dict, day: str = "2021-01-17") -> dict:
    return next(e for e in result["events"] if e["d1_date"] == day)


def failure_frame(*, lows: list[float] | None = None, highs: list[float] | None = None,
                  closes: list[float] | None = None, atr: list[float] | None = None) -> pd.DataFrame:
    close = closes or [110.0, 109.0, 108.0, 108.0, 108.0, 108.0, 108.0]
    n = len(close)
    low = lows or [x - 0.1 for x in close]
    high = highs or [x + 0.1 for x in close]
    frame = bars(close, opens=close, highs=high, lows=low)
    frame["ma"] = 100.0
    frame["atr"] = atr if atr is not None else [1.0] * n
    return frame


def failure_event(direction: str = "LONG", day1_close: float = 110.0) -> dict:
    return {"event_id": "fixture-event", "direction": direction, "d1_close": day1_close}


def test_sma_periods_include_selected_period_when_step_skips_it():
    cfg = AnalyticsConfig("FIXTURE", 24, 5, 2, date(2021, 1, 1), date(2021, 2, 1))
    assert cfg.periods() == [19, 21, 23, 24, 25, 27, 29]


def test_day1_uses_completed_same_day_sma_and_reference_uses_previous_sma():
    result = analyze_study(breakout_bars(), config(), study_id="fixed")
    event = event_for(result)
    assert event["ma_d1"] == pytest.approx((99.0 + 103.0) / 2)
    assert event["ma_d1_previous"] == pytest.approx((100.0 + 99.0) / 2)
    assert event["reference_entry"] == pytest.approx(event["ma_d1_previous"] * 1.01)
    assert event["d1_close"] >= event["ma_d1"] * 1.002
    assert event["breakout_definition_revision"] == "COMPLETED_CLOSE_VS_SMA_T_PLUS_MINUS_0_2_PERCENT"
    assert event["breakout_threshold_price"] == pytest.approx(event["ma_d1"] * 1.002)
    assert event["atr14_snapshot_date"] == event["d1_date"]


def test_subthreshold_ma_cross_does_not_create_breakout():
    close = [100.0] * 24
    close[16] = 100.1
    frame = bars(close)
    ma = (close[15] + close[16]) / 2
    assert close[16] < ma * 1.002
    # The intraday high crosses the clear-above threshold, but a completed
    # close below that threshold must not create a breakout event.
    assert frame.iloc[16]["high"] >= ma * 1.002
    result = analyze_study(frame, config(), study_id="subthreshold")
    assert result["events"] == []


@pytest.mark.parametrize(("d2_close", "expected"), [(96.0, "SUCCESS"), (97.0, "FAILURE")])
def test_short_day1_breakout_and_day2_confirmation(d2_close: float, expected: str):
    close = [100.0] * 30
    close[15], close[16], close[17] = 101.0, 97.0, d2_close
    result = analyze_study(
        bars(close),
        AnalyticsConfig("FIXTURE", 2, 0, 1, date(2021, 1, 5), date(2021, 1, 30), "SHORT_ONLY", "ALL"),
        study_id="short-day2",
    )
    event = event_for(result)
    assert event["direction"] == "SHORT"
    assert event["d1_date"] == "2021-01-17"
    assert event["d2_status"] == expected
    assert event["reference_entry"] == pytest.approx(event["ma_d1_previous"] * 0.99)


def test_existing_trend_at_study_start_is_not_fabricated_as_new_breakout():
    close = [100.0] * 28
    close[0:5] = [99.0, 101.0, 103.0, 104.0, 105.0]
    frame = bars(close)
    result = analyze_study(frame, config(start=date(2021, 1, 5)), study_id="fixed")
    assert all(e["d1_date"] != "2021-01-05" for e in result["events"])


def test_latch_requires_close_back_at_ma_before_a_second_event():
    close = [100.0] * 30
    close[15], close[16], close[17], close[18], close[19], close[20], close[21] = 99.0, 103.0, 103.1, 103.2, 105.0, 103.0, 105.0
    result = analyze_study(bars(close), config(), study_id="fixed")
    d1 = [e["d1_date"] for e in result["events"]]
    assert "2021-01-17" in d1
    # Close above the MA but below the clear threshold does not re-arm.
    assert "2021-01-20" not in d1
    # The later close back to/below the MA re-arms for a genuinely new push.
    assert "2021-01-22" in d1


def test_post_event_grey_zone_does_not_rearm():
    close = [100.0] * 26
    close[15], close[16], close[17], close[18] = 99.0, 103.0, 103.1, 105.0
    result = analyze_study(bars(close), config(), study_id="grey-no-rearm")
    events = [event for event in result["events"] if event["direction"] == "LONG"]
    first = next(event for event in events if event["d1_date"] == "2021-01-17")
    grey = (close[17] / ((close[16] + close[17]) / 2)) - 1
    assert -0.002 < grey < 0.002
    assert first["d2_close"] == close[17]
    assert [event["d1_date"] for event in events] == ["2021-01-17"]


def test_day2_close_equality_is_failure():
    result = analyze_study(breakout_bars(d2_close=103.0), config(), study_id="fixed")
    event = event_for(result)
    assert event["d2_status"] == "FAILURE"
    assert event["d2_success"] is False


def test_volume_thresholds_are_nested_and_35_percent_hits_all_flags():
    result = analyze_study(breakout_bars(day1_volume=135), config(), study_id="fixed")
    event = event_for(result)
    assert event["volume_change"] == pytest.approx(0.35)
    assert [event[f"vol_ge_{threshold}"] for threshold in (10, 20, 30)] == [True, True, True]


@pytest.mark.parametrize(("volume", "expected"), [
    (109.0, [False, False, False]), (110.0, [True, False, False]),
    (115.0, [True, False, False]), (120.0, [True, True, False]),
    (130.0, [True, True, True]),
])
def test_volume_threshold_boundaries_are_inclusive(volume: float, expected: list[bool]):
    result = analyze_study(breakout_bars(day1_volume=volume), config(), study_id="fixed")
    event = event_for(result)
    assert [event[f"vol_ge_{threshold}"] for threshold in (10, 20, 30)] == expected


def test_invalid_volume_is_not_evaluable_but_zero_current_volume_is_valid():
    invalid = analyze_study(breakout_bars(day1_volume=100), config(), study_id="fixed")
    e1 = event_for(invalid)
    assert e1["volume_evaluable"] is True
    frame = breakout_bars(day1_volume=0)
    valid_zero = analyze_study(frame, config(), study_id="fixed")
    e2 = event_for(valid_zero)
    assert e2["volume_evaluable"] is True
    assert e2["vol_lt_10"] is True
    frame.iloc[15, frame.columns.get_loc("volume")] = 0
    invalid_prior = analyze_study(frame, config(), study_id="fixed")
    assert event_for(invalid_prior)["volume_evaluable"] is False


def test_reference_entry_is_not_breakout_close_or_execution():
    result = analyze_study(breakout_bars(), config(), study_id="fixed")
    event = event_for(result)
    assert event["reference_entry"] != event["d1_close"]
    assert "execution" not in event
    assert result["reference_entry_label"] == "統計基準進場價，不是實際策略成交價"


def test_post_d1_starts_on_d2_and_post_d2_success_starts_on_d3_without_backfill():
    frame = breakout_bars()
    # The D1 intraday high has already crossed the PCT_3 reference target.
    # That price action is not observable to a post-D1 outcome until D2 Open.
    frame.iloc[16, frame.columns.get_loc("high")] = 104.0
    result = analyze_study(frame, config(), study_id="fixed")
    event = event_for(result)
    rows = [x for x in result["target_outcomes"] if x["event_id"] == event["event_id"] and x["target_type"] == "PCT_3"]
    d1 = next(x for x in rows if x["condition_type"] == "BREAKOUT" and x["observation_origin"] == "POST_D1")
    d2 = next(x for x in rows if x["condition_type"] == "DAY2_SUCCESS" and x["observation_origin"] == "POST_D2_SUCCESS")
    assert event["d1_high"] >= d1["target_level"]
    assert d1["observation_start_date"] == "2021-01-18"
    assert d1["resolution_date"] == "2021-01-18"
    assert d1["resolution_state"] == "SUCCESS_TARGET_FIRST"
    assert d2["condition_known_date"] == "2021-01-18"
    assert d2["observation_start_date"] == "2021-01-19"
    assert event["d2_high"] >= d2["target_level"]
    assert d2["resolution_date"] != "2021-01-18"
    assert d2["resolution_state"] == "RIGHT_CENSORED"
    assert {("BREAKOUT", "POST_D1"), ("DAY2_SUCCESS", "POST_D2_SUCCESS")} <= {
        (row["condition_type"], row["observation_origin"]) for row in rows
    }
    for threshold in (10, 20, 30):
        conditioned = next(x for x in rows if x["condition_type"] == f"DAY2_SUCCESS_AND_VOL_GE_{threshold}"
                           and x["observation_origin"] == "POST_D2_SUCCESS")
        assert conditioned["condition_known_date"] == "2021-01-18"
        assert conditioned["observation_start_date"] == "2021-01-19"
        assert conditioned["resolution_date"] != "2021-01-18"


def test_d2_intraday_target_and_stop_are_not_backfilled_into_post_d2_success():
    frame = breakout_bars(d2_close=104.0, d2_high=105.0, d2_low=90.0)
    result = analyze_study(frame, config(), study_id="d2-no-backfill")
    event = event_for(result)
    rows = [row for row in result["target_outcomes"]
            if row["event_id"] == event["event_id"] and row["target_type"] == "PCT_3"]
    post_d1 = next(row for row in rows if row["condition_type"] == "BREAKOUT"
                   and row["observation_origin"] == "POST_D1")
    post_d2 = next(row for row in rows if row["condition_type"] == "DAY2_SUCCESS"
                   and row["observation_origin"] == "POST_D2_SUCCESS")
    d2_audit = next(row for row in result["target_session_audit"]
                    if row["event_id"] == event["event_id"] and row["target_type"] == "PCT_3"
                    and row["condition_type"] == "BREAKOUT" and row["observation_origin"] == "POST_D1")
    assert frame.iloc[17]["high"] >= post_d1["target_level"]
    assert frame.iloc[17]["low"] <= d2_audit["stop_level"]
    assert post_d1["resolution_date"] == event["d2_date"]
    assert post_d2["observation_start_date"] == "2021-01-19"
    assert post_d2["resolution_date"] != event["d2_date"]
    assert all(row["date"] != event["d2_date"] for row in result["target_session_audit"]
               if row["event_id"] == event["event_id"] and row["observation_origin"] == "POST_D2_SUCCESS")


def test_day2_success_without_d3_is_right_censored():
    frame = breakout_bars().iloc[:18].copy()
    result = analyze_study(frame, config(end=date(2021, 1, 18)), study_id="no-d3")
    event = event_for(result)
    outcome = next(row for row in result["target_outcomes"]
                   if row["event_id"] == event["event_id"] and row["target_type"] == "PCT_3"
                   and row["condition_type"] == "DAY2_SUCCESS"
                   and row["observation_origin"] == "POST_D2_SUCCESS")
    assert event["d2_success"] is True
    assert outcome["resolution_state"] == "RIGHT_CENSORED"
    assert outcome["censor_reason"] == "STUDY_END_BEFORE_OBSERVATION_START"
    assert outcome["observation_start_date"] is None


def test_volume_conditioned_post_d1_target_origin_begins_at_d2_open():
    result = analyze_study(breakout_bars(day1_volume=135.0), config(), study_id="volume-post-d1-origin")
    event = event_for(result)
    rows = [row for row in result["target_outcomes"] if row["event_id"] == event["event_id"]]
    for threshold in (10, 20, 30):
        row = next(item for item in rows if item["target_type"] == "PCT_3"
                   and item["condition_type"] == f"VOL_GE_{threshold}"
                   and item["observation_origin"] == "POST_D1")
        assert row["condition_known_date"] == event["d1_date"]
        assert row["observation_start_date"] == event["d2_date"]


@pytest.mark.parametrize(("direction", "stop_multiple"), [("LONG", 0.985), ("SHORT", 1.015)])
def test_post_d2_success_first_dynamic_stop_uses_d2_completed_ma(direction, stop_multiple):
    frame = pd.DataFrame({
        "open": [100.0, 101.0, 105.0], "high": [101.0, 102.0, 106.0],
        "low": [99.0, 100.0, 104.0], "close": [100.0, 101.5, 105.5],
        "ma": [90.0, 100.0, 110.0],
    }, index=pd.date_range("2021-01-01", periods=3, tz="UTC"))
    event = {"event_id": "d2-stop-origin", "study_id": "s", "direction": direction, "atr14_d1": 2.0}
    target = {"target_type": "PCT_3", "target_level": 200.0 if direction == "LONG" else 50.0, "atr_target": False}
    outcome, audit = _scan_target(frame, event=event, target=target, condition="DAY2_SUCCESS",
                                  origin="POST_D2_SUCCESS", known_i=1, start_i=2)
    expected = frame.iloc[1]["ma"] * stop_multiple
    assert outcome["observation_start_date"] == "2021-01-03"
    assert outcome["first_dynamic_stop"] == pytest.approx(expected)
    assert audit[0]["stop_level"] == pytest.approx(expected)


def test_backend_chart_payload_contains_authoritative_box_volume_target_and_retest_audit():
    close = [100.0] * 36
    close[26:30] = [100.5, 99.5, 100.5, 99.5]
    close[30:33] = [103.0, 102.8, 102.9]
    frame = bars(close, volumes=[100.0] * 30 + [135.0] * 6)
    frame.iloc[26:30, frame.columns.get_loc("high")] = 101.0
    frame.iloc[26:30, frame.columns.get_loc("low")] = 99.0
    cfg = AnalyticsConfig("FIXTURE", 2, 0, 1, frame.index[30].date(), frame.index[-1].date(), "LONG_ONLY", "ALL")
    result = analyze_study(frame, cfg, study_id="chart-audit")
    event = next(row for row in result["events"] if row["d1_date"] == frame.index[30].date().isoformat())
    chart_bar = next(row for row in result["charts"]["2"] if row["date"] == event["d1_date"])
    assert chart_bar["box_active_at_session_start"] is True
    assert chart_bar["box_id_at_session_start"] == "box-2-2021-01-28"
    assert chart_bar["box_high_at_session_start"] is not None
    assert chart_bar["box_low_at_session_start"] is not None
    assert event["volume_change"] == pytest.approx(0.35)
    assert event["vol_ge_10"] and event["vol_ge_20"] and event["vol_ge_30"]
    d1_volume_target = next(row for row in result["target_outcomes"] if row["event_id"] == event["event_id"]
                            and row["target_type"] == "ATR_1.5" and row["condition_type"] == "VOL_GE_20"
                            and row["observation_origin"] == "POST_D1")
    audit = next(row for row in result["target_session_audit"] if row["event_id"] == event["event_id"]
                 and row["target_type"] == "ATR_1.5" and row["condition_type"] == "VOL_GE_20"
                 and row["observation_origin"] == "POST_D1")
    assert d1_volume_target["target_level"] is not None
    assert audit["stop_level"] == pytest.approx(audit["previous_completed_ma"] * 0.985)
    failure = next(row for row in result["failure_outcomes"] if row["event_id"] == event["event_id"])
    assert failure["retest_zone_history"]
    first_zone = failure["retest_zone_history"][0]
    assert first_zone["retest_zone_low"] == pytest.approx(first_zone["ma"] * 0.999)
    assert first_zone["retest_zone_high"] == pytest.approx(first_zone["ma"] * 1.001)


@pytest.mark.parametrize(("direction", "open", "high", "low", "close", "expected"), [
    ("LONG", 96, 101, 95, 100, "FAIL_STOP_FIRST"),
    ("LONG", 104, 105, 101, 102, "SUCCESS_TARGET_FIRST"),
    ("SHORT", 104, 105, 99, 100, "FAIL_STOP_FIRST"),
    ("SHORT", 96, 99, 95, 98, "SUCCESS_TARGET_FIRST"),
])
def test_target_open_gap_rules(direction, open, high, low, close, expected):
    row = pd.Series({"open": open, "high": high, "low": low, "close": close})
    stop, target = ((97.0, 103.0) if direction == "LONG" else (103.0, 97.0))
    assert _path_result(direction, row, stop, target) == (expected, "OPEN_GAP_STOP" if "STOP" in expected else "OPEN_GAP_TARGET")


@pytest.mark.parametrize(("direction", "green", "expected"), [
    ("LONG", True, "FAIL_STOP_FIRST"), ("LONG", False, "SUCCESS_TARGET_FIRST"),
    ("SHORT", True, "SUCCESS_TARGET_FIRST"), ("SHORT", False, "FAIL_STOP_FIRST"),
])
def test_same_day_target_stop_uses_frozen_ohlc_heuristic(direction, green, expected):
    op = 100.0
    cl = 101.0 if green else 99.0
    row = pd.Series({"open": op, "high": 104.0, "low": 96.0, "close": cl})
    stop, target = ((97.0, 103.0) if direction == "LONG" else (103.0, 97.0))
    assert _path_result(direction, row, stop, target)[0] == expected


def test_target_dynamic_stop_is_previous_completed_sma_and_updates_each_day():
    frame = bars([100, 100, 100, 101, 101], highs=[100.2, 100.2, 100.2, 101.2, 101.2], lows=[99.8, 99.8, 99.8, 100.8, 100.8])
    frame["ma"] = [100, 100, 101, 102, 102]
    event = {"event_id": "e", "study_id": "s", "direction": "LONG", "atr14_d1": 1.0}
    outcome, audit = __import__("app.ma_breakout_analytics.engine", fromlist=["_scan_target"])._scan_target(
        frame, event=event, target={"target_type": "PCT_3", "target_level": 130.0, "atr_target": False},
        condition="BREAKOUT", origin="POST_D1", known_i=1, start_i=2)
    assert outcome["first_dynamic_stop"] == pytest.approx(98.5)
    assert audit[1]["stop_level"] == pytest.approx(99.485)
    assert outcome["resolution_state"] == "RIGHT_CENSORED"


def test_short_dynamic_stop_uses_previous_completed_ma():
    frame = bars([100.0] * 5, opens=[100.0] * 5, highs=[100.4] * 5, lows=[99.6] * 5)
    frame["ma"] = [100.0, 101.0, 102.0, 103.0, 104.0]
    event = {"event_id": "short-stop", "study_id": "s", "direction": "SHORT", "atr14_d1": 1.0}
    outcome, audit = _scan_target(
        frame, event=event, target={"target_type": "PCT_3", "target_level": 70.0, "atr_target": False},
        condition="BREAKOUT", origin="POST_D1", known_i=1, start_i=2,
    )
    assert outcome["first_dynamic_stop"] == pytest.approx(101.0 * 1.015)
    assert audit[0]["stop_level"] == pytest.approx(101.0 * 1.015)
    assert audit[1]["stop_level"] == pytest.approx(102.0 * 1.015)


def test_invalid_atr_target_is_not_evaluable_and_percentage_target_remains_available():
    close = [100.0] * 20
    close[7], close[8], close[9] = 99.0, 103.0, 104.0
    result = analyze_study(bars(close), config(), study_id="fixed")
    event = result["events"][0]
    atr = [x for x in result["target_outcomes"] if x["event_id"] == event["event_id"] and x["target_type"] == "ATR_1"]
    pct = [x for x in result["target_outcomes"] if x["event_id"] == event["event_id"] and x["target_type"] == "PCT_3"]
    assert atr and all(x["resolution_state"] == "TARGET_NOT_EVALUABLE_ATR" for x in atr)
    assert pct and all(x["eligible"] for x in pct)


def test_target_families_have_independent_outcomes():
    result = analyze_study(breakout_bars(), config(), study_id="independent-targets")
    event = event_for(result)
    rows = [row for row in result["target_outcomes"] if row["event_id"] == event["event_id"]
            and row["condition_type"] == "BREAKOUT" and row["observation_origin"] == "POST_D1"]
    assert {row["target_type"] for row in rows} == {
        "PCT_3", "ATR_0.5", "ATR_1", "ATR_1.5", "ATR_2", "ATR_3",
    }
    assert len(rows) == len({row["target_type"] for row in rows})


def test_all_atr_targets_use_the_frozen_day1_atr_snapshot():
    levels = _target_levels("LONG", 100.0, 2.0)
    assert [x["target_type"] for x in levels] == ["PCT_3", "ATR_0.5", "ATR_1", "ATR_1.5", "ATR_2", "ATR_3"]
    assert [x["target_level"] for x in levels[1:]] == [101.0, 102.0, 103.0, 104.0, 106.0]
    # Later volatility changes cannot alter a target level already derived from D1 ATR.
    later_atr = [0.25, 50.0, 500.0]
    assert levels[3]["target_level"] == 103.0
    assert later_atr[-1] != 2.0


@pytest.mark.parametrize(("direction", "target_type", "same_bar_result"), [
    (direction, target_type, expected)
    for direction in ("LONG", "SHORT")
    for target_type, expected in (("PCT_3", "SUCCESS_TARGET_FIRST"),
                                  ("ATR_0.5", "SUCCESS_TARGET_FIRST"),
                                  ("ATR_1", "SUCCESS_TARGET_FIRST"),
                                  ("ATR_1.5", "SUCCESS_TARGET_FIRST"),
                                  ("ATR_2", "SUCCESS_TARGET_FIRST"),
                                  ("ATR_3", "SUCCESS_TARGET_FIRST"))
])
def test_scanner_resolves_each_target_family_against_the_dynamic_stop(direction: str, target_type: str,
                                                                        same_bar_result: str):
    levels = {x["target_type"]: x for x in _target_levels(direction, 100.0, 2.0)}
    target = levels[target_type]
    target_level = float(target["target_level"])
    if direction == "LONG":
        row = {"open": 100.0, "high": target_level + 0.1, "low": 99.0, "close": 100.5}
    else:
        row = {"open": 100.0, "high": 101.0, "low": target_level - 0.1, "close": 99.5}
    frame = pd.DataFrame([row] * 3, index=pd.date_range("2021-01-01", periods=3, tz="UTC"))
    frame["ma"] = 100.0
    event = {"event_id": "atr-family", "study_id": "s", "direction": direction, "atr14_d1": 2.0}
    outcome, _ = _scan_target(frame, event=event, target=target, condition="BREAKOUT",
                              origin="POST_D1", known_i=1, start_i=2)
    assert outcome["resolution_state"] == same_bar_result


def test_same_session_green_path_can_stop_before_three_percent_target():
    frame = pd.DataFrame([{"open": 100.0, "high": 104.0, "low": 97.0, "close": 100.2}] * 3,
                         index=pd.date_range("2021-01-01", periods=3, tz="UTC"))
    frame["ma"] = 100.0
    event = {"event_id": "same-bar-stop", "study_id": "s", "direction": "LONG", "atr14_d1": 2.0}
    outcome, _ = _scan_target(frame, event=event,
                              target={"target_type": "PCT_3", "target_level": 103.0, "atr_target": False},
                              condition="BREAKOUT", origin="POST_D1", known_i=1, start_i=2)
    assert outcome["resolution_state"] == "FAIL_STOP_FIRST"


def test_failure_observer_begins_d3_and_does_not_read_d2_intraday():
    frame = failure_frame()
    outcome = _failure_path(frame, failure_event(), 1)
    assert outcome["observation_start_date"] == "2021-01-03"
    assert outcome["terminal_outcome"] in {"SIDEWAYS", "RIGHT_CENSORED"}


def test_failure_observer_has_no_fixed_followup_timeout():
    n = 90
    closes = [110.0, 109.0] + [105.0] * (n - 2)
    opens = closes.copy()
    highs = [110.2, 109.2] + [107.0] * (n - 2)
    lows = [109.8, 108.8] + [102.0] * (n - 2)
    closes[-1], opens[-1], highs[-1], lows[-1] = 110.5, 110.3, 111.0, 110.2
    frame = failure_frame(closes=closes, highs=highs, lows=lows)
    frame["open"] = opens
    result = _failure_path(frame, failure_event(day1_close=110.0), 1)
    assert result["terminal_outcome"] == "TREND_CONTINUATION_AWAY"
    assert result["terminal_date"] == "2021-03-31"


def test_timeout_is_not_a_config_or_request_field():
    config_names = set(AnalyticsConfig.__dataclass_fields__)
    request_names = set(AnalyticsStudyRequest.model_fields)
    assert not any("timeout" in name.lower() or "horizon" in name.lower()
                   for name in config_names | request_names)


def test_failure_volume_aggregate_excludes_right_censored_from_resolved_denominator():
    close = [100.0] * 24
    close[15:22] = [99.0, 103.0, 102.0, 100.0, 99.0, 103.0, 102.0]
    volume = [100.0] * 24
    volume[16] = 120.0
    volume[20] = 120.0
    result = analyze_study(
        bars(close, volumes=volume),
        AnalyticsConfig("FIXTURE", 2, 0, 1, date(2021, 1, 5), date(2021, 1, 22), "LONG_ONLY", "ALL"),
        study_id="censor-denominator",
    )
    row = next(x for x in result["aggregates"] if x["aggregate_type"] == "FAILURE_PATH"
               and x["period"] == 2 and x["condition_type"] == "VOL_GE_10")
    assert row["eligible_count"] == 2
    assert row["resolved_count"] == 1
    assert row["censored_count"] == 1


@pytest.mark.parametrize(("day1_volume", "expected_conditions"), [
    (110.0, {"VOL_GE_10"}),
    (120.0, {"VOL_GE_10", "VOL_GE_20"}),
    (130.0, {"VOL_GE_10", "VOL_GE_20", "VOL_GE_30"}),
])
def test_failure_volume_conditioned_aggregates_are_nested(day1_volume: float, expected_conditions: set[str]):
    frame = breakout_bars(d2_close=102.9, day1_volume=day1_volume)
    result = analyze_study(frame, config(), study_id=f"failure-volume-{day1_volume:g}")
    rows = {x["condition_type"]: x for x in result["aggregates"]
            if x["aggregate_type"] == "FAILURE_PATH" and x["period"] == 2}
    assert all(rows[name]["eligible_count"] == 1 and rows[name]["resolved_count"] == 1
               for name in expected_conditions)
    assert all(rows[name]["eligible_count"] == 0
               for name in {"VOL_GE_10", "VOL_GE_20", "VOL_GE_30"} - expected_conditions)


def test_right_censored_failure_is_excluded_from_failure_probability_denominator():
    frame = breakout_bars(d2_close=102.9, day1_volume=120.0)
    end = frame.index[17].date()
    result = analyze_study(
        frame,
        AnalyticsConfig("FIXTURE", 2, 0, 1, date(2021, 1, 5), end, "LONG_ONLY", "ALL"),
        study_id="censored-failure",
    )
    row = next(x for x in result["aggregates"] if x["aggregate_type"] == "FAILURE_PATH"
               and x["period"] == 2 and x["condition_type"] == "VOL_GE_20")
    assert row["eligible_count"] == 1
    assert row["resolved_count"] == 0
    assert row["censored_count"] == 1
    assert row["probability"] is None
    assert row["status"] == "NOT_EVALUABLE"


def test_return_terminal_precedes_other_failure_outcomes():
    closes = [110, 109, 99.7, 108, 108, 108]
    lows = [x - 0.2 for x in closes]
    highs = [x + 0.2 for x in closes]
    lows[2], highs[2] = 99.6, 100.05
    result = _failure_path(failure_frame(closes=closes, lows=lows, highs=highs), failure_event(), 1)
    assert result["terminal_outcome"] == "RETURN_TO_BEAR"
    assert result["terminal_date"] == "2021-01-03"


def test_return_precedes_sideways_when_both_conditions_are_true():
    closes = [110.0, 109.0, 99.9, 99.9, 99.9, 99.7]
    lows = [109.9, 108.9, 99.5, 99.5, 99.5, 99.5]
    highs = [110.1, 109.1, 100.05, 100.05, 100.05, 100.05]
    frame = failure_frame(closes=closes, lows=lows, highs=highs)
    # The fourth post-D2 bar also completes a narrow four-bar sideways window.
    assert (max(highs[2:6]) - min(lows[2:6])) / frame["atr"].iloc[1] <= 1.5
    result = _failure_path(frame, failure_event(day1_close=110.0), 1)
    assert result["terminal_outcome"] == "RETURN_TO_BEAR"
    assert result["terminal_date"] == "2021-01-06"


def test_retest_precedes_trend_when_both_are_true():
    closes = [100.5, 100.4, 101.0, 101.0, 101.0, 101.0]
    lows = [100.3, 100.2, 100.0, 100.2, 100.2, 100.2]
    highs = [100.7, 100.6, 101.2, 101.2, 101.2, 101.2]
    result = _failure_path(failure_frame(closes=closes, lows=lows, highs=highs), failure_event(day1_close=100.5), 1)
    assert result["terminal_outcome"] == "MA_RETEST_REBOUND"


def test_retest_precedes_sideways_when_both_conditions_are_true():
    closes = [110.0, 109.0, 100.0, 100.0, 100.0, 100.05]
    lows = [109.9, 108.9, 99.95, 99.95, 99.95, 99.95]
    highs = [110.1, 109.1, 100.8, 100.8, 100.8, 100.8]
    frame = failure_frame(closes=closes, lows=lows, highs=highs)
    assert (max(highs[2:6]) - min(lows[2:6])) / frame["atr"].iloc[1] <= 1.5
    result = _failure_path(frame, failure_event(day1_close=110.0), 1)
    assert result["terminal_outcome"] == "MA_RETEST_REBOUND"
    assert result["terminal_date"] == "2021-01-06"


def test_short_retest_rejection_is_the_mirror_terminal():
    frame = failure_frame(closes=[90.0, 91.0, 99.9], lows=[89.8, 90.8, 99.8], highs=[90.2, 91.2, 100.2])
    result = _failure_path(frame, failure_event("SHORT", 90.0), 1)
    assert result["terminal_outcome"] == "MA_RETEST_REJECTION"


def test_trend_away_requires_clear_side_and_new_advance_over_d1_close():
    frame = failure_frame(closes=[100.5, 100.4, 101, 101, 101, 101])
    frame.loc[frame.index[2], ["low", "high"]] = [100.2, 101.2]
    result = _failure_path(frame, failure_event(day1_close=100.5), 1)
    assert result["terminal_outcome"] == "TREND_CONTINUATION_AWAY"
    no_new_advance = _failure_path(frame, failure_event(day1_close=101.0), 1)
    assert no_new_advance["terminal_outcome"] != "TREND_CONTINUATION_AWAY"


def test_long_trend_progress_without_clear_above_is_not_trend_continuation():
    # Close advances past Day 1, but remains below the frozen +0.2% clear-side
    # boundary. Keep the frame short so no later Sideways window can resolve it.
    frame = failure_frame(
        closes=[100.0, 99.9, 100.15],
        lows=[99.9, 99.8, 100.12],
        highs=[100.1, 100.0, 100.25],
    )
    result = _failure_path(frame, failure_event(day1_close=100.1), 1)
    assert frame.iloc[2]["close"] > 100.1
    assert frame.iloc[2]["close"] < frame.iloc[2]["ma"] * 1.002
    assert result["terminal_outcome"] == "RIGHT_CENSORED"


def test_short_trend_progress_without_clear_below_is_not_trend_continuation():
    # Mirror case: Close moves below Day 1 but not far enough to be CLEAR BELOW.
    frame = failure_frame(
        closes=[100.0, 100.1, 99.85],
        lows=[99.9, 100.0, 99.82],
        highs=[100.1, 100.2, 99.88],
    )
    result = _failure_path(frame, failure_event("SHORT", day1_close=99.9), 1)
    assert frame.iloc[2]["close"] < 99.9
    assert frame.iloc[2]["close"] > frame.iloc[2]["ma"] * 0.998
    assert result["terminal_outcome"] == "RIGHT_CENSORED"


def test_trend_continuation_precedes_sideways_when_both_conditions_are_true():
    closes = [100.25, 100.25, 100.25, 100.25, 100.25, 100.30]
    lows = [100.2] * len(closes)
    highs = [101.0] * len(closes)
    frame = failure_frame(closes=closes, lows=lows, highs=highs)
    # On the terminal bar, both the new-advance trend condition and the
    # completed four-bar range condition are true; Rev3 gives Trend priority.
    assert (max(highs[2:6]) - min(lows[2:6])) / frame["atr"].iloc[1] <= 1.5
    result = _failure_path(frame, failure_event(day1_close=100.29), 1)
    assert result["terminal_outcome"] == "TREND_CONTINUATION_AWAY"
    assert result["terminal_date"] == "2021-01-06"


def test_trend_away_does_not_use_day1_high_or_low_gate():
    frame = failure_frame(closes=[100.5, 100.4, 101.0, 101.0, 101.0, 101.0])
    frame.loc[frame.index[2], ["low", "high"]] = [100.3, 101.2]
    result = _failure_path(frame, failure_event(day1_close=100.5), 1)
    assert result["terminal_outcome"] == "TREND_CONTINUATION_AWAY"


def test_short_trend_away_requires_clear_side_and_a_new_d1_low_close():
    frame = failure_frame(closes=[90.0, 91.0, 89.5], lows=[89.8, 90.8, 89.3], highs=[90.2, 91.2, 89.7])
    result = _failure_path(frame, failure_event("SHORT", 90.0), 1)
    assert result["terminal_outcome"] == "TREND_CONTINUATION_AWAY"
    no_new_advance = _failure_path(frame, failure_event("SHORT", 89.5), 1)
    assert no_new_advance["terminal_outcome"] != "TREND_CONTINUATION_AWAY"


def sideways_candidate(*, spread: float = 0.5, below_ma: bool = False,
                       atr_values: list[float] | None = None) -> pd.DataFrame:
    close = [110.0, 109.0] + ([99.85] * 5 if below_ma else [108.0] * 5)
    if below_ma:
        low, high = [109.9, 108.9] + [99.80] * 5, [110.1, 109.1] + [99.80 + spread] * 5
    else:
        low, high = [109.9, 108.9] + [107.0] * 5, [110.1, 109.1] + [107.0 + spread] * 5
    frame = failure_frame(closes=close, lows=low, highs=high,
                          atr=atr_values if atr_values is not None else [1.0] * len(close))
    return frame


def test_sideways_is_independent_of_ma_entanglement_and_can_be_above_ma():
    frame = sideways_candidate(spread=0.5)
    result = _failure_path(frame, failure_event(day1_close=110.0), 1)
    assert result["terminal_outcome"] == "SIDEWAYS"
    assert result["sideways_window_bars"] == 4
    assert result["sideways_window_start"] == "2021-01-03"
    assert result["sideways_atr_reference_date"] == "2021-01-02"
    assert result["sideways_window_low"] > result["terminal_ma"]
    snapshots = _read_only_entanglement_snapshots(frame, 2)
    assert all(snapshot["entanglement_cohort"] == "CLEAN" for snapshot in snapshots)


def test_sideways_can_be_below_ma_without_triggering_return_or_retest():
    frame = sideways_candidate(spread=0.05, below_ma=True)
    result = _failure_path(frame, failure_event(day1_close=110.0), 1)
    assert result["terminal_outcome"] == "SIDEWAYS"
    assert result["sideways_window_high"] < 99.9


def test_sideways_requires_exactly_four_followup_bars():
    frame = sideways_candidate(spread=0.5).iloc[:5].copy()
    result = _failure_path(frame, failure_event(day1_close=110.0), 1)
    assert result["terminal_outcome"] == "RIGHT_CENSORED"


@pytest.mark.parametrize(("spread", "expected"), [(1.5, "SIDEWAYS"), (1.5001, "RIGHT_CENSORED")])
def test_sideways_range_atr_threshold_is_inclusive(spread: float, expected: str):
    frame = sideways_candidate(spread=spread)
    result = _failure_path(frame, failure_event(day1_close=110.0), 1)
    assert result["terminal_outcome"] == expected


def test_invalid_sideways_atr_skips_window_and_keeps_observing():
    atr = [1.0, np.nan, 1.0, 1.0, 1.0, 1.0, 1.0]
    frame = sideways_candidate(spread=0.5, atr_values=atr)
    result = _failure_path(frame, failure_event(day1_close=110.0), 1)
    assert result["terminal_outcome"] == "SIDEWAYS"
    assert result["sideways_window_start"] == "2021-01-04"


def test_sideways_uses_pre_window_atr14_snapshot():
    # The first candidate's pre-window ATR is 0.2, so its 0.5 range is too
    # wide. The next candidate must use the ATR at its own pre-window close
    # (1.0), not the start bar's 0.2 or any in-window value (50.0).
    frame = sideways_candidate(spread=0.5, atr_values=[1.0, 0.2, 1.0, 0.2, 50.0, 50.0, 50.0])
    result = _failure_path(frame, failure_event(day1_close=110.0), 1)
    assert result["terminal_outcome"] == "SIDEWAYS"
    assert result["sideways_window_start"] == "2021-01-04"
    assert result["sideways_atr_reference_date"] == "2021-01-03"
    assert result["sideways_atr14"] == pytest.approx(1.0)


def test_entangled_signal_can_resolve_without_sideways():
    close = [100.0] * 36
    close[26:30] = [100.5, 99.5, 100.5, 99.5]
    close[30:34] = [103.0, 102.0, 104.0, 104.0]
    frame = bars(close)
    frame.iloc[26:30, frame.columns.get_loc("high")] = 101.0
    frame.iloc[26:30, frame.columns.get_loc("low")] = 99.0
    start = frame.index[30].date()
    result = analyze_study(
        frame,
        AnalyticsConfig("FIXTURE", 2, 0, 1, start, frame.index[-1].date(), "LONG_ONLY", "ALL"),
        study_id="entangled-not-sideways",
    )
    event = next(row for row in result["events"] if row["d1_date"] == start.isoformat())
    failure = next(row for row in result["failure_outcomes"] if row["event_id"] == event["event_id"])
    assert event["entanglement_cohort"] == "ENTANGLED_AT_SIGNAL"
    assert failure["terminal_outcome"] == "TREND_CONTINUATION_AWAY"
    assert failure["terminal_outcome"] != "SIDEWAYS"


@pytest.mark.parametrize(("direction", "day1", "d2", "d3", "expected"), [
    ("LONG", 110, 109, 99, "RETURN_TO_BEAR"),
    ("SHORT", 90, 91, 101, "RETURN_TO_BULL"),
])
def test_failure_return_mirrors_by_direction(direction, day1, d2, d3, expected):
    close = [day1, d2, d3, d3, d3, d3]
    frame = failure_frame(closes=close)
    result = _failure_path(frame, failure_event(direction, day1), 1)
    assert result["terminal_outcome"] == expected


def test_target_observer_has_no_fixed_horizon():
    frame = bars([100.0] * 80)
    frame["ma"] = 100.0
    event = {"event_id": "e", "study_id": "s", "direction": "LONG", "atr14_d1": 1.0}
    outcome, audit = __import__("app.ma_breakout_analytics.engine", fromlist=["_scan_target"])._scan_target(
        frame, event=event, target={"target_type": "PCT_3", "target_level": 130.0, "atr_target": False},
        condition="BREAKOUT", origin="POST_D1", known_i=0, start_i=1)
    assert outcome["resolution_state"] == "RIGHT_CENSORED"
    assert len(audit) == 79


def test_volume_and_day2_probability_denominators_are_explicit():
    result = analyze_study(breakout_bars(), config(), study_id="fixed")
    rows = {x["condition_type"]: x for x in result["aggregates"] if x["aggregate_type"] == "PROBABILITY" and x["period"] == 2}
    assert rows["DAY2_SUCCESS"]["eligible_count"] >= 1
    assert rows["VOLUME_GE_20"]["eligible_count"] >= 1
    assert rows["DAY2_AND_VOL_GE_20"]["eligible_count"] >= 1
    joint = [event for event in result["events"] if event["sma_period"] == 2
             and event["d2_evaluable"] and event["volume_evaluable"]]
    assert rows["DAY2_AND_VOL_GE_20"]["eligible_count"] == len(joint)
    assert {member["event_id"] for member in rows["DAY2_AND_VOL_GE_20"]["members"]
            if member["membership_type"] == "ELIGIBLE"} == {event["event_id"] for event in joint}
    expected_successes = sum(event["d2_success"] and event["vol_ge_20"] for event in joint)
    assert rows["DAY2_AND_VOL_GE_20"]["success_count"] == expected_successes


def test_target_aggregate_membership_supports_denominator_and_numerator_drilldown():
    result = analyze_study(breakout_bars(), config(), study_id="fixed")
    row = next(x for x in result["aggregates"] if x["aggregate_type"] == "TARGET" and
               x["target_type"] == "PCT_3" and x["condition_type"] == "BREAKOUT" and x["observation_origin"] == "POST_D1")
    assert row["eligible_count"] == sum(x["membership_type"] == "ELIGIBLE" for x in row["members"])
    assert any(x["membership_type"] == "NUMERATOR" for x in row["members"])
    assert any(x["membership_type"] == "RESOLVED" for x in row["members"])


def test_target_aggregates_do_not_mix_observation_origins():
    result = analyze_study(breakout_bars(), config(), study_id="origin-aggregates")
    rows = [row for row in result["aggregates"] if row["aggregate_type"] == "TARGET"
            and row["target_type"] == "PCT_3"
            and row["condition_type"] in {"BREAKOUT", "DAY2_SUCCESS"}]
    identities = {(row["condition_type"], row["observation_origin"]) for row in rows}
    assert ("BREAKOUT", "POST_D1") in identities
    assert ("DAY2_SUCCESS", "POST_D2_SUCCESS") in identities
    assert all(row["aggregate_id"].endswith(
        f":{row['condition_type']}:{row['target_type']}:{row['observation_origin']}"
    ) for row in rows)
    for aggregate in rows:
        eligible_ids = {member["event_id"] for member in aggregate["members"]
                        if member["membership_type"] == "ELIGIBLE"}
        outcome_ids = {outcome["event_id"] for outcome in result["target_outcomes"]
                       if outcome["target_type"] == aggregate["target_type"]
                       and outcome["condition_type"] == aggregate["condition_type"]
                       and outcome["observation_origin"] == aggregate["observation_origin"]
                       and outcome.get("eligible", True)}
        assert eligible_ids == outcome_ids


def test_failure_combined_count_reconciles_to_mutually_exclusive_classes():
    close = [110, 109, 99.7, 108, 108, 108]
    frame = failure_frame(closes=close)
    cfg = AnalyticsConfig("FIXTURE", 2, 0, 1, date(2021, 1, 1), date(2021, 1, 6), "LONG_ONLY", "ALL")
    result = analyze_study(frame.assign(volume=100), cfg, study_id="fixed")
    for summary in result["period_summary"]:
        if summary["failure_resolved"]:
            assert summary["failure_combined_count"] == (summary["failure_retest_count"] + summary["failure_return_count"] + summary["failure_sideways_count"])


def test_wilson_ci_and_low_sample_contract():
    result = wilson(10, 20)
    assert result["probability"] == 0.5
    assert result["wilson_lower"] == pytest.approx(0.2993, abs=0.001)
    assert result["wilson_upper"] == pytest.approx(0.7007, abs=0.001)
    assert result["low_sample_size"] is False
    assert wilson(1, 5)["low_sample_size"] is True
    assert wilson(0, 0)["status"] == "NOT_EVALUABLE"


def test_long_short_are_not_pooled():
    result = analyze_study(breakout_bars(), AnalyticsConfig("FIXTURE", 2, 0, 1, date(2021, 1, 5), date(2021, 1, 30), "LONG_SHORT_SPLIT", "ALL"), study_id="fixed")
    directions = {x["direction"] for x in result["events"]}
    assert directions <= {"LONG", "SHORT"}
    aggregates = [x for x in result["aggregates"] if x["aggregate_type"] == "PROBABILITY"]
    assert {x["direction"] for x in aggregates} == {"LONG", "SHORT"}


def test_entanglement_cohort_modes_filter_only_signal_snapshot():
    result = analyze_study(breakout_bars(), AnalyticsConfig("FIXTURE", 2, 0, 1, date(2021, 1, 5), date(2021, 1, 30), "LONG_ONLY", "SPLIT_ENTANGLED_CLEAN"), study_id="fixed")
    event_cohorts = {e["entanglement_cohort"] for e in result["events"]}
    aggregate_cohorts = {x["entanglement_cohort"] for x in result["aggregates"]}
    assert event_cohorts <= {"CLEAN", "ENTANGLED_AT_SIGNAL"}
    assert aggregate_cohorts <= {"CLEAN", "ENTANGLED_AT_SIGNAL"}


def test_clean_signal_is_classified_outside_the_entanglement_cohort():
    event = event_for(analyze_study(breakout_bars(), config(), study_id="clean-cohort"))
    assert event["box_active_at_session_start"] is False
    assert event["box_formed_on_day1_close"] is False
    assert event["entanglement_cohort"] == "CLEAN"


def test_pre_evaluation_box_warmup_is_included_in_breakout_cohort_snapshot():
    close = [100.0] * 36
    close[26:30] = [100.5, 99.5, 100.5, 99.5]
    close[30] = 103.0
    frame = bars(close)
    frame.iloc[26:30, frame.columns.get_loc("high")] = 101.0
    frame.iloc[26:30, frame.columns.get_loc("low")] = 99.0
    start = frame.index[30].date()
    result = analyze_study(
        frame,
        AnalyticsConfig("FIXTURE", 2, 0, 1, start, frame.index[-1].date(), "LONG_ONLY", "ALL"),
        study_id="warmup-entanglement",
    )
    event = next(x for x in result["events"] if x["d1_date"] == start.isoformat())
    assert event["box_active_at_session_start"] is True
    assert event["entanglement_cohort"] == "ENTANGLED_AT_SIGNAL"


def test_entanglement_formed_after_day1_does_not_backpaint_cohort():
    frame = breakout_bars()
    later_closes = [104.0, 102.0, 104.0, 102.0]
    frame.iloc[18:22, frame.columns.get_loc("close")] = later_closes
    frame.iloc[18:22, frame.columns.get_loc("open")] = later_closes
    frame.iloc[18:22, frame.columns.get_loc("high")] = 105.0
    frame.iloc[18:22, frame.columns.get_loc("low")] = 101.0
    result = analyze_study(frame, config(), study_id="post-d1-entanglement")
    original = event_for(result, "2021-01-17")
    later = event_for(result, "2021-01-21")
    assert original["entanglement_cohort"] == "CLEAN"
    assert original["box_active_at_session_start"] is False
    assert original["box_formed_on_day1_close"] is False
    assert later["entanglement_cohort"] == "ENTANGLED_AT_SIGNAL"


def test_same_study_result_is_deterministic_for_fixed_identity():
    frame = breakout_bars()
    cfg = config()
    runs = [analyze_study(frame.copy(), cfg, study_id="same") for _ in range(3)]
    payloads = [json.dumps(result, sort_keys=True, separators=(",", ":")) for result in runs]
    assert payloads[0] == payloads[1] == payloads[2]
    assert len({hashlib.sha256(value.encode()).hexdigest() for value in payloads}) == 1


def test_all_first_class_results_carry_explicit_study_provenance():
    result = analyze_study(breakout_bars(d2_close=103.0), config(), study_id="provenance")
    expected = {
        "study_id": result["study_id"],
        "analytics_revision": result["analytics_revision"],
        "spec_revision": result["spec_revision"],
        "spec_revision_number": result["spec_revision_number"],
        "spec_hash": result["spec_hash"],
        "config_hash": result["config_hash"],
        "data_fingerprint": result["data_fingerprint"],
    }
    for collection_name in ("events", "target_outcomes", "failure_outcomes", "aggregates"):
        rows = result[collection_name]
        assert rows, collection_name
        assert all({key: row[key] for key in expected} == expected for row in rows), collection_name
    assert all(row["study_id"] == result["study_id"] for row in result["target_session_audit"])


def test_future_data_mutation_cannot_change_prior_day1_or_day2_event_fields():
    original = breakout_bars()
    changed = original.copy()
    changed.iloc[20:, changed.columns.get_loc("open")] *= 1.25
    changed.iloc[20:, changed.columns.get_loc("high")] *= 1.25
    changed.iloc[20:, changed.columns.get_loc("low")] *= 1.25
    changed.iloc[20:, changed.columns.get_loc("close")] *= 1.25
    a = analyze_study(original, config(), study_id="fixed")
    b = analyze_study(changed, config(), study_id="fixed")
    ea, eb = event_for(a), event_for(b)
    for key in ("d1_date", "ma_d1", "ma_d1_previous", "d2_date", "d2_close", "d2_success",
                "atr14_d1", "atr14_snapshot_date", "reference_entry", "entanglement_cohort",
                "box_active_at_session_start", "box_formed_on_day1_close", "entanglement_box_high", "entanglement_box_low"):
        assert ea[key] == eb[key]
    atr_targets_a = [x for x in a["target_outcomes"] if x["event_id"] == ea["event_id"] and x["target_type"].startswith("ATR_")]
    atr_targets_b = [x for x in b["target_outcomes"] if x["event_id"] == eb["event_id"] and x["target_type"].startswith("ATR_")]
    assert [(x["target_level"], x["atr_snapshot"]) for x in atr_targets_a] == [
        (x["target_level"], x["atr_snapshot"]) for x in atr_targets_b
    ]


def test_future_bars_after_failure_terminal_do_not_rewrite_terminal_snapshot():
    original = sideways_candidate(spread=0.5)
    extended = pd.concat([original, failure_frame(closes=[108.0] * 30).iloc[7:]])
    changed = extended.copy()
    changed.iloc[7:, changed.columns.get_loc("high")] *= 3
    changed.iloc[7:, changed.columns.get_loc("low")] *= 0.5
    baseline = _failure_path(extended, failure_event(day1_close=110.0), 1)
    mutated = _failure_path(changed, failure_event(day1_close=110.0), 1)
    assert baseline["terminal_outcome"] == mutated["terminal_outcome"] == "SIDEWAYS"
    assert baseline["terminal_date"] == mutated["terminal_date"]
    assert baseline["sideways_window_dates"] == mutated["sideways_window_dates"]


def test_period_runs_are_independent_and_combined_run_matches_standalone_metrics():
    frame = breakout_bars()
    combined = analyze_study(frame, AnalyticsConfig("FIXTURE", 3, 1, 1, date(2021, 1, 5), date(2021, 1, 30), "LONG_ONLY", "ALL"), study_id="fixed")
    standalone = analyze_study(frame, AnalyticsConfig("FIXTURE", 3, 0, 1, date(2021, 1, 5), date(2021, 1, 30), "LONG_ONLY", "ALL"), study_id="fixed")
    assert [{k: v for k, v in row.items() if k != "config_hash"} for row in combined["events"] if row["sma_period"] == 3] == [
        {k: v for k, v in row.items() if k != "config_hash"} for row in standalone["events"] if row["sma_period"] == 3
    ]
    period3_ids = {e["event_id"] for e in combined["events"] if e["sma_period"] == 3}
    for key in ("target_outcomes", "target_session_audit", "failure_outcomes"):
        assert [{k: v for k, v in x.items() if k != "config_hash"}
                for x in combined[key] if x["event_id"] in period3_ids] == [
            {k: v for k, v in x.items() if k != "config_hash"}
            for x in standalone[key] if x["event_id"] in period3_ids
        ]
    assert combined["charts"]["3"] == standalone["charts"]["3"]
    assert [{k: v for k, v in x.items() if k != "config_hash"}
            for x in combined["aggregates"] if x["period"] == 3] == [
        {k: v for k, v in x.items() if k != "config_hash"}
        for x in standalone["aggregates"] if x["period"] == 3
    ]


def test_analytics_does_not_modify_ma_box_source():
    path = Path(__file__).parents[1] / "app" / "ma_box" / "engine.py"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    analyze_study(breakout_bars(), config(), study_id="fixed")
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    assert before == after


def test_analytics_keeps_frozen_canonical_and_legacy_source_hashes():
    root = Path(__file__).parents[1]
    expected = {
        "app/backtest/execution.py": "6883ab436e4cc5bbf5c988aaa2ddb7fb5b3eddbb75ce91ee23ce384129a153ad",
        "app/backtest/portfolio.py": "244203e4bb000ac5c723e288ab6457e9b5e1bf39b3940629ed9d9abd525e5d4e",
        "app/backtest/indicators.py": "c7ba15b4c0c2a19e8880ef4827c170d8f64ffbcefd558464e5054157e38b2926",
        "app/backtest/engine.py": "070729788e573e57d2d50ff17c3ed73c7a7ca7d9c3ab3daa000d4e5edd34997f",
        "app/backtest/models.py": "0a88652416ddd272ecffc202358ba30f435bf7e8d83a5b53236abdf9308e98d1",
        "app/backtest/strategies/simple_ma_breakout.py": "396afef2a6cf70977aa9ab2f43bf417e17459bc7dd20260c94e5a4a8e0e8f59e",
        "app/backtest/strategies/advanced_ma_breakout.py": "bfd021e54b45b72ab4a679e83e494b924691b21f6abca05beb83786e56f6d7b8",
        "app/backtest/strategies/advanced_day1_stop.py": "a311dfc64abbbf37d3d1b4f30cc9b19879fe8e0f71c73c4c52853aeccbd4e737",
        "app/backtest/metrics.py": "70cc400f0af825649456872bba549e130ab6db93773b5878a83b4d97cfaafed5",
        "app/ma_box/engine.py": "4bf351516e97cc1cc3a72524af8e9aced6b79e76321371aaaa97268ea6b80a01",
    }
    assert {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in expected} == expected


def test_spec_artifact_sidecar_identity_and_encoding():
    spec_root = Path(__file__).parents[2] / "research" / "specs"
    path = spec_root / "MA_BREAKOUT_ANALYTICS_V1_REVISION_3.md"
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in raw
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    source_a = spec_root / "MA_BREAKOUT_ANALYTICS_V1_REVISION_2_SOL_FROZEN_OUTPUT.txt"
    source_b = spec_root / "MA_BREAKOUT_ANALYTICS_V1_REVISION_3_SOL_FROZEN_AMENDMENT.txt"
    raw_a, raw_b = source_a.read_bytes(), source_b.read_bytes()
    assert len(raw_a) == 21855
    assert hashlib.sha256(raw_a).hexdigest() == "f01a50e304db4e654c57a0cfb560dc98ddc0a34aa478cd6248aa498f6434c69d"
    assert len(raw_b) == 10759
    assert hashlib.sha256(raw_b).hexdigest() == "a1b80bfd9db2b4d6d1d252d050573eaf4bf40e535d698d2fee7fda38bf3b4448"
    normalized_a = raw_a.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    normalized_b = raw_b.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    assert len(normalized_a) == 20862
    assert hashlib.sha256(normalized_a).hexdigest() == "d5d08500af89fce61c33c9004af23f4656bb677be10462a32c8a26641eaf66ec"
    assert len(normalized_b) == 10270
    assert hashlib.sha256(normalized_b).hexdigest() == "80c913dd26cb0adef57e259a4660da48bb681406e0ec25cfa947ebebdae485f1"

    marker_a = b"<!-- BEGIN SOURCE A: AUTHORITATIVE SOL FROZEN REVISION 2 OUTPUT -->\n"
    end_a = b"\n<!-- END SOURCE A -->"
    marker_b = b"<!-- BEGIN SOURCE B: AUTHORITATIVE SOL FROZEN REVISION 3 AMENDMENT -->\n"
    end_b = b"\n<!-- END SOURCE B -->"
    section_a = raw.split(marker_a, 1)[1].split(end_a, 1)[0]
    section_b = raw.split(marker_b, 1)[1].split(end_b, 1)[0]
    assert section_a == normalized_a
    assert section_b == normalized_b

    expected = "0ac4a0fad9cbbc747b104b19e420e35368937e3359fd462786bd6317ad0d7647"
    sidecar = path.with_suffix(".sha256").read_text(encoding="ascii").split()[0]
    manifest = json.loads((spec_root / "MA_BREAKOUT_ANALYTICS_V1_REVISION_3_SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(raw).hexdigest() == sidecar == spec_sha256() == expected
    assert manifest["sources"]["revision_2_master"]["raw_sha256"] == hashlib.sha256(raw_a).hexdigest()
    assert manifest["sources"]["revision_2_master"]["normalized_sha256"] == hashlib.sha256(normalized_a).hexdigest()
    assert manifest["sources"]["revision_3_amendment"]["raw_sha256"] == hashlib.sha256(raw_b).hexdigest()
    assert manifest["sources"]["revision_3_amendment"]["normalized_sha256"] == hashlib.sha256(normalized_b).hexdigest()


def test_targeted_sma23_ma_path_mutation_cannot_change_sma24_or_25_execution_state(monkeypatch):
    n = 155
    close = [100.0] * 45 + [100.0 - 1.5 * i for i in range(15)] + [77.5 + 0.8 * i for i in range(n - 60)]
    frame = bars(close)
    cfg = AnalyticsConfig("FIXTURE", 24, 1, 1, frame.index[30].date(), frame.index[-1].date(), "LONG_SHORT_SPLIT", "ALL")
    baseline = analyze_study(frame.copy(), cfg, study_id="period-isolation")

    original_moving_average = analytics_engine.moving_average

    def perturb_sma23(series, period, ma_type):
        values = original_moving_average(series, period, ma_type)
        if period == 23:
            values = values.copy()
            valid = values.notna()
            values.loc[valid] = values.loc[valid] + 20.0
        return values

    monkeypatch.setattr(analytics_engine, "moving_average", perturb_sma23)
    changed = analyze_study(frame.copy(), cfg, study_id="period-isolation")

    def project(result, period):
        events = [event for event in result["events"] if event["sma_period"] == period]
        event_ids = {event["event_id"] for event in events}
        return json.dumps({
            "events": events,
            "targets": [row for row in result["target_outcomes"] if row["event_id"] in event_ids],
            "audit": [row for row in result["target_session_audit"] if row["event_id"] in event_ids],
            "failures": [row for row in result["failure_outcomes"] if row["event_id"] in event_ids],
            "aggregates": [row for row in result["aggregates"] if row["period"] == period],
            "summary": [row for row in result["period_summary"] if row["period"] == period],
            "chart": result["charts"][str(period)],
        }, sort_keys=True, separators=(",", ":"))

    baseline23, changed23 = project(baseline, 23), project(changed, 23)
    assert baseline23 != changed23
    assert [event for event in baseline["events"] if event["sma_period"] == 23] != [
        event for event in changed["events"] if event["sma_period"] == 23
    ]
    for period in (24, 25):
        assert project(baseline, period) == project(changed, period)


class SyntheticProvider(DataProvider):
    def __init__(self, frame: pd.DataFrame, fail: bool = False):
        self.frame, self.fail = frame, fail

    def get_daily(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        if self.fail:
            raise RuntimeError("fixture provider failure")
        return self.frame[(self.frame.index.date >= start) & (self.frame.index.date <= end)]


def test_dedicated_persistence_lifecycle_and_event_tables(tmp_path):
    repo = AnalyticsRepository(tmp_path / "analytics.sqlite3")
    frame = breakout_bars(d2_close=103.0)
    result = analyze_study(frame, config(), provider="synthetic", study_id="persisted")
    repo.create_running(study_id="persisted", config=result["config"], analytics_revision=result["analytics_revision"],
                        spec_revision=result["spec_revision"], spec_revision_number=3,
                        spec_hash=result["spec_hash"], config_hash=result["config_hash"])
    assert repo.get_study("persisted")["status"] == "RUNNING"
    repo.complete("persisted", result)
    saved = repo.get_study("persisted")
    assert saved["status"] == "COMPLETED"
    assert saved["spec_revision_number"] == 3
    counts = repo.counts()
    assert counts["ma_breakout_analytics_events"] == len(result["events"])
    assert counts["ma_breakout_target_outcomes"] == len(result["target_outcomes"])
    assert counts["ma_breakout_target_session_audit"] == len(result["target_session_audit"])
    identity = {key: result[key] for key in (
        "study_id", "analytics_revision", "spec_revision", "spec_revision_number",
        "spec_hash", "config_hash", "data_fingerprint",
    )}
    persisted_fields = (
        ("ma_breakout_analytics_events", "event_json"),
        ("ma_breakout_target_outcomes", "outcome_json"),
        ("ma_breakout_failure_outcomes", "outcome_json"),
        ("ma_breakout_aggregates", "aggregate_json"),
    )
    with repo.connect() as db:
        for table, column in persisted_fields:
            raw = db.execute(f"SELECT {column} FROM {table} LIMIT 1").fetchone()[0]
            record = json.loads(raw)
            assert {key: record[key] for key in identity} == identity, table
        audit_study_id = db.execute("SELECT study_id FROM ma_breakout_target_session_audit LIMIT 1").fetchone()[0]
        assert audit_study_id == result["study_id"]


def test_target_outcome_identity_includes_observation_origin(tmp_path):
    repo = AnalyticsRepository(tmp_path / "origin-identity.sqlite3")
    result = analyze_study(breakout_bars(), config(), provider="synthetic", study_id="origin-identity")
    repo.create_running(
        study_id="origin-identity", config=result["config"], analytics_revision=result["analytics_revision"],
        spec_revision=result["spec_revision"], spec_revision_number=result["spec_revision_number"],
        spec_hash=result["spec_hash"], config_hash=result["config_hash"],
    )
    repo.complete("origin-identity", result)
    with repo.connect() as db:
        pk_info = sorted(
            (row for row in db.execute("PRAGMA table_info(ma_breakout_target_outcomes)") if row["pk"]),
            key=lambda row: row["pk"],
        )
        assert [row["name"] for row in pk_info] == [
            "study_id", "event_id", "target_type", "condition_type", "observation_origin",
        ]
        persisted_origins = {
            (row["condition_type"], row["observation_origin"])
            for row in db.execute(
                "SELECT condition_type, observation_origin FROM ma_breakout_target_outcomes "
                "WHERE study_id=? AND target_type='PCT_3'",
                (result["study_id"],),
            )
        }
        assert ("BREAKOUT", "POST_D1") in persisted_origins
        assert ("DAY2_SUCCESS", "POST_D2_SUCCESS") in persisted_origins


def test_api_create_summary_events_chart_and_exports_use_dedicated_store(tmp_path):
    frame = breakout_bars(d2_close=102.9)
    app = FastAPI()
    app.include_router(router)
    app.state.ma_breakout_analytics_repository = AnalyticsRepository(tmp_path / "api.sqlite3")
    app.state.provider = SyntheticProvider(frame)
    with TestClient(app) as client:
        created = client.post("/api/ma-analytics/studies", json={
            "ticker": "fixture", "selected_ma": 2, "nearby_range": 0, "step": 1,
            "start_date": "2021-01-05", "end_date": "2021-01-30",
            "direction_mode": "LONG_ONLY", "entanglement_mode": "ALL",
        })
        assert created.status_code == 201, created.text
        data = created.json()
        study_id = data["study_id"]
        assert data["spec_revision_number"] == 3
        assert client.get("/api/ma-analytics/studies").status_code == 200
        assert client.get(f"/api/ma-analytics/studies/{study_id}").status_code == 200
        assert client.get(f"/api/ma-analytics/studies/{study_id}/summary").status_code == 200
        events = client.get(f"/api/ma-analytics/studies/{study_id}/events").json()["events"]
        assert events
        event_id = events[0]["event_id"]
        assert client.get(f"/api/ma-analytics/studies/{study_id}/events/{event_id}").status_code == 200
        assert client.get(f"/api/ma-analytics/studies/{study_id}/targets").status_code == 200
        assert client.get(f"/api/ma-analytics/studies/{study_id}/failure-paths").status_code == 200
        chart_response = client.get(f"/api/ma-analytics/studies/{study_id}/chart/2")
        assert chart_response.status_code == 200
        chart = chart_response.json()
        assert {"box_id_at_session_start", "box_high_at_session_start", "box_low_at_session_start"} <= set(chart["daily_data"][0])
        assert chart["events"][0]["reference_entry"] > 0
        assert {row["target_type"] for row in chart["target_outcomes"]} >= {"PCT_3", "ATR_0.5", "ATR_1.5", "ATR_3"}
        assert chart["target_session_audit"]
        assert chart["failures"][0]["retest_zone_history"]
        aggregates = client.get(f"/api/ma-analytics/studies/{study_id}/summary").json()["aggregates"]
        aggregate_id = next(x["aggregate_id"] for x in aggregates if x["members"])
        assert client.get(f"/api/ma-analytics/studies/{study_id}/aggregates/{aggregate_id}/members").status_code == 200
        assert client.get(f"/api/ma-analytics/studies/{study_id}/export?format=json").status_code == 200
        assert client.get(f"/api/ma-analytics/studies/{study_id}/export?format=events.csv").status_code == 200
        assert client.get(f"/api/ma-analytics/studies/{study_id}/export?format=aggregates.csv").status_code == 200
        assert client.get("/api/ma-analytics/studies/not-found").status_code == 404


def test_api_provider_failure_persists_sanitized_failed_study(tmp_path):
    app = FastAPI()
    app.include_router(router)
    repo = AnalyticsRepository(tmp_path / "failed.sqlite3")
    app.state.ma_breakout_analytics_repository = repo
    app.state.provider = SyntheticProvider(breakout_bars(), fail=True)
    with TestClient(app) as client:
        response = client.post("/api/ma-analytics/studies", json={
            "ticker": "fixture", "selected_ma": 2, "nearby_range": 0, "step": 1,
            "start_date": "2021-01-05", "end_date": "2021-01-30",
        })
        assert response.status_code == 500
        row = repo.list_studies()[0]
        assert row["status"] == "FAILED"
        assert row["error_message"] == "MA_BREAKOUT_ANALYTICS_V1 study failed."
