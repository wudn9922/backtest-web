import type { FormState } from "./types";

export const DEFAULT_FORM: FormState = {
  ticker: "NVDA", strategy: "advanced", start_date: "2021-09-01", end_date: "2026-09-01",
  initial_capital: 100000, position_size_pct: 100, execution_model: "daily_conservative", execution_policy: "conservative", market_data_provider: "auto", commission_pct: .05, slippage_pct: .02, force_close_at_end: true,
  parameters: { ma_type: "sma", ma_period: 20, breakout_trigger_pct: 1, entry_stop_pct: 1.5, exit_below_ma_pct: 1.5, volume_increase_pct: 10, ma_risk_pct: 1.5, first_tp_pct: 3, bias_lookback: 126, bias_sigma_multiple: 2, atr_period: 14, atr_multiple: 2, extreme_tp_pct_q0: 10, max_extreme_tp_count: 3, minimum_position_pct_q0: 20, day1_stop_pct: 3 },
};
