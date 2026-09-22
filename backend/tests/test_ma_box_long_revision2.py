from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.ma_box.engine import (
    ALLOWED_SETUP_TRANSITIONS,
    BoundaryEvidence,
    Contact,
    MABoxConfig,
    _best_evidence,
    _cluster,
    _entanglement,
    _frame,
    _initial_box,
    _strictly_improves_boundary,
    evaluate_box_execution_gate,
    evaluate_box_structural_gate,
    run_ma_box_study,
    spec_sha256,
)


def _prices_frame(prices: list[float], spread: float = 0.02) -> pd.DataFrame:
    close = np.asarray(prices, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * (1 + spread),
            "low": close * (1 - spread),
            "close": close,
            "volume": 1000.0,
        },
        index=pd.date_range("2021-01-01", periods=len(close), freq="B", tz="UTC"),
    )


def _config(selected: int = 10, radius: int = 0, start: str = "2021-01-01", end: str = "2021-12-31") -> MABoxConfig:
    return MABoxConfig("FIXTURE", selected, radius, 1, date.fromisoformat(start), date.fromisoformat(end))


def _enriched_formation(qualifying: int = 3, atr: float | None = 10.0) -> pd.DataFrame:
    rows = []
    closes = [101.0, 99.0, 101.0, 101.0]
    for i in range(4):
        is_qualifying = i < qualifying
        rows.append({
            "open": 100.0,
            "high": 110.0 if is_qualifying else 200.0,
            "low": 90.0 if is_qualifying else 105.0,
            "close": closes[i],
            "volume": 1000.0,
            "ma": 100.0,
            "atr": atr,
        })
    return pd.DataFrame(rows, index=pd.date_range("2021-01-01", periods=4, freq="B", tz="UTC"))


def test_period_step_always_retains_selected_period():
    config = MABoxConfig("FIXTURE", 24, 5, 2, date(2021, 1, 1), date(2021, 12, 31))
    assert config.periods() == [19, 21, 23, 24, 25, 27, 29]


def test_period_validation_rejects_negative_nearby_range():
    with pytest.raises(ValueError, match="nearby_range"):
        MABoxConfig("FIXTURE", 24, -1, 1, date(2021, 1, 1), date(2021, 12, 31)).periods()


def test_daily_frame_rejects_nonfinite_ohlcv():
    frame = _prices_frame([100.0] * 20)
    frame.iloc[0, frame.columns.get_loc("volume")] = np.nan
    with pytest.raises(ValueError, match="OHLCV"):
        _frame(frame)


def test_entanglement_uses_exact_four_bars_and_three_qualifying_bars():
    frame = _enriched_formation(3)
    indices, qualifying = _entanglement(frame, 3, 0) or ([], [])
    assert indices == [0, 1, 2, 3]
    assert qualifying == [0, 1, 2]


def test_entanglement_rejects_three_qualifying_closes_on_one_side():
    frame = _enriched_formation(3)
    frame.loc[frame.index[:3], "close"] = [101.0, 102.0, 101.0]
    assert _entanglement(frame, 3, 0) is None


def test_entanglement_rejects_no_side_switch():
    frame = _enriched_formation(4)
    frame.loc[frame.index[:4], "close"] = [101.0, 100.0, 101.0, 100.0]
    # Close equal to the completed SMA is neutral and cannot provide switching
    # evidence; only the above observations remain.
    frame.loc[frame.index[:4], "close"] = [101.0, 101.0, 101.0, 101.0]
    assert _entanglement(frame, 3, 0) is None


def test_initial_box_excludes_nonqualifying_formation_bar():
    frame = _enriched_formation(3)
    box = _initial_box(frame, [0, 1, 2, 3], [0, 1, 2], 10, 14, 0.10)
    assert box is not None
    assert box.high == 110.0
    assert box.low == 90.0
    assert box.formation_indices == [0, 1, 2]


