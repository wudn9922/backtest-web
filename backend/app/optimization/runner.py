from __future__ import annotations

import hashlib
import json
import math
import statistics
import copy
from typing import Any

import pandas as pd

from app.backtest.engine import BacktestEngine
from app.backtest.data_preparation import prepare_daily_market_data, required_warmup_start
from app.backtest.models import BacktestError, BacktestRequest, StrategyName
from app.db.repository import BacktestRepository
from app.jobs.repository import JobRepository
from app.optimization.models import MAOptimizationRequest
from app.optimization.structure import (
    STRUCTURE_IMPLEMENTATION_REVISION,
    STRUCTURE_SPEC_HASH,
    STRUCTURE_SPEC_VERSION,
    StructureValidationError,
    analyze_ma_structure,
    build_structure_selector_candidate,
    rank_structure_candidates,
    select_structure_ma,
    structure_candidate_sort_key,
    structure_required_warmup_start,
)
from app.optimization.windows import RollingWindow, build_rolling_six_month_windows


def _data_fingerprint(frame: pd.DataFrame) -> str:
    columns = ["open", "high", "low", "close", "volume"]
    stable = frame.loc[:, columns].copy()
    hashed = pd.util.hash_pandas_object(stable, index=True).values.tobytes()
    return hashlib.sha256(hashed).hexdigest()


def _request_payload(request: BacktestRequest) -> dict[str, Any]:
    payload = request.model_dump(mode="json")
    if request.strategy != StrategyName.ADVANCED_DAY1_STOP:
        payload["parameters"].pop("day1_stop_pct", None)
    return payload


