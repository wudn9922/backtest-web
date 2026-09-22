import { AmbiguitySensitivity, BacktestResult, Day1StopDiagnostic, FormState, HistoryItem, PositionAudit } from "./types";

// Empty means same-origin. Next.js rewrites /api to FastAPI, which avoids CORS
// and prevents mobile browsers from resolving `localhost` to the phone itself.
const API = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/$/, "");

export type ApiErrorDetails = {
  code?: string; message: string; ticker?: string; requested_start?: string; requested_end?: string;
  execution_model?: string; daily_bars_count?: number; yahoo_error?: string | null;
  cache_coverage?: { start?: string | null; end?: string | null; bars?: number; last_updated?: string | null; complete?: boolean; missing_ranges?: Array<{start:string;end:string}> } | string | null;
  cache_last_updated?: string | null; provider_error_code?: string | null;
  provider_error?: string | null; market_data_provider?: string | null;
  provider_errors?: Record<string, {code?: string; error_type?: string; message?: string}>;
  provider_attempts?: Array<Record<string, unknown>>;
  yahoo_hosts_attempted?: string[];
};

export type DataProviderStatus = {
  status: "online" | "degraded" | "offline" | string;
  preferred_provider: string | null;
  cache_available: boolean;
  providers: Record<string, {
    provider?: string;
    reachable: boolean | null;
    error_type?: string | null;
    cache_available?: boolean;
    cooldown_active?: boolean;
  }>;
};

export type BackgroundJob = {
  id: string; job_type: string;
  status: "QUEUED" | "RUNNING" | "COMPLETED" | "PARTIAL_SUCCESS" | "FAILED" | "FAILED_VALIDATION" | "CANCELLED" | string;
  created_at: string; started_at?: string | null; finished_at?: string | null;
  progress_current: number; progress_total: number; current_item?: string | null; message: string;
  payload: Record<string, unknown>;
  errors: Array<{ticker?: string; stage?: string; code?: string; message?: string; technical?: string;requested_start?:string;requested_end?:string;provider_requested_start?:string;cache_coverage?:unknown}>;
  result: Record<string, unknown> & {completed?: Array<{ticker:string;status:string;provider:string;bars:number}>; failed_tickers?: string[]; report_id?: string};
};
export type DataCenterDataset = {
  ticker: string; first_date: string | null; last_date: string | null; bars: number;
  provider: string | null; updated_at: string | null; complete: boolean; status: string; adjustment_mode: string | null;
};
export type DataCenter = {
  providers: Record<string, {provider:string;status:string;last_checked_at:string|null;last_success_at:string|null;last_error_type:string|null;safe_message:string|null}>;
  runtime: {context_status:string;python_path_expected:boolean;launcher_installed:boolean;repair_required:boolean};
  connection_repair_required: boolean;
  target_range: {start:string;end:string}; long_history_status: "complete"|"partial"|"incomplete"|string;
  datasets: DataCenterDataset[];
  risk_free: {status:string;series_id:string;description:string;first_observation:string|null;last_observation:string|null;observations:number;updated_at:string|null};
  readiness: {market_data_ready:boolean;risk_free_ready:boolean;research_validation_ready:boolean;universe_readiness:Record<string,{status:string;symbols:number;validated_datasets:number;target_requests_complete:number}>};
  jobs: BackgroundJob[];
};
export type SystemStatus = {frontend:string;backtest_engine:string;data_sources:string;local_cache:string;checked_by:string};

