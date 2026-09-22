from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.backtest.models import BacktestError
from app.data.base import DataProvider, MarketData
from app.data.cache import ParquetCache
from app.data.fallback import ProviderChain
from app.data.stooq import StooqDataProvider


def _frame(start: str = "2025-01-01", periods: int = 5, base: float = 100.0) -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "open": [base + n for n in range(periods)],
            "high": [base + n + 2 for n in range(periods)],
            "low": [base + n - 1 for n in range(periods)],
            "close": [base + n + 1 for n in range(periods)],
            "volume": [1000] * periods,
        },
        index=index,
    )


class StubProvider(DataProvider):
    def __init__(self, key: str, frame: pd.DataFrame | None = None, error: BacktestError | None = None):
        self.provider_key = key
        self.frame = frame
        self.error = error
        self.calls: list[str] = []
        self.cached = False
        self.reachable = error is None

    def get_daily(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        return self.get_market_data(ticker, start, end).daily

    def get_cached_market_data(self, ticker: str, start: date, end: date) -> MarketData | None:
        self.calls.append("cache")
        if not self.cached or self.frame is None:
            return None
        return MarketData(self.frame, self.provider_key, [f"cached {self.provider_key}"], {"data_source": "cache"})

    def get_market_data(self, ticker: str, start: date, end: date) -> MarketData:
        self.calls.append("network")
        if self.error is not None:
            raise self.error
        assert self.frame is not None
        return MarketData(self.frame, self.provider_key, [], {"data_source": self.provider_key})

    def offline_cooldown_active(self) -> bool:
        return False

    def status_info(self, *, force: bool = False) -> dict:
        return {"provider": self.provider_key, "reachable": self.reachable, "error_type": None if self.reachable else "PROVIDER_CONNECTION_ERROR"}


def _failure(code: str, message: str = "offline") -> BacktestError:
    return BacktestError(code, message, details={"provider_error_code": code})


def test_complete_cache_wins_without_network_or_fallback():
    yahoo = StubProvider("yahoo", _frame())
    yahoo.cached = True
    alternative = StubProvider("stooq", _frame(base=200))
    chain = ProviderChain(yahoo, alternative)

    result = chain.get_market_data("TEST", date(2025, 1, 1), date(2025, 1, 5))

    assert result.provider == "yahoo"
    assert yahoo.calls == ["cache"]
    assert alternative.calls == []
    assert result.metadata["provider_selection"] == "cache-first"


def test_yahoo_failure_falls_back_to_alternative_with_one_concise_warning():
    yahoo = StubProvider("yahoo", error=_failure("PROVIDER_CONNECTION_ERROR", "query1 and query2 blocked"))
    alternative = StubProvider("stooq", _frame(base=200))
    chain = ProviderChain(yahoo, alternative)

    result = chain.get_market_data("TEST", date(2025, 1, 1), date(2025, 1, 5))

    assert result.provider == "stooq"
    assert result.warnings[0] == "Yahoo currently unavailable. Automatically using Stooq daily data."
    assert [item["provider"] for item in result.metadata["provider_attempts"] if item.get("source") == "network"] == ["yahoo", "alternative"]


def test_known_yahoo_outage_is_skipped_during_cooldown():
    yahoo = StubProvider("yahoo", error=_failure("PROVIDER_CONNECTION_ERROR"))
    yahoo.offline_cooldown_active = lambda: True  # type: ignore[method-assign]
    alternative = StubProvider("stooq", _frame(base=200))
    chain = ProviderChain(yahoo, alternative)

    result = chain.get_market_data("TEST", date(2025, 1, 1), date(2025, 1, 5))

    assert result.provider == "stooq"
    assert yahoo.calls == ["cache"]
    assert any(item.get("skipped") == "offline_cooldown" for item in result.metadata["provider_attempts"])


def test_online_yahoo_is_preferred_over_alternative():
    yahoo = StubProvider("yahoo", _frame())
    alternative = StubProvider("stooq", _frame(base=200))
    chain = ProviderChain(yahoo, alternative)

    result = chain.get_market_data("TEST", date(2025, 1, 1), date(2025, 1, 5))

    assert result.provider == "yahoo"
    assert yahoo.calls == ["cache", "network"]
    assert alternative.calls == ["cache"]


def test_all_providers_offline_returns_machine_readable_concise_error():
    yahoo = StubProvider("yahoo", error=_failure("PROVIDER_CONNECTION_ERROR", "internal stack path must not leak"))
    alternative = StubProvider("stooq", error=_failure("PROVIDER_TIMEOUT", "timeout"))
    chain = ProviderChain(yahoo, alternative)

    with pytest.raises(BacktestError) as captured:
        chain.get_market_data("TEST", date(2025, 1, 1), date(2025, 1, 5))

    exc = captured.value
    assert exc.code == "MARKET_DATA_PROVIDERS_UNAVAILABLE"
    assert exc.message == "Market data providers are currently unavailable."
    assert set(exc.details["provider_errors"]) == {"yahoo", "alternative"}
    assert "traceback (most recent call last)" not in str(exc.details).lower()


def test_provider_cache_namespaces_are_isolated(tmp_path):
    yahoo_cache = ParquetCache(tmp_path / "yahoo")
    stooq_cache = ParquetCache(tmp_path / "stooq")
    yahoo_cache.write("TEST", "1d", date(2025, 1, 1), date(2025, 1, 5), _frame(), metadata={"provider": "yahoo", "adjustment_mode": "adjusted_for_splits"})
    stooq_cache.write("TEST", "1d", date(2025, 1, 1), date(2025, 1, 5), _frame(base=300), metadata={"provider": "stooq", "adjustment_mode": "provider_native_adjusted_for_splits"})

    assert yahoo_cache.read_metadata(yahoo_cache.path("TEST", "1d", date(2025, 1, 1), date(2025, 1, 5)))["provider"] == "yahoo"
    assert stooq_cache.read_metadata(stooq_cache.path("TEST", "1d", date(2025, 1, 1), date(2025, 1, 5)))["provider"] == "stooq"
    assert yahoo_cache.read_coverage("TEST", "1d", date(2025, 1, 1), date(2025, 1, 5)).frame["open"].iloc[0] == 100
    assert stooq_cache.read_coverage("TEST", "1d", date(2025, 1, 1), date(2025, 1, 5)).frame["open"].iloc[0] == 300


def test_stooq_csv_parser_normalizes_timezone_and_ohlcv():
    payload = b"Date,Open,High,Low,Close,Volume\n2025-01-02,10,12,9,11,100\n2025-01-03,11,13,10,12,200\n"
    frame = StooqDataProvider._csv_to_frame(payload)
    assert len(frame) == 2
    assert frame.index.tz is not None
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
