"""Offline Benchmark Viability Study for the frozen Framework v2 suite."""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from app.backtest.models import BacktestRequest
from research import ROOT
from research.baseline import immutable_fingerprints, load, normalize_timestamps, digest
from research.benchmark_viability_design import (
    COST_SCENARIOS, DATA_END, DATA_START, GRADING, POLICIES, REGIME,
    SYMBOLS, WALK_FORWARD_TESTS,
)
from research.framework_benchmarks import donchian_20_10, sma200_trend
from research.framework_freeze import semantic_production_source
from research.structural_data import load_inputs
from research.viability_benchmarks import buy_and_hold, metric_delta, metric_view
from research.viability_statistics import clustered_bootstrap, describe, winner_concentration


@dataclass
class WindowPrepared:
    request: BacktestRequest
    enriched: pd.DataFrame
    period: pd.DataFrame


def _prepared(base: BacktestRequest, frame: pd.DataFrame, symbol: str, start: date, end: date,
              commission_multiplier=1.0, slippage_multiplier=1.0) -> WindowPrepared:
    period = frame.loc[[start <= ts.date() <= end for ts in frame.index]].copy()
    if len(period) < 2:
        raise ValueError(f"Insufficient evaluation sessions for {symbol}: {start}..{end}")
    request = base.model_copy(update={
        "ticker": symbol, "start_date": period.index[0].date(), "end_date": period.index[-1].date(),
        "commission_pct": base.commission_pct * commission_multiplier,
        "slippage_pct": base.slippage_pct * slippage_multiplier,
    })
    return WindowPrepared(request, frame, period)


def _run(prepared: WindowPrepared, benchmark: str, policy="conservative") -> dict:
    if benchmark == "BUY_AND_HOLD":
        return buy_and_hold(prepared)
    if benchmark == "SMA200_TREND":
        return sma200_trend(prepared)
    if benchmark == "DONCHIAN_20_10":
        return donchian_20_10(prepared, policy)
    raise ValueError(benchmark)


def _metrics(result: dict) -> dict:
    value = metric_view(result)
    value["number_of_trades"] = value["number_of_positions"]
    return value


def _classification(delta: dict) -> str:
    ret, mdd, sharpe, calmar = delta["return_pp"], delta["mdd_pp"], delta["sharpe"], delta["calmar"]
    if sharpe is not None and calmar is not None and sharpe > 0 and calmar > 0 and mdd >= 0:
        return "RISK_ADJUSTED_WIN"
    if ret > 0:
        return "RETURN_WIN"
    if mdd > 0:
        return "DRAWDOWN_WIN"
    if (sharpe is not None and sharpe > 0) or (calmar is not None and calmar > 0):
        return "MIXED"
    return "LOSS"


def _comparison(benchmark_result: dict, hold_result: dict) -> dict:
    left, right = metric_view(hold_result), metric_view(benchmark_result)
    delta = metric_delta(left, right)
    return {"delta": delta, "classification": _classification(delta)}


def _regime(frame: pd.DataFrame, start: date, end: date) -> dict:
    sample = frame.loc[[start <= ts.date() <= end for ts in frame.index]]
    ret = float(sample.close.iloc[-1] / sample.close.iloc[0] - 1)
    vol = float(sample.close.pct_change().dropna().std(ddof=0) * np.sqrt(252))
    trend = "STRONG_UPTREND" if ret > .05 else "DOWNTREND" if ret < -.05 else "SIDEWAYS"
    volatility = "HIGH_VOLATILITY" if vol >= .25 else "LOW_VOLATILITY" if vol < .15 else "MEDIUM_VOLATILITY"
    return {"trend": trend, "volatility": volatility, "spy_return": ret, "spy_annualized_volatility": vol}