export type OptimizationMetric = "total_return"|"cagr"|"sharpe_ratio"|"sortino_ratio"|"calmar_ratio"|"max_drawdown"|"net_pnl";
export type OptimizationSelectionMode = "PERFORMANCE"|"STRUCTURE_V1";
export type OptimizationRow = {
  ma_period:number; backtest_id:string; total_return:number|null;cagr:number|null;max_drawdown:number|null;
  sharpe_ratio:number|null;sortino_ratio:number|null;calmar_ratio:number|null;number_of_positions:number;
  win_rate:number;net_pnl:number;exposure_pct:number;average_holding_days:number|null;
  total_commission:number;estimated_slippage_cost:number;final_equity:number;cache_reused:boolean;
};
export type OptimizationPayload = {
  mode?:"single"|"rolling_6m";selection_mode?:OptimizationSelectionMode;backtest:FormState; ma_min:number;ma_max:number;ma_step:number;ranking_metric:OptimizationMetric;
  train_test:{enabled:boolean;train_start:string;train_end:string;test_start:string;test_end:string};
  rolling?:{fixed_ma_period:number;calendar_months:6;independent_test_segments:true};
};
export type RollingOptimizationWindow = {
  index:number;train_start:string;train_end:string;test_start:string;test_end:string;planned_test_end:string;
  complete:boolean;status:string;aggregate_included:boolean;selected_ma?:number;tie_break_reason?:string;
  train_best?:OptimizationRow;train_ranking?:OptimizationRow[];test_result?:OptimizationRow|null;
  selection_mode?:OptimizationSelectionMode; performance_best?:OptimizationRow|null; structure_best?:StructureCandidate|null;
  structure_selector_best?:StructureCandidate|null;
  performance_test_result?:OptimizationRow|null; structure_test_result?:OptimizationRow|null;
  structure_ranking?:StructureCandidate[]; structure_top5?:StructureCandidate[];
  structure_tie_break_reason?:string; structure_minus_performance?:{return_delta:number|null;sharpe_delta:number|null;mdd_delta?:number|null;pnl_delta?:number|null};
  train_stability?:{metric:OptimizationMetric;best_ma_period:number;from_ma:number;to_ma:number;relative_spread:number|null;stable:boolean;label:string;rows:OptimizationRow[]};
  fixed_ma_period?:number;fixed_test_result?:OptimizationRow|null;
  test_vs_fixed?:{return_delta:number|null;sharpe_delta:number|null};
  train_sessions?:{first_session:string|null;last_session:string|null};test_sessions?:{first_session:string|null;last_session:string|null};
};
export type StructureComponentScore = {raw:number;component:number;percentile:number};
export type StructureSelectorComponents = {regime:number;retest:number;breakout:number;confirmation:number};
export type StructureRanking = {
  ranking_values:StructureSelectorComponents;
  percentiles:StructureSelectorComponents;
  composite:number;
};
export type StructureCandidate = {
  ma_period:number;ma_type?:"sma"|"ema";valid?:boolean;
  structure_implementation_revision?:string;
  selector_components?:StructureSelectorComponents;
  structure_ranking?:StructureRanking;
  ma_structure_score?:number;structure_score?:number;structure_rank?:number;rank?:number;
  regime_raw?:number;retest_raw?:number;breakout_raw?:number;confirmation_raw?:number;
  regime_percentile?:number;retest_percentile?:number;breakout_percentile?:number;confirmation_percentile?:number;
  component_scores?:Record<string,StructureComponentScore>;
  bull_regime_count?:number;bull_success_count?:number;bull_success_rate?:number|null;
  bear_regime_count?:number;bear_success_count?:number;bear_success_rate?:number|null;
  bull_retest_count?:number;bull_retest_success_count?:number;bear_retest_count?:number;bear_retest_success_count?:number;
  retest_success_count?:number;retest_resolved_count?:number;retest_wilson_lower?:number;
  bull_breakout_count?:number;bull_breakout_success_count?:number;bull_breakout_fail_count?:number;bull_breakout_unresolved_count?:number;
  bear_breakout_count?:number;bear_breakout_success_count?:number;bear_breakout_fail_count?:number;bear_breakout_unresolved_count?:number;
  breakout_count?:number;breakout_success_count?:number;breakout_fail_count?:number;breakout_unresolved_count?:number;breakout_resolved_count?:number;
  breakout_wilson_lower?:number;confirmation_eligible_events?:number;confirmation_confirmed_events?:number;
  confirmation_not_confirmed_events?:number;confirmation_retest_safe_events?:number;confirmation_violation_events?:number;
  confirmation_ambiguous_events?:number;confirmation_unresolved_events?:number;confirmation_resolved_count?:number;
  confirmation_violation_rate?:number|null;confirmation_consistency_score?:number|null;
  gap_breakout_count?:number;entry_zone_missed_count?:number;strategy_executable_breakout_count?:number;
  execution_feasibility_ratio?:number|null;artifact_available?:boolean;train_return?:number|null;train_sharpe?:number|null;
  tie_break_reason?:string|null;[key:string]:unknown;
};
export type StructureArtifact = {
  structure_spec_version:string;structure_spec_hash:string;structure_implementation_revision?:string;ma_period:number;ma_type?:string;
  train_start:string;train_end:string;ohlc:Array<Record<string,unknown>>;daily_data?:Array<Record<string,unknown>>;
  reference_ma?:Array<{timestamp:string;value:number|null}>;events:Array<Record<string,unknown>>;event_markers?:Array<Record<string,unknown>>;
};
export type StructureArtifactResponse = {job_id:string;window_index:number;ma_period:number;structure_spec_version:string;structure_spec_hash:string;structure_implementation_revision?:string;candidate_summary:StructureCandidate;artifact:StructureArtifact};
export type SegmentAggregate = {
  complete_test_windows:number;positive_return_windows:number;positive_return_ratio:number|null;
  average_6m_return:number|null;median_6m_return:number|null;average_sharpe:number|null;median_sharpe:number|null;
  average_mdd:number|null;worst_6m_return:number|null;best_6m_return:number|null;segment_chained_return:number|null;continuous_execution:false;
};
export type OptimizationResult = {
  mode?:"single"|"rolling_6m";selection_mode?:OptimizationSelectionMode;structure_spec_version?:string;structure_spec_hash?:string;structure_implementation_revision?:string;comparison_mode?:string;
  results:OptimizationRow[]; ranking_metric:OptimizationMetric; best:OptimizationRow;
  skipped?:Array<{ma_period:number;code:string;message:string}>;
  failure_stage?:string;requested_evaluation_range?:string[];provider_requested_range?:string[];
  stability:{metric:OptimizationMetric;best_ma_period:number;from_ma:number;to_ma:number;relative_spread:number|null;stable:boolean;label:string;rows:OptimizationRow[]};
  data_fingerprint:string;provider:string;canonical_engine:boolean;
  data_coverage:{first_date:string;last_date:string;bars:number;warnings:string[]};
  train_test:{enabled:boolean;train_best?:OptimizationRow;test_result?:OptimizationRow;selection_source?:"TRAIN_ONLY";train_range?:string[];test_range?:string[]};
  rolling_windows?:RollingOptimizationWindow[];complete_windows?:number;provisional_windows?:number;
  test_only_aggregate?:SegmentAggregate;fixed_ma_aggregate?:SegmentAggregate;
  performance_aggregate?:SegmentAggregate;structure_aggregate?:SegmentAggregate;
  selection_history?:Array<{window:number;test_start:string;test_end:string;selected_ma:number;aggregate_included:boolean}>;
  selection_summary?:{count:number;average_ma:number|null;median_ma:number|null;minimum_ma:number|null;maximum_ma:number|null;ma_standard_deviation:number|null;adjacent_window_changes:number[];average_adjacent_change:number|null;median_adjacent_change:number|null};
  performance_selection_summary?:OptimizationResult["selection_summary"];structure_selection_summary?:OptimizationResult["selection_summary"];
  train_test_relationship?:{ranking_metric:OptimizationMetric;train_test_metric_correlation:number|null;train_test_return_correlation:number|null;test_positive_return_ratio:number|null;test_positive_sharpe_ratio:number|null;display_sharpe_threshold:number;test_sharpe_above_display_threshold_ratio:number|null;display_only:true};
  rolling_progress?:{window:number;windows_total:number;phase:string;ma_current?:number;ma_total?:number};
};
export type OptimizationJob = Omit<BackgroundJob,"payload"|"result"> & {payload:OptimizationPayload;result:Partial<OptimizationResult>};

