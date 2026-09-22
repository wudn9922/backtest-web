"""Build immutable, machine-readable Research Framework v2 catalog artifacts.

This command indexes existing research and cache metadata.  It does not run a
backtest, contact a provider, or mutate history/audits.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from research import ROOT
from research.framework_v2 import (
    BASELINE_STATUS, BENCHMARKS, CANDIDATE_PROTOCOL, COST_STRESS,
    DAILY_POLICIES, EXECUTION_ASSUMPTIONS, PREFERRED_DATA_RANGE,
    TIME_ROBUSTNESS, UNIVERSE, VIABILITY_GATE, WINNER_CONCENTRATION,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def canonical_rows() -> dict[str, dict]:
    ids = {
        "SIMPLE_V2": "c7ccad72-5f93-4bfc-b7d4-3635138c6f75",
        "ADVANCED_V2": "f341e6a5-f7d4-4e72-b6a1-18ba09f71974",
    }
    rows = {}
    with sqlite3.connect(ROOT / "data/backtests.sqlite3") as db:
        for key, identifier in ids.items():
            row = db.execute(
                "SELECT created_at,parameters_json,result_json FROM backtests WHERE id=?", (identifier,)
            ).fetchone()
            if not row:
                raise RuntimeError(f"Missing frozen baseline {key}: {identifier}")
            created, request_json, result_json = row
            request, result = json.loads(request_json), json.loads(result_json)
            rows[key] = {
                "backtest_id": identifier,
                "created_at": created,
                "parameters": request,
                "result_sha256": hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                "execution_count": len(result.get("executions", [])),
                "position_count": len(result.get("positions", [])),
                "equity_points": len(result.get("equity_curve", [])),
            }
    return rows


def build() -> dict:
    data_dir, report_dir = ROOT / "data", ROOT / "reports"
    canonical = canonical_rows()
    current_environment_path = data_dir / "research-environment-v3.json"
    current_environment = (
        json.loads(current_environment_path.read_text(encoding="utf-8"))
        if current_environment_path.is_file() else None
    )
    specs = {
        "SIMPLE_V2": ROOT / "research/specs/SIMPLE_V2_FROZEN_BASELINE.md",
        "ADVANCED_V2": ROOT / "research/specs/ADVANCED_V2_FROZEN_BASELINE.md",
        "M3": ROOT / "research/specs/M3_FROZEN_RESEARCH_BASELINE.md",
    }
    candidates = []
    for key in ("SIMPLE_V2", "ADVANCED_V2"):
        base = canonical[key]
        candidates.append({
            "candidate_id": key,
            "family": "MA_BREAKOUT",
            "created_at": base["created_at"],
            "hypothesis": "Frozen historical baseline; see the immutable specification.",
            "spec_path": str(specs[key].relative_to(ROOT)).replace("\\", "/"),
            "spec_sha256": sha(specs[key]),
            "parameters": base["parameters"],
            "data_universe": list(UNIVERSE),
            "lifecycle_status": "TESTED",
            "research_status": "REJECTED",
            "role": "RESEARCH_BASELINE",
            "deployment_status": "NOT_VALIDATED_FOR_FORWARD_DEPLOYMENT",
            "production_selector_value": base["parameters"]["strategy"],
            "canonical": base,
        })
    candidates.append({
        "candidate_id": "M3",
        "family": "ADVANCED_BREAK_PROTECTION_ABLATION",
        "created_at": "2026-09-04T00:00:00+08:00",
        "hypothesis": "Suppressing the BreakDayLow full exit might reduce false-breakdown exits.",
        "spec_path": str(specs["M3"].relative_to(ROOT)).replace("\\", "/"),
        "spec_sha256": sha(specs["M3"]),
        "parameters": canonical["ADVANCED_V2"]["parameters"],
        "data_universe": list(UNIVERSE),
        "lifecycle_status": "TESTED",
        "research_status": "REJECTED",
        "role": "FROZEN_RESEARCH_BASELINE",
        "deployment_status": "NEVER_PROMOTED_TO_PRODUCTION",
        "production_selector_value": None,
    })
    registry = {
        "schema_version": 2,
        "append_only": True,
        "allowed_statuses": CANDIDATE_PROTOCOL["statuses"],
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    dump(data_dir / "research-candidate-registry.json", registry)

    studies = [
        ("simple-viability", "Simple v2 策略可行性", "simple-v2-strategy-viability.md", "NOT SUPPORTED"),
        ("advanced-ablation", "Advanced v2 規則拆解", "advanced-v2-ablation.md", "Completed research decomposition"),
        ("first-tp-decomposition", "First TP family 拆解", "first-tp-family-decomposition.md", "Completed research decomposition"),
        ("m3-evidence-gate", "M3 證據門檻", "pre-v3-evidence-gate.md", "M3 advanced to retrospective validation only"),
        ("m3-walk-forward", "M3 回溯式 Walk-Forward", "m3-retrospective-walk-forward.md", "NOT SUPPORTED"),
        ("benchmark-viability", "固定 Benchmark 可行性研究", "benchmark-viability-study.md", "SMA200: NOT SUPPORTED; Donchian 20/10: NOT SUPPORTED; NEXT FAMILY = NONE"),
        (
            "research-environment-v3", "研究環境驗證 v3", "research-environment-v3.md",
            (
                f"{current_environment['long_history_validation_status']}; "
                f"SMA200: {current_environment['benchmark_reclassification']['SMA200_TREND']['grade']}; "
                f"Donchian 20/10: {current_environment['benchmark_reclassification']['DONCHIAN_20_10']['grade']}; "
                f"NEXT FAMILY = {current_environment['next_family']}"
            ) if current_environment else "Environment result unavailable",
        ),
    ]
    long_history_report = report_dir / "research-environment-v3-long-history.md"
    if long_history_report.is_file():
        studies.append((
            "research-environment-v3-long-history",
            "研究環境長期驗證",
            long_history_report.name,
            "Completed retrospective long-history environment validation",
        ))
    history = {"schema_version": 2, "recalculated": False, "studies": []}
    for identifier, title, filename, conclusion in studies:
        path = report_dir / filename
        history["studies"].append({
            "report_id": identifier, "title": title, "report_file": filename,
            "report_sha256": sha(path), "conclusion": conclusion,
        })
    dump(data_dir / "research-history-index.json", history)

    inputs = json.loads((data_dir / "first-tp-structural-inputs.json").read_text(encoding="utf-8"))
    provenance_rows = []
    for item in inputs["symbols"]:
        provenance_rows.append({
            "ticker": item["symbol"], "provider": item["provider"],
            "adjustment_mode": item["adjustment_mode"],
            "adjustment_contract": item["actual_adjustment_contract"],
            "first_date": item["first_date"], "last_date": item["last_date"],
            "bars": item["bars"],
            "download_timestamp": item["cache_metadata"][0]["last_updated"],
            "ohlcv_sha256": item["ohlcv_sha256"],
            "cache_files": [
                {"path": path, "sha256": digest} for path, digest in item["file_sha256"].items()
            ],
            "preferred_start_available": item["first_date"] <= PREFERRED_DATA_RANGE["start"],
            "coverage_status": "COMPLETE" if item["first_date"] <= PREFERRED_DATA_RANGE["start"] else "LIMITED_CACHE_COVERAGE",
        })
    provenance = {
        "schema_version": 2,
        "preferred_range": PREFERRED_DATA_RANGE,
        "actual_common_range": {
            "start": max(row["first_date"] for row in provenance_rows),
            "end": min(row["last_date"] for row in provenance_rows),
        },
        "network_fetch_performed": False,
        "coverage_note": "Existing safe cache starts in 2020. Earlier 2010 coverage was not fabricated; refresh when a provider is reachable with the same adjustment contract.",
        "fingerprint_rule": "A research report must persist every row below; any changed checksum is a distinct dataset fingerprint.",
        "datasets": provenance_rows,
    }
    if current_environment and current_environment.get("dataset_rows"):
        provenance_rows = [{
            "ticker": row["ticker"], "provider": row["provider"],
            "adjustment_mode": row["adjustment_mode"],
            "adjustment_contract": row.get("adjustment_contract"),
            "first_date": row["first_date"], "last_date": row["last_date"],
            "bars": row["bars"], "download_timestamp": row.get("download_timestamp"),
            "ohlcv_sha256": row["ohlcv_sha256"],
            "cache_files": row.get("cache_fragments", []),
            "preferred_start_available": bool(row["target_range_was_requested"]),
            "coverage_status": "COMPLETE" if row["target_range_was_requested"] else "LIMITED_CACHE_COVERAGE",
        } for row in current_environment["dataset_rows"]]
        provenance = {
            "schema_version": 3,
            "preferred_range": {
                "start": current_environment["data_history"]["target_start"],
                "end": current_environment["data_history"]["target_end"],
            },
            "actual_common_range": {
                "start": max(row["first_date"] for row in provenance_rows),
                "end": min(row["last_date"] for row in provenance_rows),
            },
            "network_fetch_performed": False,
            "coverage_note": "Current validated snapshot-bound long-history inputs; later listings retain real inception-limited coverage.",
            "fingerprint_rule": "A research report must persist every row below; any changed checksum is a distinct dataset fingerprint.",
            "environment_snapshot_id": current_environment["environment_snapshot"]["environment_snapshot_id"],
            "input_fingerprint_sha256": current_environment["environment_snapshot"]["input_fingerprint_sha256"],
            "datasets": provenance_rows,
        }
    dump(data_dir / "research-framework-v2-data-manifest.json", provenance)

    benchmark_path = data_dir / "benchmark-viability-study.json"
    benchmark_summary = None
    if benchmark_path.is_file():
        benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
        benchmark_summary = {
            "study": benchmark["study"], "evaluation_start": benchmark["data"]["evaluation_start"],
            "evaluation_end": benchmark["data"]["evaluation_end"], "grades": benchmark["grades"],
            "next_family": benchmark["next_family"], "full_breadth": benchmark["full_breadth"],
            "walk_forward_breadth": benchmark["walk_forward_breadth"],
            "report_id": "benchmark-viability", "candidate_created": False,
        }
    environment_summary = None
    if current_environment:
        environment = current_environment
        environment_summary = {
            "study": environment["study"],
            "status": environment["long_history_validation_status"],
            "data_history": environment["data_history"],
            "connectivity": environment["connectivity"],
            "universes": environment["universes"],
            "cash_models": environment["cash_models"],
            "data_manifest": environment["data_manifest"],
            "universe_manifest": environment["universe_manifest"],
            "sensitivity_classification": environment["sensitivity_classification"],
            "next_family": environment["next_family"],
            "report_id": "research-environment-v3",
            "candidate_created": False,
            "environment_snapshot": environment["environment_snapshot"],
            "readiness": environment["readiness"],
            "benchmark_reclassification": environment["benchmark_reclassification"],
        }
    catalog = {
        "schema_version": 2,
        "title": "Research Framework v2",
        "warning": "歷史研究未通過策略可行性門檻，不代表適合實際交易。",
        "baseline_status": BASELINE_STATUS,
        "universe": list(UNIVERSE),
        "preferred_data_range": PREFERRED_DATA_RANGE,
        "registry": registry,
        "benchmarks": BENCHMARKS,
        "execution_assumptions": EXECUTION_ASSUMPTIONS,
        "candidate_protocol": CANDIDATE_PROTOCOL,
        "viability_gate": VIABILITY_GATE,
        "winner_concentration": WINNER_CONCENTRATION,
        "cost_stress": COST_STRESS,
        "time_robustness": TIME_ROBUSTNESS,
        "provenance": provenance,
        "history": history,
        "benchmark_viability": benchmark_summary,
        "research_environment": environment_summary,
        "strategy_spec_template": "research/templates/STRATEGY_SPEC.md",
        "generated_at": datetime.now().astimezone().isoformat(),
        "no_new_candidate_created": True,
    }
    dump(data_dir / "research-framework-v2-catalog.json", catalog)
    return catalog


if __name__ == "__main__":
    value = build()
    print(json.dumps({
        "candidates": value["registry"]["candidate_count"],
        "datasets": len(value["provenance"]["datasets"]),
        "historical_studies": len(value["history"]["studies"]),
    }))
