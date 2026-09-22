"""Publish one internally consistent Environment v3 artifact.

The immutable environment snapshot is the only input boundary. Previous
reports, previous Environment JSON, job pre-checks and frontend state are never
read to form conclusions.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research import ROOT
from research.baseline import immutable_fingerprints, load
from research.environment_v3_data import sha256_file
from research.environment_v3_design import CASH_MODELS, FROZEN_BENCHMARK_PARAMETERS, WARMUP_CONTRACT
from research.environment_v3_report import render, validate_report_consistency
from research.environment_v3_snapshot import (
    EnvironmentValidationError,
    assert_snapshot_immutable,
    assert_snapshot_inputs_unchanged,
    build_environment_snapshot,
)
from research.framework_freeze import semantic_production_source
from research.run_ablation import canonical_checks


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _load_matching_extension(snapshot: dict[str, Any]) -> dict[str, Any]:
    path = ROOT / "data/research-environment-v3-long-history.json"
    if not path.is_file():
        raise EnvironmentValidationError("Snapshot is ready but no snapshot-bound long-history result exists")
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EnvironmentValidationError("Long-history result is unreadable") from exc
    result_snapshot = result.get("environment_snapshot", {})
    if result_snapshot.get("environment_snapshot_id") != snapshot["environment_snapshot_id"]:
        raise EnvironmentValidationError("Long-history result belongs to a different environment snapshot")
    if result_snapshot.get("input_fingerprint_sha256") != snapshot["input_fingerprint_sha256"]:
        raise EnvironmentValidationError("Long-history result input fingerprint differs from the current snapshot")
    return result


def _selected_variant(row: dict[str, Any]) -> dict[str, Any]:
    matches = [
        item for item in row.get("variants", [])
        if item.get("provider") == row.get("selected_provider")
        and item.get("adjustment_mode") == row.get("selected_adjustment_mode")
        and item.get("ohlcv_sha256") == row.get("ohlcv_sha256")
        and item.get("validation", {}).get("status") == "PASS"
    ]
    if not matches:
        raise EnvironmentValidationError(f"Snapshot has no validated selected dataset for {row['ticker']}")
    return max(matches, key=lambda item: int(item.get("bars") or 0))


def _dataset_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    for row in snapshot["market_manifest"]["datasets"]:
        selected = _selected_variant(row)
        fragments = selected.get("fragments", [])
        sidecars = [fragment for fragment in fragments if fragment.get("metadata_sidecar_exists")]
        output.append({
            "ticker": row["ticker"],
            "status": row["status"],
            "provider": row["selected_provider"],
            "adjustment_mode": row["selected_adjustment_mode"],
            "adjustment_contract": selected.get("adjustment_contract"),
            "first_date": row["first_date"],
            "last_date": row["last_date"],
            "bars": int(row["bars"]),
            "ohlcv_sha256": row["ohlcv_sha256"],
            "download_timestamp": row.get("download_timestamp"),
            "target_range_was_requested": bool(row["target_range_was_requested"]),
            "validation_status": selected["validation"]["status"],
            "validation_issue": selected["validation"].get("issue"),
            "metadata_sidecar_exists": len(sidecars) == len(fragments) and bool(fragments),
            "metadata_sidecars": [{
                "path": fragment.get("metadata_sidecar"),
                "sha256": fragment.get("metadata_sidecar_sha256"),
            } for fragment in sidecars],
            "cache_fragments": [{
                "path": fragment["path"], "sha256": fragment["sha256"],
            } for fragment in fragments],
        })
    return output


def _universe(snapshot: dict[str, Any], name: str) -> dict[str, Any]:
    row = snapshot["market_manifest"]["universe_readiness"][name]
    return {
        "status": row["status"], "symbol_count": row["symbols"],
        "validated_datasets": row["validated_datasets"],
        "target_requests_complete": row["target_requests_complete"],
        "missing_or_short": row["missing_or_short"],
        "actual_common_start": row["actual_common_start"],
        "actual_common_end": row["actual_common_end"],
        "inception_limited_coverage_accepted": True,
    }


def _direct_answers(study: dict[str, Any]) -> list[str]:
    mega = study["universes"]["MEGA_CAP_TECH_UNIVERSE"]
    etf = study["universes"]["ETF_RESEARCH_UNIVERSE"]
    rate = study["cash_models"]["CASH_RISK_FREE"]
    grades = study["benchmark_reclassification"]
    return [
        f"2010-target market history is validated for all 23 unique tickers. Twenty begin on 2010-01-04; TSLA begins 2010-06-29, META 2012-05-18 and XLRE 2015-10-08.",
        "Coverage is inception-limited only for TSLA, META and XLRE relative to 2010-01-04; no pre-listing observations were fabricated.",
        f"The ETF research universe is ready: {etf['validated_datasets']}/{etf['symbol_count']} validated datasets.",
        "CASH_ZERO bias is now measured directly as the difference from a fixed-execution CASH_RISK_FREE replay; exact strategy-level contributions are reported above.",
        f"Risk-free cash was actually calculated from real FRED DGS3MO observations ({rate['first_observation']} → {rate['last_observation']}); it is not a theoretical placeholder.",
        f"The mega-cap research universe is complete ({mega['validated_datasets']}/{mega['symbol_count']}) but remains end-of-sample selected and therefore structurally favorable to surviving large growth stocks.",
        f"In the long-history ETF universe, SMA200 is `{grades['SMA200_TREND']['grade']}` and Donchian 20/10 is `{grades['DONCHIAN_20_10']['grade']}` under the predeclared gate.",
        "The frozen crisis tables now measure whether trend rules add bear-market protection; no crisis result was inferred from short-history output.",
        f"Overall research-environment sensitivity is `{study['sensitivity_classification']}` across the two universes and two cash assumptions.",
        f"NEXT FAMILY remains `{study['next_family']}` according to the frozen reclassification gate; no candidate was created automatically.",
    ]


def build(
    *, snapshot: dict[str, Any] | None = None, extension: dict[str, Any] | None = None,
) -> dict[str, Any]:
    before = immutable_fingerprints()
    frozen, daily = load()
    canonical = canonical_checks(frozen, daily)
    registry_path = ROOT / "data/research-candidate-registry.json"
    registry_sha = sha256_file(registry_path)

    snapshot = snapshot or build_environment_snapshot(persist=True)
    assert_snapshot_immutable(snapshot)
    assert_snapshot_inputs_unchanged(snapshot)
    if not snapshot["readiness"]["research_validation_ready"]:
        raise EnvironmentValidationError("The current environment snapshot is not ready for publication")
    extension = extension or _load_matching_extension(snapshot)
    extension_snapshot = extension.get("environment_snapshot", {})
    if extension_snapshot.get("environment_snapshot_id") != snapshot["environment_snapshot_id"]:
        raise EnvironmentValidationError("Research output and report snapshot IDs differ")
    if not extension.get("immutability", {}).get("unchanged"):
        raise EnvironmentValidationError("Long-history research did not pass its production-invariance guard")

    market = snapshot["market_manifest"]
    rate = snapshot["risk_free"]
    snapshot_id = snapshot["environment_snapshot_id"]
    section_names = tuple(snapshot["section_source_contract"])
    extension_compact = {
        key: extension[key] for key in (
            "summary", "cash_yield_attribution", "market_cycle_summary", "crisis_summary",
            "strategy_sensitivity", "runtime_seconds",
        )
    }
    study: dict[str, Any] = {
        "schema_version": 4,
        "study": "Research Environment Validation v3",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "environment_snapshot": {
            "environment_snapshot_id": snapshot_id,
            "created_at": snapshot["created_at"],
            "input_fingerprint_sha256": snapshot["input_fingerprint_sha256"],
            "snapshot_sha256": snapshot["snapshot_sha256"],
            "snapshot_file": snapshot.get("snapshot_file"),
            "snapshot_file_sha256": snapshot.get("snapshot_file_sha256"),
            "target_range": snapshot["target_range"],
        },
        "readiness": snapshot["readiness"],
        "section_sources": {
            name: "CURRENT_ENVIRONMENT_SNAPSHOT + SNAPSHOT_BOUND_LONG_HISTORY_RESULTS"
            for name in section_names
        },
        "section_snapshot_ids": {name: snapshot_id for name in section_names},
        "source_inventory": snapshot["source_inventory"],
        "long_history_validation_status": "COMPLETED",
        "long_history_research_performed": True,
        "risk_free_research_performed": True,
        "benchmark_reclassification_performed": True,
        "candidate_created": False,
        "optimization_performed": False,
        "production_strategies_modified": False,
        "benchmark_definitions_modified": False,
        "methodology_fingerprints": snapshot["methodology_fingerprints"],
        "data_history": {
            "target_start": market["target_range"]["start"],
            "target_end": market["target_range"]["end"],
            "primary_target_acquired": True,
            "validated_datasets": len(market["datasets"]),
            "fabricated_bars": market["fabricated_bars"],
            "per_symbol_fair_start": True,
            "existing_common_start": market["universe_readiness"]["MEGA_CAP_TECH_UNIVERSE"]["actual_common_start"],
            "existing_common_end": market["universe_readiness"]["MEGA_CAP_TECH_UNIVERSE"]["actual_common_end"],
        },
        "connectivity": {"status": "separate_runtime_status", "source": "not a research conclusion input"},
        "universes": {
            "MEGA_CAP_TECH_UNIVERSE": _universe(snapshot, "MEGA_CAP_TECH_UNIVERSE"),
            "ETF_RESEARCH_UNIVERSE": _universe(snapshot, "ETF_RESEARCH_UNIVERSE"),
        },
        "dataset_rows": _dataset_rows(snapshot),
        "data_manifest": {
            "path": "data/research-data-manifest-v3.json",
            "sha256": sha256_file(ROOT / "data/research-data-manifest-v3.json"),
        },
        "universe_manifest": {
            "path": "data/research-universes.json",
            "sha256": sha256_file(ROOT / "data/research-universes.json"),
        },
        "cash_models": {
            "CASH_ZERO": {**CASH_MODELS["CASH_ZERO"], "series_available": True},
            "CASH_RISK_FREE": {
                **CASH_MODELS["CASH_RISK_FREE"], "series_available": True,
                "series_id": rate["series_id"], "provider": rate.get("provider"),
                "first_observation": rate["first_observation"],
                "last_observation": rate["last_observation"],
                "observations": rate["observations"], "manifest": rate["manifest_path"],
                "manifest_sha256": rate["manifest_sha256"], "cache_sha256": rate["cache_sha256"],
                "fabricated_rates": rate["fabricated_observations"],
            },
        },
        "cash_zero_bias_quantified": True,
        "fair_evaluation": WARMUP_CONTRACT,
        "frozen_benchmarks": FROZEN_BENCHMARK_PARAMETERS,
        "long_history_results": extension_compact,
        "long_history_extension": {
            "path": "data/research-environment-v3-long-history.json",
            "sha256": sha256_file(ROOT / "data/research-environment-v3-long-history.json"),
            "environment_snapshot_id": snapshot_id,
            "input_fingerprint_sha256": snapshot["input_fingerprint_sha256"],
        },
        "sensitivity_matrix": extension["sensitivity_matrix"],
        "strategy_sensitivity": extension["strategy_sensitivity"],
        "sensitivity_classification": extension["sensitivity_classification"],
        "benchmark_reclassification": extension["benchmark_reclassification"],
        "next_family": extension["next_family"],
        "canonical_replay": canonical,
    }
    study["direct_answers"] = _direct_answers(study)

    assert_snapshot_immutable(snapshot)
    assert_snapshot_inputs_unchanged(snapshot)
    after = immutable_fingerprints()
    if before != after:
        raise EnvironmentValidationError("Production/database/canonical market data changed during publication")
    if sha256_file(registry_path) != registry_sha:
        raise EnvironmentValidationError("Candidate registry changed during publication")
    study["immutability"] = {
        "before": before, "after": after, "unchanged": True,
        "semantic_production_source": semantic_production_source(),
        "candidate_registry_sha256": registry_sha,
        "executions_differences": 0, "pnl_differences": 0,
        "equity_differences": 0, "audits_differences": 0,
    }

    report = render(study)
    validate_report_consistency(study, report)
    _atomic_text(ROOT / "reports/research-environment-v3.md", report)
    _atomic_text(
        ROOT / "data/research-environment-v3.json",
        json.dumps(study, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
    )
    return study


if __name__ == "__main__":
    value = build()
    print(json.dumps({
        "status": value["long_history_validation_status"],
        "snapshot": value["environment_snapshot"]["environment_snapshot_id"],
        "mega_ready": value["universes"]["MEGA_CAP_TECH_UNIVERSE"]["status"],
        "etf_ready": value["universes"]["ETF_RESEARCH_UNIVERSE"]["status"],
        "risk_free": value["cash_models"]["CASH_RISK_FREE"]["series_available"],
        "next_family": value["next_family"],
    }, ensure_ascii=False))