export type MABoxSummary = Record<string, number | string | null>;
export type MABoxRun = {
  track: string; sma_period: number; summary: MABoxSummary;
  equity_curve: Array<{timestamp:string;equity:number;close:number}>;
  drawdown_curve: Array<{timestamp:string;drawdown:number}>;
  daily_ledger: Array<{timestamp:string;date:string;cash_end_of_day:number;quantity_end_of_day:number;close_price:number;market_value_close:number;equity_close:number;position_state:string;setup_state?:string;daily_realized_pnl?:number}>;
  executions: Array<Record<string, unknown>>; positions: Array<Record<string, unknown>>;
  events: Array<Record<string, unknown>>; data: Array<Record<string, unknown>>;
  counterfactual_summary?: Record<string, unknown>; counterfactual_trades?: Array<Record<string, unknown>>;
  boundary_tolerance?: Record<string, unknown>; box_context?: Record<string, unknown>;
};
export type MABoxStudy = {
  study_id: string; study_revision: string; spec_revision: string; spec_revision_number?: number; spec_hash: string;
  config_hash: string; config: {ticker:string;selected_ma:number;nearby_range:number;step:number;start_date:string;end_date:string;periods:number[];[key:string]:unknown};
  data_provenance: {ticker:string;provider:string;fingerprint:string|null;data_start:string;data_end:string;evaluation_start:string;evaluation_end:string;bars:number;adjustment_mode?:string|null;[key:string]:unknown};
  evaluation_start: string; evaluation_end: string; periods: number[]; selected_ma: number;
  buy_and_hold: MABoxRun; runs: Record<string, {MA_LONG_BASELINE: MABoxRun; MA_BOX_LONG_V1: MABoxRun}>;
  local_robustness?: {selected_ma:number;periods:number[];metrics:Record<string,{values:Array<{period:number;value:number|null}>;median:number|null;min:number|null;max:number|null}>;radii?:Record<string,{radius:number;available_periods:number[];expected_periods:number[];status:"COMPLETE"|"UNAVAILABLE_PERIODS_NOT_RUN"|string;metrics:Record<string,{median:number|null;min:number|null;max:number|null}>}>};
  selected_summary: {baseline: MABoxSummary|null;box: MABoxSummary|null;buy_and_hold: MABoxSummary};
};
export type MABoxRequest = {ticker:string;selected_ma:number;nearby_range:number;step:number;start_date:string;end_date:string};