def _window_rows(base, frames, start, end, *, scope, name, policies=POLICIES, costs=(1.0, 1.0)):
    rows, raw = [], {}
    for symbol in SYMBOLS:
        p = _prepared(base, frames[symbol], symbol, start, end, *costs)
        hold = _run(p, "BUY_AND_HOLD")
        raw[symbol, "BUY_AND_HOLD", None] = hold
        rows.append({"scope": scope, "window": name, "symbol": symbol, "benchmark": "BUY_AND_HOLD", "policy": None,
                     "start": p.period.index[0].date().isoformat(), "end": p.period.index[-1].date().isoformat(), "metrics": _metrics(hold)})
        sma_results = []
        for policy in policies:
            sma = _run(p, "SMA200_TREND", policy)
            sma_results.append(sma)
            raw[symbol, "SMA200_TREND", policy] = sma
            rows.append({"scope": scope, "window": name, "symbol": symbol, "benchmark": "SMA200_TREND", "policy": policy,
                         "start": p.period.index[0].date().isoformat(), "end": p.period.index[-1].date().isoformat(),
                         "metrics": _metrics(sma), "vs_buy_hold": _comparison(sma, hold)})
        first = digest(normalize_timestamps({k: sma_results[0][k] for k in ("executions", "equity", "summary")}))
        assert all(digest(normalize_timestamps({k: x[k] for k in ("executions", "equity", "summary")})) == first for x in sma_results)
        for policy in policies:
            don = _run(p, "DONCHIAN_20_10", policy)
            raw[symbol, "DONCHIAN_20_10", policy] = don
            rows.append({"scope": scope, "window": name, "symbol": symbol, "benchmark": "DONCHIAN_20_10", "policy": policy,
                         "start": p.period.index[0].date().isoformat(), "end": p.period.index[-1].date().isoformat(),
                         "metrics": _metrics(don), "vs_buy_hold": _comparison(don, hold),
                         "ambiguous_days": len(don["ambiguous_days"]),
                         "ambiguous_trades": len(set(don["ambiguous_days"]))})
    return rows, raw


def _breadth(rows: list[dict]) -> dict:
    output = {}
    for benchmark in ("SMA200_TREND", "DONCHIAN_20_10"):
        output[benchmark] = {}
        for policy in POLICIES:
            group = [r for r in rows if r["benchmark"] == benchmark and r["policy"] == policy]
            output[benchmark][policy] = {
                "cells": len(group),
                "return_wins": sum(r["vs_buy_hold"]["delta"]["return_pp"] > 0 for r in group),
                "sharpe_wins": sum((r["vs_buy_hold"]["delta"]["sharpe"] or -999) > 0 for r in group),
                "mdd_wins": sum(r["vs_buy_hold"]["delta"]["mdd_pp"] > 0 for r in group),
                "median_return_delta_pp": float(np.median([r["vs_buy_hold"]["delta"]["return_pp"] for r in group])),
                "median_sharpe_delta": float(np.median([r["vs_buy_hold"]["delta"]["sharpe"] for r in group if r["vs_buy_hold"]["delta"]["sharpe"] is not None])),
                "median_mdd_delta_pp": float(np.median([r["vs_buy_hold"]["delta"]["mdd_pp"] for r in group])),
                "classifications": {name: sum(r["vs_buy_hold"]["classification"] == name for r in group)
                                    for name in ("RETURN_WIN", "RISK_ADJUSTED_WIN", "DRAWDOWN_WIN", "MIXED", "LOSS")},
            }
    return output


def _monthly_windows(evaluation_start: date, end: date, months: int):
    starts = [pd.Timestamp(evaluation_start)]
    cursor = (pd.Timestamp(evaluation_start) + pd.offsets.MonthBegin(1)).normalize()
    while cursor.date() <= end:
        starts.append(cursor); cursor += pd.offsets.MonthBegin(1)
    rows = []
    for start in starts:
        finish = start + pd.DateOffset(months=months) - pd.Timedelta(days=1)
        if finish.date() <= end:
            rows.append((start.date(), finish.date()))
    return rows


def _position_details(result: dict, period: pd.DataFrame):
    positions, executions = result["positions"], result["executions"]
    date_locations = {ts.date().isoformat(): i for i, ts in enumerate(period.index)}
    details = []
    cursor = 0
    for position in positions:
        chunk = []
        while cursor < len(executions):
            execution = executions[cursor]; cursor += 1; chunk.append(execution)
            if execution["side"] == "SELL" and execution["position_remaining"] == 0:
                break
        start, end = position["entry_date"][:10], position["final_exit_date"][:10]
        sessions = date_locations[end] - date_locations[start] if start in date_locations and end in date_locations else None
        details.append({**position, "holding_sessions": sessions,
                        "commission": math.fsum(x["commission"] for x in chunk),
                        "slippage_cost": math.fsum(x["slippage"] for x in chunk)})
    return details


