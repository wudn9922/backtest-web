"""Research-only cash-return accounting.

Production Portfolio and strategy engines are intentionally untouched.  The
classes here define the accounting contract that a future Environment v3 study
must use after a real, validated risk-free series has been acquired.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
import math

import pandas as pd

from app.backtest.portfolio import Portfolio


@dataclass(frozen=True)
class CashAccrual:
    model: str
    opening_cash: float
    interest: float
    closing_cash: float
    annual_rate_pct: float | None
    observation_date: str | None
    calendar_days: int


class CashReturnModel(ABC):
    name: str

    @abstractmethod
    def accrue(self, cash: float, previous_session: datetime | pd.Timestamp | None,
               current_session: datetime | pd.Timestamp) -> CashAccrual:
        """Accrue only cash between consecutive research sessions."""


class ZeroCashModel(CashReturnModel):
    name = "CASH_ZERO"

    def accrue(self, cash, previous_session, current_session) -> CashAccrual:
        days = 0 if previous_session is None else max(0, (pd.Timestamp(current_session).date() - pd.Timestamp(previous_session).date()).days)
        return CashAccrual(self.name, float(cash), 0.0, float(cash), None, None, days)


class RiskFreeCashModel(CashReturnModel):
    """Lag-safe ACT/365 cash accrual from observed annual percentage yields."""

    name = "CASH_RISK_FREE"

    def __init__(self, annual_yield_pct: pd.Series):
        if not isinstance(annual_yield_pct, pd.Series) or annual_yield_pct.empty:
            raise ValueError("A non-empty historical risk-free series is required")
        series = pd.to_numeric(annual_yield_pct, errors="coerce").dropna().sort_index()
        index = pd.DatetimeIndex(series.index)
        if index.tz is None:
            index = index.tz_localize("UTC")
        else:
            index = index.tz_convert("UTC")
        series.index = index
        if series.index.has_duplicates or not series.index.is_monotonic_increasing:
            raise ValueError("Risk-free timestamps must be unique and sorted")
        if (~series.map(math.isfinite)).any() or (series <= -100).any() or (series > 100).any():
            raise ValueError("Risk-free annual percentages are outside the accepted validation range")
        self.series = series.astype(float)

    def _known_rate(self, prior_date: date) -> tuple[float, pd.Timestamp]:
        # Strictly no future information: current-session observations are not
        # eligible.  The latest observation known by the prior session is used
        # through weekends/holidays without backward-filling before inception.
        eligible = self.series[self.series.index.date <= prior_date]
        if eligible.empty:
            raise ValueError(f"No risk-free observation was known by {prior_date.isoformat()}")
        return float(eligible.iloc[-1]), pd.Timestamp(eligible.index[-1])

    def accrue(self, cash, previous_session, current_session) -> CashAccrual:
        opening = float(cash)
        if previous_session is None:
            return CashAccrual(self.name, opening, 0.0, opening, None, None, 0)
        previous = pd.Timestamp(previous_session)
        current = pd.Timestamp(current_session)
        days = max(0, (current.date() - previous.date()).days)
        if not days or not opening:
            return CashAccrual(self.name, opening, 0.0, opening, None, None, days)
        rate, observed = self._known_rate(previous.date())
        factor = (1.0 + rate / 100.0) ** (days / 365.0) - 1.0
        interest = opening * factor
        return CashAccrual(
            self.name, opening, interest, opening + interest, rate,
            observed.date().isoformat(), days,
        )


class ResearchCashPortfolio(Portfolio):
    """Portfolio-compatible research ledger with explicit cash-only interest."""

    def __init__(self, cash: float, commission_pct: float, slippage_pct: float,
                 cash_model: CashReturnModel):
        super().__init__(cash, commission_pct, slippage_pct)
        self.cash_model = cash_model
        self.total_cash_yield = 0.0
        self.cash_accruals: list[CashAccrual] = []
        self._previous_session: pd.Timestamp | None = None

    def accrue_before_open(self, timestamp: datetime | pd.Timestamp) -> CashAccrual:
        accrual = self.cash_model.accrue(self.cash, self._previous_session, timestamp)
        self.cash = accrual.closing_cash
        self.total_cash_yield += accrual.interest
        self.cash_accruals.append(accrual)
        self._previous_session = pd.Timestamp(timestamp)
        return accrual

