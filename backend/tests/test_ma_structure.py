from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.backtest.models import BacktestRequest
from app.jobs.repository import JobRepository
from app.jobs.service import JobService
from app.main import app
from app.optimization.structure import (
    STRUCTURE_IMPLEMENTATION_REVISION,
    STRUCTURE_SPEC_HASH,
    STRUCTURE_SPEC_VERSION,
    analyze_ma_structure,
    average_rank_percentiles,
    build_structure_selector_candidate,
    rank_structure_candidates,
    select_structure_ma,
    wilson_lower_bound,
    StructureValidationError,
)


def bars(rows: list[tuple[float, float, float, float]], start: str = "2024-01-02") -> pd.DataFrame:
    index = pd.bdate_range(start, periods=len(rows), tz="UTC")
    return pd.DataFrame(
        {
            "open": [row[0] for row in rows],
            "high": [row[1] for row in rows],
            "low": [row[2] for row in rows],
            "close": [row[3] for row in rows],
            "volume": np.full(len(rows), 1_000_000.0),
        },
        index=index,
    )


def constant_ma(monkeypatch: pytest.MonkeyPatch, value: float = 100.0) -> None:
    def fake_ma(close: pd.Series, period: int, ma_type: str) -> pd.Series:
        return pd.Series(value, index=close.index, dtype=float)

    monkeypatch.setattr("app.optimization.structure.moving_average", fake_ma)


def analysis(monkeypatch: pytest.MonkeyPatch, frame: pd.DataFrame, end: str | None = None) -> dict:
    constant_ma(monkeypatch)
    return analyze_ma_structure(frame, 20, "sma", train_start=frame.index[3].date(), train_end=date.fromisoformat(end) if end else frame.index[-1].date())


def selector(ma_period: int, index: int, *, components: tuple[float, float, float, float] = (0.5, 0.5, 0.5, 0.5),
             breakout_wilson: float | None = None, resolved: int = 4, violation: float | None = 0.1) -> dict:
    regime, retest, breakout, confirmation = components
    return {
        "ma_period": ma_period,
        "candidate_index": index,
        "structure_spec_version": STRUCTURE_SPEC_VERSION,
        "structure_spec_hash": STRUCTURE_SPEC_HASH,
        "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
        "selector_components": {"regime": regime, "retest": retest, "breakout": breakout, "confirmation": confirmation},
        "breakout_wilson_lower": breakout if breakout_wilson is None else breakout_wilson,
        "total_resolved_structural_events": resolved,
        "confirmation_violation_rate": violation,
    }


def test_wilson_fixed_95_zero_one_and_high_sample() -> None:
    assert wilson_lower_bound(0, 0) == 0
    assert wilson_lower_bound(1, 1) == pytest.approx(0.20654931437723742)
    assert wilson_lower_bound(15, 18) == pytest.approx(0.6077796189608428)
    assert wilson_lower_bound(1, 1) < wilson_lower_bound(15, 18)


def test_percentile_average_rank_ties_single_and_all_zero() -> None:
    assert average_rank_percentiles([1, 1, 2]) == pytest.approx([0.25, 0.25, 1.0])
    assert average_rank_percentiles([7]) == [0.5]
    assert average_rank_percentiles([0, 0, 0]) == [0.5, 0.5, 0.5]


