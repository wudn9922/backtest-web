from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.backtest.execution import execution_policy
from app.backtest.models import StrategyParameters, StrategyState
from app.backtest.strategies.advanced_day1_stop import AdvancedDay1StopMABreakout
from app.backtest.strategies.base import Bar, EventRecorder
from app.backtest.strategies.simple_ma_breakout import SimpleMABreakout


STAMP = datetime(2025, 1, 8, tzinfo=timezone.utc)
POLICIES = ("conservative", "ohlc_heuristic", "favorable")


class Fills:
    def __init__(self, strategy=None):
        self.strategy = strategy
        self.items: list[dict] = []

    def __call__(self, side, raw, qty, event, reason, timestamp):
        self.items.append({"side": side, "raw": raw, "qty": qty, "event": event, "reason": reason})
        if side == "BUY" and self.strategy is not None:
            self.strategy.s.entry_price = raw
            self.strategy.s.q0 = qty
            self.strategy.s.current_qty = qty


def run_variant(policy_name: str, *, open_=100, high=103, low=96, close=102):
    recorder = EventRecorder()
    strategy = AdvancedDay1StopMABreakout(StrategyParameters(), recorder, execution_policy(policy_name))
    fills = Fills(strategy)
    strategy.process_bar(
        Bar(STAMP, open_, high, low, close, 1_100), trading_day=date(2025, 1, 8), reference_ma=100,
        reference_atr=2, bias_sigma=.02, buy_qty=100, fill=fills,
    )
    return strategy, fills, recorder


def test_case_a_green_ambiguous_bar_differs_by_policy():
    conservative, conservative_fills, _ = run_variant("conservative")
    favorable, favorable_fills, favorable_events = run_variant("favorable")
    heuristic, heuristic_fills, heuristic_events = run_variant("ohlc_heuristic")
    assert conservative_fills.items[-1]["reason"] == "DAY1_FULL_STOP" and conservative.s.current_qty == 0
    assert [item["side"] for item in favorable_fills.items] == ["BUY"] and favorable.s.current_qty == 100
    assert [item["side"] for item in heuristic_fills.items] == ["BUY"] and heuristic.s.current_qty == 100
    assert next(event for event in favorable_events.events if event.event == "DAILY_INTRABAR_AMBIGUITY").metadata["chosen_path"] == "favorable-low-before-entry"
    assert next(event for event in heuristic_events.events if event.event == "DAILY_INTRABAR_AMBIGUITY").metadata["chosen_path"] == "ohlc-open-low-high-close"


def test_case_b_red_heuristic_bar_enters_then_stops():
    strategy, fills, events = run_variant("ohlc_heuristic", close=99)
    assert [item["side"] for item in fills.items] == ["BUY", "SELL"]
    assert fills.items[-1]["reason"] == "DAY1_FULL_STOP" and strategy.s.current_qty == 0
    ambiguity = next(event for event in events.events if event.event == "DAILY_INTRABAR_AMBIGUITY")
    assert ambiguity.metadata["chosen_path"] == "ohlc-open-high-low-close"


@pytest.mark.parametrize("policy_name", POLICIES)
def test_case_c_gap_entry_then_stop_is_mandatory_for_every_policy(policy_name):
    strategy, fills, events = run_variant(policy_name, open_=101.5, high=103, low=96, close=99)
    assert [item["side"] for item in fills.items] == ["BUY", "SELL"]
    assert fills.items[-1]["raw"] == 97 and strategy.s.current_qty == 0
    assert not any(event.event == "DAILY_INTRABAR_AMBIGUITY" for event in events.events)


@pytest.mark.parametrize("policy_name", POLICIES)
def test_case_d_preexisting_position_stop_executes_for_every_policy(policy_name):
    strategy = SimpleMABreakout(StrategyParameters(), EventRecorder(), execution_policy(policy_name))
    strategy.state.state = StrategyState.LONG_NORMAL
    fills = Fills()
    strategy.process_bar(Bar(STAMP, 100, 101, 98, 99, 1_000), 100, 100, 0, fills)
    assert fills.items == [{"side": "SELL", "raw": 98.5, "qty": 100, "event": "FINAL_EXIT", "reason": "MA_EXIT"}]


def test_case_e_unambiguous_entry_is_identical_for_all_policies():
    outcomes = []
    for policy_name in POLICIES:
        strategy, fills, events = run_variant(policy_name, open_=100, high=102, low=100, close=101)
        outcomes.append((fills.items, strategy.s.current_qty, [event.event for event in events.events]))
    assert outcomes[0] == outcomes[1] == outcomes[2]
