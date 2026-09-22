from __future__ import annotations

from datetime import date

import pandas as pd

from app.backtest.engine import DAILY_EXECUTION_WARNING, BacktestEngine
from app.backtest.models import BacktestRequest, StrategyParameters


def test_engine_runs_using_daily_ohlc_only():
    index = pd.date_range("2025-01-01", periods=12, freq="D", tz="UTC")
    daily = pd.DataFrame(
        {"open": 100.0, "high": 102.0, "low": 100.0, "close": 100.0, "volume": 1_000.0},
        index=index,
    )
    daily.loc[index[7], ["open", "high", "low", "close"]] = [97.0, 99.0, 96.0, 98.0]
    request = BacktestRequest(
        ticker="TEST",
        strategy="simple",
        start_date=date(2025, 1, 4),
        end_date=date(2025, 1, 12),
        commission_pct=0,
        slippage_pct=0,
        parameters=StrategyParameters(ma_period=2, atr_period=2, bias_lookback=2),
    )
    engine = BacktestEngine()
    result = engine.run(request, daily)
    assert result["data_coverage"]["execution_model"] == "daily_conservative"
    assert "intraday_bars_count" not in result["data_coverage"]
    assert result["warnings"][0] == DAILY_EXECUTION_WARNING
    assert any(item["event_type"] == "ENTRY" for item in result["executions"])
    assert result["positions"] and result["positions"][0]["final_exit_date"]
    position = result["positions"][0]
    assert position["position_id"] in engine.position_audits
    audit = engine.position_audits[position["position_id"]]
    assert audit["timeline"][0]["date"] == position["entry_date"][:10]
    assert audit["timeline"][-1]["date"] == position["final_exit_date"][:10]
    assert "timeline" not in result


def test_legacy_execution_timeframe_is_ignored():
    payload = BacktestRequest.model_validate({
        "ticker": "NVDA",
        "strategy": "simple",
        "start_date": "2021-01-01",
        "end_date": "2025-01-01",
        "execution_timeframe": "5m",
    })
    assert payload.execution_model == "daily_conservative"
    assert "execution_timeframe" not in payload.model_dump()