export type MAAnalyticsRequest = {
  ticker:string; selected_ma:number; nearby_range:number; step:number;
  start_date:string; end_date:string;
  direction_mode:"LONG_ONLY"|"SHORT_ONLY"|"LONG_SHORT_SPLIT";
  entanglement_mode:"ALL"|"EXCLUDE_ENTANGLED"|"ONLY_ENTANGLED"|"SPLIT_ENTANGLED_CLEAN";
};
export type MAAnalyticsAggregate = {
  aggregate_id:string; aggregate_type:string; period:number; direction:string;
  entanglement_cohort:string; condition_type:string; target_type?:string;
  observation_origin?:string; eligible_count:number; resolved_count:number;
  success_count:number; censored_count:number; probability:number|null;
  wilson_lower:number|null; wilson_upper:number|null; low_sample_size:boolean;
  terminal_counts?:Record<string,number>; combined_probability?:number|null;
  trend_probability?:number|null;
};
export type MAAnalyticsEvent = {
  event_id:string; study_id:string; ticker:string; sma_period:number; direction:"LONG"|"SHORT";
  d1_date:string; d1_open:number; d1_high:number; d1_low:number; d1_close:number;
  ma_d1:number; ma_d1_previous:number; atr14_d1:number|null; reference_entry:number;
  volume_change:number|null; volume_evaluable:boolean;
  vol_ge_10:boolean; vol_ge_20:boolean; vol_ge_30:boolean; vol_lt_10:boolean;
  entanglement_cohort:string; box_active_at_session_start:boolean;
  box_formed_on_day1_close:boolean; box_active_after_day1_close:boolean;
  entanglement_box_id:string|null; entanglement_box_high:number|null; entanglement_box_low:number|null;
  d2_date:string|null; d2_close:number|null; d2_status:string; d2_success:boolean;
};
export type MAAnalyticsDailyBar = {
  date:string; open:number; high:number; low:number; close:number; volume:number|null;
  sma:number|null; atr14:number|null; long_day1_threshold:number|null;
  short_day1_threshold:number|null; event_ids:string[];
  box_active_at_session_start:boolean; box_formed_on_close:boolean; box_active_after_close:boolean;
  box_id_at_session_start?:string|null; box_high_at_session_start?:number|null; box_low_at_session_start?:number|null;
  box_id_after_close?:string|null; box_high_after_close?:number|null; box_low_after_close?:number|null;
  entanglement_cohort?:string;
};
export type MAAnalyticsTargetOutcome = {
  event_id:string; target_type:string; condition_type:string; observation_origin:string;
  target_level:number|null; observation_start_date:string|null; resolution_date:string|null;
  resolution_state:string|null; target_or_stop_first:string|null; eligible:boolean;
  [key:string]:unknown;
};
export type MAAnalyticsTargetAudit = {
  event_id:string; target_type:string; condition_type:string; observation_origin:string;
  date:string; stop_level:number; target_level:number; touch_resolution:string;
  [key:string]:unknown;
};
export type MAAnalyticsRetestZone = {
  date:string; ma:number; retest_zone_low:number; retest_zone_high:number;
  low:number; high:number; close:number; intersects:boolean;
};
export type MAAnalyticsFailure = {
  event_id:string; terminal_outcome:string; terminal_date:string|null;
  sideways_window_bars?:number; sideways_window_start?:string; sideways_window_end?:string;
  sideways_window_dates?:string[]; sideways_window_high?:number; sideways_window_low?:number;
  sideways_window_range?:number; sideways_atr_reference_date?:string; sideways_atr14?:number;
  sideways_range_atr?:number; sideways_threshold_atr?:number;
  retest_zone_history?:MAAnalyticsRetestZone[];
  [key:string]:unknown;
};
export type MAAnalyticsStudy = {
  study_id:string; status?:string; analytics_revision:string; spec_revision:string;
  spec_revision_number:number; spec_hash:string; config_hash:string; config:MAAnalyticsRequest;
  ticker:string; provider:string; data_fingerprint:string; evaluation_start:string;
  evaluation_end:string; bars:number; periods:number[]; period_summary:Array<Record<string,unknown>>;
  data_provenance?:Record<string,unknown>; reference_entry_label:string;
};
export type MAAnalyticsCreated = MAAnalyticsStudy;
export type MAAnalyticsChart = {
  study_id:string; period:number; daily_data:MAAnalyticsDailyBar[];
  events:MAAnalyticsEvent[]; failures:MAAnalyticsFailure[];
  target_outcomes?:MAAnalyticsTargetOutcome[];
  target_session_audit?:MAAnalyticsTargetAudit[];
};

