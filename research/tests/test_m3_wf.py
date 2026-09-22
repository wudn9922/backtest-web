from datetime import date
from pathlib import Path
import json,sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from research import ROOT
from research.baseline import load,immutable_fingerprints
from research.structural_data import load_inputs
from research.evidence_simulation import Prepared
from research.evidence_design import run_candidate
from research.m3_wf_design import folds,TRAIN_GATE,BREAKDOWN_CRITERIA,M3_SEMANTICS
from research.m3_wf_study import gate_policy,composite_gate,summary_path

def test_fold_boundaries_are_chronological_nonoverlapping_and_frozen():
    fs=folds(); assert len(fs)==12
    for design in ('expanding','rolling'):
        x=[f for f in fs if f['design']==design]
        assert len(x)==6 and all(f['train_end']<f['test_start'] for f in x)
        assert all(x[i]['test_end']<x[i+1]['test_start'] for i in range(5))
        assert all((f['test_end']-f['test_start']).days in range(180,186) for f in x)
        if design=='expanding':assert len({f['train_start'] for f in x})==1
        else:assert all(f['train_start'].year==f['test_start'].year-2 for f in x)

def test_gate_is_fixed_and_requires_conservative_plus_another_policy():
    def row(ret,mdd=0,sh=.1):return {'train_delta':{'return_pp':ret,'mdd_pp':mdd,'sharpe':sh},'train_matched_mean_return_pp':ret,'train_matched_sum_pnl':ret}
    passed=gate_policy([row(x) for x in (1,2,3,4,5,6,-1,-1,-1,-1,-1)])
    assert passed['pass'] and passed['return_improved']==6
    concentrated=gate_policy([row(x) for x in (10,1,1,1,1,1,-1,-1,-1,-1,-1)])
    assert not concentrated['pass'] and not concentrated['flags']['concentration']
    assert composite_gate({'conservative':passed,'ohlc_heuristic':passed,'favorable':concentrated})['status']=='PASS'
    assert composite_gate({'conservative':concentrated,'ohlc_heuristic':passed,'favorable':passed})['status']=='FAIL'
    assert TRAIN_GATE['return_breadth'].startswith('Strict majority')

def test_breakdown_labels_are_descriptive_not_strategy_parameters():
    assert '10/20-session' in BREAKDOWN_CRITERIA['fixed_note']
    assert 'only_change' in M3_SEMANTICS and 'full exit' in M3_SEMANTICS['only_change']

def test_m3_exactly_matches_pre_v3_saved_semantics():
    frozen,daily=load();p=Prepared(frozen['advanced']['request_object'],daily)
    a=run_candidate('M3',p)
    saved=json.loads((ROOT/'data/pre-v3-evidence-gate.json').read_text(encoding='utf-8'))
    row=next(r for r in saved['portfolio'] if (r['symbol'],r['period'],r['policy'],r['candidate'])==('NVDA','FULL','conservative','M3'))
    assert a['summary']==row['summary'];assert a['exposure']==row['exposure']
    from research.baseline import digest,normalize_timestamps
    assert digest(normalize_timestamps(a['executions']))==row['execution_sha256']

def test_stitched_summary_known_path():
    s=summary_path(['2024-01-01','2024-01-02','2024-01-03'],[1,1.1,.99])
    assert s['total_return']==pytest.approx(-.01);assert s['max_drawdown']==pytest.approx(-.1)

def test_saved_wf_reconciles_if_present():
    path=ROOT/'data/m3-retrospective-walk-forward.json'
    if not path.exists():pytest.skip('not generated yet')
    d=json.loads(path.read_text(encoding='utf-8'));f=json.loads((ROOT/d['fold_table_file']).read_text(encoding='utf-8'))
    from research.baseline import digest
    assert digest(f)==d['fold_table_sha256'];assert len(f['rows'])==396
    from research.framework_freeze import assert_frozen_artifact_fingerprint
    assert d['immutability']['before']==d['immutability']['after']
    assert_frozen_artifact_fingerprint(d['immutability']['before'])
    assert d['validation']['canonical']['advanced']['executions_differences']==0
    assert not d['true_out_of_sample'] and not d['production_v3_created'] and not d['optimization_performed']
    assert d['decision']['classification']=='NOT SUPPORTED'
    assert d['decision']['freeze_for_true_forward_test'] is False
    assert not (ROOT/'reports/m3-frozen-spec.md').exists()

def test_full_wf_replay_and_report_are_exact():
    path=ROOT/'data/m3-retrospective-walk-forward.json'
    if not path.exists():pytest.skip('not generated yet')
    from research.m3_wf_study import run
    from research.m3_wf_report import render
    old=json.loads(path.read_text(encoding='utf-8'));oldfold=json.loads((ROOT/old['fold_table_file']).read_text(encoding='utf-8'))
    fresh,foldtable=run();fresh=json.loads(json.dumps(fresh,default=str,allow_nan=False))
    for key in old:
        if key in ('runtime_seconds','freeze','immutability'):continue
        assert fresh[key]==old[key],key
    # A later isolated research study may add source/artifact files.  Every
    # item frozen by M3 must remain byte-identical; additive files are not a
    # mutation of the already-persisted M3 result.
    assert fresh['freeze']['m3_semantics']==old['freeze']['m3_semantics']
    assert fresh['freeze']['parameters']==old['freeze']['parameters']
    for name,sha in old['freeze']['source_sha256'].items():
        assert fresh['freeze']['source_sha256'][name]==sha
    from research.framework_freeze import assert_frozen_artifact_fingerprint
    assert fresh['immutability']['before']==fresh['immutability']['after']
    assert old['immutability']['before']==old['immutability']['after']
    assert_frozen_artifact_fingerprint(old['immutability']['before'])
    for name,sha in old['immutability']['existing_artifacts_sha256'].items():
        assert fresh['immutability']['existing_artifacts_sha256'][name]==sha
    assert foldtable==oldfold
    assert render(old,oldfold)==(ROOT/'reports/m3-retrospective-walk-forward.md').read_text(encoding='utf-8')
