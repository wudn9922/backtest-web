from datetime import datetime, timezone

import pytest

from app.backtest.execution import evaluate_entry_zone, execution_policy
from app.backtest.models import StrategyParameters
from app.backtest.strategies import AdvancedDay1StopMABreakout, AdvancedMABreakout, SimpleMABreakout
from app.backtest.strategies.base import Bar, EventRecorder


def zone(open_, high):
    return evaluate_entry_zone(bar_open=open_, bar_high=high, reference_ma=100, breakout_trigger_pct=1, entry_stop_pct=1.5)


def test_01_below_zone_crosses_and_fills_upper():
    decision = zone(100, 102)
    assert decision.armed and decision.fill_price == pytest.approx(101.5)


def test_02_open_inside_zone_fills_upper():
    assert zone(101.2, 101.6).fill_price == pytest.approx(101.5)


def test_03_open_equals_upper_is_allowed():
    decision = zone(101.5, 101.5)
    assert decision.entry_allowed and decision.filled and decision.fill_price == pytest.approx(101.5)


def test_04_open_just_above_upper_is_missed():
    decision = zone(101.51, 103)
    assert decision.missed and not decision.entry_allowed and not decision.filled


def test_05_gap_then_falls_back_is_still_missed():
    decision = zone(103, 103)
    assert decision.missed and decision.fill_price is None


def test_06_trigger_only_does_not_fill():
    decision = zone(100, 101.4)
    assert decision.armed and not decision.filled


def test_07_large_high_still_fills_exact_upper():
    assert zone(100, 105).fill_price == pytest.approx(101.5)


class Fills:
    def __init__(self, strategy=None): self.items, self.strategy = [], strategy
    def __call__(self, side, raw, qty, event_type, reason, timestamp):
        self.items.append((side, raw, qty, reason))
        if side == "BUY" and self.strategy is not None and hasattr(self.strategy, "s"):
            self.strategy.s.entry_price = raw
            self.strategy.s.q0 = qty
            self.strategy.s.current_qty = qty


def bar(open_, high, low=100, close=101):
    return Bar(datetime(2026, 1, 2, tzinfo=timezone.utc), open_, high, low, close, 1_000_000)


@pytest.mark.parametrize("strategy_cls", [SimpleMABreakout, AdvancedMABreakout, AdvancedDay1StopMABreakout])
def test_08_all_strategies_share_entry_zone(strategy_cls):
    recorder = EventRecorder()
    strategy = strategy_cls(StrategyParameters(), recorder)
    fills = Fills(strategy)
    if strategy_cls is SimpleMABreakout:
        strategy.process_bar(bar(100, 102), 100, 0, 10, fills)
    else:
        strategy.process_bar(bar(100, 102), trading_day=datetime(2026, 1, 2).date(), reference_ma=100, reference_atr=2, bias_sigma=.02, buy_qty=10, fill=fills)
    assert fills.items[0][:2] == ("BUY", pytest.approx(101.5))


@pytest.mark.parametrize("policy_name", ["conservative", "ohlc_heuristic", "favorable"])
def test_09_every_policy_misses_open_above_upper(policy_name):
    recorder = EventRecorder()
    strategy = AdvancedDay1StopMABreakout(StrategyParameters(), recorder, execution_policy(policy_name))
    fills = Fills(strategy)
    strategy.process_bar(bar(103, 105, 96, 102), trading_day=datetime(2026, 1, 2).date(), reference_ma=100, reference_atr=2, bias_sigma=.02, buy_qty=10, fill=fills)
    assert not fills.items
    assert recorder.events[-1].event == "ENTRY_ZONE_MISSED"


@pytest.mark.parametrize("policy_name", ["conservative", "ohlc_heuristic", "favorable"])
def test_10_every_policy_enters_at_open_equal_upper(policy_name):
    recorder = EventRecorder()
    strategy = AdvancedMABreakout(StrategyParameters(), recorder, execution_policy(policy_name))
    fills = Fills(strategy)
    strategy.process_bar(bar(101.5, 102, 100, 101), trading_day=datetime(2026, 1, 2).date(), reference_ma=100, reference_atr=2, bias_sigma=.02, buy_qty=10, fill=fills)
    assert fills.items[0][:2] == ("BUY", pytest.approx(101.5))


@pytest.mark.parametrize("policy_name", ["conservative", "ohlc_heuristic", "favorable"])
def test_11_open_entry_then_day1_stop_is_mandatory(policy_name):
    recorder = EventRecorder()
    strategy = AdvancedDay1StopMABreakout(StrategyParameters(), recorder, execution_policy(policy_name))
    fills = Fills(strategy)
    strategy.process_bar(bar(101.5, 105, 97, 100), trading_day=datetime(2026, 1, 2).date(), reference_ma=100, reference_atr=2, bias_sigma=.02, buy_qty=10, fill=fills)
    assert [item[0] for item in fills.items] == ["BUY", "SELL"]
    assert fills.items[-1][3] == "DAY1_FULL_STOP"


def test_12_no_ambiguity_is_identical_across_policies():
    results = []
    for policy_name in ["conservative", "ohlc_heuristic", "favorable"]:
        recorder = EventRecorder()
        strategy = AdvancedMABreakout(StrategyParameters(), recorder, execution_policy(policy_name))
        fills = Fills(strategy)
        strategy.process_bar(bar(100, 102, 100, 102), trading_day=datetime(2026, 1, 2).date(), reference_ma=100, reference_atr=2, bias_sigma=.02, buy_qty=10, fill=fills)
        results.append(fills.items)
    assert results[0] == results[1] == results[2]
