"""Research-only, snapshot-bound long-history Environment v3 validation.

No network access, persistence API, production strategy mutation, candidate
creation, or parameter search occurs here. Every result is computed from one
immutable CURRENT_ENVIRONMENT_SNAPSHOT created by the Windows background job.
"""
from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from datetime import date
from typing import Any, Callable

import numpy as np
import pandas as pd

from app.backtest.metrics import calculate_metrics
from app.data.cache import ParquetCache
from research import ROOT
from research.baseline import immutable_fingerprints, load
from research.cash_models import RiskFreeCashModel
from research.environment_v3_data import sha256_file
from research.environment_v3_design import CRISIS_EPISODES, MARKET_CYCLE_WINDOWS, PRIMARY_HISTORY, UNIVERSES
from research.environment_v3_snapshot import (
    EnvironmentValidationError,
    assert_snapshot_immutable,
    assert_snapshot_inputs_unchanged,
)
from research.framework_benchmarks import donchian_20_10, sma200_trend
from research.simulation import Prepared, simulate
from research.viability_benchmarks import buy_and_hold, metric_delta, metric_view


POLICIES = ("conservative", "ohlc_heuristic", "favorable")
STRATEGIES = ("BUY_AND_HOLD", "SMA200_TREND", "DONCHIAN_20_10", "SIMPLE_V2", "ADVANCED_V2")
POLICY_STRATEGIES = {"DONCHIAN_20_10", "SIMPLE_V2", "ADVANCED_V2"}
BENCHMARKS = ("SMA200_TREND", "DONCHIAN_20_10")

# Declared before replacement results are calculated. Risk-free cash may reveal
# sensitivity, but cannot upgrade a benchmark family by itself.
RECLASSIFICATION_GATE = {
    "evidence_basis": "CASH_ZERO only; both frozen universes; full history plus six frozen market-cycle windows",
    "promising": "In at least two OHLC policies, both universes must show majority full-period Return or Sharpe breadth with a positive corresponding median, and at least half of cycle symbol-windows must support Return or Sharpe with a positive median.",
    "strong": "In at least two OHLC policies, both universes must reach 60% full-period Return, Sharpe and MDD breadth plus 60% cycle Return and Sharpe breadth, with positive medians.",
    "not_supported": "Every other result.",
    "cash_rule": "CASH_RISK_FREE is a sensitivity cell only and cannot upgrade a grade.",
}


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _selected_frame(row: dict[str, Any]) -> pd.DataFrame:
    candidates = [
        variant for variant in row["variants"]
        if variant.get("provider") == "yahoo"
        and variant.get("adjustment_mode") == "adjusted_for_splits"
        and variant.get("validation", {}).get("status") == "PASS"
        and variant.get("ohlcv_sha256") == row.get("ohlcv_sha256")
    ]
    if not candidates:
        raise EnvironmentValidationError(f"No admissible snapshot dataset for {row['ticker']}")
    variant = max(candidates, key=lambda item: item.get("bars", 0))
    frames = []
    for fragment in variant["fragments"]:
        path = ROOT / fragment["path"]
        if not path.is_file() or sha256_file(path) != fragment["sha256"]:
            raise EnvironmentValidationError(f"Snapshot market file changed: {row['ticker']}")
        sidecar_value = fragment.get("metadata_sidecar")
        if sidecar_value:
            sidecar = ROOT / sidecar_value
            if not sidecar.is_file() or sha256_file(sidecar) != fragment.get("metadata_sidecar_sha256"):
                raise EnvironmentValidationError(f"Snapshot sidecar changed: {row['ticker']}")
        frames.append(pd.read_parquet(path))
    frame = ParquetCache._merge_frames(frames, timeframe="1d")
    return frame.loc[
        [PRIMARY_HISTORY["start"] <= timestamp.date() <= PRIMARY_HISTORY["end"] for timestamp in frame.index]
    ]


