from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone

import pandas as pd

from app.backtest.audit import build_position_audits, make_daily_audit
from app.backtest.models import BacktestRequest, Event, Execution, StrategyParameters
from app.backtest.strategies.base import Bar
from app.db.repository import BacktestRepository


STAMP = datetime(2025, 1, 8, tzinfo=timezone.utc)


def test_daily_audit_contains_thresholds_states_events_and_ambiguity():
    request = BacktestRequest(
        ticker="NVDA", strategy="advanced", start_date=date(2025, 1, 1), end_date=date(2025, 2, 1),
        parameters=StrategyParameters(bias_lookback=2, atr_period=2, ma_period=2),
    )
    open_snapshot = {"state": "LONG_NORMAL", "quantity": 100, "q0": 100, "entry_price": 100.0, "entry_day": "2025-01-06", "first_tp_triggered": False, "break_day_low": None, "break_day": None, "bias_extreme_active": False, "atr_extreme_active": False}
    close_snapshot = {**open_snapshot, "state": "BREAK_PROTECTION", "quantity": 50, "break_day_low": 98.0, "break_day": "2025-01-08"}
    events = [
        Event(STAMP, 100.0, "DAILY_INTRABAR_AMBIGUITY", None, None, 100, 100, "LONG_NORMAL", "LONG_NORMAL", {"simultaneous_conditions": ["MA_HALF_STOP", "FIRST_TP"]}),
        Event(STAMP, 100.0, "BREAK_HALF_TRIGGERED", 98.5, 98.5, 100, 50, "LONG_NORMAL", "BREAK_PROTECTION", {}),
    ]
    execution = Execution(STAMP, "SELL", 98.48, 50, 4924, 2.46, 1.0, 50, "MA_HALF_EXIT", "MA_BREAK_HALF_EXIT")
    audit = make_daily_audit(
        request=request, bar=Bar(STAMP, 100, 104, 98, 102, 1100), current_ma=101, reference_ma=100,
        reference_atr=2, bias_sigma=.02, previous_day_volume=1000, open_snapshot=open_snapshot,
        close_snapshot=close_snapshot, events=events, executions=[execution],
    )
    assert audit["strategy_state_at_open"] == "LONG_NORMAL"
    assert audit["strategy_state_at_close"] == "BREAK_PROTECTION"
    assert audit["thresholds"]["ma_half_stop"] == 98.5
    assert audit["thresholds"]["first_tp_price"] == 103
    assert audit["ambiguity"]["simultaneous_conditions"] == ["MA_HALF_STOP", "FIRST_TP"]
    half = next(item for item in audit["events"] if item["event"] == "MA_BREAK_HALF_EXIT")
    assert half["execution_price"] == execution.price
    assert half["shares_sold"] == 50 and half["shares_remaining"] == 50


def test_position_audit_is_persisted_separately_and_deleted_with_backtest(tmp_path):
    repository = BacktestRepository(tmp_path / "backtests.sqlite3")
    identifier = repository.create_pending({
        "ticker": "NVDA", "strategy": "advanced", "start_date": "2021-01-01", "end_date": "2026-01-01",
        "parameters": {}, "initial_capital": 100_000,
    })
    result = {"summary": {"final_equity": 110_000, "total_return": .1, "cagr": .02, "max_drawdown": -.1, "sharpe_ratio": 1.0}, "positions": [{"position_id": "position-1"}]}
    audit = {"position-1": {"backtest_id": None, "position_id": "position-1", "timeline": [{"date": "2025-01-08"}]}}
    repository.complete(identifier, result, audit)
    stored = repository.get(identifier)
    assert "timeline" not in stored["result"]
    assert repository.get_position_audit(identifier, "position-1")["timeline"][0]["date"] == "2025-01-08"
    repository.delete(identifier)
    assert repository.get_position_audit(identifier, "position-1") is None


