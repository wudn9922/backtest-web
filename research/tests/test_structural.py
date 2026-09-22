from dataclasses import replace
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from research import ROOT
from research.baseline import load, immutable_fingerprints, normalize_timestamps
from research.structural_data import load_inputs, admissible, SYMBOLS
from research.structural_study import CANDIDATES, NO_PROTECTIVE, POLICIES, fixed_summary
from research.simulation import Prepared, simulate
from research.strategy import ResearchAdvanced
from research.modules import FULL
from app.backtest.models import AdvancedStrategyState, StrategyState, StrategyParameters
from app.backtest.strategies.base import Bar, EventRecorder
from app.backtest.engine import BacktestEngine


@pytest.fixture(scope="module")
def data():
    before=immutable_fingerprints()
    frozen,daily=load()
    manifest,frames=load_inputs()
    yield frozen,Prepared(frozen["advanced"]["request_object"],daily),manifest,frames
    assert before==immutable_fingerprints()


def test_only_five_fixed_structures_no_parameter_sweep():
    assert list(CANDIDATES)==list("ABCDE")
    assert CANDIDATES["A"].modules==FULL
    assert CANDIDATES["D"].first_tp_fraction==.25
    assert all(c.modules.volume and c.modules.day2 and c.modules.ma_break and c.modules.first_tp and c.modules.protective for c in CANDIDATES.values())
    assert not CANDIDATES["B"].modules.first_tp_partial
    assert not CANDIDATES["C"].modules.bias and not CANDIDATES["C"].modules.atr
    assert NO_PROTECTIVE.modules==replace(CANDIDATES["C"].modules,protective=False)
    with pytest.raises(ValueError):
        ResearchAdvanced(StrategyParameters(),EventRecorder(),first_tp_fraction=.4)


@pytest.mark.parametrize("current,expected",[(85,21),(101,25),(19,0),(20,5)])
def test_25_percent_uses_current_integer_quantity_and_minimum(current,expected):
    q0=101 if current>=85 else 100
    s=ResearchAdvanced(StrategyParameters(),EventRecorder(),modules=replace(FULL,bias=False,atr=False),first_tp_fraction=.25)
    s.s=AdvancedStrategyState(state=StrategyState.LONG_NORMAL,q0=q0,current_qty=current,entry_price=100,entry_day=date(2025,1,6))
    fills=[]
    s.process_bar(Bar(datetime(2025,1,8,tzinfo=timezone.utc),102,104,101,103,1000),trading_day=date(2025,1,8),reference_ma=90,reference_atr=20,bias_sigma=.2,buy_qty=0,fill=lambda *a:fills.append(a))
    assert sum(f[2] for f in fills)==expected
    assert s.s.current_qty==current-expected and s.s.first_tp_triggered
    assert all(f[3]=="FIRST_TP" for f in fills)


def test_25_checkpoint_does_not_change_half_risk_quantity():
    s=ResearchAdvanced(StrategyParameters(),EventRecorder(),first_tp_fraction=.25)
    s.s=AdvancedStrategyState(state=StrategyState.LONG_NORMAL,q0=101,current_qty=85,entry_price=100,entry_day=date(2025,1,6))
    fills=[]
    s.process_bar(Bar(datetime(2025,1,8,tzinfo=timezone.utc),100,101,98,100,1000),trading_day=date(2025,1,8),reference_ma=100,reference_atr=20,bias_sigma=.2,buy_qty=0,fill=lambda *a:fills.append(a))
    assert fills[0][2:5]==(42,"MA_HALF_EXIT","MA_BREAK_HALF_EXIT")
    assert s.s.current_qty==43


def test_provider_adjustment_isolation_and_common_calendar(data):
    _,_,manifest,frames=data
    assert set(frames)==set(SYMBOLS)
    assert len({tuple(ts.date() for ts in f.index) for f in frames.values()})==1
    assert all(r["bars"]==1442 and r["period_bars"]==1255 and r["warmup_bars"]==187 for r in manifest["symbols"])
    assert all(admissible(r["provider"],r["adjustment_mode"]) for r in manifest["symbols"])
    assert not admissible("stooq","provider_native_adjusted_for_splits")
    assert not admissible("yahoo","raw")


@pytest.mark.parametrize("symbol",SYMBOLS)
@pytest.mark.parametrize("policy",POLICIES)
def test_all_on_all_symbols_all_policies_exact_production_parity(data,symbol,policy):
    frozen,_,_,frames=data
    req=frozen["advanced"]["request_object"].model_copy(update={"ticker":symbol,"execution_policy":policy})
    prepared=Prepared(req,frames[symbol])
    before=req.model_dump()
    a=BacktestEngine().run(req,frames[symbol])
    b=CANDIDATES["A"].run(prepared,policy=policy)
    assert normalize_timestamps(a["executions"])==normalize_timestamps(b["executions"])
    # Production adds UI-only policy/ambiguity labels after calculate_metrics;
    # compare every numerical performance metric, not those reporting extras.
    assert set(a["summary"])-set(b["summary"])=={"ambiguous_days","ambiguous_positions","intrabar_assumption"}
    assert {k:a["summary"][k] for k in b["summary"]}==b["summary"]
    assert [r["strategy"] for r in a["equity_curve"]]==[r["strategy"] for r in b["equity"]]
    assert req.model_dump()==before


