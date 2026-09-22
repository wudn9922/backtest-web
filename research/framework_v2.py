"""Frozen contracts for Research Framework v2.

Definitions in this module are research infrastructure, not production strategy
registration.  Result-producing code may read these contracts but must not edit
them after observing results.
"""
from __future__ import annotations

UNIVERSE = (
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "AVGO",
    "SPY", "QQQ",
)
SINGLE_STOCKS = UNIVERSE[:9]
ETFS = UNIVERSE[9:]
PREFERRED_DATA_RANGE = {"start": "2010-01-01", "end": "2026-09-01"}
DAILY_POLICIES = ("conservative", "ohlc_heuristic", "favorable")

BASELINE_STATUS = {
    "SIMPLE_V2": {
        "display_name": "Simple Strategy v2",
        "role": "RESEARCH BASELINE",
        "status": "REJECTED",
        "deployment": "NOT VALIDATED FOR FORWARD DEPLOYMENT",
    },
    "ADVANCED_V2": {
        "display_name": "Advanced Strategy v2",
        "role": "RESEARCH BASELINE",
        "status": "REJECTED",
        "deployment": "NOT VALIDATED FOR FORWARD DEPLOYMENT",
    },
    "M3": {
        "display_name": "M3",
        "role": "FROZEN RESEARCH BASELINE",
        "status": "REJECTED",
        "deployment": "NEVER PROMOTED TO PRODUCTION",
    },
}

BENCHMARKS = {
    "BUY_AND_HOLD": {
        "name": "Buy & Hold",
        "rule": "Buy maximum affordable whole shares on the first study-session open and sell on the final close.",
        "lookahead": "None; opening and final-closing prices are known only at their execution phase.",
        "policy_sensitive": False,
    },
    "SPY_BUY_AND_HOLD": {
        "name": "SPY Buy & Hold",
        "rule": "Apply the same costed Buy & Hold contract to SPY over the identical comparison dates.",
        "lookahead": "No symbol strategy data selects SPY exposure.",
        "policy_sensitive": False,
    },
    "SMA200_TREND": {
        "name": "200-day MA trend benchmark",
        "rule": "Close(t) > SMA200(t) schedules long at t+1 open; Close(t) <= SMA200(t) schedules cash at t+1 open.",
        "lookahead": "The opening decision uses only the previous completed close and SMA200.",
        "policy_sensitive": False,
    },
    "DONCHIAN_20_10": {
        "name": "Donchian 20/10 benchmark",
        "rule": "Long on a 20-session high breakout; exit on a 10-session low. Both thresholds exclude the current bar.",
        "lookahead": "At t, entry=max(high[t-20:t-1]); exit=min(low[t-10:t-1]).",
        "policy_sensitive": True,
    },
}

EXECUTION_ASSUMPTIONS = {
    "position": "Long only, one whole-share position, no leverage, residual cash yield 0%.",
    "costs": "Use the candidate's frozen commission and slippage; report both independently.",
    "policies": list(DAILY_POLICIES),
    "require_all_policies_when_sensitive": True,
    "prohibition": "A report may not select or omit a policy after seeing its result.",
}

COST_STRESS = {
    "BASELINE": {"commission_multiplier": 1, "slippage_multiplier": 1},
    "DOUBLE_COMMISSION": {"commission_multiplier": 2, "slippage_multiplier": 1},
    "DOUBLE_SLIPPAGE": {"commission_multiplier": 1, "slippage_multiplier": 2},
    "DOUBLE_BOTH": {"commission_multiplier": 2, "slippage_multiplier": 2},
}

TIME_ROBUSTNESS = {
    "calendar_year": True,
    "rolling_6_month": True,
    "rolling_12_month": True,
    "required_fields": ["positive_periods", "negative_periods", "worst_period", "best_period"],
}

WINNER_CONCENTRATION = {
    "profit_contribution_counts": [1, 3, 5, 10],
    "remove_largest_winner_per_symbol": True,
    "trim_fractions": [0.01, 0.05],
    "automatic_flag": "WINNER_CONCENTRATED",
    "flag_rule": "Flag when the top 10% of profitable positions contribute at least 70% of positive gross trade PnL, or a result loses its positive matched edge after the required 5% trim.",
}

VIABILITY_GATE = {
    "comparators": ["BUY_AND_HOLD", "SPY_BUY_AND_HOLD", "SMA200_TREND", "DONCHIAN_20_10"],
    "metrics": ["total_return", "cagr", "max_drawdown", "sharpe_ratio", "sortino_ratio", "calmar_ratio", "exposure_pct", "turnover", "total_commission", "estimated_slippage_cost"],
    "required_evidence": [
        "Cross-symbol return and risk-adjusted breadth",
        "Calendar-year, rolling-6-month, and rolling-12-month breadth",
        "All three Daily OHLC policies when ordering can affect execution",
        "Winner-concentration diagnostics",
        "All four fixed cost scenarios",
        "Clustered or block-aware uncertainty; ticker×period×policy is not IID",
    ],
    "decision_labels": ["REJECTED", "PROMISING", "FORWARD_TEST_CANDIDATE"],
    "pass_contract": "No single metric can pass the gate. A candidate must have majority directional breadth versus the fixed suite, no policy-sign reversal in the primary conclusion, acceptable MDD trade-off, and coherent matched-entry evidence under stressed costs.",
}

CANDIDATE_PROTOCOL = {
    "pre_result_spec": "A completed STRATEGY_SPEC.md must be saved and hashed before any result run.",
    "immutable_identity": "Any rule or parameter change requires a new candidate ID such as TREND_002; tested IDs are append-only.",
    "statuses": ["DRAFT", "TESTED", "REJECTED", "PROMISING", "FORWARD_TEST_CANDIDATE"],
    "required_registry_fields": ["candidate_id", "family", "created_at", "hypothesis", "spec_sha256", "parameters", "data_universe", "research_status"],
    "promotion": "Research candidates never enter the production selector without an explicit future promotion decision.",
}

