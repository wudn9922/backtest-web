from datetime import datetime, date, timezone
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from research import ROOT
from research.baseline import load, immutable_fingerprints
from research.structural_data import load_inputs
from research.structural_study import CANDIDATES, POLICIES
from research.simulation import Prepared, simulate
from research.evidence_design import run_candidate, MA_VARIANTS, GATE
from research.evidence_strategy import EvidenceAdvanced
from research.evidence_statistics import feature_frame, entry_features, bootstrap, weighted_median_samples, resampling_weights
from app.backtest.models import StrategyParameters, AdvancedStrategyState, StrategyState
from app.backtest.strategies.base import Bar, EventRecorder

@pytest.fixture(scope='module')
def data():
    before=immutable_fingerprints(); frozen,daily=load(); _,frames=load_inputs()
    yield frozen,daily,frames
    assert before==immutable_fingerprints()

@pytest.mark.parametrize('policy',POLICIES)
@pytest.mark.parametrize('key',list(CANDIDATES))
def test_new_isolated_copy_preserves_all_five_frozen_candidates(data,key,policy):
    f,d,_=data; p=Prepared(f['advanced']['request_object'],d)
    assert run_candidate(key,p,policy=policy)==CANDIDATES[key].run(p,policy=policy)

@pytest.mark.parametrize('mode',['half_only','exit_off'])
def test_half_risk_modes_have_explicit_tracking_and_rearming(mode):
    rec=EventRecorder(); s=EvidenceAdvanced(StrategyParameters(),rec,ma_mode=mode)
    s.s=AdvancedStrategyState(state=StrategyState.LONG_NORMAL,q0=100,current_qty=100,entry_price=120,entry_day=date(2025,1,2))
    fills=[]
    for day in (6,7):
        b=Bar(datetime(2025,1,day,tzinfo=timezone.utc),99,100,97 if day==6 else 96,98,1000)
        s.process_bar(b,trading_day=b.timestamp.date(),reference_ma=100,reference_atr=10,bias_sigma=.2,buy_qty=0,fill=lambda *a:fills.append(a))
    assert not any(f[4]=='BREAK_DAY_LOW_BROKEN' for f in fills)
    assert s.s.current_qty==(25 if mode=='half_only' else 50)
    assert s.s.break_day_low==(None if mode=='half_only' else 97)
    assert all(f[4]=='MA_BREAK_HALF_EXIT' for f in fills)

def test_exit_off_retains_close_only_reset_and_half_reeligibility():
    rec=EventRecorder(); s=EvidenceAdvanced(StrategyParameters(),rec,ma_mode='exit_off')
    s.s=AdvancedStrategyState(state=StrategyState.BREAK_PROTECTION,q0=100,current_qty=50,entry_price=120,entry_day=date(2025,1,2),break_day=date(2025,1,3),break_day_low=97)
    b=Bar(datetime(2025,1,6,tzinfo=timezone.utc),99,100,98,99,1000)
    s.process_bar(b,trading_day=b.timestamp.date(),reference_ma=100,reference_atr=10,bias_sigma=.2,buy_qty=0,fill=lambda *a:None)
    assert s.s.break_day_low==97
    s.end_day(trading_day=b.timestamp.date(),daily_close=99,daily_high=100,daily_low=98,daily_volume=1000,previous_day_volume=1000,current_day_ma=97.5,timestamp=b.timestamp,reference_ma=100,reference_atr=10,bias_sigma=.2)
    assert s.s.break_day_low is None and s.s.state==StrategyState.LONG_NORMAL

def test_entry_features_never_use_entry_or_future_ohlcv(data):
    f,d,frames=data; req=f['advanced']['request_object']
    fs={s:feature_frame(Prepared(req.model_copy(update={'ticker':s}),df)) for s,df in frames.items()}
    anchor=f['advanced']['result']['positions'][35]; day=anchor['entry_date'][:10]
    before=entry_features('NVDA',day,anchor['entry_price'],fs)
    changed={}
    for s,df in frames.items():
        df=df.copy(); mask=[ts.date().isoformat()>=day for ts in df.index]
        df.loc[mask,['open','high','low','close','volume']]*=5
        changed[s]=feature_frame(Prepared(req.model_copy(update={'ticker':s}),df))
    assert before==entry_features('NVDA',day,anchor['entry_price'],changed)
    raw=frames['NVDA']; i=next(i for i,t in enumerate(raw.index) if t.date().isoformat()==day)
    assert before['volume_ratio']==pytest.approx(raw.volume.iloc[i-1]/raw.volume.iloc[i-21:i-1].mean())
    assert before['prior20_return']==pytest.approx(raw.close.iloc[i-1]/raw.close.iloc[i-21]-1)

