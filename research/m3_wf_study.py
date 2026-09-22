"""Retrospective walk-forward robustness study. Offline and stdout-only."""
from __future__ import annotations
from dataclasses import asdict
from datetime import date
import hashlib, json, math, time
import numpy as np
import pandas as pd
from research import ROOT
from research.baseline import load, immutable_fingerprints, digest, normalize_timestamps
from research.run_ablation import canonical_checks
from research.structural_data import load_inputs
from research.evidence_simulation import Prepared, simulate
from research.evidence_design import run_candidate
from research.evidence_statistics import describe
from research.m3_wf_design import (POLICIES,SYMBOLS,folds,M3_SEMANTICS,PARAMETER_FREEZE,
 FOLD_EXECUTION,TRAIN_GATE,BREAKDOWN_CRITERIA,REGIME_CRITERIA,RETROSPECTIVE_DECISION,
 FORWARD_FAILURE_CRITERIA,EARLIER_CHECK)

METRICS=('total_return','cagr','max_drawdown','sharpe_ratio','exposure_pct','number_of_positions')

def metric_view(result):
    s=result['summary']; e=result['exposure']
    return {**{k:s[k] for k in METRICS},'turnover':e['two_sided_turnover'],
            'commission':s['total_commission'],'slippage':s['estimated_slippage_cost']}

def deltas(a,b):
    return {'return_pp':100*(b['total_return']-a['total_return']),
            'mdd_pp':100*(b['max_drawdown']-a['max_drawdown']),
            'sharpe':None if a['sharpe_ratio'] is None or b['sharpe_ratio'] is None else b['sharpe_ratio']-a['sharpe_ratio'],
            'exposure_pp':b['exposure_pct']-a['exposure_pct'],
            'positions':b['number_of_positions']-a['number_of_positions'],
            'turnover':b['turnover']-a['turnover']}

def run_pair(req,frame,policy):
    p=Prepared(req.model_copy(update={'execution_policy':policy}),frame)
    full=run_candidate('A',p,policy=policy); m3=run_candidate('M3',p,policy=policy)
    return p,full,m3

def gate_policy(rows):
    ds=[r['train_delta'] for r in rows]; returns=[x['return_pp'] for x in ds]
    positives=[x for x in returns if x>1e-12]
    flags={'return_breadth':sum(x>=-1e-12 for x in returns)>=len(rows)//2+1,
           'return_median':float(np.median(returns))>1e-12,
           'mdd':float(np.median([x['mdd_pp'] for x in ds]))>=-3,
           'concentration':bool(positives) and max(positives)/sum(positives)<=.5+1e-12}
    return {'pass':all(flags.values()),'flags':flags,'return_improved':sum(x>1e-12 for x in returns),
            'return_nonnegative':sum(x>=-1e-12 for x in returns),
            'median_return_delta_pp':float(np.median(returns)),
            'median_mdd_delta_pp':float(np.median([x['mdd_pp'] for x in ds])),
            'median_sharpe_delta':float(np.median([x['sharpe'] for x in ds if x['sharpe'] is not None])),
            'largest_positive_contribution':max(positives)/sum(positives) if positives else None,
            'matched_entry_delta':describe([r['train_matched_mean_return_pp'] for r in rows]),
            'matched_entry_dollar_delta':math.fsum(r['train_matched_sum_pnl'] for r in rows)}

def composite_gate(policy_gates):
    passed=[p for p,v in policy_gates.items() if v['pass']]
    return {'status':'PASS' if 'conservative' in passed and len(passed)>=2 else 'FAIL',
            'passed_policies':passed,'required':'Conservative plus at least one other policy'}

def fixed_anchor_delta(prepared,full,policy):
    values=[]; dollars=[]
    for anchor in full['positions']:
        a=simulate(prepared,anchor=anchor,policy=policy); b=run_candidate('M3',prepared,anchor=anchor,policy=policy)
        delta=b['positions'][0]['net_pnl']-a['positions'][0]['net_pnl']
        ex=a['executions'][0]; cost=ex['gross_value']+ex['commission']
        values.append(100*delta/cost); dollars.append(delta)
    return {'mean':float(np.mean(values)) if values else 0,'median':float(np.median(values)) if values else 0,
            'sum_pnl':math.fsum(dollars),'positions':len(values)}

