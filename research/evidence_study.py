"""Offline PRE-V3 analysis; fixed anchors, frozen data, no production writes."""
from dataclasses import replace
import hashlib
import json
import math
import time
import numpy as np
from research import ROOT
from research.baseline import load, immutable_fingerprints, digest, normalize_timestamps
from research.run_ablation import canonical_checks
from research.structural_data import load_inputs
from research.simulation import Prepared
from research.structural_study import POLICIES, PERIODS, CANDIDATES, portfolio_row
from research.evidence_design import MA_VARIANTS, DEFINITIONS, BOOTSTRAP, FEATURES, MODEL, GATE, run_candidate
from research.evidence_statistics import (describe, feature_frame, entry_features, bootstrap,
    concentration, heterogeneity, diagnostic_model)

KEYS=('B','C','D','E','M1','M2','M3')


def paired_row(symbol, policy, key, anchor, features, full, cf):
    a,b=full['positions'][0],cf['positions'][0]
    entry=full['executions'][0]; cost=entry['gross_value']+entry['commission']
    assert cf['executions'][0]==entry
    assert sum(e['quantity'] for e in cf['executions'] if e['side']=='SELL')==anchor['q0']
    return {'symbol':symbol,'is_etf':symbol in ('SPY','QQQ'),'policy':policy,'candidate':key,
        'position_id':anchor['position_id'],'entry_date':anchor['entry_date'][:10],
        'p0':anchor['entry_price'],'q0':anchor['q0'],'entry_cost':cost,'features':features,
        'full_net_pnl':a['net_pnl'],'candidate_net_pnl':b['net_pnl'],
        'delta_net_pnl':b['net_pnl']-a['net_pnl'],
        'delta_return_on_entry_cost_pp':100*(b['net_pnl']-a['net_pnl'])/cost,
        'full_exit_date':a['final_exit_date'][:10],'candidate_exit_date':b['final_exit_date'][:10],
        'full_reason':a['exit_final_close_reason'],'candidate_reason':b['exit_final_close_reason'],
        'full_holding_days':a['holding_days'],'candidate_holding_days':b['holding_days'],
        'delta_holding_days':b['holding_days']-a['holding_days'],
        'full_mfe':a['maximum_favorable_excursion'],'candidate_mfe':b['maximum_favorable_excursion'],
        'full_mae':a['maximum_adverse_excursion'],'candidate_mae':b['maximum_adverse_excursion'],
        'delta_mfe':b['maximum_favorable_excursion']-a['maximum_favorable_excursion'],
        'delta_mae':b['maximum_adverse_excursion']-a['maximum_adverse_excursion'],
        'delta_exposure_days':math.fsum(r['quantity']/anchor['q0'] for r in cf['equity'])-math.fsum(r['quantity']/anchor['q0'] for r in full['equity']),
        'delta_any_exposure_sessions':sum(r['had_exposure'] for r in cf['equity'])-sum(r['had_exposure'] for r in full['equity']),
        'candidate_terminal_censored':b['exit_final_close_reason']=='END_OF_BACKTEST',
        'full_execution_sha256':digest(normalize_timestamps(full['executions'])),
        'candidate_execution_sha256':digest(normalize_timestamps(cf['executions']))}


def breadth(portfolio):
    out=[]
    for key in KEYS:
        for period in PERIODS:
            for policy in POLICIES:
                rs=[r for r in portfolio if (r['candidate'],r['period'],r['policy'])==(key,period,policy)]
                ds=[r['delta_vs_full'] for r in rs]
                out.append({'candidate':key,'period':period,'policy':policy,'n':len(rs),
                    'return_better':sum(d['return_pp']>1e-9 for d in ds),
                    'sharpe_better':sum((d['sharpe'] or 0)>1e-9 for d in ds),
                    'mdd_better':sum(d['mdd_pp']>1e-9 for d in ds),'mdd_worse':sum(d['mdd_pp']<-1e-9 for d in ds),
                    'joint_better_symbols':[r['symbol'] for r in rs if r['delta_vs_full']['return_pp']>1e-9 and (r['delta_vs_full']['sharpe'] or 0)>1e-9],
                    'median':{m:describe([d[m] for d in ds])['median'] for m in ('return_pp','mdd_pp','sharpe','exposure_pp','turnover')},
                    'mdd_p10':float(np.quantile([d['mdd_pp'] for d in ds],.1))})
    return out


