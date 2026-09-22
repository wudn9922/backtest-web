"""Snapshot-bound study orchestration for the frozen volatility benchmark."""
from __future__ import annotations

import json
import math
import os
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from research import ROOT
from research.baseline import immutable_fingerprints, load
from research.environment_v3_data import sha256_file
from research.environment_v3_design import CRISIS_EPISODES, ETF_RESEARCH_UNIVERSE, MARKET_CYCLE_WINDOWS
from research.environment_v3_extension import _json_safe, _load_rate_model, _selected_frame
from research.environment_v3_snapshot import assert_snapshot_immutable, assert_snapshot_inputs_unchanged
from research.volatility_managed import (
    SPEC_HASH,
    exposure_schedule,
    metric_delta,
    paired_block_uncertainty,
    simulate,
    slice_metrics,
    verify_spec,
)

CASH_MODELS = ("CASH_ZERO", "CASH_RISK_FREE")
COST_SCENARIOS = {
    "BASELINE": (1.0, 1.0),
    "2X_COMMISSION": (2.0, 1.0),
    "2X_SLIPPAGE": (1.0, 2.0),
    "2X_BOTH": (2.0, 2.0),
}


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _rate_factors(frame: pd.DataFrame, model) -> dict[pd.Timestamp, float]:
    return {current: model.accrue(1.0, previous, current).interest for previous, current in zip(frame.index, frame.index[1:])}


def _pair(frame, schedule, start, end, capital, commission, slippage, factors):
    managed = simulate(frame, schedule, "MANAGED", start, end, capital, commission, slippage, factors)
    hold = simulate(frame, schedule, "BUY_HOLD", start, end, capital, commission, slippage, factors)
    return managed, hold


def _window_rows(managed, hold, windows):
    rows = []
    for name, start, end in windows:
        left = slice_metrics(managed, start, end)
        right = slice_metrics(hold, start, end)
        if left and right:
            rows.append({"window": name, "start": str(start), "end": str(end), "managed": left, "buy_hold": right, "delta": metric_delta(left, right)})
    return rows


def _crisis_analysis(managed, hold, windows):
    rows = []
    managed_dates = [row["date"] for row in managed["daily"]]
    hold_dates = [row["date"] for row in hold["daily"]]
    assert managed_dates == hold_dates
    for name, start, end in windows:
        selected = [i for i, value in enumerate(managed_dates) if str(start) <= value <= str(end)]
        if not selected:
            continue
        first, last = selected[0], selected[-1]
        managed_metric = slice_metrics(managed, start, end)
        hold_metric = slice_metrics(hold, start, end)
        bh_values = np.asarray([hold["daily"][i]["equity"] for i in selected])
        local_trough = int(np.argmin(bh_values))
        trough_i = selected[local_trough]
        before_equity = hold["capital"] if first == 0 else hold["daily"][first - 1]["equity"]
        recovery_i = next((i for i in range(trough_i + 1, len(hold["daily"])) if hold["daily"][i]["equity"] >= before_equity), None)
        managed_recovery = None
        if recovery_i is not None:
            bh_return = hold["daily"][recovery_i]["equity"] / hold["daily"][trough_i]["equity"] - 1
            managed_return = managed["daily"][recovery_i]["equity"] / managed["daily"][trough_i]["equity"] - 1
            managed_recovery = {
                "date": managed_dates[recovery_i], "buy_hold_return": bh_return, "managed_return": managed_return,
                "participation_ratio": managed_return / bh_return if bh_return else None,
                "return_shortfall_pp": (bh_return - managed_return) * 100,
            }
        exposure_path = [{
            key: managed["daily"][i][key] for key in
            ("date", "rv20", "target_exposure", "open_exposure", "close_exposure", "quantity")
        } for i in selected]
        first_low_i = next((i for i in selected if managed["daily"][i]["target_exposure"] < .5), None)
        if managed["daily"][first]["target_exposure"] < .5:
            spell = first
            while spell > 0 and managed["daily"][spell - 1]["target_exposure"] < .5:
                spell -= 1
            first_low_i = spell
        rows.append({
            "episode": name, "start": str(start), "end": str(end),
            "managed": managed_metric, "buy_hold": hold_metric, "delta": metric_delta(managed_metric, hold_metric),
            "buy_hold_trough_date": managed_dates[trough_i],
            "first_target_below_50_date": managed_dates[first_low_i] if first_low_i is not None else None,
            "sessions_to_target_below_50": first_low_i - first if first_low_i is not None else None,
            "minimum_target_exposure": min(row["target_exposure"] for row in exposure_path),
            "minimum_actual_open_exposure": min(row["open_exposure"] for row in exposure_path),
            "sessions_actual_open_exposure_below_50": sum(row["open_exposure"] < .5 for row in exposure_path),
            "recovery": managed_recovery,
            "exposure_path": exposure_path,
        })
    return rows


