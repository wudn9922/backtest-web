"""Ablation statistics; all monetary attribution is explicitly labelled."""
from __future__ import annotations

from collections import defaultdict
import math
import numpy as np
import pandas as pd

from research.baseline import digest, normalize_timestamps
from research.modules import VARIANTS, BRIDGE
from research.simulation import simulate

HORIZONS = (5, 10, 20, 40)


def distribution(values):
    xs = [float(x) for x in values if x is not None]
    return {"n": len(xs), "mean": float(np.mean(xs)) if xs else None,
            "median": float(np.median(xs)) if xs else None,
            "positive_pct": sum(x > 0 for x in xs) / len(xs) * 100 if xs else None}


def forward_returns(prepared, timestamp, price):
    index = prepared.date_index[timestamp[:10]]
    return {str(n): (prepared.rows[index+n][0].close / price - 1) if index+n < len(prepared.rows) else None for n in HORIZONS}


def drawdown_episodes(equity):
    peak = equity[0]["strategy"]; peak_date = equity[0]["timestamp"][:10]
    current = None; episodes = []
    for row in equity[1:]:
        value, day = row["strategy"], row["timestamp"][:10]
        if value >= peak:
            if current:
                current["recovery"] = day; episodes.append(current); current = None
            peak, peak_date = value, day
        else:
            dd = value / peak - 1
            if current is None:
                current = {"start": peak_date, "trough": day, "depth": dd, "recovery": None}
            if dd < current["depth"]:
                current.update(trough=day, depth=dd)
    if current:
        episodes.append(current)
    return sorted(episodes, key=lambda x: x["depth"])


def summarize_simulation(name, modules, result, full_summary):
    summary = result["summary"]
    deltas = {k: (v-full_summary[k]) if isinstance(v, (int, float)) and isinstance(full_summary.get(k), (int, float)) else None for k, v in summary.items()}
    return {"name": name, "modules": modules.as_dict() if modules else None,
            "summary": summary, "delta_vs_full": deltas, "exposure": result["exposure"],
            "drawdown_episodes": drawdown_episodes(result["equity"])[:5],
            "execution_sha256": digest(normalize_timestamps(result["executions"])),
            "equity_sha256": digest([r["strategy"] for r in result["equity"]])}


def group_executions(executions):
    groups = []
    for e in executions:
        if e["side"] == "BUY":
            groups.append([])
        groups[-1].append(e)
    return groups


def first_difference(a, b):
    for x, y in zip(a, b):
        if normalize_timestamps(x) != normalize_timestamps(y):
            return min(x["timestamp"][:10], y["timestamp"][:10])
    if len(a) != len(b):
        return (a if len(a)>len(b) else b)[min(len(a),len(b))]["timestamp"][:10]
    return None


