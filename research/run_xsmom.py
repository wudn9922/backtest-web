"""Offline benchmark study: fixed inputs and specification, no registry writes."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
import numpy as np
import pandas as pd

from research import ROOT
from research.baseline import immutable_fingerprints, load
from research.environment_v3_data import sha256_file
from research.environment_v3_design import ETF_RESEARCH_UNIVERSE, MARKET_CYCLE_WINDOWS, CRISIS_EPISODES
from research.environment_v3_extension import _selected_frame, _load_rate_model, _json_safe
from research.environment_v3_snapshot import assert_snapshot_immutable, assert_snapshot_inputs_unchanged
from research.xsmom import SPEC_HASH, verify_spec, rankings, simulate, slice_metrics, paired_uncertainty

KINDS = ("RS", "EW", "SPY", "QQQ")


def write_json(name, payload):
    (ROOT / "data" / name).write_text(json.dumps(_json_safe(payload),ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")


def differences(a,b):
    return {k: a[k]-b[k] if a.get(k) is not None and b.get(k) is not None else None
            for k in ("total_return","cagr","mdd","sharpe","sortino","calmar","exposure")}


def window_table(suite, windows):
    out=[]
    for name,start,end in windows:
        m={k:slice_metrics(v,str(start),str(end)) for k,v in suite.items()}
        if not m["RS"]: continue
        out.append({"window":name,"start":str(start),"end":str(end),"metrics":m,
                    "vs_EW":differences(m["RS"],m["EW"]),"vs_SPY":differences(m["RS"],m["SPY"])})
    return out


def main():
    begun=time.monotonic(); verify_spec()
    snapshot=json.loads((ROOT/"data/research-environment-current-snapshot.json").read_text(encoding="utf-8"))
    assert_snapshot_immutable(snapshot); assert_snapshot_inputs_unchanged(snapshot)
    protected=immutable_fingerprints()
    registry=sha256_file(ROOT/"data/research-candidate-registry.json")
    frozen,_=load(); request=frozen["advanced"]["request"]
    capital=request["initial_capital"]; comm=request["commission_pct"]/100; slip=request["slippage_pct"]/100
    registration={"spec_sha256":SPEC_HASH,"registered_at":datetime.now(timezone.utc).isoformat(),
                  "initial_capital":capital,"commission_pct":comm*100,"slippage_pct":slip*100,
                  "snapshot_id":snapshot["environment_snapshot_id"],"fingerprint":snapshot["input_fingerprint_sha256"],
                  "protected_before":protected,"registry_sha256":registry}
    reg_path=ROOT/"data/cross-sectional-momentum-registration.json"
    if reg_path.exists():
        prior=json.loads(reg_path.read_text(encoding="utf-8"))
        for key in ("initial_capital","commission_pct","slippage_pct","snapshot_id","fingerprint","registry_sha256"):
            assert registration[key]==prior[key],f"Frozen registration mismatch: {key}"
        if prior["spec_sha256"] == SPEC_HASH:
            registration=prior
        else:
            assert prior["spec_sha256"] == "9d2a25fac583bfc4f09a52ee3f91b2158277269370f3e21c0f71619e0064fb35"
            registration["previous_spec_sha256"]=prior["spec_sha256"]
            registration["correction"]="v2 reporting-only provenance extraction; all rules unchanged"
            write_json(reg_path.name,registration)
    else: write_json(reg_path.name,registration)
    print("Frozen registration verified; loading local snapshot",flush=True)
    datasets=[r for r in snapshot["market_manifest"]["datasets"] if r["ticker"] in ETF_RESEARCH_UNIVERSE]
    frames={r["ticker"]:_selected_frame(r) for r in datasets}
    schedule=rankings(frames); start=min(schedule); end=frames["SPY"].index[-1]
    rate=_load_rate_model(snapshot)
    calendar=frames["SPY"].index
    factors={t:rate.accrue(1,prev,t).interest for prev,t in zip(calendar,calendar[1:])}
    suites={}; stresses={}; gross={}
    for cash in ("CASH_ZERO","CASH_RISK_FREE"):
        cf=factors if cash=="CASH_RISK_FREE" else None
        suites[cash]={k:simulate(frames,schedule,k,start,end,capital,comm,slip,cf) for k in KINDS}
        stresses[cash]={}
        for label,cm,sm in (("2X_COMMISSION",2,1),("2X_SLIPPAGE",1,2),("2X_BOTH",2,2)):
            stresses[cash][label]={k:simulate(frames,schedule,k,start,end,capital,comm*cm,slip*sm,cf)["metrics"] for k in KINDS}
        gross[cash]={k:simulate(frames,schedule,k,start,end,capital,0,0,cf)["metrics"] for k in KINDS}
        print(f"Full history / cost stress completed: {cash}",flush=True)
    zero=suites["CASH_ZERO"]
    calendar_results={cash:window_table(s,[(str(y),f"{y}-01-01",f"{y}-12-31") for y in range(start.year,end.year+1)]) for cash,s in suites.items()}
    cycles={cash:window_table(s,MARKET_CYCLE_WINDOWS) for cash,s in suites.items()}
    crises={cash:window_table(s,CRISIS_EPISODES) for cash,s in suites.items()}
    folds=[]; test_start=start+pd.DateOffset(years=2); fold=0
    while test_start<=end:
        test_end=min(test_start+pd.DateOffset(months=6)-pd.Timedelta(days=1),end)
        fold+=1
        train_end=test_start-pd.Timedelta(days=1)
        for cash in suites:
            cf=factors if cash=="CASH_RISK_FREE" else None
            test={k:simulate(frames,schedule,k,test_start,test_end,capital,comm,slip,cf)["metrics"] for k in KINDS}
            for design in ("EXPANDING","ROLLING"):
                train_start=start if design=="EXPANDING" else test_start-pd.DateOffset(years=2)
                train={k:simulate(frames,schedule,k,train_start,train_end,capital,comm,slip,cf)["metrics"] for k in KINDS}
                folds.append({"fold":fold,"design":design,"cash_model":cash,
                              "train_start":str(train_start.date()),"train_end":str(train_end.date()),
                              "test_start":str(test_start.date()),"test_end":str(test_end.date()),
                              "partial_fold":test_end==end,"train":train,"test":test,
                              "vs_EW":differences(test["RS"],test["EW"]),"vs_SPY":differences(test["RS"],test["SPY"])})
        print(f"Walk-forward fold {fold} complete",flush=True)
        test_start+=pd.DateOffset(months=6)
    monthly=zero["RS"]["monthly_holdings"]
    prev=[]; rank_prev={}; stability=[]; streaks={}; completed=[]
    for row in monthly:
        top=row["selected"]; rank={s:i+1 for i,s in enumerate(row["ranking"])}
        for s in set(prev)-set(top): completed.append(streaks.pop(s))
        for s in top: streaks[s]=streaks.get(s,0)+1
        stability.append({**row,"new_entrants":sorted(set(top)-set(prev)),"exits":sorted(set(prev)-set(top)),
                          "rank_changes":{s:rank[s]-rank_prev[s] for s in rank.keys()&rank_prev.keys()},
                          "persistence":len(set(prev)&set(top))/3 if prev else None})
        prev=top; rank_prev=rank
    completed.extend(streaks.values())
    contributions=zero["RS"]["etf_contribution"]
    sorted_contrib=sorted(contributions.items(),key=lambda x:-x[1]); best=sorted_contrib[0][0]
    excluded=simulate(frames,schedule,"RS",start,end,capital,comm,slip,exclude=best)
    pos=sum(max(0,v) for v in contributions.values()); net=sum(contributions.values())
    weights={}
    year_pnl={}
    for year in range(start.year,end.year+1):
        ds=[d for d in zero["RS"]["daily"] if d["date"].startswith(str(year))]
        weights[str(year)]={s:float(np.mean([d["weights"].get(s,0) for d in ds])) for s in frames}
        year_pnl[str(year)]=sum(sum(d["contribution"].values()) for d in ds)
    uncertainty={b:paired_uncertainty(zero["RS"],zero[b]) for b in ("EW","SPY")}
    for b in uncertainty:
        ds=[r[f"vs_{b}"]["total_return"] for r in calendar_results["CASH_ZERO"]]
        uncertainty[b].update(mean_calendar_return_delta=float(np.mean(ds)),median_calendar_return_delta=float(np.median(ds)))
    def breadth(rows,b,metric): return sum(r[f"vs_{b}"][metric] is not None and r[f"vs_{b}"][metric]>0 for r in rows)/len(rows)
    test_rows=[r for r in folds if r["design"]=="EXPANDING" and r["cash_model"]=="CASH_ZERO"]
    full_delta={b:differences(zero["RS"]["metrics"],zero[b]["metrics"]) for b in ("EW","SPY","QQQ")}
    checks={}
    for b in ("EW","SPY"):
        checks[b]={"return_positive":full_delta[b]["total_return"]>0,"sharpe_positive":full_delta[b]["sharpe"]>0,
                   "mdd_within_5pp":full_delta[b]["mdd"]>=-.05,
                   "cycle_return_breadth":breadth(cycles["CASH_ZERO"],b,"total_return"),
                   "fold_return_breadth":breadth(test_rows,b,"total_return"),
                   "stress_positive":stresses["CASH_ZERO"]["2X_BOTH"]["RS"]["total_return"]>stresses["CASH_ZERO"]["2X_BOTH"][b]["total_return"]}
    promising=all(c["return_positive"] and c["sharpe_positive"] and c["mdd_within_5pp"] and c["cycle_return_breadth"]>.5 and c["fold_return_breadth"]>.5 and c["stress_positive"] for c in checks.values())
    strong=promising and all(full_delta[b]["mdd"]>0 and checks[b]["cycle_return_breadth"]>=2/3 and checks[b]["fold_return_breadth"]>=2/3 and uncertainty[b]["ci95"][0]>0 and excluded["metrics"]["total_return"]>zero[b]["metrics"]["total_return"] for b in ("EW","SPY"))
    grade="STRONG RETROSPECTIVE EVIDENCE" if strong else "PROMISING — FAMILY WORTH STUDYING" if promising else "NOT SUPPORTED"
    verify_spec(); assert_snapshot_inputs_unchanged(snapshot)
    after=immutable_fingerprints(); assert after==protected
    assert sha256_file(ROOT/"data/research-candidate-registry.json")==registry
    result={"study":"XSMOM_12_1_TOP3","title":"橫斷面動能基準研究","registration":registration,
            "evaluation_start":str(start.date()),"evaluation_end":str(end.date()),
            "data_coverage":[{**{k:r.get(k) for k in ("ticker","first_date","last_date","bars","ohlcv_sha256")},
                              **next({k:v[k] for k in ("provider","adjustment_mode")} for v in r["variants"] if v["provider"]=="yahoo" and v["adjustment_mode"]=="adjusted_for_splits" and v.get("ohlcv_sha256")==r["ohlcv_sha256"])} for r in datasets],
            "cash_models":{cash:{k:v["metrics"] for k,v in suite.items()} for cash,suite in suites.items()},
            "full_comparison":full_delta,"calendar_years":calendar_results,"fixed_cycles":cycles,"crises":crises,
            "cost_stress":stresses,"gross_before_cost":gross,
            "cost_attribution":{cash:{k:{"gross_return":gross[cash][k]["total_return"],"net_return":suites[cash][k]["metrics"]["total_return"],"cost_drag_pp":100*(gross[cash][k]["total_return"]-suites[cash][k]["metrics"]["total_return"])} for k in KINDS} for cash in suites},
            "cash_return_delta":{k:suites["CASH_RISK_FREE"][k]["metrics"]["total_return"]-zero[k]["metrics"]["total_return"] for k in KINDS},
            "ranking_stability":{"average_monthly_new_entrants":float(np.mean([len(r["new_entrants"]) for r in stability[1:]])),"mean_top3_persistence":float(np.mean([r["persistence"] for r in stability[1:]])),"median_holding_months":float(np.median(completed))},
            "concentration":{"etf_dollar_contribution":contributions,"top_etf":best,"top_etf_positive_profit_share":sorted_contrib[0][1]/pos,"top3_positive_profit_share":sum(v for _,v in sorted_contrib[:3])/pos,"top_etf_net_share":sorted_contrib[0][1]/net,"year_dollar_contribution":year_pnl,"top_year_positive_profit_share":max(year_pnl.values())/sum(max(0,v) for v in year_pnl.values()),"yearly_weights":weights,"mean_QQQ_XLK_weight":float(np.mean([d["weights"].get("QQQ",0)+d["weights"].get("XLK",0) for d in zero["RS"]["daily"]])),"excluded_best_etf_sensitivity":{"label":"POST_HOC_DESCRIPTIVE_SENSITIVITY_NOT_CANDIDATE","excluded":best,"metrics":excluded["metrics"]}},
            "uncertainty":uncertainty,"gate_checks":checks,"grade":grade,"next_family":"NONE" if grade=="NOT SUPPORTED" else "CROSS_SECTIONAL_MOMENTUM",
            "policy":"OPEN_ONLY_POLICY_INDEPENDENT","candidate_created":False,
            "invariance":{"before":protected,"after":after,"registry_sha256":registry,"differences":0},
            "runtime_seconds":time.monotonic()-begun,
            "limitations":["Retrospective walk-forward, not true OOS","Fixed modern ETF list, overlapping broad and sector holdings; not independent assets","Yahoo split-adjusted price data; dividend cash flows omitted","DGS3MO is a yield proxy, not investable fund total return; no vintage revision guarantee","Partial calendar years and last WF fold explicitly retained; short-fold CAGR not decision criterion","First eligibility requires 253 observations to address t-252; XLRE never backfilled","Whole-share cost reserve and cost-induced sizing/path differences included"]}
    old=json.loads((ROOT/"data/cross-sectional-momentum-benchmark.v1.json").read_text(encoding="utf-8"))
    compared=("cash_models","full_comparison","calendar_years","fixed_cycles","crises","cost_stress","gross_before_cost","cash_return_delta","ranking_stability","concentration","uncertainty","gate_checks","grade","next_family")
    assert all(result[k]==old[k] for k in compared),"Reporting-only correction changed numeric results"
    result["v1_numeric_result_differences"]=0
    write_json("cross-sectional-momentum-benchmark.json",result)
    write_json("cross-sectional-momentum-monthly-holdings.json",{"spec_sha256":SPEC_HASH,"snapshot_id":registration["snapshot_id"],"ranking_timeline":stability,"runs":{cash:{k:{"monthly_holdings":v["monthly_holdings"],"daily":v["daily"],"executions":v["executions"]} for k,v in suite.items()} for cash,suite in suites.items()}})
    write_json("cross-sectional-momentum-walk-forward.json",{"name":"Retrospective Walk-Forward Robustness Validation","spec_sha256":SPEC_HASH,"folds":folds,"design_note":"Fixed parameters; identical test windows in expanding/rolling; not independent replications"})
    from research.xsmom_report import render
    (ROOT/"reports/cross-sectional-momentum-benchmark.md").write_text(render(result,folds,stability),encoding="utf-8")
    print(json.dumps({"grade":grade,"next_family":result["next_family"],"metrics":result["cash_models"],"checks":checks,"runtime":result["runtime_seconds"]},ensure_ascii=False),flush=True)


if __name__=="__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    main()
