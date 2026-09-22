from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from app.backtest.models import BacktestError
from app.data.base import MarketData
from app.jobs.repository import JobRepository
from app.jobs.service import (
    CONNECTIVITY_JOB,
    JobService,
    MARKET_JOB,
    RATE_JOB,
    REPAIR_JOB,
    SMOKE_JOB,
    _enable_research_imports,
)
from app.main import app


_enable_research_imports()


class Chain:
    yahoo = object()
    alternative = object()


def service(tmp_path: Path) -> JobService:
    return JobService(tmp_path, Chain())


def bar() -> MarketData:
    frame = pd.DataFrame(
        {"open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5], "volume": [1000.0]},
        index=pd.DatetimeIndex([pd.Timestamp("2024-01-02", tz="UTC")], name="timestamp"),
    )
    return MarketData(frame, "yahoo", [])


def test_create_is_idempotent_and_progress_is_persistent(tmp_path):
    repo = JobRepository(tmp_path / "jobs.sqlite3")
    first, created = repo.create(MARKET_JOB, {}, 23)
    second, duplicate = repo.create(MARKET_JOB, {}, 23)
    assert created is True and duplicate is False
    assert first["id"] == second["id"]
    repo.mark_running(first["id"])
    repo.progress(first["id"], 6, 23, "AMD", "正在處理 AMD。", result={"completed": [{"ticker": "AAPL"}]})
    stored = repo.get(first["id"])
    assert stored and stored["status"] == "RUNNING"
    assert stored["progress_current"] == 6 and stored["current_item"] == "AMD"


def test_interrupted_running_job_is_requeued_for_supervisor_recovery(tmp_path):
    repo = JobRepository(tmp_path / "jobs.sqlite3")
    job, _ = repo.create(MARKET_JOB, {}, 23)
    repo.mark_running(job["id"])
    assert repo.recover_interrupted() == [job["id"]]
    recovered = repo.get(job["id"])
    assert recovered and recovered["status"] == "QUEUED"
    assert "繼續" in recovered["message"]


def test_partial_success_retry_contains_only_failed_tickers(tmp_path):
    jobs = service(tmp_path)
    original, _ = jobs.repository.create(MARKET_JOB, {}, 2)
    jobs.repository.finish(original["id"], "PARTIAL_SUCCESS", "部分完成", errors=[{"ticker": "TSLA", "code": "RATE_LIMITED"}], result={})
    retry = jobs.retry(original["id"])
    assert retry["payload"]["tickers"] == ["TSLA"]
    assert retry["payload"]["retry_of"] == original["id"]


def test_cache_first_skips_network_and_does_not_duplicate_download(tmp_path, monkeypatch):
    jobs = service(tmp_path)
    calls = {"network": 0}
    class Yahoo:
        def __init__(self, _root): pass
        def get_cached_market_data(self, *_args): return bar()
        def get_market_data(self, *_args): calls["network"] += 1; return bar()
    class Stooq:
        def __init__(self, _root): pass
    monkeypatch.setattr("app.jobs.service.YahooDataProvider", Yahoo)
    monkeypatch.setattr("app.jobs.service.StooqDataProvider", Stooq)
    monkeypatch.setattr("research.prepare_environment_v3.write_manifests", lambda: ({"long_history_validation_ready": False, "universe_readiness": {}, "generated_at": "now"}, {}))
    job, _ = jobs.repository.create(MARKET_JOB, {"tickers": ["AAPL"]}, 1)
    jobs.repository.mark_running(job["id"])
    jobs._market(job["id"], {"tickers": ["AAPL"]})
    stored = jobs.repository.get(job["id"])
    assert calls["network"] == 0
    assert stored and stored["status"] == "COMPLETED"
    assert stored["result"]["completed"][0]["status"] == "CACHE_COMPLETE"


def test_rate_limit_stops_storm_and_records_remaining_for_resume(tmp_path, monkeypatch):
    jobs = service(tmp_path)
    calls = {"yahoo": 0}
    class Yahoo:
        def __init__(self, _root): pass
        def get_cached_market_data(self, *_args): return None
        def get_market_data(self, *_args):
            calls["yahoo"] += 1
            raise BacktestError("RATE_LIMITED", "HTTP 429")
    class Stooq:
        def __init__(self, _root): pass
        def get_market_data(self, *_args): raise BacktestError("PROVIDER_CONNECTION_ERROR", "offline")
    monkeypatch.setattr("app.jobs.service.YahooDataProvider", Yahoo)
    monkeypatch.setattr("app.jobs.service.StooqDataProvider", Stooq)
    monkeypatch.setattr("research.prepare_environment_v3.write_manifests", lambda: ({"long_history_validation_ready": False, "universe_readiness": {}, "generated_at": "now"}, {}))
    job, _ = jobs.repository.create(MARKET_JOB, {"tickers": ["AAPL", "MSFT"]}, 2)
    jobs.repository.mark_running(job["id"])
    jobs._market(job["id"], {"tickers": ["AAPL", "MSFT"]})
    stored = jobs.repository.get(job["id"])
    assert calls["yahoo"] == 1
    assert stored and stored["status"] == "PARTIAL_SUCCESS"
    assert [row["ticker"] for row in stored["errors"]] == ["AAPL", "MSFT"]
    assert all(row["code"] == "RATE_LIMITED" for row in stored["errors"])


def test_risk_free_job_writes_only_real_downloader_result(tmp_path, monkeypatch):
    jobs = service(tmp_path)
    manifest = {"series_id": "DGS3MO", "observations": 100, "fabricated_observations": 0}
    monkeypatch.setattr("research.environment_v3_data.download_risk_free", lambda *_args: manifest)
    job, _ = jobs.repository.create(RATE_JOB, {}, 1)
    jobs.repository.mark_running(job["id"])
    result = jobs._risk_free(job["id"])
    assert result == {"manifest": manifest}
    assert jobs.repository.provider_health()["fred"]["status"] == "online"


def test_risk_free_failure_creates_no_fake_manifest(tmp_path, monkeypatch):
    jobs = service(tmp_path)
    monkeypatch.setattr("research.environment_v3_data.download_risk_free", lambda *_args: (_ for _ in ()).throw(RuntimeError("offline")))
    job, _ = jobs.repository.create(RATE_JOB, {}, 1)
    jobs.repository.mark_running(job["id"])
    assert jobs._risk_free(job["id"]) is None
    stored = jobs.repository.get(job["id"])
    assert stored and stored["status"] == "FAILED"
    assert not (tmp_path / "risk-free-rate-manifest.json").exists()


def test_environment_readiness_requires_market_and_real_rate_manifest(tmp_path, monkeypatch):
    jobs = service(tmp_path)
    universe = {
        "MEGA_CAP_TECH_UNIVERSE": {"status": "READY", "target_requests_complete": 11, "symbols": 11},
        "ETF_RESEARCH_UNIVERSE": {"status": "READY", "target_requests_complete": 14, "symbols": 14},
    }
    monkeypatch.setattr("research.environment_v3_data.build_data_manifest", lambda: {"long_history_validation_ready": True, "universe_readiness": universe})
    assert jobs.readiness()["research_validation_ready"] is False
    (tmp_path / "risk-free-rate-manifest.json").write_text('{"series_id":"DGS3MO"}', encoding="utf-8")
    assert jobs.readiness()["research_validation_ready"] is False
    monkeypatch.setattr("research.environment_v3_snapshot.validate_risk_free_input", lambda **_kwargs: {
        "ready": True, "status": "READY", "reason": "validated", "series_id": "DGS3MO",
        "first_observation": "2010-01-04", "last_observation": "2026-09-01",
        "observations": 4169, "validation_status": "PASS",
    })
    assert jobs.readiness()["research_validation_ready"] is True


def test_data_center_api_creates_jobs_without_network_on_request_thread(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(JobService, "start", lambda self: None)
    monkeypatch.setattr(JobService, "stop", lambda self: None)
    monkeypatch.setattr(JobService, "runtime_health", lambda self: {
        "context_status": "current_interactive_user", "python_path_expected": True,
        "launcher_installed": True, "repair_required": False,
    })
    with TestClient(app) as client:
        status = client.get("/api/system/status")
        assert status.status_code == 200
        assert status.json()["checked_by"] == "windows_backend"
        center = client.get("/api/data-center")
        assert center.status_code == 200
        assert center.json()["risk_free"]["status"] == "not_downloaded"
        job = client.post("/api/jobs/provider-connectivity-check")
        assert job.status_code == 202
        assert job.json()["status"] == "QUEUED"
        assert client.get(f"/api/jobs/{job.json()['id']}").status_code == 200
        assert client.post("/api/jobs/provider-connectivity-repair").status_code == 202
        assert client.post("/api/jobs/provider-download-smoke-test").status_code == 202


def test_connectivity_job_preserves_online_restricted_and_validation_states(tmp_path, monkeypatch):
    jobs = service(tmp_path)
    monkeypatch.setattr("app.jobs.service.run_diagnostic", lambda *_args: {
        "providers": {
            "yahoo": {"status": "online", "error_type": None},
            "stooq": {"status": "restricted", "error_type": "RATE_LIMITED"},
            "fred": {"status": "validation_failed", "error_type": "PROVIDER_VALIDATION_FAILED"},
        },
        "network_control": {"google_https": True, "google_tcp_443": True},
        "runtime": {"repair_required": False},
    })
    job, _ = jobs.repository.create(CONNECTIVITY_JOB, {}, 3)
    jobs.repository.mark_running(job["id"])
    result = jobs._connectivity(job["id"])
    health = jobs.repository.provider_health()
    assert result["network_control"]["google_https"] is True
    assert health["yahoo"]["status"] == "online" and health["yahoo"]["last_success_at"]
    assert health["stooq"]["status"] == "restricted" and health["stooq"]["last_error_type"] == "RATE_LIMITED"
    assert health["fred"]["status"] == "validation_failed"


def test_repair_job_opens_fixed_windows_approval_when_runtime_is_wrong(tmp_path, monkeypatch):
    jobs = service(tmp_path)
    monkeypatch.setattr("app.jobs.service.runtime_environment", lambda *_args: {
        "repair_required": True, "context_status": "restricted_or_noninteractive", "technical": {"secret": "local-only"},
    })
    monkeypatch.setattr("app.jobs.service.launch_windows_launcher_approval", lambda *_args: True)
    job, _ = jobs.repository.create(REPAIR_JOB, {}, 3)
    jobs.repository.mark_running(job["id"])
    assert jobs._repair_connectivity(job["id"]) is None
    stored = jobs.repository.get(job["id"])
    assert stored and stored["status"] == "FAILED"
    assert stored["errors"][0]["code"] == "WINDOWS_LAUNCHER_APPROVAL_REQUIRED"
    assert stored["result"]["gui_approval_launched"] is True
    assert "technical" not in stored["result"]["runtime"]


def test_small_download_job_writes_real_cache_and_isolated_rate_manifest(tmp_path, monkeypatch):
    class Cache:
        def has_any(self, *_args): return False
        def read_coverage(self, *_args):
            return type("Coverage", (), {"paths": [tmp_path / "VTI.parquet"], "complete": True})()
    class Yahoo:
        cache = Cache()
        def get_market_data(self, *_args): return bar()
    class SmokeChain:
        yahoo = Yahoo()
        alternative = object()
    jobs = JobService(tmp_path, SmokeChain())
    monkeypatch.setattr("app.jobs.service.write_fred_smoke_cache", lambda *_args: {
        "series_id": "DGS3MO", "observations": 7, "cache_written": True,
        "manifest_written": True, "fabricated_observations": 0,
    })
    job, _ = jobs.repository.create(SMOKE_JOB, {}, 2)
    jobs.repository.mark_running(job["id"])
    result = jobs._download_smoke_test(job["id"])
    assert result and result["market"]["cache_written"] is True
    assert result["risk_free"]["manifest_written"] is True
    stored = jobs.repository.get(job["id"])
    assert stored and stored["progress_current"] == stored["progress_total"] == 2


def test_research_validation_runs_long_history_extension_and_indexes_report(tmp_path, monkeypatch):
    jobs = service(tmp_path)
    snapshot = {
        "environment_snapshot_id": "env-test", "created_at": "2026-09-06T00:00:00+00:00",
        "input_fingerprint_sha256": "abc", "readiness": {"research_validation_ready": True},
    }
    monkeypatch.setattr("research.environment_v3_snapshot.build_environment_snapshot", lambda persist=True: snapshot)
    monkeypatch.setattr(
        "research.environment_v3_extension.run",
        lambda progress, snapshot: (
            progress(2, 3, "NVDA", "正在驗證 NVDA。")
            or {"full_period": [{"symbol": "NVDA"}], "immutability": {"unchanged": True}}
        ),
    )
    calls = {"environment": 0, "catalog": 0}
    monkeypatch.setattr("research.build_environment_v3.build", lambda **_kwargs: (calls.__setitem__("environment", calls["environment"] + 1) or {"sensitivity_classification": "MIXED", "next_family": "NONE"}))
    monkeypatch.setattr("research.build_framework_catalog.build", lambda: calls.__setitem__("catalog", calls["catalog"] + 1))
    job, _ = jobs.repository.create("RESEARCH_ENVIRONMENT_VALIDATION", {}, 1)
    jobs.repository.mark_running(job["id"])
    result = jobs._research_validation(job["id"])
    assert result and result["report_id"] == "research-environment-v3"
    assert result["rows"] == 1
    assert result["environment_snapshot_id"] == "env-test"
    assert calls == {"environment": 1, "catalog": 1}
    stored = jobs.repository.get(job["id"])
    assert stored and stored["progress_current"] == stored["progress_total"] == 3


def test_research_consistency_failure_gets_dedicated_terminal_status(tmp_path, monkeypatch):
    jobs = service(tmp_path)
    snapshot = {
        "environment_snapshot_id": "env-invalid", "created_at": "2026-09-06T00:00:00+00:00",
        "input_fingerprint_sha256": "abc", "readiness": {"research_validation_ready": True},
    }
    monkeypatch.setattr("research.environment_v3_snapshot.build_environment_snapshot", lambda persist=True: snapshot)
    from research.environment_v3_snapshot import EnvironmentValidationError
    monkeypatch.setattr(
        "research.environment_v3_extension.run",
        lambda **_kwargs: (_ for _ in ()).throw(EnvironmentValidationError("contradictory output")),
    )
    job, _ = jobs.repository.create("RESEARCH_ENVIRONMENT_VALIDATION", {}, 1)
    jobs.repository.mark_running(job["id"])
    assert jobs._research_validation(job["id"]) is None
    stored = jobs.repository.get(job["id"])
    assert stored and stored["status"] == "FAILED_VALIDATION"
    assert stored["errors"][0]["code"] == "RESEARCH_REPORT_VALIDATION_FAILED"