def asset_groups(portfolio, matched):
    out=[]
    for key in KEYS:
        for policy in POLICIES:
            for group in ('stocks','etfs'):
                included=lambda s:(s in ('SPY','QQQ'))==(group=='etfs')
                ps=[r for r in portfolio if r['period']=='FULL' and r['candidate']==key and r['policy']==policy and included(r['symbol'])]
                ms=[r for r in matched if r['candidate']==key and r['policy']==policy and included(r['symbol'])]
                out.append({'candidate':key,'policy':policy,'group':group,'symbols':len(ps),
                    'portfolio_median':{m:describe([r['delta_vs_full'][m] for r in ps])['median'] for m in ('return_pp','mdd_pp','sharpe','exposure_pp')},
                    'matched_return_pp':describe([r['delta_return_on_entry_cost_pp'] for r in ms]),
                    'matched_pnl':describe([r['delta_net_pnl'] for r in ms])})
    return out


def gradients(portfolio,matched):
    output=[]
    for period in PERIODS:
        for policy in POLICIES:
            rs=[r for r in portfolio if r['period']==period and r['policy']==policy]
            result={'period':period,'policy':policy,'symbols':11}
            for label,get,increasing in (
                ('return',lambda r:r['summary']['total_return'],True),
                ('exposure',lambda r:r['exposure']['average_close_capital_exposure_pct'],True),
                ('mdd_deterioration',lambda r:r['summary']['max_drawdown'],False)):
                result[label+'_monotonic_symbols']=[]
                for s in sorted({r['symbol'] for r in rs}):
                    v={r['candidate']:get(r) for r in rs if r['symbol']==s}
                    a,d,b=[v[k]*(1 if increasing else -1) for k in ('A','D','B')]
                    if a<=d+1e-9 and d<=b+1e-9: result[label+'_monotonic_symbols'].append(s)
            if period=='FULL':
                ms=[r for r in matched if r['policy']==policy and r['candidate'] in ('B','D')]
                by={(r['symbol'],r['position_id'],r['candidate']):r for r in ms}
                n=0; changed=0; changed_monotonic=0
                for (s,p,k),r in by.items():
                    if k!='D': continue
                    d=r['delta_net_pnl']; b=by[s,p,'B']['delta_net_pnl']
                    ok=-1e-7<=d<=b+1e-7; n+=ok
                    if abs(d)>1e-7 or abs(b)>1e-7:
                        changed+=1; changed_monotonic+=ok
                result['matched_monotonic']=n; result['matched_anchors']=len(ms)//2
                result['changed_matched']=changed; result['changed_matched_monotonic']=changed_monotonic
            output.append(result)
    return output


def forward_rows(symbol, policy, prepared, sim):
    out=[]; pid=0
    for e in sim['executions']:
        if e['side']=='BUY': pid+=1
        if e['reason'] not in ('MA_BREAK_HALF_EXIT','BREAK_DAY_LOW_BROKEN'): continue
        i=prepared.date_index[e['timestamp'][:10]]
        returns={str(n):(prepared.rows[i+n][0].close/e['price']-1 if i+n<len(prepared.rows) else None) for n in (5,10,20,40)}
        out.append({'symbol':symbol,'policy':policy,'position_id':f'position-{pid}',
            'date':e['timestamp'][:10],'event':e['reason'],'execution_price':e['price'],
            'forward_returns':returns})
    return out


def forward_summary(rows):
    out=[]
    for policy in POLICIES:
        for event in ('MA_BREAK_HALF_EXIT','BREAK_DAY_LOW_BROKEN'):
            for group in ('all','stocks','etfs'):
                rs=[r for r in rows if r['policy']==policy and r['event']==event and (group=='all' or ((r['symbol'] in ('SPY','QQQ'))==(group=='etfs')))]
                out.append({'policy':policy,'event':event,'group':group,'events':len(rs),
                    'horizons':{str(n):{**describe([r['forward_returns'][str(n)] for r in rs]),
                        'recovery_frequency':describe([r['forward_returns'][str(n)] for r in rs])['positive']/max(1,describe([r['forward_returns'][str(n)] for r in rs])['n']),
                        'continued_decline_frequency':describe([r['forward_returns'][str(n)] for r in rs])['negative']/max(1,describe([r['forward_returns'][str(n)] for r in rs])['n'])} for n in (5,10,20,40)}})
    return out