def fold_bootstrap(test_rows,reps=4000,seed=20260905):
    out={}; rng=np.random.default_rng(seed)
    for policy in POLICIES:
        rs=[r for r in test_rows if r['design']=='expanding' and r['policy']==policy]
        symbols=list(SYMBOLS); fids=sorted({r['fold'] for r in rs})
        sidx=np.array([symbols.index(r['symbol']) for r in rs]); fidx=np.array([fids.index(r['fold']) for r in rs])
        x=np.array([r['test_delta']['return_pp'] for r in rs])
        means=[]; medians=[]
        for _ in range(reps):
            sw=rng.multinomial(len(symbols),np.ones(len(symbols))/len(symbols))[sidx]
            fw=rng.multinomial(len(fids),np.ones(len(fids))/len(fids))[fidx]
            w=sw*fw
            if not w.sum():continue
            means.append(np.average(x,weights=w)); medians.append(np.median(np.repeat(x,w)))
        out[policy]={'n_symbol_fold':len(rs),'symbol_clusters':11,'fold_clusters':6,'replicates':len(means),
                     'mean_delta_pp':float(x.mean()),'median_delta_pp':float(np.median(x)),
                     'mean_ci95':np.quantile(means,[.025,.975]).tolist(),
                     'median_ci95':np.quantile(medians,[.025,.975]).tolist(),
                     'positive_cells':int((x>1e-12).sum()),'negative_cells':int((x<-1e-12).sum())}
    return out

def summary_path(dates,values):
    a=np.asarray(values,float); peaks=np.maximum.accumulate(a); dd=a/peaks-1; bottom=int(np.argmin(dd)); peak=int(np.argmax(a[:bottom+1]))
    daily=pd.Series(a,index=pd.to_datetime(dates)).pct_change().dropna(); sd=daily.std(ddof=1)
    years=max((pd.Timestamp(dates[-1])-pd.Timestamp(dates[0])).days/365.25,1/365.25)
    return {'start':dates[0],'end':dates[-1],'observations':len(a),'total_return':a[-1]-1,
            'cagr':a[-1]**(1/years)-1 if a[-1]>0 else -1,'max_drawdown':float(dd.min()),
            'drawdown_start':dates[peak],'drawdown_bottom':dates[bottom],
            'sharpe':None if not len(daily) or not sd or np.isnan(sd) else float(daily.mean()/sd*np.sqrt(252))}

def stitched(test_cache,gate_by_design):
    result={}
    for policy in POLICIES:
        per_symbol={s:{'dates':[],'v2':[],'m3':[]} for s in SYMBOLS}
        aggregate={'dates':[],'v2':[],'m3':[],'median_v2':[],'median_m3':[]}; prior={'v2':1.,'m3':1.,'median_v2':1.,'median_m3':1.}
        for fid in sorted({k[0] for k in test_cache}):
            normalized={}
            for s in SYMBOLS:
                p,a,b=test_cache[fid,s,policy]; dates=[r['timestamp'][:10] for r in a['equity']]
                av=np.array([r['strategy']/p.request.initial_capital for r in a['equity']]); bv=np.array([r['strategy']/p.request.initial_capital for r in b['equity']])
                assert dates==[r['timestamp'][:10] for r in b['equity']]
                basea=per_symbol[s]['v2'][-1] if per_symbol[s]['v2'] else 1.; baseb=per_symbol[s]['m3'][-1] if per_symbol[s]['m3'] else 1.
                per_symbol[s]['dates']+=dates; per_symbol[s]['v2']+=(basea*av).tolist(); per_symbol[s]['m3']+=(baseb*bv).tolist()
                normalized[s]=(dates,av,bv)
            dates=normalized[SYMBOLS[0]][0]; assert all(normalized[s][0]==dates for s in SYMBOLS)
            av=np.vstack([normalized[s][1] for s in SYMBOLS]); bv=np.vstack([normalized[s][2] for s in SYMBOLS])
            for name,path in [('v2',av.mean(axis=0)),('m3',bv.mean(axis=0)),('median_v2',np.median(av,axis=0)),('median_m3',np.median(bv,axis=0))]:
                aggregate[name]+=(prior[name]*path).tolist(); prior[name]=aggregate[name][-1]
            aggregate['dates']+=dates
        result[policy]={'per_symbol':{s:{'v2':summary_path(x['dates'],x['v2']),'m3':summary_path(x['dates'],x['m3'])} for s,x in per_symbol.items()},
            'equal_weight':{'v2':summary_path(aggregate['dates'],aggregate['v2']),'m3':summary_path(aggregate['dates'],aggregate['m3'])},
            'cross_symbol_median_index':{'v2':summary_path(aggregate['dates'],aggregate['median_v2']),'m3':summary_path(aggregate['dates'],aggregate['median_m3'])},
            'capital_assumption':'At each fold boundary, 11 independent normalized sleeves are reset to equal 1/11 weights. Inside the fold, the equal-weight index is the arithmetic mean of sleeve equity relatives (weights drift); no sleeve borrows another sleeve capital. Source simulations each use canonical $100,000 only to preserve whole-share sizing, then are normalized—this aggregate is a research index, not an executable pooled portfolio.',
            'median_warning':'Median of normalized sleeve paths is not self-financing and is descriptive only.'}
        for design,gates in gate_by_design.items():
            dates=[]; chosen=[]; base=1.
            for fid in sorted(gates):
                use_m3=gates[fid]['composite']['status']=='PASS'
                arrays=[]
                for s in SYMBOLS:
                    p,a,b=test_cache[fid,s,policy]; src=b if use_m3 else a
                    arrays.append(np.array([r['strategy']/p.request.initial_capital for r in src['equity']]))
                path=np.vstack(arrays).mean(axis=0); fd=[r['timestamp'][:10] for r in a['equity']]
                dates+=fd; chosen+=(base*path).tolist(); base=chosen[-1]
            result[policy][design+'_gate_conditioned_equal_weight']=summary_path(dates,chosen)
    return result

