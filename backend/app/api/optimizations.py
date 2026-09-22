from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.jobs.service import MA_OPTIMIZATION_JOB
from app.optimization.models import MAOptimizationRequest
from app.optimization.structure import (
    STRUCTURE_IMPLEMENTATION_REVISION,
    STRUCTURE_SPEC_HASH,
    STRUCTURE_SPEC_VERSION,
)


router = APIRouter(prefix="/api/optimizations", tags=["optimizations"])


def _service(request: Request):
    service = getattr(request.app.state, "job_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail={"code": "JOB_SERVICE_UNAVAILABLE", "message": "Background jobs are unavailable."})
    return service


@router.post("", status_code=202)
def create_optimization(payload: MAOptimizationRequest, request: Request):
    return _service(request).create(MA_OPTIMIZATION_JOB, payload.model_dump(mode="json"))


@router.get("")
def list_optimizations(request: Request, limit: int = 30):
    return _service(request).repository.list_by_type(MA_OPTIMIZATION_JOB, limit)


@router.get("/{identifier}")
def get_optimization(identifier: str, request: Request):
    job = _service(request).repository.get(identifier)
    if not job or job.get("job_type") != MA_OPTIMIZATION_JOB:
        raise HTTPException(status_code=404, detail={"code": "OPTIMIZATION_NOT_FOUND", "message": "Optimization was not found."})
    return job


@router.post("/{identifier}/cancel", status_code=202)
def cancel_optimization(identifier: str, request: Request):
    service = _service(request)
    job = service.repository.get(identifier)
    if not job or job.get("job_type") != MA_OPTIMIZATION_JOB:
        raise HTTPException(status_code=404, detail={"code": "OPTIMIZATION_NOT_FOUND", "message": "Optimization was not found."})
    service.repository.cancel(identifier)
    return service.repository.get(identifier)


@router.post("/{identifier}/retry", status_code=202)
def retry_optimization(identifier: str, request: Request):
    service = _service(request)
    job = service.repository.get(identifier)
    if not job or job.get("job_type") != MA_OPTIMIZATION_JOB:
        raise HTTPException(status_code=404, detail={"code": "OPTIMIZATION_NOT_FOUND", "message": "Optimization was not found."})
    if job.get("status") in {"QUEUED", "RUNNING"}:
        return job
    return service.retry(identifier)


@router.get("/{identifier}/structure/windows/{window_index}/candidates/{ma_period}")
def get_structure_artifact(identifier: str, window_index: int, ma_period: int, request: Request):
    """Return one persisted Top-5 Train-only numerical chart artifact."""
    service = _service(request)
    job = service.repository.get(identifier)
    if not job or job.get("job_type") != MA_OPTIMIZATION_JOB:
        raise HTTPException(status_code=404, detail={"code": "OPTIMIZATION_NOT_FOUND", "message": "Optimization was not found."})
    payload = job.get("payload") or {}
    result = job.get("result") or {}
    if payload.get("selection_mode", "PERFORMANCE") != "STRUCTURE_V1" or result.get("selection_mode") != "STRUCTURE_V1":
        raise HTTPException(status_code=422, detail={"code": "STRUCTURE_ARTIFACT_NOT_AVAILABLE", "message": "This optimization does not contain Structure V1 artifacts."})
    if result.get("structure_spec_version") != STRUCTURE_SPEC_VERSION or result.get("structure_spec_hash") != STRUCTURE_SPEC_HASH:
        raise HTTPException(status_code=422, detail={"code": "STRUCTURE_SPEC_MISMATCH", "message": "The saved Structure artifact uses a different frozen specification."})
    if result.get("structure_implementation_revision") != STRUCTURE_IMPLEMENTATION_REVISION:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "STRUCTURE_IMPLEMENTATION_REVISION_MISMATCH",
                "message": "This saved Structure result predates the corrected selector implementation and is invalidated.",
            },
        )
    windows = result.get("rolling_windows") or []
    window = next((item for item in windows if int(item.get("index", -1)) == int(window_index)), None)
    if window is None:
        raise HTTPException(status_code=404, detail={"code": "STRUCTURE_WINDOW_NOT_FOUND", "message": "Structure window was not found."})
    top5 = {int(item.get("ma_period")): item for item in (window.get("structure_top5") or []) if item.get("ma_period") is not None}
    if ma_period not in top5:
        raise HTTPException(status_code=404, detail={"code": "STRUCTURE_ARTIFACT_NOT_FOUND", "message": "Only saved Top-5 Structure candidates have chart artifacts."})
    artifact = service.repository.get_structure_artifact(identifier, window_index, ma_period, STRUCTURE_SPEC_HASH)
    if artifact is None:
        raise HTTPException(status_code=404, detail={"code": "STRUCTURE_ARTIFACT_NOT_FOUND", "message": "Structure chart artifact was not found."})
    if artifact.get("structure_implementation_revision") != STRUCTURE_IMPLEMENTATION_REVISION:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "STRUCTURE_IMPLEMENTATION_REVISION_MISMATCH",
                "message": "This saved Structure chart predates the corrected selector implementation and is invalidated.",
            },
        )
    return {
        "job_id": identifier,
        "window_index": int(window_index),
        "ma_period": int(ma_period),
        "structure_spec_version": STRUCTURE_SPEC_VERSION,
        "structure_spec_hash": STRUCTURE_SPEC_HASH,
        "structure_implementation_revision": STRUCTURE_IMPLEMENTATION_REVISION,
        "candidate_summary": top5[ma_period],
        "artifact": artifact,
    }
