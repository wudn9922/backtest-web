"""Transparent paired descriptive statistics; no iid tests or fitted strategy."""
import hashlib
import math
import numpy as np
import pandas as pd
from research.evidence_design import BOOTSTRAP, MODEL_FEATURES


def finite(value):
    return None if value is None or not np.isfinite(value) else float(value)


def describe(values):
    a = np.asarray([x for x in values if x is not None and np.isfinite(x)], float)
    return {'n': len(a), 'mean': float(a.mean()) if len(a) else None,
            'median': float(np.median(a)) if len(a) else None,
            'sum': math.fsum(a), 'positive': int((a > 1e-9).sum()),
            'negative': int((a < -1e-9).sum()), 'zero': int((abs(a) <= 1e-9).sum())}


def feature_frame(prepared):
    """Every rolling calculation is shifted once before entry-date lookup."""
    d = prepared.enriched
    c, v = d.close, d.volume
    ma = c.rolling(20, min_periods=20).mean()
    out = pd.DataFrame(index=d.index)
    out['reference_ma20'] = ma.shift(1)
    out['reference_atr'] = d.reference_atr
    out['ma20_slope'] = (ma/ma.shift(5)-1).shift(1)
    for n in (20, 60):
        out[f'prior{n}_return'] = c.pct_change(n, fill_method=None).shift(1)
        out[f'rv{n}'] = c.pct_change(fill_method=None).rolling(n, min_periods=n).std(ddof=1).shift(1)*np.sqrt(252)
    out['volume_ratio'] = v.shift(1)/v.shift(2).rolling(20, min_periods=20).mean()
    ma200 = c.rolling(200, min_periods=200).mean().shift(1)
    out['symbol_above_ma200'] = (c.shift(1)>ma200).astype(float).where(ma200.notna())
    out.index = [ts.date().isoformat() for ts in out.index]
    return out


def entry_features(symbol, day, p0, frames):
    r = frames[symbol].loc[day]
    out = {k:finite(r[k]) for k in ('ma20_slope','prior20_return','prior60_return','rv20','rv60','volume_ratio','symbol_above_ma200')}
    out['atr_pct'] = finite(r.reference_atr/p0)
    out['distance_ma20'] = finite(p0/r.reference_ma20-1)
    out['spy_prior_trend'] = finite(frames['SPY'].loc[day,'prior60_return'])
    out['qqq_prior_trend'] = finite(frames['QQQ'].loc[day,'prior60_return'])
    out['spy_above_ma200'] = finite(frames['SPY'].loc[day,'symbol_above_ma200'])
    return out


def cluster_ids(rows):
    syms=sorted({r['symbol'] for r in rows})
    episodes=sorted({r['entry_date'][:4]+'H'+str(1 if int(r['entry_date'][5:7])<=6 else 2) for r in rows})
    t=np.array([syms.index(r['symbol']) for r in rows])
    b=np.array([episodes.index(r['entry_date'][:4]+'H'+str(1 if int(r['entry_date'][5:7])<=6 else 2)) for r in rows])
    return syms, episodes, t, b


def resampling_weights(rows, reps=4000, two_way=True, seed=20260904):
    syms, episodes, t, b = cluster_ids(rows)
    rng=np.random.default_rng(seed)
    tw=rng.multinomial(len(syms),np.ones(len(syms))/len(syms),size=reps)
    weights=tw[:,t].astype(float)
    if two_way:
        bw=rng.multinomial(len(episodes),np.ones(len(episodes))/len(episodes),size=reps)
        weights*=bw[:,b]
    return weights


def weighted_median_samples(x,weights):
    order=np.argsort(x,kind='stable'); sx=x[order]; sw=weights[:,order]
    cumulative=np.cumsum(sw,axis=1); half=sw.sum(axis=1)/2
    left=(cumulative>=half[:,None]).argmax(axis=1)
    # Integer replication median agrees with np.median including even samples.
    right=(cumulative>half[:,None]).argmax(axis=1)
    return (sx[left]+sx[right])/2


