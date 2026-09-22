"""Attribution of existing policies, without redefining production ordering."""
import math
from research.modules import FULL, VARIANTS
from research.simulation import simulate
from research.analysis import distribution, first_difference, summarize_simulation
from research.ambiguity import inspect, ENTRY, TP_STOP, MULTI, NONE

POLICIES = ("conservative", "ohlc_heuristic", "favorable")
STUDIES = {"SIMPLE": None, "ADVANCED_FULL": FULL,
           **{k: VARIANTS[k] for k in ("ADVANCED_MINUS_FIRST_TP_FAMILY", "ADVANCED_MINUS_MA_BREAK")}}


def run_one(prepared, modules, policy, anchor=None):
    sim = simulate(prepared, modules or FULL, simple=modules is None, policy=policy, anchor=anchor, trace=True)
    diag = inspect(sim, prepared.request.parameters, modules or FULL, simple=modules is None)
    if anchor:
        for day in diag["days"]:
            day["position_id"] = anchor["position_id"]
    return sim, diag


def analyze(prepared, frozen):
    runs = {}; table = []; diagnostics = {}
    full = simulate(prepared)["summary"]
    for name, modules in STUDIES.items():
        runs[name] = {}; diagnostics[name] = {}
        for policy in POLICIES:
            sim, diag = run_one(prepared, modules, policy)
            runs[name][policy] = sim; diagnostics[name][policy] = diag
            row = summarize_simulation(name, modules, sim, full)
            row.update(policy=policy, ambiguous_days=diag["ambiguous_days"], ambiguous_positions=diag["ambiguous_positions"],
                       engine_flagged_days=diag["engine_flagged_days"], flagged_but_identifiable_days=len(diag["flagged_but_identifiable_days"]))
            table.append(row)
    anchors = frozen["advanced"]["result"]["positions"]
    matched = []; entry_cases = []
    for anchor in anchors:
        life = {policy: run_one(prepared, FULL, policy, anchor) for policy in POLICIES}
        base = life["conservative"][0]
        assert base["positions"][0]["net_pnl"] == anchor["net_pnl"]
        day = anchor["entry_date"][:10]
        diff_day = first_difference(base["executions"], life["favorable"][0]["executions"])
        classifications = [d for _, diag in life.values() for d in diag["days"] if d["date"] == diff_day]
        classes = set(c for d in classifications if d["genuine"] for c in d["classes"])
        bucket = ENTRY if ENTRY in classes else TP_STOP if TP_STOP in classes else MULTI if MULTI in classes else "IDENTIFIABLE_OR_OTHER_POLICY_DIFFERENCE"
        item = {"position_id": anchor["position_id"], "entry_date": day, "p0": anchor["entry_price"], "q0": anchor["q0"],
                "first_difference_date": diff_day, "first_difference_classes": sorted(classes), "cost_bucket": bucket,
                "policies": {p: {"position": sim["positions"][0], "executions": sim["executions"],
                                 "ambiguous_days": diag["ambiguous_days"],
                                 "classifications": [d for d in diag["days"] if d["genuine"] or d["engine_flagged"]]}
                             for p, (sim, diag) in life.items()},
                "delta_favorable_minus_conservative": life["favorable"][0]["positions"][0]["net_pnl"]-anchor["net_pnl"]}
        matched.append(item)
        entry_diag = next(d for d in life["conservative"][1]["days"] if d["date"] == day)
        if entry_diag["entry_stop_candidate"]:
            entry_cases.append({"position_id": anchor["position_id"], **entry_diag,
                "policies": {p: {"entry_day_executions": [e for e in sim["executions"] if e["timestamp"][:10] == day],
                                 "lifecycle_pnl": sim["positions"][0]["net_pnl"], "exit_date": sim["positions"][0]["final_exit_date"]}
                             for p, (sim, _) in life.items()},
                "delta_lifecycle_pnl": item["delta_favorable_minus_conservative"]})
    buckets = {}
    for name in (ENTRY, TP_STOP, MULTI, "IDENTIFIABLE_OR_OTHER_POLICY_DIFFERENCE"):
        sample = [r for r in matched if r["cost_bucket"] == name and abs(r["delta_favorable_minus_conservative"]) > 1e-7]
        vals = [r["delta_favorable_minus_conservative"] for r in sample]
        buckets[name] = {"count": len(sample), "sum_delta": math.fsum(vals), "distribution": distribution(vals),
                         "largest_10": [{"position_id": r["position_id"], "delta": r["delta_favorable_minus_conservative"], "date": r["first_difference_date"]}
                                        for r in sorted(sample, key=lambda r: abs(r["delta_favorable_minus_conservative"]), reverse=True)[:10]]}
    # Post-selection diagnostic only: each policy's own trades, common union-of-uncertain dates.
    uncertain_days = set(d["date"] for strat in diagnostics.values() for diag in strat.values() for d in diag["days"] if d["genuine"])
    excluded = []
    for name in STUDIES:
        for policy in POLICIES:
            sim = runs[name][policy]
            eligible = [p for p in sim["positions"] if not any(p["entry_date"][:10] <= d <= p["final_exit_date"][:10] for d in uncertain_days)]
            excluded.append({"strategy": name, "policy": policy, "total_positions": len(sim["positions"]),
                "retained_count": len(eligible), "removed_count": len(sim["positions"])-len(eligible),
                "net_pnl_sum_NOT_portfolio": math.fsum(p["net_pnl"] for p in eligible),
                "trade_returns": distribution([p["return_pct"]/100 for p in eligible]),
                "position_ids": [p["position_id"] for p in eligible]})
    # Stronger paired check: same Simple entries/P0/Q0; remove anchor if ANY compared lifecycle is ambiguous.
    paired = []; paired_summary = {}
    for anchor in frozen["simple"]["result"]["positions"]:
        comparisons = {}; keep = True; stable = True
        for name, modules in STUDIES.items():
            comparisons[name] = {}
            policy_executions = []
            for policy in POLICIES:
                sim, diag = run_one(prepared, modules, policy, anchor)
                keep = keep and not diag["ambiguous_days"]
                policy_executions.append(sim["executions"])
                comparisons[name][policy] = {"net_pnl": sim["positions"][0]["net_pnl"],
                    "return_pct": sim["positions"][0]["return_pct"], "ambiguous_days": diag["ambiguous_days"]}
            stable = stable and all(first_difference(policy_executions[0], ex) is None for ex in policy_executions[1:])
        paired.append({"simple_position_id": anchor["position_id"], "entry_date": anchor["entry_date"],
                       "retained": keep, "policy_stable": stable, "comparisons": comparisons})
    clean = [r for r in paired if r["retained"]]
    for name in STUDIES:
        paired_summary[name] = {p: {"n": len(clean),
            "sum_net_pnl_NOT_portfolio": math.fsum(r["comparisons"][name][p]["net_pnl"] for r in clean),
            "return_distribution": distribution([r["comparisons"][name][p]["return_pct"]/100 for r in clean]),
            "delta_vs_simple": math.fsum(r["comparisons"][name][p]["net_pnl"]-r["comparisons"]["SIMPLE"][p]["net_pnl"] for r in clean)} for p in POLICIES}
    stable_clean = [r for r in clean if r["policy_stable"]]
    stable_summary = {name: {"n":len(stable_clean),
        "sum_net_pnl_NOT_portfolio":math.fsum(r["comparisons"][name]["conservative"]["net_pnl"] for r in stable_clean),
        "return_distribution":distribution([r["comparisons"][name]["conservative"]["return_pct"]/100 for r in stable_clean])} for name in STUDIES}
    portfolio_deltas = {name: {"final_equity_difference": runs[name]["favorable"]["summary"]["final_equity"]-runs[name]["conservative"]["summary"]["final_equity"],
        "return_difference_pp": (runs[name]["favorable"]["summary"]["total_return"]-runs[name]["conservative"]["summary"]["total_return"])*100} for name in STUDIES}
    robustness = {}
    for policy in POLICIES:
        base = runs["ADVANCED_FULL"][policy]["summary"]["total_return"]
        robustness[policy] = {name: (runs[name][policy]["summary"]["total_return"]-base)*100 for name in STUDIES if name != "ADVANCED_FULL"}
    # Keep evidence without thousands of uneventful rows in the artifact.
    for strategies in diagnostics.values():
        for diag in strategies.values():
            diag["days"] = [d for d in diag["days"] if d["genuine"] or d["engine_flagged"] or d["entry_stop_candidate"]]
    return {"portfolio": table, "portfolio_policy_deltas": portfolio_deltas, "classifications": diagnostics,
            "matched_advanced_77": matched, "entry_day_cases": entry_cases, "ambiguity_cost_buckets": buckets,
            "sum_all_matched_policy_delta": math.fsum(r["delta_favorable_minus_conservative"] for r in matched),
            "exclusion": {"union_genuine_dates": sorted(uncertain_days), "own_path_descriptive": excluded,
                          "paired_simple_entries": paired, "paired_retained": len(clean), "paired_summary": paired_summary,
                          "paired_policy_stable_retained":len(stable_clean), "paired_policy_stable_summary":stable_summary},
            "ablation_return_improvements_pp": robustness}
