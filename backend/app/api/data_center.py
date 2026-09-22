from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.jobs.service import CONNECTIVITY_JOB, MARKET_JOB, RATE_JOB, REPAIR_JOB, RESEARCH_JOB, SMOKE_JOB


router = APIRouter(prefix="/api", tags=["data-center"])


def _data_root() -> Path:
    return Path(os.getenv("RESEARCH_DATA_DIR", os.getenv("DATA_DIR", "../data"))).resolve()


def _load_json(name: str) -> dict[str, Any] | None:
    path = (_data_root() / name).resolve()
    if path.parent != _data_root() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _jobs(request: Request):
    service = getattr(request.app.state, "job_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail={"code": "JOB_SERVICE_UNAVAILABLE", "message": "Background jobs are unavailable."})
    return service


def _provider_view(service) -> dict[str, Any]:
    stored = service.repository.provider_health()
    output = {}
    for provider in ("yahoo", "stooq", "fred"):
        row = stored.get(provider)
        output[provider] = row or {
            "provider": provider,
            "status": "not_tested",
            "last_checked_at": None,
            "last_success_at": None,
            "last_error_type": None,
            "safe_message": None,
        }
    return output


@router.get("/data-center")
def data_center(request: Request):
    service = _jobs(request)
    providers = _provider_view(service)
    runtime = service.runtime_health()
    manifest = _load_json("research-data-manifest-v3.json") or {}
    universe_manifest = _load_json("research-universes.json") or {}
    readiness = service.readiness()
    risk_free = readiness.get("risk_free", {})
    rows = []
    for row in manifest.get("datasets", []):
        rows.append({
            "ticker": row.get("ticker"),
            "first_date": row.get("first_date"),
            "last_date": row.get("last_date"),
            "bars": int(row.get("bars") or 0),
            "provider": row.get("selected_provider"),
            "updated_at": row.get("download_timestamp"),
            "complete": bool(row.get("target_range_was_requested")),
            "status": row.get("status"),
            "adjustment_mode": row.get("selected_adjustment_mode"),
        })
    if readiness["market_data_ready"]:
        long_status = "complete"
    elif any(row["bars"] for row in rows):
        long_status = "partial"
    else:
        long_status = "incomplete"
    return {
        "providers": providers,
        "runtime": runtime,
        "connection_repair_required": bool(
            runtime.get("repair_required")
            or all(
                row.get("status") == "offline" and row.get("last_error_type") == "PROVIDER_CONNECTION_ERROR"
                for row in providers.values()
            )
        ),
        "target_range": manifest.get("target_range", {"start": "2010-01-01", "end": "2026-09-01"}),
        "long_history_status": long_status,
        "datasets": rows,
        "universes": universe_manifest.get("universes", {}),
        "risk_free": {
            "status": "available" if readiness["risk_free_ready"] else (
                "not_downloaded" if risk_free.get("status") == "MISSING"
                else risk_free.get("status", "not_downloaded").lower()
            ),
            "series_id": "DGS3MO",
            "description": "3 個月美國國庫券利率",
            "first_observation": risk_free.get("first_observation"),
            "last_observation": risk_free.get("last_observation"),
            "observations": risk_free.get("observations", 0),
            "updated_at": None,
            "validation_status": risk_free.get("validation_status"),
            "reason": risk_free.get("reason"),
        },
        "readiness": readiness,
        "jobs": service.repository.list(20),
    }


@router.get("/system/status")
def system_status(request: Request):
    service = _jobs(request)
    providers = _provider_view(service)
    provider_states = [row["status"] for row in providers.values()]
    if provider_states and all(value == "online" for value in provider_states):
        provider_status = "normal"
    elif any(value == "online" for value in provider_states):
        provider_status = "partial"
    elif all(value == "not_tested" for value in provider_states):
        provider_status = "not_tested"
    else:
        provider_status = "unavailable"
    try:
        probe = service.data_dir / ".write-check"
        probe.write_text("ok", encoding="ascii"); probe.unlink()
        cache_status = "normal"
    except OSError:
        cache_status = "unavailable"
    return {
        "frontend": "normal",
        "backtest_engine": "normal",
        "data_sources": provider_status,
        "local_cache": cache_status,
        "checked_by": "windows_backend",
    }


@router.get("/jobs")
def list_jobs(request: Request, limit: int = 30):
    return _jobs(request).repository.list(limit)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    job = _jobs(request).repository.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "Background job was not found."})
    return job


@router.post("/jobs/provider-connectivity-check", status_code=202)
def check_providers(request: Request):
    return _jobs(request).create(CONNECTIVITY_JOB)


@router.post("/jobs/provider-connectivity-repair", status_code=202)
def repair_provider_connectivity(request: Request):
    return _jobs(request).create(REPAIR_JOB)


@router.post("/jobs/provider-download-smoke-test", status_code=202)
def provider_download_smoke_test(request: Request):
    return _jobs(request).create(SMOKE_JOB)


@router.post("/jobs/research-market-data", status_code=202)
def download_research_market_data(request: Request):
    return _jobs(request).create(MARKET_JOB)


@router.post("/jobs/risk-free-data", status_code=202)
def download_risk_free(request: Request):
    return _jobs(request).create(RATE_JOB)


@router.post("/jobs/research-environment-validation", status_code=202)
def validate_research_environment(request: Request):
    service = _jobs(request)
    ready = service.readiness()
    if not ready["research_validation_ready"]:
        raise HTTPException(status_code=409, detail={"code": "RESEARCH_INPUTS_NOT_READY", "message": "Research data is not ready."})
    return service.create(RESEARCH_JOB)


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str, request: Request):
    try:
        return _jobs(request).retry(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "Background job was not found."}) from None