def event_segments(executions):
    out={}; pid=0
    for e in executions:
        if e['side']=='BUY':pid+=1; out[pid]=[e]
        elif pid:out[pid].append(e)
    return out

def mechanism_rows(test_cache,full_prepared):
    rows=[]; seen=set()
    for (fid,symbol,policy),(prep,full,m3portfolio) in test_cache.items():
        segments=event_segments(full['executions'])
        for n,pos in enumerate(full['positions'],1):
            breaks=[e for e in segments[n] if e['reason']=='BREAK_DAY_LOW_BROKEN']
            if not breaks:continue
            ex=breaks[-1]; key=(fid,symbol,policy,pos['position_id']); assert key not in seen;seen.add(key)
            anchor=pos; v2=simulate(prep,anchor=anchor,policy=policy); m3=run_candidate('M3',prep,anchor=anchor,policy=policy)
            assert v2['positions'][0]['net_pnl']==pos['net_pnl']
            break_events=[e for e in v2['events'] if e['event']=='BREAK_LOW_BROKEN']; assert len(break_events)==1
            be=break_events[0]; broken=be['timestamp'][:10]; level=be['trigger_price']
            halves=[e for e in v2['events'] if e['event']=='BREAK_HALF_TRIGGERED' and e['timestamp'][:10]<=broken]
            half_exec=[e for e in v2['executions'] if e['reason']=='MA_BREAK_HALF_EXIT' and e['timestamp'][:10]<=broken]
            gp=full_prepared[symbol]; i=gp.date_index[broken]
            fwd={str(n):(gp.rows[i+n][0].close/ex['price']-1 if i+n<len(gp.rows) else None) for n in (5,10,20,40)}
            next10=gp.rows[i+1:min(i+11,len(gp.rows))]; next20=gp.rows[i+1:min(i+21,len(gp.rows))]
            complete20=len(next20)==20; recovered=any(x[0].close>=level for x in next10)
            ret20=fwd['20']; mae20=min((x[0].low/ex['price']-1 for x in next20),default=None)
            if complete20 and recovered and ret20>=0:category='FALSE_BREAKDOWN'
            elif complete20 and not recovered and (ret20<=-.05 or mae20<=-.10):category='TRUE_BREAKDOWN'
            else:category='MIXED'
            mp=m3['positions'][0]; mstart=gp.date_index[broken]; mend=gp.date_index[mp['final_exit_date'][:10]]
            path=gp.rows[mstart:mend+1]
            capital=2*anchor['entry_price']*anchor['q0']*(1+prep.request.commission_pct/100); entrycost=v2['executions'][0]['gross_value']+v2['executions'][0]['commission']
            after=[r for r in m3['equity'] if r['timestamp'][:10]>=broken]
            additional_dd=min((r['strategy']-capital-v2['positions'][0]['net_pnl'])/entrycost*100 for r in after)
            rows.append({'fold':fid,'symbol':symbol,'policy':policy,'position_id':pos['position_id'],'entry_date':pos['entry_date'][:10],
                'entry_price':pos['entry_price'],'q0':pos['q0'],'half_stop_date':halves[-1]['timestamp'][:10],
                'half_stop_level':halves[-1]['trigger_price'],'half_stop_execution_price':half_exec[-1]['price'],
                'break_day_low':level,'break_broken_date':broken,'v2_exit_price':ex['price'],'v2_exit_qty':ex['quantity'],
                'forward_return_from_v2_exit':fwd,'forward_20d_mae':mae20,'recovered_break_level_within_10d':recovered,
                'classification':category,'complete_20d_classification_horizon':complete20,
                'm3_exit_date':mp['final_exit_date'][:10],'m3_exit_price':m3['executions'][-1]['price'],'m3_exit_reason':mp['exit_final_close_reason'],
                'v2_net_pnl':pos['net_pnl'],'m3_net_pnl':mp['net_pnl'],'delta_net_pnl':mp['net_pnl']-pos['net_pnl'],
                'delta_return_on_entry_cost_pp':100*(mp['net_pnl']-pos['net_pnl'])/entrycost,
                'm3_mae_after_broken':min(x[0].low/ex['price']-1 for x in path),
                'm3_mfe_after_broken':max(x[0].high/ex['price']-1 for x in path),
                'largest_additional_marked_drawdown_pp':additional_dd,
                'm3_subsequent_executions':[e for e in m3['executions'] if e['timestamp'][:10]>=broken],
                'v2_execution_sha256':digest(normalize_timestamps(v2['executions'])),'m3_execution_sha256':digest(normalize_timestamps(m3['executions']))})
    return rows