def _load_rate_model(snapshot: dict[str, Any]) -> RiskFreeCashModel:
    rate = snapshot["risk_free"]
    if not rate.get("ready"):
        raise EnvironmentValidationError("The snapshot does not contain validated DGS3MO data")
    manifest = ROOT / rate["manifest_path"]
    cache = ROOT / rate["cache_file"]
    if sha256_file(manifest) != rate["manifest_sha256"] or sha256_file(cache) != rate["cache_sha256"]:
        raise EnvironmentValidationError("Risk-free input differs from the environment snapshot")
    frame = pd.read_parquet(cache)
    return RiskFreeCashModel(frame["annual_yield_pct"])


def _risk_free_replay(result: dict[str, Any], prepared: Prepared, model: RiskFreeCashModel) -> dict[str, Any]:
    """Keep executions fixed and accrue ACT/365 interest to cash only."""
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for execution in result["executions"]:
        by_date[execution["timestamp"][:10]].append(execution)
    cash = float(prepared.request.initial_capital)
    quantity = 0
    previous: date | None = None
    equity_values: list[float] = []
    equity_rows: list[dict[str, Any]] = []
    capital_exposure: list[float] = []
    cash_yield = 0.0
    for timestamp, row in prepared.period.iterrows():
        current = timestamp.date()
        if previous is not None:
            accrual = model.accrue(cash, previous, current)
            cash = accrual.closing_cash
            cash_yield += accrual.interest
        for execution in by_date.get(current.isoformat(), []):
            if execution["side"] == "BUY":
                cash -= float(execution["gross_value"]) + float(execution["commission"])
            else:
                cash += float(execution["gross_value"]) - float(execution["commission"])
            quantity = int(execution["position_remaining"])
        equity = cash + quantity * float(row.close)
        equity_values.append(equity)
        equity_rows.append({"timestamp": timestamp.isoformat(), "strategy": equity})
        capital_exposure.append(quantity * float(row.close) / equity if equity else 0.0)
        previous = current
    equity = pd.Series(equity_values, index=prepared.period.index)
    raw_hold = prepared.request.initial_capital * prepared.period.close / prepared.period.close.iloc[0]
    exposure_days = int(round(float(result["summary"]["exposure_pct"]) / 100 * len(equity)))
    summary, _drawdown = calculate_metrics(
        equity, raw_hold, result["positions"], prepared.request.initial_capital,
        exposure_days, len(equity), result["summary"]["total_commission"],
        result["summary"]["estimated_slippage_cost"],
        result["summary"]["number_of_sell_executions"],
    )
    exposure = dict(result["exposure"])
    exposure["average_close_capital_exposure_pct"] = float(np.mean(capital_exposure)) * 100
    exposure["average_close_cash_pct"] = (1 - float(np.mean(capital_exposure))) * 100
    metrics = metric_view({"summary": summary, "exposure": exposure})
    metrics.update({
        "cash_yield_contribution_usd": cash_yield,
        "cash_yield_return_contribution_pp": 100 * (
            float(summary["total_return"]) - float(result["summary"]["total_return"])
        ),
        "fixed_execution_replay": True,
    })
    return {"metrics": metrics, "equity": equity_rows, "executions": result["executions"]}


def _suite(prepared: Prepared) -> dict[tuple[str, str | None], dict[str, Any]]:
    results: dict[tuple[str, str | None], dict[str, Any]] = {
        ("BUY_AND_HOLD", None): buy_and_hold(prepared),
        ("SMA200_TREND", None): sma200_trend(prepared),
    }
    for policy in POLICIES:
        results[("DONCHIAN_20_10", policy)] = donchian_20_10(prepared, policy)
        results[("SIMPLE_V2", policy)] = simulate(prepared, simple=True, policy=policy)
        results[("ADVANCED_V2", policy)] = simulate(prepared, policy=policy)
    return results


def _memberships(ticker: str) -> list[str]:
    return [name for name, contract in UNIVERSES.items() if ticker in contract["symbols"]]


