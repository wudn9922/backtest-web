from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.backtest.models import BacktestError
from app.data.yahoo import YahooDataProvider, YAHOO_HOSTS


def _frame(start: str, periods: int, base: float = 100.0) -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "open": [base + n for n in range(periods)],
            "high": [base + n + 1 for n in range(periods)],
            "low": [base + n - 1 for n in range(periods)],
            "close": [base + n + 0.5 for n in range(periods)],
            "volume": [1000] * periods,
        },
        index=index,
    )


def test_complete_cache_is_used_without_remote_call(tmp_path, monkeypatch):
    provider = YahooDataProvider(tmp_path)
    cached = _frame("2025-01-01", 15)
    provider.cache.write("TEST", "1d", date(2025, 1, 1), date(2025, 1, 15), cached)

    def fail_remote(*args, **kwargs):
        raise AssertionError("complete cache must not call Yahoo")

    monkeypatch.setattr(provider, "_download_remote", fail_remote)
    result = provider.get_market_data("TEST", date(2025, 1, 1), date(2025, 1, 15))
    assert len(result.daily) == 15
    assert result.metadata["data_source"] == "cache"
    assert result.metadata["cache_complete"] is True
    assert result.warnings


def test_remote_falls_back_from_query1_to_query2(tmp_path, monkeypatch):
    provider = YahooDataProvider(tmp_path)
    provider.max_retries = 0
    calls: list[str] = []

    def fake_request(host, ticker, start, end):
        calls.append(host)
        if host == YAHOO_HOSTS[0]:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"]), "connection refused", "connection", None
        return _frame("2025-01-01", 3), None, "ok", 200

    monkeypatch.setattr(provider, "_run_request", fake_request)
    result = provider.get_market_data("TEST", date(2025, 1, 1), date(2025, 1, 3))
    assert calls == list(YAHOO_HOSTS)
    assert len(result.daily) == 3
    assert result.metadata["data_source"] == "yahoo"


def test_remote_retries_are_finite_with_exponential_backoff(tmp_path, monkeypatch):
    provider = YahooDataProvider(tmp_path)
    provider.max_retries = 2
    provider.retry_backoff_seconds = 1
    calls = []
    sleeps = []

    def fail_request(host, ticker, start, end):
        calls.append(host)
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"]), "timeout", "timeout", None

    monkeypatch.setattr(provider, "_run_request", fail_request)
    monkeypatch.setattr("app.data.yahoo.time.sleep", lambda seconds: sleeps.append(seconds))
    frame, failure = provider._download_remote("TEST", date(2025, 1, 1), date(2025, 1, 2))
    assert frame.empty
    assert failure is not None and failure.code == "PROVIDER_TIMEOUT"
    assert len(calls) == 2 * 3
    assert sleeps == [1, 2]


def test_partial_cache_fetches_only_missing_range(tmp_path, monkeypatch):
    provider = YahooDataProvider(tmp_path)
    provider.cache.write("TEST", "1d", date(2025, 1, 10), date(2025, 1, 20), _frame("2025-01-10", 11))
    requested = (date(2025, 1, 1), date(2025, 1, 20))
    missing_calls = []

    def fake_remote(ticker, start, end):
        missing_calls.append((start, end))
        assert (start, end) == (date(2025, 1, 1), date(2025, 1, 9))
        return _frame("2025-01-01", 9, 80), None

    monkeypatch.setattr(provider, "_download_remote", fake_remote)
    result = provider.get_market_data("TEST", *requested)
    assert missing_calls == [(date(2025, 1, 1), date(2025, 1, 9))]
    assert len(result.daily) == 20
    assert result.metadata["data_source"] == "yahoo+cache"


def test_incomplete_cache_does_not_run_a_truncated_backtest(tmp_path, monkeypatch):
    provider = YahooDataProvider(tmp_path)
    provider.cache.write("TEST", "1d", date(2025, 1, 10), date(2025, 1, 20), _frame("2025-01-10", 11))
    provider.max_retries = 0

    def fail_remote(*args):
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"]), type("Failure", (), {
            "code": "PROVIDER_CONNECTION_ERROR",
            "message": "query1: connection refused; query2: connection refused",
            "hosts_attempted": list(YAHOO_HOSTS),
        })()

    monkeypatch.setattr(provider, "_download_remote", fail_remote)
    with pytest.raises(BacktestError) as captured:
        provider.get_daily("TEST", date(2025, 1, 1), date(2025, 1, 20))
    assert captured.value.code == "CACHE_INCOMPLETE"
    assert "Cached coverage" in captured.value.message
    assert captured.value.details["cache_coverage"]["start"] == "2025-01-10"


def test_empty_remote_result_is_classified_as_no_data(tmp_path, monkeypatch):
    provider = YahooDataProvider(tmp_path)
    provider.max_retries = 3

    def no_data(*args):
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"]), "symbol not found", "no_data", 200

    monkeypatch.setattr(provider, "_run_request", no_data)
    with pytest.raises(BacktestError) as captured:
        provider.get_daily("NOTREAL", date(2025, 1, 1), date(2025, 1, 2))
    assert captured.value.code == "NO_DATA"


def test_status_shape_is_safe_and_reports_cache(tmp_path, monkeypatch):
    provider = YahooDataProvider(tmp_path)
    provider.cache.write("TEST", "1d", date(2025, 1, 1), date(2025, 1, 2), _frame("2025-01-01", 2))
    monkeypatch.setattr(provider, "_probe_host", lambda host: host == YAHOO_HOSTS[1])
    status = provider.status()
    assert status == {
        "provider": "yahoo",
        "query1_reachable": False,
        "query2_reachable": True,
        "cache_available": True,
        "status": "degraded",
    }
    assert not any(secret in str(status).lower() for secret in ["password", "token", "cookie"])


def test_status_endpoint_returns_provider_reachability_shape(monkeypatch):
    from app.main import app

    with TestClient(app) as client:
        monkeypatch.setattr(app.state.provider.yahoo, "_probe_host", lambda host: host == YAHOO_HOSTS[0])
        monkeypatch.setattr(app.state.provider.alternative, "_probe", lambda: (False, "PROVIDER_CONNECTION_ERROR"))
        response = client.get("/api/data-provider/status")
    assert response.status_code == 200
    body = response.json()
    assert body["providers"]["yahoo"]["reachable"] is True
    assert body["providers"]["alternative"]["reachable"] is False
    assert body["status"] == "degraded"
    assert body["preferred_provider"] == "yahoo"
    assert set(body) == {"status", "providers", "preferred_provider", "cache_available"}
