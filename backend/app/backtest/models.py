from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrategyName(StrEnum):
    SIMPLE = "simple"
    ADVANCED = "advanced"
    ADVANCED_DAY1_STOP = "advanced_day1_stop"


class StrategyState(StrEnum):
    FLAT = "FLAT"
    ENTRY_ARMED = "ENTRY_ARMED"
    LONG_VALIDATING_DAY1 = "LONG_VALIDATING_DAY1"
    LONG_VALIDATING_DAY2 = "LONG_VALIDATING_DAY2"
    LONG_NORMAL = "LONG_NORMAL"
    BREAK_PROTECTION = "BREAK_PROTECTION"
    POST_FIRST_TP = "POST_FIRST_TP"
    PENDING_FULL_EXIT_NEXT_OPEN = "PENDING_FULL_EXIT_NEXT_OPEN"
    CLOSED = "CLOSED"


class StrategyParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ma_type: Literal["sma", "ema"] = "sma"
    ma_period: int = Field(20, ge=2, le=500)
    breakout_trigger_pct: float = Field(1.0, ge=0)
    entry_stop_pct: float = Field(1.5, ge=0)
    exit_below_ma_pct: float = Field(1.5, ge=0)
    volume_increase_pct: float = Field(10.0, ge=0, le=100)
    ma_risk_pct: float = Field(1.5, ge=0)
    day1_stop_pct: float = Field(3.0, ge=0, le=100)
    first_tp_pct: float = Field(3.0, gt=0)
    bias_lookback: int = Field(126, ge=2, le=1000)
    bias_sigma_multiple: float = Field(2.0, gt=0)
    atr_period: int = Field(14, ge=2, le=200)
    atr_multiple: float = Field(2.0, gt=0)
    extreme_tp_pct_q0: float = Field(10.0, gt=0, le=100)
    max_extreme_tp_count: int = Field(3, ge=0, le=20)
    minimum_position_pct_q0: float = Field(20.0, ge=0, le=100)

    @model_validator(mode="after")
    def entry_above_trigger(self) -> "StrategyParameters":
        if self.entry_stop_pct < self.breakout_trigger_pct:
            raise ValueError("entry_stop_pct must be >= breakout_trigger_pct")
        return self


class BacktestRequest(BaseModel):
    # Ignore legacy execution_timeframe fields saved by the former intraday
    # engine so old history entries can still be cloned safely.
    model_config = ConfigDict(extra="ignore")

    ticker: str = Field(min_length=1, max_length=24)
    strategy: StrategyName = StrategyName.ADVANCED
    start_date: date
    end_date: date
    initial_capital: float = Field(100_000, gt=0)
    position_size_pct: float = Field(100, gt=0, le=100)
    execution_model: Literal["daily_conservative"] = "daily_conservative"
    execution_policy: Literal["conservative", "ohlc_heuristic", "favorable"] = "conservative"
    market_data_provider: Literal["auto", "yahoo", "alternative", "stooq"] = "auto"
    commission_pct: float = Field(0.05, ge=0, le=10)
    slippage_pct: float = Field(0.02, ge=0, le=10)
    force_close_at_end: bool = True
    parameters: StrategyParameters = Field(default_factory=StrategyParameters)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9.\^=\-]{1,24}", normalized):
            raise ValueError("ticker contains unsupported characters")
        return normalized

    @model_validator(mode="after")
    def dates_valid(self) -> "BacktestRequest":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        if self.end_date - self.start_date > timedelta(days=365 * 20 + 5):
            raise ValueError("date range cannot exceed 20 years")
        return self


@dataclass
class AdvancedStrategyState:
    state: StrategyState = StrategyState.FLAT
    q0: int | None = None
    entry_timestamp: datetime | None = None
    entry_price: float | None = None
    entry_day: date | None = None
    entry_day_close: float | None = None
    entry_day_volume: float | None = None
    previous_day_volume: float | None = None
    current_qty: int = 0
    pending_next_open_exit_reason: str | None = None
    break_day: date | None = None
    break_day_low: float | None = None
    first_tp_triggered: bool = False
    bias_extreme_active: bool = False
    atr_extreme_active: bool = False
    extreme_tp_count: int = 0
    day2_validation_pending: bool = False
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    fees: float = 0.0

    def partial_tp_allowed(self, minimum_pct: float) -> bool:
        return bool(self.q0 and self.current_qty / self.q0 >= minimum_pct / 100)


@dataclass
class Execution:
    timestamp: datetime
    side: Literal["BUY", "SELL"]
    price: float
    quantity: int
    gross_value: float
    commission: float
    slippage: float
    position_remaining: int
    event_type: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class Event:
    timestamp: datetime
    daily_reference_ma: float | None
    event: str
    trigger_price: float | None
    current_price: float | None
    position_before: int
    position_after: int
    state_before: str
    state_after: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "timestamp": self.timestamp.isoformat(),
        }


class BacktestError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