def matched_analysis(prepared, positions, expected_groups):
    rows = []; cache = {}
    for anchor, expected in zip(positions, expected_groups):
        full = simulate(prepared, anchor=anchor)
        assert normalize_timestamps(full["executions"]) == normalize_timestamps(expected)
        assert full["positions"][0]["net_pnl"] == anchor["net_pnl"]
        final_price = full["executions"][-1]["price"]
        item = {"position_id": anchor["position_id"], "entry_date": anchor["entry_date"],
                "entry_price": anchor["entry_price"], "q0": anchor["initial_shares"],
                "full": anchor, "forward_from_original_exit": forward_returns(prepared, anchor["final_exit_date"], final_price),
                "counterfactuals": {}}
        cache[anchor["position_id"]] = {"ADVANCED_FULL": full}
        for name, modules in VARIANTS.items():
            if name == "ADVANCED_FULL":
                continue
            cf = simulate(prepared, modules, anchor=anchor); p = cf["positions"][0]
            cache[anchor["position_id"]][name] = cf
            item["counterfactuals"][name] = {"net_pnl": p["net_pnl"], "gross_pnl": p["gross_pnl"],
                "fees": p["fees"], "delta_pnl_without_minus_full": p["net_pnl"]-anchor["net_pnl"],
                "exit_date": p["final_exit_date"], "exit_reason": p["exit_final_close_reason"],
                "holding_days": p["holding_days"], "holding_days_delta": p["holding_days"]-anchor["holding_days"],
                "mfe": p["maximum_favorable_excursion"], "mae": p["maximum_adverse_excursion"],
                "first_execution_difference_date": first_difference(full["executions"], cf["executions"]),
                "executions_sha256": digest(normalize_timestamps(cf["executions"]))}
        rows.append(item)
    summaries = {}
    for name in VARIANTS:
        if name == "ADVANCED_FULL":
            continue
        changed = [r for r in rows if r["counterfactuals"][name]["first_execution_difference_date"] is not None]
        deltas = [r["counterfactuals"][name]["delta_pnl_without_minus_full"] for r in rows]
        summaries[name] = {"anchors": len(rows), "changed_anchors": len(changed),
            "delta_pnl_without_minus_full": distribution(deltas), "sum_delta_pnl": math.fsum(deltas),
            "changed_only_delta_pnl": distribution([r["counterfactuals"][name]["delta_pnl_without_minus_full"] for r in changed]),
            "changed_cf_terminal_closes": sum(r["counterfactuals"][name]["exit_reason"] == "END_OF_BACKTEST" for r in changed),
            "mean_holding_days_delta": float(np.mean([r["counterfactuals"][name]["holding_days_delta"] for r in rows])),
            "top_harm_from_rule": [r["position_id"] for r in sorted(rows, key=lambda r:r["counterfactuals"][name]["delta_pnl_without_minus_full"], reverse=True)[:10]],
            "top_benefit_from_rule": [r["position_id"] for r in sorted(rows, key=lambda r:r["counterfactuals"][name]["delta_pnl_without_minus_full"])[:10]]}
    return {"rows": rows, "summary": summaries}, cache


def event_category(e):
    if e["event_type"] == "EXTREME_TP":
        return {"BIAS_EXTREME":"BIAS_EXTREME_TP", "ATR_EXTREME":"ATR_EXTREME_TP", "BIAS+ATR_EXTREME":"BIAS_AND_ATR_EXTREME_TP"}[e["reason"]]
    if e["event_type"] == "FIRST_TP":
        return "FIRST_TP"
    return e["reason"]


def event_attribution(prepared, positions, groups):
    by_type = defaultdict(list)
    for pos, executions in zip(positions, groups):
        q0=pos["initial_shares"]; buy_fee=executions[0]["commission"]
        for e in executions[1:]:
            kind=event_category(e)
            effect=(e["price"]-pos["entry_price"])*e["quantity"]-e["commission"]-buy_fee*e["quantity"]/q0
            bar=prepared.rows[prepared.date_index[e["timestamp"][:10]]][0]
            by_type[kind].append({"position_id":pos["position_id"], "date":e["timestamp"], "quantity":e["quantity"],
                "quantity_before":e["quantity"]+e["position_remaining"], "execution_price":e["price"],
                "booked_net_pnl_allocated_buy_fee":effect,
                "forward_from_execution":forward_returns(prepared,e["timestamp"],e["price"]),
                "underlying_forward_from_day_close":forward_returns(prepared,e["timestamp"],bar.close)})
    return {kind:{"event_count":len(rows),"positions_affected":len({r["position_id"] for r in rows}),
        "booked_net_pnl":distribution([r["booked_net_pnl_allocated_buy_fee"] for r in rows]),
        "total_booked_net_pnl":math.fsum(r["booked_net_pnl_allocated_buy_fee"] for r in rows),
        "forward_from_execution":{str(n):distribution([r["forward_from_execution"][str(n)] for r in rows]) for n in HORIZONS},
        "underlying_forward_from_day_close":{str(n):distribution([r["underlying_forward_from_day_close"][str(n)] for r in rows]) for n in HORIZONS},
        "rows":rows} for kind,rows in by_type.items()}


FIRST_RULE_REMOVAL = {
    "VOLUME_CONFIRMATION_FAIL":"ADVANCED_MINUS_VOLUME", "DAY2_CLOSE_CONFIRMATION_FAIL":"ADVANCED_MINUS_DAY2",
    "MA_BREAK_HALF_EXIT":"ADVANCED_MINUS_MA_BREAK", "BREAK_DAY_LOW_BROKEN":"ADVANCED_MINUS_MA_BREAK",
    "FIRST_TAKE_PROFIT":"ADVANCED_MINUS_FIRST_TP_FAMILY", "PROTECTIVE_STOP":"ADVANCED_MINUS_PROTECTIVE_STOP",
    "BIAS_EXTREME":"ADVANCED_MINUS_BIAS_EXTREME", "ATR_EXTREME":"ADVANCED_MINUS_ATR_EXTREME",
    "BIAS+ATR_EXTREME":"ADVANCED_MINUS_ALL_EXTREME_TP"}


