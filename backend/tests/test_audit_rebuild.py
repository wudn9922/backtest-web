from __future__ import annotations

from copy import deepcopy
from datetime import date

import pandas as pd
import pytest

from app.backtest.audit_rebuild import AuditRebuildError, rebuild_position_audits
from app.backtest.engine import BacktestEngine
from app.backtest.models import BacktestRequest, StrategyParameters
from app.data.base import DataProvider, MarketData
from app.db.repository import BacktestRepository


class CacheOnlyProvider(DataProvider):
    """A provider that proves audit rebuild never falls through to network fetches."""

    def __init__(self, daily: pd.DataFrame):
        self.daily = daily
        self.cached_calls = 0

    def get_daily(self, ticker: str, start: date, end: date) -> pd.DataFrame:  # pragma: no cover - must never run
        raise AssertionError("audit rebuild must not request provider data over the network")

    def get_cached_market_data(self, ticker: str, start: date, end: date) -> MarketData | None:
        self.cached_calls += 1
        return MarketData(
            daily=self.daily.copy(),
            provider="synthetic_cache",
            warnings=[],
            metadata={"cache_last_updated": "2025-01-01T00:00:00+00:00"},
        )


def _daily_with_completed_trade() -> tuple[BacktestRequest, pd.DataFrame]:
    index = pd.bdate_range("2024-01-02", periods=70, tz="UTC")
    daily = pd.DataFrame(
        {"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1_000_000.0},
        index=index,
    )
    # On this requested day's bar, MA is 100 and the upper entry level is
    # 101.5.  The next day's low takes the normal Simple MA exit, giving the
    # fixture a real execution/PnL history to protect.
    entry_timestamp = index[45]
    exit_timestamp = index[46]
    daily.loc[entry_timestamp, ["high", "low", "close"]] = [102.0, 99.0, 101.0]
    daily.loc[exit_timestamp, ["high", "low", "close"]] = [101.0, 97.0, 98.0]
    request = BacktestRequest(
        ticker="NVDA",
        strategy="simple",
        start_date=entry_timestamp.date(),
        end_date=exit_timestamp.date(),
        parameters=StrategyParameters(ma_period=2, atr_period=2, bias_lookback=2),
    )
    return request, daily


def _stored_backtest(tmp_path):
    request, daily = _daily_with_completed_trade()
    engine = BacktestEngine()
    result = engine.run(request, daily, provider="synthetic_cache")
    assert len(result["executions"]) == 2
    assert len(result["positions"]) == 1
    repository = BacktestRepository(tmp_path / "backtests.sqlite3")
    identifier = repository.create_pending(request.model_dump(mode="json"))
    repository.complete(identifier, result, engine.position_audits)
    return repository, identifier, daily


def test_cache_only_audit_rebuild_replaces_audits_without_changing_result(tmp_path):
    repository, identifier, daily = _stored_backtest(tmp_path)
    before_result = deepcopy(repository.get(identifier)["result"])
    provider = CacheOnlyProvider(daily)

    report = rebuild_position_audits(
        backtest_id=identifier,
        repository=repository,
        data_provider=provider,
    )

    assert provider.cached_calls == 1
    assert report.audit_count == 1
    assert repository.get(identifier)["result"] == before_result
    stored_audit = repository.get_position_audit(identifier, "position-1")
    assert stored_audit is not None
    assert stored_audit["backtest_id"] == identifier
    assert stored_audit["position"]["net_pnl"] == before_result["positions"][0]["net_pnl"]


def test_audit_rebuild_refuses_on_result_difference_without_replacing_old_audits(tmp_path):
    repository, identifier, daily = _stored_backtest(tmp_path)
    before_result = deepcopy(repository.get(identifier)["result"])
    before_audit = deepcopy(repository.get_position_audit(identifier, "position-1"))
    changed = daily.copy()
    # The entry day no longer reaches the 101.5 upper entry level, so the
    # safety comparison must reject the replay before writing any audit rows.
    changed.loc[changed.index[45], "high"] = 101.4

    with pytest.raises(AuditRebuildError, match="cached replay differs"):
        rebuild_position_audits(
            backtest_id=identifier,
            repository=repository,
            data_provider=CacheOnlyProvider(changed),
        )

    assert repository.get(identifier)["result"] == before_result
    assert repository.get_position_audit(identifier, "position-1") == before_audit
