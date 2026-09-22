from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd


STANDARD_COLUMNS = ["open", "high", "low", "close", "volume"]


@dataclass
class MarketData:
    daily: pd.DataFrame
    provider: str
    warnings: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)


class DataProvider(ABC):
    @abstractmethod
    def get_daily(self, ticker: str, start: date, end: date) -> pd.DataFrame: ...

    def get_market_data(self, ticker: str, start: date, end: date) -> MarketData:
        return MarketData(
            daily=self.get_daily(ticker, start, end),
            provider=self.__class__.__name__,
            warnings=[],
            metadata={"requested_start": start.isoformat(), "requested_end": end.isoformat()},
        )

    def get_cached_market_data(self, ticker: str, start: date, end: date) -> MarketData | None:
        """Return a complete local-only result, or ``None`` when unavailable.

        The fallback coordinator calls this hook before any network operation.
        Providers that do not have a cache can keep the default implementation;
        this keeps the provider abstraction backwards compatible for custom
        integrations and the synthetic test provider.
        """
        return None

    def status_info(self, *, force: bool = False) -> dict[str, Any]:
        """Return a safe reachability summary for the provider.

        Concrete network providers may cache this result.  A deliberately small
        default makes status reporting safe for custom providers without
        requiring them to perform a probe.
        """
        return {"provider": self.__class__.__name__.lower(), "reachable": None}


def normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    out = frame.copy()
    out.columns = [str(col).lower().replace(" ", "_") for col in out.columns]
    if "adj_close" in out.columns and "close" not in out.columns:
        out["close"] = out["adj_close"]
    out = out[STANDARD_COLUMNS].apply(pd.to_numeric, errors="coerce").dropna(subset=["open", "high", "low", "close"])
    index = pd.DatetimeIndex(out.index)
    if index.tz is None:
        index = index.tz_localize("UTC")
    out.index = index
    out.index.name = "timestamp"
    return out.sort_index()


def validate_daily_ohlcv(frame: pd.DataFrame) -> tuple[bool, str | None]:
    """Validate the provider-neutral daily OHLCV contract.

    Providers normalize their own responses before this check.  We reject
    malformed or unsafe market data at the data boundary so the strategy engine
    never has to know which provider supplied the bars.
    """
    if frame is None or frame.empty:
        return False, "provider returned no daily bars"
    missing = [column for column in STANDARD_COLUMNS if column not in frame.columns]
    if missing:
        return False, f"missing daily columns: {', '.join(missing)}"
    try:
        index = pd.DatetimeIndex(frame.index)
    except Exception:
        return False, "daily timestamps are invalid"
    if index.tz is None:
        return False, "daily timestamps must be timezone-aware"
    if not index.is_monotonic_increasing:
        return False, "daily timestamps are not sorted"
    if index.duplicated().any() or pd.Series(index.date).duplicated().any():
        return False, "daily timestamps contain duplicate trading dates"
    values = frame[STANDARD_COLUMNS].apply(pd.to_numeric, errors="coerce")
    if values[STANDARD_COLUMNS[:4]].isna().any().any():
        return False, "daily OHLC contains non-numeric values"
    if values["volume"].isna().any():
        return False, "daily volume contains non-numeric values"
    if (values[STANDARD_COLUMNS[:4]] <= 0).any().any():
        return False, "daily prices must be greater than zero"
    if (values["volume"] < 0).any():
        return False, "daily volume cannot be negative"
    if (values["high"] < values[["open", "close", "low"]].max(axis=1)).any():
        return False, "daily high is below one of open/close/low"
    if (values["low"] > values[["open", "close", "high"]].min(axis=1)).any():
        return False, "daily low is above one of open/close/high"
    return True, None