export type ResearchEnvironment = {
  schema_version: number; study: string; generated_at: string;
  long_history_validation_status: string; long_history_research_performed: boolean;
  sensitivity_classification: string; next_family: string;
  environment_snapshot: {
    environment_snapshot_id: string; created_at: string; input_fingerprint_sha256: string;
    snapshot_sha256: string; snapshot_file?: string | null; snapshot_file_sha256?: string | null;
    target_range: {start:string;end:string};
  };
  readiness: {
    market_long_history_ready:boolean;mega_cap_universe_ready:boolean;etf_universe_ready:boolean;
    risk_free_ready:boolean;research_validation_ready:boolean;reasons:Record<string,string>;
  };
  data_history: {target_start:string;target_end:string;primary_target_acquired:boolean;validated_datasets:number;fabricated_bars:number;per_symbol_fair_start:boolean};
  universes: Record<string,{status:string;symbol_count:number;validated_datasets:number;target_requests_complete:number;actual_common_start:string|null;actual_common_end:string|null;inception_limited_coverage_accepted:boolean}>;
  cash_models: Record<string,{series_available:boolean;series_id?:string;first_observation?:string;last_observation?:string;observations?:number;manifest_sha256?:string;cache_sha256?:string}>;
  data_manifest:{path:string;sha256:string}; universe_manifest:{path:string;sha256:string};
  benchmark_reclassification:Record<string,{grade:string;supportive_policies:number;strong_policies:number}>;
};

