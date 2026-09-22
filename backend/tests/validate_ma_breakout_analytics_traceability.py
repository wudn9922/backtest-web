from __future__ import annotations

"""Validate source-derived traceability against independent bindings and pytest collection."""

import ast
import json
from pathlib import Path
from typing import Any

import pytest

try:
    from .ma_breakout_analytics_requirement_bindings import MA_BREAKOUT_ANALYTICS_REQUIREMENT_BINDINGS
    from .ma_breakout_analytics_traceability_support import REPO_ROOT, authoritative_sources, source_requirement_records
except ImportError:  # pragma: no cover - direct script invocation
    from ma_breakout_analytics_requirement_bindings import MA_BREAKOUT_ANALYTICS_REQUIREMENT_BINDINGS
    from ma_breakout_analytics_traceability_support import REPO_ROOT, authoritative_sources, source_requirement_records


MATRIX_PATH = REPO_ROOT / "research" / "specs" / "MA_BREAKOUT_ANALYTICS_V1_TEST_TRACEABILITY_REV3.json"
TEST_ROOT = REPO_ROOT / "backend" / "tests"
COLLECTED_TEST_FILES = [
    "tests/test_ma_breakout_analytics.py",
    "tests/test_ma_breakout_analytics_traceability.py",
]
REQUIRED_DIRECT_BINDINGS = {
    "REV3-TEST-28": {"tests/test_ma_breakout_analytics.py::test_d2_intraday_target_and_stop_are_not_backfilled_into_post_d2_success"},
    "REV3-TEST-29": {"tests/test_ma_breakout_analytics.py::test_d2_intraday_target_and_stop_are_not_backfilled_into_post_d2_success"},
    "REV3-TEST-31": {"tests/test_ma_breakout_analytics.py::test_post_d2_success_first_dynamic_stop_uses_d2_completed_ma"},
    "REV3-TEST-32": {"tests/test_ma_breakout_analytics.py::test_post_d2_success_first_dynamic_stop_uses_d2_completed_ma"},
}
IMPLEMENTATION_DIRECT_TESTS = {
    "authoritative_artifact_identity": "tests/test_ma_breakout_analytics.py::test_spec_artifact_sidecar_identity_and_encoding",
    "targeted_sma23_period_isolation": "tests/test_ma_breakout_analytics.py::test_targeted_sma23_ma_path_mutation_cannot_change_sma24_or_25_execution_state",
    "backend_chart_overlay_payload": "tests/test_ma_breakout_analytics.py::test_backend_chart_payload_contains_authoritative_box_volume_target_and_retest_audit",
}


def _base_nodeid(nodeid: str) -> str:
    return nodeid.split("[", 1)[0]


