from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from app.backtest.execution import ConservativeIntrabarPolicy
from app.backtest.indicators import add_indicators
from app.backtest.models import AdvancedStrategyState, StrategyParameters, StrategyState
from app.backtest.strategies.advanced_ma_breakout import AdvancedMABreakout
from app.backtest.strategies.base import Bar, EventRecorder
from app.backtest.strategies.simple_ma_breakout import SimpleMABreakout


NOW = datetime(2025, 1, 8, 10, 0, tzinfo=timezone.utc)


class Fills:
    def __init__(self):
        self.items = []

    def __call__(self, side, raw, qty, event, reason, timestamp):
        self.items.append({"side": side, "raw": raw, "qty": qty, "event": event, "reason": reason})


def bar(open_=100, high=100, low=100, close=100, day=8):
    return Bar(NOW.replace(day=day), open_, high, low, close, 1_000)


def advanced(qty=100, entry=100, state=StrategyState.LONG_NORMAL, **overrides):
    strategy = AdvancedMABreakout(StrategyParameters(), EventRecorder())
    strategy.s = AdvancedStrategyState(
        state=state,
        q0=overrides.pop("q0", 100),
        entry_timestamp=NOW,
        entry_price=entry,
        entry_day=date(2025, 1, 6),
        entry_day_close=100,
        current_qty=qty,
        **overrides,
    )
    return strategy


def process(strategy, value, fills=None, ref_ma=100, sigma=0.02, atr=2, day=8):
    fills = fills or Fills()
    strategy.process_bar(value, trading_day=date(2025, 1, day), reference_ma=ref_ma, reference_atr=atr, bias_sigma=sigma, buy_qty=100, fill=fills)
    return fills


def test_01_arm_without_entry_expires_same_day():
    rec, fills = EventRecorder(), Fills()
    strategy = SimpleMABreakout(StrategyParameters(), rec)
    strategy.process_bar(bar(high=101.3), 100, 0, 100, fills)
    assert strategy.state.state == StrategyState.ENTRY_ARMED and not fills.items
    strategy.end_day()
    assert strategy.state.state == StrategyState.FLAT


def test_advanced_flat_bar_below_trigger_is_a_noop():
    strategy = AdvancedMABreakout(StrategyParameters(), EventRecorder())
    fills = process(strategy, bar(open_=99, high=100, low=98, close=99))
    assert strategy.s.state == StrategyState.FLAT and not fills.items


def test_02_trigger_then_entry_stop_fills():
    fills = Fills(); strategy = SimpleMABreakout(StrategyParameters(), EventRecorder())
    strategy.process_bar(bar(high=101.6), 100, 0, 100, fills)
    assert fills.items[0]["side"] == "BUY" and fills.items[0]["raw"] == pytest.approx(101.5)


def test_03_entry_gap_above_zone_is_missed():
    fills = Fills(); recorder = EventRecorder(); strategy = SimpleMABreakout(StrategyParameters(), recorder)
    strategy.process_bar(bar(open_=103, high=104, low=102, close=103), 100, 0, 90, fills)
    assert fills.items == []
    assert recorder.events[-1].event == "ENTRY_ZONE_MISSED"


def test_04_day1_volume_plus_9_fails_and_schedules_exit():
    s = advanced(state=StrategyState.LONG_VALIDATING_DAY1)
    s.s.entry_day = date(2025, 1, 8)
    s.end_day(trading_day=date(2025, 1, 8), daily_close=100, daily_high=101, daily_low=99, daily_volume=1090, previous_day_volume=1000, current_day_ma=100, timestamp=NOW, reference_ma=99)
    assert s.s.pending_next_open_exit_reason == "VOLUME_CONFIRMATION_FAIL"


