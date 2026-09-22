"""Independent, reviewable bindings from frozen source requirements to pytest tests.

This registry is intentionally separate from the generated JSON traceability
matrix. The validator cross-checks both sources and pytest's collected items.
"""


def _tests(*names: str) -> tuple[str, ...]:
    return tuple(f"tests/test_ma_breakout_analytics.py::{name}" for name in names)


REV2_TEST_BINDINGS = {
    1: _tests("test_subthreshold_ma_cross_does_not_create_breakout"),
    2: _tests("test_day1_uses_completed_same_day_sma_and_reference_uses_previous_sma"),
    3: _tests("test_short_day1_breakout_and_day2_confirmation"),
    4: _tests("test_latch_requires_close_back_at_ma_before_a_second_event"),
    5: _tests("test_latch_requires_close_back_at_ma_before_a_second_event"),
    6: _tests("test_post_d1_starts_on_d2_and_post_d2_success_starts_on_d3_without_backfill"),
    7: _tests("test_day2_close_equality_is_failure"),
    8: _tests("test_short_day1_breakout_and_day2_confirmation"),
    9: _tests("test_short_day1_breakout_and_day2_confirmation"),
    10: _tests("test_volume_threshold_boundaries_are_inclusive"),
    11: _tests("test_volume_threshold_boundaries_are_inclusive"),
    12: _tests("test_volume_threshold_boundaries_are_inclusive"),
    13: _tests("test_volume_thresholds_are_nested_and_35_percent_hits_all_flags"),
    14: _tests("test_volume_threshold_boundaries_are_inclusive"),
    15: _tests("test_invalid_volume_is_not_evaluable_but_zero_current_volume_is_valid"),
    16: _tests("test_day1_uses_completed_same_day_sma_and_reference_uses_previous_sma"),
    17: _tests("test_reference_entry_is_not_breakout_close_or_execution"),
    18: _tests("test_scanner_resolves_each_target_family_against_the_dynamic_stop"),
    19: _tests("test_same_session_green_path_can_stop_before_three_percent_target"),
    20: _tests("test_scanner_resolves_each_target_family_against_the_dynamic_stop"),
    21: _tests("test_scanner_resolves_each_target_family_against_the_dynamic_stop"),
    22: _tests("test_scanner_resolves_each_target_family_against_the_dynamic_stop"),
    23: _tests("test_scanner_resolves_each_target_family_against_the_dynamic_stop"),
    24: _tests("test_scanner_resolves_each_target_family_against_the_dynamic_stop"),
    25: _tests("test_same_day_target_stop_uses_frozen_ohlc_heuristic"),
    26: _tests("test_same_day_target_stop_uses_frozen_ohlc_heuristic"),
    27: _tests("test_target_observer_has_no_fixed_horizon"),
    28: _tests("test_target_dynamic_stop_is_previous_completed_sma_and_updates_each_day"),
    29: _tests("test_all_atr_targets_use_the_frozen_day1_atr_snapshot"),
    30: _tests("test_retest_precedes_trend_when_both_are_true"),
    31: _tests("test_retest_precedes_trend_when_both_are_true"),
    32: _tests("test_return_terminal_precedes_other_failure_outcomes"),
    33: _tests("test_sideways_is_independent_of_ma_entanglement_and_can_be_above_ma"),
    34: _tests("test_trend_away_requires_clear_side_and_new_advance_over_d1_close", "test_long_trend_progress_without_clear_above_is_not_trend_continuation", "test_short_trend_progress_without_clear_below_is_not_trend_continuation"),
    35: _tests("test_failure_observer_has_no_fixed_followup_timeout"),
    36: _tests("test_return_terminal_precedes_other_failure_outcomes", "test_retest_precedes_trend_when_both_are_true", "test_trend_continuation_precedes_sideways_when_both_conditions_are_true"),
    37: _tests("test_failure_combined_count_reconciles_to_mutually_exclusive_classes"),
    38: _tests("test_right_censored_failure_is_excluded_from_failure_probability_denominator"),
    39: _tests("test_failure_volume_conditioned_aggregates_are_nested"),
    40: _tests("test_failure_volume_conditioned_aggregates_are_nested"),
    41: _tests("test_failure_volume_conditioned_aggregates_are_nested"),
    42: _tests("test_long_short_are_not_pooled"),
    43: _tests("test_pre_evaluation_box_warmup_is_included_in_breakout_cohort_snapshot"),
    44: _tests("test_clean_signal_is_classified_outside_the_entanglement_cohort"),
    45: _tests("test_period_runs_are_independent_and_combined_run_matches_standalone_metrics", "test_targeted_sma23_ma_path_mutation_cannot_change_sma24_or_25_execution_state"),
    46: _tests("test_wilson_ci_and_low_sample_contract"),
    47: _tests("test_wilson_ci_and_low_sample_contract"),
    48: _tests("test_target_aggregate_membership_supports_denominator_and_numerator_drilldown"),
    49: _tests("test_target_aggregate_membership_supports_denominator_and_numerator_drilldown"),
    50: _tests("test_analytics_does_not_modify_ma_box_source"),
    51: _tests("test_analytics_keeps_frozen_canonical_and_legacy_source_hashes"),
    52: _tests("test_day1_uses_completed_same_day_sma_and_reference_uses_previous_sma"),
    53: _tests("test_subthreshold_ma_cross_does_not_create_breakout"),
    54: _tests("test_post_event_grey_zone_does_not_rearm"),
    55: _tests("test_latch_requires_close_back_at_ma_before_a_second_event"),
    56: _tests("test_existing_trend_at_study_start_is_not_fabricated_as_new_breakout"),
    57: _tests("test_post_d1_starts_on_d2_and_post_d2_success_starts_on_d3_without_backfill"),
    58: _tests("test_post_d1_starts_on_d2_and_post_d2_success_starts_on_d3_without_backfill"),
    59: _tests("test_target_open_gap_rules"),
    60: _tests("test_failure_return_mirrors_by_direction"),
    61: _tests("test_trend_away_requires_clear_side_and_new_advance_over_d1_close", "test_short_trend_away_requires_clear_side_and_a_new_d1_low_close", "test_long_trend_progress_without_clear_above_is_not_trend_continuation", "test_short_trend_progress_without_clear_below_is_not_trend_continuation"),
    62: _tests("test_return_precedes_sideways_when_both_conditions_are_true"),
    63: _tests("test_retest_precedes_sideways_when_both_conditions_are_true"),
    64: (),  # Superseded by Rev3's frozen Trend-before-Sideways precedence.
    65: _tests("test_pre_evaluation_box_warmup_is_included_in_breakout_cohort_snapshot", "test_entanglement_formed_after_day1_does_not_backpaint_cohort"),
    66: _tests("test_invalid_atr_target_is_not_evaluable_and_percentage_target_remains_available"),
    67: _tests("test_volume_and_day2_probability_denominators_are_explicit"),
    68: _tests("test_target_families_have_independent_outcomes"),
    69: _tests("test_entanglement_formed_after_day1_does_not_backpaint_cohort"),
    70: _tests("test_short_day1_breakout_and_day2_confirmation"),
    71: _tests("test_short_dynamic_stop_uses_previous_completed_ma"),
    72: _tests("test_timeout_is_not_a_config_or_request_field"),
}