def make_gate(breadth_rows, statistics, portfolio):
    result=[]
    for key in KEYS:
        rs=[r for r in breadth_rows if r['candidate']==key]
        full=[r for r in rs if r['period']=='FULL']; subs=[r for r in rs if r['period']!='FULL']
        positive=lambda r:r['median']['return_pp']>1e-9 and (r['median']['sharpe'] or 0)>1e-9
        ss={p:statistics[key][p] for p in POLICIES}
        flags={
            'majority':all(r['return_better']>=6 and r['sharpe_better']>=6 for r in full),
            'period':sum(positive(r) for r in subs)>=4 and all(any(positive(r) for r in subs if r['period']==per) for per in ('A','B')),
            'policy':all(positive(r) for r in full) and max(r['return_better'] for r in full)-min(r['return_better'] for r in full)<=3,
            'drawdown':all(r['median']['mdd_pp']>=-3 and r['mdd_p10']>=-10 for r in full),
            'matched':sum(ss[p]['concentration']['without_nvda_meta']['mean']>0 and ss[p]['concentration']['without_each_symbol_largest_full_winner']['mean']>0 for p in POLICIES)>=2,
            'concentration':sum((ss[p]['concentration']['top_contributions']['3']['fraction_of_positive_improvements'] or 1)<=.5 and ss[p]['concentration']['without_nvda_meta_dollar_sum']>0 for p in POLICIES)>=2,
            'uncertainty':sum(ss[p]['bootstrap']['two_way']['mean_ci95'][0]>0 for p in POLICIES)>=2,
        }
        first=[v for k,v in flags.items() if k!='uncertainty']
        grade='STRONG' if all(flags.values()) else 'MODERATE' if all(first) or sum(first)>=4 else 'WEAK' if any(r['median']['return_pp']>0 for r in full) else 'REJECT'
        strict_sign_change=any(min(r['median'][m] or 0 for r in rs if r['period']==per)<-1e-9 and max(r['median'][m] or 0 for r in rs if r['period']==per)>1e-9 for per in PERIODS for m in ('return_pp','sharpe'))
        robust=flags['policy'] and all(positive(r) for r in subs)
        symbols=sorted({r['symbol'] for r in portfolio})
        all_cells=[s for s in symbols if all(r['delta_vs_full']['return_pp']>0 and (r['delta_vs_full']['sharpe'] or 0)>0 for r in portfolio if r['candidate']==key and r['symbol']==s and r['period'] in ('A','B'))]
        result.append({'candidate':key,'grade':grade,'screens':flags,'walk_forward_eligible':all(first),
            'policy_label':'ROBUST' if robust else 'POLICY-SENSITIVE' if strict_sign_change else 'MIXED',
            'subperiod_positive_cells':sum(positive(r) for r in subs),'both_periods_all_policies_joint_symbols':all_cells,
            'breadth_full':[{k:r[k] for k in ('policy','return_better','sharpe_better','mdd_better','mdd_worse','median','mdd_p10')} for r in full],
            'conservative_mean_matched_ci95':ss['conservative']['bootstrap']['two_way']['mean_ci95']})
    # MA choice is a transparent evidence summary, not a tuned production rule.
    grade_score={'STRONG':3,'MODERATE':2,'WEAK':1,'REJECT':0}
    # Feasibility first: do not select a risk-screen failure over an eligible MA
    # candidate merely because its return breadth or precision is larger.
    ma=max([r for r in result if r['candidate'].startswith('M')],key=lambda r:(r['walk_forward_eligible'],grade_score[r['grade']],sum(r['screens'].values()),min(x['return_better'] for x in r['breadth_full'])))
    allowed=['B','C','D',ma['candidate']]
    ready=[r['candidate'] for r in result if r['candidate'] in allowed and r['walk_forward_eligible']]
    ready=sorted(ready,key=lambda k:(-grade_score[next(r for r in result if r['candidate']==k)['grade']], k))[:2]
    return {'rows':result,'best_supported_ma':ma['candidate'],'ma_selection':'Eligibility/risk feasibility first, then grade, passed screens, minimum policy return breadth; never choose maximum return.', 'matrix_candidates':['A','D','B','C',ma['candidate']],
            'ready_for_walk_forward':ready,'production_v3_created':False,
            'decision':'Exploratory prospective validation only; no production v3' if ready else 'No candidate passes the predeclared evidence gate. Do not create v3.'}