def _rebound_analysis(managed, hold, crises):
    output = []
    dates = [row["date"] for row in hold["daily"]]
    for episode in ("2020_CRASH", "2022_BEAR"):
        _, start, end = next(item for item in crises if item[0] == episode)
        indices = [i for i, value in enumerate(dates) if str(start) <= value <= str(end)]
        trough = min(indices, key=lambda i: hold["daily"][i]["equity"])
        horizons = []
        for label, sessions in (("1M", 21), ("3M", 63), ("6M", 126)):
            target = min(trough + sessions, len(dates) - 1)
            bh_return = hold["daily"][target]["equity"] / hold["daily"][trough]["equity"] - 1
            managed_return = managed["daily"][target]["equity"] / managed["daily"][trough]["equity"] - 1
            horizons.append({
                "horizon": label, "sessions": target - trough, "complete": target == trough + sessions,
                "end_date": dates[target], "buy_hold_return": bh_return, "managed_return": managed_return,
                "managed_minus_buy_hold_pp": (managed_return - bh_return) * 100,
                "rebound_participation_ratio": managed_return / bh_return if bh_return else None,
            })
        output.append({"episode": episode, "trough_date": dates[trough], "horizons": horizons})
    return output


def _summarize_robustness(rows):
    fields = ("sharpe", "mdd", "cagr", "calmar")
    return {
        "etfs": len(rows),
        "improvement_counts": {field: sum(row["delta"][field] > 0 for row in rows) for field in fields},
        "median_delta": {field: float(np.median([row["delta"][field] for row in rows])) for field in fields},
        "median_managed_exposure": float(np.median([row["managed"]["exposure"] for row in rows])),
        "median_cagr_sacrifice": float(np.median([min(0.0, row["delta"]["cagr"]) for row in rows])),
    }


def _folds_for_frame(frame, evaluation_start):
    target = pd.Timestamp(evaluation_start) + pd.DateOffset(years=2)
    number = 0
    while target <= frame.index[-1]:
        eligible = frame.index[frame.index >= target]
        if eligible.empty:
            break
        test_start = eligible[0]
        end_target = target + pd.DateOffset(months=6) - pd.Timedelta(days=1)
        through = frame.index[(frame.index >= test_start) & (frame.index <= end_target)]
        if len(through) < 2:
            break
        number += 1
        yield number, target, test_start, through[-1], through[-1] < end_target
        target += pd.DateOffset(months=6)


def _walk_forward(frames, schedules, factors, full_runs, capital, commission, slippage, progress):
    rows = []
    for ticker, frame in frames.items():
        evaluation_start = schedules[ticker].index[0]
        for fold, target, test_start, test_end, partial in _folds_for_frame(frame, evaluation_start):
            train_end_rows = frame.index[frame.index < test_start]
            train_end = train_end_rows[-1]
            for cash_model in CASH_MODELS:
                cash_factors = factors[ticker] if cash_model == "CASH_RISK_FREE" else None
                test_managed, test_hold = _pair(frame, schedules[ticker], test_start, test_end, capital, commission, slippage, cash_factors)
                for design in ("EXPANDING", "ROLLING"):
                    train_start = evaluation_start if design == "EXPANDING" else max(evaluation_start, test_start - pd.DateOffset(years=2))
                    train_managed = slice_metrics(full_runs[ticker][cash_model]["managed"], train_start, train_end)
                    train_hold = slice_metrics(full_runs[ticker][cash_model]["buy_hold"], train_start, train_end)
                    rows.append({
                        "ticker": ticker, "fold": fold, "design": design, "cash_model": cash_model,
                        "train_start": pd.Timestamp(train_start).date().isoformat(), "train_end": train_end.date().isoformat(),
                        "test_start": test_start.date().isoformat(), "test_end": test_end.date().isoformat(),
                        "partial_fold": bool(partial), "train_managed": train_managed, "train_buy_hold": train_hold,
                        "train_delta": metric_delta(train_managed, train_hold), "test_managed": test_managed["metrics"],
                        "test_buy_hold": test_hold["metrics"], "test_delta": metric_delta(test_managed["metrics"], test_hold["metrics"]),
                    })
        progress(f"Walk-forward complete: {ticker}")
    unique = [row for row in rows if row["design"] == "EXPANDING" and row["cash_model"] == "CASH_ZERO"]
    spy = [row for row in unique if row["ticker"] == "SPY"]
    def breadth(values):
        return {"cells": len(values), **{field: sum(row["test_delta"][field] > 0 for row in values) for field in ("total_return", "sharpe", "mdd", "calmar")}}
    return rows, {"all_etf_unique_tests": breadth(unique), "spy_unique_tests": breadth(spy), "duplicate_designs_not_double_counted": True}