def test_initial_box_includes_all_four_qualifying_bars():
    frame = _enriched_formation(4)
    frame.loc[frame.index[3], "high"] = 120.0
    frame.loc[frame.index[3], "low"] = 80.0
    box = _initial_box(frame, [0, 1, 2, 3], [0, 1, 2, 3], 10, 14, 0.10)
    assert box is not None
    assert box.high == 120.0
    assert box.low == 80.0


def test_initial_box_requires_finite_positive_atr():
    assert _initial_box(_enriched_formation(3, None), [0, 1, 2, 3], [0, 1, 2], 10, 14, 0.10) is None
    assert _initial_box(_enriched_formation(3, 0.0), [0, 1, 2, 3], [0, 1, 2], 10, 14, 0.10) is None


def test_upper_contact_pool_has_no_low_field():
    from app.ma_box.engine import _contacts_for_bar

    row = pd.Series({"open": 105.0, "high": 110.0, "low": 90.0, "close": 104.0})
    contacts = _contacts_for_bar(0, pd.Timestamp("2021-01-01", tz="UTC"), row, 100.0, 100.0, "upper")
    assert {contact.field for contact in contacts} == {"open", "high", "close"}


def test_lower_contact_pool_has_no_high_field():
    from app.ma_box.engine import _contacts_for_bar

    row = pd.Series({"open": 95.0, "high": 110.0, "low": 90.0, "close": 96.0})
    contacts = _contacts_for_bar(0, pd.Timestamp("2021-01-01", tz="UTC"), row, 100.0, 100.0, "lower")
    assert {contact.field for contact in contacts} == {"open", "low", "close"}


def test_cluster_recomputes_level_as_median_and_mad():
    points = [
        Contact(0, "2021-01-01", "high", 100.0, "upper"),
        Contact(1, "2021-01-04", "open", 101.0, "upper"),
        Contact(2, "2021-01-05", "close", 102.0, "upper"),
    ]
    evidence = _cluster(points, points[0], 3.0)
    assert evidence.level == 101.0
    assert evidence.count == 3
    assert evidence.distinct_bars == 3
    assert evidence.mad == 1.0


def test_boundary_candidate_requires_two_distinct_bars():
    points = [
        Contact(0, "2021-01-01", "high", 100.0, "upper"),
        Contact(0, "2021-01-01", "open", 100.1, "upper"),
    ]
    assert _best_evidence(points, BoundaryEvidence(100.0), 1.0, "upper") is None


def test_equal_contact_candidate_never_updates_even_with_better_secondary_evidence():
    current_points = [
        Contact(0, "2021-01-01", "high", 100.0, "upper"),
        Contact(1, "2021-01-04", "open", 100.1, "upper"),
    ]
    candidate_points = [
        Contact(2, "2021-01-05", "high", 101.0, "upper"),
        Contact(3, "2021-01-06", "close", 101.0, "upper"),
    ]
    current = _cluster(current_points, current_points[0], 1.0)
    candidate = _cluster(candidate_points, candidate_points[0], 1.0)
    assert candidate.count == current.count == 2
    assert candidate.mad <= current.mad
    assert not _strictly_improves_boundary(candidate, current)