export type ResearchCandidate = {
  candidate_id: string; family: string; hypothesis: string; spec_sha256: string;
  lifecycle_status: string; research_status: string; role: string;
  deployment_status: string; production_selector_value?: string | null;
};
export type ResearchDataset = {
  ticker: string; provider: string; adjustment_mode: string; first_date: string;
  last_date: string; bars: number; download_timestamp: string; ohlcv_sha256: string;
  coverage_status: string; preferred_start_available: boolean;
};
export type XsmomSummary = {
  study: string; grade: string; next_family: string; evaluation_start: string; evaluation_end: string;
  registration: {snapshot_id: string; spec_sha256: string; fingerprint: string};
  cash_models: Record<string, Record<string, {total_return:number;cagr:number;mdd:number;sharpe:number|null;exposure:number;turnover:number}>>;
};
export type VolatilityManagedSummary = {
  study:string; title:string; evidence_grade:string; next_family:string;
  registration:{snapshot_id:string;spec_sha256:string;fingerprint:string};
  evaluation:{data_start:string;signal_start:string;evaluation_start:string;evaluation_end:string;warmup_returns:number};
  parameters:{rv_lookback_sessions:number;target_annualized_volatility:number;max_equity_exposure:number;execution:string};
  primary_spy:Record<string,{managed:VolMetric;buy_hold:VolMetric;delta:Record<string,number|null>}>;
  robustness_summary:Record<string,{etfs:number;improvement_counts:Record<string,number>;median_delta:Record<string,number>;median_managed_exposure:number;median_cagr_sacrifice:number}>;
  crisis_analysis:Record<string,Array<{episode:string;managed:VolMetric;buy_hold:VolMetric;delta:Record<string,number>;minimum_target_exposure:number;sessions_actual_open_exposure_below_50:number}>>;
  cost_stress_spy:Record<string,Record<string,{managed:VolMetric;buy_hold:VolMetric;delta?:Record<string,number>}>>;
  cash_decomposition:Record<string,{managed_return_contribution_pp:number;incremental_managed_cash_effect_pp:number}>;
  walk_forward_summary:{spy_unique_tests:Record<string,number>;all_etf_unique_tests:Record<string,number>};
};
export type VolMetric = {total_return:number;cagr:number;annualized_volatility:number;mdd:number;sharpe:number|null;sortino:number|null;calmar:number|null;exposure:number;cash_pct:number;turnover:number;commission:number;slippage:number;cash_interest:number;number_of_trades:number};
export type ResearchFramework = {
  xsmom_benchmark?: XsmomSummary;
  volatility_managed_benchmark?: VolatilityManagedSummary;
  schema_version: number; title: string; warning: string; universe: string[];
  preferred_data_range: {start: string; end: string}; no_new_candidate_created: boolean;
  registry: {append_only: boolean; candidate_count: number; candidates: ResearchCandidate[]};
  benchmarks: Record<string, {name: string; rule: string; lookahead: string; policy_sensitive: boolean}>;
  execution_assumptions: {position: string; costs: string; policies: string[]; require_all_policies_when_sensitive: boolean; prohibition: string};
  candidate_protocol: {pre_result_spec: string; immutable_identity: string; statuses: string[]; promotion: string};
  viability_gate: {comparators: string[]; metrics: string[]; required_evidence: string[]; decision_labels: string[]; pass_contract: string};
  winner_concentration: Record<string, unknown>;
  cost_stress: Record<string, {commission_multiplier: number; slippage_multiplier: number}>;
  time_robustness: Record<string, unknown>;
  provenance: {actual_common_range: {start: string; end: string}; coverage_note: string; fingerprint_rule: string; datasets: ResearchDataset[]};
  history: {recalculated: boolean; studies: Array<{report_id: string; title: string; conclusion: string; report_sha256: string}>};
  benchmark_viability?: null | {study: string; evaluation_start: string; evaluation_end: string; next_family: string; candidate_created: boolean; report_id: string; grades: Record<string, {grade: string; supportive_policies: number; strong_policies: number}>; full_breadth: Record<string, Record<string, {cells: number; return_wins: number; sharpe_wins: number; mdd_wins: number; median_return_delta_pp: number; median_sharpe_delta: number; median_mdd_delta_pp: number}>>; walk_forward_breadth: Record<string, Record<string, {cells: number; return_wins: number; sharpe_wins: number; mdd_wins: number}>>};
  research_environment?: null | {
    study: string; status: string; sensitivity_classification: string; next_family: string;
    report_id: string; candidate_created: boolean;
    data_history: {target_start: string; target_end: string; primary_target_acquired: boolean; existing_common_start: string | null; existing_common_end: string | null; fabricated_bars: number};
    connectivity: {status: string; source: string};
    universes: Record<string, {status: string; symbol_count: number; validated_datasets: number; target_requests_complete: number; actual_common_start: string | null; actual_common_end: string | null; no_validated_cache: string[]}>;
    cash_models: Record<string, {series_available: boolean; description?: string; series?: string; compounding?: string; manifest?: string | null; fabricated_rates?: number}>;
    data_manifest: {path: string; sha256: string}; universe_manifest: {path: string; sha256: string};
  };
};

export class ApiClientError extends Error {
  details: ApiErrorDetails;
  constructor(message: string, details: Partial<ApiErrorDetails> = {}) {
    super(message);
    this.name = "ApiClientError";
    this.details = { message, ...details };
  }
}