def bootstrap(rows, key='delta_return_on_entry_cost_pp', reps=None):
    reps=BOOTSTRAP['replicates'] if reps is None else reps
    x=np.array([r[key] for r in rows]); syms,episodes,t,_=cluster_ids(rows)
    out={'entry_count':len(rows),'ticker_clusters':syms,'episode_clusters':episodes,'replicates':reps,
         'pooled_entry_point':describe(x),'equal_ticker_mean':float(np.mean([x[t==i].mean() for i in range(len(syms))]))}
    for mode in ('ticker_only','two_way'):
        w=resampling_weights(rows,reps,two_way=mode=='two_way')
        w=w[w.sum(axis=1)>0]
        mean=w@x/w.sum(axis=1); median=weighted_median_samples(x,w)
        equal=w/np.bincount(t)[t]
        out[mode]={'mean_ci95':np.quantile(mean,[.025,.975]).tolist(),
                   'median_ci95':np.quantile(median,[.025,.975]).tolist(),
                   'equal_ticker_mean_ci95':np.quantile(equal@x/equal.sum(axis=1),[.025,.975]).tolist(),
                   'valid_replicates':len(w)}
    return out


def concentration(rows):
    values=[r['delta_net_pnl'] for r in rows]
    positive=sorted([r for r in rows if r['delta_net_pnl']>1e-9],key=lambda r:r['delta_net_pnl'],reverse=True)
    total=math.fsum(values); positives=math.fsum(r['delta_net_pnl'] for r in positive)
    drop=set()
    for s in sorted({r['symbol'] for r in rows}):
        group=[r for r in rows if r['symbol']==s]
        best=max(group,key=lambda r:r['full_net_pnl'])
        drop.add((s,best['position_id']))
    kept=[r for r in rows if (r['symbol'],r['position_id']) not in drop]
    # Also remove each ticker's best delta, rather than conflating it with Full winner.
    drop_delta={(s,max([r for r in rows if r['symbol']==s],key=lambda r:r['delta_net_pnl'])['position_id']) for s in {r['symbol'] for r in rows}}
    not_top_delta=[r for r in rows if (r['symbol'],r['position_id']) not in drop_delta]
    ex=[r for r in rows if r['symbol'] not in ('NVDA','META')]
    x=np.array([r['delta_return_on_entry_cost_pp'] for r in rows]); lo,hi=np.quantile(x,[.05,.95])
    sorted_x=np.sort(x); n=int(len(x)*.05)
    changed=[r for r in rows if abs(r['delta_net_pnl'])>1e-7]
    return {'sum_delta_pnl':total,'sum_positive_delta_pnl':positives,
            'top_contributions':{str(k):{'sum':math.fsum(r['delta_net_pnl'] for r in positive[:k]),
                'fraction_of_net_improvement':math.fsum(r['delta_net_pnl'] for r in positive[:k])/total if total>0 else None,
                'fraction_of_positive_improvements':math.fsum(r['delta_net_pnl'] for r in positive[:k])/positives if positives>0 else None} for k in (1,3,5,10)},
            'without_each_symbol_largest_full_winner':describe([r['delta_return_on_entry_cost_pp'] for r in kept]),
            'without_each_symbol_largest_delta':describe([r['delta_return_on_entry_cost_pp'] for r in not_top_delta]),
            'without_nvda_meta':describe([r['delta_return_on_entry_cost_pp'] for r in ex]),
            'without_nvda_meta_dollar_sum':math.fsum(r['delta_net_pnl'] for r in ex),
            'changed_only':describe([r['delta_return_on_entry_cost_pp'] for r in changed]),
            'winsorized_5_95':describe(np.clip(x,lo,hi)),
            'trimmed_5_each_tail':describe(sorted_x[n:len(x)-n]),
            'dropped_full_winners':[{'symbol':s,'position_id':p} for s,p in sorted(drop)],
            'top_positive':[compact_trade(r) for r in positive[:10]],
            'top_negative':[compact_trade(r) for r in sorted(rows,key=lambda r:r['delta_net_pnl'])[:10] if r['delta_net_pnl']<0]}