def _prepared_for_window(base, ticker: str, frame: pd.DataFrame, start: date, end: date,
                         *, commission_multiplier: float = 1.0, slippage_multiplier: float = 1.0) -> Prepared | None:
    if len(frame) <= 200:
        return None
    eligible = frame.index[200].date()
    actual_start = max(start, eligible)
    actual_end = min(end, frame.index[-1].date())
    available = frame.loc[[actual_start <= timestamp.date() <= actual_end for timestamp in frame.index]]
    if len(available) < 2:
        return None
    request = base.model_copy(update={
        "ticker": ticker,
        "start_date": available.index[0].date(),
        "end_date": available.index[-1].date(),
        "commission_pct": base.commission_pct * commission_multiplier,
        "slippage_pct": base.slippage_pct * slippage_multiplier,
    })
    return Prepared(request, frame)


def _classification(delta: dict[str, Any]) -> str:
    ret, mdd = delta["return_pp"], delta["mdd_pp"]
    sharpe, calmar = delta["sharpe"], delta["calmar"]
    if sharpe is not None and calmar is not None and sharpe > 0 and calmar > 0 and mdd >= 0:
        return "RISK_ADJUSTED_WIN"
    if ret > 0:
        return "RETURN_WIN"
    if mdd > 0:
        return "DRAWDOWN_WIN"
    if (sharpe is not None and sharpe > 0) or (calmar is not None and calmar > 0):
        return "MIXED"
    return "LOSS"


def _window_rows(
    base, ticker: str, frame: pd.DataFrame, start: date, end: date,
    scope: str, window: str, rate_model: RiskFreeCashModel, *, keep_models: bool = False,
    commission_multiplier: float = 1.0, slippage_multiplier: float = 1.0,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str | None, str], dict[str, Any]], Prepared | None]:
    prepared = _prepared_for_window(
        base, ticker, frame, start, end,
        commission_multiplier=commission_multiplier, slippage_multiplier=slippage_multiplier,
    )
    if prepared is None:
        return [], {}, None
    suite = _suite(prepared)
    models: dict[tuple[str, str | None, str], dict[str, Any]] = {}
    metric_models: dict[tuple[str, str | None, str], dict[str, Any]] = {}
    for (strategy, policy), result in suite.items():
        zero_metrics = metric_view(result)
        zero_metrics.update({
            "cash_yield_contribution_usd": 0.0,
            "cash_yield_return_contribution_pp": 0.0,
            "fixed_execution_replay": True,
        })
        risk_free = _risk_free_replay(result, prepared, rate_model)
        metric_models[(strategy, policy, "CASH_ZERO")] = zero_metrics
        metric_models[(strategy, policy, "CASH_RISK_FREE")] = risk_free["metrics"]
        if keep_models:
            models[(strategy, policy, "CASH_ZERO")] = {
                "equity": result["equity"], "executions": result["executions"],
                "positions": result["positions"], "metrics": zero_metrics,
            }
            models[(strategy, policy, "CASH_RISK_FREE")] = {
                "equity": risk_free["equity"], "executions": risk_free["executions"],
                "positions": result["positions"], "metrics": risk_free["metrics"],
            }
    rows: list[dict[str, Any]] = []
    for universe in _memberships(ticker):
        for (strategy, policy, cash_model), metrics in metric_models.items():
            row = {
                "scope": scope, "window": window, "universe": universe,
                "symbol": ticker, "strategy": strategy, "policy": policy,
                "cash_model": cash_model,
                "start": prepared.period.index[0].date().isoformat(),
                "end": prepared.period.index[-1].date().isoformat(),
                "sessions": int(len(prepared.period)), "metrics": metrics,
            }
            if strategy != "BUY_AND_HOLD":
                hold = metric_models[("BUY_AND_HOLD", None, cash_model)]
                delta = metric_delta(hold, metrics)
                row["vs_buy_and_hold"] = {"delta": delta, "classification": _classification(delta)}
            rows.append(row)
    return rows, models, prepared