def test_equal_contact_candidate_with_more_bars_and_lower_mad_still_never_updates():
    """Frozen rule: contact count must be strictly greater before any update."""
    current_points = [
        Contact(0, "2021-01-01", "high", 100.00, "upper"),
        Contact(0, "2021-01-01", "open", 100.20, "upper"),
        Contact(1, "2021-01-04", "high", 99.80, "upper"),
        Contact(1, "2021-01-04", "close", 100.10, "upper"),
    ]
    candidate_points = [
        Contact(2, "2021-01-05", "high", 103.00, "upper"),
        Contact(3, "2021-01-06", "open", 103.01, "upper"),
        Contact(4, "2021-01-07", "close", 102.99, "upper"),
        Contact(5, "2021-01-08", "high", 103.00, "upper"),
    ]
    current = _cluster(current_points, current_points[0], 0.5)
    candidate = _cluster(candidate_points, candidate_points[0], 0.05)
    assert current.count == candidate.count == 4
    assert candidate.distinct_bars > current.distinct_bars
    assert candidate.mad < current.mad
    assert candidate.level != current.level
    assert not _strictly_improves_boundary(candidate, current)
    # A strict-count gate also means no update audit can be emitted.
    updates: list[dict] = []
    if _strictly_improves_boundary(candidate, current):
        updates.append({"old": current.level, "new": candidate.level})
    assert current.level == 100.05
    assert updates == []


def test_open_close_contacts_are_partitioned_by_midpoint_without_cross_side_wicks():
    from app.ma_box.engine import _contacts_for_bar

    upper_row = pd.Series({"open": 106.0, "high": 110.0, "low": 90.0, "close": 105.0})
    lower_row = pd.Series({"open": 94.0, "high": 110.0, "low": 90.0, "close": 95.0})
    upper = _contacts_for_bar(0, pd.Timestamp("2021-01-01", tz="UTC"), upper_row, 100.0, 100.0, "upper")
    lower = _contacts_for_bar(1, pd.Timestamp("2021-01-04", tz="UTC"), lower_row, 100.0, 100.0, "lower")
    assert {item.field for item in upper} == {"high", "open", "close"}
    assert {item.field for item in lower} == {"low", "open", "close"}


@pytest.mark.parametrize(
    ("box_high", "stop", "eligible", "reason"),
    [
        (105.0, 100.0, True, "DIRECT_ENTRY_ELIGIBLE"),
        (110.0, 100.0, False, "NO_ENTRY_BOX_RISK_GT_5"),
        (99.0, 100.0, False, "NO_ENTRY_BOX_RISK_NOT_POSITIVE"),
    ],
)
def test_stage_a_structural_gate_boundaries(box_high, stop, eligible, reason):
    result = evaluate_box_structural_gate(box_high, stop)
    assert result["eligible"] is eligible
    assert result["reason"] == reason


@pytest.mark.parametrize(
    ("bar_open", "stop", "reason"),
    [(104.0, 100.0, "DIRECT_ENTRY_ELIGIBLE"), (106.0, 100.0, "NO_ENTRY_GAP_RISK_GT_5"), (99.9, 100.0, "NO_ENTRY_OPEN_AT_OR_BELOW_STOP")],
)
def test_stage_b_execution_gate_boundaries(bar_open, stop, reason):
    result = evaluate_box_execution_gate(bar_open, stop, 0.02)
    assert result["reason"] == reason
    assert result["eligible"] is (reason == "DIRECT_ENTRY_ELIGIBLE")


def test_state_machine_contract_exposes_forbidden_cross_axis_transitions():
    assert "BOX_FORMING" in ALLOWED_SETUP_TRANSITIONS["TREND_ELIGIBLE"]
    assert "BOX_ACTIVE" not in ALLOWED_SETUP_TRANSITIONS["TREND_ELIGIBLE"]
    assert "LONG_POSITION" not in ALLOWED_SETUP_TRANSITIONS
    assert "WAIT_RETEST" in ALLOWED_SETUP_TRANSITIONS["DIRECT_ENTRY_ELIGIBLE"]
    assert "BOX_ACTIVE" in ALLOWED_SETUP_TRANSITIONS["FAILED_BREAKOUT"]


def test_boundary_update_audit_contains_before_and_after_values():
    prices = [100.0] * 20 + [101.0, 99.0, 101.0, 100.0, 104.0, 106.0, 108.0, 110.0] + list(range(111, 161))
    result = run_ma_box_study(_prices_frame(prices, spread=0.03), _config(10, 0))
    updates = [event for event in result["runs"]["10"]["MA_BOX_LONG_V1"]["events"] if event["reason_code"] == "BOX_BOUNDARY_UPDATE"]
    assert updates
    assert any(event["BoxHigh_before"] != event["BoxHigh_after"] or event["BoxLow_before"] != event["BoxLow_after"] for event in updates)
    assert all("supporting_contacts" in event["metadata"] for event in updates)