@pytest.mark.parametrize("key",list(CANDIDATES))
def test_candidate_fixed_anchor_shares_costs_and_regime(data,key):
    frozen,prepared,_,_=data
    anchor=frozen["advanced"]["result"]["positions"][30]
    sim=CANDIDATES[key].run(prepared,anchor=anchor)
    ex=sim["executions"]; pos=sim["positions"][0]
    assert ex[0]["quantity"]==anchor["q0"] and ex[0]["price"]==anchor["entry_price"]
    assert sum(e["side"]=="BUY" for e in ex)==1
    assert sum(e["quantity"] for e in ex if e["side"]=="SELL")==anchor["q0"]
    assert all(e["position_remaining"]>=0 for e in ex)
    assert pos["gross_pnl"]-sum(e["commission"] for e in ex)==pytest.approx(pos["net_pnl"],abs=1e-8)
    assert sum(e["slippage"] for e in ex)>0
    assert any(e["event"]=="FIRST_TP_TRIGGERED" for e in sim["events"])
    if key in "BC":
        assert not any(e["event_type"]=="FIRST_TP" for e in ex)
    if key in "CE":
        assert not any(e["event_type"]=="EXTREME_TP" for e in ex)


def test_40_session_horizon_no_reentry_and_no_future_dependence(data):
    frozen,prepared,_,_=data
    anchor=frozen["advanced"]["result"]["positions"][0]
    start=prepared.date_index[anchor["entry_date"][:10]]
    result=NO_PROTECTIVE.run(prepared,anchor=anchor,horizon_sessions=40)
    assert result["horizon"]["complete_horizon_available"]
    assert result["horizon"]["target_date"]==prepared.dates[start+40]
    assert len(result["equity"])<=41
    assert result["executions"][-1]["reason"]=="RESEARCH_40_SESSION_HORIZON"
    assert result["executions"][-1]["timestamp"][:10]==prepared.dates[start+40]
    frame=prepared.daily.copy()
    future=[ts.date().isoformat()>prepared.dates[start+40] for ts in frame.index]
    frame.loc[future,["open","high","low","close"]]*=10
    altered=Prepared(prepared.request,frame)
    replay=NO_PROTECTIVE.run(altered,anchor=anchor,horizon_sessions=40)
    assert result==replay
    assert sum(e["side"]=="BUY" for e in result["executions"])==1
    with pytest.raises(ValueError):
        simulate(prepared,horizon_sessions=40)


def test_incomplete_horizon_excluded_even_if_natural_exit_early(data):
    frozen,prepared,_,_=data
    anchor=frozen["advanced"]["result"]["positions"][-1]
    result=CANDIDATES["C"].run(prepared,anchor=anchor,horizon_sessions=40)
    assert not result["horizon"]["complete_horizon_available"]
    fake={"symbol":"NVDA","policy":"conservative","horizon":result["horizon"]}
    summary=fixed_summary([fake])["conservative"]["pooled"]
    assert summary["all_anchors"]==1 and summary["complete_horizon_anchors"]==0
    assert summary["endpoint_censored_excluded"]==1 and summary["sum_delta_on_minus_off"]==0


def test_report_aggregates_and_saved_baselines(data):
    path=ROOT/"data/first-tp-structural-robustness.json"
    saved=json.loads(path.read_text(encoding="utf-8"))
    assert len(saved["portfolio"])==11*5*3*3
    from research.framework_freeze import assert_frozen_artifact_fingerprint
    assert saved["immutability"]["unchanged"] and saved["immutability"]["before"]==saved["immutability"]["after"]
    assert_frozen_artifact_fingerprint(saved["immutability"]["after"])
    assert all(r["executions_equal"] and r["equity_equal"] and r["metrics_equal"] for r in saved["previous_research_verification"])
    from research.structural_study import breadth, robustness, fixed_summary, match_summary
    assert saved["breadth"]==breadth(saved["portfolio"])
    assert saved["robustness"]==robustness(saved["portfolio"],saved["breadth"])
    assert saved["protective_fixed_horizon"]["summary"]==fixed_summary(saved["protective_fixed_horizon"]["rows"])
    assert saved["matched_candidate_c"]["summary"]==match_summary(saved["matched_candidate_c"]["rows"])
    from research.structural_report import render
    validation=json.loads((ROOT/"data/first-tp-structural-validation.json").read_text(encoding="utf-8"))
    assert render(saved,validation).strip()==(ROOT/"reports/first-tp-structural-robustness.md").read_text(encoding="utf-8").strip()
    # Re-run all 495 portfolios and all matched lifecycles entirely offline.
    # Runtime varies, and a report renderer was added after numerical freezing;
    # every previously frozen numerical source must still match its fingerprint.
    import hashlib
    for name,sha in saved["research_source_sha256"].items():
        assert hashlib.sha256((ROOT/"research"/name).read_bytes()).hexdigest()==sha
    from research.run_structural import run
    fresh=json.loads(json.dumps(run(),default=str))
    saved_immutability=saved.pop("immutability")
    fresh_immutability=fresh.pop("immutability")
    for result in (saved,fresh):
        result.pop("runtime_seconds")
        result.pop("research_source_sha256")
    assert saved==fresh
    assert fresh_immutability["before"]==fresh_immutability["after"]
    assert_frozen_artifact_fingerprint(saved_immutability["before"])
