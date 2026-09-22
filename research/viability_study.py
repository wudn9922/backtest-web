"""Simple Strategy v2 viability gate — offline, research-only computation."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import date
import hashlib
import json
import math
import time

import numpy as np

from research import ROOT
from research.analysis import drawdown_episodes, group_executions
from research.ambiguity import inspect
from research.baseline import digest, immutable_fingerprints, load, normalize_timestamps
from research.modules import FULL
from research.run_ablation import canonical_checks
from research.simulation import Prepared, simulate
from research.structural_data import load_inputs
from research.viability_benchmarks import (
    buy_and_hold, comparison_label, entry_zone_hold, entry_zone_signals,
    exposure_normalized, independent_signal_horizon, metric_delta, metric_view,
)
from research.viability_design import (
    AMBIGUITY_CLASSIFICATION, BENCHMARKS, COMPARISON_LABELS, COST_SCENARIOS,
    ETFS, EXIT_FORWARD_HORIZONS, FORWARD_HORIZONS, PERIODS, POLICIES,
    STATISTICS, STRATEGY_FREEZE, SYMBOLS, TEST_BLOCKS, VIABILITY_GATE,
    WF_TRAIN_GATE, walk_forward_folds,
)
from research.viability_statistics import (
    clustered_bootstrap, describe, signal_block_bootstrap, winner_concentration,
)


def _hash_result(result):
    return {
        "executions_sha256": digest(normalize_timestamps(result["executions"])),
        "positions_sha256": digest(normalize_timestamps(result["positions"])),
        "equity_sha256": digest([x["strategy"] for x in result["equity"]]),
    }


def _record(symbol, period, policy, name, result):
    return {"symbol": symbol, "period": period, "policy": policy, "strategy": name,
            "metrics": metric_view(result), **_hash_result(result)}


def _distribution_by_policy(rows, comparator):
    result = {}
    for policy in POLICIES:
        selected = [r for r in rows if r["period"] == "FULL" and r["policy"] == policy and r["comparator"] == comparator]
        result[policy] = {
            "symbols": len(selected),
            "return_improved": sum(r["delta"]["return_pp"] > 1e-9 for r in selected),
            "sharpe_improved": sum((r["delta"]["sharpe"] or 0) > 1e-9 for r in selected),
            "mdd_improved": sum(r["delta"]["mdd_pp"] > 1e-9 for r in selected),
            "return_delta_pp": describe([r["delta"]["return_pp"] for r in selected]),
            "sharpe_delta": describe([r["delta"]["sharpe"] for r in selected]),
            "mdd_delta_pp": describe([r["delta"]["mdd_pp"] for r in selected]),
            "calmar_delta": describe([r["delta"]["calmar"] for r in selected]),
        }
    return result


def _forward(prepared, day, price=None, horizons=EXIT_FORWARD_HORIZONS):
    i = prepared.date_index[day[:10]]
    base = prepared.rows[i][0].close if price is None else price
    return {str(n): (prepared.rows[i+n][0].close / base - 1 if i+n < len(prepared.rows) else None) for n in horizons}


def _entry_features(prepared, day):
    i = prepared.date_index[day[:10]]
    close = prepared.enriched.close
    raw_i = prepared.enriched.index.get_loc(prepared.period.index[i])
    def prior(n):
        return float(close.iloc[raw_i-1] / close.iloc[raw_i-1-n] - 1) if raw_i-1-n >= 0 else None
    return {"prior_20d_return": prior(20), "prior_60d_return": prior(60),
            "reference_atr_pct": float(prepared.rows[i][2] / prepared.rows[i][0].open),
            "reference_ma_distance": float(prepared.rows[i][0].open / prepared.rows[i][1] - 1)}


def _train_policy_gate(rows):
    flags = {}
    output = {}
    for comparator, mdd_limit in (("ADVANCED_V2", -20), ("BUY_AND_HOLD", -10)):
        selected = [r for r in rows if r["comparator"] == comparator]
        returns = [r["delta"]["return_pp"] for r in selected]
        positives = [x for x in returns if x > 1e-9]
        local = {
            "return_breadth": sum(x >= -1e-9 for x in returns) >= 6,
            "median_return": float(np.median(returns)) > 1e-9,
            "median_sharpe": float(np.median([r["delta"]["sharpe"] for r in selected])) >= -1e-9,
            "mdd": float(np.median([r["delta"]["mdd_pp"] for r in selected])) >= mdd_limit,
            "concentration": bool(positives) and max(positives) / sum(positives) <= .5 + 1e-12,
        }
        flags[comparator] = local
        output[comparator] = {
            "pass": all(local.values()), "flags": local,
            "return_improved": sum(x > 1e-9 for x in returns),
            "median_return_delta_pp": float(np.median(returns)),
            "median_sharpe_delta": float(np.median([r["delta"]["sharpe"] for r in selected])),
            "median_mdd_delta_pp": float(np.median([r["delta"]["mdd_pp"] for r in selected])),
            "largest_positive_contribution": max(positives) / sum(positives) if positives else None,
        }
    return {"pass": all(v["pass"] for v in output.values()), "comparators": output}


def _fold_gate(policy_gates):
    passed = [p for p, value in policy_gates.items() if value["pass"]]
    return {"status": "PASS" if "conservative" in passed and len(passed) >= 2 else "FAIL",
            "passed_policies": passed, "required": "Conservative plus at least one other policy"}


def _classification(full_breadth, cross_period, fold_breadth, ambiguity, costs, uncertainty, concentration):
    def full_ok(comparator, policies=2):
        supportive = [x for x in POLICIES if full_breadth[comparator][x]["return_delta_pp"]["median"] > 0
                      and full_breadth[comparator][x]["return_improved"] >= 6]
        return len(supportive) >= policies
    period_cells = []
    for period in ("A", "B"):
        for policy in POLICIES:
            values = [r for r in cross_period if r["period"] == period and r["policy"] == policy]
            period_cells.append(all(next(x for x in values if x["comparator"] == c)["median_return_delta_pp"] > 0
                                    for c in ("ADVANCED_V2", "BUY_AND_HOLD")))
    fold_policy = {}
    for policy in POLICIES:
        rows = [r for r in fold_breadth if r["policy"] == policy]
        fold_policy[policy] = sum(r["vs_advanced_return_improved"] >= 6 and r["vs_buy_hold_return_improved"] >= 6 for r in rows)
    worst = costs["DOUBLE_BOTH"]["breadth"]
    cost_ok = sum(all(worst[c][p]["return_delta_pp"]["median"] > 0 and worst[c][p]["return_improved"] >= 6
                      for c in ("ADVANCED_V2", "BUY_AND_HOLD")) for p in POLICIES) >= 2
    promising = {
        "full_period": full_ok("ADVANCED_V2") and full_ok("BUY_AND_HOLD"),
        "subperiod": sum(period_cells) >= 3,
        "walk_forward": any(count >= 3 for count in fold_policy.values()),
        "cost_stress": cost_ok,
        "ambiguity": not ambiguity["median_sign_reversal_vs_buy_hold"],
    }
    strong = {
        "full_period_all_policies": full_ok("ADVANCED_V2", 3) and full_ok("BUY_AND_HOLD", 3)
            and all(full_breadth[c][p]["sharpe_delta"]["median"] > 0 for c in ("ADVANCED_V2", "BUY_AND_HOLD") for p in POLICIES),
        "subperiod": sum(period_cells) >= 4,
        "walk_forward": sum(count >= 4 for count in fold_policy.values()) >= 2,
        "ambiguity": ambiguity["classification"] == "ROBUST",
        "cost_stress": all(all(worst[c][p]["return_delta_pp"]["median"] > 0 and worst[c][p]["return_improved"] >= 6
                               for c in ("ADVANCED_V2", "BUY_AND_HOLD")) for p in POLICIES),
        "bootstrap": False,
        "concentration": concentration["pooled_conservative"]["remove_each_symbol_largest_winner_net_pnl"] > 0
            and concentration["pooled_conservative"]["trim_top_5pct_winners_net_pnl"] > 0,
        "risk": sum(full_breadth["BUY_AND_HOLD"][p]["mdd_delta_pp"]["median"] >= -15
                    and full_breadth["BUY_AND_HOLD"][p]["sharpe_delta"]["median"] > 0
                    and full_breadth["BUY_AND_HOLD"][p]["calmar_delta"]["median"] > 0 for p in POLICIES) >= 2,
    }
    # Correctly evaluate paired bootstrap precision separately for both comparators.
    strong["bootstrap"] = sum(all(uncertainty[c][p]["mean_ci95"][0] > 0 for c in ("ADVANCED_V2", "BUY_AND_HOLD")) for p in POLICIES) >= 2
    if all(strong.values()):
        label = "STRONG RETROSPECTIVE EVIDENCE — FREEZE FOR FORWARD TEST"
    elif all(promising.values()):
        label = "PROMISING — NEEDS FORWARD DATA"
    else:
        label = "NOT SUPPORTED"
    return {"classification": label, "promising_checks": promising, "strong_checks": strong,
            "subperiod_supportive_cells": sum(period_cells), "folds_supportive_by_policy": fold_policy}


def run(progress=lambda _s: None):
    started = time.perf_counter()
    before = immutable_fingerprints()
    frozen, canonical_daily = load()
    canonical = canonical_checks(frozen, canonical_daily)
    manifest, frames = load_inputs()
    assert tuple(frames) == SYMBOLS
    base = frozen["advanced"]["request_object"]
    common_start = max(PERIODS["FULL"][0], max(frame.index[0].date() for frame in frames.values()))
    common_end = min(PERIODS["FULL"][1], min(frame.index[-1].date() for frame in frames.values()))

    prepared_full = {}
    full_results = {}
    portfolio = []
    comparisons = []
    cross_period = []
    calendar_checks = {}

    for period_name, (requested_start, requested_end) in PERIODS.items():
        calendars = {}
        for symbol in SYMBOLS:
            req = base.model_copy(update={"ticker": symbol, "start_date": max(requested_start, common_start),
                                          "end_date": min(requested_end, common_end)})
            p = Prepared(req, frames[symbol])
            calendars[symbol] = p.dates
            if period_name == "FULL":
                prepared_full[symbol] = p
            hold = buy_and_hold(p)
            zone = entry_zone_hold(p)
            portfolio.append(_record(symbol, period_name, None, "BUY_AND_HOLD", hold))
            portfolio.append(_record(symbol, period_name, None, "ENTRY_ZONE_HOLD", zone))
            for policy in POLICIES:
                simple = simulate(p, simple=True, policy=policy)
                advanced = simulate(p, policy=policy)
                if period_name == "FULL":
                    full_results[symbol, policy] = {"prepared": p, "simple": simple, "advanced": advanced,
                                                    "buy_hold": hold, "entry_zone_hold": zone}
                portfolio.extend((_record(symbol, period_name, policy, "SIMPLE_V2", simple),
                                  _record(symbol, period_name, policy, "ADVANCED_V2", advanced)))
                sm, am, hm = metric_view(simple), metric_view(advanced), metric_view(hold)
                for comparator, left in (("ADVANCED_V2", am), ("BUY_AND_HOLD", hm)):
                    comparisons.append({"symbol": symbol, "period": period_name, "policy": policy,
                                        "comparator": comparator, "delta": metric_delta(left, sm),
                                        "label": comparison_label(sm, hm) if comparator == "BUY_AND_HOLD" else None})
            progress(f"Portfolio comparison: {period_name} / {symbol}")
        calendar_checks[period_name] = {
            "identical_session_dates": all(v == next(iter(calendars.values())) for v in calendars.values()),
            "session_count": {s: len(v) for s, v in calendars.items()},
            "date_set_differences": {s: sorted(set(v) ^ set(next(iter(calendars.values())))) for s, v in calendars.items()},
        }
        assert calendar_checks[period_name]["identical_session_dates"]

    full_breadth = {c: _distribution_by_policy(comparisons, c) for c in ("ADVANCED_V2", "BUY_AND_HOLD")}
    for period_name in ("A", "B"):
        for policy in POLICIES:
            for comparator in ("ADVANCED_V2", "BUY_AND_HOLD"):
                rows = [r for r in comparisons if r["period"] == period_name and r["policy"] == policy and r["comparator"] == comparator]
                cross_period.append({"period": period_name, "policy": policy, "comparator": comparator,
                    "return_improved": sum(r["delta"]["return_pp"] > 0 for r in rows),
                    "sharpe_improved": sum((r["delta"]["sharpe"] or 0) > 0 for r in rows),
                    "mdd_improved": sum(r["delta"]["mdd_pp"] > 0 for r in rows),
                    "median_return_delta_pp": float(np.median([r["delta"]["return_pp"] for r in rows])),
                    "median_sharpe_delta": float(np.median([r["delta"]["sharpe"] for r in rows])),
                    "median_mdd_delta_pp": float(np.median([r["delta"]["mdd_pp"] for r in rows]))})

    # Every date is retained for the unconditional distribution.  Fixed-horizon
    # costed rows are attached only to valid signals and never pooled as capital.
    signal_rows = []
    for symbol, p in prepared_full.items():
        for signal in entry_zone_signals(p):
            row = {"symbol": symbol, **signal}
            i = signal["index"]
            for horizon in FORWARD_HORIZONS:
                row[f"forward_{horizon}d_from_open"] = (p.rows[i+horizon][0].close / signal["open"] - 1
                    if i+horizon < len(p.rows) else None)
                row[f"forward_{horizon}d_from_entry_level"] = (p.rows[i+horizon][0].close / signal["raw_fill"] - 1
                    if signal["raw_fill"] is not None and i+horizon < len(p.rows) else None)
            if signal["classification"] == "VALID_ENTRY":
                row["fixed_horizon"] = {str(n): independent_signal_horizon(p, signal, n) for n in (20, 40, 60)}
            signal_rows.append(row)
        progress(f"Entry Zone forward paths: {symbol}")
    entry_summary = {
        "counts": {kind: sum(r["classification"] == kind for r in signal_rows)
                   for kind in ("VALID_ENTRY", "ENTRY_ZONE_MISSED", "ARMED_UNFILLED", "NO_SIGNAL")},
        "valid_vs_unconditional": {str(n): signal_block_bootstrap(signal_rows, "VALID_ENTRY", n) for n in FORWARD_HORIZONS},
        "missed_vs_unconditional": {str(n): signal_block_bootstrap(signal_rows, "ENTRY_ZONE_MISSED", n) for n in (5, 10, 20, 40)},
        "valid_vs_missed": {str(n): {
            "valid": describe([r[f"forward_{n}d_from_open"] for r in signal_rows if r["classification"] == "VALID_ENTRY"]),
            "missed": describe([r[f"forward_{n}d_from_open"] for r in signal_rows if r["classification"] == "ENTRY_ZONE_MISSED"]),
            "mean_difference": float(np.mean([r[f"forward_{n}d_from_open"] for r in signal_rows if r["classification"] == "VALID_ENTRY" and r[f"forward_{n}d_from_open"] is not None]) -
                                     np.mean([r[f"forward_{n}d_from_open"] for r in signal_rows if r["classification"] == "ENTRY_ZONE_MISSED" and r[f"forward_{n}d_from_open"] is not None])),
        } for n in (5, 10, 20, 40)},
        "costed_fixed_horizon_valid_signals": {str(n): describe([
            r["fixed_horizon"][str(n)]["return_on_entry_cost"] for r in signal_rows
            if r["classification"] == "VALID_ENTRY" and r["fixed_horizon"][str(n)]["complete"]
        ]) for n in (20, 40, 60)},
    }

    # Retrospective expanding/rolling windows.  Test values are calculated once
    # per unique fold then referenced by both train designs.
    test_cache = {}
    train_gates = {"expanding": {}, "rolling": {}}
    fold_rows = []
    for design in ("expanding", "rolling"):
        for fold in [f for f in walk_forward_folds() if f["design"] == design]:
            train_by_policy = defaultdict(list)
            train_cells = {}
            for symbol in SYMBOLS:
                req = base.model_copy(update={"ticker": symbol, "start_date": fold["train_start"], "end_date": fold["train_end"]})
                p = Prepared(req, frames[symbol]); hold = buy_and_hold(p)
                for policy in POLICIES:
                    simple, advanced = simulate(p, simple=True, policy=policy), simulate(p, policy=policy)
                    sm, am, hm = metric_view(simple), metric_view(advanced), metric_view(hold)
                    comp = [{"comparator": c, "delta": metric_delta(m, sm)} for c, m in (("ADVANCED_V2", am), ("BUY_AND_HOLD", hm))]
                    train_by_policy[policy].extend(comp)
                    train_cells[symbol, policy] = {"simple": sm, "advanced": am, "buy_hold": hm,
                                                   "vs_advanced": comp[0]["delta"], "vs_buy_hold": comp[1]["delta"]}
            policy_gates = {policy: _train_policy_gate(rows) for policy, rows in train_by_policy.items()}
            gate = _fold_gate(policy_gates)
            train_gates[design][fold["fold"]] = {"policies": policy_gates, "composite": gate}
            for symbol in SYMBOLS:
                for policy in POLICIES:
                    key = (fold["fold"], symbol, policy)
                    if key not in test_cache:
                        req = base.model_copy(update={"ticker": symbol, "start_date": fold["test_start"], "end_date": fold["test_end"]})
                        p = Prepared(req, frames[symbol]); hold = buy_and_hold(p)
                        simple, advanced = simulate(p, simple=True, policy=policy), simulate(p, policy=policy)
                        test_cache[key] = {"prepared": p, "simple": simple, "advanced": advanced, "buy_hold": hold}
                    test = test_cache[key]
                    sm, am, hm = map(metric_view, (test["simple"], test["advanced"], test["buy_hold"]))
                    tr = train_cells[symbol, policy]
                    fold_rows.append({"design": design, "fold": fold["fold"],
                        "train_start": str(fold["train_start"]), "train_end": str(fold["train_end"]),
                        "test_start": str(fold["test_start"]), "test_end": str(fold["test_end"]),
                        "actual_train_start": Prepared(base.model_copy(update={"ticker": symbol, "start_date": fold["train_start"], "end_date": fold["train_end"]}), frames[symbol]).dates[0],
                        "actual_test_start": test["prepared"].dates[0], "actual_test_end": test["prepared"].dates[-1],
                        "symbol": symbol, "policy": policy, "train": tr,
                        "test": {"simple": sm, "advanced": am, "buy_hold": hm,
                                 "vs_advanced": metric_delta(am, sm), "vs_buy_hold": metric_delta(hm, sm)},
                        "train_gate": gate["status"]})
            progress(f"Walk-forward: {design} / {fold['fold']} / gate {gate['status']}")

    fold_breadth = []
    for fold, *_ in TEST_BLOCKS:
        for policy in POLICIES:
            rows = [r for r in fold_rows if r["design"] == "expanding" and r["fold"] == fold and r["policy"] == policy]
            fold_breadth.append({"fold": fold, "policy": policy,
                "vs_advanced_return_improved": sum(r["test"]["vs_advanced"]["return_pp"] > 0 for r in rows),
                "vs_buy_hold_return_improved": sum(r["test"]["vs_buy_hold"]["return_pp"] > 0 for r in rows),
                "vs_advanced_sharpe_improved": sum((r["test"]["vs_advanced"]["sharpe"] or 0) > 0 for r in rows),
                "vs_buy_hold_sharpe_improved": sum((r["test"]["vs_buy_hold"]["sharpe"] or 0) > 0 for r in rows),
                "vs_advanced_mdd_improved": sum(r["test"]["vs_advanced"]["mdd_pp"] > 0 for r in rows),
                "vs_buy_hold_mdd_improved": sum(r["test"]["vs_buy_hold"]["mdd_pp"] > 0 for r in rows),
                "median_return_delta_vs_advanced_pp": float(np.median([r["test"]["vs_advanced"]["return_pp"] for r in rows])),
                "median_return_delta_vs_buy_hold_pp": float(np.median([r["test"]["vs_buy_hold"]["return_pp"] for r in rows])),
            })

    stitched = {}
    for policy in POLICIES:
        per_symbol = {}
        for symbol in SYMBOLS:
            sr = [next(r for r in fold_rows if r["design"] == "expanding" and r["fold"] == f and r["symbol"] == symbol and r["policy"] == policy) for f, *_ in TEST_BLOCKS]
            per_symbol[symbol] = {name: math.prod(1 + r["test"][name]["total_return"] for r in sr) - 1
                                  for name in ("simple", "advanced", "buy_hold")}
        stitched[policy] = {"per_symbol_return": per_symbol,
            "median": {name: float(np.median([x[name] for x in per_symbol.values()])) for name in ("simple", "advanced", "buy_hold")},
            "equal_weight_fold_reset": {name: math.prod(1 + np.mean([next(r for r in fold_rows if r["design"] == "expanding" and r["fold"] == f and r["symbol"] == s and r["policy"] == policy)["test"][name]["total_return"] for s in SYMBOLS]) for f, *_ in TEST_BLOCKS) - 1 for name in ("simple", "advanced", "buy_hold")},
            "warning": "Research index: every symbol is an independent equal 1/11 sleeve reset at fold boundaries; it is not a pooled executable portfolio."}

    # Ambiguity attribution and exact policy-invariant matched cohort.
    ambiguity_by_symbol = {}
    ambiguity_cost_rows = []
    clean_rows = []
    for symbol, p in prepared_full.items():
        traced = {policy: simulate(p, simple=True, policy=policy, trace=True) for policy in POLICIES}
        audited = {policy: inspect(result, p.request.parameters, FULL, simple=True) for policy, result in traced.items()}
        ambiguity_by_symbol[symbol] = {policy: {k: audit[k] for k in ("ambiguous_days", "ambiguous_positions", "engine_flagged_days")} for policy, audit in audited.items()}
        anchors = full_results[symbol, "conservative"]["simple"]["positions"]
        for anchor in anchors:
            simple_sims = {policy: simulate(p, simple=True, policy=policy, anchor=anchor, trace=True) for policy in POLICIES}
            advanced_sims = {policy: simulate(p, policy=policy, anchor=anchor, trace=True) for policy in POLICIES}
            simple_audits = {policy: inspect(sim, p.request.parameters, FULL, simple=True) for policy, sim in simple_sims.items()}
            advanced_audits = {policy: inspect(sim, p.request.parameters, FULL) for policy, sim in advanced_sims.items()}
            ambiguity_classes = sorted({klass for audit in (*simple_audits.values(), *advanced_audits.values())
                                        for day in audit["days"] if day["genuine"] for klass in day["classes"]
                                        if klass != "NON_AMBIGUOUS"})
            simple_ambiguity_classes = sorted({klass for audit in simple_audits.values()
                                               for day in audit["days"] if day["genuine"] for klass in day["classes"]
                                               if klass != "NON_AMBIGUOUS"})
            genuine = bool(ambiguity_classes)
            simple_hashes = {_hash_result(sim)["executions_sha256"] for sim in simple_sims.values()}
            advanced_hashes = {_hash_result(sim)["executions_sha256"] for sim in advanced_sims.values()}
            divergent = len(simple_hashes) > 1 or len(advanced_hashes) > 1
            positions = {"simple": {k: v["positions"][0] for k, v in simple_sims.items()},
                         "advanced": {k: v["positions"][0] for k, v in advanced_sims.items()}}
            row = {"symbol": symbol, "position_id": anchor["position_id"], "entry_date": anchor["entry_date"],
                   "entry_price": anchor["entry_price"], "q0": anchor["q0"], "genuine_ambiguity": genuine,
                   "ambiguity_classes": ambiguity_classes, "simple_ambiguity_classes": simple_ambiguity_classes,
                   "policy_execution_divergence": divergent,
                   "simple_pnl": {k: v["net_pnl"] for k, v in positions["simple"].items()},
                   "advanced_pnl": {k: v["net_pnl"] for k, v in positions["advanced"].items()},
                   "favorable_minus_conservative_simple_pnl": positions["simple"]["favorable"]["net_pnl"] - positions["simple"]["conservative"]["net_pnl"]}
            if genuine or divergent:
                ambiguity_cost_rows.append(row)
            else:
                sp, ap = positions["simple"]["conservative"], positions["advanced"]["conservative"]
                entry_execution = simple_sims["conservative"]["executions"][0]
                entry_cost = entry_execution["gross_value"] + entry_execution["commission"]
                clean_rows.append({**row, "simple_net_pnl": sp["net_pnl"], "advanced_net_pnl": ap["net_pnl"],
                    "delta_simple_minus_advanced": sp["net_pnl"] - ap["net_pnl"],
                    "entry_cost": entry_cost,
                    "delta_return_on_entry_cost_pp": 100 * (sp["net_pnl"] - ap["net_pnl"]) / entry_cost,
                    "simple_mfe": sp["maximum_favorable_excursion"], "advanced_mfe": ap["maximum_favorable_excursion"],
                    "simple_mae": sp["maximum_adverse_excursion"], "advanced_mae": ap["maximum_adverse_excursion"],
                    "holding_days_delta": sp["holding_days"] - ap["holding_days"]})
        progress(f"Ambiguity / policy-invariant cohort: {symbol}")
    policy_medians = {policy: float(np.median([next(r for r in comparisons if r["symbol"] == s and r["period"] == "FULL" and r["policy"] == policy and r["comparator"] == "BUY_AND_HOLD")["delta"]["return_pp"] for s in SYMBOLS])) for policy in POLICIES}
    sharpe_medians = {policy: full_breadth["BUY_AND_HOLD"][policy]["sharpe_delta"]["median"] for policy in POLICIES}
    consistent_symbols = sum(len({int(np.sign(next(r for r in comparisons if r["symbol"] == s and r["period"] == "FULL" and r["policy"] == p and r["comparator"] == "BUY_AND_HOLD")["delta"]["return_pp"])) for p in POLICIES}) == 1 for s in SYMBOLS)
    median_sign_reversal = len({int(np.sign(x)) for x in policy_medians.values()}) > 1 or len({int(np.sign(x)) for x in sharpe_medians.values()}) > 1
    if not median_sign_reversal and consistent_symbols >= 8 and max(policy_medians.values()) - min(policy_medians.values()) <= 20:
        ambiguity_class = "ROBUST"
    elif median_sign_reversal or consistent_symbols < 7:
        ambiguity_class = "POLICY_SENSITIVE"
    else:
        ambiguity_class = "MIXED"
    ambiguity = {"definition": AMBIGUITY_CLASSIFICATION, "by_symbol": ambiguity_by_symbol,
        "classification": ambiguity_class, "policy_median_simple_minus_buy_hold_return_pp": policy_medians,
        "policy_median_sharpe_delta": sharpe_medians, "symbols_same_return_delta_sign": consistent_symbols,
        "median_sign_reversal_vs_buy_hold": median_sign_reversal,
        "affected_entries": len(ambiguity_cost_rows),
        "cost_favorable_minus_conservative": describe([r["favorable_minus_conservative_simple_pnl"] for r in ambiguity_cost_rows]),
        "entry_day_ambiguity": {"entries": sum("ENTRY_THEN_STOP_AMBIGUITY" in r["simple_ambiguity_classes"] for r in ambiguity_cost_rows),
            "favorable_minus_conservative_pnl": describe([r["favorable_minus_conservative_simple_pnl"] for r in ambiguity_cost_rows if "ENTRY_THEN_STOP_AMBIGUITY" in r["simple_ambiguity_classes"]]),
            "largest": sorted([r for r in ambiguity_cost_rows if "ENTRY_THEN_STOP_AMBIGUITY" in r["simple_ambiguity_classes"]], key=lambda r: abs(r["favorable_minus_conservative_simple_pnl"]), reverse=True)[:10]},
        "largest_cost_differences": sorted(ambiguity_cost_rows, key=lambda r: abs(r["favorable_minus_conservative_simple_pnl"]), reverse=True)[:10],
        "ambiguity_free_matched": {"entries": len(clean_rows),
            "simple_minus_advanced_net_pnl": describe([r["delta_simple_minus_advanced"] for r in clean_rows]),
            "simple_mfe": describe([r["simple_mfe"] for r in clean_rows]), "advanced_mfe": describe([r["advanced_mfe"] for r in clean_rows]),
            "simple_mae": describe([r["simple_mae"] for r in clean_rows]), "advanced_mae": describe([r["advanced_mae"] for r in clean_rows]),
            "holding_days_delta": describe([r["holding_days_delta"] for r in clean_rows]),
            "two_way_cluster_bootstrap": clustered_bootstrap(clean_rows, "delta_return_on_entry_cost_pp")}}

    # Simple exit attribution and worst-trade / drawdown comparisons.
    exit_rows = []
    worst_trades = {}
    worst_drawdowns = {}
    concentration = {"by_symbol_policy": {}}
    pooled_by_policy = defaultdict(list)
    for policy in POLICIES:
        losses = []
        episodes = []
        concentration["by_symbol_policy"][policy] = {}
        for symbol in SYMBOLS:
            bundle = full_results[symbol, policy]; p = bundle["prepared"]; simple = bundle["simple"]
            groups = group_executions(simple["executions"])
            for position, executions in zip(simple["positions"], groups):
                assert len(executions) == 2
                exit_execution = executions[-1]
                bar = p.rows[p.date_index[exit_execution["timestamp"][:10]]][0]
                exit_rows.append({"symbol": symbol, "policy": policy, "position_id": position["position_id"],
                    "entry_date": position["entry_date"], "exit_date": position["final_exit_date"],
                    "exit_reason": exit_execution["reason"], "net_pnl": position["net_pnl"],
                    "mfe": position["maximum_favorable_excursion"], "mae": position["maximum_adverse_excursion"],
                    "forward_from_execution": _forward(p, exit_execution["timestamp"], exit_execution["price"]),
                    "underlying_forward_from_close": _forward(p, exit_execution["timestamp"], bar.close)})
            enriched_positions = [{"symbol": symbol, "policy": policy, **x} for x in simple["positions"]]
            pooled_by_policy[policy].extend(enriched_positions)
            concentration["by_symbol_policy"][policy][symbol] = winner_concentration(enriched_positions)
            for position in sorted(simple["positions"], key=lambda x: x["net_pnl"])[:10]:
                advanced = simulate(p, policy=policy, anchor=position)["positions"][0]
                losses.append({"symbol": symbol, "policy": policy, **position,
                    "market_context": _entry_features(p, position["entry_date"]),
                    "advanced_same_entry_net_pnl": advanced["net_pnl"],
                    "advanced_loss_avoided": advanced["net_pnl"] - position["net_pnl"],
                    "advanced_exit_reason": advanced["exit_final_close_reason"]})
            ae = {x["timestamp"][:10]: x["strategy"] for x in bundle["advanced"]["equity"]}
            for episode in drawdown_episodes(simple["equity"]):
                av = ae[episode["trough"]] / ae[episode["start"]] - 1
                episodes.append({"symbol": symbol, "policy": policy, **episode,
                    "advanced_same_calendar_return": av,
                    "advanced_loss_avoided_pp": 100 * (av - episode["depth"])})
        worst_trades[policy] = sorted(losses, key=lambda x: x["net_pnl"])[:10]
        worst_drawdowns[policy] = sorted(episodes, key=lambda x: x["depth"])[:10]
        concentration["by_symbol_policy"][policy] = concentration["by_symbol_policy"][policy]
    for policy in POLICIES:
        pooled = winner_concentration(pooled_by_policy[policy])
        dropped = []
        for symbol in SYMBOLS:
            group = [p for p in pooled_by_policy[policy] if p["symbol"] == symbol]
            if group:
                dropped.append(max(group, key=lambda p: p["net_pnl"]))
        pooled["remove_each_symbol_largest_winner_net_pnl"] = math.fsum(p["net_pnl"] for p in pooled_by_policy[policy]) - math.fsum(max((p for p in pooled_by_policy[policy] if p["symbol"] == s), key=lambda p: p["net_pnl"])["net_pnl"] for s in SYMBOLS)
        pooled["without_nvda_meta_tsla_net_pnl"] = math.fsum(p["net_pnl"] for p in pooled_by_policy[policy] if p["symbol"] not in ("NVDA", "META", "TSLA"))
        concentration[f"pooled_{policy}"] = pooled
    exit_summary = {}
    for policy in POLICIES:
        exit_summary[policy] = {}
        for reason in sorted({r["exit_reason"] for r in exit_rows if r["policy"] == policy}):
            rows = [r for r in exit_rows if r["policy"] == policy and r["exit_reason"] == reason]
            exit_summary[policy][reason] = {"events": len(rows), "net_pnl": describe([r["net_pnl"] for r in rows]),
                "mfe": describe([r["mfe"] for r in rows]), "mae": describe([r["mae"] for r in rows]),
                "forward_from_close": {str(n): describe([r["underlying_forward_from_close"][str(n)] for r in rows]) for n in EXIT_FORWARD_HORIZONS}}

    # Deterministic cost stress; baseline rows are recomputed through the same
    # function for a direct audit trail rather than analytically adjusted.
    cost_results = {}
    for scenario, multiplier in COST_SCENARIOS.items():
        rows = []
        for symbol in SYMBOLS:
            req = base.model_copy(update={"ticker": symbol, "start_date": common_start, "end_date": common_end,
                "commission_pct": base.commission_pct * multiplier["commission_multiplier"],
                "slippage_pct": base.slippage_pct * multiplier["slippage_multiplier"]})
            p = Prepared(req, frames[symbol]); hold = buy_and_hold(p)
            for policy in POLICIES:
                simple, advanced = simulate(p, simple=True, policy=policy), simulate(p, policy=policy)
                sm, am, hm = map(metric_view, (simple, advanced, hold))
                for comparator, left in (("ADVANCED_V2", am), ("BUY_AND_HOLD", hm)):
                    rows.append({"symbol": symbol, "policy": policy, "comparator": comparator,
                                 "simple": sm, "comparator_metrics": left, "delta": metric_delta(left, sm)})
        cost_results[scenario] = {"multipliers": multiplier, "rows": rows,
            "breadth": {c: _distribution_by_policy([{"period": "FULL", **r} for r in rows], c) for c in ("ADVANCED_V2", "BUY_AND_HOLD")}}
        progress(f"Cost stress: {scenario}")

    # Cluster uncertainty uses unique six-month test cells (not expanding and
    # rolling duplicates).  Policy is always analysed separately.
    uncertainty = {c: {} for c in ("ADVANCED_V2", "BUY_AND_HOLD")}
    for comparator, key in (("ADVANCED_V2", "vs_advanced"), ("BUY_AND_HOLD", "vs_buy_hold")):
        for policy in POLICIES:
            rows = [{"symbol": r["symbol"], "entry_date": r["test_start"],
                     "delta_return_pp": r["test"][key]["return_pp"]}
                    for r in fold_rows if r["design"] == "expanding" and r["policy"] == policy]
            uncertainty[comparator][policy] = clustered_bootstrap(rows, "delta_return_pp")

    exposure_rows = []
    for symbol in SYMBOLS:
        for policy in POLICIES:
            bundle = full_results[symbol, policy]
            for name in ("simple", "advanced", "buy_hold", "entry_zone_hold"):
                metrics = metric_view(bundle[name])
                exposure_rows.append({"symbol": symbol, "policy": policy if name in ("simple", "advanced") else None,
                                      "strategy": name.upper(), "metrics": metrics,
                                      "normalized": exposure_normalized(metrics)})

    decision = _classification(full_breadth, cross_period, fold_breadth, ambiguity, cost_results, uncertainty, concentration)
    after = immutable_fingerprints()
    assert before == after
    sources = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT / "research").glob("*.py")}
    compact_manifest = [{k: row.get(k) for k in ("symbol", "status", "provider", "adjustment_mode", "first_date", "last_date", "bars", "period_bars", "warmup_bars", "ohlcv_sha256", "actual_adjustment_contract")} for row in manifest["symbols"]]
    report = {
        "schema_version": 1, "study": "Simple v2 Strategy Viability Gate", "research_only": True,
        "retrospective_not_true_oos": True, "optimization_performed": False,
        "production_strategy_created": False, "production_strategies_modified": False,
        "freeze": {"strategies": STRATEGY_FREEZE, "benchmarks": BENCHMARKS,
                   "comparison_labels": COMPARISON_LABELS, "viability_gate": VIABILITY_GATE,
                   "wf_train_gate": WF_TRAIN_GATE, "statistics": STATISTICS,
                   "canonical_parameters": frozen["advanced"]["request"],
                   "production_source_sha256": before["production_source"]},
        "canonical": {name: {"backtest_id": item["id"], "strategy_version": item["result"]["strategy_version"],
            "request": item["request"], "summary": item["result"]["summary"],
            "data_coverage": item["result"]["data_coverage"], "reproducibility": item["result"]["reproducibility"],
            "result_sha256": item["result_sha256"]} for name, item in frozen.items()},
        "validation": {"canonical": canonical, "common_start": str(common_start), "common_end": str(common_end),
            "calendar_checks": calendar_checks, "data_manifest": compact_manifest},
        "portfolio": portfolio, "comparisons": comparisons, "full_period_breadth": full_breadth,
        "cross_period": cross_period, "walk_forward": {"folds": [asdict(x) if hasattr(x, "__dataclass_fields__") else {k: str(v) if isinstance(v, date) else v for k, v in x.items()} for x in walk_forward_folds()],
            "train_gates": train_gates, "fold_breadth": fold_breadth, "stitched": stitched},
        "entry_zone": {"summary": entry_summary,
            "data_file": "data/simple-v2-entry-zone-forward-returns.json"},
        "ambiguity": ambiguity, "ambiguity_cost_rows": ambiguity_cost_rows,
        "ambiguity_free_matched_rows": clean_rows,
        "simple_exit_attribution": {"summary": exit_summary, "rows": exit_rows},
        "winner_concentration": concentration,
        "tail_risk": {"worst_trades": worst_trades, "worst_drawdown_episodes": worst_drawdowns},
        "cost_robustness": cost_results, "statistical_uncertainty": uncertainty,
        "exposure_normalized": exposure_rows, "decision": decision,
        "entry_zone_data_sha256": None, "walk_forward_file": "data/simple-v2-walk-forward-folds.json",
        "walk_forward_sha256": None,
        "immutability": {"before": before, "after": after, "unchanged": True,
            "production_executions_changed": 0, "production_pnl_changed": 0, "production_equity_changed": 0,
            "history_changed": 0, "audits_changed": 0},
        "research_source_sha256": sources, "runtime_seconds": time.perf_counter() - started,
    }
    entry_data = {"schema_version": 1, "study": report["study"], "research_only": True,
                  "horizons": list(FORWARD_HORIZONS), "definitions": BENCHMARKS["ENTRY_ZONE_HOLD"],
                  "summary": entry_summary, "rows": signal_rows}
    columns = list(fold_rows[0])
    fold_data = {"schema_version": 1, "study": report["study"], "definitions": {"folds": report["walk_forward"]["folds"], "gate": WF_TRAIN_GATE},
                 "columns": columns, "rows": [[r[c] for c in columns] for r in fold_rows]}
    report["entry_zone_data_sha256"] = digest(entry_data)
    report["walk_forward_sha256"] = digest(fold_data)
    return report, entry_data, fold_data