def test_preroll_regime_is_state_only_and_not_scored(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = bars([(110, 111, 109, 110)] * 3 + [(101, 103, 99, 101)] * 3)
    result = analysis(monkeypatch, frame)
    assert result["pre_roll"]["state_only_no_score"] is True
    assert result["bull_regime_count"] == 0
    assert result["bear_regime_count"] == 0


def test_missing_completed_preroll_state_is_candidate_validation_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    constant_ma(monkeypatch)
    frame = bars([(100, 101, 99, 100)] * 4)
    with pytest.raises(StructureValidationError, match="MA reference"):
        analyze_ma_structure(frame, 20, "sma", train_start=frame.index[0].date(), train_end=frame.index[-1].date())


def test_bull_breakout_uses_previous_ma_and_fixed_three_percent_target(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = bars(
        [(90, 91, 89, 90)] * 3
        + [(100, 102, 99, 101), (103, 105, 102, 103), (103, 104, 100, 101)]
    )
    result = analysis(monkeypatch, frame)
    breakout = result["breakout"]
    assert breakout["bull_breakout_count"] == 1
    assert breakout["bull_breakout_success_count"] == 1
    event = next(item for item in result["events"] if item.get("event_type") == "STRUCTURE_BULL_STRUCTURAL_BREAKOUT")
    assert event["trigger"] == pytest.approx(101.0)
    assert event["target"] == pytest.approx(104.03)


def test_active_breakout_invalidates_and_train_end_is_unresolved(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = bars([(90, 91, 89, 90)] * 3 + [(100, 102, 99, 101), (99, 100, 97, 99)])
    failed = analysis(monkeypatch, frame)
    assert failed["breakout"]["bull_breakout_fail_count"] == 1
    unresolved = analysis(monkeypatch, frame, end=frame.index[3].date().isoformat())
    assert unresolved["breakout"]["bull_breakout_unresolved_count"] == 1
    assert unresolved["breakout"]["breakout_resolved_count"] == 0


def test_retest_strict_prior_side_and_equality_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = bars([(101, 102, 100, 101), (102, 103, 101, 102), (101, 102, 99, 101), (99, 101, 98, 101)])
    result = analysis(monkeypatch, frame)
    assert result["retest"]["bull_retest_count"] >= 1
    assert result["retest"]["bull_retest_success_count"] >= 1
    assert result["retest"]["retest_wilson_lower"] <= 1


def test_confirmation_day2_violation_safe_and_ambiguous_are_separate(monkeypatch: pytest.MonkeyPatch) -> None:
    # D2 does not confirm; following sessions respectively violate, touch
    # safely, and contain both observations (the last event is independent).
    frame = bars(
        [(90, 91, 89, 90)] * 3
        + [(100, 102, 99, 101), (101, 102, 100, 101), (101, 103, 100, 101)]
    )
    result = analysis(monkeypatch, frame)
    confirmation = result["confirmation"]
    assert confirmation["confirmation_eligible_events"] >= 1
    assert confirmation["confirmation_not_confirmed_events"] >= 1
    assert confirmation["confirmation_violation_events"] + confirmation["confirmation_ambiguous_events"] >= 1


def test_gap_breakout_is_not_execution_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = bars([(90, 91, 89, 90)] * 3 + [(110, 115, 109, 112), (114, 118, 113, 116)])
    request = BacktestRequest.model_validate({
        "ticker": "NVDA", "strategy": "simple", "start_date": "2024-01-05", "end_date": "2024-01-10",
        "parameters": {"ma_period": 20, "breakout_trigger_pct": 1, "entry_stop_pct": 1.5},
    })
    constant_ma(monkeypatch)
    result = analyze_ma_structure(frame, 20, "sma", train_start=frame.index[3].date(), train_end=frame.index[-1].date(), strategy_request=request)
    event = next(item for item in result["events"] if item.get("event_type") == "STRUCTURE_BULL_STRUCTURAL_BREAKOUT")
    assert event["gap_breakout"] is True
    assert event["entry_zone_missed"] is True
    assert result["breakout"]["bull_breakout_success_count"] == 1


def test_structure_selector_never_reads_train_performance_and_tie_breaks() -> None:
    candidates = [
        selector(20, 0, components=(0.9, 0.9, 0.5, 0.9)),
        selector(30, 1, components=(0.9, 0.9, 0.5, 0.9)),
    ]
    best, reason = select_structure_ma(candidates)
    assert best["ma_period"] == 20
    assert reason == "SMALLER_MA_PERIOD"
    assert "train_reference" not in best
    assert "train_return" not in best
    assert select_structure_ma(candidates)[0]["ma_period"] == 20


def test_structure_selector_preserves_earlier_confirmation_tie_break_reason() -> None:
    candidates = [
        selector(20, 0, violation=0.2),
        selector(30, 1, violation=0.1),
        selector(40, 2, violation=0.1),
    ]
    best, reason = select_structure_ma(candidates)
    assert best["ma_period"] == 30
    assert reason == "SMALLER_MA_PERIOD"


def test_structure_component_percentiles_and_equal_weights() -> None:
    ranked = rank_structure_candidates([
        selector(20, 0, components=(0.0, 0.0, 0.0, 0.0), breakout_wilson=0.0),
        selector(30, 1, components=(1.0, 1.0, 1.0, 1.0), breakout_wilson=1.0),
    ])
    assert ranked[0]["ma_structure_score"] == pytest.approx(0.0)
    assert ranked[1]["ma_structure_score"] == pytest.approx(1.0)


def test_artifact_is_train_only_and_has_numerical_event_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = bars([(90, 91, 89, 90)] * 3 + [(100, 102, 99, 101), (103, 105, 102, 103), (103, 104, 100, 101)] + [(140, 141, 139, 140)])
    constant_ma(monkeypatch)
    result = analyze_ma_structure(frame, 20, "sma", train_start=frame.index[3].date(), train_end=frame.index[5].date())
    artifact = result["chart_artifact"]
    assert len(artifact["ohlc"]) == 3
    assert all(row["date"] <= result["train_end"] for row in artifact["ohlc"])
    assert artifact["events"] == result["events"]
    assert artifact["structure_spec_hash"] == STRUCTURE_SPEC_HASH
    assert artifact["structure_spec_version"] == STRUCTURE_SPEC_VERSION


def test_artifact_repository_round_trip_and_copy(tmp_path: Path) -> None:
    repo = JobRepository(tmp_path / "jobs.sqlite3")
    first, _ = repo.create("MA_PERIOD_OPTIMIZATION", {}, 1)
    second, _ = repo.create("MA_PERIOD_OPTIMIZATION", {"copy": True}, 1)
    artifact = {"train_start": "2024-01-01", "events": [], "ohlc": []}
    repo.put_structure_artifact(first["id"], 1, 20, STRUCTURE_SPEC_HASH, artifact)
    assert repo.get_structure_artifact(first["id"], 1, 20, STRUCTURE_SPEC_HASH) == artifact | {"structure_spec_hash": STRUCTURE_SPEC_HASH}
    assert repo.copy_structure_artifacts(first["id"], second["id"], STRUCTURE_SPEC_HASH) == 1
    assert repo.get_structure_artifact(second["id"], 1, 20, STRUCTURE_SPEC_HASH) is not None


def test_structure_artifact_api_requires_saved_top5_and_matching_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(JobService, "start", lambda self: None)
    monkeypatch.setattr(JobService, "stop", lambda self: None)
    request = BacktestRequest.model_validate({
        "ticker": "NVDA", "strategy": "simple", "start_date": "2024-01-01", "end_date": "2024-12-31",
        "parameters": {"ma_period": 20, "breakout_trigger_pct": 1, "entry_stop_pct": 1.5},
    })
    payload = {
        "mode": "rolling_6m", "selection_mode": "STRUCTURE_V1", "backtest": request.model_dump(mode="json"),
        "ma_min": 20, "ma_max": 20, "ma_step": 1, "ranking_metric": "sharpe_ratio",
        "rolling": {"fixed_ma_period": 20, "calendar_months": 6, "independent_test_segments": True},
    }
    with TestClient(app) as client:
        created = client.post("/api/optimizations", json=payload)
        assert created.status_code == 202
        identifier = created.json()["id"]
        repository = app.state.job_service.repository
        summary = {"ma_period": 20, "ma_structure_score": 0.5}
        result = {
            "selection_mode": "STRUCTURE_V1", "structure_spec_version": STRUCTURE_SPEC_VERSION,
            "structure_spec_hash": STRUCTURE_SPEC_HASH,
            "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
            "rolling_windows": [{"index": 1, "structure_top5": [summary]}],
        }
        repository.finish(identifier, "COMPLETED", "done", result=result)
        repository.put_structure_artifact(identifier, 1, 20, STRUCTURE_SPEC_HASH, {"ohlc": [], "events": [], "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION})
        response = client.get(f"/api/optimizations/{identifier}/structure/windows/1/candidates/20")
        assert response.status_code == 200
        assert response.json()["candidate_summary"] == summary
        assert client.get(f"/api/optimizations/{identifier}/structure/windows/1/candidates/30").status_code == 404
