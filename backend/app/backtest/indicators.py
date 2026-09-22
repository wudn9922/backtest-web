from __future__ import annotations

import numpy as np
import pandas as pd


def moving_average(close: pd.Series, period: int, ma_type: str) -> pd.Series:
    if ma_type == "ema":
        return close.ewm(span=period, adjust=False, min_periods=period).mean()
    return close.rolling(period, min_periods=period).mean()


def wilder_atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def add_indicators(frame: pd.DataFrame, *, ma_type: str, ma_period: int, atr_period: int, bias_lookback: int) -> pd.DataFrame:
    """Add indicators plus explicit previous-completed-day references."""
    out = frame.sort_index().copy()
    out["ma"] = moving_average(out["close"], ma_period, ma_type)
    out["reference_ma"] = out["ma"].shift(1)
    out["atr"] = wilder_atr(out, atr_period)
    out["reference_atr"] = out["atr"].shift(1)
    out["daily_bias"] = (out["close"] - out["reference_ma"]) / out["reference_ma"]
    # Shift first: day t sigma contains completed days only (t-lookback ... t-1).
    out["reference_bias_sigma"] = out["daily_bias"].shift(1).rolling(
        bias_lookback, min_periods=bias_lookback
    ).std(ddof=0)
    return out.replace([np.inf, -np.inf], np.nan)
