"""Fixed-parameter signal/partial/protective/extreme decomposition. No IO."""
from dataclasses import replace
from itertools import product
import math

from research.modules import FULL
from research.simulation import simulate
from research.analysis import distribution, summarize_simulation

# P = immediate partial; S = protective; E = both extremes. Signal always on.
FACTORIAL = {f"P{int(p)}S{int(s)}E{int(e)}": replace(FULL, first_tp_partial=p, protective=s, bias=e, atr=e)
             for p, s, e in product((False, True), repeat=3)}
NAMES = {
    "ADVANCED_FULL": "P1S1E1",
    "FIRST_TP_SIGNAL_ONLY_NO_PARTIAL": "P0S1E1",
    "FIRST_TP_PARTIAL_NO_PROTECTIVE": "P1S0E1",
    "FIRST_TP_PARTIAL_ONLY": "P1S0E0",
    "FIRST_TP_SIGNAL_PLUS_PROTECTIVE_NO_PARTIAL": "P0S1E0",
    "EXTREME_TP_OFF": "P1S1E0",
    "PROTECTIVE_OFF": "P1S0E1",
    "SIGNAL_ONLY_FULL_RISK_REFERENCE": "P0S0E0",
    "SIGNAL_PLUS_EXTREME_NO_PARTIAL_NO_PROTECTIVE": "P0S0E1",
}


