from __future__ import annotations

from datetime import date
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from app.optimization.structure import (
    STRUCTURE_IMPLEMENTATION_REVISION,
    STRUCTURE_SPEC_HASH,
    STRUCTURE_SPEC_VERSION,
    StructureValidationError,
    _Observation,
    _breakout_analysis,
    _confirmation_analysis,
    _retest_analysis,
    analyze_ma_structure,
    build_structure_selector_candidate,
    rank_structure_candidates,
    select_structure_ma,
    validate_structure_selector_candidate,
    wilson_lower_bound,
)
from app.data.base import MarketData
from app.backtest.models import BacktestRequest
from app.backtest.engine import BacktestEngine
from app.backtest.data_preparation import prepare_daily_market_data
from app.jobs.repository import JobRepository
from app.db.repository import BacktestRepository
from app.optimization.models import MAOptimizationRequest
from app.optimization.runner import _rolling_cache_key, run_ma_optimization


def _bars(count: int = 12) -> pd.DataFrame:
    index = pd.bdate_range("2024-01-02", periods=count, tz="UTC")
    close = np.array([90, 90, 90, 101, 103, 101, 99, 102, 104, 103, 101, 102], dtype=float)[:count]
    return pd.DataFrame({
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": np.full(len(close), 1_000_000.0),
    }, index=index)


def _selector(
    ma_period: int,
    candidate_index: int,
    components: tuple[float, float, float, float] = (0.5, 0.5, 0.5, 0.5),
    *,
    resolved: int = 4,
    violation: float | None = 0.1,
) -> dict:
    regime, retest, breakout, confirmation = components
    return {
        "ma_period": ma_period,
        "candidate_index": candidate_index,
        "structure_spec_version": STRUCTURE_SPEC_VERSION,
        "structure_spec_hash": STRUCTURE_SPEC_HASH,
        "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
        "selector_components": {
            "regime": regime,
            "retest": retest,
            "breakout": breakout,
            "confirmation": confirmation,
        },
        "breakout_wilson_lower": breakout,
        "total_resolved_structural_events": resolved,
        "confirmation_violation_rate": violation,
    }


def _analysis_template(*, ma_period: int, retest_component: float, breakout_component: float) -> dict:
    return {
        "valid": True,
        "ma_period": ma_period,
        "structure_spec_version": STRUCTURE_SPEC_VERSION,
        "structure_spec_hash": STRUCTURE_SPEC_HASH,
        "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
        "regime": {"regime_component": 0.5},
        "retest": {
            "retest_raw": 1.0,
            "retest_component": retest_component,
            "retest_wilson_lower": retest_component,
            "retest_resolved_count": 18,
        },
        "breakout": {
            "breakout_raw": 1.0,
            "breakout_component": breakout_component,
            "breakout_wilson_lower": breakout_component,
            "breakout_resolved_count": 18,
        },
        "confirmation": {
            "confirmation_raw": 1.0,
            "confirmation_component": 0.5,
            "confirmation_violation_rate": 0.0,
            "confirmation_resolved_count": 1,
        },
        "total_resolved_structural_events": 37,
    }


def _observation(day: str, *, open_: float = 100.0, high: float = 101.0, low: float = 99.0, close: float = 100.0, ma: float | None = 100.0, reference: float | None = 100.0, side: str = "NEUTRAL") -> _Observation:
    return _Observation(
        position=0,
        timestamp=pd.Timestamp(day, tz="UTC"),
        open=open_, high=high, low=low, close=close, volume=1_000_000.0,
        ma=ma, reference_ma=reference, side=side,
    )


def test_real_analyzer_output_normalizes_before_rank_and_select(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.optimization.structure.moving_average",
        lambda close, period, ma_type: pd.Series(100.0, index=close.index, dtype=float),
    )
    frame = _bars()
    analyzed = analyze_ma_structure(frame, 20, "sma", train_start=frame.index[3].date(), train_end=date(2024, 1, 17))
    candidate = build_structure_selector_candidate(analyzed, 0)
    ranked = rank_structure_candidates([candidate])
    selected, reason = select_structure_ma([candidate])
    assert ranked[0]["structure_ranking"]["ranking_values"]["retest"] == analyzed["retest"]["retest_component"]
    assert selected["ma_period"] == 20
    assert reason == "CANONICAL_CANDIDATE_ORDER"
    assert "train_reference" not in selected