def mechanism_summary(rows):
    out={}
    for p in POLICIES:
        rs=[r for r in rows if r['policy']==p]; x=[r['delta_return_on_entry_cost_pp'] for r in rs]
        out[p]={'events':len(rs),'classification':{c:sum(r['classification']==c for r in rs) for c in ('FALSE_BREAKDOWN','TRUE_BREAKDOWN','MIXED')},
            'complete_classification':sum(r['complete_20d_classification_horizon'] for r in rs),
            'delta_pnl':describe([r['delta_net_pnl'] for r in rs]),'delta_return_pp':describe(x),
            'loss_var95_pp':float(np.quantile(x,.05)) if x else None,
            'worst_m3_mae_after_broken':min((r['m3_mae_after_broken'] for r in rs),default=None),
            'worst_additional_marked_drawdown_pp':min((r['largest_additional_marked_drawdown_pp'] for r in rs),default=None),
            'worst_5':sorted(rs,key=lambda r:r['delta_net_pnl'])[:5],'worst_10':sorted(rs,key=lambda r:r['delta_net_pnl'])[:10]}
    return out

def regime(test_cache):
    labels={}; spy={}
    for fid in sorted({k[0] for k in test_cache}):
        p,_,_=test_cache[fid,'SPY','conservative']; close=p.period.close; ret=close.iloc[-1]/close.iloc[0]-1; vol=close.pct_change().std(ddof=1)*np.sqrt(252)
        trend='uptrend' if ret>.05 else 'downtrend' if ret<-.05 else 'sideways'; v='high_volatility' if vol>=.25 else 'low_volatility' if vol<.15 else 'medium_volatility'
        labels[fid]={'spy_return':float(ret),'spy_realized_volatility':float(vol),'trend':trend,'volatility':v,'uses_only_test_period_data':True}
    rows=[]
    for fid,label in labels.items():
        for p in POLICIES:
            rs=[deltas(metric_view(test_cache[fid,s,p][1]),metric_view(test_cache[fid,s,p][2])) for s in SYMBOLS]
            rows.append({'fold':fid,'policy':p,**label,'median_return_delta_pp':float(np.median([r['return_pp'] for r in rs])),
                'median_mdd_delta_pp':float(np.median([r['mdd_pp'] for r in rs])),'return_improved':sum(r['return_pp']>0 for r in rs)})
    return {'fold_labels':labels,'results':rows}

