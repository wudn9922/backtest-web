from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

from app.backtest.models import BacktestRequest


RankingMetric = Literal[
    "total_return", "cagr", "sharpe_ratio", "sortino_ratio",
    "calmar_ratio", "max_drawdown", "net_pnl",
]
OptimizationMode = Literal["single", "rolling_6m"]
SelectionMode = Literal["PERFORMANCE", "STRUCTURE_V1"]


class RollingOptimizationConfig(BaseModel):
    """Frozen first-version rolling contract.

    The six-month train/test length is intentionally not configurable.  The
    only comparison input is one user-selected fixed MA reference.
    """

    fixed_ma_period: int = Field(20, ge=2, le=500)
    calendar_months: Literal[6] = 6
    independent_test_segments: Literal[True] = True


class TrainTestConfig(BaseModel):
    enabled: bool = False
    train_start: date | None = None
    train_end: date | None = None
    test_start: date | None = None
    test_end: date | None = None

    @model_validator(mode="after")
    def validate_ranges(self) -> "TrainTestConfig":
        if not self.enabled:
            return self
        if None in (self.train_start, self.train_end, self.test_start, self.test_end):
            raise ValueError("train and test dates are required when out-of-sample validation is enabled")
        assert self.train_start and self.train_end and self.test_start and self.test_end
        if self.train_end <= self.train_start:
            raise ValueError("train_end must be after train_start")
        if self.test_end <= self.test_start:
            raise ValueError("test_end must be after test_start")
        if self.test_start <= self.train_end:
            raise ValueError("test period must begin after the train period ends")
        return self


class MAOptimizationRequest(BaseModel):
    backtest: BacktestRequest
    mode: OptimizationMode = "single"
    # PERFORMANCE is the historical/default path.  Keeping this default is
    # important for old saved requests and callers that predate Structure V1.
    selection_mode: SelectionMode = "PERFORMANCE"
    ma_min: int = Field(5, ge=2, le=500)
    ma_max: int = Field(200, ge=2, le=500)
    ma_step: int = Field(5, ge=1, le=499)
    ranking_metric: RankingMetric = "sharpe_ratio"
    train_test: TrainTestConfig = Field(default_factory=TrainTestConfig)
    rolling: RollingOptimizationConfig = Field(default_factory=RollingOptimizationConfig)

    @computed_field
    @property
    def combinations(self) -> int:
        return ((self.ma_max - self.ma_min) // self.ma_step) + 1 if self.ma_max >= self.ma_min else 0

    @model_validator(mode="after")
    def validate_search(self) -> "MAOptimizationRequest":
        if self.ma_max < self.ma_min:
            raise ValueError("ma_max must be greater than or equal to ma_min")
        if self.combinations > 500:
            raise ValueError("MA optimization is limited to 500 backtests; reduce the range or increase the step")
        if self.selection_mode == "STRUCTURE_V1" and self.mode != "rolling_6m":
            raise ValueError("MA_STRUCTURE_V1 is available only for rolling_6m optimization")
        return self

    def periods(self) -> list[int]:
        return list(range(self.ma_min, self.ma_max + 1, self.ma_step))