def run(progress=lambda s:None):
    started=time.perf_counter(); before=immutable_fingerprints(); frozen,daily=load(); manifest,frames=load_inputs()
    prior_path=ROOT/'data/first-tp-structural-robustness.json'
    prior=json.loads(prior_path.read_text(encoding='utf-8'))
    protected={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in list((ROOT/'research').glob('*.py'))+list((ROOT/'reports').glob('*.md'))+list((ROOT/'data').glob('*.json')) if not p.name.startswith(('evidence_','pre-v3','run_evidence','test_evidence'))}
    checks=canonical_checks(frozen,daily)
    portfolio=list(prior['portfolio']); old_lookup={(r['symbol'],r['period'],r['policy'],r['candidate']):r for r in portfolio}
    old_c={(r['symbol'],r['policy'],r['position_id']):r for r in prior['matched_candidate_c']['rows']}
    prepared={s:Prepared(frozen['advanced']['request_object'].model_copy(update={'ticker':s}),f) for s,f in frames.items()}
    feature_frames={s:feature_frame(p) for s,p in prepared.items()}
    anchors=[]; matched=[]; forward=[]; parity_count=0; c_parity=0
    for symbol in frames:
        prep=prepared[symbol]; canonical=run_candidate('A',prep)
        for period,(start,end) in PERIODS.items():
            p=prep if period=='FULL' else Prepared(prep.request.model_copy(update={'start_date':start,'end_date':end}),frames[symbol])
            for policy in POLICIES:
                full=canonical if period=='FULL' and policy=='conservative' else run_candidate('A',p,policy=policy)
                new=portfolio_row(symbol,period,policy,'A',p,full,full)
                assert new==old_lookup[symbol,period,policy,'A']; parity_count+=1
                if period=='FULL': forward.extend(forward_rows(symbol,policy,p,full))
                for key in ('M1','M2','M3'):
                    sim=run_candidate(key,p,policy=policy)
                    portfolio.append(portfolio_row(symbol,period,policy,key,p,sim,full))
        for anchor in canonical['positions']:
            features=entry_features(symbol,anchor['entry_date'][:10],anchor['entry_price'],feature_frames)
            anchors.append({'symbol':symbol,'position_id':anchor['position_id'],'entry_date':anchor['entry_date'][:10],
                'p0':anchor['entry_price'],'q0':anchor['q0'],'features':features})
            for policy in POLICIES:
                full=run_candidate('A',prep,anchor=anchor,policy=policy)
                for key in KEYS:
                    cf=run_candidate(key,prep,anchor=anchor,policy=policy)
                    r=paired_row(symbol,policy,key,anchor,features,full,cf); matched.append(r)
                    if key=='C':
                        old=old_c[symbol,policy,anchor['position_id']]
                        assert r['delta_net_pnl']==old['delta_pnl']
                        assert r['full_execution_sha256']==old['full_execution_sha256']
                        assert r['candidate_execution_sha256']==old['candidate_c_execution_sha256']; c_parity+=1
        progress(f'{symbol}: full/MA portfolios verified; matched anchors {len(canonical["positions"])}')
    assert len(anchors)==800 and len(matched)==16800 and len(portfolio)==792
    old_ma=json.loads((ROOT/'data/advanced-v2-ablation.json').read_text(encoding='utf-8'))
    for r in matched:
        if r['symbol']=='NVDA' and r['policy']=='conservative' and r['candidate']=='M1':
            old=next(x for x in old_ma['matched_entry']['rows'] if x['position_id']==r['position_id'])
            assert abs(r['delta_net_pnl']-old['counterfactuals']['ADVANCED_MINUS_MA_BREAK']['delta_pnl_without_minus_full'])<1e-8
    statistics={}
    for key in KEYS:
        statistics[key]={}
        for policy in POLICIES:
            rs=[r for r in matched if r['candidate']==key and r['policy']==policy]
            uncensored=[r for r in rs if not r['candidate_terminal_censored'] and r['full_reason']!='END_OF_BACKTEST']
            statistics[key][policy]={'bootstrap':bootstrap(rs),'concentration':concentration(rs),
                'uncensored_sensitivity':describe([r['delta_return_on_entry_cost_pp'] for r in uncensored]),
                'terminal_censored':sum(r['candidate_terminal_censored'] for r in rs),
                'by_symbol':{s:{'pnl':describe([r['delta_net_pnl'] for r in rs if r['symbol']==s]),
                               'return_pp':describe([r['delta_return_on_entry_cost_pp'] for r in rs if r['symbol']==s]),
                               'exposure_q0_days':describe([r['delta_exposure_days'] for r in rs if r['symbol']==s])} for s in frames},
                'delta_outcomes':{k:describe([r[k] for r in rs]) for k in ('delta_holding_days','delta_mfe','delta_mae','delta_exposure_days')}}
        progress(f'{key}: clustered uncertainty and concentration completed')
    models={key:{policy:diagnostic_model([r for r in matched if r['candidate']==key and r['policy']==policy]) for policy in POLICIES} for key in ('B','C','D')}
    breadth_rows=breadth(portfolio)
    gate=make_gate(breadth_rows,statistics,portfolio)
    after=immutable_fingerprints(); assert before==after; load_inputs()
    for name,sha in protected.items(): assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha
    table_columns=[k for k in matched[0] if k not in ('features','is_etf')]
    table={'schema_version':1,'research_only':True,'columns':table_columns,
           'rows':[[r[k] for k in table_columns] for r in matched],
           'anchors_with_features':anchors,
           'join_key':['symbol','position_id'],'row_key':['symbol','position_id','policy','candidate'],
           'units':{'return':'percentage points of entry gross value plus entry commission','mfe_mae':'fraction of P0, lifecycle high/low, NOT entry features','exposure_days':'sum closing quantity/Q0, equivalent full-position trading sessions','holding_days':'calendar days'},
           'design':'800 conservative Full anchors x 3 separately analyzed policies x 7 alternatives. Never pool policy copies or subperiods as independent entries.'}
    body={'schema_version':1,'research_only':True,'study':'PRE-V3 EVIDENCE GATE','production_v3_created':False,'optimization_performed':False,
        'canonical':prior['canonical'],'data_manifest':manifest,'common_periods':{k:[str(a),str(b)] for k,(a,b) in PERIODS.items()},
        'design':{'bootstrap':BOOTSTRAP,'features':FEATURES,'model':MODEL,'gate':GATE,
                  'first_tp_candidates':{k:c.as_dict() for k,c in CANDIDATES.items()},'ma_variants':DEFINITIONS},
        'counts':{'anchors':len(anchors),'matched_rows':len(matched),'unique_portfolios':len(portfolio),'new_ma_portfolios_including_full':396,'first_tp_portfolios_reused':495},
        'portfolio':portfolio,'breadth':breadth_rows,'matched_statistics':statistics,
        'asset_groups':asset_groups(portfolio,matched),'heterogeneity':heterogeneity(matched,anchors),
        'models':models,'gradients':gradients(portfolio,matched),'forward_events':forward,'forward_summary':forward_summary(forward),
        'feature_missing':{k:sum(a['features'][k] is None for a in anchors) for k in FEATURES},
        'gate':gate,'validation':{'canonical':checks,'full_portfolio_parity_cases':parity_count,'prior_C_matched_parity_cases':c_parity,'NVDA_no_MA_matched_parity_cases':77},
        'immutability':{'before':before,'after':after,'unchanged':True,'existing_research_artifacts_sha256':protected},
        'research_source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'research').glob('evidence_*.py')},
        'source_structural_result_sha256':hashlib.sha256(prior_path.read_bytes()).hexdigest(),
        'matched_table_file':'data/pre-v3-matched-entries.json','matched_table_digest':digest(table),
        'runtime_seconds':time.perf_counter()-started}
    return body,table