def earlier_check(frozen,frames):
    prepared={s:Prepared(frozen['advanced']['request_object'].model_copy(update={'ticker':s}),f) for s,f in frames.items()}
    first=[]
    for p in prepared.values():
        ok=p.enriched[['reference_ma','reference_atr','reference_bias_sigma']].notna().all(axis=1)
        first.append(p.enriched.index[np.flatnonzero(ok)[0]].date())
    start=max(first); end=date(2021,8,31); rows=[]
    for s in SYMBOLS:
        req=frozen['advanced']['request_object'].model_copy(update={'ticker':s,'start_date':start,'end_date':end})
        for policy in POLICIES:
            p,a,b=run_pair(req,frames[s],policy); av,bv=metric_view(a),metric_view(b)
            rows.append({'symbol':s,'policy':policy,'actual_start':p.dates[0],'actual_end':p.dates[-1],'bars':len(p.rows),'v2':av,'m3':bv,'delta':deltas(av,bv)})
    years=(end-start).days/365.25; valid=years>=3 and min(r['bars'] for r in rows)>=500
    return {'preferred_period':['2016-01-01','2021-08-31'],'actual_common_fully_warmed_period':[str(start),str(end)],'years':years,'bars':min(r['bars'] for r in rows),
        'valid_for_strong_evidence':valid,'network_status':'query2 Yahoo HTTPS unavailable (curl error 7); cache-only limited check',
        'adjustment_consistent':True,'rows':rows,'breadth':{p:{'return_improved':sum(r['delta']['return_pp']>0 for r in rows if r['policy']==p),
             'sharpe_improved':sum((r['delta']['sharpe'] or 0)>0 for r in rows if r['policy']==p),
             'median_return_delta_pp':float(np.median([r['delta']['return_pp'] for r in rows if r['policy']==p])),
             'median_mdd_delta_pp':float(np.median([r['delta']['mdd_pp'] for r in rows if r['policy']==p]))} for p in POLICIES},
        'interpretation':'Earlier and non-overlapping with discovery, but only a short fully warmed cache interval; reported descriptively and cannot satisfy the frozen external-check validity criterion.'}

def leave_one_out(prior):
    rows=[r for r in prior['portfolio'] if r['candidate']=='M3' and r['period']=='FULL']; out=[]
    for held in SYMBOLS:
        per={}
        for p in POLICIES:
            train=[r for r in rows if r['policy']==p and r['symbol']!=held]; hr=next(r for r in rows if r['policy']==p and r['symbol']==held)
            ds=[r['delta_vs_full'] for r in train]; ret=[x['return_pp'] for x in ds]; pos=[x for x in ret if x>0]
            gate=sum(x>=0 for x in ret)>=6 and np.median(ret)>0 and np.median([x['mdd_pp'] for x in ds])>=-3 and bool(pos) and max(pos)/sum(pos)<=.5
            per[p]={'other_10_gate_pass':bool(gate),'other_10_return_improved':sum(x>0 for x in ret),'other_10_median_return_pp':float(np.median(ret)),
                'other_10_median_sharpe_delta':float(np.median([x['sharpe'] for x in ds])),'heldout_return_delta_pp':hr['delta_vs_full']['return_pp'],
                'heldout_sharpe_delta':hr['delta_vs_full']['sharpe'],'heldout_mdd_delta_pp':hr['delta_vs_full']['mdd_pp']}
        out.append({'heldout':held,'policies':per,'supportive_policies':sum(v['other_10_gate_pass'] and v['heldout_return_delta_pp']>0 for v in per.values())})
    return out