def test_wilson_component_beats_raw_rate_for_retest_and_breakout() -> None:
    low_sample = _analysis_template(
        ma_period=20,
        retest_component=wilson_lower_bound(1, 1),
        breakout_component=wilson_lower_bound(1, 1),
    )
    high_sample = _analysis_template(
        ma_period=30,
        retest_component=wilson_lower_bound(15, 18),
        breakout_component=wilson_lower_bound(15, 18),
    )
    # Both raw rates are deliberately higher for the low-sample candidate;
    # selection must use pooled Wilson lower bounds instead.
    low_sample["retest"]["retest_raw"] = 1.0
    low_sample["breakout"]["breakout_raw"] = 1.0
    high_sample["retest"]["retest_raw"] = 15 / 18
    high_sample["breakout"]["breakout_raw"] = 15 / 18
    a = build_structure_selector_candidate(low_sample, 0)
    b = build_structure_selector_candidate(high_sample, 1)
    ranked = rank_structure_candidates([a, b])
    assert ranked[1]["selector_components"]["retest"] > ranked[0]["selector_components"]["retest"]
    assert ranked[1]["selector_components"]["breakout"] > ranked[0]["selector_components"]["breakout"]
    assert ranked[1]["retest_percentile"] > ranked[0]["retest_percentile"]
    assert ranked[1]["breakout_percentile"] > ranked[0]["breakout_percentile"]
    assert select_structure_ma([a, b])[0]["ma_period"] == 30


def test_composite_uses_wilson_values_and_input_is_immutable() -> None:
    candidates = [_selector(20, 0, (0.2, 0.1, 0.3, 0.4)), _selector(30, 1, (0.8, 0.9, 0.7, 0.6))]
    before = deepcopy(candidates)
    ranked = rank_structure_candidates(candidates)
    assert candidates == before
    expected = sum(ranked[1]["structure_ranking"]["percentiles"].values()) / 4
    assert ranked[1]["structure_ranking"]["composite"] == pytest.approx(expected)
    assert ranked[1]["ma_structure_score"] == pytest.approx(expected)


def test_selector_contract_rejects_legacy_aliases_nan_and_nested_performance() -> None:
    candidate = _selector(20, 0)
    with pytest.raises(StructureValidationError):
        rank_structure_candidates([dict(candidate, train_reference={"total_return": 99})])
    with pytest.raises(StructureValidationError):
        rank_structure_candidates([dict(candidate, breakout_component=0.99)])
    with pytest.raises(StructureValidationError):
        rank_structure_candidates([dict(candidate, selector_components={**candidate["selector_components"], "retest": float("nan")})])


def test_raw_null_is_not_synthesized_into_selector_or_display_fields() -> None:
    analyzed = _analysis_template(ma_period=20, retest_component=0.2, breakout_component=0.3)
    analyzed["confirmation"]["confirmation_raw"] = None
    analyzed["confirmation"]["confirmation_component"] = 0.0
    candidate = build_structure_selector_candidate(analyzed, 0)
    ranked = rank_structure_candidates([candidate])[0]
    assert analyzed["confirmation"]["confirmation_raw"] is None
    assert "confirmation_raw" not in ranked
    assert ranked["selector_components"]["confirmation"] == 0.0


@pytest.mark.parametrize(
    ("candidates", "expected"),
    [
        ([_selector(20, 0, (0.1, 0.1, 0.1, 0.1)), _selector(30, 1, (0.9, 0.9, 0.9, 0.9))], "STRUCTURE_SCORE"),
        ([_selector(20, 0, (0.0, 0.5, 0.9, 0.5)), _selector(30, 1, (0.9, 0.5, 0.1, 0.5))], "HIGHER_BREAKOUT_WILSON"),
        ([_selector(20, 0, resolved=8), _selector(30, 1, resolved=4)], "MORE_RESOLVED_EVENTS"),
        ([_selector(20, 0, violation=0.1), _selector(30, 1, violation=0.2)], "LOWER_CONFIRMATION_VIOLATION"),
        ([_selector(20, 0), _selector(30, 1)], "SMALLER_MA_PERIOD"),
        ([_selector(20, 1), _selector(20, 0)], "CANONICAL_CANDIDATE_ORDER"),
    ],
)
def test_reason_is_first_differing_final_order_key(candidates: list[dict], expected: str) -> None:
    _, reason = select_structure_ma(candidates)
    assert reason == expected