def test_day1_full_stop_audit_exposes_variant_threshold_and_execution():
    request = BacktestRequest(
        ticker="NVDA", strategy="advanced_day1_stop", start_date=date(2025, 1, 1), end_date=date(2025, 2, 1),
        parameters=StrategyParameters(day1_stop_pct=3, bias_lookback=2, atr_period=2, ma_period=2),
    )
    open_snapshot = {"state": "FLAT", "quantity": 0, "q0": None, "entry_price": None, "entry_day": None, "first_tp_triggered": False, "break_day_low": None, "break_day": None, "bias_extreme_active": False, "atr_extreme_active": False}
    close_snapshot = {**open_snapshot, "state": "CLOSED", "q0": 100, "entry_price": 101.5, "entry_day": "2025-01-08"}
    events = [
        Event(STAMP, 100.0, "ENTRY_STOP_FILLED", 101.5, 101.5, 0, 100, "ENTRY_ARMED", "LONG_VALIDATING_DAY1", {}),
        Event(STAMP, 100.0, "DAILY_INTRABAR_AMBIGUITY", None, None, 100, 100, "LONG_VALIDATING_DAY1", "LONG_VALIDATING_DAY1", {"simultaneous_conditions": ["ENTRY_LEVEL", "DAY1_FULL_STOP"]}),
        Event(STAMP, 100.0, "DAY1_FULL_STOP", 97.0, 97.0, 100, 0, "LONG_VALIDATING_DAY1", "CLOSED", {}),
    ]
    executions = [
        Execution(STAMP, "BUY", 101.5, 100, 10_150, 0, 0, 100, "ENTRY", "ENTRY_STOP_FILLED"),
        Execution(STAMP, "SELL", 97.0, 100, 9_700, 0, 0, 0, "DAY1_FULL_STOP", "DAY1_FULL_STOP"),
    ]
    audit = make_daily_audit(
        request=request, bar=Bar(STAMP, 100, 102, 97, 98, 1_100), current_ma=99, reference_ma=100,
        reference_atr=2, bias_sigma=.02, previous_day_volume=1_000, open_snapshot=open_snapshot,
        close_snapshot=close_snapshot, events=events, executions=executions,
    )
    assert audit["thresholds"]["day1_stop"] == 97
    assert audit["thresholds"]["ma_half_stop"] is None
    assert audit["entry_zone"] == {
        "lower_entry": 101.0,
        "upper_entry": 101.5,
        "entry_allowed": True,
        "entry_missed": False,
        "entry_execution_price": 101.5,
        "intrabar_assumption": "conservative",
    }
    stopped = next(item for item in audit["events"] if item["event"] == "DAY1_FULL_STOP")
    assert stopped["trigger_level"] == 97
    assert stopped["execution_price"] == 97
    assert stopped["shares_before"] == 100 and stopped["shares_sold"] == 100 and stopped["shares_remaining"] == 0


def _advanced_request() -> BacktestRequest:
    return BacktestRequest(
        ticker="NVDA", strategy="advanced", start_date=date(2025, 1, 1), end_date=date(2025, 2, 1),
        commission_pct=0, slippage_pct=0,
        parameters=StrategyParameters(bias_lookback=2, atr_period=2, ma_period=2),
    )


def _previous_position_snapshot() -> dict:
    """A closed predecessor with every position-local runtime field activated."""
    return {
        "state": "CLOSED",
        "quantity": 0,
        "q0": 100,
        "entry_price": 100.0,
        "entry_day": "2025-01-07",
        "first_tp_triggered": True,
        "break_day_low": 95.0,
        "break_day": "2025-01-07",
        "bias_extreme_active": True,
        "atr_extreme_active": True,
    }


def _new_position_entry_snapshot() -> dict:
    """The actual freshly reset runtime state after a new entry fills."""
    return {
        "state": "LONG_VALIDATING_DAY1",
        "quantity": 100,
        "q0": 100,
        "entry_price": 101.5,
        "entry_day": "2025-01-08",
        "first_tp_triggered": False,
        "break_day_low": None,
        "break_day": None,
        "bias_extreme_active": False,
        "atr_extreme_active": False,
    }


def _new_position_entry_audit() -> dict:
    """Build the entry-day audit when the prior position closed yesterday.

    The engine takes its open snapshot before it creates the new position
    state.  The audit therefore must explicitly scope visible values to the
    entry's fresh runtime state rather than retain truthy predecessor values.
    """
    entry = Execution(
        STAMP, "BUY", 101.5, 100, 10_150, 0, 0, 100, "ENTRY", "ENTRY_STOP_FILLED"
    )
    return make_daily_audit(
        request=_advanced_request(),
        bar=Bar(STAMP, 100, 102, 99, 101, 1_100),
        current_ma=100.5,
        reference_ma=100.0,
        reference_atr=2.0,
        bias_sigma=0.02,
        previous_day_volume=1_000,
        open_snapshot=_previous_position_snapshot(),
        close_snapshot=_new_position_entry_snapshot(),
        events=[
            Event(
                STAMP, 100.0, "ENTRY_STOP_FILLED", 101.5, 101.5, 0, 100,
                "ENTRY_ARMED", "LONG_VALIDATING_DAY1", {},
            )
        ],
        executions=[entry],
    )


def test_new_entry_audit_does_not_inherit_previous_first_tp_or_protective_stop():
    audit = _new_position_entry_audit()

    # The predecessor had already hit its +3% TP.  This fresh position has not.
    # Its valid first-TP reference may be displayed, but its protective regime
    # must not be made active by the predecessor's truthy flag.
    assert audit["thresholds"]["first_tp_price"] == 104.545
    assert audit["thresholds"]["protective_stop"] is None