def classify(wf,train_gates,mechanism,loso,earlier):
    directions=sum(sum(1 for fid in {r['fold'] for r in wf['fold_breadth']} if next(r for r in wf['fold_breadth'] if r['fold']==fid and r['policy']==p)['median_return_delta_pp']>0)>=4 for p in POLICIES)
    cells={p:wf['bootstrap'][p]['positive_cells'] for p in POLICIES}
    direction=directions>=2 and sum(cells[p]>=33 for p in POLICIES)>=2
    gate_ok=any(sum(v[f]['composite']['status']=='PASS' for f in v)>=3 for v in train_gates.values())
    cons=mechanism['conservative']; tail=cons['loss_var95_pp'] is not None and cons['loss_var95_pp']>=-10 and cons['worst_additional_marked_drawdown_pp']>=-20
    loo=sum(r['supportive_policies']>=2 for r in loso)>=8 and all(next(r for r in loso if r['heldout']==s)['supportive_policies']>=1 for s in ('NVDA','META','TSLA'))
    precision=sum(wf['bootstrap'][p]['mean_ci95'][0]>0 for p in POLICIES)>=2
    core={'direction':direction,'train_gate':gate_ok,'tail':tail,'leave_one_out':loo}
    if not all(core.values()):label='NOT SUPPORTED'
    elif precision and earlier['valid_for_strong_evidence']:label='STRONG RETROSPECTIVE EVIDENCE — FREEZE AND FORWARD TEST'
    else:label='PROMISING — NEEDS TRUE FORWARD DATA'
    return {'classification':label,'core':core,'strong_requirements':{'bootstrap_precision':precision,'valid_earlier_check':earlier['valid_for_strong_evidence']},
        'policy_positive_fold_count':{p:sum(r['median_return_delta_pp']>0 for r in wf['fold_breadth'] if r['policy']==p) for p in POLICIES},
        'policy_positive_symbol_fold_cells':cells,'freeze_for_true_forward_test':label!='NOT SUPPORTED','production_ready':False}

