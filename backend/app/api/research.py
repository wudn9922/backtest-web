from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse


router = APIRouter(prefix="/api/research", tags=["research"])
SAFE_REPORT_ID = re.compile(r"^[a-z0-9-]{1,64}$")


def _data_root() -> Path:
    return Path(os.getenv("RESEARCH_DATA_DIR", os.getenv("DATA_DIR", "../data"))).resolve()


def _reports_root() -> Path:
    return Path(os.getenv("RESEARCH_REPORTS_DIR", "../reports")).resolve()


def _load(name: str) -> dict:
    path = (_data_root() / name).resolve()
    if path.parent != _data_root() or not path.is_file():
        raise HTTPException(status_code=503, detail={"code": "RESEARCH_CATALOG_UNAVAILABLE", "message": "Research catalog is not available."})
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail={"code": "RESEARCH_CATALOG_INVALID", "message": "Research catalog could not be read."}) from exc


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"


@router.get("/framework")
def research_framework(response: Response):
    """Read-only framework/registry view; never runs or mutates research."""
    _no_store(response)
    catalog = _load("research-framework-v2-catalog.json")
    # The current published environment is authoritative even if a catalog
    # indexing step was interrupted after the report was atomically published.
    current_path = _data_root() / "research-environment-v3.json"
    if current_path.is_file():
        current = _load("research-environment-v3.json")
        catalog["research_environment"] = {
            "study": current["study"],
            "status": current["long_history_validation_status"],
            "data_history": current["data_history"],
            "universes": current["universes"],
            "cash_models": current["cash_models"],
            "data_manifest": current["data_manifest"],
            "universe_manifest": current["universe_manifest"],
            "sensitivity_classification": current["sensitivity_classification"],
            "next_family": current["next_family"],
            "report_id": "research-environment-v3",
            "candidate_created": False,
            "environment_snapshot": current["environment_snapshot"],
            "readiness": current["readiness"],
        }
    momentum_path = _data_root() / "cross-sectional-momentum-benchmark.json"
    if momentum_path.is_file():
        study = _load(momentum_path.name)
        catalog["xsmom_benchmark"] = {
            key: study[key] for key in ("study", "grade", "next_family", "evaluation_start",
                                       "evaluation_end", "registration", "cash_models")
        }
    volatility_path = _data_root() / "volatility-managed-benchmark.json"
    if volatility_path.is_file():
        study = _load(volatility_path.name)
        catalog["volatility_managed_benchmark"] = {
            key: study[key] for key in (
                "study", "title", "evidence_grade", "next_family", "registration", "evaluation",
                "parameters", "primary_spy", "robustness_summary", "crisis_analysis",
                "cost_stress_spy", "cash_decomposition", "walk_forward_summary",
            )
        }
    return catalog


@router.get("/environment/current")
def current_research_environment(response: Response):
    """Return the latest atomically published snapshot-bound environment result."""
    _no_store(response)
    return _load("research-environment-v3.json")


@router.get("/reports/{report_id}")
def research_report(report_id: str):
    """Serve only report filenames present in the immutable history index."""
    if not SAFE_REPORT_ID.fullmatch(report_id):
        raise HTTPException(status_code=404, detail={"code": "RESEARCH_REPORT_NOT_FOUND", "message": "Research report was not found."})
    history = _load("research-history-index.json")
    row = next((item for item in history.get("studies", []) if item.get("report_id") == report_id), None)
    # Fixed benchmark report, intentionally outside the candidate registry.
    fixed_benchmark_reports = {
        "cross-sectional-momentum-benchmark": "cross-sectional-momentum-benchmark.md",
        "volatility-managed-benchmark": "volatility-managed-benchmark.md",
    }
    if report_id in fixed_benchmark_reports:
        row = {"report_file": fixed_benchmark_reports[report_id]}
    if not row:
        raise HTTPException(status_code=404, detail={"code": "RESEARCH_REPORT_NOT_FOUND", "message": "Research report was not found."})
    filename = str(row.get("report_file", ""))
    if Path(filename).name != filename or not filename.endswith(".md"):
        raise HTTPException(status_code=404, detail={"code": "RESEARCH_REPORT_NOT_FOUND", "message": "Research report was not found."})
    root = _reports_root()
    path = (root / filename).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(status_code=404, detail={"code": "RESEARCH_REPORT_NOT_FOUND", "message": "Research report was not found."})
    return FileResponse(
        path, media_type="text/markdown; charset=utf-8", filename=filename,
        content_disposition_type="inline", headers={"Cache-Control": "no-store, max-age=0"},
    )