def test_single_candidate_reason_is_canonical() -> None:
    _, reason = select_structure_ma([_selector(20, 0)])
    assert reason == "CANONICAL_CANDIDATE_ORDER"


def test_performance_mutation_cannot_change_a_normalized_selection() -> None:
    analysis = _analysis_template(ma_period=20, retest_component=0.7, breakout_component=0.7)
    selector = build_structure_selector_candidate(analysis, 0)
    before = select_structure_ma([selector])[0]
    analysis["train_reference"] = {"total_return": 10_000_000, "sharpe_ratio": 10_000_000}
    after = select_structure_ma([selector])[0]
    assert after == before
    assert "train_reference" not in after


def test_implementation_revision_is_required_and_old_revision_fails_closed() -> None:
    candidate = _selector(20, 0)
    assert candidate["structure_implementation_revision"] == "MA_STRUCTURE_V1_IMPL_2"
    with pytest.raises(StructureValidationError, match="invalidated"):
        rank_structure_candidates([dict(candidate, structure_implementation_revision="MA_STRUCTURE_V1_IMPL_1")])


def test_selector_contract_rejects_fractional_identity_and_invalid_ranking_namespace() -> None:
    candidate = _selector(20, 0)
    with pytest.raises(StructureValidationError):
        rank_structure_candidates([dict(candidate, ma_period=20.5)])
    with pytest.raises(StructureValidationError):
        rank_structure_candidates([dict(candidate, candidate_index=0.5)])
    ranked = rank_structure_candidates([candidate])[0]
    malformed = dict(ranked, structure_ranking={"ranking_values": {}, "percentiles": {}, "composite": 0.0})
    with pytest.raises(StructureValidationError):
        validate_structure_selector_candidate(malformed)


