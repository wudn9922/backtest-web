"""Immutable source-of-truth snapshots for Research Environment v3.

The snapshot is created when a validation job *starts*.  Every calculation,
report section, API response and UI summary for that run is tied to the same
snapshot instead of mixing a current manifest with an older narrative.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from research import ROOT
from research.baseline import digest
from research.environment_v3_data import (
    build_data_manifest,
    build_universe_manifest,
    frame_hash,
    sha256_file,
)
from research.environment_v3_design import PRIMARY_HISTORY


class EnvironmentValidationError(RuntimeError):
    """Raised when validated inputs or a generated report contradict itself."""


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _snapshot_digest(snapshot: dict[str, Any]) -> str:
    value = dict(snapshot)
    value.pop("snapshot_sha256", None)
    return digest(value)


def validate_risk_free_input(root: Path = ROOT, *, data_dir: Path | None = None) -> dict[str, Any]:
    """Validate the actual DGS3MO Parquet and manifest, not mere existence."""
    storage = (data_dir or (root / "data")).resolve()
    manifest_path = storage / "risk-free-rate-manifest.json"
    unavailable = {
        "ready": False,
        "status": "MISSING",
        "reason": "Validated FRED DGS3MO manifest is not present.",
        "manifest_path": "data/risk-free-rate-manifest.json",
        "manifest_exists": manifest_path.is_file(),
        "data_file_exists": False,
        "series_id": "DGS3MO",
        "first_observation": None,
        "last_observation": None,
        "observations": 0,
        "manifest_sha256": None,
        "cache_sha256": None,
        "series_sha256": None,
        "validation_status": "FAIL",
    }
    if not manifest_path.is_file():
        return unavailable
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("series_id") != "DGS3MO":
            raise ValueError("manifest series_id is not DGS3MO")
        if int(manifest.get("fabricated_observations", -1)) != 0:
            raise ValueError("manifest does not guarantee zero fabricated observations")
        relative = Path(str(manifest.get("cache_file", "")))
        if relative.parts and relative.parts[0].lower() == "data":
            cache_path = ((root / relative) if storage == (root / "data").resolve()
                          else storage.joinpath(*relative.parts[1:])).resolve()
        else:
            cache_path = (storage / relative).resolve()
        data_root = storage
        if not cache_path.is_relative_to(data_root):
            raise ValueError("risk-free cache path is outside the research data directory")
        if not cache_path.is_file():
            raise ValueError("risk-free Parquet file does not exist")
        cache_sha = sha256_file(cache_path)
        if cache_sha != manifest.get("cache_sha256"):
            raise ValueError("risk-free Parquet checksum differs from the manifest")
        frame = pd.read_parquet(cache_path)
        if "annual_yield_pct" not in frame:
            raise ValueError("annual_yield_pct column is missing")
        series = pd.to_numeric(frame["annual_yield_pct"], errors="coerce").dropna().sort_index()
        index = pd.DatetimeIndex(series.index)
        if index.tz is None:
            index = index.tz_localize("UTC")
        else:
            index = index.tz_convert("UTC")
        series.index = index
        if series.empty or series.index.has_duplicates or not series.index.is_monotonic_increasing:
            raise ValueError("risk-free observations are empty, duplicated, or unsorted")
        if (series <= -100).any() or (series > 100).any():
            raise ValueError("risk-free observations are outside the accepted range")
        first = series.index[0].date().isoformat()
        last = series.index[-1].date().isoformat()
        series_sha = digest([
            {"date": timestamp.date().isoformat(), "annual_yield_pct": float(value)}
            for timestamp, value in series.items()
        ])
        comparisons = {
            "observations": int(manifest.get("observations", -1)) == len(series),
            "first_observation": manifest.get("first_observation") == first,
            "last_observation": manifest.get("last_observation") == last,
            "series_sha256": manifest.get("series_sha256") == series_sha,
            "requested_start": str(manifest.get("requested_start", "")) <= PRIMARY_HISTORY["start"].isoformat(),
            "requested_end": str(manifest.get("requested_end", "")) >= PRIMARY_HISTORY["end"].isoformat(),
            "coverage_end": last >= PRIMARY_HISTORY["end"].isoformat(),
        }
        if not all(comparisons.values()):
            failed = ", ".join(key for key, passed in comparisons.items() if not passed)
            raise ValueError(f"risk-free manifest validation failed: {failed}")
        return {
            "ready": True,
            "status": "READY",
            "reason": "Validated real FRED DGS3MO data covers the frozen research target.",
            "manifest_path": "data/risk-free-rate-manifest.json",
            "manifest_exists": True,
            "data_file_exists": True,
            "cache_file": relative.as_posix(),
            "provider": manifest.get("provider"),
            "series_id": "DGS3MO",
            "first_observation": first,
            "last_observation": last,
            "observations": int(len(series)),
            "download_timestamp": manifest.get("download_timestamp"),
            "manifest_sha256": sha256_file(manifest_path),
            "cache_sha256": cache_sha,
            "series_sha256": series_sha,
            "validation_status": "PASS",
            "fabricated_observations": 0,
            "lookahead_rule": manifest.get("lookahead_rule"),
            "compounding": manifest.get("compounding"),
        }
    except Exception as exc:
        return {
            **unavailable,
            "manifest_exists": True,
            "status": "INVALID",
            "reason": " ".join(str(exc).split())[:300],
            "manifest_sha256": sha256_file(manifest_path),
        }


def _input_fingerprint_payload(
    market: dict[str, Any], risk_free: dict[str, Any], methodology: dict[str, Any]
) -> dict[str, Any]:
    datasets = []
    for row in market["datasets"]:
        selected = next((
            variant for variant in row.get("variants", [])
            if variant.get("provider") == row.get("selected_provider")
            and variant.get("adjustment_mode") == row.get("selected_adjustment_mode")
            and variant.get("ohlcv_sha256") == row.get("ohlcv_sha256")
        ), None)
        datasets.append({
            "ticker": row["ticker"],
            "status": row["status"],
            "provider": row["selected_provider"],
            "adjustment_mode": row["selected_adjustment_mode"],
            "first_date": row["first_date"],
            "last_date": row["last_date"],
            "bars": row["bars"],
            "ohlcv_sha256": row["ohlcv_sha256"],
            "target_range_was_requested": row["target_range_was_requested"],
            "fragments": [{
                "path": fragment.get("path"),
                "sha256": fragment.get("sha256"),
                "metadata_sidecar": fragment.get("metadata_sidecar"),
                "metadata_sidecar_sha256": fragment.get("metadata_sidecar_sha256"),
            } for fragment in (selected or {}).get("fragments", [])],
        })
    return {
        "target_range": market["target_range"],
        "adjustment_basis_required": market["adjustment_basis_required"],
        "datasets": datasets,
        "risk_free": {key: risk_free.get(key) for key in (
            "ready", "series_id", "first_observation", "last_observation", "observations",
            "manifest_sha256", "cache_sha256", "series_sha256", "fabricated_observations",
        )},
        "methodology": methodology,
    }


def build_environment_snapshot(*, persist: bool = True, root: Path = ROOT) -> dict[str, Any]:
    """Re-read and validate current files, then freeze one run-level snapshot."""
    if root != ROOT:
        raise ValueError("Environment snapshots currently require the configured research root")
    market = build_data_manifest()
    universes = build_universe_manifest(market)
    risk_free = validate_risk_free_input(root)
    methodology = {}
    for name, relative in {
        "environment_spec": "research/specs/RESEARCH_ENVIRONMENT_V3.md",
        "environment_design": "research/environment_v3_design.py",
        "cash_accounting": "research/cash_models.py",
        "frozen_benchmark_spec": "research/specs/BENCHMARK_SUITE_V2.md",
    }.items():
        methodology[name] = {"path": relative, "sha256": sha256_file(root / relative)}

    mega = market["universe_readiness"]["MEGA_CAP_TECH_UNIVERSE"]
    etf = market["universe_readiness"]["ETF_RESEARCH_UNIVERSE"]
    market_ready = bool(market["long_history_validation_ready"])
    mega_ready = mega["status"] == "READY"
    etf_ready = etf["status"] == "READY"
    rate_ready = bool(risk_free["ready"])
    fingerprint_payload = _input_fingerprint_payload(market, risk_free, methodology)
    input_fingerprint = digest(fingerprint_payload)
    created_at = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "schema_version": 1,
        "environment_snapshot_id": f"env3-{created_at.replace(':', '').replace('-', '').replace('+00:00', 'Z')}-{input_fingerprint[:12]}",
        "created_at": created_at,
        "input_fingerprint_sha256": input_fingerprint,
        "target_range": market["target_range"],
        "readiness": {
            "market_long_history_ready": market_ready,
            "mega_cap_universe_ready": mega_ready,
            "etf_universe_ready": etf_ready,
            "risk_free_ready": rate_ready,
            "research_validation_ready": market_ready and mega_ready and etf_ready and rate_ready,
            "reasons": {
                "market_long_history": "All frozen-universe datasets passed provider/adjustment/OHLCV validation and target-request coverage."
                if market_ready else "One or more frozen-universe market datasets are missing or invalid.",
                "mega_cap_universe": f"{mega['target_requests_complete']}/{mega['symbols']} target requests validated.",
                "etf_universe": f"{etf['target_requests_complete']}/{etf['symbols']} target requests validated; inception-limited instruments are accepted without synthetic pre-listing bars.",
                "risk_free": risk_free["reason"],
            },
        },
        "coverage": {
            "datasets": len(market["datasets"]),
            "mega_cap": mega,
            "etf": etf,
            "fabricated_bars": market["fabricated_bars"],
        },
        "market_manifest": market,
        "universe_manifest": universes,
        "risk_free": risk_free,
        "methodology_fingerprints": methodology,
        "section_source_contract": {
            section: "CURRENT_ENVIRONMENT_SNAPSHOT"
            for section in (
                "Executive Summary", "Data Acquisition", "Universe", "Cash Model",
                "Sensitivity Matrix", "Direct Answers", "Final Classification",
            )
        },
        "source_inventory": {
            "market_cache_and_sidecars": "authoritative validated market input",
            "risk_free_parquet_and_manifest": "authoritative validated cash-rate input",
            "environment_snapshot": "sole run-level source of truth",
            "research_data_manifest": "snapshot-derived compatibility artifact",
            "universe_manifest": "snapshot-derived compatibility artifact",
            "job_result": "pointer to snapshot and generated report only",
            "previous_report": "output only; never an input",
            "previous_environment_json": "output only; never an input",
            "frontend_api_state": "no-store view of current output; never a research input",
            "in_memory_state": "immutable snapshot object for the duration of one job",
        },
        "input_fingerprint_payload": fingerprint_payload,
    }
    snapshot["snapshot_sha256"] = _snapshot_digest(snapshot)

    if persist:
        data_dir = root / "data"
        _atomic_json(data_dir / "research-data-manifest-v3.json", market)
        _atomic_json(data_dir / "research-universes.json", universes)
        snapshots = data_dir / "research-environment-snapshots"
        snapshot_path = snapshots / f"{snapshot['environment_snapshot_id']}.json"
        if snapshot_path.exists():
            existing = json.loads(snapshot_path.read_text(encoding="utf-8"))
            if existing != snapshot:
                raise EnvironmentValidationError("An immutable environment snapshot ID collision occurred")
        else:
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
        _atomic_json(data_dir / "research-environment-current-snapshot.json", snapshot)
        snapshot["snapshot_file"] = snapshot_path.relative_to(root).as_posix()
        snapshot["snapshot_file_sha256"] = sha256_file(snapshot_path)
    return snapshot


def assert_snapshot_immutable(snapshot: dict[str, Any], root: Path = ROOT) -> None:
    expected = snapshot.get("snapshot_sha256")
    if not expected or _snapshot_digest(snapshot) != expected:
        # Persistence-only locator fields are appended after the frozen payload.
        compact = dict(snapshot)
        compact.pop("snapshot_file", None)
        compact.pop("snapshot_file_sha256", None)
        if _snapshot_digest(compact) != expected:
            raise EnvironmentValidationError("Environment snapshot content changed during the research run")
    path_value = snapshot.get("snapshot_file")
    if path_value:
        path = root / str(path_value)
        if not path.is_file() or sha256_file(path) != snapshot.get("snapshot_file_sha256"):
            raise EnvironmentValidationError("Persisted environment snapshot changed during the research run")


def assert_snapshot_inputs_unchanged(snapshot: dict[str, Any], root: Path = ROOT) -> None:
    """Verify every Parquet/sidecar/rate byte used by a snapshot is unchanged."""
    for dataset in snapshot["input_fingerprint_payload"]["datasets"]:
        for fragment in dataset.get("fragments", []):
            path = root / fragment["path"]
            if not path.is_file() or sha256_file(path) != fragment["sha256"]:
                raise EnvironmentValidationError(
                    f"Market input changed during research: {dataset['ticker']}"
                )
            sidecar_value = fragment.get("metadata_sidecar")
            if sidecar_value:
                sidecar = root / sidecar_value
                if not sidecar.is_file() or sha256_file(sidecar) != fragment.get("metadata_sidecar_sha256"):
                    raise EnvironmentValidationError(
                        f"Market metadata changed during research: {dataset['ticker']}"
                    )
    rate = snapshot["risk_free"]
    if rate.get("ready"):
        manifest = root / rate["manifest_path"]
        cache = root / rate["cache_file"]
        if sha256_file(manifest) != rate["manifest_sha256"] or sha256_file(cache) != rate["cache_sha256"]:
            raise EnvironmentValidationError("Risk-free input changed during research")
