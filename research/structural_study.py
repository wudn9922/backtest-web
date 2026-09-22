"""Frozen structural candidates, cross-sectional tests and matched lifecycles.

No optimizer, production registration, network, database or file writes.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
import math

import numpy as np

from research.modules import FULL, Modules
from research.simulation import Prepared, simulate
from research.analysis import drawdown_episodes, distribution, group_executions
from research.baseline import digest, normalize_timestamps

POLICIES = ("conservative", "ohlc_heuristic", "favorable")
PERIODS = {"FULL": (date(2021,9,1),date(2026,9,1)),
           "A": (date(2021,9,1),date(2023,12,31)),
           "B": (date(2024,1,1),date(2026,9,1))}


@dataclass(frozen=True)
class Candidate:
    name: str
    modules: Modules
    first_tp_fraction: float
    description: str

    def run(self, prepared, **kwargs):
        return simulate(prepared, self.modules, first_tp_fraction=self.first_tp_fraction, **kwargs)

    def as_dict(self):
        return {"name":self.name,"modules":self.modules.as_dict(),
                "first_tp_current_quantity_fraction":self.first_tp_fraction if self.modules.first_tp_partial else 0,
                "description":self.description}


CANDIDATES = {
    "A": Candidate("ADVANCED_V2_FULL", FULL, .5, "正式 v2：首次停利 50% current qty；Protective 與 Bias/ATR 保留。"),
    "B": Candidate("SIGNAL_ONLY_FIRST_TP", replace(FULL,first_tp_partial=False), .5, "首次停利僅切換狀態、不立即賣出；Protective 與 Bias/ATR 保留。"),
    "C": Candidate("SIGNAL_PROTECTIVE_NO_PROFIT_PARTIALS", replace(FULL,first_tp_partial=False,bias=False,atr=False), .5, "首次停利僅切換狀態；保留 Protective；關閉兩種 Extreme 停利。"),
    "D": Candidate("FIRST_TP_25_PERCENT", FULL, .25, "唯一敏感度檢查：首次停利賣 25% current qty，其餘同 A。"),
    "E": Candidate("ADVANCED_MINUS_EXTREME", replace(FULL,bias=False,atr=False), .5, "保留首次 50% 減碼與 Protective；關閉兩種 Extreme 停利。"),
}
NO_PROTECTIVE = replace(CANDIDATES["C"],name="FIXED_HORIZON_NO_PROFIT_PARTIALS_NO_PROTECTIVE",
                        modules=replace(CANDIDATES["C"].modules,protective=False))
CRITERIA = {
    "ROBUST":"Full-period median return and Sharpe delta > 0 under all three policies; at least ceil(2N/3) symbols improve BOTH metrics under ALL three policies; median return and Sharpe delta > 0 in EACH subperiod under EACH policy.",
    "POLICY-SENSITIVE":"Median return or Sharpe delta changes strict sign across policies in any period, or full-period joint-improvement symbol count differs by at least ceil(N/3) across policies.",
    "MIXED":"All other cases; direction/magnitude may depend on symbols or subperiods even if all-policy median return is positive.",
    "Strong candidate":"ROBUST; all policies have full-period median MDD deterioration no worse than 5 percentage points; coverage >= 8 symbols.",
    "Promising but needs validation":"Not Strong; full-period median return and Sharpe improve in >= 2 policies and >= half of symbols improve return under every policy.",
    "Reject":"Full-period median return and Sharpe are negative under all three policies.",
    "No clear improvement":"Otherwise (also the unchanged A benchmark).",
    "epsilon":1e-9,
    "caution":"Descriptive, predeclared evidence screens, not statistical significance, optimization, independent samples or production approval. MDD delta > 0 = improvement."
}


def _delta(a,b):
    return None if a is None or b is None else a-b


def portfolio_row(symbol,period,policy,key,prepared,result,full):
    s,f=result["summary"],full["summary"]
    e=result["exposure"]; fe=full["exposure"]
    return {"symbol":symbol,"period":period,"policy":policy,"candidate":key,
            "start":prepared.dates[0],"end":prepared.dates[-1],"bars":len(prepared.rows),
            "summary":s,"exposure":e,
            "delta_vs_full":{"return_pp":100*(s["total_return"]-f["total_return"]),
                "mdd_pp":100*(s["max_drawdown"]-f["max_drawdown"]),"sharpe":_delta(s["sharpe_ratio"],f["sharpe_ratio"]),
                "exposure_pp":e["average_close_capital_exposure_pct"]-fe["average_close_capital_exposure_pct"],
                "turnover":e["two_sided_turnover"]-fe["two_sided_turnover"]},
            "drawdown_episodes":drawdown_episodes(result["equity"])[:3],
            "execution_sha256":digest(normalize_timestamps(result["executions"])),
            "equity_sha256":digest([r["strategy"] for r in result["equity"]]),
            "positions_sha256":digest(normalize_timestamps(result["positions"]))}


def breadth(rows):
    output=[]
    for period in PERIODS:
        for policy in POLICIES:
            for key in "BCDE":
                rs=[r for r in rows if (r["period"],r["policy"],r["candidate"])==(period,policy,key)]
                ds=[r["delta_vs_full"] for r in rs]
                def count(metric,sign):
                    return sum(d[metric] is not None and (d[metric]>1e-9 if sign>0 else d[metric]<-1e-9 if sign<0 else abs(d[metric])<=1e-9) for d in ds)
                output.append({"period":period,"policy":policy,"candidate":key,"symbols":len(rs),
                    "return_better":count("return_pp",1),"return_worse":count("return_pp",-1),"return_tied":count("return_pp",0),
                    "sharpe_better":count("sharpe",1),"sharpe_worse":count("sharpe",-1),"sharpe_tied":count("sharpe",0),
                    "mdd_better":count("mdd_pp",1),"mdd_worse":count("mdd_pp",-1),"mdd_tied":count("mdd_pp",0),
                    "joint_return_sharpe_better":sum(d["return_pp"]>1e-9 and d["sharpe"] is not None and d["sharpe"]>1e-9 for d in ds),
                    "distributions":{m:distribution([d[m] for d in ds]) for m in ("return_pp","mdd_pp","sharpe","exposure_pp","turnover")},
                    "return_better_symbols":[r["symbol"] for r in rs if r["delta_vs_full"]["return_pp"]>1e-9],
                    "return_worse_symbols":[r["symbol"] for r in rs if r["delta_vs_full"]["return_pp"]<-1e-9]})
    return output


def robustness(rows,breadth_rows):
    out=[]
    symbols=sorted({r["symbol"] for r in rows})
    for key in "ABCDE":
        if key=="A":
            out.append({"candidate":key,"label":"REFERENCE","category":"No clear improvement","reason":"Unchanged benchmark"})
            continue
        get=lambda period,policy:next(r for r in breadth_rows if (r["candidate"],r["period"],r["policy"])==(key,period,policy))
        all_policy=[]; all_period=[]
        for symbol in symbols:
            selected=[r for r in rows if r["symbol"]==symbol and r["candidate"]==key]
            joint=lambda r:r["delta_vs_full"]["return_pp"]>1e-9 and (r["delta_vs_full"]["sharpe"] or 0)>1e-9
            if all(joint(r) for r in selected if r["period"]=="FULL"):
                all_policy.append(symbol)
            if all(joint(r) for r in selected if r["period"] in ("A","B")):
                all_period.append(symbol)
        med=lambda per,pol,m:get(per,pol)["distributions"][m]["median"]
        positive=lambda per:all(med(per,p,m) is not None and med(per,p,m)>1e-9 for p in POLICIES for m in ("return_pp","sharpe"))
        robust=positive("FULL") and len(all_policy)>=math.ceil(2*len(symbols)/3) and positive("A") and positive("B")
        sign_change=any(min(med(per,p,m) or 0 for p in POLICIES)<-1e-9 and max(med(per,p,m) or 0 for p in POLICIES)>1e-9
                        for per in PERIODS for m in ("return_pp","sharpe"))
        counts=[get("FULL",p)["joint_return_sharpe_better"] for p in POLICIES]
        sensitive=sign_change or max(counts)-min(counts)>=math.ceil(len(symbols)/3)
        label="ROBUST" if robust else "POLICY-SENSITIVE" if sensitive else "MIXED"
        positive_policy=sum(all((med("FULL",p,m) or 0)>0 for m in ("return_pp","sharpe")) for p in POLICIES)
        if robust and len(symbols)>=8 and all(med("FULL",p,"mdd_pp")>=-5 for p in POLICIES):
            category="Strong candidate"
        elif positive_policy>=2 and all(get("FULL",p)["return_better"]>=math.ceil(len(symbols)/2) for p in POLICIES):
            category="Promising but needs validation"
        elif all((med("FULL",p,m) or 0)<0 for p in POLICIES for m in ("return_pp","sharpe")):
            category="Reject"
        else:
            category="No clear improvement"
        out.append({"candidate":key,"label":label,"category":category,
            "all_three_policies_joint_improved_symbols":all_policy,
            "both_subperiods_all_policies_joint_improved_symbols":all_period,
            "subperiod_medians_joint_positive":{per:positive(per) for per in PERIODS},
            "sign_changes_across_policy":sign_change,
            "maximum_joint_breadth_policy_spread":max(counts)-min(counts),
            "median_mdd_delta_by_policy":{p:med("FULL",p,"mdd_pp") for p in POLICIES},
            "median_exposure_delta_by_policy":{p:med("FULL",p,"exposure_pp") for p in POLICIES},
            "median_turnover_delta_by_policy":{p:med("FULL",p,"turnover") for p in POLICIES},
            "complexity":"Two extreme-state/partial-sale modules removed" if key in "CE" else "Same downstream modules; immediate-sale branch disabled" if key=="B" else "Same modules, one frozen 25% checkpoint"})
    return out


def gradient(rows):
    out=[]
    for period in PERIODS:
        for policy in POLICIES:
            symbols=sorted({r["symbol"] for r in rows if r["period"]==period})
            ret=[]; exp=[]
            for s in symbols:
                v={r["candidate"]:r for r in rows if (r["symbol"],r["period"],r["policy"])==(s,period,policy)}
                if v["A"]["summary"]["total_return"]-1e-9<=v["D"]["summary"]["total_return"]<=v["B"]["summary"]["total_return"]+1e-9:
                    ret.append(s)
                if v["A"]["exposure"]["average_close_capital_exposure_pct"]-1e-9<=v["D"]["exposure"]["average_close_capital_exposure_pct"]<=v["B"]["exposure"]["average_close_capital_exposure_pct"]+1e-9:
                    exp.append(s)
            out.append({"period":period,"policy":policy,"symbols":len(symbols),"return_A_le_D_le_B":ret,"exposure_A_le_D_le_B":exp})
    return out


def short_position(p):
    return {k:p[k] for k in ("net_pnl","gross_pnl","fees","return_pct","final_exit_date","holding_days",
                             "exit_final_close_reason","maximum_favorable_excursion","maximum_adverse_excursion")}


def matched_c_row(symbol,policy,anchor,full,cf):
    a,b=full["positions"][0],cf["positions"][0]
    delta=b["net_pnl"]-a["net_pnl"]
    return {"symbol":symbol,"policy":policy,"position_id":anchor["position_id"],
            "entry_date":anchor["entry_date"],"p0":anchor["entry_price"],"q0":anchor["q0"],
            "full":short_position(a),"candidate_c":short_position(b),"delta_pnl":delta,
            "delta_return_on_entry_notional_pp":100*delta/(anchor["entry_price"]*anchor["q0"]),
            "holding_days_delta":b["holding_days"]-a["holding_days"],
            "extra_q0_sessions":math.fsum(e["quantity"]/anchor["q0"] for e in cf["equity"])-math.fsum(e["quantity"]/anchor["q0"] for e in full["equity"]),
            "full_execution_sha256":digest(normalize_timestamps(full["executions"])),
            "candidate_c_execution_sha256":digest(normalize_timestamps(cf["executions"]))}


def match_summary(rows):
    def summarise(rs):
        ds=[r["delta_pnl"] for r in rs]
        return {"anchors":len(rs),"delta_pnl":distribution(ds),"sum_delta_pnl":math.fsum(ds),
            "changed":sum(abs(x)>1e-7 for x in ds),"benefited":sum(x>1e-7 for x in ds),"harmed":sum(x<-1e-7 for x in ds),
            "winner_delta":math.fsum(r["delta_pnl"] for r in rs if r["full"]["net_pnl"]>0),
            "loser_delta":math.fsum(r["delta_pnl"] for r in rs if r["full"]["net_pnl"]<=0),
            "delta_return_on_entry_notional_pp":distribution([r["delta_return_on_entry_notional_pp"] for r in rs]),
            "extra_q0_sessions":math.fsum(r["extra_q0_sessions"] for r in rs),
            "top_benefited":sorted([r for r in rs if r["delta_pnl"]>1e-7],key=lambda r:r["delta_pnl"],reverse=True)[:10],
            "top_harmed":sorted([r for r in rs if r["delta_pnl"]<-1e-7],key=lambda r:r["delta_pnl"])[:10]}
    return {p:{"pooled":summarise([r for r in rows if r["policy"]==p]),
               "by_symbol":{s:summarise([r for r in rows if r["policy"]==p and r["symbol"]==s])
                            for s in sorted({r["symbol"] for r in rows})}} for p in POLICIES}


def horizon_risk(sim,anchor,commission):
    # Remove the simulator's ample funding buffer. A one-position account is
    # normalized to the anchored entry execution notional, includes all fees.
    notional=anchor["entry_price"]*anchor["q0"]
    capital=2*notional*(1+commission/100)
    pnl=np.array([0.]+[r["strategy"]-capital for r in sim["equity"]])
    values=notional+pnl
    dd=values/np.maximum.accumulate(values)-1
    return {"worst_marked_pnl":float(pnl.min()),"best_marked_pnl":float(pnl.max()),
            "position_account_mdd":float(dd.min()),"terminal_pnl":sim["positions"][0]["net_pnl"]}


def fixed_row(symbol,policy,anchor,on,off,commission):
    a,b=on["positions"][0],off["positions"][0]
    ra,rb=horizon_risk(on,anchor,commission),horizon_risk(off,anchor,commission)
    return {"symbol":symbol,"policy":policy,"position_id":anchor["position_id"],"entry_date":anchor["entry_date"],
            "p0":anchor["entry_price"],"q0":anchor["q0"],"horizon":on["horizon"],
            "protective_on":short_position(a),"protective_off":short_position(b),
            "risk_on":ra,"risk_off":rb,"delta_on_minus_off":a["net_pnl"]-b["net_pnl"],
            "delta_return_on_entry_notional_pp":100*(a["net_pnl"]-b["net_pnl"])/(anchor["entry_price"]*anchor["q0"]),
            "worst_marked_loss_reduction":ra["worst_marked_pnl"]-rb["worst_marked_pnl"],
            "mdd_improvement_pp":100*(ra["position_account_mdd"]-rb["position_account_mdd"]),
            "on_execution_sha256":digest(normalize_timestamps(on["executions"])),
            "off_execution_sha256":digest(normalize_timestamps(off["executions"]))}


def fixed_summary(rows):
    def summarise(rs):
        complete=[r for r in rs if r["horizon"]["complete_horizon_available"]]
        changed=[r for r in complete if r["on_execution_sha256"]!=r["off_execution_sha256"]]
        losers=[r for r in complete if r["protective_off"]["net_pnl"]<0]
        winners=[r for r in complete if r["protective_off"]["net_pnl"]>0]
        return {"all_anchors":len(rs),"complete_horizon_anchors":len(complete),"endpoint_censored_excluded":len(rs)-len(complete),
            "changed_lifecycles":len(changed),"benefited":sum(r["delta_on_minus_off"]>1e-7 for r in complete),
            "harmed":sum(r["delta_on_minus_off"]<-1e-7 for r in complete),
            "sum_delta_on_minus_off":math.fsum(r["delta_on_minus_off"] for r in complete),
            "delta_on_minus_off":distribution([r["delta_on_minus_off"] for r in complete]),
            "changed_delta":distribution([r["delta_on_minus_off"] for r in changed]),
            "normalized_return_delta_pp":distribution([r["delta_return_on_entry_notional_pp"] for r in complete]),
            "off_losing_anchors":len(losers),"loss_avoided_vs_off_losers":math.fsum(r["delta_on_minus_off"] for r in losers),
            "off_winning_anchors":len(winners),"upside_sacrificed_vs_off_winners":-math.fsum(r["delta_on_minus_off"] for r in winners),
            "sum_worst_marked_loss_reduction":math.fsum(r["worst_marked_loss_reduction"] for r in complete),
            "mdd_improvement_pp":distribution([r["mdd_improvement_pp"] for r in complete]),
            "off_horizon_liquidations":sum(r["protective_off"]["exit_final_close_reason"]=="RESEARCH_40_SESSION_HORIZON" for r in complete),
            "on_horizon_liquidations":sum(r["protective_on"]["exit_final_close_reason"]=="RESEARCH_40_SESSION_HORIZON" for r in complete)}
    return {p:{"pooled":summarise([r for r in rows if r["policy"]==p]),
               "by_symbol":{s:summarise([r for r in rows if r["policy"]==p and r["symbol"]==s])
                            for s in sorted({r["symbol"] for r in rows})}} for p in POLICIES}


def run_study(frozen,frames,progress=lambda s:None):
    base=frozen["advanced"]["request_object"]
    rows=[]; matrices={}; unavailable=[]; calendar={}
    common_start=max(PERIODS["FULL"][0],max(min(t.date() for t in f.index if t.date()>=PERIODS["FULL"][0]) for f in frames.values()))
    common_end=min(PERIODS["FULL"][1],min(f.index[-1].date() for f in frames.values()))
    for symbol,frame in frames.items():
        matrices[symbol]={}
        for period,(start,end) in PERIODS.items():
            left,right=max(start,common_start),min(end,common_end)
            request=base.model_copy(update={"ticker":symbol,"start_date":left,"end_date":right})
            try:
                p=Prepared(request,frame)
                if not p.rows or left>right:
                    raise ValueError("No usable period")
            except ValueError as exc:
                unavailable.append({"symbol":symbol,"period":period,"error":str(exc)})
                continue
            calendar.setdefault(period,{})[symbol]=p.dates
            for policy in POLICIES:
                sims={k:c.run(p,policy=policy) for k,c in CANDIDATES.items()}
                rows.extend(portfolio_row(symbol,period,policy,k,p,sim,sims["A"]) for k,sim in sims.items())
                if period=="FULL":
                    matrices[symbol][policy]=(p,sims)
            progress(f"Portfolios complete: {symbol} / {period}")
    # Date holes are not silently filled, skipped or interpreted as holidays.
    calendar_checks={per:{"identical_session_dates":all(ds==next(iter(values.values())) for ds in values.values()),
                         "session_count_by_symbol":{s:len(ds) for s,ds in values.items()},
                         "date_set_differences":{s:sorted(set(ds)^set(next(iter(values.values())))) for s,ds in values.items()}}
                     for per,values in calendar.items()}
    if any(not c["identical_session_dates"] for c in calendar_checks.values()):
        raise ValueError("Inconsistent session coverage: inspect before cross-symbol comparison")
    matched=[]; fixed=[]
    for symbol,results in matrices.items():
        if "conservative" not in results:
            continue
        prepared,conservative=results["conservative"]
        anchors=conservative["A"]["positions"]
        expected=group_executions(conservative["A"]["executions"])
        for policy in POLICIES:
            for anchor,ex in zip(anchors,expected):
                full=CANDIDATES["A"].run(prepared,policy=policy,anchor=anchor)
                if policy=="conservative":
                    assert normalize_timestamps(full["executions"])==normalize_timestamps(ex)
                    assert full["positions"][0]["net_pnl"]==anchor["net_pnl"]
                cf=CANDIDATES["C"].run(prepared,policy=policy,anchor=anchor)
                matched.append(matched_c_row(symbol,policy,anchor,full,cf))
                on=CANDIDATES["C"].run(prepared,policy=policy,anchor=anchor,horizon_sessions=40)
                off=NO_PROTECTIVE.run(prepared,policy=policy,anchor=anchor,horizon_sessions=40)
                fixed.append(fixed_row(symbol,policy,anchor,on,off,base.commission_pct))
            progress(f"Matched lifecycles / 40-session study: {symbol} / {policy} / {len(anchors)} entries")
    ms=match_summary(matched)
    # Daily inventory tracks for global top 10 helped and harmed dollar-matched
    # entries; no synthetic dollar aggregation is represented as a portfolio.
    top=ms["conservative"]["pooled"]["top_benefited"]+ms["conservative"]["pooled"]["top_harmed"]
    trajectories=[]
    for r in top:
        prepared,sims=matrices[r["symbol"]]["conservative"]
        anchor=next(p for p in sims["A"]["positions"] if p["position_id"]==r["position_id"])
        full=CANDIDATES["A"].run(prepared,anchor=anchor)
        cf=CANDIDATES["C"].run(prepared,anchor=anchor)
        maps=[{e["timestamp"][:10]:e["quantity"] for e in sim["equity"]} for sim in (full,cf)]
        daily=[]
        for d in sorted(set(maps[0])|set(maps[1])):
            bar=prepared.rows[prepared.date_index[d]][0]
            daily.append({"date":d,"close":bar.close,"full_qty":maps[0].get(d,0),"candidate_c_qty":maps[1].get(d,0)})
        trajectories.append({"symbol":r["symbol"],"position_id":r["position_id"],"q0":r["q0"],"delta_pnl":r["delta_pnl"],
                             "daily":daily,"full_executions":full["executions"],"candidate_c_executions":cf["executions"]})
    br=breadth(rows)
    return {"candidate_definitions":{k:c.as_dict() for k,c in CANDIDATES.items()},"criteria":CRITERIA,
        "common_start":str(common_start),"common_end":str(common_end),"calendar_checks":calendar_checks,
        "unavailable_periods":unavailable,"portfolio":rows,"breadth":br,
        "breadth_excluding_nvda":breadth([r for r in rows if r["symbol"]!="NVDA"]),
        "robustness":robustness(rows,br),"exposure_gradient":gradient(rows),
        "matched_candidate_c":{"anchor_design":"Each symbol's Full Conservative entries, frozen timestamp/P0/Q0, replayed independently under all 3 policies; one lifecycle, no re-entry; overlapping counterfactuals are not a portfolio.",
            "rows":matched,"summary":ms,"top_position_quantity_trajectories":trajectories},
        "protective_fixed_horizon":{"sessions_after_entry":40,"control":NO_PROTECTIVE.as_dict(),
            "design":"Entry day is day 0; close after 40 subsequent trading sessions is the common horizon. Each side exits on its first natural exit or at the horizon close, with normal slippage/commission. Exit proceeds remain cash without re-entry. Entries lacking all 40 subsequent sessions are reported separately and EXCLUDED from headline estimates, even if they exited early. Without Protective, pre-signal risk/validations stay on; after signal MA half-stop is not revived. This is NOT portfolio performance.",
            "rows":fixed,"summary":fixed_summary(fixed)}}
