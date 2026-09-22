from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.backtest.models import AdvancedStrategyState, StrategyParameters, StrategyState
from app.backtest.strategies.advanced_ma_breakout import AdvancedMABreakout
from app.backtest.strategies.base import Bar, EventRecorder
from app.backtest.strategies.simple_ma_breakout import SimpleMABreakout


STAMP = datetime(2025, 1, 8, tzinfo=timezone.utc)


class Fills:
    def __init__(self):
        self.items: list[dict] = []

    def __call__(self, side, raw, qty, event, reason, timestamp):
        self.items.append({"side": side, "raw": raw, "qty": qty, "event": event, "reason": reason})


def daily(open_=100, high=100, low=100, close=100, day=8):
    return Bar(STAMP.replace(day=day), open_, high, low, close, 1_000)


def held(*, qty=100, q0=100, first_tp=False, state=StrategyState.LONG_NORMAL, **extra):
    strategy = AdvancedMABreakout(StrategyParameters(), EventRecorder())
    strategy.s = AdvancedStrategyState(
        state=state,
        q0=q0,
        entry_timestamp=STAMP,
        entry_price=100,
        entry_day=date(2025, 1, 6),
        entry_day_close=100,
        current_qty=qty,
        first_tp_triggered=first_tp,
        **extra,
    )
    return strategy


def run_advanced(strategy, bar, fills=None, day=8, ref_ma=100, sigma=.02, atr=99):
    fills = fills or Fills()
    strategy.process_bar(bar, trading_day=date(2025, 1, day), reference_ma=ref_ma, reference_atr=atr, bias_sigma=sigma, buy_qty=100, fill=fills)
    return fills


def test_a_trigger_without_entry_level_has_no_fill():
    fills, strategy = Fills(), SimpleMABreakout(StrategyParameters(), EventRecorder())
    strategy.process_bar(daily(high=101.4), 100, 0, 100, fills)
    assert not fills.items
    strategy.end_day()
    assert strategy.state.state == StrategyState.FLAT


def test_b_daily_high_reaches_entry_level_fill_is_level():
    fills, strategy = Fills(), SimpleMABreakout(StrategyParameters(), EventRecorder())
    strategy.process_bar(daily(high=102, low=100), 100, 0, 100, fills)
    assert fills.items[0]["raw"] == pytest.approx(101.5)


def test_c_gap_above_entry_zone_is_missed():
    fills, strategy = Fills(), SimpleMABreakout(StrategyParameters(), EventRecorder())
    strategy.process_bar(daily(open_=103, high=104, low=102), 100, 0, 100, fills)
    assert fills.items == []


def test_d_gap_through_existing_stop_fills_at_open():
    fills, strategy = Fills(), SimpleMABreakout(StrategyParameters(), EventRecorder())
    strategy.state.state = StrategyState.LONG_NORMAL
    strategy.process_bar(daily(open_=97, high=99, low=96), 100, 100, 0, fills)
    assert fills.items[0]["raw"] == 97


def test_e_same_day_entry_and_stop_uses_entry_then_adverse():
    recorder, fills = EventRecorder(), Fills()
    strategy = SimpleMABreakout(StrategyParameters(), recorder)
    strategy.process_bar(daily(open_=100, high=102, low=98), 100, 0, 100, fills)
    assert [item["side"] for item in fills.items] == ["BUY", "SELL"]
    assert fills.items[1]["raw"] == pytest.approx(98.5)
    assert any(event.event == "DAILY_INTRABAR_AMBIGUITY" for event in recorder.events)


def test_f_same_day_first_tp_and_protective_stop_is_adverse_first():
    strategy, fills = held(), Fills()
    run_advanced(strategy, daily(open_=101, high=103, low=100), fills, atr=99)
    assert strategy.s.first_tp_triggered
    assert fills.items == [{"side": "SELL", "raw": 100, "qty": 100, "event": "PROTECTIVE_STOP", "reason": "PROTECTIVE_STOP"}]
    assert any(event.event == "DAILY_INTRABAR_AMBIGUITY" for event in strategy.events.events)


def test_g_daily_high_crosses_bias_threshold_for_extreme_tp():
    strategy, fills = held(first_tp=True, state=StrategyState.POST_FIRST_TP), Fills()
    run_advanced(strategy, daily(open_=101, high=104, low=101), fills, atr=99)
    assert fills.items[0]["event"] == "EXTREME_TP"
    assert fills.items[0]["raw"] == pytest.approx(104)


def test_h_completed_day_high_below_threshold_rearms_bias():
    strategy = held(first_tp=True, state=StrategyState.POST_FIRST_TP, bias_extreme_active=True)
    run_advanced(strategy, daily(open_=101, high=103, low=101), atr=99)
    assert strategy.s.bias_extreme_active
    strategy.end_day(trading_day=date(2025, 1, 8), daily_close=102, daily_high=103, daily_low=101, daily_volume=1000, previous_day_volume=900, current_day_ma=100, timestamp=STAMP, reference_ma=100, reference_atr=99, bias_sigma=.02)
    assert not strategy.s.bias_extreme_active


def test_i_rearmed_bias_crosses_again_for_second_extreme_tp():
    strategy = held(qty=90, first_tp=True, state=StrategyState.POST_FIRST_TP, extreme_tp_count=1, bias_extreme_active=False)
    fills = run_advanced(strategy, daily(open_=101, high=104, low=101), atr=99)
    assert fills.items[0]["qty"] == 10
    assert strategy.s.extreme_tp_count == 2


def test_j_break_reset_uses_current_day_ma_only_at_close():
    strategy = held(qty=50, state=StrategyState.BREAK_PROTECTION, break_day=date(2025, 1, 7), break_day_low=95)
    run_advanced(strategy, daily(open_=102, high=103, low=101, close=102))
    assert strategy.s.break_day_low == 95
    strategy.end_day(trading_day=date(2025, 1, 8), daily_close=102, daily_high=103, daily_low=101, daily_volume=1000, previous_day_volume=900, current_day_ma=100, timestamp=STAMP, reference_ma=99)
    assert strategy.s.break_day_low is None
    assert any(event.metadata.get("uses_current_day_completed_ma") for event in strategy.events.events)