def run(progress: Callable[[str], None] = print):
    begun = time.monotonic()
    verify_spec()
    registration = json.loads((ROOT / "data/volatility-managed-registration.json").read_text(encoding="utf-8"))
    assert registration["spec_sha256"] == SPEC_HASH
    snapshot = json.loads((ROOT / "data/research-environment-current-snapshot.json").read_text(encoding="utf-8"))
    assert_snapshot_immutable(snapshot)
    assert_snapshot_inputs_unchanged(snapshot)
    assert registration["snapshot_id"] == snapshot["environment_snapshot_id"]
    assert registration["fingerprint"] == snapshot["input_fingerprint_sha256"]
    registry_hash = sha256_file(ROOT / "data/research-candidate-registry.json")
    assert registry_hash == registration["registry_sha256"]
    before = immutable_fingerprints()
    assert before == registration["protected_before"]
    frozen, _ = load()
    request = frozen["advanced"]["request"]
    assert request["initial_capital"] == registration["initial_capital"]
    assert request["commission_pct"] == registration["commission_pct"]
    assert request["slippage_pct"] == registration["slippage_pct"]
    capital = registration["initial_capital"]
    commission = registration["commission_pct"] / 100
    slippage = registration["slippage_pct"] / 100
    datasets = [row for row in snapshot["market_manifest"]["datasets"] if row["ticker"] in ETF_RESEARCH_UNIVERSE]
    frames = {row["ticker"]: _selected_frame(row) for row in datasets}
    assert set(frames) == set(ETF_RESEARCH_UNIVERSE)
    schedules = {ticker: exposure_schedule(frame) for ticker, frame in frames.items()}
    assert all(not schedule.empty for schedule in schedules.values())
    rate_model = _load_rate_model(snapshot)
    factors = {ticker: _rate_factors(frame, rate_model) for ticker, frame in frames.items()}
    full_runs = {}
    cost_runs = {}
    gross_runs = {}
    robustness_rows = {cash: [] for cash in CASH_MODELS}
    for ticker, frame in frames.items():
        start, end = schedules[ticker].index[0], frame.index[-1]
        full_runs[ticker] = {}
        cost_runs[ticker] = {}
        gross_runs[ticker] = {}
        for cash_model in CASH_MODELS:
            cash_factors = factors[ticker] if cash_model == "CASH_RISK_FREE" else None
            managed, hold = _pair(frame, schedules[ticker], start, end, capital, commission, slippage, cash_factors)
            managed["ticker"] = hold["ticker"] = ticker
            full_runs[ticker][cash_model] = {"managed": managed, "buy_hold": hold}
            robustness_rows[cash_model].append({
                "ticker": ticker, "evaluation_start": managed["start"], "evaluation_end": managed["end"],
                "managed": managed["metrics"], "buy_hold": hold["metrics"],
                "delta": metric_delta(managed["metrics"], hold["metrics"]),
            })
            cost_runs[ticker][cash_model] = {"BASELINE": {"managed": managed["metrics"], "buy_hold": hold["metrics"]}}
            for scenario, (commission_multiplier, slippage_multiplier) in COST_SCENARIOS.items():
                if scenario == "BASELINE":
                    continue
                stressed_managed, stressed_hold = _pair(
                    frame, schedules[ticker], start, end, capital,
                    commission * commission_multiplier, slippage * slippage_multiplier, cash_factors,
                )
                cost_runs[ticker][cash_model][scenario] = {
                    "managed": stressed_managed["metrics"], "buy_hold": stressed_hold["metrics"],
                    "delta": metric_delta(stressed_managed["metrics"], stressed_hold["metrics"]),
                }
            zero_managed, zero_hold = _pair(frame, schedules[ticker], start, end, capital, 0.0, 0.0, cash_factors)
            gross_runs[ticker][cash_model] = {
                "managed": zero_managed["metrics"], "buy_hold": zero_hold["metrics"],
                "delta": metric_delta(zero_managed["metrics"], zero_hold["metrics"]),
            }
        progress(f"Full history and cost stress complete: {ticker}")

    robustness_summary = {cash: _summarize_robustness(rows) for cash, rows in robustness_rows.items()}
    stress_breadth = {}
    for cash_model in CASH_MODELS:
        stress_breadth[cash_model] = {}
        for scenario in COST_SCENARIOS:
            rows = []
            for ticker in frames:
                cell = cost_runs[ticker][cash_model][scenario]
                delta = cell.get("delta") or metric_delta(cell["managed"], cell["buy_hold"])
                rows.append({"ticker": ticker, "managed": cell["managed"], "buy_hold": cell["buy_hold"], "delta": delta})
            stress_breadth[cash_model][scenario] = _summarize_robustness(rows)

    spy_runs = full_runs["SPY"]
    fixed_periods = {cash: _window_rows(pair["managed"], pair["buy_hold"], MARKET_CYCLE_WINDOWS) for cash, pair in spy_runs.items()}
    crises = {cash: _crisis_analysis(pair["managed"], pair["buy_hold"], CRISIS_EPISODES) for cash, pair in spy_runs.items()}
    rebounds = {cash: _rebound_analysis(pair["managed"], pair["buy_hold"], CRISIS_EPISODES) for cash, pair in spy_runs.items()}
    walk_rows, walk_summary = _walk_forward(frames, schedules, factors, full_runs, capital, commission, slippage, progress)
    uncertainty = paired_block_uncertainty(spy_runs["CASH_ZERO"]["managed"], spy_runs["CASH_ZERO"]["buy_hold"])

    spy_zero = robustness_rows["CASH_ZERO"][next(i for i, row in enumerate(robustness_rows["CASH_ZERO"]) if row["ticker"] == "SPY")]
    spy_delta = spy_zero["delta"]
    period_support = [
        row for row in fixed_periods["CASH_ZERO"]
        if row["delta"]["sharpe"] > 0 and row["delta"]["calmar"] > 0
        and row["delta"]["mdd"] >= 0 and row["delta"]["cagr"] >= -.05
    ]
    zero_summary = robustness_summary["CASH_ZERO"]
    spy_walk = walk_summary["spy_unique_tests"]
    stressed_spy = cost_runs["SPY"]["CASH_ZERO"]["2X_BOTH"]["delta"]
    stressed_breadth = stress_breadth["CASH_ZERO"]["2X_BOTH"]
    primary_checks = {
        "spy_sharpe_positive": spy_delta["sharpe"] > 0,
        "spy_sortino_positive": spy_delta["sortino"] > 0,
        "spy_calmar_positive": spy_delta["calmar"] > 0,
        "spy_mdd_improves_at_least_5pp": spy_delta["mdd"] >= .05,
        "spy_cagr_sacrifice_within_3pp": spy_delta["cagr"] >= -.03,
        "supportive_fixed_periods": len(period_support),
        "fixed_periods_required": 4,
        "etf_sharpe_count": zero_summary["improvement_counts"]["sharpe"],
        "etf_mdd_count": zero_summary["improvement_counts"]["mdd"],
        "etf_calmar_count": zero_summary["improvement_counts"]["calmar"],
        "etf_required": 8,
        "median_sharpe_positive": zero_summary["median_delta"]["sharpe"] > 0,
        "median_mdd_positive": zero_summary["median_delta"]["mdd"] > 0,
        "median_calmar_positive": zero_summary["median_delta"]["calmar"] > 0,
        "median_cagr_sacrifice_within_3pp": zero_summary["median_delta"]["cagr"] >= -.03,
        "spy_walk_sharpe_majority": spy_walk["sharpe"] > spy_walk["cells"] / 2,
        "spy_walk_mdd_majority": spy_walk["mdd"] > spy_walk["cells"] / 2,
        "spy_walk_calmar_half": spy_walk["calmar"] >= spy_walk["cells"] / 2,
        "stress_spy_core": stressed_spy["sharpe"] > 0 and stressed_spy["sortino"] > 0 and stressed_spy["calmar"] > 0 and stressed_spy["mdd"] >= .05 and stressed_spy["cagr"] >= -.03,
        "stress_etf_sharpe_at_least_8": stressed_breadth["improvement_counts"]["sharpe"] >= 8,
        "stress_etf_calmar_at_least_8": stressed_breadth["improvement_counts"]["calmar"] >= 8,
    }
    promising = (
        all(primary_checks[key] for key in (
            "spy_sharpe_positive", "spy_sortino_positive", "spy_calmar_positive",
            "spy_mdd_improves_at_least_5pp", "spy_cagr_sacrifice_within_3pp",
            "median_sharpe_positive", "median_mdd_positive", "median_calmar_positive",
            "median_cagr_sacrifice_within_3pp", "spy_walk_sharpe_majority",
            "spy_walk_mdd_majority", "spy_walk_calmar_half", "stress_spy_core",
            "stress_etf_sharpe_at_least_8", "stress_etf_calmar_at_least_8",
        ))
        and len(period_support) >= 4
        and min(zero_summary["improvement_counts"][key] for key in ("sharpe", "mdd", "calmar")) >= 8
    )
    strong = promising and (
        len(period_support) >= 5
        and min(zero_summary["improvement_counts"][key] for key in ("sharpe", "mdd", "calmar")) >= 10
        and min(spy_walk[key] for key in ("sharpe", "mdd", "calmar")) >= math.ceil(spy_walk["cells"] * 2 / 3)
        and uncertainty["sharpe_delta"]["ci95"][0] > 0
        and uncertainty["calmar_delta"]["ci95"][0] > 0
        and spy_delta["cagr"] >= -.02
        and min(stressed_breadth["improvement_counts"][key] for key in ("sharpe", "calmar")) >= 10
    )
    grade = "STRONG RETROSPECTIVE EVIDENCE" if strong else "PROMISING — FAMILY WORTH STUDYING" if promising else "NOT SUPPORTED"

    cash_decomposition = {}
    for ticker in frames:
        managed_zero = full_runs[ticker]["CASH_ZERO"]["managed"]["metrics"]
        managed_rf = full_runs[ticker]["CASH_RISK_FREE"]["managed"]["metrics"]
        hold_zero = full_runs[ticker]["CASH_ZERO"]["buy_hold"]["metrics"]
        hold_rf = full_runs[ticker]["CASH_RISK_FREE"]["buy_hold"]["metrics"]
        cash_decomposition[ticker] = {
            "managed_cash_interest_usd": managed_rf["cash_interest"],
            "buy_hold_cash_interest_usd": hold_rf["cash_interest"],
            "managed_return_contribution_pp": (managed_rf["total_return"] - managed_zero["total_return"]) * 100,
            "buy_hold_return_contribution_pp": (hold_rf["total_return"] - hold_zero["total_return"]) * 100,
            "incremental_managed_cash_effect_pp": (
                (managed_rf["total_return"] - managed_zero["total_return"])
                - (hold_rf["total_return"] - hold_zero["total_return"])
            ) * 100,
        }

    turn = full_runs["SPY"]["CASH_ZERO"]["managed"]
    result = {
        "study": "VOL_MANAGED_20D_15PCT_CAP1",
        "title": "20 日波動度管理曝險",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "registration": registration,
        "candidate_created": False,
        "production_strategy_created": False,
        "parameter_sweep_performed": False,
        "evaluation": {
            "data_start": frames["SPY"].index[0].date().isoformat(),
            "signal_start": schedules["SPY"].iloc[0]["signal_date"].date().isoformat(),
            "evaluation_start": schedules["SPY"].index[0].date().isoformat(),
            "evaluation_end": frames["SPY"].index[-1].date().isoformat(),
            "warmup_returns": 20,
        },
        "parameters": {"rv_lookback_sessions": 20, "target_annualized_volatility": .15, "max_equity_exposure": 1.0, "execution": "NEXT_OPEN"},
        "primary_spy": {
            cash: {
                "managed": pair["managed"]["metrics"], "buy_hold": pair["buy_hold"]["metrics"],
                "delta": metric_delta(pair["managed"]["metrics"], pair["buy_hold"]["metrics"]),
            } for cash, pair in spy_runs.items()
        },
        "fixed_periods": fixed_periods,
        "crisis_analysis": crises,
        "post_crash_rebound": rebounds,
        "cost_stress_spy": {cash: cost_runs["SPY"][cash] for cash in CASH_MODELS},
        "gross_before_cost_spy": {cash: gross_runs["SPY"][cash] for cash in CASH_MODELS},
        "cash_decomposition": cash_decomposition,
        "turnover_forensic": {
            "number_of_adjustment_trades": turn["metrics"]["number_of_adjustment_trades"],
            "adjustment_days": turn["metrics"]["adjustment_days"],
            "average_daily_turnover": turn["metrics"]["average_daily_turnover"],
            "annual_turnover": turn["metrics"]["annual_turnover"],
            "target_change_distribution": turn["target_change_distribution"],
        },
        "uncertainty": uncertainty,
        "robustness_summary": robustness_summary,
        "cost_stress_breadth": stress_breadth,
        "walk_forward_summary": walk_summary,
        "gate_checks": primary_checks,
        "evidence_grade": grade,
        "next_family": "VOLATILITY_MANAGED_EXPOSURE" if grade != "NOT SUPPORTED" else "NONE",
        "sma200_descriptive_reference": {"grade": "NOT SUPPORTED", "source": "Frozen Research Environment v3; not rerun"},
        "data_coverage": [{
            "ticker": row["ticker"], "first_date": row["first_date"], "last_date": row["last_date"],
            "bars": row["bars"], "ohlcv_sha256": row["ohlcv_sha256"],
            "provider": "yahoo", "adjustment_mode": "adjusted_for_splits",
        } for row in datasets],
        "limitations": [
            "Retrospective evidence only; no true future out-of-sample data.",
            "Yahoo split-adjusted price series does not include dividend cash flows.",
            "DGS3MO is a cash-yield proxy and not an investable total-return instrument.",
            "Fixed modern ETF universe reduces company survivorship effects but is not point-in-time constituent data.",
            "Daily next-open sizing cannot represent an intraday response to volatility.",
            "Walk-forward train windows do not fit parameters; duplicate design test results are not independent evidence.",
            "Block-bootstrap intervals depend on one realized historical path and the predeclared 63-session block length.",
        ],
        "runtime_seconds": time.monotonic() - begun,
    }
    robustness = {
        "study": result["study"], "registration": registration, "rows": robustness_rows,
        "summary": robustness_summary, "cost_stress": cost_runs, "cost_stress_breadth": stress_breadth,
        "gross_before_cost": gross_runs, "cash_decomposition": cash_decomposition,
    }
    walk_forward = {
        "study": result["study"], "name": "Retrospective Walk-Forward Robustness Validation",
        "registration": registration, "rows": walk_rows, "summary": walk_summary,
        "note": "Fixed parameters; expanding and rolling test results are identical and counted once.",
    }
    verify_spec()
    assert_snapshot_inputs_unchanged(snapshot)
    after = immutable_fingerprints()
    assert before == after
    assert sha256_file(ROOT / "data/research-candidate-registry.json") == registry_hash
    result["invariance"] = {
        "before": before, "after": after, "differences": 0,
        "registry_sha256_before_after": registry_hash,
        "executions_pnl_equity_audits_differences": 0,
    }
    return _json_safe(result), _json_safe(robustness), _json_safe(walk_forward)


def publish(result, robustness, walk_forward):
    atomic_json(ROOT / "data/volatility-managed-benchmark.json", result)
    atomic_json(ROOT / "data/volatility-managed-etf-robustness.json", robustness)
    atomic_json(ROOT / "data/volatility-managed-walk-forward.json", walk_forward)
    from research.volatility_managed_report import render
    report = render(result, robustness, walk_forward)
    path = ROOT / "reports/volatility-managed-benchmark.md"
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(report, encoding="utf-8")
    os.replace(temporary, path)