def analyze(prepared, anchors):
    simulations = {key: simulate(prepared, m) for key, m in FACTORIAL.items()}
    full = simulations["P1S1E1"]
    table = [dict(summarize_simulation(name, FACTORIAL[key], simulations[key], full["summary"]),
                  factorial_cell=key, alias_of="FIRST_TP_PARTIAL_NO_PROTECTIVE" if name == "PROTECTIVE_OFF" else None)
             for name, key in NAMES.items()]
    matched = []; cache = {}
    for anchor in anchors:
        pid = anchor["position_id"]
        cache[pid] = {k: simulate(prepared, m, anchor=anchor) for k, m in FACTORIAL.items()}
        assert cache[pid]["P1S1E1"]["positions"][0]["net_pnl"] == anchor["net_pnl"]
        matched.append({"position_id": pid, "entry_date": anchor["entry_date"], "p0": anchor["entry_price"],
            "q0": anchor["q0"], "full_net_pnl": anchor["net_pnl"],
            "cells": {k: {"position": r["positions"][0], "delta_pnl": r["positions"][0]["net_pnl"]-anchor["net_pnl"],
                           "executions": r["executions"]} for k, r in cache[pid].items()}})
    summaries = {}
    for name, key in NAMES.items():
        xs = [r["cells"][key]["delta_pnl"] for r in matched]
        changed = [r for r in matched if abs(r["cells"][key]["delta_pnl"]) > 1e-7]
        ranked = sorted(matched, key=lambda r: r["cells"][key]["delta_pnl"])
        summaries[name] = {"anchors": len(matched), "delta": distribution(xs), "sum_delta": math.fsum(xs),
            "changed_anchors": len(changed), "changed_delta": distribution([r["cells"][key]["delta_pnl"] for r in changed]),
            "exit_date_changes": sum(r["cells"][key]["position"]["final_exit_date"] != r["cells"]["P1S1E1"]["position"]["final_exit_date"] for r in matched),
            "winner_delta": math.fsum(r["cells"][key]["delta_pnl"] for r in matched if r["full_net_pnl"] > 0),
            "loser_delta": math.fsum(r["cells"][key]["delta_pnl"] for r in matched if r["full_net_pnl"] <= 0),
            "terminal_closes": sum(r["cells"][key]["position"]["exit_final_close_reason"] == "END_OF_BACKTEST" for r in changed),
            "top_positive": [{"position_id": r["position_id"], "delta": r["cells"][key]["delta_pnl"]} for r in reversed(ranked) if r["cells"][key]["delta_pnl"] > 1e-7][:10],
            "top_negative": [{"position_id": r["position_id"], "delta": r["cells"][key]["delta_pnl"]} for r in ranked if r["cells"][key]["delta_pnl"] < -1e-7][:10]}
    marginal = []
    for dimension in ("P", "S", "E"):
        i = {"P": 1, "S": 3, "E": 5}[dimension]
        for off in FACTORIAL:
            if off[i] != "0":
                continue
            on = off[:i] + "1" + off[i+1:]
            diffs = [r["cells"][on]["position"]["net_pnl"]-r["cells"][off]["position"]["net_pnl"] for r in matched]
            a, b = simulations[on], simulations[off]
            marginal.append({"module": dimension, "off": off, "on": on,
                "return_effect_pp": (a["summary"]["total_return"]-b["summary"]["total_return"])*100,
                "mdd_reduction_pp": (a["summary"]["max_drawdown"]-b["summary"]["max_drawdown"])*100,
                "matched_sum_on_minus_off": math.fsum(diffs), "matched_distribution": distribution(diffs),
                "exposure_effect_pp": a["exposure"]["average_close_capital_exposure_pct"]-b["exposure"]["average_close_capital_exposure_pct"]})
    # Inclusion/exclusion interaction effects, not parameter optimization.
    def value(key, metric):
        if metric == "matched_pnl":
            return math.fsum(r["cells"][key]["position"]["net_pnl"] for r in matched)
        return simulations[key]["summary"][metric]
    interactions = {}
    for metric in ("total_return", "max_drawdown", "matched_pnl"):
        v = lambda k: value(k, metric)
        interactions[metric] = {
            "P_x_S_at_E1": v("P1S1E1")-v("P0S1E1")-v("P1S0E1")+v("P0S0E1"),
            "P_x_E_at_S1": v("P1S1E1")-v("P0S1E1")-v("P1S1E0")+v("P0S1E0"),
            "S_x_E_at_P1": v("P1S1E1")-v("P1S0E1")-v("P1S1E0")+v("P1S0E0"),
            "P_x_S_x_E": sum((1 if k.count("1") % 2 else -1)*v(k) for k in FACTORIAL)}
    # Rank by full-risk-reference upside, stated explicitly to avoid cherry-picking.
    winners = sorted(matched, key=lambda r: r["cells"]["P0S0E0"]["position"]["net_pnl"], reverse=True)[:5]
    for item in sorted(matched, key=lambda r:r["full_net_pnl"], reverse=True)[:3]:
        if item not in winners:
            winners.append(item)
    trajectories = []
    for item in winners:
        selected = {label: cache[item["position_id"]][key] for label, key in
                    [("full", "P1S1E1"), ("no_50_partial", "P0S1E1"), ("no_protective", "P1S0E1"), ("no_extreme", "P1S1E0")]}
        maps = {k: {r["timestamp"][:10]: r for r in sim["equity"]} for k, sim in selected.items()}
        dates = sorted(set().union(*(x.keys() for x in maps.values())))
        rows = []
        for day in dates:
            bar = prepared.rows[prepared.date_index[day]][0]
            rows.append({"date": day, "close": bar.close,
                **{f"{k}_qty": m.get(day, {}).get("quantity", 0) for k, m in maps.items()},
                "executions": {k: [e for e in sim["executions"] if e["timestamp"][:10] == day] for k, sim in selected.items()}})
        trajectories.append({"position_id": item["position_id"], "p0": item["p0"], "q0": item["q0"],
                             "reference_pnl": item["cells"]["P0S0E0"]["position"]["net_pnl"], "daily": rows})
    tradeoffs = []
    for name, key in NAMES.items():
        # Fixed full-risk-defined winner/loser groups, not variant-defined survivor groups.
        loss = [r for r in matched if r["cells"]["P0S0E0"]["position"]["net_pnl"] < 0]
        win = [r for r in matched if r["cells"]["P0S0E0"]["position"]["net_pnl"] > 0]
        tradeoffs.append({"variant": name, "reference_losers": len(loss), "reference_winners": len(win),
            "loss_avoided": math.fsum(r["cells"][key]["position"]["net_pnl"]-r["cells"]["P0S0E0"]["position"]["net_pnl"] for r in loss),
            "upside_sacrificed": math.fsum(r["cells"]["P0S0E0"]["position"]["net_pnl"]-r["cells"][key]["position"]["net_pnl"] for r in win)})
    return {"variant_definitions": {name: {"factorial_cell": k, "modules": FACTORIAL[k].as_dict()} for name, k in NAMES.items()},
            "portfolio": table, "matched": {"rows": matched, "summary": summaries}, "marginal_effects": marginal,
            "factorial_interactions": interactions, "winner_quantity_trajectories": trajectories,
            "risk_tradeoffs": tradeoffs}