REV3_CHANGE_BINDINGS = {
    1: _tests("test_sideways_is_independent_of_ma_entanglement_and_can_be_above_ma"),
    2: _tests("test_trend_away_requires_clear_side_and_new_advance_over_d1_close", "test_short_trend_away_requires_clear_side_and_a_new_d1_low_close", "test_long_trend_progress_without_clear_above_is_not_trend_continuation", "test_short_trend_progress_without_clear_below_is_not_trend_continuation"),
    3: _tests("test_return_precedes_sideways_when_both_conditions_are_true", "test_retest_precedes_trend_when_both_are_true", "test_trend_continuation_precedes_sideways_when_both_conditions_are_true"),
    4: _tests("test_failure_volume_conditioned_aggregates_are_nested"),
    5: _tests("test_entanglement_cohort_modes_filter_only_signal_snapshot", "test_entangled_signal_can_resolve_without_sideways"),
    6: _tests("test_trend_continuation_precedes_sideways_when_both_conditions_are_true"),
    7: _tests("test_sideways_is_independent_of_ma_entanglement_and_can_be_above_ma", "test_sideways_can_be_below_ma_without_triggering_return_or_retest"),
}


REV3_TEST_BINDINGS = {
    1: _tests("test_sideways_is_independent_of_ma_entanglement_and_can_be_above_ma"),
    2: _tests("test_sideways_requires_exactly_four_followup_bars"),
    3: _tests("test_sideways_requires_exactly_four_followup_bars"),
    4: _tests("test_sideways_requires_exactly_four_followup_bars"),
    5: _tests("test_sideways_range_atr_threshold_is_inclusive"),
    6: _tests("test_sideways_range_atr_threshold_is_inclusive"),
    7: _tests("test_sideways_uses_pre_window_atr14_snapshot"),
    8: _tests("test_sideways_uses_pre_window_atr14_snapshot"),
    9: _tests("test_invalid_sideways_atr_skips_window_and_keeps_observing"),
    10: _tests("test_sideways_is_independent_of_ma_entanglement_and_can_be_above_ma"),
    11: _tests("test_sideways_can_be_below_ma_without_triggering_return_or_retest"),
    12: _tests("test_sideways_is_independent_of_ma_entanglement_and_can_be_above_ma", "test_sideways_can_be_below_ma_without_triggering_return_or_retest"),
    13: _tests("test_entangled_signal_can_resolve_without_sideways"),
    14: _tests("test_sideways_is_independent_of_ma_entanglement_and_can_be_above_ma"),
    15: _tests("test_trend_away_requires_clear_side_and_new_advance_over_d1_close"),
    16: _tests("test_long_trend_progress_without_clear_above_is_not_trend_continuation"),
    17: _tests("test_trend_away_requires_clear_side_and_new_advance_over_d1_close"),
    18: _tests("test_trend_away_requires_clear_side_and_new_advance_over_d1_close"),
    19: _tests("test_short_trend_away_requires_clear_side_and_a_new_d1_low_close"),
    20: _tests("test_short_trend_away_requires_clear_side_and_a_new_d1_low_close"),
    21: _tests("test_trend_away_does_not_use_day1_high_or_low_gate"),
    22: _tests("test_retest_precedes_trend_when_both_are_true"),
    23: _tests("test_trend_continuation_precedes_sideways_when_both_conditions_are_true"),
    24: _tests("test_post_d1_starts_on_d2_and_post_d2_success_starts_on_d3_without_backfill"),
    25: _tests("test_volume_conditioned_post_d1_target_origin_begins_at_d2_open"),
    26: _tests("test_post_d1_starts_on_d2_and_post_d2_success_starts_on_d3_without_backfill"),
    27: _tests("test_post_d1_starts_on_d2_and_post_d2_success_starts_on_d3_without_backfill"),
    28: _tests("test_d2_intraday_target_and_stop_are_not_backfilled_into_post_d2_success"),
    29: _tests("test_d2_intraday_target_and_stop_are_not_backfilled_into_post_d2_success"),
    30: _tests("test_d2_intraday_target_and_stop_are_not_backfilled_into_post_d2_success"),
    31: _tests("test_post_d2_success_first_dynamic_stop_uses_d2_completed_ma"),
    32: _tests("test_post_d2_success_first_dynamic_stop_uses_d2_completed_ma"),
    33: _tests("test_target_families_have_independent_outcomes"),
    34: _tests("test_target_aggregates_do_not_mix_observation_origins"),
    35: _tests("test_day2_success_without_d3_is_right_censored"),
    36: _tests("test_failure_observer_has_no_fixed_followup_timeout"),
    37: _tests("test_failure_observer_has_no_fixed_followup_timeout"),
    38: _tests("test_entangled_signal_can_resolve_without_sideways", "test_entanglement_formed_after_day1_does_not_backpaint_cohort"),
}


def build_independent_registry() -> dict[str, tuple[str, ...]]:
    registry = {f"REV2-TEST-{number:03d}": nodeids for number, nodeids in REV2_TEST_BINDINGS.items()}
    registry.update({f"REV3-CHANGE-{number:02d}": nodeids for number, nodeids in REV3_CHANGE_BINDINGS.items()})
    registry.update({f"REV3-TEST-{number:02d}": nodeids for number, nodeids in REV3_TEST_BINDINGS.items()})
    return registry


MA_BREAKOUT_ANALYTICS_REQUIREMENT_BINDINGS = build_independent_registry()
