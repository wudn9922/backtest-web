from dataclasses import replace
from datetime import datetime, date, timezone
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.baseline import load, immutable_fingerprints, normalize_timestamps
from research.modules import FULL, CORE, Modules, VARIANTS, BRIDGE
from research.simulation import Prepared, simulate
from research.strategy import ResearchAdvanced
from app.backtest.engine import BacktestEngine
from app.backtest.models import AdvancedStrategyState, StrategyState, StrategyParameters
from app.backtest.strategies.base import Bar, EventRecorder


@pytest.fixture(scope="module")
def inputs():
    before = immutable_fingerprints()
    frozen, daily = load()
    yield frozen, daily, Prepared(frozen["advanced"]["request_object"], daily)
    assert before == immutable_fingerprints()


def assert_execution_parity(left, right):
    left, right = normalize_timestamps(left), normalize_timestamps(right)
    assert left["executions"] == right["executions"]
    assert len(left["positions"]) == len(right["positions"])
    for a, b in zip(left["positions"], right["positions"]):
        assert {k: v for k, v in a.items() if k != "gross_pnl"} == {k: v for k, v in b.items() if k != "gross_pnl"}
        assert a["gross_pnl"] == pytest.approx(b["gross_pnl"], abs=1e-9)


@pytest.mark.parametrize("name", ["simple", "advanced"])
def test_current_production_reproduces_frozen_canonical_without_writes(inputs, name):
    frozen, daily, _ = inputs
    expected = frozen[name]["result"]
    actual = BacktestEngine().run(frozen[name]["request_object"], daily)
    assert_execution_parity(actual, expected)
    assert normalize_timestamps(actual["equity_curve"]) == normalize_timestamps(expected["equity_curve"])
    assert actual["summary"] == expected["summary"]


@pytest.mark.parametrize("name", ["simple", "advanced"])
def test_research_all_on_exact_execution_equity_and_metrics(inputs, name):
    frozen, _, prepared = inputs
    expected = frozen[name]["result"]
    actual = simulate(prepared, simple=name == "simple")
    assert_execution_parity(actual, expected)
    assert [r["strategy"] for r in actual["equity"]] == [r["strategy"] for r in expected["equity_curve"]]
    left, right = normalize_timestamps(actual["events"]), normalize_timestamps(expected["events"])
    if name == "simple":
        # Older Simple records precede these entry-zone audit metadata additions.
        for event in left + right:
            for key in ["entry_allowed", "entry_missed", "lower_entry", "upper_entry", "entry_execution_price"]:
                event["metadata"].pop(key, None)
    assert left == right
    for key, value in actual["summary"].items():
        assert value == expected["summary"][key]


def test_illegal_downstream_without_first_tp_rejected():
    for field in ["protective", "bias", "atr"]:
        with pytest.raises(ValueError):
            replace(CORE, **{field: True})
    assert BRIDGE["PLUS_ATR_FULL"] == FULL
    assert not any(VARIANTS["ADVANCED_MINUS_FIRST_TP_FAMILY"].as_dict()[k] for k in ["first_tp", "protective", "bias", "atr"])


def test_all_77_anchors_preserve_full_lifecycle(inputs):
    frozen, _, prepared = inputs
    groups = []
    for e in frozen["advanced"]["result"]["executions"]:
        if e["side"] == "BUY":
            groups.append([])
        groups[-1].append(e)
    for anchor, expected in zip(frozen["advanced"]["result"]["positions"], groups):
        got = simulate(prepared, anchor=anchor)
        assert normalize_timestamps(got["executions"]) == normalize_timestamps(expected)
        assert got["positions"][0]["net_pnl"] == anchor["net_pnl"]


def test_volume_off_keeps_day2_anchor_but_removes_volume_gate():
    rec = EventRecorder()
    s = ResearchAdvanced(StrategyParameters(), rec, modules=replace(FULL, volume=False))
    s.s = AdvancedStrategyState(state=StrategyState.LONG_VALIDATING_DAY1, q0=100, current_qty=100, entry_price=100, entry_day=date(2025, 1, 8))
    for day, close in [(8, 102), (9, 102)]:
        s.end_day(trading_day=date(2025, 1, day), daily_close=close, daily_high=102, daily_low=101, daily_volume=1,
                  previous_day_volume=1000, current_day_ma=100, timestamp=datetime(2025, 1, day, tzinfo=timezone.utc), reference_ma=100)
    assert s.s.pending_next_open_exit_reason == "DAY2_CLOSE_CONFIRMATION_FAIL"
    assert not any(e.event.startswith("VOLUME") for e in rec.events)


def test_no_parameters_mutated_and_no_illegal_downstream_in_core(inputs):
    _, _, prepared = inputs
    original = prepared.request.model_dump()
    got = simulate(prepared, CORE)
    assert prepared.request.model_dump() == original
    assert len(got["positions"]) == 1
    assert got["executions"][-1]["reason"] == "END_OF_BACKTEST"
    assert not any("TP" in e["event"] or "CONFIRMATION" in e["event"] for e in got["events"])


@pytest.mark.parametrize("name", list(VARIANTS))
def test_disabled_families_do_not_leak_events_or_change_parameters(inputs, name):
    _, _, prepared = inputs
    original = prepared.request.model_dump()
    modules = VARIANTS[name]
    result = simulate(prepared, modules)
    assert original == prepared.request.model_dump()
    names = [e["event"] for e in result["events"]]
    if not modules.volume:
        assert not any(n.startswith("VOLUME_CONFIRMATION") for n in names)
    if not modules.day2:
        assert not any(n.startswith("DAY2") for n in names)
    if not modules.ma_break:
        assert not any(n.startswith("BREAK_") for n in names)
    if not modules.first_tp:
        assert "FIRST_TP_TRIGGERED" not in names and "EXTREME_TP_EXECUTED" not in names
    if not modules.protective:
        assert "PROTECTIVE_STOP_TRIGGERED" not in names
    if not modules.bias:
        assert not any(n.startswith("BIAS_EXTREME") for n in names)
    if not modules.atr:
        assert not any(n.startswith("ATR_EXTREME") for n in names)
    assert all(e["position_remaining"] >= 0 for e in result["executions"])


def test_counterfactual_anchor_is_fixed_and_never_reenters(inputs):
    frozen, _, prepared = inputs
    for pos in [frozen["advanced"]["result"]["positions"][i] for i in [0,13,31,55,76]]:
        for modules in VARIANTS.values():
            result = simulate(prepared, modules, anchor=pos)
            buys = [e for e in result["executions"] if e["side"] == "BUY"]
            assert len(buys) == 1 and buys[0]["quantity"] == pos["q0"] and buys[0]["price"] == pos["entry_price"]
            assert result["executions"][-1]["position_remaining"] == 0


def test_forward_returns_are_future_completed_bars_and_end_is_null(inputs):
    from research.analysis import forward_returns
    _, _, prepared = inputs
    bar = prepared.rows[10][0]
    fwd = forward_returns(prepared, bar.timestamp.isoformat(), bar.close)
    assert fwd["5"] == prepared.rows[15][0].close / bar.close - 1
    last = prepared.rows[-1][0]
    assert all(v is None for v in forward_returns(prepared, last.timestamp.isoformat(), last.close).values())
