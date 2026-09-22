"""Predeclared Research Environment Validation v3 contracts.

This module contains methodology only.  It neither registers a strategy nor
selects a benchmark parameter after observing results.
"""
from __future__ import annotations

from datetime import date


PRIMARY_HISTORY = {"start": date(2010, 1, 1), "end": date(2026, 9, 1)}
OPTIONAL_EARLY_HISTORY = {"start": date(2005, 1, 1), "end": date(2009, 12, 31)}

# The original eleven-symbol universe is intentionally renamed rather than
# represented as a generic US-equity universe.  It remains a selected-at-the-
# end-of-sample list and is not point-in-time constituent data.
MEGA_CAP_TECH_UNIVERSE = (
    "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "AVGO",
    "SPY", "QQQ",
)

# Fixed before Environment v3 results.  An ETF being listed after 2010 is an
# observed coverage limitation, never a reason to synthesize earlier bars.
ETF_RESEARCH_UNIVERSE = (
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "XLP",
    "XLY", "XLU", "XLB", "XLRE",
)

UNIVERSES = {
    "MEGA_CAP_TECH_UNIVERSE": {
        "symbols": MEGA_CAP_TECH_UNIVERSE,
        "purpose": "Frozen prior research universe; mega-cap/growth concentrated and not a general-US-equity sample.",
        "point_in_time": False,
        "survivorship_status": "END_OF_SAMPLE_SELECTED; NOT SURVIVORSHIP_FREE",
    },
    "ETF_RESEARCH_UNIVERSE": {
        "symbols": ETF_RESEARCH_UNIVERSE,
        "purpose": "Broad-market and sector ETF environment intended to reduce single-company and winner-concentration effects.",
        "point_in_time": False,
        "survivorship_status": "FIXED ETF LIST; REDUCES BUT DOES NOT ELIMINATE SELECTION/SURVIVORSHIP BIAS",
    },
}

ALLOWED_RESEARCH_STRATEGIES = (
    "BUY_AND_HOLD", "SMA200_TREND", "DONCHIAN_20_10", "SIMPLE_V2", "ADVANCED_V2",
)
FROZEN_BENCHMARK_PARAMETERS = {
    "SMA200_TREND": {"period": 200, "execution": "signal on completed close; next-session open"},
    "DONCHIAN_20_10": {"entry_lookback": 20, "exit_lookback": 10, "levels": "prior completed sessions only"},
}

# The common evaluation date is the first session for which the largest fixed
# benchmark warm-up is fully complete.  Buy & Hold is deliberately delayed to
# the same date.
WARMUP_CONTRACT = {
    "largest_completed_bar_requirement": 200,
    "evaluation_start_rule": "For each comparison group, use the latest first-eligible date after 200 completed bars across every included dataset.",
    "buy_and_hold_rule": "Buy & Hold begins at the same common evaluation start and receives no warm-up-period return.",
}

MARKET_CYCLE_WINDOWS = (
    ("2010_2012", date(2010, 1, 1), date(2012, 12, 31)),
    ("2013_2015", date(2013, 1, 1), date(2015, 12, 31)),
    ("2016_2018", date(2016, 1, 1), date(2018, 12, 31)),
    ("2019_2021", date(2019, 1, 1), date(2021, 12, 31)),
    ("2022_2023", date(2022, 1, 1), date(2023, 12, 31)),
    ("2024_2026", date(2024, 1, 1), date(2026, 9, 1)),
)

CRISIS_EPISODES = (
    ("2011_CORRECTION", date(2011, 4, 29), date(2011, 10, 3)),
    ("2015_2016_CORRECTION", date(2015, 5, 20), date(2016, 2, 11)),
    ("2018_Q4", date(2018, 9, 20), date(2018, 12, 24)),
    ("2020_CRASH", date(2020, 2, 19), date(2020, 3, 23)),
    ("2022_BEAR", date(2022, 1, 3), date(2022, 10, 12)),
)

DESCRIPTIVE_REGIME_CONTRACT = {
    "trend": "Use the already frozen Framework v2 convention within each completed evaluation window: SPY total return > +5% = strong uptrend, < -5% = downtrend, otherwise sideways.",
    "volatility": "SPY completed daily-return annualized volatility >=25% = high, <15% = low, otherwise medium.",
    "use": "Ex-post descriptive attribution only; never an entry, exit, universe-selection, or parameter-tuning condition.",
}

CASH_MODELS = {
    "CASH_ZERO": {
        "available_without_external_series": True,
        "description": "Uninvested cash earns exactly 0%; this is the existing research convention.",
    },
    "CASH_RISK_FREE": {
        "available_without_external_series": False,
        "series": "FRED DGS3MO (3-Month Treasury Constant Maturity Rate)",
        "units": "annual percent",
        "observation_lag": "An observation dated t may be used only after t; accrual uses the latest observation dated on or before the prior research session.",
        "compounding": "ACT/365 effective compounding: (1 + annual_yield/100)^(calendar_days/365) - 1.",
        "balance": "Interest accrues on portfolio cash only, never on invested market value.",
    },
}

SENSITIVITY_LABELS = ("ROBUST", "MIXED", "ENVIRONMENT-SENSITIVE", "UNAVAILABLE")
VIABILITY_LABELS = (
    "NOT SUPPORTED", "PROMISING — FAMILY WORTH STUDYING", "STRONG RETROSPECTIVE EVIDENCE",
)