def test_05_day1_volume_plus_10_passes():
    s = advanced(state=StrategyState.LONG_VALIDATING_DAY1); s.s.entry_day = date(2025, 1, 8)
    s.end_day(trading_day=date(2025, 1, 8), daily_close=100, daily_high=101, daily_low=99, daily_volume=1100, previous_day_volume=1000, current_day_ma=100, timestamp=NOW, reference_ma=99)
    assert s.s.state == StrategyState.LONG_VALIDATING_DAY2


def test_06_equal_day2_close_fails_then_next_open_exits():
    s = advanced(state=StrategyState.LONG_VALIDATING_DAY2, day2_validation_pending=True)
    s.end_day(trading_day=date(2025, 1, 8), daily_close=100, daily_high=101, daily_low=99, daily_volume=1000, previous_day_volume=900, current_day_ma=100, timestamp=NOW, reference_ma=99)
    fills = process(s, bar(open_=98, high=99, low=97, close=98, day=9), day=9)
    assert fills.items[0]["reason"] == "DAY2_CLOSE_CONFIRMATION_FAIL" and s.s.current_qty == 0


def test_07_first_ma_break_sells_current_half_and_records_break_day():
    s = advanced(); fills = process(s, bar(open_=100, high=100, low=98.5, close=99))
    assert fills.items[0]["qty"] == 50 and s.s.break_day == date(2025, 1, 8)


def test_08_next_day_strict_break_low_full_exit():
    s = advanced(qty=50, state=StrategyState.BREAK_PROTECTION, break_day=date(2025, 1, 7), break_day_low=97)
    fills = process(s, bar(open_=98, high=99, low=96.9, close=97))
    assert fills.items[0]["reason"] == "BREAK_DAY_LOW_BROKEN" and s.s.current_qty == 0


def test_09_break_protection_resets_using_current_day_ma():
    s = advanced(qty=50, state=StrategyState.BREAK_PROTECTION, break_day=date(2025, 1, 7), break_day_low=95)
    s.end_day(trading_day=date(2025, 1, 8), daily_close=103, daily_high=104, daily_low=101, daily_volume=1000, previous_day_volume=900, current_day_ma=100, timestamp=NOW, reference_ma=99)
    assert s.s.state == StrategyState.LONG_NORMAL and s.s.break_day_low is None


def test_10_second_ma_break_again_sells_current_half():
    s = advanced(qty=50); fills = process(s, bar(open_=100, high=100, low=98.5, close=99))
    assert fills.items[0]["qty"] == 25 and s.s.current_qty == 25


def test_11_first_tp_sells_current_half_and_sets_flag():
    s = advanced(); fills = process(s, bar(open_=101, high=103, low=101, close=102))
    assert s.s.first_tp_triggered and fills.items[0]["qty"] == 50


def test_12_post_tp_protective_stop_is_max_entry_and_previous_ma_risk():
    s = advanced(qty=50, first_tp_triggered=True, state=StrategyState.POST_FIRST_TP)
    fills = process(s, bar(open_=102, high=102, low=100, close=100), ref_ma=102)
    assert fills.items[0]["raw"] == pytest.approx(100.47)  # max(100, 102*.985)


def test_13_bias_false_to_true_sells_ten_percent_q0():
    s = advanced(first_tp_triggered=True, state=StrategyState.POST_FIRST_TP)
    fills = process(s, bar(open_=102, high=105, low=102, close=105), atr=99)
    assert fills.items[0]["qty"] == 10 and s.s.extreme_tp_count == 1


def test_14_bias_remaining_true_has_no_second_sale():
    s = advanced(qty=90, first_tp_triggered=True, state=StrategyState.POST_FIRST_TP, bias_extreme_active=True)
    fills = process(s, bar(open_=104, high=105, low=104, close=105), atr=99)
    assert not fills.items


