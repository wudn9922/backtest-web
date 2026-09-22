"""Independent, machine-readable bindings for the frozen MA_BOX test matrix.

The traceability JSON is an artifact produced from the frozen source text.  It
is intentionally not the source of truth for test membership: this module is
kept separate so the validator can cross-check the artifact against an
independent registration of collected tests.
"""

from __future__ import annotations


def _node(path: str, function: str) -> str:
    return f"{path}::{function}"


_R2 = "backend/tests/test_ma_box_long_revision2.py"
_R3 = "backend/tests/test_ma_box_long_revision3.py"
_M = "backend/tests/test_ma_box_long.py"
_T = "backend/tests/test_ma_box_traceability.py"
_I = "backend/tests/test_engine_integration.py"


_MASTER_FUNCTIONS = [
    (_R2, "test_entanglement_uses_exact_four_bars_and_three_qualifying_bars"),
    (_R2, "test_entanglement_rejects_three_qualifying_closes_on_one_side"),
    (_R2, "test_entanglement_rejects_no_side_switch"),
    (_R3, "test_revision3_box_creation_is_not_retroactive"),
    (_R3, "test_revision3_box_formation_while_long_does_not_exit_position"),
    (_M, "test_box_blocks_normal_entry_and_keeps_counterfactual_separate"),
    (_R3, "test_revision3_counterfactual_persisted_full_execution_parity_and_shadow_isolation"),
    (_R3, "test_revision3_breakout_candle_cannot_fill_on_same_day"),
    (_R2, "test_stage_a_structural_gate_boundaries"),
    (_R2, "test_stage_a_structural_gate_boundaries"),
    (_R2, "test_stage_b_execution_gate_boundaries"),
    (_R2, "test_stage_b_execution_gate_boundaries"),
    (_R2, "test_stage_b_execution_gate_boundaries"),
    (_R3, "test_revision3_wait_retest_valid_retest_has_priority_over_failed_breakout"),
    (_R3, "test_revision3_retest_confirmation_executes_only_next_open"),
    (_R2, "test_stage_b_execution_gate_boundaries"),
    (_R3, "test_revision3_wait_retest_valid_retest_has_priority_over_failed_breakout"),
    (_R3, "test_revision3_wait_retest_non_retest_close_reactivates_same_box"),
    (_R3, "test_revision3_failed_breakout_next_attempt_gets_new_id"),
    (_R3, "test_revision3_wait_retest_has_no_timeout_even_after_sixty_sessions"),
    (_R2, "test_no_short_execution_is_possible_on_box_down_break"),
    (_R3, "test_revision3_down_break_while_long_does_not_force_box_exit"),
    (_R3, "test_revision3_ma_stop_intraday_uses_stop_level"),
    (_R3, "test_revision3_ma_stop_gap_through_uses_open"),
    (_R3, "test_revision3_entry_then_same_day_stop_leaves_position_flat"),
    (_R2, "test_box_result_contains_no_fixed_profit_target_reason"),
    (_R3, "test_revision3_counterfactual_persisted_full_execution_parity_and_shadow_isolation"),
    (_R3, "test_revision3_counterfactual_persisted_full_execution_parity_and_shadow_isolation"),
    (_R3, "test_revision3_targeted_sma23_execution_mutation_leaves_sma24_sma25_byte_identical"),
    (_R3, "test_breakout_candle_is_evaluated_before_boundary_contacts_are_added"),
    (_R3, "test_revision3_atr14_is_the_only_tolerance_source"),
    (_R2, "test_open_close_contacts_are_partitioned_by_midpoint_without_cross_side_wicks"),
    (_R2, "test_equal_contact_candidate_with_more_bars_and_lower_mad_still_never_updates"),
    (_R2, "test_equal_contact_candidate_with_more_bars_and_lower_mad_still_never_updates"),
    (_R2, "test_equal_contact_candidate_with_more_bars_and_lower_mad_still_never_updates"),
    (_R3, "test_revision3_new_box_requires_invalidation_and_four_fresh_bars"),
    (_R3, "test_ohlc_green_path_is_deterministic"),
    (_R3, "test_ohlc_red_path_is_deterministic"),
    (_R3, "test_daily_bh_ledger_matches_hand_calculation"),
    (_R3, "test_daily_bh_ledger_matches_hand_calculation"),
    (_M, "test_buy_and_hold_single_session_still_has_forced_close"),
    (_M, "test_common_start_uses_requested_period_warmup_and_bh_is_matched"),
    (_M, "test_common_start_uses_requested_period_warmup_and_bh_is_matched"),
    (_M, "test_no_lookahead_future_mutation_does_not_change_prior_events"),
    (_R3, "test_box_data_contains_causal_stepwise_boundary_values"),
    (_I, "test_engine_runs_using_daily_ohlc_only"),
    (_R3, "test_repository_ma_box_migration_is_idempotent_and_preserves_legacy_rows"),
]


