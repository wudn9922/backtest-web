from __future__ import annotations

"""Generate the source-derived MA_BREAKOUT_ANALYTICS_V1 traceability matrix."""

import ast
import json
from pathlib import Path

try:
    from .ma_breakout_analytics_requirement_bindings import MA_BREAKOUT_ANALYTICS_REQUIREMENT_BINDINGS
    from .ma_breakout_analytics_traceability_support import REPO_ROOT, source_requirement_records
except ImportError:  # pragma: no cover - direct script invocation
    from ma_breakout_analytics_requirement_bindings import MA_BREAKOUT_ANALYTICS_REQUIREMENT_BINDINGS
    from ma_breakout_analytics_traceability_support import REPO_ROOT, source_requirement_records


OUTPUT = REPO_ROOT / "research" / "specs" / "MA_BREAKOUT_ANALYTICS_V1_TEST_TRACEABILITY_REV3.json"
TEST_ROOT = REPO_ROOT / "backend" / "tests"


def _assert_counts(bindings: tuple[str, ...]) -> int:
    count = 0
    cache: dict[Path, ast.Module] = {}
    for nodeid in bindings:
        path_text, function_name = nodeid.split("::", 1)
        path = TEST_ROOT / Path(path_text).name
        module = cache.setdefault(path, ast.parse(path.read_text(encoding="utf-8")))
        function = next((node for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and node.name == function_name), None)
        if function is None:
            continue
        count += sum(isinstance(node, ast.Assert) for node in ast.walk(function))
    return count


def build() -> dict:
    requirements = source_requirement_records()
    for row in requirements:
        binding = MA_BREAKOUT_ANALYTICS_REQUIREMENT_BINDINGS.get(row["requirement_id"], ())
        if row["status"] == "SUPERSEDED_BY_REV3":
            row.update({
                "coverage_status": "SUPERSEDED_BY_REV3",
                "verification_kind": "SPEC_REVISION",
                "binding_id": None,
                "test_bindings": [],
                "test_file": None,
                "test_function": None,
                "assertion_summary": "Historical test item is superseded by the linked later frozen requirement; not counted as active coverage.",
            })
            continue
        row["coverage_status"] = "MISSING" if not binding else ("DIRECT" if len(binding) == 1 else "COMBINED_DIRECT")
        row["verification_kind"] = "EXECUTION_BEHAVIOR"
        row["binding_id"] = f"pytest:{row['requirement_id']}"
        row["test_bindings"] = list(binding)
        first_file, first_function = binding[0].split("::", 1) if binding else (None, None)
        row["test_file"] = first_file
        row["test_function"] = first_function
        row["assertion_summary"] = (
            f"Independent binding: {', '.join(binding)}; AST assert count={_assert_counts(binding)} (syntax sanity only)."
            if binding else "No independent collected-test binding is registered."
        )

    active = [row for row in requirements if row["status"] == "ACTIVE"]
    superseded = [row for row in requirements if row["status"] == "SUPERSEDED_BY_REV3"]
    counts = {
        "DIRECT": sum(row["coverage_status"] == "DIRECT" for row in active),
        "COMBINED_DIRECT": sum(row["coverage_status"] == "COMBINED_DIRECT" for row in active),
        "MISSING": sum(row["coverage_status"] == "MISSING" for row in active),
    }
    return {
        "strategy_revision": "MA_BREAKOUT_ANALYTICS_V1",
        "traceability_revision": 3,
        "source_authority": "FROZEN_SOL_OUTPUTS_ONLY",
        "source_fingerprints": {
            "master": {
                "path": "MA_BREAKOUT_ANALYTICS_V1_REVISION_2_SOL_FROZEN_OUTPUT.txt",
                "raw_bytes": 21855,
                "raw_sha256": "f01a50e304db4e654c57a0cfb560dc98ddc0a34aa478cd6248aa498f6434c69d",
                "normalized_bytes": 20862,
                "normalized_sha256": "d5d08500af89fce61c33c9004af23f4656bb677be10462a32c8a26641eaf66ec",
            },
            "revision_3": {
                "path": "MA_BREAKOUT_ANALYTICS_V1_REVISION_3_SOL_FROZEN_AMENDMENT.txt",
                "raw_bytes": 10759,
                "raw_sha256": "a1b80bfd9db2b4d6d1d252d050573eaf4bf40e535d698d2fee7fda38bf3b4448",
                "normalized_bytes": 10270,
                "normalized_sha256": "80c913dd26cb0adef57e259a4660da48bb681406e0ec25cfa947ebebdae485f1",
            },
        },
        "requirement_counts": {
            "master_test_matrix": 72,
            "rev3_impacted_test_requirements": 7,
            "rev3_direct_test_matrix": 38,
            "total_source_requirements": len(requirements),
            "active": len(active),
            "superseded_by_rev3": len(superseded),
        },
        "active_coverage_counts": counts,
        "requirements": requirements,
    }


if __name__ == "__main__":
    payload = build()
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8", newline="\n")
    print(json.dumps({"path": str(OUTPUT), **payload["requirement_counts"],
                      "active_coverage_counts": payload["active_coverage_counts"]},
                     ensure_ascii=False, sort_keys=True))