def test_15_bias_true_false_true_rearms():
    s = advanced(qty=90, first_tp_triggered=True, state=StrategyState.POST_FIRST_TP, bias_extreme_active=True, extreme_tp_count=1)
    s.end_day(trading_day=date(2025, 1, 7), daily_close=100, daily_high=100, daily_low=100, daily_volume=1000, previous_day_volume=900, current_day_ma=100, timestamp=NOW, reference_ma=100, reference_atr=99, bias_sigma=.02)
    fills = process(s, bar(open_=104, high=105, low=104, close=105), atr=99)
    assert fills.items[0]["qty"] == 10 and s.s.extreme_tp_count == 2


def test_16_atr_independently_rearms_while_bias_true():
    s = advanced(qty=90, first_tp_triggered=True, state=StrategyState.POST_FIRST_TP, bias_extreme_active=True)
    fills = process(s, bar(open_=102, high=103, low=102, close=103), sigma=.001, atr=1)
    assert fills.items[0]["qty"] == 10


def test_17_simultaneous_bias_atr_edges_only_one_sale():
    s = advanced(first_tp_triggered=True, state=StrategyState.POST_FIRST_TP)
    fills = process(s, bar(open_=104, high=105, low=104, close=105), sigma=.02, atr=2)
    assert len(fills.items) == 1 and fills.items[0]["qty"] == 10


def test_18_fourth_extreme_tp_is_blocked():
    s = advanced(qty=70, first_tp_triggered=True, state=StrategyState.POST_FIRST_TP, extreme_tp_count=3)
    fills = process(s, bar(open_=104, high=105, low=104, close=105))
    assert not fills.items and s.s.extreme_tp_count == 3


def test_19_below_twenty_percent_blocks_partial_tp():
    s = advanced(qty=19, q0=100, first_tp_triggered=True, state=StrategyState.POST_FIRST_TP)
    fills = process(s, bar(open_=104, high=105, low=104, close=105))
    assert not fills.items


def test_20_exactly_twenty_percent_allows_partial_tp():
    s = advanced(qty=20, q0=100, first_tp_triggered=True, state=StrategyState.POST_FIRST_TP)
    fills = process(s, bar(open_=104, high=105, low=104, close=105))
    assert fills.items[0]["qty"] == 10


def test_21_below_twenty_percent_does_not_block_protective_full_exit():
    s = advanced(qty=19, q0=100, first_tp_triggered=True, state=StrategyState.POST_FIRST_TP)
    fills = process(s, bar(open_=99, high=100, low=98, close=99))
    assert fills.items[0]["qty"] == 19 and s.s.current_qty == 0


def test_22_gap_through_stop_fills_open_not_trigger():
    assert ConservativeIntrabarPolicy.downward_fill(95, 100) == 95


def test_23_same_bar_stop_and_profit_uses_adverse_first():
    decision = ConservativeIntrabarPolicy.choose(stop_touched=True, profit_touched=True)
    assert decision.event == "RISK" and decision.ambiguous


def test_24_reference_ma_is_previous_day_only():
    index = pd.date_range("2025-01-01", periods=6, tz="UTC")
    frame = pd.DataFrame({"open": range(1, 7), "high": range(2, 8), "low": range(0, 6), "close": range(1, 7), "volume": 100}, index=index)
    out = add_indicators(frame, ma_type="sma", ma_period=2, atr_period=2, bias_lookback=2)
    assert out.iloc[3].reference_ma == out.iloc[2].ma and out.iloc[3].reference_ma != out.iloc[3].ma


def test_25_reset_is_close_only_and_uses_completed_current_ma():
    s = advanced(qty=50, state=StrategyState.BREAK_PROTECTION, break_day=date(2025, 1, 7), break_day_low=95)
    process(s, bar(open_=102, high=102, low=101, close=102))
    assert s.s.state == StrategyState.BREAK_PROTECTION
    s.end_day(trading_day=date(2025, 1, 8), daily_close=102, daily_high=102, daily_low=101, daily_volume=1000, previous_day_volume=900, current_day_ma=100, timestamp=NOW, reference_ma=99)
    assert s.s.state == StrategyState.LONG_NORMAL