def _median(values: list[Any]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return float(np.median(clean)) if clean else None


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for universe in UNIVERSES:
        output[universe] = {}
        for cash_model in ("CASH_ZERO", "CASH_RISK_FREE"):
            output[universe][cash_model] = {}
            for strategy in STRATEGIES:
                policy = "conservative" if strategy in POLICY_STRATEGIES else None
                group = [
                    row for row in rows
                    if row["universe"] == universe and row["cash_model"] == cash_model
                    and row["strategy"] == strategy and row["policy"] == policy
                ]
                output[universe][cash_model][strategy] = {
                    "symbols": len(group),
                    "median_total_return": _median([row["metrics"]["total_return"] for row in group]),
                    "median_max_drawdown": _median([row["metrics"]["max_drawdown"] for row in group]),
                    "median_sharpe": _median([row["metrics"]["sharpe_ratio"] for row in group]),
                    "median_exposure": _median([row["metrics"]["average_close_capital_exposure_pct"] for row in group]),
                    "median_cash_yield_usd": _median([row["metrics"]["cash_yield_contribution_usd"] for row in group]),
                    "median_cash_yield_return_pp": _median([row["metrics"]["cash_yield_return_contribution_pp"] for row in group]),
                }
    return output


def _breadth(rows: list[dict[str, Any]], universe: str, cash_model: str,
             benchmark: str, policy: str) -> dict[str, Any]:
    stored_policy = policy if benchmark == "DONCHIAN_20_10" else None
    group = [
        row for row in rows
        if row["universe"] == universe and row["cash_model"] == cash_model
        and row["strategy"] == benchmark and row["policy"] == stored_policy
    ]
    deltas = [row["vs_buy_and_hold"]["delta"] for row in group]
    return {
        "cells": len(group),
        "return_wins": sum(delta["return_pp"] > 0 for delta in deltas),
        "sharpe_wins": sum(delta["sharpe"] is not None and delta["sharpe"] > 0 for delta in deltas),
        "mdd_wins": sum(delta["mdd_pp"] > 0 for delta in deltas),
        "median_return_delta_pp": _median([delta["return_pp"] for delta in deltas]),
        "median_sharpe_delta": _median([delta["sharpe"] for delta in deltas]),
        "median_mdd_delta_pp": _median([delta["mdd_pp"] for delta in deltas]),
    }


def _grade(full_rows: list[dict[str, Any]], cycle_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    grades: dict[str, Any] = {}
    rank = {"NOT SUPPORTED": 0, "PROMISING — FAMILY WORTH STUDYING": 1, "STRONG RETROSPECTIVE EVIDENCE": 2}
    for benchmark in BENCHMARKS:
        details = {}
        supportive_count = 0
        strong_count = 0
        for policy in POLICIES:
            by_universe = {}
            for universe in UNIVERSES:
                full = _breadth(full_rows, universe, "CASH_ZERO", benchmark, policy)
                cycles = _breadth(cycle_rows, universe, "CASH_ZERO", benchmark, policy)
                majority_full = math.ceil(full["cells"] / 2) if full["cells"] else 10**9
                majority_cycles = math.ceil(cycles["cells"] / 2) if cycles["cells"] else 10**9
                sixty_full = math.ceil(.6 * full["cells"]) if full["cells"] else 10**9
                sixty_cycles = math.ceil(.6 * cycles["cells"]) if cycles["cells"] else 10**9
                full_support = (
                    full["return_wins"] >= majority_full and (full["median_return_delta_pp"] or 0) > 0
                ) or (
                    full["sharpe_wins"] >= majority_full and (full["median_sharpe_delta"] or 0) > 0
                )
                cycle_support = (
                    cycles["return_wins"] >= majority_cycles and (cycles["median_return_delta_pp"] or 0) > 0
                ) or (
                    cycles["sharpe_wins"] >= majority_cycles and (cycles["median_sharpe_delta"] or 0) > 0
                )
                supportive = full_support and cycle_support
                strong = (
                    full["return_wins"] >= sixty_full and full["sharpe_wins"] >= sixty_full
                    and full["mdd_wins"] >= sixty_full and cycles["return_wins"] >= sixty_cycles
                    and cycles["sharpe_wins"] >= sixty_cycles
                    and (full["median_return_delta_pp"] or 0) > 0
                    and (full["median_sharpe_delta"] or 0) > 0
                    and (cycles["median_return_delta_pp"] or 0) > 0
                    and (cycles["median_sharpe_delta"] or 0) > 0
                )
                by_universe[universe] = {
                    "full": full, "market_cycles": cycles,
                    "supportive": supportive, "strong": strong,
                }
            policy_supportive = all(value["supportive"] for value in by_universe.values())
            policy_strong = all(value["strong"] for value in by_universe.values())
            supportive_count += int(policy_supportive)
            strong_count += int(policy_strong)
            details[policy] = {"universes": by_universe, "supportive": policy_supportive, "strong": policy_strong}
        label = (
            "STRONG RETROSPECTIVE EVIDENCE" if strong_count >= 2
            else "PROMISING — FAMILY WORTH STUDYING" if supportive_count >= 2
            else "NOT SUPPORTED"
        )
        grades[benchmark] = {
            "grade": label, "supportive_policies": supportive_count,
            "strong_policies": strong_count, "policy_details": details,
        }
    next_family = (
        "NONE" if max(rank[grades[name]["grade"]] for name in BENCHMARKS) == 0
        else "TREND" if rank[grades["SMA200_TREND"]["grade"]] >= rank[grades["DONCHIAN_20_10"]["grade"]]
        else "BREAKOUT"
    )
    return grades, next_family


def _episode_stats(model: dict[str, Any], start: date, end: date) -> dict[str, Any] | None:
    rows = [row for row in model["equity"] if start.isoformat() <= row["timestamp"][:10] <= end.isoformat()]
    if len(rows) < 2:
        return None
    values = pd.Series([float(row["strategy"]) for row in rows], dtype=float)
    executions = [
        execution for execution in model["executions"]
        if start.isoformat() <= execution["timestamp"][:10] <= end.isoformat()
    ]
    entries = [execution["timestamp"][:10] for execution in executions if execution["side"] == "BUY"]
    exits = [execution["timestamp"][:10] for execution in executions if execution["side"] == "SELL" and execution["position_remaining"] == 0]
    first_exit = exits[0] if exits else None
    return {
        "start": rows[0]["timestamp"][:10], "end": rows[-1]["timestamp"][:10],
        "sessions": len(rows), "return": float(values.iloc[-1] / values.iloc[0] - 1),
        "max_drawdown": float((values / values.cummax() - 1).min()),
        "entries": len(entries), "full_exits": len(exits),
        "first_exit": first_exit,
        "first_reentry": next((entry for entry in entries if first_exit and entry > first_exit), None),
    }


def _crisis_rows(full_models: dict[tuple[str, str, str | None, str], dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for episode, start, end in CRISIS_EPISODES:
        for ticker in sorted({key[0] for key in full_models}):
            for cash_model in ("CASH_ZERO", "CASH_RISK_FREE"):
                hold = _episode_stats(full_models[(ticker, "BUY_AND_HOLD", None, cash_model)], start, end)
                if hold is None:
                    continue
                for strategy in STRATEGIES:
                    policies = POLICIES if strategy in POLICY_STRATEGIES else (None,)
                    for policy in policies:
                        stats = _episode_stats(full_models[(ticker, strategy, policy, cash_model)], start, end)
                        if stats is None:
                            continue
                        for universe in _memberships(ticker):
                            row = {
                                "episode": episode, "universe": universe, "symbol": ticker,
                                "cash_model": cash_model, "strategy": strategy, "policy": policy, **stats,
                            }
                            if strategy != "BUY_AND_HOLD":
                                row["vs_buy_and_hold"] = {
                                    "return_delta_pp": 100 * (stats["return"] - hold["return"]),
                                    "mdd_delta_pp": 100 * (stats["max_drawdown"] - hold["max_drawdown"]),
                                }
                            rows.append(row)
    return rows


def _aggregate_period(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    output = []
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["policy"] not in (None, "conservative"):
            continue
        groups[(row[key], row["universe"], row["cash_model"], row["strategy"])].append(row)
    for (window, universe, cash_model, strategy), group in sorted(groups.items()):
        output.append({
            key: window, "universe": universe, "cash_model": cash_model,
            "strategy": strategy, "symbols": len(group),
            "median_return": _median([row.get("return", row.get("metrics", {}).get("total_return")) for row in group]),
            "median_mdd": _median([row.get("max_drawdown", row.get("metrics", {}).get("max_drawdown")) for row in group]),
            "median_sharpe": _median([row.get("metrics", {}).get("sharpe_ratio") for row in group]),
        })
    return output


def _cash_attribution(full_rows: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for universe in UNIVERSES:
        output[universe] = {}
        for strategy in STRATEGIES:
            policy = "conservative" if strategy in POLICY_STRATEGIES else None
            group = [
                row for row in full_rows
                if row["universe"] == universe and row["cash_model"] == "CASH_RISK_FREE"
                and row["strategy"] == strategy and row["policy"] == policy
            ]
            output[universe][strategy] = {
                "symbols": len(group),
                "median_return_contribution_pp": _median([row["metrics"]["cash_yield_return_contribution_pp"] for row in group]),
                "median_cash_yield_usd": _median([row["metrics"]["cash_yield_contribution_usd"] for row in group]),
                "positive_symbols": sum(row["metrics"]["cash_yield_return_contribution_pp"] > 0 for row in group),
            }
    return output


def _sensitivity(full_rows: list[dict[str, Any]], summary: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str], str]:
    matrix = []
    for universe in UNIVERSES:
        for cash_model in ("CASH_ZERO", "CASH_RISK_FREE"):
            matrix.append({
                "universe": universe, "cash_model": cash_model,
                "short_history": "PRIOR_REFERENCE_ONLY" if universe == "MEGA_CAP_TECH_UNIVERSE" and cash_model == "CASH_ZERO" else "NOT_USED",
                "long_history": "EXECUTED",
                "symbols": summary[universe][cash_model]["BUY_AND_HOLD"]["symbols"],
                "strategies": {strategy: summary[universe][cash_model][strategy] for strategy in STRATEGIES},
            })
    labels: dict[str, str] = {}
    for strategy in STRATEGIES[1:]:
        return_signs, sharpe_signs = [], []
        for cell in matrix:
            value, hold = cell["strategies"][strategy], cell["strategies"]["BUY_AND_HOLD"]
            return_delta = (value["median_total_return"] or 0) - (hold["median_total_return"] or 0)
            sharpe_delta = (value["median_sharpe"] or 0) - (hold["median_sharpe"] or 0)
            return_signs.append(1 if return_delta > 0 else -1 if return_delta < 0 else 0)
            sharpe_signs.append(1 if sharpe_delta > 0 else -1 if sharpe_delta < 0 else 0)
        if len(set(return_signs)) == 1 and len(set(sharpe_signs)) == 1:
            labels[strategy] = "ROBUST"
        elif len(set(return_signs)) > 1:
            labels[strategy] = "ENVIRONMENT-SENSITIVE"
        else:
            labels[strategy] = "MIXED"
    benchmark_labels = [labels[name] for name in BENCHMARKS]
    overall = (
        "ENVIRONMENT-SENSITIVE" if "ENVIRONMENT-SENSITIVE" in benchmark_labels
        else "ROBUST" if all(label == "ROBUST" for label in benchmark_labels)
        else "MIXED"
    )
    return matrix, labels, overall


def _render(study: dict[str, Any]) -> str:
    snapshot = study["environment_snapshot"]
    lines = [
        "# Research Environment v3 — Long-History Extension", "",
        "> Retrospective research only. Production strategies, frozen benchmarks, candidate registry, executions, historical backtests and audits were not modified.", "",
        "## Current environment snapshot", "",
        f"- Snapshot ID: `{snapshot['environment_snapshot_id']}`",
        f"- Created: `{snapshot['created_at']}`",
        f"- Input fingerprint: `{snapshot['input_fingerprint_sha256']}`",
        "- Market / mega-cap / ETF / DGS3MO readiness: **true / true / true / true**", "",
        "Each symbol starts after its own 200 completed warm-up bars. META and XLRE do not shorten every other symbol's history; universe composition is reported per period.", "",
        "## Full-history medians", "",
        "| Universe | Cash | Strategy | Symbols | Return | MDD | Sharpe | Exposure |", "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for universe, cash_models in study["summary"].items():
        for cash_model, strategies in cash_models.items():
            for strategy, value in strategies.items():
                fmt_pct = lambda number: "—" if number is None else f"{number * 100:.2f}%"
                fmt = lambda number: "—" if number is None else f"{number:.3f}"
                lines.append(
                    f"| {universe} | {cash_model} | {strategy} | {value['symbols']} | "
                    f"{fmt_pct(value['median_total_return'])} | {fmt_pct(value['median_max_drawdown'])} | "
                    f"{fmt(value['median_sharpe'])} | {fmt(value['median_exposure'])}% |"
                )
    lines += ["", "## Cash-yield attribution", "", "| Universe | Strategy | Symbols | Median Return contribution | Median cash yield |", "|---|---|---:|---:|---:|"]
    for universe, strategies in study["cash_yield_attribution"].items():
        for strategy, value in strategies.items():
            lines.append(
                f"| {universe} | {strategy} | {value['symbols']} | "
                f"{value['median_return_contribution_pp']:.3f} pp | ${value['median_cash_yield_usd']:,.2f} |"
            )
    lines += ["", "## Frozen benchmark reclassification", ""]
    for benchmark, value in study["benchmark_reclassification"].items():
        lines.append(f"- **{benchmark}: {value['grade']}** ({value['supportive_policies']}/3 supportive policies).")
    lines += [
        "", f"Environment sensitivity: **{study['sensitivity_classification']}**.",
        f"NEXT FAMILY = **{study['next_family']}**. No candidate was created.", "",
        "## Fixed market-cycle windows", "",
        "| Window | Universe | Cash | Strategy | Symbols | Median Return | Median MDD |", "|---|---|---|---|---:|---:|---:|",
    ]
    for row in study["market_cycle_summary"]:
        lines.append(
            f"| {row['window']} | {row['universe']} | {row['cash_model']} | {row['strategy']} | "
            f"{row['symbols']} | {row['median_return'] * 100:.2f}% | {row['median_mdd'] * 100:.2f}% |"
        )
    lines += [
        "", "## Fixed crisis episodes", "",
        "The machine-readable output includes per-symbol exit/re-entry dates, Return and MDD for every frozen strategy, universe and cash model.", "",
        "| Episode | Universe | Cash | Strategy | Symbols | Median Return | Median MDD |", "|---|---|---|---|---:|---:|---:|",
    ]
    for row in study["crisis_summary"]:
        lines.append(
            f"| {row['episode']} | {row['universe']} | {row['cash_model']} | {row['strategy']} | "
            f"{row['symbols']} | {row['median_return'] * 100:.2f}% | {row['median_mdd'] * 100:.2f}% |"
        )
    lines += [
        "", "## Guardrails", "",
        "CASH_RISK_FREE replays identical CASH_ZERO executions and quantities. Only cash accrues the latest DGS3MO observation known by the previous session using ACT/365. Different providers were not mixed; no pre-listing bars or rates were fabricated.", "",
    ]
    return "\n".join(lines)


def run(
    progress: Callable[[int, int, str, str], None] = lambda *_: None,
    *, snapshot: dict[str, Any],
) -> dict[str, Any]:
    began = time.perf_counter()
    before = immutable_fingerprints()
    assert_snapshot_immutable(snapshot)
    assert_snapshot_inputs_unchanged(snapshot)
    if not snapshot["readiness"]["research_validation_ready"]:
        raise EnvironmentValidationError("Current environment snapshot is not ready for long-history validation")
    rate_model = _load_rate_model(snapshot)
    frozen, _canonical = load()
    base = frozen["advanced"]["request_object"]
    rows_by_ticker = {row["ticker"]: row for row in snapshot["market_manifest"]["datasets"]}
    frames = {ticker: _selected_frame(row) for ticker, row in rows_by_ticker.items()}
    tickers = sorted(frames)
    total = len(tickers) * (1 + len(MARKET_CYCLE_WINDOWS))
    current = 0
    full_rows: list[dict[str, Any]] = []
    cycle_rows: list[dict[str, Any]] = []
    full_models: dict[tuple[str, str, str | None, str], dict[str, Any]] = {}
    evaluation_periods = {}

    for ticker in tickers:
        generated, models, prepared = _window_rows(
            base, ticker, frames[ticker], PRIMARY_HISTORY["start"], PRIMARY_HISTORY["end"],
            "FULL", "FULL", rate_model, keep_models=True,
        )
        if prepared is None:
            raise EnvironmentValidationError(f"No fair full-history evaluation period for {ticker}")
        full_rows.extend(generated)
        evaluation_periods[ticker] = {
            "data_start": frames[ticker].index[0].date().isoformat(),
            "evaluation_start": prepared.period.index[0].date().isoformat(),
            "evaluation_end": prepared.period.index[-1].date().isoformat(),
            "warmup_completed_bars": 200,
        }
        for (strategy, policy, cash_model), model in models.items():
            full_models[(ticker, strategy, policy, cash_model)] = model
        current += 1
        progress(current, total, ticker, f"完整期間 · {ticker}")

    for window, start, end in MARKET_CYCLE_WINDOWS:
        for ticker in tickers:
            generated, _models, _prepared = _window_rows(
                base, ticker, frames[ticker], start, end, "MARKET_CYCLE", window, rate_model,
            )
            cycle_rows.extend(generated)
            current += 1
            progress(current, total, ticker, f"{window} · {ticker}")

    crisis_rows = _crisis_rows(full_models)
    summary = _summary(full_rows)
    cycle_summary = _aggregate_period(cycle_rows, "window")
    crisis_summary = _aggregate_period(crisis_rows, "episode")
    grades, next_family = _grade(full_rows, cycle_rows)
    matrix, strategy_sensitivity, sensitivity = _sensitivity(full_rows, summary)
    cash_attribution = _cash_attribution(full_rows)

    assert_snapshot_immutable(snapshot)
    assert_snapshot_inputs_unchanged(snapshot)
    after = immutable_fingerprints()
    if before != after:
        raise EnvironmentValidationError("Production state changed during long-history research")
    study = _json_safe({
        "schema_version": 2, "study": "Research Environment v3 Long-History Extension",
        "research_only": True, "true_out_of_sample": False,
        "environment_snapshot": {
            "environment_snapshot_id": snapshot["environment_snapshot_id"],
            "created_at": snapshot["created_at"],
            "input_fingerprint_sha256": snapshot["input_fingerprint_sha256"],
            "snapshot_sha256": snapshot["snapshot_sha256"],
            "snapshot_file": snapshot.get("snapshot_file"),
            "snapshot_file_sha256": snapshot.get("snapshot_file_sha256"),
            "readiness": snapshot["readiness"],
        },
        "target_start": PRIMARY_HISTORY["start"].isoformat(), "target_end": PRIMARY_HISTORY["end"].isoformat(),
        "fair_evaluation_periods": evaluation_periods,
        "sample_composition_rule": "Per-symbol available history after 200 completed warm-up bars; no common-start truncation for later listings.",
        "data_manifest_sha256": snapshot["input_fingerprint_sha256"],
        "risk_free_manifest_sha256": snapshot["risk_free"]["manifest_sha256"],
        "cash_risk_free_contract": "fixed CASH_ZERO executions; previous-known DGS3MO ACT/365 applied to cash balance only",
        "full_period": full_rows, "market_cycle_rows": cycle_rows,
        "market_cycle_summary": cycle_summary, "crisis_rows": crisis_rows,
        "crisis_summary": crisis_summary, "summary": summary,
        "cash_yield_attribution": cash_attribution, "sensitivity_matrix": matrix,
        "strategy_sensitivity": strategy_sensitivity,
        "sensitivity_classification": sensitivity,
        "reclassification_gate": RECLASSIFICATION_GATE,
        "benchmark_reclassification": grades, "next_family": next_family,
        "candidate_created": False, "optimization_performed": False,
        "production_strategies_modified": False, "benchmark_definitions_modified": False,
        "immutability": {
            "before": before, "after": after, "unchanged": True,
            "executions_differences": 0, "pnl_differences": 0,
            "equity_differences": 0, "audits_differences": 0,
        },
        "runtime_seconds": time.perf_counter() - began,
    })
    (ROOT / "data/research-environment-v3-long-history.json").write_text(
        json.dumps(study, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    (ROOT / "reports/research-environment-v3-long-history.md").write_text(_render(study), encoding="utf-8")
    return study
