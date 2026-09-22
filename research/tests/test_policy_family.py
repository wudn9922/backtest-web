from dataclasses import replace
from datetime import date, datetime, timezone
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.baseline import load, immutable_fingerprints, normalize_timestamps
from research.simulation import Prepared, simulate
from research.modules import FULL
from research.ambiguity import classify, ENTRY, TP_STOP, NONE
from research.family_study import FACTORIAL, NAMES
from research.strategy import ResearchAdvanced
from app.backtest.engine import BacktestEngine
from app.backtest.models import StrategyParameters, AdvancedStrategyState, StrategyState
from app.backtest.strategies.base import Bar, EventRecorder


@pytest.fixture(scope="module")
def inputs():
    before = immutable_fingerprints()
    frozen, daily = load()
    yield frozen, daily, Prepared(frozen["advanced"]["request_object"], daily)
    assert before == immutable_fingerprints()


@pytest.mark.parametrize("policy", ["conservative", "ohlc_heuristic", "favorable"])
@pytest.mark.parametrize("simple", [False, True])
def test_policy_research_parity_with_existing_production(inputs, policy, simple):
    frozen, daily, prepared = inputs
    req = frozen["simple" if simple else "advanced"]["request_object"].model_copy(update={"execution_policy": policy})
    actual = BacktestEngine().run(req, daily)
    research = simulate(prepared, simple=simple, policy=policy, trace=True)
    assert normalize_timestamps(actual["executions"]) == normalize_timestamps(research["executions"])
    assert [r["strategy"] for r in actual["equity_curve"]] == [r["strategy"] for r in research["equity"]]
    for key in research["summary"]:
        assert research["summary"][key] == actual["summary"][key]


def row(o=100, h=102, l=98, c=101):
    return {"date":"2025-01-08", "open":o, "high":h, "low":l, "close":c,
            "reference_ma":100, "reference_atr":10, "bias_sigma":.1,
            "quantity_open":0, "quantity_close":50, "state_open":{}, "state_close":{}, "events":[],
            "executions":[{"side":"BUY", "price":101.5, "quantity":100}]}


def test_low_before_entry_is_not_known_from_open_below_entry():
    d = classify(row(), StrategyParameters(), FULL)
    assert ENTRY in d["classes"] and d["genuine"]


def test_entry_at_open_not_entry_order_ambiguity():
    d = classify(row(o=101.5), StrategyParameters(), FULL)
    assert d["classes"] == [NONE]


def test_close_through_stop_forces_post_entry_stop():
    assert classify(row(c=98), StrategyParameters(), FULL)["classes"] == [NONE]


def test_gap_above_zone_has_no_entry_ambiguity():
    r = row(o=103, h=105); r["executions"] = []
    assert classify(r, StrategyParameters(), FULL)["classes"] == [NONE]


def test_existing_protective_vs_extreme_and_open_stop_identifiability():
    r = row(o=105, h=112, l=99, c=106)
    r.update(quantity_open=100, executions=[], reference_atr=5,
             state_open={"entry_price":100,"first_tp_triggered":True,"q0":100,"current_qty":100})
    assert TP_STOP in classify(r, StrategyParameters(), FULL)["classes"]
    r["open"] = 99
    assert classify(r, StrategyParameters(), FULL)["classes"] == [NONE]


def test_no_partial_preserves_signal_protective_and_remaining_quantity():
    recorder = EventRecorder(); s = ResearchAdvanced(StrategyParameters(), recorder, modules=replace(FULL, first_tp_partial=False, bias=False, atr=False))
    s.s = AdvancedStrategyState(state=StrategyState.LONG_NORMAL, q0=101, current_qty=101, entry_price=100, entry_day=date(2025,1,6))
    executions=[]
    def fill(*args): executions.append(args)
    s.process_bar(Bar(datetime(2025,1,8,tzinfo=timezone.utc),102,104,101,103,1000),trading_day=date(2025,1,8),reference_ma=90,reference_atr=10,bias_sigma=.1,buy_qty=0,fill=fill)
    assert s.s.first_tp_triggered and s.s.current_qty == 101 and not executions
    s.process_bar(Bar(datetime(2025,1,9,tzinfo=timezone.utc),99,102,98,101,1000),trading_day=date(2025,1,9),reference_ma=90,reference_atr=10,bias_sigma=.1,buy_qty=0,fill=fill)
    assert executions[0][1:5] == (99,101,"PROTECTIVE_STOP","PROTECTIVE_STOP")
    assert s.s.current_qty == 0


def test_redundant_requested_variants_are_explicit_aliases():
    assert NAMES["FIRST_TP_PARTIAL_NO_PROTECTIVE"] == NAMES["PROTECTIVE_OFF"]
    assert len(FACTORIAL) == 8


@pytest.mark.parametrize("phase,name",[("A","intrabar-ambiguity-attribution"),("B","first-tp-family-decomposition")])
def test_saved_research_artifacts_are_reproducible_and_position_scoped(phase,name):
    import json
    from research import ROOT
    from research.run_policy_family import run
    from research.policy_family_report import render
    saved=json.loads((ROOT/"data"/(name+".json")).read_text(encoding="utf-8"))
    assert render(phase,saved).strip() == (ROOT/"reports"/(name+".md")).read_text(encoding="utf-8").strip()
    fresh=json.loads(json.dumps(run(phase),default=str))
    saved_immutability=saved.pop("immutability")
    fresh_immutability=fresh.pop("immutability")
    for data in (saved,fresh):
        data.pop("runtime_seconds")
    assert saved == fresh
    from research.framework_freeze import assert_frozen_artifact_fingerprint
    assert saved_immutability["before"]==saved_immutability["after"]
    assert fresh_immutability["before"]==fresh_immutability["after"]
    assert_frozen_artifact_fingerprint(saved_immutability["before"])
    if phase == "A":
        anchors={r["entry_date"]:r["position_id"] for r in saved["matched_advanced_77"]}
        assert all(r["position_id"] == anchors[r["date"]] for r in saved["entry_day_cases"])
        assert len(set(r["position_id"] for r in saved["entry_day_cases"])) == 22


@pytest.mark.parametrize("cell", list(FACTORIAL))
def test_family_dependencies_quantities_and_fixed_entries(inputs, cell):
    frozen, _, prepared = inputs
    for p in (frozen["advanced"]["result"]["positions"][i] for i in [0,30,35,55]):
        sim = simulate(prepared, FACTORIAL[cell], anchor=p)
        assert sum(e["side"] == "BUY" for e in sim["executions"]) == 1
        assert sim["executions"][0]["price"] == p["entry_price"]
        assert sim["executions"][0]["quantity"] == p["q0"]
        assert all(e["position_remaining"] >= 0 for e in sim["executions"])
        if not FACTORIAL[cell].first_tp_partial:
            assert not any(e["event_type"] == "FIRST_TP" for e in sim["executions"])
        if not FACTORIAL[cell].protective:
            assert not any(e["reason"] == "PROTECTIVE_STOP" for e in sim["executions"])
        assert all(e["event_type"] != "EXTREME_TP" for e in sim["executions"]) if not FACTORIAL[cell].bias else True