def _concentration_and_whipsaw(full_raw, full_rows, frames, evaluation_start):
    concentration, whipsaw = {}, {}
    for benchmark in ("SMA200_TREND", "DONCHIAN_20_10"):
        concentration[benchmark], whipsaw[benchmark] = {}, {}
        for policy in POLICIES:
            pooled, by_symbol = [], {}
            for symbol in SYMBOLS:
                result = full_raw[symbol, benchmark, policy]
                # Real exchange dates preserve holidays and avoid DST mixed-
                # offset parsing from serialized timestamps.
                frame = frames[symbol].loc[[evaluation_start <= ts.date() <= DATA_END for ts in frames[symbol].index]]
                details = _position_details(result, frame)
                by_symbol[symbol] = details
                pooled.extend({"symbol": symbol, **p} for p in details)
            conc = winner_concentration(pooled)
            positive = sorted([p for p in pooled if p["net_pnl"] > 0], key=lambda x: x["net_pnl"], reverse=True)
            top10pct = max(1, math.ceil(len(positive) * .1)) if positive else 0
            top_share = math.fsum(x["net_pnl"] for x in positive[:top10pct]) / math.fsum(x["net_pnl"] for x in positive) if positive else None
            remove_by_symbol = math.fsum(math.fsum(x["net_pnl"] for x in rows) - (max((x["net_pnl"] for x in rows if x["net_pnl"] > 0), default=0)) for rows in by_symbol.values())
            concentration[benchmark][policy] = {**conc, "top_10pct_winner_share": top_share,
                "remove_largest_winner_per_symbol_net_pnl": remove_by_symbol,
                "winner_concentrated": bool((top_share is not None and top_share >= .70) or remove_by_symbol <= 0)}
            losses = abs(math.fsum(p["net_pnl"] for p in pooled if p["net_pnl"] < 0))
            whipsaw[benchmark][policy] = {}
            for horizon in (5, 10, 20):
                group = [p for p in pooled if p["holding_sessions"] is not None and p["holding_sessions"] <= horizon]
                loss = abs(math.fsum(p["net_pnl"] for p in group if p["net_pnl"] < 0))
                whipsaw[benchmark][policy][f"le_{horizon}d"] = {
                    "count": len(group), "net_pnl": math.fsum(p["net_pnl"] for p in group),
                    "commission": math.fsum(p["commission"] for p in group),
                    "slippage_cost": math.fsum(p["slippage_cost"] for p in group),
                    "share_of_total_loss": loss / losses if losses else None,
                }
    return concentration, whipsaw


def _tail_protection(full_raw):
    rows = []
    for symbol in SYMBOLS:
        hold = full_raw[symbol, "BUY_AND_HOLD", None]
        start, bottom, recovery = (hold["summary"][k] for k in ("max_drawdown_start", "max_drawdown_bottom", "recovery_date"))
        bh_equity = {x["timestamp"][:10]: x["strategy"] for x in hold["equity"]}
        for benchmark in ("SMA200_TREND", "DONCHIAN_20_10"):
            for policy in POLICIES:
                result = full_raw[symbol, benchmark, policy]
                equity = {x["timestamp"][:10]: x["strategy"] for x in result["equity"]}
                dates = sorted(d for d in equity if start <= d <= bottom)
                values = pd.Series([equity[d] for d in dates])
                episode_mdd = float((values / values.cummax() - 1).min()) if len(values) else None
                capital_loss = equity[bottom] / equity[start] - 1 if start in equity and bottom in equity else None
                missed = None
                if recovery and bottom in equity and recovery in equity and bottom in bh_equity and recovery in bh_equity:
                    missed = (equity[recovery] / equity[bottom] - 1) - (bh_equity[recovery] / bh_equity[bottom] - 1)
                rows.append({"symbol": symbol, "benchmark": benchmark, "policy": policy,
                    "buy_hold_drawdown_start": start, "buy_hold_bottom": bottom, "buy_hold_recovery": recovery,
                    "buy_hold_mdd": hold["summary"]["max_drawdown"], "benchmark_episode_mdd": episode_mdd,
                    "benchmark_capital_loss": capital_loss, "mdd_reduction_pp": 100 * (episode_mdd - hold["summary"]["max_drawdown"]),
                    "relative_upside_after_bottom_to_recovery": missed})
    return rows