def compact_trade(r):
    return {k:r[k] for k in ('symbol','policy','candidate','position_id','entry_date','full_net_pnl','candidate_net_pnl','delta_net_pnl','delta_return_on_entry_cost_pp','full_exit_date','candidate_exit_date','full_reason','candidate_reason','delta_holding_days')}


def heterogeneity(rows,anchors):
    out=[]
    # One fixed set of cutpoints from 800 distinct anchors, not policy duplicates.
    for feature in ('ma20_slope','prior60_return','rv20','atr_pct'):
        xs=[a['features'][feature] for a in anchors if a['features'][feature] is not None]
        edges=np.quantile(xs,[.25,.5,.75]).tolist()
        for k in ('B','C','D'):
            for policy in ('conservative','ohlc_heuristic','favorable'):
                for binid in range(4):
                    rs=[r for r in rows if r['candidate']==k and r['policy']==policy and r['features'][feature] is not None and int(np.searchsorted(edges,r['features'][feature],side='right'))==binid]
                    out.append({'feature':feature,'edges':edges,'quantile':binid+1,'candidate':k,'policy':policy,
                        'delta_return_on_entry_cost_pp':describe([r['delta_return_on_entry_cost_pp'] for r in rs]),
                        'symbols':len({r['symbol'] for r in rs}),
                        'stock_count':sum(not r['is_etf'] for r in rs),'etf_count':sum(r['is_etf'] for r in rs)})
    return out


def diagnostic_model(rows, reps=499):
    selected=[r for r in rows if all(r['features'][f] is not None for f in MODEL_FEATURES)]
    syms,episodes,t,_=cluster_ids(selected)
    f=np.array([[r['features'][name] for name in MODEL_FEATURES] for r in selected])
    within=f.copy()
    for i in range(len(syms)):
        within[t==i]-=f[t==i].mean(axis=0)
    scale=np.sqrt(np.mean(within**2,axis=0)); assert (scale>1e-12).all()
    z=(f-f.mean(axis=0))/scale
    x=np.column_stack((np.eye(len(syms))[t],z)); y=np.array([r['delta_return_on_entry_cost_pp'] for r in selected])
    beta=np.linalg.lstsq(x,y,rcond=None)[0]
    weights=resampling_weights(selected,reps)
    estimates=[]
    for w in weights:
        # Absent ticker dummies removed; avoid treating nonidentified slopes as estimates.
        cols=np.r_[np.any((x[:,:len(syms)]!=0)&(w[:,None]>0),axis=0),np.ones(len(MODEL_FEATURES),bool)]
        a=x[:,cols]*np.sqrt(w[:,None]); b=y*np.sqrt(w)
        if np.linalg.matrix_rank(a)<a.shape[1]:
            continue
        estimates.append(np.linalg.lstsq(a,b,rcond=None)[0][-len(MODEL_FEATURES):])
    huber=beta.copy()
    for _ in range(60):
        residual=y-x@huber
        mad=np.median(abs(residual-np.median(residual)))/.67448975
        if mad<1e-10: break
        w=np.minimum(1,1.345*mad/np.maximum(abs(residual),1e-12))
        new=np.linalg.lstsq(x*np.sqrt(w[:,None]),y*np.sqrt(w),rcond=None)[0]
        if np.max(abs(new-huber))<1e-9:
            huber=new; break
        huber=new
    ci=np.quantile(np.array(estimates),[.025,.975],axis=0)
    return {'n':len(selected),'excluded':len(rows)-len(selected),'ticker_fixed_effects':syms,
            'rank':int(np.linalg.matrix_rank(x)),'columns':x.shape[1],'condition_number':float(np.linalg.cond(x)),
            'bootstrap_valid':len(estimates),'coefficients':{name:{'within_ticker_sd':float(scale[i]),
                'ols_pp_per_sd':float(beta[len(syms)+i]),'ci95':ci[:,i].tolist(),
                'huber_pp_per_sd':float(huber[len(syms)+i])} for i,name in enumerate(MODEL_FEATURES)},
            'caution':'Many zero deltas make robust and mean effects differ; model explains association, not future performance. No individual coefficient significance claims.'}
