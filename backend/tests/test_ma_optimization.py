from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.backtest.engine import BacktestEngine
from app.backtest.data_preparation import prepare_daily_market_data
from app.backtest.models import BacktestError, BacktestRequest
from app.data.base import MarketData
from app.data.cache import ParquetCache
from app.data.fallback import ProviderChain
from app.db.repository import BacktestRepository
from app.jobs.repository import JobRepository
from app.optimization.models import MAOptimizationRequest
from app.optimization.runner import run_ma_optimization
from app.optimization.windows import build_rolling_six_month_windows
from app.jobs.service import JobService
from app.main import app


def daily_frame() -> pd.DataFrame:
    index = pd.bdate_range("2022-01-03", periods=520, tz="UTC")
    close = 80 + np.linspace(0, 70, len(index)) + np.sin(np.arange(len(index)) / 7) * 3
    return pd.DataFrame({
        "open": close * 0.997, "high": close * 1.025, "low": close * 0.975,
        "close": close, "volume": 1_000_000 + (np.arange(len(index)) % 13) * 40_000,
    }, index=index)


class Provider:
    def __init__(self, frame: pd.DataFrame): self.frame = frame; self.calls = []
    def get_market_data(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        start, end = args[1], args[2]
        sliced = self.frame[[(start <= timestamp.date() <= end) for timestamp in self.frame.index]].copy()
        return MarketData(sliced, "synthetic", [])


def request(ma: int = 20, strategy: str = "simple") -> BacktestRequest:
    return BacktestRequest.model_validate({
        "ticker": "NVDA", "strategy": strategy, "start_date": "2023-03-01", "end_date": "2023-12-29",
        "initial_capital": 100000, "position_size_pct": 100, "execution_policy": "conservative",
        "commission_pct": 0.05, "slippage_pct": 0.02,
        "parameters": {"ma_period": ma, "breakout_trigger_pct": 1, "entry_stop_pct": 1.5},
    })


@pytest.mark.parametrize("ma_period", [20, 50])
def test_optimizer_result_is_identical_to_manual_canonical_backtest(tmp_path: Path, ma_period: int):
    frame = daily_frame(); jobs = JobRepository(tmp_path / "jobs.sqlite3"); backtests = BacktestRepository(tmp_path / "backtests.sqlite3")
    spec = MAOptimizationRequest(backtest=request(ma_period), ma_min=ma_period, ma_max=ma_period, ma_step=1)
    job, _ = jobs.create("MA_PERIOD_OPTIMIZATION", spec.model_dump(mode="json"), 1); jobs.mark_running(job["id"])
    result = run_ma_optimization(job["id"], spec.model_dump(mode="json"), jobs, backtests, Provider(frame))
    assert result is not None
    stored = backtests.get(result["results"][0]["backtest_id"])
    manual_request = request(ma_period)
    manual_market = prepare_daily_market_data(manual_request, Provider(frame))
    manual_engine = BacktestEngine(); manual = manual_engine.run(manual_request, manual_market.daily, "synthetic")
    assert stored and stored["result"]
    assert stored["result"]["executions"] == manual["executions"]
    assert stored["result"]["positions"] == manual["positions"]
    assert stored["result"]["events"] == manual["events"]
    assert stored["result"]["equity_curve"] == manual["equity_curve"]
    assert stored["result"]["summary"] == manual["summary"]


def test_optimizer_changes_only_ma_period_and_reuses_fingerprint_cache(tmp_path: Path):
    frame = daily_frame(); jobs = JobRepository(tmp_path / "jobs.sqlite3"); backtests = BacktestRepository(tmp_path / "backtests.sqlite3")
    base = request(20, "advanced")
    spec = MAOptimizationRequest(backtest=base, ma_min=20, ma_max=30, ma_step=10)
    payload = spec.model_dump(mode="json")
    first, _ = jobs.create("MA_PERIOD_OPTIMIZATION", payload, 2); jobs.mark_running(first["id"])
    result = run_ma_optimization(first["id"], payload, jobs, backtests, Provider(frame))
    assert result and [row["ma_period"] for row in result["results"]] == [20, 30]
    records = [backtests.get(row["backtest_id"]) for row in result["results"]]
    assert all(record for record in records)
    assert records[0]["parameters"]["parameters"]["atr_period"] == records[1]["parameters"]["parameters"]["atr_period"] == 14
    assert records[0]["parameters"]["parameters"]["ma_period"] == 20
    assert records[1]["parameters"]["parameters"]["ma_period"] == 30
    assert records[0]["result"]["daily_data"] != records[1]["result"]["daily_data"]

    second, _ = jobs.create("MA_PERIOD_OPTIMIZATION", {**payload, "ranking_metric": "cagr"}, 2); jobs.mark_running(second["id"])
    reused = run_ma_optimization(second["id"], {**payload, "ranking_metric": "cagr"}, jobs, backtests, Provider(frame))
    assert reused and all(row["cache_reused"] for row in reused["results"])


def test_train_best_selection_never_uses_test_results(tmp_path: Path, monkeypatch):
    frame = daily_frame(); jobs = JobRepository(tmp_path / "jobs.sqlite3"); backtests = BacktestRepository(tmp_path / "backtests.sqlite3")
    base = request(20)
    payload = {
        "backtest": base.model_dump(mode="json"), "ma_min": 20, "ma_max": 30, "ma_step": 10,
        "ranking_metric": "sharpe_ratio",
        "train_test": {"enabled": True, "train_start": "2022-03-01", "train_end": "2023-01-31", "test_start": "2023-02-01", "test_end": "2023-12-29"},
    }
    calls: list[tuple[int, date]] = []
    def fake_run(req, *_args):
        calls.append((req.parameters.ma_period, req.start_date))
        sharpe = {20: 2.0, 30: 1.0}[req.parameters.ma_period] if req.start_date.year == 2022 else -99.0
        return {"ma_period": req.parameters.ma_period, "backtest_id": f"id-{len(calls)}", "sharpe_ratio": sharpe}
    monkeypatch.setattr("app.optimization.runner._run_canonical", fake_run)
    job, _ = jobs.create("MA_PERIOD_OPTIMIZATION", payload, 3); jobs.mark_running(job["id"])
    result = run_ma_optimization(job["id"], payload, jobs, backtests, Provider(frame))
    assert result and result["best"]["ma_period"] == 20
    assert result["train_test"]["selection_source"] == "TRAIN_ONLY"
    assert calls == [(20, date(2022, 3, 1)), (30, date(2022, 3, 1)), (20, date(2023, 2, 1))]


def test_search_limit_and_date_boundaries_are_validated():
    widest = MAOptimizationRequest(backtest=request(), ma_min=2, ma_max=500, ma_step=1)
    assert widest.combinations == 499
    with pytest.raises(ValueError, match="less than or equal to 500"):
        MAOptimizationRequest(backtest=request(), ma_min=2, ma_max=501, ma_step=1)
    with pytest.raises(ValueError, match="after the train"):
        MAOptimizationRequest.model_validate({
            "backtest": request().model_dump(mode="json"), "ma_min": 20, "ma_max": 20, "ma_step": 1,
            "train_test": {"enabled": True, "train_start": "2022-01-01", "train_end": "2023-01-01", "test_start": "2022-12-01", "test_end": "2023-12-01"},
        })


def test_cancel_is_durable_and_prevents_recovery(tmp_path: Path):
    jobs = JobRepository(tmp_path / "jobs.sqlite3")
    job, _ = jobs.create("MA_PERIOD_OPTIMIZATION", {}, 10)
    jobs.mark_running(job["id"])
    assert jobs.cancel(job["id"]) is True
    assert jobs.get(job["id"])["status"] == "CANCELLED"
    assert jobs.recover_interrupted() == []


def test_recovered_job_resumes_only_unfinished_periods_and_clears_stale_failure(tmp_path: Path, monkeypatch):
    frame = daily_frame(); jobs = JobRepository(tmp_path / "jobs.sqlite3"); backtests = BacktestRepository(tmp_path / "backtests.sqlite3")
    spec = MAOptimizationRequest(backtest=request(), ma_min=20, ma_max=30, ma_step=10)
    payload = spec.model_dump(mode="json")
    job, _ = jobs.create("MA_PERIOD_OPTIMIZATION", payload, 2); jobs.mark_running(job["id"])
    completed = {"ma_period": 20, "backtest_id": "saved-20", "sharpe_ratio": 1.0, "total_return": 5.0}
    jobs.progress(
        job["id"], 1, 2, "MA 30", "checkpoint",
        errors=[{"ma_period": 30, "code": "INTERRUPTED", "message": "old failure"}],
        result={"results": [completed]},
    )
    assert jobs.recover_interrupted() == [job["id"]]
    jobs.mark_running(job["id"])
    calls: list[int] = []

    def fake_run(req, *_args):
        calls.append(req.parameters.ma_period)
        return {"ma_period": 30, "backtest_id": "saved-30", "sharpe_ratio": 2.0, "total_return": 7.0}

    monkeypatch.setattr("app.optimization.runner._run_canonical", fake_run)
    result = run_ma_optimization(job["id"], payload, jobs, backtests, Provider(frame))
    assert result and calls == [30]
    assert [row["ma_period"] for row in result["results"]] == [20, 30]
    assert jobs.get(job["id"])["errors"] == []


def test_data_preparation_failure_is_stage_specific_and_runs_no_ma(tmp_path: Path, monkeypatch):
    class OfflineProvider:
        def get_market_data(self, *_args, **_kwargs):
            raise BacktestError("MARKET_DATA_PROVIDERS_UNAVAILABLE", "Market data providers are currently unavailable.")

    jobs = JobRepository(tmp_path / "jobs.sqlite3"); backtests = BacktestRepository(tmp_path / "backtests.sqlite3")
    spec = MAOptimizationRequest(backtest=request(20, "advanced"), ma_min=5, ma_max=200, ma_step=5)
    payload = spec.model_dump(mode="json")
    job, _ = jobs.create("MA_PERIOD_OPTIMIZATION", payload, 40); jobs.mark_running(job["id"])
    called = False
    def forbidden(*_args):
        nonlocal called; called = True
    monkeypatch.setattr("app.optimization.runner._run_canonical", forbidden)
    assert run_ma_optimization(job["id"], payload, jobs, backtests, OfflineProvider()) is None
    saved = jobs.get(job["id"])
    assert called is False
    assert saved["status"] == "FAILED" and saved["progress_current"] == 0
    assert saved["errors"][0]["stage"] == "DATA_PREPARATION"
    assert saved["result"]["failure_stage"] == "DATA_PREPARATION"


def test_shared_preparation_uses_only_validated_same_provider_long_cache_when_upstream_is_offline(tmp_path: Path):
    class OfflineCachedProvider:
        def __init__(self, key: str, adjustment: str):
            self.provider_key = key; self.adjustment_mode = adjustment; self.display_name = key
            self.cache = ParquetCache(tmp_path / "cache")
        def get_cached_market_data(self, *_args): return None
        def get_market_data(self, *_args): raise BacktestError("PROVIDER_CONNECTION_ERROR", "offline")
        def offline_cooldown_active(self): return True

    yahoo = OfflineCachedProvider("yahoo", "adjusted_for_splits")
    alternative = OfflineCachedProvider("stooq", "provider_native_adjusted_for_splits")
    long_cache = ParquetCache(tmp_path / "research-cache" / "yahoo")
    frame = daily_frame()
    long_cache.write("NVDA", "1d", date(2022, 1, 3), date(2023, 12, 29), frame, {
        "provider": "yahoo", "adjustment_mode": "adjusted_for_splits",
    })
    req = request(200, "advanced")
    market = prepare_daily_market_data(req, ProviderChain(yahoo, alternative), ma_period=200)
    assert market.provider == "yahoo" and len(market.daily) >= 500
    assert market.metadata["data_source"] == "validated_research_cache"
    assert market.metadata["warmup_fallback"] is False


def test_insufficient_one_period_is_skipped_and_later_period_continues(tmp_path: Path, monkeypatch):
    frame = daily_frame(); jobs = JobRepository(tmp_path / "jobs.sqlite3"); backtests = BacktestRepository(tmp_path / "backtests.sqlite3")
    spec = MAOptimizationRequest(backtest=request(), ma_min=20, ma_max=30, ma_step=10)
    payload = spec.model_dump(mode="json")
    job, _ = jobs.create("MA_PERIOD_OPTIMIZATION", payload, 2); jobs.mark_running(job["id"])
    calls: list[int] = []
    def fake_run(req, *_args):
        calls.append(req.parameters.ma_period)
        if req.parameters.ma_period == 20:
            raise BacktestError("NOT_ENOUGH_MA_LOOKBACK", "not enough")
        return {"ma_period": 30, "backtest_id": "saved-30", "sharpe_ratio": 1.0, "total_return": 2.0}
    monkeypatch.setattr("app.optimization.runner._run_canonical", fake_run)
    assert run_ma_optimization(job["id"], payload, jobs, backtests, Provider(frame)) is None
    saved = jobs.get(job["id"])
    assert calls == [20, 30]
    assert saved["result"]["results"][0]["ma_period"] == 30
    assert saved["result"]["skipped"] == [{"ma_period": 20, "code": "NOT_ENOUGH_MA_LOOKBACK", "message": "此均線週期的已完成歷史資料不足。"}]
    assert saved["status"] == "PARTIAL_SUCCESS"


@pytest.mark.parametrize("ma_period", [20, 50, 100, 200])
def test_short_advanced_evaluation_uses_real_pre_start_bars_and_matches_manual(tmp_path: Path, ma_period: int):
    index = pd.bdate_range("2023-01-02", "2026-09-01", tz="UTC")
    close = 80 + np.linspace(0, 90, len(index)) + np.sin(np.arange(len(index)) / 9) * 4
    frame = pd.DataFrame({
        "open": close * .997, "high": close * 1.025, "low": close * .975,
        "close": close, "volume": 1_000_000 + (np.arange(len(index)) % 17) * 30_000,
    }, index=index)
    req = request(ma_period, "advanced").model_copy(update={"start_date": date(2025, 12, 1), "end_date": date(2026, 9, 1)})
    spec = MAOptimizationRequest(backtest=req, ma_min=ma_period, ma_max=ma_period, ma_step=1)
    payload = spec.model_dump(mode="json"); provider = Provider(frame)
    jobs = JobRepository(tmp_path / f"jobs-{ma_period}.sqlite3"); backtests = BacktestRepository(tmp_path / f"backtests-{ma_period}.sqlite3")
    job, _ = jobs.create("MA_PERIOD_OPTIMIZATION", payload, 1); jobs.mark_running(job["id"])
    result = run_ma_optimization(job["id"], payload, jobs, backtests, provider)
    assert result is not None
    requested_start = provider.calls[0][0][1]
    assert requested_start < req.start_date
    stored = backtests.get(result["results"][0]["backtest_id"])["result"]
    manual_market = prepare_daily_market_data(req, Provider(frame))
    manual_engine = BacktestEngine(); manual = manual_engine.run(req, manual_market.daily, "synthetic")
    for key in ("executions", "positions", "events", "equity_curve", "summary"):
        assert stored[key] == manual[key]


def test_optimization_api_creates_lists_and_cancels_durable_job(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api-backtests.sqlite3'}")
    monkeypatch.setattr(JobService, "start", lambda self: None)
    monkeypatch.setattr(JobService, "stop", lambda self: None)
    payload = {
        "backtest": request().model_dump(mode="json"), "ma_min": 20, "ma_max": 30,
        "ma_step": 10, "ranking_metric": "sharpe_ratio", "train_test": {"enabled": False},
    }
    with TestClient(app) as client:
        created = client.post("/api/optimizations", json=payload)
        assert created.status_code == 202
        identifier = created.json()["id"]
        listed = client.get("/api/optimizations").json()
        assert listed[0]["id"] == identifier and listed[0]["progress_total"] == 2
        cancelled = client.post(f"/api/optimizations/{identifier}/cancel")
        assert cancelled.status_code == 202 and cancelled.json()["status"] == "CANCELLED"
        retried = client.post(f"/api/optimizations/{identifier}/retry")
        assert retried.status_code == 202 and retried.json()["id"] != identifier


def rolling_payload(*, end: str = "2023-05-31", fixed_ma: int = 50) -> dict:
    base = request(20, "simple").model_copy(update={"start_date": date(2022, 6, 1), "end_date": date.fromisoformat(end)})
    return {
        "mode": "rolling_6m", "backtest": base.model_dump(mode="json"),
        "ma_min": 20, "ma_max": 20, "ma_step": 1, "ranking_metric": "sharpe_ratio",
        "rolling": {"fixed_ma_period": fixed_ma, "calendar_months": 6, "independent_test_segments": True},
    }


def test_rolling_train_row_and_test_are_canonical_backtests(tmp_path: Path):
    frame = daily_frame(); jobs = JobRepository(tmp_path / "jobs.sqlite3"); backtests = BacktestRepository(tmp_path / "backtests.sqlite3")
    payload = rolling_payload(fixed_ma=20); provider = Provider(frame)
    job, _ = jobs.create("MA_PERIOD_OPTIMIZATION", payload, 3); jobs.mark_running(job["id"])
    result = run_ma_optimization(job["id"], payload, jobs, backtests, provider)
    assert result and result["complete_windows"] == 1
    window = result["rolling_windows"][0]
    train_request = BacktestRequest.model_validate(payload["backtest"]).model_copy(deep=True)
    train_request.start_date = date(2022, 6, 1); train_request.end_date = date(2022, 11, 30); train_request.parameters.ma_period = 20
    manual_market = prepare_daily_market_data(train_request, Provider(frame))
    manual = BacktestEngine().run(train_request, manual_market.daily, "synthetic")
    stored = backtests.get(window["train_best"]["backtest_id"])["result"]
    for key in ("executions", "positions", "events", "equity_curve", "summary"):
        assert stored[key] == manual[key]
    assert window["test_result"]["backtest_id"] == window["fixed_test_result"]["backtest_id"]


def test_rolling_selection_uses_train_only_even_when_test_values_change(tmp_path: Path, monkeypatch):
    frame = daily_frame(); payload = rolling_payload(fixed_ma=20)
    payload["ma_max"] = 30; payload["ma_step"] = 10
    selected: list[int] = []

    def fake_run(req, *_args):
        is_train = req.start_date == date(2022, 6, 1)
        sharpe = ({20: 2.0, 30: 1.0}[req.parameters.ma_period] if is_train else 999.0 - req.parameters.ma_period)
        if not is_train and req.parameters.ma_period not in selected:
            selected.append(req.parameters.ma_period)
        return {"ma_period": req.parameters.ma_period, "backtest_id": f"{req.start_date}-{req.parameters.ma_period}", "sharpe_ratio": sharpe,
                "total_return": sharpe / 100, "max_drawdown": -.1, "net_pnl": sharpe}

    monkeypatch.setattr("app.optimization.runner._run_canonical", fake_run)
    jobs = JobRepository(tmp_path / "jobs.sqlite3"); backtests = BacktestRepository(tmp_path / "backtests.sqlite3")
    job, _ = jobs.create("MA_PERIOD_OPTIMIZATION", payload, 4); jobs.mark_running(job["id"])
    result = run_ma_optimization(job["id"], payload, jobs, backtests, Provider(frame))
    assert result and result["rolling_windows"][0]["selected_ma"] == 20
    assert result["rolling_windows"][0]["selection_source"] == "TRAIN_ONLY"
    assert selected == [20]


def test_rolling_windows_are_calendar_months_and_adjacent_train_equals_prior_test():
    windows = build_rolling_six_month_windows(date(2020, 1, 1), date(2021, 8, 31))
    assert windows[0].train_start == date(2020, 1, 1)
    assert windows[0].train_end == date(2020, 6, 30)
    assert windows[0].test_start == date(2020, 7, 1)
    assert windows[0].test_end == date(2020, 12, 31)
    assert windows[1].train_start == windows[0].test_start
    assert windows[1].train_end == windows[0].test_end
    assert windows[1].test_start == date(2021, 1, 1)
    assert (windows[0].test_start - windows[0].train_start).days != 126


def test_rolling_warmup_precedes_train_but_metrics_do_not(tmp_path: Path):
    frame = daily_frame(); payload = rolling_payload(fixed_ma=20); provider = Provider(frame)
    jobs = JobRepository(tmp_path / "jobs.sqlite3"); backtests = BacktestRepository(tmp_path / "backtests.sqlite3")
    job, _ = jobs.create("MA_PERIOD_OPTIMIZATION", payload, 3); jobs.mark_running(job["id"])
    result = run_ma_optimization(job["id"], payload, jobs, backtests, provider)
    assert result
    assert provider.calls[0][0][1] < date(2022, 6, 1)
    stored = backtests.get(result["rolling_windows"][0]["train_best"]["backtest_id"])["result"]
    assert min(row["timestamp"][:10] for row in stored["equity_curve"]) >= "2022-06-01"


def test_partial_final_rolling_test_is_provisional_and_excluded(tmp_path: Path, monkeypatch):
    payload = rolling_payload(end="2023-03-31", fixed_ma=20)
    calls = 0
    def fake_run(req, *_args):
        nonlocal calls; calls += 1
        return {"ma_period": req.parameters.ma_period, "backtest_id": f"id-{calls}", "sharpe_ratio": 1.0,
                "total_return": .05, "max_drawdown": -.02, "net_pnl": 5000}
    monkeypatch.setattr("app.optimization.runner._run_canonical", fake_run)
    jobs = JobRepository(tmp_path / "jobs.sqlite3"); backtests = BacktestRepository(tmp_path / "backtests.sqlite3")
    job, _ = jobs.create("MA_PERIOD_OPTIMIZATION", payload, 3); jobs.mark_running(job["id"])
    result = run_ma_optimization(job["id"], payload, jobs, backtests, Provider(daily_frame()))
    assert result is None
    saved = jobs.get(job["id"])
    assert saved["status"] == "FAILED_VALIDATION"
    window = saved["result"]["rolling_windows"][0]
    assert window["status"] == "PROVISIONAL_PARTIAL_TEST" and window["aggregate_included"] is False
    assert saved["result"]["test_only_aggregate"]["complete_test_windows"] == 0


def test_rolling_tie_break_is_deterministic(tmp_path: Path, monkeypatch):
    payload = rolling_payload(fixed_ma=20); payload["ma_max"] = 30; payload["ma_step"] = 10
    def fake_run(req, *_args):
        return {"ma_period": req.parameters.ma_period, "backtest_id": f"id-{req.start_date}-{req.parameters.ma_period}",
                "sharpe_ratio": 1.0, "total_return": .1, "max_drawdown": -.1, "net_pnl": 100}
    monkeypatch.setattr("app.optimization.runner._run_canonical", fake_run)
    jobs = JobRepository(tmp_path / "jobs.sqlite3"); backtests = BacktestRepository(tmp_path / "backtests.sqlite3")
    job, _ = jobs.create("MA_PERIOD_OPTIMIZATION", payload, 4); jobs.mark_running(job["id"])
    result = run_ma_optimization(job["id"], payload, jobs, backtests, Provider(daily_frame()))
    assert result and result["rolling_windows"][0]["selected_ma"] == 20
    assert result["rolling_windows"][0]["tie_break_reason"] == "SMALLER_MA_PERIOD"


@pytest.mark.parametrize("strategy", ["simple", "advanced", "advanced_day1_stop"])
def test_rolling_mode_accepts_all_three_frozen_strategy_implementations(strategy: str):
    payload = rolling_payload()
    payload["backtest"]["strategy"] = strategy
    spec = MAOptimizationRequest.model_validate(payload)
    assert spec.mode == "rolling_6m" and spec.backtest.strategy.value == strategy


def test_completed_rolling_job_reuses_only_identical_spec_and_data_fingerprint(tmp_path: Path, monkeypatch):
    payload = rolling_payload(fixed_ma=20); frame = daily_frame(); calls = 0
    def fake_run(req, *_args):
        nonlocal calls; calls += 1
        return {"ma_period": req.parameters.ma_period, "backtest_id": f"id-{calls}", "sharpe_ratio": 1.0,
                "total_return": .05, "max_drawdown": -.02, "net_pnl": 5000}
    monkeypatch.setattr("app.optimization.runner._run_canonical", fake_run)
    jobs = JobRepository(tmp_path / "jobs.sqlite3"); backtests = BacktestRepository(tmp_path / "backtests.sqlite3")
    first, _ = jobs.create("MA_PERIOD_OPTIMIZATION", payload, 3); jobs.mark_running(first["id"])
    original = run_ma_optimization(first["id"], payload, jobs, backtests, Provider(frame))
    assert original and calls == 3
    jobs.finish(first["id"], "COMPLETED", "done", result=original)
    second, _ = jobs.create("MA_PERIOD_OPTIMIZATION", payload, 3); jobs.mark_running(second["id"])
    reused = run_ma_optimization(second["id"], payload, jobs, backtests, Provider(frame))
    assert reused and reused["job_cache_reused"] is True and reused["reused_from_job_id"] == first["id"]
    assert calls == 3