def run(progress=lambda s:None):
    began=time.perf_counter(); before=immutable_fingerprints(); frozen,daily=load(); manifest,frames=load_inputs(); canonical=canonical_checks(frozen,daily)
    source_freeze={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'research').glob('*.py') if not p.name.startswith(('m3_wf','run_m3'))}
    artifact_freeze={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in list((ROOT/'data').glob('*.json'))+list((ROOT/'reports').glob('*.md')) if not p.name.startswith('m3-')}
    base_req=frozen['advanced']['request_object']; test_cache={}; test_unique={}; train_rows=[]; train_gates={'expanding':{},'rolling':{}}; table=[]
    for fold in folds():
        policy_gates={}
        for policy in POLICIES:
            prows=[]
            for symbol in SYMBOLS:
                treq=base_req.model_copy(update={'ticker':symbol,'start_date':fold['train_start'],'end_date':fold['train_end']})
                tp,ta,tb=run_pair(treq,frames[symbol],policy); match=fixed_anchor_delta(tp,ta,policy)
                testkey=(fold['fold'],symbol,policy)
                if testkey not in test_cache:
                    q=base_req.model_copy(update={'ticker':symbol,'start_date':fold['test_start'],'end_date':fold['test_end']})
                    test_cache[testkey]=run_pair(q,frames[symbol],policy)
                qp,qa,qb=test_cache[testkey]; av,bv=metric_view(ta),metric_view(tb); qav,qbv=metric_view(qa),metric_view(qb)
                row={**{k:(str(v) if isinstance(v,date) else v) for k,v in fold.items()},'symbol':symbol,'policy':policy,
                    'actual_train_start':tp.dates[0],'actual_train_end':tp.dates[-1],'train_v2':av,'train_m3':bv,'train_delta':deltas(av,bv),
                    'train_matched_mean_return_pp':match['mean'],'train_matched_median_return_pp':match['median'],'train_matched_sum_pnl':match['sum_pnl'],'train_matched_positions':match['positions'],
                    'actual_test_start':qp.dates[0],'actual_test_end':qp.dates[-1],'test_v2':qav,'test_m3':qbv,'test_delta':deltas(qav,qbv)}
                prows.append(row);table.append(row)
            policy_gates[policy]=gate_policy(prows);train_rows+=prows
        comp=composite_gate(policy_gates);train_gates[fold['design']][fold['fold']]={'policies':policy_gates,'composite':comp}
        for r in table[-33:]:r['train_gate_policy_pass']=policy_gates[r['policy']]['pass'];r['train_fold_gate_status']=comp['status']
        progress(f"{fold['design']} {fold['fold']}: train gate {comp['status']}")
    assert len(table)==396 and len(test_cache)==198
    fold_breadth=[]
    for fid in sorted({k[0] for k in test_cache}):
        for p in POLICIES:
            rs=[]
            for s in SYMBOLS:
                _,a,b=test_cache[fid,s,p];rs.append({'symbol':s,**deltas(metric_view(a),metric_view(b))})
            for group,symbols in [('all',SYMBOLS),('stocks',SYMBOLS[:-2]),('etfs',SYMBOLS[-2:])]:
                x=[r for r in rs if r['symbol'] in symbols]
                fold_breadth.append({'fold':fid,'policy':p,'group':group,'symbols':len(x),'return_improved':sum(r['return_pp']>0 for r in x),
                    'sharpe_improved':sum((r['sharpe'] or 0)>0 for r in x),'mdd_improved':sum(r['mdd_pp']>0 for r in x),
                    'median_return_delta_pp':float(np.median([r['return_pp'] for r in x])),
                    'median_sharpe_delta':float(np.median([r['sharpe'] for r in x if r['sharpe'] is not None])),
                    'median_mdd_delta_pp':float(np.median([r['mdd_pp'] for r in x]))})
    wf={'fold_breadth':[r for r in fold_breadth if r['group']=='all'],'group_breadth':fold_breadth,
        'bootstrap':fold_bootstrap(table),'stitched':stitched(test_cache,train_gates)}
    mechanisms=mechanism_rows(test_cache,{s:Prepared(base_req.model_copy(update={'ticker':s}),f) for s,f in frames.items()}); mech_summary=mechanism_summary(mechanisms)
    reg=regime(test_cache); earlier=earlier_check(frozen,frames)
    prior=json.loads((ROOT/'data/pre-v3-evidence-gate.json').read_text(encoding='utf-8')); loso=leave_one_out(prior)
    decision=classify(wf,train_gates,mech_summary,loso,earlier)
    after=immutable_fingerprints();assert before==after;load_inputs()
    for name,h in source_freeze.items():assert hashlib.sha256((ROOT/'research'/name).read_bytes()).hexdigest()==h
    for name,h in artifact_freeze.items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==h
    compact_columns=list(table[0]); fold_table={'schema_version':1,'study':'M3 retrospective walk-forward fold table','columns':compact_columns,
       'rows':[[r[k] for k in compact_columns] for r in table],'unique_test_note':FOLD_EXECUTION['same_test_twice']}
    body={'schema_version':1,'study':'M3 Retrospective Walk-Forward Robustness Validation','research_only':True,'true_out_of_sample':False,
        'production_v3_created':False,'optimization_performed':False,'strategy_version':2,
        'canonical':{k:{'backtest_id':v['id'],'request':v['request'],'summary':v['result']['summary'],'result_sha256':v['result_sha256']} for k,v in frozen.items()},
        'freeze':{'m3_semantics':M3_SEMANTICS,'parameters':PARAMETER_FREEZE,'source_sha256':source_freeze},
        'design':{'fold_execution':FOLD_EXECUTION,'train_gate':TRAIN_GATE,'breakdown_classification':BREAKDOWN_CRITERIA,'regime':REGIME_CRITERIA,'decision':RETROSPECTIVE_DECISION,'earlier':EARLIER_CHECK,'forward_failure_criteria':FORWARD_FAILURE_CRITERIA},
        'data_manifest':manifest,'folds':[{k:(str(v) if isinstance(v,date) else v) for k,v in f.items()} for f in folds()],
        'counts':{'fold_table_rows':len(table),'unique_test_symbol_policy_folds':len(test_cache),'mechanism_events_policy_specific':len(mechanisms)},
        'train_gates':train_gates,'walk_forward':wf,'mechanism_rows':mechanisms,'mechanism_summary':mech_summary,
        'regime':reg,'earlier_historical_external_check':earlier,'leave_one_symbol_out':loso,'decision':decision,
        'validation':{'canonical':canonical,'test_raw_results_identical_across_designs':True,'m3_prior_semantics_sha256':source_freeze['evidence_strategy.py'],
                      'production_and_history_fingerprints_unchanged':True},
        'immutability':{'before':before,'after':after,'existing_artifacts_sha256':artifact_freeze},
        'fold_table_file':'data/m3-retrospective-walk-forward-folds.json','fold_table_sha256':digest(fold_table),
        'runtime_seconds':time.perf_counter()-began}
    return body,fold_table