def test_structure_artifact_copy_requires_current_revision_when_requested(tmp_path) -> None:
    jobs = JobRepository(tmp_path / "jobs.sqlite3")
    source, _ = jobs.create("MA_PERIOD_OPTIMIZATION", {}, 1)
    target, _ = jobs.create("MA_PERIOD_OPTIMIZATION", {"copy": True}, 1)
    jobs.put_structure_artifact(
        source["id"], 1, 20, STRUCTURE_SPEC_HASH,
        {"ohlc": [], "events": [], "structure_implementation_revision": "MA_STRUCTURE_V1_IMPL_1"},
    )
    assert jobs.copy_structure_artifacts(
        source["id"], target["id"], STRUCTURE_SPEC_HASH, STRUCTURE_IMPLEMENTATION_REVISION
    ) == 0
    assert jobs.get_structure_artifact(target["id"], 1, 20, STRUCTURE_SPEC_HASH) is None

    jobs.put_structure_artifact(
        source["id"], 1, 20, STRUCTURE_SPEC_HASH,
        {"ohlc": [], "events": [], "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION},
    )
    assert jobs.copy_structure_artifacts(
        source["id"], target["id"], STRUCTURE_SPEC_HASH, STRUCTURE_IMPLEMENTATION_REVISION
    ) == 1


def test_structure_cache_identity_includes_revision_but_performance_namespace_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    base = {
        "mode": "rolling_6m", "selection_mode": "STRUCTURE_V1",
        "backtest": {"ticker": "NVDA", "strategy": "simple", "start_date": "2022-01-01", "end_date": "2024-01-01"},
        "ma_min": 20, "ma_max": 30, "ma_step": 10, "ranking_metric": "sharpe_ratio",
    }
    structure_spec = MAOptimizationRequest.model_validate(base)
    current_key = _rolling_cache_key(structure_spec, "fingerprint")
    monkeypatch.setattr("app.optimization.runner.STRUCTURE_IMPLEMENTATION_REVISION", "MA_STRUCTURE_V1_IMPL_1")
    old_key = _rolling_cache_key(structure_spec, "fingerprint")
    assert current_key != old_key

    performance_spec = MAOptimizationRequest.model_validate({**base, "selection_mode": "PERFORMANCE"})
    performance_current = _rolling_cache_key(performance_spec, "fingerprint")
    performance_old = _rolling_cache_key(performance_spec, "fingerprint")
    assert performance_current == performance_old


@pytest.mark.parametrize("close", [99.0, 100.0, 101.0])
def test_bear_retest_mirror_uses_strict_close_below_ma(close: float) -> None:
    observations = [
        _observation("2024-01-02", close=100.0, ma=100.0, reference=100.0),
        _observation("2024-01-03", close=90.0, ma=100.0, reference=100.0, side="BELOW"),
        _observation("2024-01-04", high=101.0, close=close, ma=100.0, reference=100.0, side="BELOW"),
    ]
    result, _ = _retest_analysis(observations, date(2024, 1, 2), date(2024, 1, 4))
    assert result["bear_retest_count"] == 1
    assert result["bear_retest_success_count"] == (1 if close < 100.0 else 0)


def test_pooled_retest_wilson_uses_combined_successes_and_trials() -> None:
    observations = [
        _observation("2024-01-02", close=100.0, ma=100.0, reference=100.0),
        _observation("2024-01-03", close=110.0, ma=100.0, reference=100.0, side="ABOVE"),
        _observation("2024-01-04", low=99.0, close=101.0, ma=100.0, reference=100.0, side="ABOVE"),
        _observation("2024-01-05", close=90.0, ma=100.0, reference=100.0, side="BELOW"),
        _observation("2024-01-08", high=101.0, close=100.0, ma=100.0, reference=100.0, side="BELOW"),
    ]
    result, _ = _retest_analysis(observations, date(2024, 1, 2), date(2024, 1, 8))
    expected = wilson_lower_bound(result["retest_success_count"], result["retest_resolved_count"])
    assert result["retest_component"] == pytest.approx(expected)
    assert result["retest_wilson_lower"] == pytest.approx(expected)


def test_bear_breakout_mirror_uses_lower_threshold_and_rearms_after_close() -> None:
    observations = [
        _observation("2024-01-02", close=100.0, ma=100.0, reference=100.0),
        _observation("2024-01-03", close=100.0, ma=100.0, reference=100.0),
        _observation("2024-01-04", low=98.5, close=98.0, ma=100.0, reference=100.0),
        _observation("2024-01-05", low=96.0, close=96.5, ma=100.0, reference=100.0),
        _observation("2024-01-08", high=101.0, close=101.0, ma=100.0, reference=100.0),
        _observation("2024-01-09", low=98.5, close=98.0, ma=100.0, reference=100.0),
        _observation("2024-01-10", low=96.0, close=96.5, ma=100.0, reference=100.0),
    ]
    result, events, _ = _breakout_analysis(observations, date(2024, 1, 4), date(2024, 1, 10), None)
    bear_events = [event for event in events if event.get("direction") == "BEAR"]
    assert result["bear_breakout_count"] >= 1
    assert bear_events[0]["trigger"] == pytest.approx(99.0)
    assert bear_events[0]["target"] == pytest.approx(96.03)


def test_same_day_breakout_target_success_precedes_close_invalidation_for_bull_and_bear() -> None:
    bull_obs = [
        _observation("2024-01-02", close=100.0, ma=100.0, reference=100.0),
        _observation("2024-01-03", high=105.0, low=98.0, close=99.0, ma=100.0, reference=100.0),
    ]
    _, bull_events, _ = _breakout_analysis(bull_obs, date(2024, 1, 3), date(2024, 1, 3), None)
    assert next(event for event in bull_events if event["direction"] == "BULL")["status"] == "BREAKOUT_3PCT_SUCCESS"

    bear_obs = [
        _observation("2024-01-02", close=100.0, ma=100.0, reference=100.0),
        _observation("2024-01-03", high=102.0, low=95.0, close=101.0, ma=100.0, reference=100.0),
    ]
    _, bear_events, _ = _breakout_analysis(bear_obs, date(2024, 1, 3), date(2024, 1, 3), None)
    assert next(event for event in bear_events if event["direction"] == "BEAR")["status"] == "BREAKOUT_3PCT_SUCCESS"


def test_active_breakout_does_not_duplicate_on_consecutive_trigger_bars() -> None:
    observations = [
        _observation("2024-01-02", close=100.0, ma=100.0, reference=100.0),
        _observation("2024-01-03", high=102.0, low=99.5, close=101.0, ma=100.0, reference=100.0),
        _observation("2024-01-04", high=103.0, low=100.5, close=102.0, ma=100.0, reference=100.0),
    ]
    _, events, _ = _breakout_analysis(observations, date(2024, 1, 3), date(2024, 1, 4), None)
    assert len([event for event in events if event["direction"] == "BULL"]) == 1


def test_confirmation_day2_equality_is_not_confirmed_for_bull_or_bear() -> None:
    train = [
        _observation("2024-01-02", close=100.0, ma=100.0, reference=100.0),
        _observation("2024-01-03", close=102.0, ma=100.0, reference=100.0),
    ]
    breakouts = [
        {"timestamp": train[0].timestamp.isoformat(), "date": "2024-01-02", "direction": "BULL", "high": 102.0, "low": 99.0},
        {"timestamp": train[0].timestamp.isoformat(), "date": "2024-01-02", "direction": "BEAR", "high": 101.0, "low": 102.0},
    ]
    result, events = _confirmation_analysis(breakouts, train)
    assert result["confirmation_confirmed_events"] == 0
    assert result["confirmation_not_confirmed_events"] == 2
    assert all(event["status"] == "DAY2_NOT_CONFIRMED" for event in events if event["event_type"] == "STRUCTURE_CONFIRMATION")


def test_execution_feasibility_denominator_is_bull_structural_breakouts_only() -> None:
    observations = [
        _observation("2024-01-02", close=100.0, ma=100.0, reference=100.0),
        _observation("2024-01-03", high=102.0, low=98.0, close=101.0, ma=100.0, reference=100.0),
        _observation("2024-01-04", high=103.0, low=97.0, close=100.0, ma=100.0, reference=100.0),
    ]
    result, events, _ = _breakout_analysis(observations, date(2024, 1, 3), date(2024, 1, 4), None)
    bull_total = result["bull_breakout_count"]
    bull_executable = result["strategy_executable_breakout_count"]
    assert result["execution_feasibility_ratio"] == pytest.approx(bull_executable / bull_total if bull_total else None)
    assert result["bear_breakout_count"] >= 1
    assert all(event["direction"] == "BULL" for event in events if event.get("strategy_executable"))


def test_rolling_runner_separates_selector_from_train_reference(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    index = pd.bdate_range("2022-01-03", periods=520, tz="UTC")
    close = 80 + np.linspace(0, 70, len(index)) + np.sin(np.arange(len(index)) / 7) * 3
    frame = pd.DataFrame({
        "open": close * 0.997,
        "high": close * 1.025,
        "low": close * 0.975,
        "close": close,
        "volume": np.full(len(index), 1_000_000.0),
    }, index=index)

    class Provider:
        def get_market_data(self, *args, **kwargs):
            start, end = args[1], args[2]
            sliced = frame[[start <= timestamp.date() <= end for timestamp in frame.index]].copy()
            return MarketData(sliced, "synthetic", [])

    request = {
        "ticker": "NVDA", "strategy": "simple", "start_date": "2022-06-01", "end_date": "2023-12-29",
        "initial_capital": 100000, "position_size_pct": 100, "execution_policy": "conservative",
        "commission_pct": 0.05, "slippage_pct": 0.02,
        "parameters": {"ma_period": 20, "breakout_trigger_pct": 1, "entry_stop_pct": 1.5},
    }
    payload = {
        "mode": "rolling_6m", "selection_mode": "STRUCTURE_V1", "backtest": request,
        "ma_min": 20, "ma_max": 30, "ma_step": 10, "ranking_metric": "sharpe_ratio",
        "rolling": {"fixed_ma_period": 20, "calendar_months": 6, "independent_test_segments": True},
    }
    monkeypatch.setattr(
        "app.optimization.structure.moving_average",
        lambda close, period, ma_type: pd.Series(100.0, index=close.index, dtype=float),
    )
    monkeypatch.setattr(
        "app.optimization.runner._run_canonical",
        lambda req, *args: {
            "ma_period": req.parameters.ma_period,
            "backtest_id": f"{req.start_date}-{req.parameters.ma_period}",
            "sharpe_ratio": 1.0,
            "total_return": 0.05,
            "max_drawdown": -0.1,
            "net_pnl": 100.0,
            "cagr": 0.05,
            "sortino_ratio": 0.5,
            "calmar_ratio": 0.5,
            "number_of_positions": 1,
            "win_rate": 1.0,
            "exposure_pct": 50.0,
            "average_holding_days": 10.0,
            "total_commission": 1.0,
            "estimated_slippage_cost": 1.0,
            "final_equity": 100005.0,
            "cache_reused": False,
        },
    )
    jobs = JobRepository(tmp_path / "jobs.sqlite3")
    backtests = BacktestRepository(tmp_path / "backtests.sqlite3")
    job, _ = jobs.create("MA_PERIOD_OPTIMIZATION", payload, 1)
    jobs.mark_running(job["id"])
    jobs.progress(
        job["id"], 1, 1, None, "legacy checkpoint",
        result={
            "selection_mode": "STRUCTURE_V1",
            "structure_implementation_revision": "MA_STRUCTURE_V1_IMPL_1",
            "rolling_windows": [{"index": 999, "status": "COMPLETED"}],
        },
    )
    result = run_ma_optimization(job["id"], payload, jobs, backtests, Provider())
    assert result is not None
    assert result["structure_implementation_revision"] == STRUCTURE_IMPLEMENTATION_REVISION
    assert result["prior_checkpoint_invalidated"] is True
    assert all(window.get("index") != 999 for window in result["rolling_windows"])
    candidate = result["rolling_windows"][0]["structure_ranking"][0]
    # The display row is joined only after structure selection.  Its ranking
    # value must be the authoritative analyzer component (Wilson lower bound),
    # not a value copied from the Train performance reference.
    assert candidate["structure_ranking"]["ranking_values"]["retest"] == pytest.approx(candidate["retest_component_value"])
    assert "train_reference" in candidate  # display join only
    assert "train_return" in candidate
    # ``structure_selector_best`` is the exact selector copy; the
    # backwards-compatible ``structure_best`` row is a display join.
    selector_best = result["rolling_windows"][0]["structure_selector_best"]
    assert "train_reference" not in selector_best
    assert "train_return" not in selector_best
    assert set(selector_best).issubset({
        "ma_period", "candidate_index", "structure_spec_version", "structure_spec_hash",
        "structure_implementation_revision", "selector_components", "breakout_wilson_lower",
        "total_resolved_structural_events", "confirmation_violation_rate", "valid", "skipped",
        "invalid_reason", "structure_ranking", "regime_percentile", "retest_percentile",
        "breakout_percentile", "confirmation_percentile", "ma_structure_score", "structure_score",
        "structure_percentile", "structure_components", "structure_rank", "rank", "tie_break_reason",
    })


@pytest.mark.parametrize("strategy", ["simple", "advanced", "advanced_day1_stop"])
def test_structure_selected_test_matches_canonical_engine_for_frozen_strategies(tmp_path, strategy: str) -> None:
    index = pd.bdate_range("2022-01-03", periods=520, tz="UTC")
    close = 80 + np.linspace(0, 70, len(index)) + np.sin(np.arange(len(index)) / 7) * 3
    frame = pd.DataFrame({
        "open": close * 0.997, "high": close * 1.025, "low": close * 0.975,
        "close": close, "volume": np.full(len(index), 1_000_000.0),
    }, index=index)

    class Provider:
        def get_market_data(self, *args, **kwargs):
            start, end = args[1], args[2]
            sliced = frame[[start <= timestamp.date() <= end for timestamp in frame.index]].copy()
            return MarketData(sliced, "synthetic", [])

    payload = {
        "mode": "rolling_6m", "selection_mode": "STRUCTURE_V1",
        "backtest": {
            "ticker": "NVDA", "strategy": strategy, "start_date": "2022-06-01", "end_date": "2023-05-31",
            "initial_capital": 100000, "position_size_pct": 100, "execution_policy": "conservative",
            "commission_pct": 0.05, "slippage_pct": 0.02,
            "parameters": {"ma_period": 20, "breakout_trigger_pct": 1, "entry_stop_pct": 1.5},
        },
        "ma_min": 20, "ma_max": 20, "ma_step": 1, "ranking_metric": "sharpe_ratio",
        "rolling": {"fixed_ma_period": 20, "calendar_months": 6, "independent_test_segments": True},
    }
    jobs = JobRepository(tmp_path / "jobs.sqlite3")
    backtests = BacktestRepository(tmp_path / "backtests.sqlite3")
    job, _ = jobs.create("MA_PERIOD_OPTIMIZATION", payload, 1)
    jobs.mark_running(job["id"])
    result = run_ma_optimization(job["id"], payload, jobs, backtests, Provider())
    assert result is not None
    window = result["rolling_windows"][0]
    stored = backtests.get(window["structure_test_result"]["backtest_id"])["result"]
    test_request = BacktestRequest.model_validate(payload["backtest"]).model_copy(deep=True)
    test_request.start_date = date.fromisoformat(window["test_start"])
    test_request.end_date = date.fromisoformat(window["test_end"])
    test_request.parameters.ma_period = int(window["selected_ma"])
    manual_market = prepare_daily_market_data(test_request, Provider())
    manual = BacktestEngine().run(test_request, manual_market.daily, "synthetic")
    for key in ("executions", "positions", "events", "equity_curve", "summary"):
        assert stored[key] == manual[key]


def test_structure_rolling_selection_is_invariant_to_test_ohlc_mutation(tmp_path) -> None:
    """Test OHLC mutations must never change the frozen Train selector.

    This is intentionally exercised through the real rolling STRUCTURE_V1
    orchestration.  The two runs use separate temporary repositories, while
    the only market-data difference is a deterministic, valid mutation in
    the six-month Test segment.  Canonical Test backtests are stubbed because
    this regression is specifically about Train structure isolation; their
    outputs are deliberately not compared.
    """
    index = pd.bdate_range("2019-01-02", "2021-12-31", tz="UTC")
    close = 80 + np.linspace(0, 70, len(index)) + np.sin(np.arange(len(index)) / 7) * 3
    base_frame = pd.DataFrame(
        {
            "open": close * 0.997,
            "high": close * 1.025,
            "low": close * 0.975,
            "close": close,
            "volume": np.full(len(index), 1_000_000.0),
        },
        index=index,
    )
    test_start = date(2021, 7, 1)
    test_end = date(2021, 12, 31)

    class Provider:
        def __init__(self, mutate_test: bool) -> None:
            self.mutate_test = mutate_test

        def get_market_data(self, ticker, start, end, **kwargs):
            mask = [(start <= timestamp.date() <= end) for timestamp in base_frame.index]
            selected = base_frame.loc[mask].copy()
            if self.mutate_test:
                test_mask = [test_start <= timestamp.date() <= test_end for timestamp in selected.index]
                # Valid OHLC bars with a deliberately extreme, deterministic
                # Test path.  Train OHLCV, dates, and all metadata are intact.
                selected.loc[test_mask, "open"] = 1_000.0
                selected.loc[test_mask, "close"] = 1_050.0
                selected.loc[test_mask, "high"] = 1_100.0
                selected.loc[test_mask, "low"] = 950.0
            return MarketData(selected, "synthetic", [])

    payload = {
        "mode": "rolling_6m",
        "selection_mode": "STRUCTURE_V1",
        "backtest": {
            "ticker": "NVDA",
            "strategy": "simple",
            "start_date": "2021-01-01",
            "end_date": "2021-12-31",
            "initial_capital": 100000,
            "position_size_pct": 100,
            "execution_model": "daily_conservative",
            "execution_policy": "conservative",
            "commission_pct": 0.05,
            "slippage_pct": 0.02,
            "parameters": {
                "ma_period": 20,
                "breakout_trigger_pct": 1,
                "entry_stop_pct": 1.5,
            },
        },
        "ma_min": 20,
        "ma_max": 40,
        "ma_step": 20,
        "ranking_metric": "sharpe_ratio",
        "rolling": {
            "fixed_ma_period": 20,
            "calendar_months": 6,
            "independent_test_segments": True,
        },
    }

    def fake_canonical(request, daily, provider_name, fingerprint, repo):
        # Keep the comparator cheap and deterministic.  The test intentionally
        # allows Test results to differ; only Train selection is asserted.
        ma_period = int(request.parameters.ma_period)
        return {
            "ma_period": ma_period,
            "backtest_id": f"{request.start_date.isoformat()}-{ma_period}",
            "summary": {
                "total_return": 0.01 * ma_period,
                "cagr": 0.01,
                "max_drawdown": -0.1,
                "sharpe_ratio": 1.0,
                "sortino_ratio": 0.5,
                "calmar_ratio": 0.5,
                "final_equity": 100000.0,
                "number_of_positions": 1,
                "win_rate": 1.0,
                "exposure_pct": 50.0,
                "average_holding_days": 10.0,
                "total_commission": 1.0,
                "estimated_slippage_cost": 1.0,
            },
            "positions": [{"net_pnl": 100.0}],
        }

    def run_isolated(mutate_test: bool, root) -> tuple[dict, JobRepository, str]:
        jobs = JobRepository(root / "jobs.sqlite3")
        backtests = BacktestRepository(root / "backtests.sqlite3")
        job, _ = jobs.create("MA_PERIOD_OPTIMIZATION", payload, 1)
        jobs.mark_running(job["id"])
        result = run_ma_optimization(job["id"], payload, jobs, backtests, Provider(mutate_test))
        assert result is not None
        assert result["selection_mode"] == "STRUCTURE_V1"
        assert result["job_cache_reused"] is False
        return result, jobs, str(job["id"])

    # Patch only the canonical performance/test comparator.  The Structure
    # analyzer, ranking, selection, slicing, and artifact persistence remain
    # the production implementations under test.
    original_canonical = __import__("app.optimization.runner", fromlist=["_run_canonical"])._run_canonical
    import app.optimization.runner as runner_module

    runner_module._run_canonical = fake_canonical
    try:
        result_a, jobs_a, job_id_a = run_isolated(False, tmp_path / "run_a")
        result_b, jobs_b, job_id_b = run_isolated(True, tmp_path / "run_b")
    finally:
        runner_module._run_canonical = original_canonical

    window_a = result_a["rolling_windows"][0]
    window_b = result_b["rolling_windows"][0]
    assert window_a["train_start"] == window_b["train_start"]
    assert window_a["train_end"] == window_b["train_end"]
    assert window_a["test_start"] == window_b["test_start"]
    assert window_a["test_end"] == window_b["test_end"]

    # These are the exact fields used for Train structure selection.  The
    # display join may contain performance references, so compare the
    # structure-only selector/ranking namespaces, not Test metrics.
    assert window_a["selected_ma"] == window_b["selected_ma"]
    assert window_a["structure_tie_break_reason"] == window_b["structure_tie_break_reason"]
    assert window_a["tie_break_reason"] == window_b["tie_break_reason"]
    assert window_a["structure_selector_best"] == window_b["structure_selector_best"]

    rows_a = {int(row["ma_period"]): row for row in window_a["structure_ranking"]}
    rows_b = {int(row["ma_period"]): row for row in window_b["structure_ranking"]}
    assert set(rows_a) == {20, 40}
    assert set(rows_a) == set(rows_b)
    for ma_period in rows_a:
        left, right = rows_a[ma_period], rows_b[ma_period]
        for key in (
            "regime", "retest", "breakout", "confirmation",
            "total_resolved_structural_events", "regime_raw", "retest_raw_value",
            "breakout_raw_value", "confirmation_raw_value", "regime_component_raw",
            "retest_component_value", "breakout_component_value",
            "confirmation_component_value", "structure_ranking", "ma_structure_score",
        ):
            assert left.get(key) == right.get(key), (ma_period, key)

        artifact_a = jobs_a.get_structure_artifact(job_id_a, 1, ma_period, STRUCTURE_SPEC_HASH)
        artifact_b = jobs_b.get_structure_artifact(job_id_b, 1, ma_period, STRUCTURE_SPEC_HASH)
        assert artifact_a == artifact_b