_REV2_FUNCTIONS = [
    (_R2, "test_initial_box_excludes_nonqualifying_formation_bar"),
    (_R2, "test_initial_box_includes_all_four_qualifying_bars"),
    (_R2, "test_initial_box_excludes_nonqualifying_formation_bar"),
    (_R2, "test_upper_contact_pool_has_no_low_field"),
    (_R2, "test_lower_contact_pool_has_no_high_field"),
    (_R2, "test_open_close_contacts_are_partitioned_by_midpoint_without_cross_side_wicks"),
    (_R2, "test_cluster_recomputes_level_as_median_and_mad"),
    (_R3, "test_revision3_atr14_is_the_only_tolerance_source"),
    (_R2, "test_stage_a_structural_gate_boundaries"),
    (_R2, "test_stage_b_execution_gate_boundaries"),
    (_R2, "test_stage_b_execution_gate_boundaries"),
    (_M, "test_structural_gate_rejects_nonpositive_risk"),
    (_R3, "test_revision3_stage_a_is_close_independent_and_risk_monotonic"),
    (_R3, "test_revision3_wait_retest_has_no_timeout_even_after_sixty_sessions"),
    (_R3, "test_revision3_wait_retest_valid_retest_has_priority_over_failed_breakout"),
    (_R3, "test_revision3_wait_retest_non_retest_close_reactivates_same_box"),
    (_R3, "test_revision3_failed_breakout_next_attempt_gets_new_id"),
    (_R3, "test_revision3_wait_retest_close_below_box_low_invalidates"),
    (_R3, "test_revision3_new_box_requires_invalidation_and_four_fresh_bars"),
    (_R3, "test_revision3_removes_unreachable_wait_retest_supersession_path"),
    (_R3, "test_revision3_study_end_unfilled_attempt_is_a_terminal_audit_event"),
]


_REV3_FUNCTIONS = [
    (_R3, "test_daily_bh_ledger_changes_with_close_and_final_row_is_flat"),
    (_R3, "test_initial_capital_anchor_produces_nonzero_mdd_and_dates"),
    (_R3, "test_revision3_removes_unreachable_wait_retest_supersession_path"),
    (_R3, "test_revision3_wait_retest_valid_retest_has_priority_over_failed_breakout"),
    (_R3, "test_revision3_new_box_requires_invalidation_and_four_fresh_bars"),
    (_T, "test_revision3_traceability_verifies_authoritative_source_fingerprints_and_verbatim_sections"),
    (_T, "test_revision3_traceability_has_truthful_source_matrix_and_independent_bindings"),
    (_R3, "test_local_robustness_reports_each_radius_and_unavailable_status"),
    (_R3, "test_box_data_contains_causal_stepwise_boundary_values"),
]


BACKEND_REQUIREMENT_BINDINGS: dict[str, list[str]] = {
    **{f"MASTER-{i:02d}": [_node(*binding)] for i, binding in enumerate(_MASTER_FUNCTIONS, 1)},
    **{f"REV2-{i:02d}": [_node(*binding)] for i, binding in enumerate(_REV2_FUNCTIONS, 1)},
    **{f"REV3-{i:02d}": [_node(*binding)] for i, binding in enumerate(_REV3_FUNCTIONS, 1)},
}


# High-risk bindings are intentionally explicit and independent of the JSON
# artifact.  They are used by the validator to prevent a weak legacy test from
# remaining the advertised evidence after a direct adversarial test is added.
HIGH_RISK_REQUIREMENT_BINDINGS: dict[str, list[str]] = {
    "MASTER-27": [_node(_R3, "test_revision3_counterfactual_persisted_full_execution_parity_and_shadow_isolation")],
    "MASTER-29": [_node(_R3, "test_revision3_targeted_sma23_execution_mutation_leaves_sma24_sma25_byte_identical")],
    "MASTER-30": [_node(_R3, "test_breakout_candle_is_evaluated_before_boundary_contacts_are_added")],
    "MASTER-33": [_node(_R2, "test_equal_contact_candidate_with_more_bars_and_lower_mad_still_never_updates")],
    "MASTER-35": [_node(_R2, "test_equal_contact_candidate_with_more_bars_and_lower_mad_still_never_updates")],
    # The frozen Master item covers all legacy tracks; bind it to one
    # collected test for each legacy strategy rather than treating the
    # daily-engine smoke test as a complete regression by itself.
    "MASTER-46": [
        _node(_I, "test_engine_runs_using_daily_ohlc_only"),
        _node("backend/tests/test_strategy_rules.py", "test_advanced_flat_bar_below_trigger_is_a_noop"),
        _node("backend/tests/test_advanced_day1_stop.py", "test_day1_low_above_three_percent_stop_does_not_exit"),
    ],
    "REV3-06": [_node(_T, "test_revision3_traceability_verifies_authoritative_source_fingerprints_and_verbatim_sections")],
    "REV3-09": [
        _node(_R3, "test_box_data_contains_causal_stepwise_boundary_values"),
        "frontend/tests/ma-box.test.mjs::MA_BOX boundary renderer is causal and stepwise",
        "frontend/tests/ma-box.test.mjs::MA_BOX zoom, reset, focus and horizontal-pan contracts are deterministic",
    ],
}


def all_backend_bindings() -> dict[str, list[str]]:
    return {key: list(value) for key, value in BACKEND_REQUIREMENT_BINDINGS.items()}
