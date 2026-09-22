from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.backtest.models import BacktestError
from app.data.yahoo import YahooDataProvider, safe_yahoo_error


EMPTY = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def test_empty_daily_download_has_daily_specific_error(tmp_path):
    provider = YahooDataProvider(tmp_path)
    provider._download = lambda *args: (EMPTY, "safe upstream daily message")
    with pytest.raises(BacktestError) as captured:
        provider.get_daily("NVDA", date(2021, 1, 1), date(2026, 1, 1))
    assert captured.value.code == "YAHOO_DAILY_DATA_UNAVAILABLE"
    assert captured.value.details == {"data_kind": "daily", "yahoo_error": "safe upstream daily message"}


def test_safe_yahoo_error_removes_urls_and_is_bounded():
    message = safe_yahoo_error("failed at https://query.example.test/private " + "x" * 800)
    assert "https://" not in message
    assert len(message) <= 500
