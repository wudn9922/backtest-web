from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.backtest.models import StrategyParameters, StrategyState
from app.backtest.strategies.advanced_day1_stop import AdvancedDay1StopMABreakout
from app.backtest.strategies.base import Bar, EventRecorder


STAMP = datetime(2025, 1, 8, tzinfo=timezone.utc)


class StrategyFills:
    def __init__(self, strategy: AdvancedDay1StopMABreakout):
        self.strategy = strategy
        self.items: list[dict] = []

    def __call__(self, side, raw, qty, event, reason, timestamp):
        self.items.append({"side": side, "raw": raw, "qty": qty, "event": event, "reason": reason})
        if side == "BUY":
            self.strategy.s.entry_price = raw
            self.strategy.s.q0 = qty
            self.strategy.s.current_qty = qty


def daily(*, open_=100, high=102, low=100, close=101, volume=1_100, day=8):
    return Bar(STAMP.replace(day=day), open_, high, low, close, volume)


def enter(bar: Bar, recorder: EventRecorder | None = None):
    recorder = recorder or EventRecorder()
    strategy = AdvancedDay1StopMABreakout(StrategyParameters(), recorder)
    fills = StrategyFills(strategy)
    strategy.process_bar(
        bar,
        trading_day=bar.timestamp.date(),
        reference_ma=100,
        reference_atr=2,
        bias_sigma=.02,
        buy_qty=100,
        fill=fills,
    )
    return strategy, fills, recorder


def test_day1_low_above_three_percent_stop_does_not_exit():
    strategy, fills, _ = enter(daily(low=97.1))
    assert [item["side"] for item in fills.items] == ["BUY"]
    assert strategy.s.current_qty == 100


def test_day1_low_equal_to_three_percent_stop_full_exits():
    strategy, fills, _ = enter(daily(low=97))
    assert [item["side"] for item in fills.items] == ["BUY", "SELL"]
    assert fills.items[-1] == {"side": "SELL", "raw": 97.0, "qty": 100, "event": "DAY1_FULL_STOP", "reason": "DAY1_FULL_STOP"}
    assert strategy.s.current_qty == 0


def test_day1_low_below_three_percent_stop_full_exits():
    strategy, fills, _ = enter(daily(low=96))
    assert fills.items[-1]["reason"] == "DAY1_FULL_STOP"
    assert fills.items[-1]["qty"] == 100
    assert strategy.s.state == StrategyState.CLOSED


def test_day2_uses_original_half_risk_not_day1_full_stop():
    strategy, fills, _ = enter(daily(low=97.1, close=102))
    strategy.end_day(
        trading_day=date(2025, 1, 8),
        daily_close=102,
        daily_high=102,
        daily_low=97.1,
        daily_volume=1_100,
        previous_day_volume=1_000,
        current_day_ma=100,
        timestamp=STAMP,
        reference_ma=100,
        reference_atr=2,
        bias_sigma=.02,
    )
    strategy.process_bar(
        daily(open_=100, high=101, low=98.5, close=99, day=9),
        trading_day=date(2025, 1, 9),
        reference_ma=100,
        reference_atr=2,
        bias_sigma=.02,
        buy_qty=0,
        fill=fills,
    )
    assert fills.items[-1]["reason"] == "MA_BREAK_HALF_EXIT"
    assert fills.items[-1]["qty"] == 50
    assert strategy.s.current_qty == 50


def test_same_day_entry_and_stop_records_daily_ambiguity():
    strategy, fills, recorder = enter(daily(high=102, low=96))
    assert fills.items[-1]["reason"] == "DAY1_FULL_STOP"
    ambiguity = next(event for event in recorder.events if event.event == "DAILY_INTRABAR_AMBIGUITY")
    assert ambiguity.metadata["policy"] == "conservative"
    assert ambiguity.metadata["chosen_path"] == "conservative-entry-first"
    assert ambiguity.metadata["simultaneous_conditions"] == ["ENTRY_LEVEL", "DAY1_FULL_STOP"]
    assert strategy.s.current_qty == 0


def test_day1_full_stop_precedes_first_take_profit():
    strategy, fills, recorder = enter(daily(high=105, low=97))
    sells = [item for item in fills.items if item["side"] == "SELL"]
    assert len(sells) == 1 and sells[0]["reason"] == "DAY1_FULL_STOP"
    assert not any(event.event == "FIRST_TP_TRIGGERED" for event in recorder.events)
    ambiguity = next(event for event in recorder.events if event.event == "DAILY_INTRABAR_AMBIGUITY")
    assert "FIRST_TP" in ambiguity.metadata["simultaneous_conditions"]
    assert strategy.s.first_tp_triggered is False


def test_day1_gap_below_stop_uses_open_as_adverse_fill():
    _, fills, _ = enter(daily(open_=96, high=102, low=95))
    assert fills.items[-1]["raw"] == pytest.approx(96)
