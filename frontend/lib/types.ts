export type Parameters = {
  ma_type: "sma" | "ema"; ma_period: number; breakout_trigger_pct: number; entry_stop_pct: number;
  exit_below_ma_pct: number; volume_increase_pct: number; ma_risk_pct: number; first_tp_pct: number;
  bias_lookback: number; bias_sigma_multiple: number; atr_period: number; atr_multiple: number;
  extreme_tp_pct_q0: number; max_extreme_tp_count: number; minimum_position_pct_q0: number;
  day1_stop_pct: number;
};

export type FormState = {
  ticker: string; strategy: "simple" | "advanced" | "advanced_day1_stop"; start_date: string; end_date: string;
  initial_capital: number; position_size_pct: number; execution_model: "daily_conservative"; execution_policy: "conservative" | "ohlc_heuristic" | "favorable";
  market_data_provider: "auto" | "yahoo" | "alternative";
  commission_pct: number; slippage_pct: number; force_close_at_end: boolean; parameters: Parameters;
};

export type Summary = Record<string, number | string | null>;
export type Execution = { timestamp: string; side: string; price: number; quantity: number; gross_value: number; commission: number; slippage: number; position_remaining: number; event_type: string; reason: string };
export type EventItem = { timestamp: string; daily_reference_ma: number | null; event: string; trigger_price: number | null; current_price: number | null; position_before: number; position_after: number; state_before: string; state_after: string; metadata: Record<string, unknown> };
export type AuditThresholds = { breakout_trigger: number | null; entry_level: number | null; day1_stop: number | null; simple_ma_exit_stop?: number | null; ma_half_stop: number | null; break_day_low: number | null; first_tp_price: number | null; protective_stop: number | null; bias_extreme_threshold_price: number | null; atr_extreme_threshold_price: number | null };
export type StopExecutionPresentation = {
  trigger_type: "GAP_THROUGH" | "INTRADAY_STOP" | "NOT_TRIGGERED";
  reference_ma: number | null; active_stop_price: number; open_price: number; low_price: number;
  raw_fill_price: number | null; actual_execution_price: number | null; sell_slippage_pct: number; formula: string;
};
export type AuditEvent = { event: string; source_event: string; trigger_level: number | null; execution_price: number | null; shares_before: number; shares_sold: number; shares_remaining: number; state_before: string; state_after: string; metadata: Record<string, unknown>; stop_execution?: StopExecutionPresentation };
export type AuditDay = {
  date: string; timestamp: string; open: number; high: number; low: number; close: number; volume: number;
  previous_day_ma: number | null; current_day_ma: number | null; previous_day_atr: number | null; bias_sigma: number | null;
  current_quantity_at_open: number; current_quantity_at_close: number; strategy_state_at_open: string; strategy_state_at_close: string;
  entry_zone?: { lower_entry: number | null; upper_entry: number | null; entry_allowed: boolean | null; entry_missed: boolean | null; entry_execution_price: number | null; intrabar_assumption: string };
  thresholds: AuditThresholds; validations: { entry_day_volume: Record<string, number | string | null> | null; day2_confirmation: Record<string, number | string | null> | null };
  events: AuditEvent[]; ambiguity: { applied: boolean; message: string | null; policy: string | null; chosen_path: string | null; simultaneous_conditions: string[] };
};
export type PositionAudit = {
  backtest_id: string; position_id: string; ticker: string; strategy: string; position: Record<string, number | string | null>;
  timeline: AuditDay[]; chart: { daily_data: Array<Record<string, number | string | null>>; executions: Execution[] };
  presentation?: { ma_stop: { kind: "SIMPLE_FULL_STOP" | "ADVANCED_HALF_STOP"; percent_below_ma: number; multiplier: number; formula: string }; sell_slippage_pct: number; source: string; persisted_audit_modified: boolean };
};
export type Day1StopRow = {
  position_id: string; entry_date: string; previous_day_ma: number; entry_price: number; day1_stop_price: number;
  day1_open: number; day1_high: number; day1_low: number; day1_close: number; execution_price: number; loss_pct: number;
  daily_intrabar_ambiguity: boolean; next_day_close_return_pct: number | null; forward_5d_pct: number | null;
  forward_10d_pct: number | null; forward_20d_pct: number | null; backtest_id: string;
};
export type DiagnosticOutcome = { position_id: string; entry_date: string; entry_price: number; final_exit_date: string; exit_reason: string; net_pnl: number; return_pct: number };
export type DiagnosticComparison = {
  entry_date: string; match_status: string; baseline_backtest_id: string; variant_backtest_id: string;
  original_advanced: DiagnosticOutcome | null; day1_stop_strategy: DiagnosticOutcome; pnl_difference: number | null;
};
export type DiagnosticGroup = { count: number; average_stop_loss_pct: number | null; median_5_day_forward_return_pct: number | null; median_10_day_forward_return_pct: number | null; median_20_day_forward_return_pct: number | null };
export type Day1StopDiagnostic = {
  ticker: string; start_date: string; end_date: string; strategy: string; variant_backtest_id: string; baseline_backtest_id: string;
  day1_full_stop_count: number; daily_intrabar_ambiguity_count: number; stops: Day1StopRow[];
  group_statistics: { unambiguous: DiagnosticGroup; ambiguous: DiagnosticGroup };
  backtest_comparison: { existing_advanced_total_return: number; day1_stop_total_return: number; total_return_difference: number; existing_advanced_final_equity: number; day1_stop_final_equity: number; final_equity_difference: number };
  comparison: { matched_count: number; unmatched_count: number; all_divergences: DiagnosticComparison[]; largest_return_damage: DiagnosticComparison[]; largest_improvements: DiagnosticComparison[] };
};
export type SensitivityPolicyRow = { strategy: string; policy: string; backtest_id: string; strategy_version: number; total_return: number; cagr: number; max_drawdown: number; sharpe: number; positions: number; entry_zone_missed_count: number; ambiguous_positions: number; day1_full_stop_count: number };
export type SensitivityDelta = { policy: string; advanced_backtest_id: string; day1_stop_backtest_id: string; matched_positions: number; advanced_only_positions: number; day1_stop_only_positions: number; matched_net_pnl_delta: number; total_return_delta: number };
export type LegacyChaseEntry = { date: string; entry_price: number; open: number; reference_ma: number; upper_entry: number; gap_above_upper_entry_pct: number };
export type AmbiguitySensitivity = {
  ticker: string; start_date: string; end_date: string; strategy_version: number;
  matrix: SensitivityPolicyRow[];
  policies: SensitivityPolicyRow[];
  matched_deltas: SensitivityDelta[];
  legacy_entry_chasing: { legacy_backtest_id: string | null; count: number; available: boolean; entries: LegacyChaseEntry[] };
};
export type BacktestResult = {
  id: string; strategy_version?: number | null; summary: Summary; equity_curve: Array<{timestamp: string; strategy: number; buy_hold: number}>;
  drawdown: Array<{timestamp: string; drawdown: number}>; daily_data: Array<Record<string, number | string | null>>;
  executions: Execution[]; positions: Array<Record<string, number | string | null>>; events: EventItem[];
  monthly_returns: Array<{year: number; month: number; return: number}>; warnings: string[];
  data_coverage: Record<string, unknown>; reproducibility: Record<string, unknown>;
};

export type HistoryItem = { id: string; created_at: string; ticker: string; strategy: string; start_date: string; end_date: string; status: string; total_return: number | null; max_drawdown: number | null; strategy_version: number | null; parameters: FormState };