def simple_episode_analysis(prepared, simple_positions, advanced, *, winners):
    candidates=sorted([p for p in simple_positions if (p["net_pnl"]>0 if winners else p["net_pnl"]<0)], key=lambda p:p["net_pnl"], reverse=winners)
    selected=candidates[:20 if winners else 10];rows=[]
    for anchor in selected:
        exact_simple=simulate(prepared,anchor=anchor,simple=True)["positions"][0]
        assert exact_simple["net_pnl"] == anchor["net_pnl"]
        full=simulate(prepared,anchor=anchor);pos=full["positions"][0]
        first_reduction=full["executions"][1]
        reduction_bar = prepared.rows[prepared.date_index[first_reduction["timestamp"][:10]]][0]
        name=FIRST_RULE_REMOVAL.get(first_reduction["reason"])
        variants={key:simulate(prepared,module,anchor=anchor)["positions"][0] for key,module in VARIANTS.items() if key!="ADVANCED_FULL"}
        start,end=anchor["entry_date"][:10],anchor["final_exit_date"][:10]
        overlapping=[p["position_id"] for p in advanced["positions"] if p["entry_date"][:10]<=end and p["final_exit_date"][:10]>=start]
        i,j=prepared.date_index[start],prepared.date_index[end]
        prior_equity=prepared.request.initial_capital if i==0 else advanced["equity"][i-1]["strategy"]
        rows.append({"simple_position_id":anchor["position_id"], "entry_date":anchor["entry_date"],
            "simple_exit_date":anchor["final_exit_date"], "p0":anchor["entry_price"], "q0":anchor["initial_shares"],
            "simple_pnl":anchor["net_pnl"], "advanced_same_entry_pnl":pos["net_pnl"],
            "advanced_same_entry_exit":pos["final_exit_date"], "advanced_minus_simple_pnl":pos["net_pnl"]-anchor["net_pnl"],
            "first_exposure_reduction":first_reduction["reason"], "first_reduction_date":first_reduction["timestamp"],
            "first_reduction_ohlc": {k:getattr(reduction_bar,k) for k in ["open","high","low","close"]},
            "first_reduction_event_order": [e["event"] for e in full["events"] if e["timestamp"][:10] == first_reduction["timestamp"][:10]],
            "removal_variant":name,"potential_pnl_without_first_rule":variants[name]["net_pnl"] if name else None,
            "potential_exit_without_first_rule":variants[name]["final_exit_date"] if name else None,
            "actual_advanced_overlapping_position_ids":overlapping,
            "actual_advanced_equity_change_in_simple_calendar_interval":advanced["equity"][j]["strategy"]-prior_equity,
            "counterfactual_pnl_by_rule":{key:p["net_pnl"] for key,p in variants.items()}})
    aggregates={}
    for n in ([10,20] if winners else [10]):
        sample=rows[:n]
        aggregates[str(n)]={"requested":n,"available":len(sample),"simple_pnl_sum":math.fsum(r["simple_pnl"] for r in sample),
            "advanced_same_entry_pnl_sum":math.fsum(r["advanced_same_entry_pnl"] for r in sample),
            "advanced_minus_simple_sum":math.fsum(r["advanced_minus_simple_pnl"] for r in sample)}
    return {"matching_method":"Exact Simple entry timestamp/P0/Q0 replay; actual Advanced interval overlaps are contextual, not dollar-matched trades. CF can last beyond the Simple episode.",
            "available_profitable_or_losing_positions":len(candidates),"rows":rows,"aggregates":aggregates}