def validate_traceability(matrix: dict[str, Any], registry: dict[str, tuple[str, ...]],
                          collected: dict[str, set[str]],
                          source_records: list[dict[str, Any]] | None = None) -> list[str]:
    """Return concrete validation errors; inputs are injectable for negative tests."""
    if not isinstance(matrix, dict):
        return ["traceability artifact is not an object"]
    expected = source_records if source_records is not None else source_requirement_records()
    errors: list[str] = []
    sources = authoritative_sources()
    expected_fingerprints = {
        "master": {
            "path": sources["REV2_MASTER"]["path"].name,
            "raw_bytes": sources["REV2_MASTER"]["raw_bytes"],
            "raw_sha256": sources["REV2_MASTER"]["raw_sha256"],
            "normalized_bytes": sources["REV2_MASTER"]["normalized_bytes"],
            "normalized_sha256": sources["REV2_MASTER"]["normalized_sha256"],
        },
        "revision_3": {
            "path": sources["REV3_AMENDMENT"]["path"].name,
            "raw_bytes": sources["REV3_AMENDMENT"]["raw_bytes"],
            "raw_sha256": sources["REV3_AMENDMENT"]["raw_sha256"],
            "normalized_bytes": sources["REV3_AMENDMENT"]["normalized_bytes"],
            "normalized_sha256": sources["REV3_AMENDMENT"]["normalized_sha256"],
        },
    }
    if matrix.get("source_fingerprints") != expected_fingerprints:
        errors.append("source_fingerprints do not match hard-verified frozen source bytes")
    rows = matrix.get("requirements") if isinstance(matrix, dict) else None
    if not isinstance(rows, list):
        return ["requirements is not a list"]
    expected_ids = [row["requirement_id"] for row in expected]
    actual_ids = [row.get("requirement_id") for row in rows]
    if actual_ids != expected_ids:
        errors.append("requirement IDs/order do not exactly match frozen source extraction")
        return errors
    if set(registry) != set(expected_ids):
        errors.append("independent pytest binding registry IDs differ from frozen requirements")

    for source_row, row in zip(expected, rows, strict=True):
        requirement_id = source_row["requirement_id"]
        for key in ("source_spec", "source_section", "source_test_number", "source_text_verbatim", "status",
                    "superseded_by_requirement_id"):
            if row.get(key) != source_row.get(key):
                errors.append(f"{requirement_id}: {key} differs from frozen source extraction")
        independent = tuple(registry.get(requirement_id, ()))
        matrix_bindings = tuple(row.get("test_bindings") or ())
        if matrix_bindings != independent:
            errors.append(f"{requirement_id}: JSON binding differs from independent registry")

        if source_row["status"] == "SUPERSEDED_BY_REV3":
            if independent or row.get("coverage_status") != "SUPERSEDED_BY_REV3":
                errors.append(f"{requirement_id}: superseded item must not claim active coverage")
            continue

        expected_status = "MISSING" if not independent else ("DIRECT" if len(independent) == 1 else "COMBINED_DIRECT")
        if row.get("coverage_status") != expected_status:
            errors.append(f"{requirement_id}: coverage status does not match independent binding count")
        if not independent:
            errors.append(f"{requirement_id}: active requirement has no independent test binding")
            continue
        if row.get("binding_id") != f"pytest:{requirement_id}":
            errors.append(f"{requirement_id}: binding_id is missing or inconsistent")
        if row.get("test_file") != independent[0].split("::", 1)[0] or row.get("test_function") != independent[0].split("::", 1)[1]:
            errors.append(f"{requirement_id}: primary test_file/test_function do not match independent binding")

        for nodeid in independent:
            base = _base_nodeid(nodeid)
            if base not in collected:
                errors.append(f"{requirement_id}: bound pytest test was not collected: {nodeid}")
                continue
            marks = collected[base]
            if "skip" in marks or "skipif" in marks or "xfail" in marks:
                errors.append(f"{requirement_id}: bound pytest test is marked skip/xfail: {nodeid}")
            path_text, function_name = base.split("::", 1)
            test_path = TEST_ROOT / Path(path_text).name
            try:
                module = ast.parse(test_path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError) as exc:
                errors.append(f"{requirement_id}: cannot parse bound test source {test_path}: {exc}")
                continue
            function = next((node for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                             and node.name == function_name), None)
            assert_count = sum(isinstance(node, ast.Assert) for node in ast.walk(function)) if function else 0
            if function is None or assert_count == 0:
                errors.append(f"{requirement_id}: bound test is missing or has no assert statement: {nodeid}")

    counts = matrix.get("requirement_counts", {})
    active = [row for row in rows if row.get("status") == "ACTIVE"]
    superseded_count = sum(row.get("status") == "SUPERSEDED_BY_REV3" for row in rows)
    expected_counts = {
        "master_test_matrix": 72,
        "rev3_impacted_test_requirements": 7,
        "rev3_direct_test_matrix": 38,
        "total_source_requirements": len(expected),
        "active": len(active),
        "superseded_by_rev3": superseded_count,
    }
    if counts != expected_counts:
        errors.append("requirement_counts do not match source-extracted matrices")
    coverage = {
        "DIRECT": sum(row.get("coverage_status") == "DIRECT" for row in active),
        "COMBINED_DIRECT": sum(row.get("coverage_status") == "COMBINED_DIRECT" for row in active),
        "MISSING": sum(row.get("coverage_status") == "MISSING" for row in active),
    }
    if matrix.get("active_coverage_counts") != coverage:
        errors.append("active coverage counts do not reconcile to requirement rows")
    if coverage["MISSING"]:
        errors.append(f"active requirements missing test coverage: {coverage['MISSING']}")

    for requirement_id, required in REQUIRED_DIRECT_BINDINGS.items():
        if set(registry.get(requirement_id, ())) != required:
            errors.append(f"high-risk direct binding is not pinned for {requirement_id}")
    for label, nodeid in IMPLEMENTATION_DIRECT_TESTS.items():
        if _base_nodeid(nodeid) not in collected:
            errors.append(f"implementation direct regression not collected: {label} -> {nodeid}")
        else:
            path_text, function_name = _base_nodeid(nodeid).split("::", 1)
            module = ast.parse((TEST_ROOT / Path(path_text).name).read_text(encoding="utf-8"))
            function = next((node for node in module.body if isinstance(node, ast.FunctionDef)
                             and node.name == function_name), None)
            if function is None or not any(isinstance(node, ast.Assert) for node in ast.walk(function)):
                errors.append(f"implementation direct regression has no assertion: {label}")
    return errors


class _PytestCollection:
    def __init__(self) -> None:
        self.items: dict[str, set[str]] = {}

    @pytest.hookimpl
    def pytest_collection_finish(self, session) -> None:
        for item in session.items:
            self.items[item.nodeid] = {mark.name for mark in item.iter_markers()}


def collect_real_pytest_items() -> tuple[int, dict[str, set[str]]]:
    collector = _PytestCollection()
    exit_code = pytest.main(["--collect-only", "-qq", *COLLECTED_TEST_FILES], plugins=[collector])
    by_base: dict[str, set[str]] = {}
    for nodeid, marks in collector.items.items():
        base = _base_nodeid(nodeid)
        by_base.setdefault(base, set()).update(marks)
    return int(exit_code), by_base


def main() -> int:
    matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    collect_exit, collected = collect_real_pytest_items()
    errors = validate_traceability(matrix, MA_BREAKOUT_ANALYTICS_REQUIREMENT_BINDINGS, collected)
    if collect_exit:
        errors.insert(0, f"pytest collection failed with exit code {collect_exit}")
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({
        "status": "PASS",
        "requirement_count": len(matrix["requirements"]),
        "active_requirement_count": matrix["requirement_counts"]["active"],
        "superseded_count": matrix["requirement_counts"]["superseded_by_rev3"],
        "coverage": matrix["active_coverage_counts"],
        "collected_test_functions": len(collected),
        "high_risk_direct_bindings": len(REQUIRED_DIRECT_BINDINGS),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