function friendlyNetworkError(reason: unknown): Error {
  if (reason instanceof ApiClientError) return reason;
  if (reason instanceof TypeError) {
    return new ApiClientError("Backend service is temporarily unavailable.", { code: "BACKEND_UNAVAILABLE" });
  }
  return reason instanceof Error ? reason : new Error("Network request failed.");
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body?.detail === "object" ? body.detail : { message: body?.detail };
    const message = detail?.message || "Request failed";
    throw new ApiClientError(message, detail);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export const api = {
  health: () => fetch(`${API}/api/health`, { cache: "no-store" }).then(parse<{status: string}>).catch((error) => { throw friendlyNetworkError(error); }),
  dataProviderStatus: () => fetch(`${API}/api/data-provider/status`, { cache: "no-store" }).then(parse<DataProviderStatus>).catch((error) => { throw friendlyNetworkError(error); }),
  dataCenter: () => fetch(`${API}/api/data-center`, { cache: "no-store" }).then(parse<DataCenter>).catch((error) => { throw friendlyNetworkError(error); }),
  systemStatus: () => fetch(`${API}/api/system/status`, { cache: "no-store" }).then(parse<SystemStatus>).catch((error) => { throw friendlyNetworkError(error); }),
  jobs: () => fetch(`${API}/api/jobs`, { cache: "no-store" }).then(parse<BackgroundJob[]>).catch((error) => { throw friendlyNetworkError(error); }),
  checkProviders: () => fetch(`${API}/api/jobs/provider-connectivity-check`, { method: "POST" }).then(parse<BackgroundJob>).catch((error) => { throw friendlyNetworkError(error); }),
  repairProviderConnectivity: () => fetch(`${API}/api/jobs/provider-connectivity-repair`, { method: "POST" }).then(parse<BackgroundJob>).catch((error) => { throw friendlyNetworkError(error); }),
  fillResearchData: () => fetch(`${API}/api/jobs/research-market-data`, { method: "POST" }).then(parse<BackgroundJob>).catch((error) => { throw friendlyNetworkError(error); }),
  updateRiskFree: () => fetch(`${API}/api/jobs/risk-free-data`, { method: "POST" }).then(parse<BackgroundJob>).catch((error) => { throw friendlyNetworkError(error); }),
  validateResearchEnvironment: () => fetch(`${API}/api/jobs/research-environment-validation`, { method: "POST" }).then(parse<BackgroundJob>).catch((error) => { throw friendlyNetworkError(error); }),
  createOptimization: (payload: OptimizationPayload) => fetch(`${API}/api/optimizations`, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload) }).then(parse<OptimizationJob>).catch((error)=>{throw friendlyNetworkError(error);}),
  optimizations: () => fetch(`${API}/api/optimizations`, {cache:"no-store"}).then(parse<OptimizationJob[]>).catch((error)=>{throw friendlyNetworkError(error);}),
  optimization: (id:string) => fetch(`${API}/api/optimizations/${encodeURIComponent(id)}`, {cache:"no-store"}).then(parse<OptimizationJob>).catch((error)=>{throw friendlyNetworkError(error);}),
  cancelOptimization: (id:string) => fetch(`${API}/api/optimizations/${encodeURIComponent(id)}/cancel`, {method:"POST"}).then(parse<OptimizationJob>).catch((error)=>{throw friendlyNetworkError(error);}),
  retryOptimization: (id:string) => fetch(`${API}/api/optimizations/${encodeURIComponent(id)}/retry`, {method:"POST"}).then(parse<OptimizationJob>).catch((error)=>{throw friendlyNetworkError(error);}),
  structureArtifact: (id:string, windowIndex:number, maPeriod:number) => fetch(`${API}/api/optimizations/${encodeURIComponent(id)}/structure/windows/${encodeURIComponent(windowIndex)}/candidates/${encodeURIComponent(maPeriod)}`, {cache:"no-store"}).then(parse<StructureArtifactResponse>).catch((error)=>{throw friendlyNetworkError(error);}),
  retryJob: (id: string) => fetch(`${API}/api/jobs/${encodeURIComponent(id)}/retry`, { method: "POST" }).then(parse<BackgroundJob>).catch((error) => { throw friendlyNetworkError(error); }),
  researchFramework: () => fetch(`${API}/api/research/framework`, { cache: "no-store" }).then(parse<ResearchFramework>).catch((error) => { throw friendlyNetworkError(error); }),
  researchEnvironmentCurrent: () => fetch(`${API}/api/research/environment/current`, { cache: "no-store" }).then(parse<ResearchEnvironment>).catch((error) => { throw friendlyNetworkError(error); }),
  run: (form: FormState) => fetch(`${API}/api/backtests`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(form) }).then(parse<BacktestResult>).catch((error) => { throw friendlyNetworkError(error); }),
  history: () => fetch(`${API}/api/backtests`, { cache: "no-store" }).then(parse<HistoryItem[]>).catch((error) => { throw friendlyNetworkError(error); }),
  get: (id: string) => fetch(`${API}/api/backtests/${id}`, { cache: "no-store" }).then(parse<{result: BacktestResult; parameters: FormState}>).catch((error) => { throw friendlyNetworkError(error); }),
  positionAudit: (backtestId: string, positionId: string) => fetch(`${API}/api/backtests/${encodeURIComponent(backtestId)}/positions/${encodeURIComponent(positionId)}/audit`, { cache: "no-store" }).then(parse<PositionAudit>).catch((error) => { throw friendlyNetworkError(error); }),
  day1StopDiagnostic: (backtestId: string) => fetch(`${API}/api/backtests/${encodeURIComponent(backtestId)}/diagnostics/day1-stop`, { cache: "no-store" }).then(parse<Day1StopDiagnostic>).catch((error) => { throw friendlyNetworkError(error); }),
  ambiguitySensitivity: (backtestId: string) => fetch(`${API}/api/backtests/${encodeURIComponent(backtestId)}/diagnostics/ambiguity-sensitivity`, { method: "POST" }).then(parse<AmbiguitySensitivity>).catch((error) => { throw friendlyNetworkError(error); }),
  delete: (id: string) => fetch(`${API}/api/backtests/${id}`, { method: "DELETE" }).then(parse<void>).catch((error) => { throw friendlyNetworkError(error); }),
  maBoxStudies: () => fetch(`${API}/api/ma-box/studies`, { cache: "no-store" }).then(parse<Array<Record<string, unknown>>>).catch((error) => { throw friendlyNetworkError(error); }),
  createMaBoxStudy: (payload: MABoxRequest) => fetch(`${API}/api/ma-box/studies`, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload) }).then(parse<MABoxStudy>).catch((error) => { throw friendlyNetworkError(error); }),
  maBoxStudy: (id:string) => fetch(`${API}/api/ma-box/studies/${encodeURIComponent(id)}`, { cache: "no-store" }).then(parse<Record<string, unknown>>).catch((error) => { throw friendlyNetworkError(error); }),
  maBoxSummary: (id:string) => fetch(`${API}/api/ma-box/studies/${encodeURIComponent(id)}/summary`, { cache: "no-store" }).then(parse<Record<string, unknown>>).catch((error) => { throw friendlyNetworkError(error); }),
  maBoxRun: (id:string, period:number, track:string) => fetch(`${API}/api/ma-box/studies/${encodeURIComponent(id)}/runs/${period}/${encodeURIComponent(track)}`, { cache: "no-store" }).then(parse<{run:MABoxRun}>).catch((error) => { throw friendlyNetworkError(error); }),
  maBoxChart: (id:string, period:number) => fetch(`${API}/api/ma-box/studies/${encodeURIComponent(id)}/chart/${period}`, { cache: "no-store" }).then(parse<Record<string, unknown>>).catch((error) => { throw friendlyNetworkError(error); }),
  createMaBreakoutAnalyticsStudy: (payload: MAAnalyticsRequest) => fetch(`${API}/api/ma-analytics/studies`, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload) }).then(parse<MAAnalyticsCreated>).catch((error)=>{throw friendlyNetworkError(error);}),
  maBreakoutAnalyticsSummary: (id:string) => fetch(`${API}/api/ma-analytics/studies/${encodeURIComponent(id)}/summary`, {cache:"no-store"}).then(parse<Record<string,unknown>>).catch((error)=>{throw friendlyNetworkError(error);}),
  maBreakoutAnalyticsEvents: (id:string, period?:number) => fetch(`${API}/api/ma-analytics/studies/${encodeURIComponent(id)}/events${period == null ? "" : `?period=${period}`}`, {cache:"no-store"}).then(parse<{events:MAAnalyticsEvent[];count:number}>).catch((error)=>{throw friendlyNetworkError(error);}),
  maBreakoutAnalyticsEvent: (id:string, eventId:string) => fetch(`${API}/api/ma-analytics/studies/${encodeURIComponent(id)}/events/${encodeURIComponent(eventId)}`, {cache:"no-store"}).then(parse<Record<string,unknown>>).catch((error)=>{throw friendlyNetworkError(error);}),
  maBreakoutAnalyticsChart: (id:string, period:number) => fetch(`${API}/api/ma-analytics/studies/${encodeURIComponent(id)}/chart/${period}`, {cache:"no-store"}).then(parse<MAAnalyticsChart>).catch((error)=>{throw friendlyNetworkError(error);}),
  exportMaBreakoutAnalytics: (id:string, format:"json"|"events.csv"|"aggregates.csv") => fetch(`${API}/api/ma-analytics/studies/${encodeURIComponent(id)}/export?format=${encodeURIComponent(format)}`, {cache:"no-store"}).then(async response=>{if(!response.ok){const body=await response.json().catch(()=>({}));throw new ApiClientError(body?.detail?.message??"Export failed",body?.detail??{});}return format==="json"?response.json():response.text();}).catch((error)=>{throw friendlyNetworkError(error);}),
};