def _cache_key(request: BacktestRequest, fingerprint: str) -> str:
    encoded = json.dumps(
        {"request": _request_payload(request), "data_fingerprint": fingerprint},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _row(backtest_id: str, ma_period: int, result: dict[str, Any], reused: bool) -> dict[str, Any]:
    summary = result["summary"]
    return {
        "ma_period": ma_period,
        "backtest_id": backtest_id,
        "total_return": summary.get("total_return"),
        "cagr": summary.get("cagr"),
        "max_drawdown": summary.get("max_drawdown"),
        "sharpe_ratio": summary.get("sharpe_ratio"),
        "sortino_ratio": summary.get("sortino_ratio"),
        "calmar_ratio": summary.get("calmar_ratio"),
        "number_of_positions": summary.get("number_of_positions"),
        "win_rate": summary.get("win_rate"),
        "net_pnl": sum(float(item.get("net_pnl") or 0) for item in result.get("positions", [])),
        "exposure_pct": summary.get("exposure_pct"),
        "average_holding_days": summary.get("average_holding_days"),
        "total_commission": summary.get("total_commission"),
        "estimated_slippage_cost": summary.get("estimated_slippage_cost"),
        "final_equity": summary.get("final_equity"),
        "cache_reused": reused,
    }


def _score(row: dict[str, Any], metric: str) -> float:
    value = row.get(metric)
    return float(value) if value is not None else float("-inf")


def _select_best(rows: list[dict[str, Any]], metric: str) -> tuple[dict[str, Any], str]:
    """Apply the frozen, deterministic MA tie-break contract."""
    best = max(
        rows,
        key=lambda row: (
            _score(row, metric),
            _score(row, "total_return"),
            -abs(_score(row, "max_drawdown")),
            -int(row["ma_period"]),
        ),
    )
    primary = [row for row in rows if _score(row, metric) == _score(best, metric)]
    if len(primary) == 1:
        return best, "RANKING_METRIC"
    by_return = [row for row in primary if _score(row, "total_return") == max(_score(item, "total_return") for item in primary)]
    if len(by_return) == 1:
        return best, "HIGHER_TOTAL_RETURN"
    least_drawdown = min(abs(_score(item, "max_drawdown")) for item in by_return)
    by_drawdown = [row for row in by_return if abs(_score(row, "max_drawdown")) == least_drawdown]
    if len(by_drawdown) == 1:
        return best, "LOWER_ABSOLUTE_MDD"
    return best, "SMALLER_MA_PERIOD"


def _canonical_input_frame(daily: pd.DataFrame, request: BacktestRequest) -> pd.DataFrame:
    """Slice the one batch download to the normal request's exact pre-roll.

    This matters for recursively initialized indicators such as Wilder ATR: a
    shorter MA must not inherit extra history merely because the same optimizer
    batch also contains a larger MA period.
    """
    start = required_warmup_start(request)
    mask = [(start <= timestamp.date() <= request.end_date) for timestamp in daily.index]
    return daily.loc[mask].copy()


def _stability(rows: list[dict[str, Any]], best: dict[str, Any], metric: str, step: int) -> dict[str, Any]:
    nearby = [row for row in rows if abs(int(row["ma_period"]) - int(best["ma_period"])) <= step * 5]
    best_value = _score(best, metric)
    finite = [_score(row, metric) for row in nearby if _score(row, metric) != float("-inf")]
    if len(finite) < 2:
        stable = False
        relative_spread = None
    else:
        relative_spread = (max(finite) - min(finite)) / max(abs(best_value), 1e-9)
        stable = relative_spread <= 0.20
    return {
        "metric": metric,
        "best_ma_period": best["ma_period"],
        "from_ma": min(int(row["ma_period"]) for row in nearby),
        "to_ma": max(int(row["ma_period"]) for row in nearby),
        "relative_spread": relative_spread,
        "stable": stable,
        "label": "附近參數表現相對穩定" if stable else "此最佳值附近穩定性較低",
        "rows": nearby,
    }


def _run_canonical(
    request: BacktestRequest,
    daily: pd.DataFrame,
    provider_name: str,
    fingerprint: str,
    repo: BacktestRepository,
) -> dict[str, Any]:
    key = _cache_key(request, fingerprint)
    cached = repo.get_optimization_cache(key, fingerprint)
    if cached and cached.get("result"):
        return _row(str(cached["id"]), request.parameters.ma_period, cached["result"], True)

    payload = _request_payload(request)
    identifier = repo.create_pending(payload)
    try:
        engine = BacktestEngine()
        result = engine.run(request, daily, provider_name)
        result["id"] = identifier
        result["reproducibility"]["optimization_data_fingerprint"] = fingerprint
        repo.complete(identifier, result, engine.position_audits)
        repo.put_optimization_cache(key, fingerprint, identifier)
        return _row(identifier, request.parameters.ma_period, result, False)
    except Exception as exc:
        repo.fail(identifier, str(exc))
        raise


def _run_single_ma_optimization(
    identifier: str,
    payload: dict[str, Any],
    jobs: JobRepository,
    backtests: BacktestRepository,
    provider: Any,
) -> dict[str, Any] | None:
    """Run a resumable MA sweep using the production BacktestEngine verbatim."""
    spec = MAOptimizationRequest.model_validate(payload)
    periods = spec.periods()
    train_test = spec.train_test
    if train_test.enabled:
        assert train_test.train_start and train_test.train_end and train_test.test_start and train_test.test_end
        first_date, last_date = train_test.train_start, train_test.test_end
    else:
        first_date, last_date = spec.backtest.start_date, spec.backtest.end_date

    total = len(periods) + (1 if train_test.enabled else 0)
    required_start = required_warmup_start(
        spec.backtest,
        evaluation_start=first_date,
        ma_period=spec.ma_max,
    )
    jobs.progress(identifier, 0, total, "DATA_PREPARATION", "正在準備指標預熱所需的歷史日線資料。")
    try:
        market = prepare_daily_market_data(
            spec.backtest,
            provider,
            evaluation_start=first_date,
            evaluation_end=last_date,
            ma_period=spec.ma_max,
        )
    except BacktestError as exc:
        jobs.finish(
            identifier,
            "FAILED",
            "資料準備失敗；目前無法取得指標預熱所需的完整歷史資料。",
            errors=[{
                "stage": "DATA_PREPARATION",
                "code": exc.code,
                "message": exc.message,
                "ticker": spec.backtest.ticker,
                "requested_start": first_date.isoformat(),
                "requested_end": last_date.isoformat(),
                "provider_requested_start": required_start.isoformat(),
                "cache_coverage": exc.details.get("cache_coverage"),
            }],
            result={
                "results": [],
                "skipped": [],
                "failure_stage": "DATA_PREPARATION",
                "requested_evaluation_range": [first_date.isoformat(), last_date.isoformat()],
                "provider_requested_range": [required_start.isoformat(), last_date.isoformat()],
            },
        )
        return None
    daily, provider_name = market.daily, market.provider
    fingerprint = _data_fingerprint(daily)

    current_job = jobs.get(identifier) or {}
    checkpoint = current_job.get("result") or {}
    rows: list[dict[str, Any]] = list(checkpoint.get("results") or [])
    prior_errors: list[dict[str, Any]] = list(current_job.get("errors") or [])
    skipped: list[dict[str, Any]] = list(checkpoint.get("skipped") or [])
    period_errors = {
        int(item["ma_period"]): item for item in prior_errors if item.get("ma_period") is not None
    }
    other_errors = [item for item in prior_errors if item.get("ma_period") is None]
    done = {int(row["ma_period"]) for row in rows}
    skipped_periods = {int(item["ma_period"]) for item in skipped if item.get("ma_period") is not None}

    for ma_period in periods:
        if (jobs.get(identifier) or {}).get("status") == "CANCELLED":
            return None
        if ma_period in done or ma_period in skipped_periods:
            continue
        request = spec.backtest.model_copy(deep=True)
        request.parameters.ma_period = ma_period
        if train_test.enabled:
            request.start_date = train_test.train_start  # type: ignore[assignment]
            request.end_date = train_test.train_end  # type: ignore[assignment]
        # A recovered job retries only unfinished periods.  Remove the stale
        # failure for this period before the retry so a later success does not
        # leave a false PARTIAL_SUCCESS result behind.
        period_errors.pop(ma_period, None)
        errors = other_errors + list(period_errors.values())
        jobs.progress(identifier, len(rows) + len(skipped) + len(period_errors), total, f"MA {ma_period}", f"正在執行 MA {ma_period}。", errors=errors, result={
            "results": rows, "skipped": skipped, "data_fingerprint": fingerprint, "provider": provider_name,
        })
        try:
            canonical_daily = _canonical_input_frame(daily, request)
            canonical_fingerprint = _data_fingerprint(canonical_daily)
            rows.append(_run_canonical(request, canonical_daily, provider_name, canonical_fingerprint, backtests))
        except BacktestError as exc:
            if exc.code in {"NOT_ENOUGH_MA_LOOKBACK", "NOT_ENOUGH_BIAS_HISTORY", "NOT_ENOUGH_ATR_HISTORY", "NO_DAILY_BARS"}:
                skipped.append({"ma_period": ma_period, "code": exc.code, "message": "此均線週期的已完成歷史資料不足。"})
                skipped_periods.add(ma_period)
            else:
                period_errors[ma_period] = {"ma_period": ma_period, "stage": "CANONICAL_BACKTEST", "code": exc.code, "message": exc.message}
        except Exception as exc:
            period_errors[ma_period] = {"ma_period": ma_period, "code": "OPTIMIZATION_RUN_FAILED", "message": str(exc)[:500]}
        errors = other_errors + list(period_errors.values())
        jobs.progress(identifier, len(rows) + len(skipped) + len(period_errors), total, f"MA {ma_period}", f"MA {ma_period} 已完成。", errors=errors, result={
            "results": rows, "skipped": skipped, "data_fingerprint": fingerprint, "provider": provider_name,
        })

    errors = other_errors + list(period_errors.values())

    if not rows:
        status = "FAILED_VALIDATION" if skipped and not errors else "FAILED"
        message = "所有均線週期都因歷史資料不足而略過。" if status == "FAILED_VALIDATION" else "所有均線週期回測都未完成。"
        jobs.finish(identifier, status, message, errors=errors, result={"results": [], "skipped": skipped, "data_fingerprint": fingerprint, "provider": provider_name})
        return None

    best, tie_break_reason = _select_best(rows, spec.ranking_metric)
    result: dict[str, Any] = {
        "results": rows,
        "skipped": skipped,
        "ranking_metric": spec.ranking_metric,
        "best": best,
        "tie_break_reason": tie_break_reason,
        "stability": _stability(rows, best, spec.ranking_metric, spec.ma_step),
        "data_fingerprint": fingerprint,
        "provider": provider_name,
        "data_coverage": {
            "first_date": daily.index[0].date().isoformat(),
            "last_date": daily.index[-1].date().isoformat(),
            "bars": len(daily),
            "warnings": list(getattr(market, "warnings", []) or []),
        },
        "canonical_engine": True,
        "train_test": {"enabled": train_test.enabled},
    }
    if train_test.enabled:
        if (jobs.get(identifier) or {}).get("status") == "CANCELLED":
            return None
        test_request = spec.backtest.model_copy(deep=True)
        test_request.parameters.ma_period = int(best["ma_period"])
        test_request.start_date = train_test.test_start  # type: ignore[assignment]
        test_request.end_date = train_test.test_end  # type: ignore[assignment]
        test_daily = _canonical_input_frame(daily, test_request)
        test_row = _run_canonical(test_request, test_daily, provider_name, _data_fingerprint(test_daily), backtests)
        result["train_test"] = {
            "enabled": True,
            "train_best": best,
            "test_result": test_row,
            "selection_source": "TRAIN_ONLY",
            "train_range": [train_test.train_start.isoformat(), train_test.train_end.isoformat()],
            "test_range": [train_test.test_start.isoformat(), train_test.test_end.isoformat()],
        }
        jobs.progress(identifier, total, total, None, "樣本外驗證已完成。", errors=errors, result=result)

    if errors or skipped:
        jobs.finish(identifier, "PARTIAL_SUCCESS", "部分均線週期未完成，其餘結果可正常查看。", errors=errors, result=result)
        return None
    return result


def _actual_session_bounds(daily: pd.DataFrame, start: Any, end: Any) -> dict[str, str | None]:
    selected = daily[[(start <= timestamp.date() <= end) for timestamp in daily.index]]
    return {
        "first_session": selected.index[0].date().isoformat() if len(selected) else None,
        "last_session": selected.index[-1].date().isoformat() if len(selected) else None,
    }


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    left_mean, right_mean = statistics.fmean(left), statistics.fmean(right)
    left_var = sum((value - left_mean) ** 2 for value in left)
    right_var = sum((value - right_mean) ** 2 for value in right)
    if left_var == 0 or right_var == 0:
        return None
    return sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right)) / math.sqrt(left_var * right_var)


