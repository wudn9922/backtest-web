"""Predeclared Simple-v2 viability design.

This module intentionally contains no simulation imports.  The definitions and
decision thresholds are frozen before results are calculated; none is a trading
rule, parameter search, or production registration.
"""
from datetime import date, timedelta

SYMBOLS = ("NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "AVGO", "SPY", "QQQ")
ETFS = ("SPY", "QQQ")
POLICIES = ("conservative", "ohlc_heuristic", "favorable")
PERIODS = {
    "FULL": (date(2021, 9, 1), date(2026, 9, 1)),
    "A": (date(2021, 9, 1), date(2023, 12, 31)),
    "B": (date(2024, 1, 1), date(2026, 9, 1)),
}
TEST_BLOCKS = (
    ("F1", date(2023, 9, 1), date(2024, 2, 29)),
    ("F2", date(2024, 3, 1), date(2024, 8, 31)),
    ("F3", date(2024, 9, 1), date(2025, 2, 28)),
    ("F4", date(2025, 3, 1), date(2025, 8, 31)),
    ("F5", date(2025, 9, 1), date(2026, 2, 28)),
    ("F6", date(2026, 3, 1), date(2026, 9, 1)),
)
FORWARD_HORIZONS = (5, 10, 20, 40, 60)
EXIT_FORWARD_HORIZONS = (5, 10, 20, 40)


def walk_forward_folds():
    rows = []
    for name, start, end in TEST_BLOCKS:
        train_end = start - timedelta(days=1)
        rows.append({"design": "expanding", "fold": name, "train_start": date(2021, 9, 1),
                     "train_end": train_end, "test_start": start, "test_end": end})
        rows.append({"design": "rolling", "fold": name, "train_start": date(start.year - 2, start.month, start.day),
                     "train_end": train_end, "test_start": start, "test_end": end})
    return rows


STRATEGY_FREEZE = {
    "simple": "Production SIMPLE_V2, unmodified: Entry Zone v2 and previous-day-MA full exit.",
    "advanced": "Production ADVANCED_V2, unmodified and used only as a frozen comparator.",
    "shared": [
        "Daily OHLC; MA/ATR/Bias inputs retain production look-back semantics",
        "Entry Zone v2 LowerEntry/UpperEntry/no-chase semantics",
        "Whole shares, canonical capital, position size, commission and slippage",
        "The selected existing Conservative/OHLC Heuristic/Favorable execution policy",
    ],
    "forbidden": ["strategy change", "parameter sweep", "optimization", "new production strategy", "future-data feature"],
}

BENCHMARKS = {
    "BUY_AND_HOLD": {
        "entry": "First usable study session OPEN; actual buy price includes buy slippage.",
        "sizing": "Maximum whole shares affordable under the canonical position-size allocation including buy commission; residual cash remains cash at 0% yield.",
        "exit": "Last study session CLOSE; actual sell price includes sell slippage and sell commission.",
        "trades": "Exactly one buy and one final sell.",
    },
    "ENTRY_ZONE_HOLD": {
        "entry": "First valid production Simple Entry Zone v2 fill: same LowerEntry, UpperEntry, no-chase and gap semantics.",
        "exit": "No tactical exit; final study-session CLOSE only.",
        "fixed_horizons": "Every valid signal is also evaluated independently at 20/40/60 subsequent sessions. Entry day is day 0; incomplete horizons are censored, not zero.",
        "claim": "Research benchmark only; overlapping signal lifecycles are not a portfolio.",
    },
}

# Mutually exclusive label, frozen before comparison.
COMPARISON_LABELS = {
    "RISK_ADJUSTED_WIN": "Simple Sharpe and Calmar are both higher and MDD is no worse than Buy & Hold.",
    "RETURN_WIN": "Simple total return is higher, but the complete risk-adjusted-win condition is not met.",
    "DRAW": "Absolute return delta <= 1 percentage point and absolute Sharpe delta <= 0.10.",
    "LOSS": "Every other case.",
}

AMBIGUITY_CLASSIFICATION = {
    "ROBUST": "All three policies have the same sign for cross-symbol median Simple-minus-BuyHold return and Sharpe; at least 8/11 symbols keep the return-delta sign; median return spread <= 20 pp.",
    "POLICY_SENSITIVE": "A cross-symbol median return or Sharpe sign flips, or fewer than 7/11 symbols keep the return-delta sign across all policies.",
    "MIXED": "Neither ROBUST nor POLICY_SENSITIVE.",
}

WF_TRAIN_GATE = {
    "scope": "Per train window and policy; Simple is compared independently with Advanced and Buy & Hold over 11 symbols.",
    "return_breadth": "At least 6/11 symbols have nonnegative return delta versus each comparator.",
    "median_return": "Median return delta is strictly positive versus each comparator.",
    "median_sharpe": "Median Sharpe delta is nonnegative versus each comparator.",
    "mdd": "Median MDD delta is no worse than -20 pp versus Advanced and -10 pp versus Buy & Hold (positive is better).",
    "concentration": "Largest positive symbol return delta is no more than 50% of positive deltas versus each comparator.",
    "fold_gate": "PASS only if Conservative and at least one other policy satisfy every condition. Train never tunes or selects parameters.",
}

# This evidence gate is deliberately demanding.  It is evaluated mechanically
# and cannot be edited by a result-producing function.
VIABILITY_GATE = {
    "strong": [
        "Full-period median Return and Sharpe deltas versus both Advanced and BuyHold are positive under all three policies, with return breadth >=6/11 each.",
        "At least four of six policy×subperiod cells have positive median Return and Sharpe deltas versus both comparators.",
        "At least two policies have majority Return breadth versus both comparators in >=4/6 six-month folds.",
        "No cross-symbol median Return/Sharpe sign flip from intrabar policy; median Return spread <=20 pp.",
        "Under 2x commission+slippage, median Return deltas remain positive versus both comparators in every policy with breadth >=6/11.",
        "Two-way ticker×time-block bootstrap mean-delta lower bound is >0 versus both comparators in at least two policies.",
        "Winner concentration diagnostics remain directionally positive after removing each symbol's largest winner and after 5% trimming.",
        "Median MDD deterioration versus BuyHold is no worse than 15 pp, and median Sharpe plus Calmar deltas are positive in at least two policies.",
    ],
    "promising": [
        "Full-period median Return delta is positive versus both comparators in at least two policies, with >=6/11 breadth in those policies.",
        "At least half of policy×subperiod cells have positive median Return delta versus both comparators.",
        "At least one policy has majority Return breadth versus both comparators in >=3/6 folds.",
        "Worst cost stress retains a positive median Return delta versus Advanced and BuyHold in at least two policies.",
        "Result is not invalidated by an intrabar-policy median sign reversal versus BuyHold.",
    ],
    "labels": ["NOT SUPPORTED", "PROMISING — NEEDS FORWARD DATA", "STRONG RETROSPECTIVE EVIDENCE — FREEZE FOR FORWARD TEST"],
}

COST_SCENARIOS = {
    "BASELINE": {"commission_multiplier": 1.0, "slippage_multiplier": 1.0},
    "DOUBLE_COMMISSION": {"commission_multiplier": 2.0, "slippage_multiplier": 1.0},
    "DOUBLE_SLIPPAGE": {"commission_multiplier": 1.0, "slippage_multiplier": 2.0},
    "DOUBLE_BOTH": {"commission_multiplier": 2.0, "slippage_multiplier": 2.0},
}

STATISTICS = {
    "replicates": 4000,
    "clusters": "ticker and chronological six-month market block; weights are multiplied in a two-way block bootstrap",
    "primary": "breadth, median, sign consistency and concentration; no iid t-test or pseudo-precise p-value",
}