def test_cluster_sampling_preserves_pair_dependence_and_median():
    rows=[{'symbol':s,'entry_date':day,'delta_return_on_entry_cost_pp':v} for s in ('A','B') for day,v in [('2022-01-01',0),('2022-02-01',0),('2022-07-01',3),('2022-08-01',-1)]]
    w=resampling_weights(rows,200)
    assert np.array_equal(w[:,0],w[:,1]) and np.array_equal(w[:,2],w[:,3])
    x=np.array([r['delta_return_on_entry_cost_pp'] for r in rows])
    nonempty=w[w.sum(axis=1)>0]
    actual=weighted_median_samples(x,nonempty)
    expected=[np.median(np.repeat(x,wi.astype(int))) for wi in nonempty]
    assert np.allclose(actual,expected)
    assert bootstrap(rows,reps=200)==bootstrap(rows,reps=200)

def test_fixed_design_has_no_parameter_sweep():
    assert len(MA_VARIANTS)==4
    assert set(GATE)>={'majority','period','policy','matched','concentration','uncertainty'}

def test_saved_evidence_artifacts_reconcile_if_present():
    path=ROOT/'data/pre-v3-evidence-gate.json'
    if not path.exists():pytest.skip('Report not generated yet')
    from research.baseline import digest
    d=json.loads(path.read_text(encoding='utf-8'))
    t=json.loads((ROOT/d['matched_table_file']).read_text(encoding='utf-8'))
    assert digest(t)==d['matched_table_digest']
    assert len(t['rows'])==16800 and len(t['anchors_with_features'])==800
    columns=t['columns']; rs=[dict(zip(columns,r)) for r in t['rows']]
    for r in rs:
        assert r['delta_net_pnl']==r['candidate_net_pnl']-r['full_net_pnl']
        assert r['delta_return_on_entry_cost_pp']==100*r['delta_net_pnl']/r['entry_cost']
    from research.framework_freeze import assert_frozen_artifact_fingerprint
    assert d['immutability']['before']==d['immutability']['after']
    assert_frozen_artifact_fingerprint(d['immutability']['before'])
    assert d['validation']['full_portfolio_parity_cases']==99
    assert d['validation']['prior_C_matched_parity_cases']==2400
    # Risk-eligible MA alternatives must not be eclipsed by high-return ones
    # that fail the declared risk screen.
    assert d['gate']['best_supported_ma']=='M3'
    assert d['gate']['ready_for_walk_forward']==['M3']
    for key in ('B','C','D','E','M1','M2','M3'):
        for policy in POLICIES:
            group=[r for r in rs if r['candidate']==key and r['policy']==policy]
            assert len(group)==800
            assert np.mean([r['delta_return_on_entry_cost_pp'] for r in group])==pytest.approx(d['matched_statistics'][key][policy]['bootstrap']['pooled_entry_point']['mean'])

def test_full_evidence_replay_is_reproducible():
    path=ROOT/'data/pre-v3-evidence-gate.json'
    if not path.exists():pytest.skip('Report not generated yet')
    from research.evidence_study import run
    from research.evidence_report import render
    old=json.loads(path.read_text(encoding='utf-8'))
    fresh,table=run()
    # Compare the persisted JSON representation: tuples become JSON arrays.
    fresh=json.loads(json.dumps(fresh,default=str,allow_nan=False))
    for k in old:
        if k in ('runtime_seconds','research_source_sha256','immutability'):continue
        assert fresh[k]==old[k], k
    from research.framework_freeze import assert_frozen_artifact_fingerprint
    assert fresh['immutability']['before']==fresh['immutability']['after']
    assert old['immutability']['before']==old['immutability']['after']
    assert_frozen_artifact_fingerprint(old['immutability']['before'])
    # Later studies may add isolated files. Every file frozen by this study
    # must remain byte-identical; an additive research file is not a mutation.
    for name,sha in old['immutability']['existing_research_artifacts_sha256'].items():
        assert fresh['immutability']['existing_research_artifacts_sha256'][name]==sha
    for name,sha in old['research_source_sha256'].items():
        assert fresh['research_source_sha256'][name]==sha
    saved_table=json.loads((ROOT/old['matched_table_file']).read_text(encoding='utf-8'))
    assert table==saved_table
    assert render(old)==(ROOT/'reports/pre-v3-evidence-gate.md').read_text(encoding='utf-8')