def _aggregate_test_segments(windows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    rows = [window[key] for window in windows if window.get("aggregate_included") and window.get(key)]
    returns = [float(row["total_return"]) for row in rows if row.get("total_return") is not None]
    sharpes = [float(row["sharpe_ratio"]) for row in rows if row.get("sharpe_ratio") is not None]
    drawdowns = [float(row["max_drawdown"]) for row in rows if row.get("max_drawdown") is not None]
    compounded = math.prod(1 + value for value in returns) - 1 if returns else None
    return {
        "complete_test_windows": len(rows),
        "positive_return_windows": sum(value > 0 for value in returns),
        "positive_return_ratio": sum(value > 0 for value in returns) / len(returns) if returns else None,
        "average_6m_return": _mean(returns),
        "median_6m_return": _median(returns),
        "average_sharpe": _mean(sharpes),
        "median_sharpe": _median(sharpes),
        "average_mdd": _mean(drawdowns),
        "worst_6m_return": min(returns) if returns else None,
        "best_6m_return": max(returns) if returns else None,
        "segment_chained_return": compounded,
        "continuous_execution": False,
    }


def _selection_summary(windows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [int(window["selected_ma"]) for window in windows if window.get("aggregate_included")]
    changes = [abs(current - previous) for previous, current in zip(values, values[1:])]
    return {
        "count": len(values),
        "average_ma": _mean([float(value) for value in values]),
        "median_ma": _median([float(value) for value in values]),
        "minimum_ma": min(values) if values else None,
        "maximum_ma": max(values) if values else None,
        "ma_standard_deviation": statistics.pstdev(values) if len(values) > 1 else (0.0 if values else None),
        "adjacent_window_changes": changes,
        "average_adjacent_change": _mean([float(value) for value in changes]),
        "median_adjacent_change": _median([float(value) for value in changes]),
    }


def _relationship(windows: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    included = [window for window in windows if window.get("aggregate_included")]
    train_metric: list[float] = []
    test_metric: list[float] = []
    train_returns: list[float] = []
    test_returns: list[float] = []
    for window in included:
        train, test = window["train_best"], window["test_result"]
        if train.get(metric) is not None and test.get(metric) is not None:
            train_metric.append(float(train[metric])); test_metric.append(float(test[metric]))
        if train.get("total_return") is not None and test.get("total_return") is not None:
            train_returns.append(float(train["total_return"])); test_returns.append(float(test["total_return"]))
    sharpes = [float(window["test_result"]["sharpe_ratio"]) for window in included if window["test_result"].get("sharpe_ratio") is not None]
    return {
        "ranking_metric": metric,
        "train_test_metric_correlation": _correlation(train_metric, test_metric),
        "train_test_return_correlation": _correlation(train_returns, test_returns),
        "test_positive_return_ratio": sum(value > 0 for value in test_returns) / len(test_returns) if test_returns else None,
        "test_positive_sharpe_ratio": sum(value > 0 for value in sharpes) / len(sharpes) if sharpes else None,
        "display_sharpe_threshold": 1.0,
        "test_sharpe_above_display_threshold_ratio": sum(value > 1 for value in sharpes) / len(sharpes) if sharpes else None,
        "display_only": True,
    }


def _rolling_cache_key(spec: MAOptimizationRequest, fingerprint: str) -> str:
    request_payload = spec.model_dump(mode="json")
    # Keep the historical Performance cache namespace byte-for-byte stable
    # for payloads created before selection_mode existed.  Structure results
    # deliberately retain the explicit mode plus frozen version/hash.
    if spec.selection_mode == "PERFORMANCE":
        request_payload.pop("selection_mode", None)
    structure_identity = (
        {
            "structure_spec_version": STRUCTURE_SPEC_VERSION,
            "structure_spec_hash": STRUCTURE_SPEC_HASH,
            "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
        }
        if spec.selection_mode == "STRUCTURE_V1" else {}
    )
    encoded = json.dumps(
        {"spec": request_payload, **structure_identity, "data_fingerprint": fingerprint},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _structure_input_frame(
    daily: pd.DataFrame,
    window: RollingWindow,
    ma_period: int,
) -> pd.DataFrame:
    """Slice candidate-specific MA pre-roll while excluding Test bars."""
    start = structure_required_warmup_start(window.train_start, ma_period)
    mask = [(start <= timestamp.date() <= window.train_end) for timestamp in daily.index]
    return daily.loc[mask].copy()


def _structure_summary(
    analysis: dict[str, Any],
    selector_candidate: dict[str, Any],
    train_reference: dict[str, Any] | None,
    candidate_index: int,
) -> dict[str, Any]:
    """Join display/audit data only after structure selection is complete.

    The selector candidate remains a separate, structure-only object.  Train
    performance is deliberately attached here, after rank/select, solely as a
    UI/reference field and can never affect the selector.
    """
    excluded = {"events", "chart_artifact", "artifact"}
    summary = {key: value for key, value in analysis.items() if key not in excluded}
    # Keep the new ranking namespace and compatibility display aliases in the
    # persisted candidate, while preserving analyzer *_raw fields verbatim.
    for key, value in selector_candidate.items():
        if key in {
            "structure_ranking", "regime_percentile", "retest_percentile", "breakout_percentile",
            "confirmation_percentile", "ma_structure_score", "structure_score", "structure_percentile",
            "structure_components", "structure_rank", "rank", "tie_break_reason",
        }:
            summary[key] = value
    summary["candidate_index"] = candidate_index
    summary["train_reference"] = train_reference
    summary["train_return"] = train_reference.get("total_return") if train_reference else None
    summary["train_sharpe"] = train_reference.get("sharpe_ratio") if train_reference else None
    # Only the ranked Top-5 artifacts are persisted; the flag is updated once
    # the complete ranking order is known.
    summary["artifact_available"] = False
    return summary


def _relationship_track(
    windows: list[dict[str, Any]],
    train_key: str,
    test_key: str,
    metric: str,
) -> dict[str, Any]:
    def train_value(row: dict[str, Any], key: str) -> Any:
        if row.get(key) is not None:
            return row.get(key)
        reference = row.get("train_reference") or {}
        if reference.get(key) is not None:
            return reference.get(key)
        aliases = {"sharpe_ratio": "train_sharpe", "total_return": "train_return"}
        return row.get(aliases.get(key, key))

    included = [window for window in windows if window.get("aggregate_included")]
    train_metric: list[float] = []
    test_metric: list[float] = []
    train_returns: list[float] = []
    test_returns: list[float] = []
    for window in included:
        train = window.get(train_key) or {}
        test = window.get(test_key) or {}
        train_metric_value = train_value(train, metric)
        train_return_value = train_value(train, "total_return")
        if train_metric_value is not None and test.get(metric) is not None:
            train_metric.append(float(train_metric_value)); test_metric.append(float(test[metric]))
        if train_return_value is not None and test.get("total_return") is not None:
            train_returns.append(float(train_return_value)); test_returns.append(float(test["total_return"]))
    sharpes = [float((window.get(test_key) or {})["sharpe_ratio"]) for window in included if (window.get(test_key) or {}).get("sharpe_ratio") is not None]
    return {
        "ranking_metric": metric,
        "train_test_metric_correlation": _correlation(train_metric, test_metric),
        "train_test_return_correlation": _correlation(train_returns, test_returns),
        "test_positive_return_ratio": sum(value > 0 for value in test_returns) / len(test_returns) if test_returns else None,
        "test_positive_sharpe_ratio": sum(value > 0 for value in sharpes) / len(sharpes) if sharpes else None,
        "display_sharpe_threshold": 1.0,
        "test_sharpe_above_display_threshold_ratio": sum(value > 1 for value in sharpes) / len(sharpes) if sharpes else None,
        "display_only": True,
    }


def _run_rolling_structure_optimization(
    identifier: str,
    spec: MAOptimizationRequest,
    jobs: JobRepository,
    backtests: BacktestRepository,
    provider: Any,
) -> dict[str, Any] | None:
    """Run Structure V1 plus a parallel unchanged Performance comparator."""
    periods = spec.periods()
    windows = build_rolling_six_month_windows(spec.backtest.start_date, spec.backtest.end_date)
    # Structure mode executes a Performance comparator, a Structure-selected
    # test (possibly reusing the same canonical result), and the fixed-MA
    # comparator for every complete window.
    total = len(windows) * (len(periods) + 3)
    if not windows:
        jobs.finish(identifier, "FAILED_VALIDATION", "研究期間不足以建立前 6 個月訓練與後續測試區間。", result={
            "mode": "rolling_6m", "selection_mode": "STRUCTURE_V1", "rolling_windows": [],
            "structure_spec_version": STRUCTURE_SPEC_VERSION, "structure_spec_hash": STRUCTURE_SPEC_HASH,
            "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
        })
        return None

    current_job = jobs.get(identifier) or {}
    checkpoint = current_job.get("result") or {}
    prior_checkpoint_invalidated = False
    # Inspect the durable checkpoint before the first progress update.  The
    # progress row is intentionally rewritten during data preparation, so an
    # old structure checkpoint must be classified before it can be replaced.
    if (
        (
            checkpoint.get("selection_mode") == "STRUCTURE_V1"
            or bool(checkpoint.get("rolling_windows"))
            or "structure_spec_hash" in checkpoint
            or "structure_spec_version" in checkpoint
        )
        and checkpoint.get("structure_implementation_revision") != STRUCTURE_IMPLEMENTATION_REVISION
    ):
        prior_checkpoint_invalidated = True
        checkpoint = {
            "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
            "prior_checkpoint_invalidated": True,
        }

    jobs.progress(identifier, 0, total, "DATA_PREPARATION", "正在準備結構分析所需的歷史日線資料。", result={
        "mode": "rolling_6m", "selection_mode": "STRUCTURE_V1",
        "structure_spec_version": STRUCTURE_SPEC_VERSION, "structure_spec_hash": STRUCTURE_SPEC_HASH,
        "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
        "prior_checkpoint_invalidated": prior_checkpoint_invalidated,
        "rolling_progress": {"window": 0, "windows_total": len(windows), "phase": "DATA_PREPARATION", "ma_current": 0, "ma_total": len(periods)},
    })
    try:
        market = prepare_daily_market_data(
            spec.backtest,
            provider,
            evaluation_start=windows[0].train_start,
            evaluation_end=windows[-1].test_end,
            ma_period=spec.ma_max,
        )
    except BacktestError as exc:
        jobs.finish(identifier, "FAILED", "資料準備失敗；目前無法取得結構分析所需的歷史資料。", errors=[{
            "stage": "DATA_PREPARATION", "code": exc.code, "message": exc.message,
        }], result={
            "mode": "rolling_6m", "selection_mode": "STRUCTURE_V1", "rolling_windows": [],
            "failure_stage": "DATA_PREPARATION", "structure_spec_version": STRUCTURE_SPEC_VERSION,
            "structure_spec_hash": STRUCTURE_SPEC_HASH,
            "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
        })
        return None

    daily, provider_name = market.daily, market.provider
    fingerprint = _data_fingerprint(daily)
    cache_key = _rolling_cache_key(spec, fingerprint)
    for previous in jobs.list_by_type("MA_PERIOD_OPTIMIZATION", 100):
        if previous.get("id") == identifier or previous.get("status") != "COMPLETED":
            continue
        prior_result = previous.get("result") or {}
        if (
            prior_result.get("rolling_cache_key") == cache_key
            and prior_result.get("selection_mode") == "STRUCTURE_V1"
            and prior_result.get("structure_spec_hash") == STRUCTURE_SPEC_HASH
            and prior_result.get("structure_implementation_revision") == STRUCTURE_IMPLEMENTATION_REVISION
        ):
            copied = jobs.copy_structure_artifacts(
                str(previous["id"]),
                identifier,
                STRUCTURE_SPEC_HASH,
                STRUCTURE_IMPLEMENTATION_REVISION,
            )
            reused = {
                **prior_result,
                "job_cache_reused": True,
                "reused_from_job_id": previous["id"],
                "structure_artifacts_copied": copied,
            }
            jobs.progress(identifier, total, total, None, "已沿用相同設定、資料指紋與結構規格的完整滾動結果。", result=reused)
            return reused

    output_windows: list[dict[str, Any]] = list(checkpoint.get("rolling_windows") or [])
    skipped: list[dict[str, Any]] = list(checkpoint.get("skipped") or [])
    errors: list[dict[str, Any]] = list(current_job.get("errors") or [])
    done_indexes = {int(item.get("index")) for item in output_windows if item.get("index") is not None and item.get("status") in {"COMPLETED", "PROVISIONAL_PARTIAL_TEST", "TEST_FAILED", "NO_VALID_TRAIN_RESULT"}}
    # The candidate loop accounts for one completed phase per MA.  Three
    # independent test phases follow it (Performance, Structure, Fixed), so
    # a recovered window contributes periods + 3.  Structure Test remains a
    # distinct phase even when it reuses the Performance canonical result.
    completed_steps = len(done_indexes) * (len(periods) + 3)

    for window in windows:
        if (jobs.get(identifier) or {}).get("status") == "CANCELLED":
            return None
        if window.index in done_indexes:
            continue
        train_rows: list[dict[str, Any]] = []
        # Analyzer/audit output and Train performance references remain
        # outside the structure-only selector path until rank/select finish.
        analysis_by_candidate: dict[int, dict[str, Any]] = {}
        train_reference_by_ma: dict[int, dict[str, Any] | None] = {}
        structure_candidates: list[dict[str, Any]] = []
        window_skipped: list[dict[str, Any]] = []
        for position, ma_period in enumerate(periods, start=1):
            if (jobs.get(identifier) or {}).get("status") == "CANCELLED":
                return None
            request = spec.backtest.model_copy(deep=True)
            request.start_date, request.end_date = window.train_start, window.train_end
            request.parameters.ma_period = ma_period
            current = (
                f"正在分析第 {window.index} / {len(windows)} 個期間 · Train：{window.train_start.isoformat()} ～ {window.train_end.isoformat()} · "
                f"K 線結構候選：MA {position} / {len(periods)} · 目前分析：MA {ma_period}"
            )
            jobs.progress(identifier, completed_steps, total, current, "只使用 Train OHLC 與必要 pre-roll 分析均線結構。", errors=errors, result={
                "mode": "rolling_6m", "selection_mode": "STRUCTURE_V1", "rolling_windows": output_windows, "skipped": skipped,
                "structure_spec_version": STRUCTURE_SPEC_VERSION, "structure_spec_hash": STRUCTURE_SPEC_HASH,
                "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
                "rolling_progress": {"window": window.index, "windows_total": len(windows), "phase": "STRUCTURE_TRAIN", "ma_current": position, "ma_total": len(periods), "completed": position - 1},
            })
            train_row: dict[str, Any] | None = None
            try:
                canonical_daily = _canonical_input_frame(daily, request)
                train_row = _run_canonical(request, canonical_daily, provider_name, _data_fingerprint(canonical_daily), backtests)
                train_rows.append(train_row)
            except BacktestError as exc:
                item = {"window": window.index, "ma_period": ma_period, "code": exc.code, "message": "此期間的正式訓練回測資料不足。"}
                window_skipped.append(item); skipped.append(item)
            except Exception as exc:
                errors.append({"window": window.index, "ma_period": ma_period, "stage": "TRAIN_CANONICAL_BACKTEST", "code": "OPTIMIZATION_RUN_FAILED", "message": str(exc)[:500]})
            try:
                structure_frame = _structure_input_frame(daily, window, ma_period)
                analysis = analyze_ma_structure(
                    structure_frame,
                    ma_period,
                    request.parameters.ma_type,
                    train_start=window.train_start,
                    train_end=window.train_end,
                    strategy_request=request,
                )
                analysis_by_candidate[int(ma_period)] = analysis
                train_reference_by_ma[int(ma_period)] = train_row
                structure_candidates.append(build_structure_selector_candidate(analysis, position - 1))
            except StructureValidationError as exc:
                item = {"window": window.index, "ma_period": ma_period, "code": exc.code, "message": "此期間的均線結構資料不足。"}
                window_skipped.append(item); skipped.append(item)
            except Exception as exc:
                errors.append({"window": window.index, "ma_period": ma_period, "stage": "STRUCTURE_ANALYSIS", "code": "STRUCTURE_ANALYSIS_FAILED", "message": str(exc)[:500]})
            completed_steps += 1

        if not structure_candidates:
            # No MA can be selected, so the three per-window test phases are
            # skipped but still accounted for in the durable progress total.
            completed_steps += 3
            output_windows.append({
                **window.as_dict(), "status": "NO_VALID_TRAIN_RESULT", "aggregate_included": False,
                "train_ranking": sorted(train_rows, key=lambda row: row.get("ma_period", 0)), "structure_ranking": [], "structure_top5": [],
                "skipped": window_skipped, "train_sessions": _actual_session_bounds(daily, window.train_start, window.train_end),
                "test_sessions": _actual_session_bounds(daily, window.test_start, window.test_end),
                "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
            })
            jobs.progress(identifier, completed_steps, total, None, f"第 {window.index}/{len(windows)} 個期間沒有可用的結構候選。", errors=errors, result={
                "mode": "rolling_6m", "selection_mode": "STRUCTURE_V1", "rolling_windows": output_windows, "skipped": skipped,
                "structure_spec_version": STRUCTURE_SPEC_VERSION, "structure_spec_hash": STRUCTURE_SPEC_HASH,
                "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
                "rolling_progress": {"window": window.index, "windows_total": len(windows), "phase": "WINDOW_SKIPPED", "ma_current": len(periods), "ma_total": len(periods)},
            })
            continue

        ranked_candidates = rank_structure_candidates(structure_candidates)
        structure_best_full, structure_tie_break_reason = select_structure_ma(ranked_candidates)
        performance_best, performance_tie_break_reason = _select_best(train_rows, spec.ranking_metric) if train_rows else (None, "NO_VALID_TRAIN_RESULT")
        structure_ranking_full = sorted(ranked_candidates, key=structure_candidate_sort_key)
        # Keep full events/OHLC only in the dedicated artifact table.  The job
        # result remains compact and still contains every auditable metric.
        structure_ranking = [
            _structure_summary(
                analysis_by_candidate[int(row["ma_period"])],
                row,
                train_reference_by_ma.get(int(row["ma_period"])),
                int(row.get("candidate_index", index)),
            )
            for index, row in enumerate(structure_ranking_full)
        ]
        structure_best = next(item for item in structure_ranking if int(item["ma_period"]) == int(structure_best_full["ma_period"]))
        for rank, row in enumerate(structure_ranking, start=1):
            row["structure_rank"] = rank
            row["rank"] = rank
            row["artifact_available"] = rank <= 5
        structure_top5 = structure_ranking[:5]
        for candidate in structure_ranking_full[:5]:
            analysis = analysis_by_candidate.get(int(candidate["ma_period"]))
            artifact = analysis.get("chart_artifact") if analysis else None
            if isinstance(artifact, dict):
                artifact = {**artifact, "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION}
                jobs.put_structure_artifact(identifier, window.index, int(candidate["ma_period"]), STRUCTURE_SPEC_HASH, artifact)

        performance_test: dict[str, Any] | None = None
        structure_test: dict[str, Any] | None = None
        fixed_test: dict[str, Any] | None = None
        if performance_best is not None:
            test_request = spec.backtest.model_copy(deep=True)
            test_request.start_date, test_request.end_date = window.test_start, window.test_end
            test_request.parameters.ma_period = int(performance_best["ma_period"])
            jobs.progress(identifier, completed_steps, total, f"期間 {window.index}/{len(windows)} · Performance Test MA {performance_best['ma_period']}", "正在執行 Performance comparator 的獨立測試區間。", result={
                "mode": "rolling_6m", "selection_mode": "STRUCTURE_V1", "rolling_windows": output_windows, "skipped": skipped,
                "structure_spec_version": STRUCTURE_SPEC_VERSION, "structure_spec_hash": STRUCTURE_SPEC_HASH,
                "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
                "rolling_progress": {"window": window.index, "windows_total": len(windows), "phase": "PERFORMANCE_TEST", "ma_current": len(periods), "ma_total": len(periods)},
            })
            try:
                test_daily = _canonical_input_frame(daily, test_request)
                performance_test = _run_canonical(test_request, test_daily, provider_name, _data_fingerprint(test_daily), backtests)
            except Exception as exc:
                errors.append({"window": window.index, "stage": "PERFORMANCE_TEST_CANONICAL_BACKTEST", "code": "OPTIMIZATION_TEST_FAILED", "message": str(exc)[:500]})
        completed_steps += 1

        structure_request = spec.backtest.model_copy(deep=True)
        structure_request.start_date, structure_request.end_date = window.test_start, window.test_end
        structure_request.parameters.ma_period = int(structure_best["ma_period"])
        if performance_test is not None and int(structure_best["ma_period"]) == int(performance_best["ma_period"]):
            structure_test = performance_test
        else:
            jobs.progress(identifier, completed_steps, total, f"期間 {window.index}/{len(windows)} · Structure Test MA {structure_best['ma_period']}", "正在執行 Structure-selected 的獨立測試區間。", result={
                "mode": "rolling_6m", "selection_mode": "STRUCTURE_V1", "rolling_windows": output_windows, "skipped": skipped,
                "structure_spec_version": STRUCTURE_SPEC_VERSION, "structure_spec_hash": STRUCTURE_SPEC_HASH,
                "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
                "rolling_progress": {"window": window.index, "windows_total": len(windows), "phase": "STRUCTURE_TEST", "ma_current": len(periods), "ma_total": len(periods)},
            })
            try:
                structure_daily = _canonical_input_frame(daily, structure_request)
                structure_test = _run_canonical(structure_request, structure_daily, provider_name, _data_fingerprint(structure_daily), backtests)
            except Exception as exc:
                errors.append({"window": window.index, "stage": "STRUCTURE_TEST_CANONICAL_BACKTEST", "code": "STRUCTURE_TEST_FAILED", "message": str(exc)[:500]})
        completed_steps += 1

        fixed_request = spec.backtest.model_copy(deep=True)
        fixed_request.start_date, fixed_request.end_date = window.test_start, window.test_end
        fixed_request.parameters.ma_period = spec.rolling.fixed_ma_period
        jobs.progress(identifier, completed_steps, total, f"期間 {window.index}/{len(windows)} · Fixed MA {spec.rolling.fixed_ma_period}", "正在執行固定均線比較。", result={
            "mode": "rolling_6m", "selection_mode": "STRUCTURE_V1", "rolling_windows": output_windows, "skipped": skipped,
            "structure_spec_version": STRUCTURE_SPEC_VERSION, "structure_spec_hash": STRUCTURE_SPEC_HASH,
            "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
            "rolling_progress": {"window": window.index, "windows_total": len(windows), "phase": "FIXED_TEST", "ma_current": len(periods), "ma_total": len(periods)},
        })
        try:
            fixed_daily = _canonical_input_frame(daily, fixed_request)
            fixed_test = _run_canonical(fixed_request, fixed_daily, provider_name, _data_fingerprint(fixed_daily), backtests)
        except Exception as exc:
            errors.append({"window": window.index, "stage": "FIXED_MA_CANONICAL_BACKTEST", "code": "FIXED_MA_TEST_FAILED", "message": str(exc)[:500]})
        completed_steps += 1

        selected_test = structure_test
        aggregate_included = bool(window.complete and selected_test is not None)
        structure_minus_performance = {
            "return_delta": (float(structure_test["total_return"]) - float(performance_test["total_return"])) if structure_test and performance_test and structure_test.get("total_return") is not None and performance_test.get("total_return") is not None else None,
            "sharpe_delta": (float(structure_test["sharpe_ratio"]) - float(performance_test["sharpe_ratio"])) if structure_test and performance_test and structure_test.get("sharpe_ratio") is not None and performance_test.get("sharpe_ratio") is not None else None,
            "mdd_delta": (float(structure_test["max_drawdown"]) - float(performance_test["max_drawdown"])) if structure_test and performance_test and structure_test.get("max_drawdown") is not None and performance_test.get("max_drawdown") is not None else None,
            "pnl_delta": (float(structure_test["net_pnl"]) - float(performance_test["net_pnl"])) if structure_test and performance_test and structure_test.get("net_pnl") is not None and performance_test.get("net_pnl") is not None else None,
        }
        output_windows.append({
            **window.as_dict(), "status": "TEST_FAILED" if selected_test is None else ("COMPLETED" if window.complete else "PROVISIONAL_PARTIAL_TEST"),
            "aggregate_included": aggregate_included,
            "selection_mode": "STRUCTURE_V1", "selected_ma": int(structure_best["ma_period"]),
            "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
            "performance_best": performance_best, "structure_best": structure_best,
            # Keep the exact post-validation selector object available for
            # audits.  ``structure_best`` remains the backwards-compatible
            # display/detail join (analyzer + Train reference), while this
            # field is the object that was actually passed to rank/select.
            "structure_selector_best": copy.deepcopy(structure_best_full),
            "train_best": performance_best,
            "performance_tie_break_reason": performance_tie_break_reason,
            "structure_tie_break_reason": structure_tie_break_reason,
            "tie_break_reason": structure_tie_break_reason,
            "train_ranking": sorted(train_rows, key=lambda row: row.get("ma_period", 0)),
            "structure_ranking": structure_ranking,
            "structure_top5": structure_top5,
            "performance_test_result": performance_test,
            "structure_test_result": structure_test,
            "test_result": selected_test,
            "fixed_ma_period": spec.rolling.fixed_ma_period,
            "fixed_test_result": fixed_test,
            "test_vs_fixed": {
                "return_delta": (float(selected_test["total_return"]) - float(fixed_test["total_return"])) if selected_test and fixed_test and selected_test.get("total_return") is not None and fixed_test.get("total_return") is not None else None,
                "sharpe_delta": (float(selected_test["sharpe_ratio"]) - float(fixed_test["sharpe_ratio"])) if selected_test and fixed_test and selected_test.get("sharpe_ratio") is not None and fixed_test.get("sharpe_ratio") is not None else None,
            },
            "structure_minus_performance": structure_minus_performance,
            "skipped": window_skipped,
            "train_sessions": _actual_session_bounds(daily, window.train_start, window.train_end),
            "test_sessions": _actual_session_bounds(daily, window.test_start, window.test_end),
            "selection_source": "TRAIN_STRUCTURE_ONLY",
            "independent_flat_test": True,
        })
        done_indexes.add(window.index)
        jobs.progress(identifier, completed_steps, total, None, f"第 {window.index}/{len(windows)} 個期間已完成。", errors=errors, result={
            "mode": "rolling_6m", "selection_mode": "STRUCTURE_V1", "rolling_windows": output_windows, "skipped": skipped,
            "structure_spec_version": STRUCTURE_SPEC_VERSION, "structure_spec_hash": STRUCTURE_SPEC_HASH,
            "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
            "rolling_progress": {"window": window.index, "windows_total": len(windows), "phase": "WINDOW_COMPLETE", "ma_current": len(periods), "ma_total": len(periods), "completed": len(periods)},
        })

    complete_windows = [item for item in output_windows if item.get("aggregate_included")]
    result = {
        "mode": "rolling_6m", "selection_mode": "STRUCTURE_V1",
        "structure_spec_version": STRUCTURE_SPEC_VERSION, "structure_spec_hash": STRUCTURE_SPEC_HASH,
        "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
        "comparison_mode": "RETROSPECTIVE_OOS",
        "ranking_metric": spec.ranking_metric,
        "rolling_definition": {
            "train_calendar_months": 6, "test_calendar_months": 6,
            "selection_source": "PRIOR_TRAIN_ONLY", "test_segments_start_flat": True,
            "cross_window_position_carry": False,
        },
        "rolling_windows": output_windows,
        "complete_windows": len(complete_windows),
        "provisional_windows": sum(not item.complete for item in windows),
        "performance_aggregate": _aggregate_test_segments(output_windows, "performance_test_result"),
        "structure_aggregate": _aggregate_test_segments(output_windows, "structure_test_result"),
        "test_only_aggregate": _aggregate_test_segments(output_windows, "structure_test_result"),
        "fixed_ma_aggregate": _aggregate_test_segments(output_windows, "fixed_test_result"),
        "selection_history": [{
            "window": item["index"], "test_start": item["test_start"], "test_end": item["test_end"],
            "selected_ma": item.get("selected_ma"), "performance_selected_ma": (item.get("performance_best") or {}).get("ma_period"),
            "structure_selected_ma": (item.get("structure_best") or {}).get("ma_period"), "aggregate_included": item.get("aggregate_included", False),
        } for item in output_windows if item.get("selected_ma") is not None],
        "performance_selection_summary": _selection_summary([{**item, "selected_ma": (item.get("performance_best") or {}).get("ma_period")} for item in output_windows if item.get("performance_best")]),
        "structure_selection_summary": _selection_summary([{**item, "selected_ma": (item.get("structure_best") or {}).get("ma_period")} for item in output_windows if item.get("structure_best")]),
        "selection_summary": _selection_summary(output_windows),
        "performance_train_test_relationship": _relationship_track(output_windows, "performance_best", "performance_test_result", spec.ranking_metric),
        "structure_train_test_relationship": _relationship_track(output_windows, "structure_best", "structure_test_result", spec.ranking_metric),
        "train_test_relationship": _relationship_track(output_windows, "structure_best", "structure_test_result", spec.ranking_metric),
        "skipped": skipped, "data_fingerprint": fingerprint, "provider": provider_name,
        "data_coverage": {
            "first_date": daily.index[0].date().isoformat(), "last_date": daily.index[-1].date().isoformat(),
            "bars": len(daily), "warnings": list(getattr(market, "warnings", []) or []),
        },
        "canonical_engine": True, "rolling_cache_key": cache_key, "job_cache_reused": False,
        "prior_checkpoint_invalidated": prior_checkpoint_invalidated,
        "non_predictive_comparison": "retrospective OOS comparison; does not establish future predictive ability",
    }
    if not complete_windows:
        jobs.finish(identifier, "FAILED_VALIDATION", "沒有可納入正式彙總的完整 6 個月測試區間。", errors=errors, result=result)
        return None
    if errors or skipped:
        jobs.finish(identifier, "PARTIAL_SUCCESS", "結構滾動最佳化已完成；部分均線或期間未能執行。", errors=errors, result=result)
        return None
    return result


def _run_rolling_ma_optimization(
    identifier: str,
    payload: dict[str, Any],
    jobs: JobRepository,
    backtests: BacktestRepository,
    provider: Any,
) -> dict[str, Any] | None:
    spec = MAOptimizationRequest.model_validate(payload)
    if spec.selection_mode == "STRUCTURE_V1":
        return _run_rolling_structure_optimization(identifier, spec, jobs, backtests, provider)
    periods = spec.periods()
    windows = build_rolling_six_month_windows(spec.backtest.start_date, spec.backtest.end_date)
    total = len(windows) * (len(periods) + 2)
    if not windows:
        jobs.finish(identifier, "FAILED_VALIDATION", "研究期間不足以建立前 6 個月訓練與後續測試區間。", result={"mode": "rolling_6m", "rolling_windows": []})
        return None

    jobs.progress(identifier, 0, total, "DATA_PREPARATION", "正在準備所有滾動期間共用的指標預熱日線資料。")
    try:
        market = prepare_daily_market_data(
            spec.backtest,
            provider,
            evaluation_start=windows[0].train_start,
            evaluation_end=windows[-1].test_end,
            ma_period=spec.ma_max,
        )
    except BacktestError as exc:
        jobs.finish(identifier, "FAILED", "資料準備失敗；目前無法取得滾動最佳化所需的歷史資料。", errors=[{
            "stage": "DATA_PREPARATION", "code": exc.code, "message": exc.message,
        }], result={"mode": "rolling_6m", "rolling_windows": [], "failure_stage": "DATA_PREPARATION"})
        return None

    daily, provider_name = market.daily, market.provider
    fingerprint = _data_fingerprint(daily)
    cache_key = _rolling_cache_key(spec, fingerprint)
    for previous in jobs.list_by_type("MA_PERIOD_OPTIMIZATION", 100):
        if previous.get("id") == identifier or previous.get("status") != "COMPLETED":
            continue
        prior_result = previous.get("result") or {}
        if prior_result.get("rolling_cache_key") == cache_key:
            reused = {**prior_result, "job_cache_reused": True, "reused_from_job_id": previous["id"]}
            jobs.progress(identifier, total, total, None, "已沿用相同設定與資料指紋的完整滾動結果。", result=reused)
            return reused

    output_windows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    completed_steps = 0
    for window in windows:
        train_rows: list[dict[str, Any]] = []
        window_skipped: list[dict[str, Any]] = []
        for position, ma_period in enumerate(periods, start=1):
            if (jobs.get(identifier) or {}).get("status") == "CANCELLED":
                return None
            request = spec.backtest.model_copy(deep=True)
            request.start_date, request.end_date = window.train_start, window.train_end
            request.parameters.ma_period = ma_period
            current = (
                f"期間 {window.index}/{len(windows)} · Train {window.train_start.isoformat()}～{window.train_end.isoformat()} "
                f"· MA {position}/{len(periods)}（MA {ma_period}）"
            )
            jobs.progress(identifier, completed_steps, total, current, "只使用此訓練區間選擇下一期均線。", errors=errors, result={
                "mode": "rolling_6m", "rolling_windows": output_windows, "skipped": skipped,
                "rolling_progress": {"window": window.index, "windows_total": len(windows), "phase": "TRAIN", "ma_current": position, "ma_total": len(periods)},
            })
            try:
                canonical_daily = _canonical_input_frame(daily, request)
                row = _run_canonical(request, canonical_daily, provider_name, _data_fingerprint(canonical_daily), backtests)
                train_rows.append(row)
            except BacktestError as exc:
                item = {"window": window.index, "ma_period": ma_period, "code": exc.code, "message": "此期間的已完成歷史資料不足。"}
                window_skipped.append(item); skipped.append(item)
            except Exception as exc:
                errors.append({"window": window.index, "ma_period": ma_period, "stage": "TRAIN_CANONICAL_BACKTEST", "code": "OPTIMIZATION_RUN_FAILED", "message": str(exc)[:500]})
            completed_steps += 1

        if not train_rows:
            completed_steps += 2
            output_windows.append({
                **window.as_dict(), "status": "NO_VALID_TRAIN_RESULT", "aggregate_included": False,
                "train_ranking": [], "skipped": window_skipped,
                "train_sessions": _actual_session_bounds(daily, window.train_start, window.train_end),
                "test_sessions": _actual_session_bounds(daily, window.test_start, window.test_end),
            })
            continue

        best, tie_break_reason = _select_best(train_rows, spec.ranking_metric)
        test_request = spec.backtest.model_copy(deep=True)
        test_request.start_date, test_request.end_date = window.test_start, window.test_end
        test_request.parameters.ma_period = int(best["ma_period"])
        jobs.progress(identifier, completed_steps, total, f"期間 {window.index}/{len(windows)} · Test MA {best['ma_period']}", "正在執行下一個 6 個月的獨立測試區間。")
        try:
            test_daily = _canonical_input_frame(daily, test_request)
            test_row = _run_canonical(test_request, test_daily, provider_name, _data_fingerprint(test_daily), backtests)
        except Exception as exc:
            errors.append({"window": window.index, "stage": "TEST_CANONICAL_BACKTEST", "code": "OPTIMIZATION_TEST_FAILED", "message": str(exc)[:500]})
            test_row = None
        completed_steps += 1

        fixed_request = spec.backtest.model_copy(deep=True)
        fixed_request.start_date, fixed_request.end_date = window.test_start, window.test_end
        fixed_request.parameters.ma_period = spec.rolling.fixed_ma_period
        jobs.progress(identifier, completed_steps, total, f"期間 {window.index}/{len(windows)} · Fixed MA {spec.rolling.fixed_ma_period}", "正在執行使用者指定的固定均線比較。")
        try:
            fixed_daily = _canonical_input_frame(daily, fixed_request)
            fixed_row = _run_canonical(fixed_request, fixed_daily, provider_name, _data_fingerprint(fixed_daily), backtests)
        except Exception as exc:
            errors.append({"window": window.index, "stage": "FIXED_MA_CANONICAL_BACKTEST", "code": "FIXED_MA_TEST_FAILED", "message": str(exc)[:500]})
            fixed_row = None
        completed_steps += 1

        aggregate_included = bool(window.complete and test_row is not None)
        output_windows.append({
            **window.as_dict(),
            "status": "TEST_FAILED" if test_row is None else ("COMPLETED" if window.complete else "PROVISIONAL_PARTIAL_TEST"),
            "aggregate_included": aggregate_included,
            "selected_ma": int(best["ma_period"]),
            "tie_break_reason": tie_break_reason,
            "train_best": best,
            "train_ranking": sorted(train_rows, key=lambda row: row["ma_period"]),
            "train_stability": _stability(train_rows, best, spec.ranking_metric, spec.ma_step),
            "test_result": test_row,
            "fixed_ma_period": spec.rolling.fixed_ma_period,
            "fixed_test_result": fixed_row,
            "test_vs_fixed": {
                "return_delta": (float(test_row["total_return"]) - float(fixed_row["total_return"])) if test_row and fixed_row else None,
                "sharpe_delta": (float(test_row["sharpe_ratio"]) - float(fixed_row["sharpe_ratio"])) if test_row and fixed_row and test_row.get("sharpe_ratio") is not None and fixed_row.get("sharpe_ratio") is not None else None,
            },
            "skipped": window_skipped,
            "train_sessions": _actual_session_bounds(daily, window.train_start, window.train_end),
            "test_sessions": _actual_session_bounds(daily, window.test_start, window.test_end),
            "selection_source": "TRAIN_ONLY",
            "independent_flat_test": True,
        })
        jobs.progress(identifier, completed_steps, total, None, f"第 {window.index}/{len(windows)} 個期間已完成。", errors=errors, result={
            "mode": "rolling_6m", "rolling_windows": output_windows, "skipped": skipped,
            "rolling_progress": {"window": window.index, "windows_total": len(windows), "phase": "WINDOW_COMPLETE"},
        })

    complete_windows = [window for window in output_windows if window.get("aggregate_included")]
    result = {
        "mode": "rolling_6m",
        "ranking_metric": spec.ranking_metric,
        "rolling_definition": {
            "train_calendar_months": 6, "test_calendar_months": 6,
            "selection_source": "PRIOR_TRAIN_ONLY", "test_segments_start_flat": True,
            "cross_window_position_carry": False,
        },
        "rolling_windows": output_windows,
        "complete_windows": len(complete_windows),
        "provisional_windows": sum(not window.complete for window in windows),
        "test_only_aggregate": _aggregate_test_segments(output_windows, "test_result"),
        "fixed_ma_aggregate": _aggregate_test_segments(output_windows, "fixed_test_result"),
        "selection_history": [{
            "window": window["index"], "test_start": window["test_start"], "test_end": window["test_end"],
            "selected_ma": window.get("selected_ma"), "aggregate_included": window.get("aggregate_included", False),
        } for window in output_windows if window.get("selected_ma") is not None],
        "selection_summary": _selection_summary(output_windows),
        "train_test_relationship": _relationship(output_windows, spec.ranking_metric),
        "skipped": skipped,
        "data_fingerprint": fingerprint,
        "provider": provider_name,
        "data_coverage": {
            "first_date": daily.index[0].date().isoformat(), "last_date": daily.index[-1].date().isoformat(),
            "bars": len(daily), "warnings": list(getattr(market, "warnings", []) or []),
        },
        "canonical_engine": True,
        "rolling_cache_key": cache_key,
        "job_cache_reused": False,
    }
    if not complete_windows:
        jobs.finish(identifier, "FAILED_VALIDATION", "沒有可納入正式彙總的完整 6 個月測試區間。", errors=errors, result=result)
        return None
    if errors or skipped:
        jobs.finish(identifier, "PARTIAL_SUCCESS", "滾動最佳化已完成；部分均線或期間未能執行。", errors=errors, result=result)
        return None
    return result


def run_ma_optimization(
    identifier: str,
    payload: dict[str, Any],
    jobs: JobRepository,
    backtests: BacktestRepository,
    provider: Any,
) -> dict[str, Any] | None:
    spec = MAOptimizationRequest.model_validate(payload)
    if spec.mode == "rolling_6m":
        return _run_rolling_ma_optimization(identifier, payload, jobs, backtests, provider)
    return _run_single_ma_optimization(identifier, payload, jobs, backtests, provider)