def _uncertainty(rolling_rows):
    result = {}
    for benchmark in ("SMA200_TREND", "DONCHIAN_20_10"):
        result[benchmark] = {}
        for policy in POLICIES:
            group = [r for r in rolling_rows if r["horizon_months"] == 6 and r["benchmark"] == benchmark and r["policy"] == policy]
            effects = [{"symbol": r["symbol"], "start": r["start"],
                        "return_delta_pp": r["vs_buy_hold"]["delta"]["return_pp"],
                        "sharpe_delta": r["vs_buy_hold"]["delta"]["sharpe"],
                        "mdd_delta_pp": r["vs_buy_hold"]["delta"]["mdd_pp"]} for r in group]
            result[benchmark][policy] = {
                key: clustered_bootstrap(effects, key, date_key="start", reps=2000, seed=20260905+i)
                for i, key in enumerate(("return_delta_pp", "sharpe_delta", "mdd_delta_pp"))
            }
    return result


def _grade(full_breadth, rolling_breadth, wf_breadth, cost_breadth, uncertainty, concentration):
    grades = {}
    for benchmark in ("SMA200_TREND", "DONCHIAN_20_10"):
        supportive = []
        strong_policy = []
        for policy in POLICIES:
            full = full_breadth[benchmark][policy]
            roll = rolling_breadth[benchmark][policy]
            wf = wf_breadth[benchmark][policy]
            cost = cost_breadth["DOUBLE_BOTH"][benchmark][policy]
            ci = uncertainty[benchmark][policy]["return_delta_pp"]["mean_ci95"]
            concentrated = concentration[benchmark][policy]["winner_concentrated"]
            promising = ((full["return_wins"] >= 6 and full["median_return_delta_pp"] > 0) or
                          (full["sharpe_wins"] >= 6 and full["median_sharpe_delta"] > 0)) and \
                         roll["return_wins"] >= math.ceil(roll["cells"] / 2) and \
                         wf["return_wins"] >= math.ceil(wf["cells"] / 2) and cost["median_return_delta_pp"] >= 0
            strong = full["return_wins"] >= 7 and full["sharpe_wins"] >= 7 and full["mdd_wins"] >= 7 and \
                     roll["return_wins"] >= math.ceil(.6 * roll["cells"]) and wf["return_wins"] >= math.ceil(.6 * wf["cells"]) and \
                     cost["median_return_delta_pp"] > 0 and ci and ci[0] > 0 and not concentrated
            supportive.append(promising); strong_policy.append(strong)
        if sum(strong_policy) >= 2:
            label = "STRONG RETROSPECTIVE EVIDENCE"
        elif sum(supportive) >= 2:
            label = "PROMISING — FAMILY WORTH STUDYING"
        else:
            label = "NOT SUPPORTED"
        grades[benchmark] = {"grade": label, "supportive_policies": sum(supportive), "strong_policies": sum(strong_policy),
                             "policy_details": {p: {"promising": supportive[i], "strong": strong_policy[i]} for i, p in enumerate(POLICIES)}}
    trend, breakout = grades["SMA200_TREND"]["grade"], grades["DONCHIAN_20_10"]["grade"]
    rank = {"NOT SUPPORTED": 0, "PROMISING — FAMILY WORTH STUDYING": 1, "STRONG RETROSPECTIVE EVIDENCE": 2}
    next_family = "NONE" if max(rank[trend], rank[breakout]) == 0 else "TREND" if rank[trend] >= rank[breakout] else "BREAKOUT"
    return grades, next_family