def rank_rules(oat,matched,winners,losses):
    full=oat[0]["summary"]; ranks=[]
    for variant in oat[1:]:
        name=variant["name"];m=matched["summary"][name]
        ret=(full["total_return"]-variant["summary"]["total_return"])*100
        dd=(full["max_drawdown"]-variant["summary"]["max_drawdown"])*100
        controlled=-m["sum_delta_pnl"]
        # Descriptive effect-size screen, declared independently of strategy parameters.
        terminal_fraction = m["changed_cf_terminal_closes"] / m["changed_anchors"] if m["changed_anchors"] else 0
        if m["changed_anchors"]<5 or (terminal_fraction > .5 and variant["summary"]["number_of_positions"] <= 1):
            category="E_SAMPLE_LIMITED"
        elif abs(ret)<1 and abs(dd)<1 and abs(controlled)<1000:
            category="C_NEGLIGIBLE"
        elif ret>0 and dd>=0 and controlled>0:
            category="A_ADDS_VALUE"
        elif ret<0 and dd<=0 and controlled<0:
            category="D_DRAG"
        else:
            category="B_TRADE_OFF"
        ranks.append({"variant":name,"category":category,"return_contribution_pp":ret,"mdd_reduction_contribution_pp":dd,
            "matched_pnl_contribution":controlled,"matched_changed_anchors":m["changed_anchors"],
            "matched_average_contribution":-m["delta_pnl_without_minus_full"]["mean"],
            "matched_median_contribution":-m["delta_pnl_without_minus_full"]["median"],
            "changed_cf_terminal_closes":m["changed_cf_terminal_closes"],
            "terminal_horizon_warning":terminal_fraction > .5,
            "winner_upside_removed_sum":math.fsum(r["counterfactual_pnl_by_rule"][name]-r["advanced_same_entry_pnl"] for r in winners["rows"]),
            "loss_prevention_sum":math.fsum(r["advanced_same_entry_pnl"]-r["counterfactual_pnl_by_rule"][name] for r in losses["rows"]),
            "winner_sample":len(winners["rows"]),"loss_sample":len(losses["rows"])})
    return sorted(ranks,key=lambda x:x["return_contribution_pp"])


def build_analysis(prepared,frozen):
    full_results={name:simulate(prepared,m) for name,m in VARIANTS.items()}
    full=full_results["ADVANCED_FULL"]; simple=simulate(prepared,simple=True)
    oat=[summarize_simulation(name,m,full_results[name],full["summary"]) for name,m in VARIANTS.items()]
    bridge=[];previous=None
    for name,m in BRIDGE.items():
        result=simulate(prepared,m)
        row=summarize_simulation(name,m,result,full["summary"])
        row["delta_vs_previous"]={k: v-previous[k] if isinstance(v,(float,int)) and isinstance(previous.get(k),(float,int)) else None for k,v in row["summary"].items()} if previous else None
        bridge.append(row);previous=row["summary"]
    positions=frozen["advanced"]["result"]["positions"]
    groups=group_executions(frozen["advanced"]["result"]["executions"])
    matched,_=matched_analysis(prepared,positions,groups)
    events=event_attribution(prepared,positions,groups)
    assert abs(math.fsum(x["total_booked_net_pnl"] for x in events.values())-math.fsum(p["net_pnl"] for p in positions))<1e-7
    winners=simple_episode_analysis(prepared,frozen["simple"]["result"]["positions"],full,winners=True)
    losses=simple_episode_analysis(prepared,frozen["simple"]["result"]["positions"],full,winners=False)
    # Same calendar window comparisons supplement the different worst-MDD dates.
    calendar=[]
    for episode in drawdown_episodes(simple["equity"])[:3]:
        start=prepared.date_index[episode["start"]];end=prepared.date_index[episode["trough"]]
        rows={}
        for name,r in {"SIMPLE":simple,**full_results}.items():
            values=[x["strategy"] for x in r["equity"][start:end+1]]
            rows[name]={"peak_to_simple_trough_return":values[-1]/values[0]-1,
                        "within_window_mdd":float((np.array(values)/np.maximum.accumulate(values)-1).min())}
        calendar.append({"simple_episode":episode,"variants":rows})
    return {"one_at_a_time":oat,"progressive_bridge":bridge,"matched_entry":matched,"event_attribution":events,
            "winner_truncation":winners,"loss_prevention":losses,"drawdown_common_calendar_windows":calendar,
            "exposure":{"simple":simple["exposure"],"advanced":full["exposure"]},
            "simple_drawdown_episodes":drawdown_episodes(simple["equity"])[:5],
            "rule_ranking":rank_rules(oat,matched,winners,losses)}