def test_new_entry_audit_does_not_inherit_previous_bias_or_atr_extreme_overlays():
    audit = _new_position_entry_audit()

    # Bias/ATR thresholds are only executable after THIS position's first TP.
    assert audit["thresholds"]["bias_extreme_threshold_price"] is None
    assert audit["thresholds"]["atr_extreme_threshold_price"] is None


def test_new_entry_audit_does_not_inherit_previous_break_protection_state_or_level():
    audit = _new_position_entry_audit()

    # A previous MA half exit cannot disable the new position's normal MA risk
    # threshold or leave a BreakDayLow overlay on the new position.
    assert audit["strategy_state_at_open"] == "FLAT"
    assert audit["strategy_state_at_close"] == "LONG_VALIDATING_DAY1"
    assert audit["thresholds"]["break_day_low"] is None
    assert audit["thresholds"]["ma_half_stop"] == 98.5


def test_entry_day_audit_thresholds_match_the_new_position_runtime_snapshot():
    audit = _new_position_entry_audit()
    fresh = _new_position_entry_snapshot()

    # This asserts the audit-visible execution thresholds are derived from the
    # actual state that exists after this entry, not the prior closed state.
    assert fresh["first_tp_triggered"] is False
    assert fresh["break_day_low"] is None
    assert fresh["bias_extreme_active"] is False
    assert fresh["atr_extreme_active"] is False
    assert audit["thresholds"] == {
        "breakout_trigger": 101.0,
        "entry_level": 101.5,
        "day1_stop": None,
        "ma_half_stop": 98.5,
        "break_day_low": None,
        "first_tp_price": 104.545,
        "protective_stop": None,
        "bias_extreme_threshold_price": None,
        "atr_extreme_threshold_price": None,
    }


def test_audit_rebuild_is_read_only_for_executions_and_position_pnl():
    """Audit reconstruction must be a presentation operation only."""
    request = _advanced_request()
    buy = Execution(STAMP, "BUY", 101.5, 100, 10_150, 5.0, 2.0, 100, "ENTRY", "ENTRY_STOP_FILLED")
    sell = Execution(STAMP, "SELL", 103.0, 100, 10_300, 5.0, 2.0, 0, "FINAL_EXIT", "END_OF_BACKTEST")
    executions = [buy, sell]
    position = {
        "position_id": "position-1",
        "entry_date": STAMP.isoformat(),
        "entry_price": 101.5,
        "initial_shares": 100,
        "final_exit_date": STAMP.isoformat(),
        "net_pnl": 140.0,
        "realized_pnl": 140.0,
        "final_return": 0.01379,
    }
    open_snapshot = {
        "state": "FLAT", "quantity": 0, "q0": None, "entry_price": None, "entry_day": None,
        "first_tp_triggered": False, "break_day_low": None, "break_day": None,
        "bias_extreme_active": False, "atr_extreme_active": False,
    }
    close_snapshot = _new_position_entry_snapshot() | {"state": "CLOSED", "quantity": 0}
    daily_audit = make_daily_audit(
        request=request,
        bar=Bar(STAMP, 100, 103, 99, 102, 1_100),
        current_ma=100.5,
        reference_ma=100.0,
        reference_atr=2.0,
        bias_sigma=0.02,
        previous_day_volume=1_000,
        open_snapshot=open_snapshot,
        close_snapshot=close_snapshot,
        events=[Event(STAMP, 100.0, "ENTRY_STOP_FILLED", 101.5, 101.5, 0, 100, "ENTRY_ARMED", "LONG_VALIDATING_DAY1", {})],
        executions=executions,
    )
    enriched = pd.DataFrame(
        {
            "open": [100.0], "high": [103.0], "low": [99.0], "close": [102.0], "volume": [1_100.0],
            "ma": [100.5], "reference_ma": [100.0],
        },
        index=pd.DatetimeIndex([STAMP]),
    )
    original_executions = deepcopy([item.as_dict() for item in executions])
    original_position = deepcopy(position)
    original_daily_audit = deepcopy(daily_audit)

    first = build_position_audits(
        backtest_id="audit-rebuild", ticker="NVDA", strategy="advanced", positions=[position],
        daily_audits=[daily_audit], enriched=enriched, executions=executions,
    )
    second = build_position_audits(
        backtest_id="audit-rebuild", ticker="NVDA", strategy="advanced", positions=[position],
        daily_audits=[daily_audit], enriched=enriched, executions=executions,
    )

    assert first == second
    assert [item.as_dict() for item in executions] == original_executions
    assert position == original_position
    assert daily_audit == original_daily_audit