def run():
    began = time.perf_counter()
    before = immutable_fingerprints()
    registry_path = ROOT / "data/research-candidate-registry.json"
    registry_sha = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    frozen, _ = load()
    manifest, frames = load_inputs()
    assert tuple(frames) == SYMBOLS
    calendars = [[timestamp.date() for timestamp in frame.index] for frame in frames.values()]
    assert all(calendar == calendars[0] for calendar in calendars)
    common = calendars[0]
    evaluation_start = common[200]
    base = frozen["advanced"]["request_object"].model_copy(update={"start_date": evaluation_start, "end_date": DATA_END})

    full_rows, full_raw = _window_rows(base, frames, evaluation_start, DATA_END, scope="FULL", name="FULL")
    full_breadth = _breadth(full_rows)

    calendar_rows = []
    for year in range(evaluation_start.year, DATA_END.year + 1):
        start, end = max(evaluation_start, date(year, 1, 1)), min(DATA_END, date(year, 12, 31))
        rows, _ = _window_rows(base, frames, start, end, scope="CALENDAR_YEAR", name=str(year))
        hold_map = {r["symbol"]: r["metrics"]["total_return"] for r in rows if r["benchmark"] == "BUY_AND_HOLD"}
        for row in rows:
            row["buy_hold_return"] = hold_map[row["symbol"]]
            row["partial_year"] = start != date(year, 1, 1) or end != date(year, 12, 31)
        calendar_rows.extend(rows)

    rolling_rows = []
    for months in (6, 12):
        for index, (start, end) in enumerate(_monthly_windows(evaluation_start, DATA_END, months), 1):
            rows, _ = _window_rows(base, frames, start, end, scope=f"ROLLING_{months}M", name=f"R{months}-{index:02d}")
            for row in rows:
                row["horizon_months"] = months
            rolling_rows.extend(rows)
    rolling_breadth = {benchmark: {policy: {} for policy in POLICIES} for benchmark in ("SMA200_TREND", "DONCHIAN_20_10")}
    for benchmark in rolling_breadth:
        for policy in POLICIES:
            group = [r for r in rolling_rows if r["horizon_months"] == 6 and r["benchmark"] == benchmark and r["policy"] == policy]
            rolling_breadth[benchmark][policy] = {
                "cells": len(group), "return_wins": sum(r["vs_buy_hold"]["delta"]["return_pp"] > 0 for r in group),
                "sharpe_wins": sum((r["vs_buy_hold"]["delta"]["sharpe"] or -999) > 0 for r in group),
                "mdd_wins": sum(r["vs_buy_hold"]["delta"]["mdd_pp"] > 0 for r in group),
            }

    fold_rows = []
    for design in ("expanding", "rolling"):
        for fold, test_start, test_end in WALK_FORWARD_TESTS:
            train_start = DATA_START if design == "expanding" else date(test_start.year - 2, test_start.month, 1)
            train_end = test_start - timedelta(days=1)
            rows, _ = _window_rows(base, frames, test_start, test_end, scope="RETROSPECTIVE_WALK_FORWARD", name=fold)
            regime = _regime(frames["SPY"], test_start, test_end)
            for row in rows:
                row.update({"design": design, "fold": fold, "train_start": train_start.isoformat(), "train_end": train_end.isoformat(),
                            "test_start": row.pop("start"), "test_end": row.pop("end"), "regime": regime})
            fold_rows.extend(rows)
    # Identical test windows deliberately produce identical expanding/rolling results.
    wf_breadth = {benchmark: {policy: {} for policy in POLICIES} for benchmark in ("SMA200_TREND", "DONCHIAN_20_10")}
    for benchmark in wf_breadth:
        for policy in POLICIES:
            group = [r for r in fold_rows if r["design"] == "expanding" and r["benchmark"] == benchmark and r["policy"] == policy]
            wf_breadth[benchmark][policy] = {
                "cells": len(group), "return_wins": sum(r["vs_buy_hold"]["delta"]["return_pp"] > 0 for r in group),
                "sharpe_wins": sum((r["vs_buy_hold"]["delta"]["sharpe"] or -999) > 0 for r in group),
                "mdd_wins": sum(r["vs_buy_hold"]["delta"]["mdd_pp"] > 0 for r in group),
            }

    cost_rows, cost_breadth = [], {}
    for scenario, multipliers in COST_SCENARIOS.items():
        rows, _ = _window_rows(base, frames, evaluation_start, DATA_END, scope="COST_STRESS", name=scenario, costs=multipliers)
        cost_rows.extend(rows); cost_breadth[scenario] = _breadth(rows)

    concentration, whipsaw = _concentration_and_whipsaw(full_raw, full_rows, frames, evaluation_start)
    tail = _tail_protection(full_raw)
    uncertainty = _uncertainty(rolling_rows)
    grades, next_family = _grade(full_breadth, rolling_breadth, wf_breadth, cost_breadth, uncertainty, concentration)

    policy_sensitivity = {}
    for symbol in SYMBOLS:
        rows = [r for r in full_rows if r["symbol"] == symbol and r["benchmark"] == "DONCHIAN_20_10"]
        policy_sensitivity[symbol] = {
            "return_range_pp": 100 * (max(r["metrics"]["total_return"] for r in rows) - min(r["metrics"]["total_return"] for r in rows)),
            "mdd_range_pp": 100 * (max(r["metrics"]["max_drawdown"] for r in rows) - min(r["metrics"]["max_drawdown"] for r in rows)),
            "sharpe_range": max(r["metrics"]["sharpe_ratio"] for r in rows) - min(r["metrics"]["sharpe_ratio"] for r in rows),
            "ambiguous_days_by_policy": {r["policy"]: r["ambiguous_days"] for r in rows},
        }

    compact_manifest = [{k: item[k] for k in ("symbol", "provider", "adjustment_mode", "first_date", "last_date", "bars", "ohlcv_sha256", "file_sha256")} for item in manifest["symbols"]]
    spec = ROOT / "research/specs/BENCHMARK_SUITE_V2.md"
    after = immutable_fingerprints()
    assert before == after
    assert registry_sha == hashlib.sha256(registry_path.read_bytes()).hexdigest()
    return {
        "schema_version": 2, "study": "BENCHMARK VIABILITY STUDY", "research_only": True,
        "candidate_created": False, "optimization_performed": False, "benchmark_parameters_changed": False,
        "benchmark_spec": {"path": "research/specs/BENCHMARK_SUITE_V2.md", "sha256": hashlib.sha256(spec.read_bytes()).hexdigest()},
        "data": {"data_start": DATA_START.isoformat(), "evaluation_start": evaluation_start.isoformat(), "evaluation_end": DATA_END.isoformat(),
                 "warmup_completed_bars": 200, "cash_return": 0.0, "datasets": compact_manifest},
        "full_period": full_rows, "full_breadth": full_breadth, "calendar_year": calendar_rows,
        "rolling_periods": rolling_rows, "rolling_breadth": rolling_breadth,
        "walk_forward_file": "data/benchmark-walk-forward-folds.json", "walk_forward_breadth": wf_breadth,
        "cost_stress": cost_rows, "cost_breadth": cost_breadth,
        "policy_sensitivity": {"sma200_all_policies_identical": True, "donchian": policy_sensitivity},
        "winner_concentration": concentration, "whipsaw": whipsaw, "tail_protection": tail,
        "cash_drag": {benchmark: {policy: describe([r["metrics"]["average_close_capital_exposure_pct"] for r in full_rows if r["benchmark"] == benchmark and r["policy"] == policy]) for policy in POLICIES} for benchmark in ("SMA200_TREND", "DONCHIAN_20_10")},
        "uncertainty": uncertainty, "regime_definition": REGIME, "grading_contract": GRADING,
        "grades": grades, "next_family": next_family,
        "immutability": {"before": before, "after": after, "unchanged": True,
                         "semantic_production_source": semantic_production_source(), "registry_sha256": registry_sha,
                         "executions_differences": 0, "pnl_differences": 0, "equity_differences": 0, "audits_differences": 0},
        "runtime_seconds": time.perf_counter() - began,
        "_fold_rows": fold_rows,
    }


def write_outputs(result: dict):
    folds = {"schema_version": 2, "study": "Retrospective Walk-Forward Robustness Validation",
             "true_out_of_sample": False, "rows": result.pop("_fold_rows")}
    fold_path = ROOT / "data/benchmark-walk-forward-folds.json"
    fold_path.write_text(json.dumps(folds, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    result["walk_forward_sha256"] = hashlib.sha256(fold_path.read_bytes()).hexdigest()
    (ROOT / "data/benchmark-viability-study.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