def test_run_and_event_schema_carry_period_and_provenance():
    result = run_ma_box_study(_prices_frame(list(np.linspace(100, 140, 100))), _config(10, 0))
    run = result["runs"]["10"]["MA_BOX_LONG_V1"]
    assert run["strategy_revision"] == "MA_BOX_LONG_V1"
    assert run["spec_revision"] == "MA_BOX_LONG_V1_REVISION_3"
    assert run["config_hash"] == result["config_hash"]
    for event in run["events"]:
        assert event["period"] == 10
        assert event["source_cutoff"]


def test_baseline_track_keeps_its_own_revision():
    result = run_ma_box_study(_prices_frame(list(np.linspace(100, 140, 100))), _config(10, 0))
    assert result["runs"]["10"]["MA_LONG_BASELINE"]["strategy_revision"] == "MA_LONG_BASELINE"
    assert result["runs"]["10"]["MA_BOX_LONG_V1"]["strategy_revision"] == "MA_BOX_LONG_V1"


def test_study_reports_local_robustness_without_selection_score():
    result = run_ma_box_study(_prices_frame(list(np.linspace(100, 160, 130))), _config(10, 2))
    robustness = result["local_robustness"]
    assert robustness["selected_ma"] == 10
    assert robustness["periods"] == [8, 9, 10, 11, 12]
    assert set(robustness["metrics"]) >= {"total_return", "cagr", "max_drawdown", "calmar_ratio"}


def test_box_result_contains_no_fixed_profit_target_reason():
    prices = [100.0] * 20 + [101.0, 99.0, 101.0, 100.0, 104.0, 106.0, 108.0, 110.0] + list(range(111, 141))
    result = run_ma_box_study(_prices_frame(prices, spread=0.03), _config(10, 0))
    reasons = {event["reason_code"] for event in result["runs"]["10"]["MA_BOX_LONG_V1"]["events"]}
    assert not reasons.intersection({"FIRST_TP", "EXTREME_TP", "PARTIAL_TP", "FIXED_TP"})


def test_reproducibility_includes_same_event_ids_and_hashes():
    frame = _prices_frame(list(np.linspace(100, 160, 130)))
    first = run_ma_box_study(frame, _config(10, 1))
    second = run_ma_box_study(frame, _config(10, 1))
    first_run = first["runs"]["10"]["MA_BOX_LONG_V1"]
    second_run = second["runs"]["10"]["MA_BOX_LONG_V1"]
    assert first["config_hash"] == second["config_hash"]
    assert first_run["events"] == second_run["events"]
    assert first_run["executions"] == second_run["executions"]


def test_no_short_execution_is_possible_on_box_down_break():
    prices = [100.0] * 24 + [101.0, 99.0, 101.0, 100.0, 103.0, 98.0, 95.0, 92.0] + [90.0] * 30
    result = run_ma_box_study(_prices_frame(prices, spread=0.03), _config(10, 0))
    executions = result["runs"]["10"]["MA_BOX_LONG_V1"]["executions"]
    assert all(execution["side"] in {"BUY", "SELL"} for execution in executions)
    assert all(execution["side"] != "SHORT" for execution in executions)


def test_revision_three_spec_sidecar_hash_matches_runtime_artifact():
    from pathlib import Path

    sidecar = Path(__file__).resolve().parents[2] / "research" / "specs" / "MA_BOX_LONG_V1_REVISION_3.sha256"
    assert sidecar.exists()
    assert spec_sha256() in sidecar.read_text(encoding="utf-8")
