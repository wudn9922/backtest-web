"""Predeclared benchmark viability design; contains no result imports."""
from __future__ import annotations

from datetime import date

SYMBOLS = ("NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "AVGO", "SPY", "QQQ")
POLICIES = ("conservative", "ohlc_heuristic", "favorable")
BENCHMARKS = ("BUY_AND_HOLD", "SMA200_TREND", "DONCHIAN_20_10")
DATA_START = date(2020, 12, 3)
DATA_END = date(2026, 9, 1)
SMA_PERIOD = 200
DONCHIAN_ENTRY = 20
DONCHIAN_EXIT = 10

COST_SCENARIOS = {
    "BASELINE": (1.0, 1.0),
    "DOUBLE_COMMISSION": (2.0, 1.0),
    "DOUBLE_SLIPPAGE": (1.0, 2.0),
    "DOUBLE_BOTH": (2.0, 2.0),
}

COMPARISON_CLASSIFICATION = {
    "RISK_ADJUSTED_WIN": "Sharpe and Calmar improve and MDD is no worse.",
    "RETURN_WIN": "Return improves but the complete risk-adjusted condition does not.",
    "DRAWDOWN_WIN": "MDD improves while Return does not.",
    "LOSS": "Return, Sharpe and MDD all fail to improve.",
    "MIXED": "Every other combination.",
}

REGIME = {
    "trend": "SPY window return >+5% strong uptrend, <-5% downtrend, otherwise sideways.",
    "volatility": "SPY completed daily-return annualized volatility >=25% high, <15% low, otherwise medium.",
    "research_only": True,
}

GRADING = {
    "STRONG_RETROSPECTIVE_EVIDENCE": "Full-period median Return and Sharpe deltas positive with >=7/11 breadth; MDD breadth >=7/11; rolling and walk-forward majority in >=2 policies; double-both cost median Return remains positive; clustered mean lower bound >0; no winner-concentration flag.",
    "PROMISING_FAMILY_WORTH_STUDYING": "At least two policies have >=6/11 full-period Return or Sharpe breadth with positive corresponding median; at least half of rolling and walk-forward cells are directionally supportive; double-both median Return is not negative in those policies.",
    "NOT_SUPPORTED": "Every other result.",
    "winner_concentrated": "Top 10% of winning trades >=70% of gross winning PnL, or pooled net PnL turns nonpositive after removing each symbol's largest winner.",
}

WALK_FORWARD_TESTS = (
    ("F1", date(2023, 1, 1), date(2023, 6, 30)),
    ("F2", date(2023, 7, 1), date(2023, 12, 31)),
    ("F3", date(2024, 1, 1), date(2024, 6, 30)),
    ("F4", date(2024, 7, 1), date(2024, 12, 31)),
    ("F5", date(2025, 1, 1), date(2025, 6, 30)),
    ("F6", date(2025, 7, 1), date(2025, 12, 31)),
    ("F7", date(2026, 1, 1), date(2026, 6, 30)),
)

