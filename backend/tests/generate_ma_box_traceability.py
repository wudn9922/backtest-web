from __future__ import annotations

import json
from pathlib import Path

from ma_box_requirement_bindings import BACKEND_REQUIREMENT_BINDINGS, HIGH_RISK_REQUIREMENT_BINDINGS
from ma_box_traceability_sources import all_frozen_matrix_records


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "research" / "specs" / "MA_BOX_LONG_V1_TEST_TRACEABILITY_REV3.json"


def _display_parts(node_id: str) -> tuple[str, str]:
    path, function = node_id.split("::", 1)
    return path, function


def build_payload() -> dict:
    requirements = []
    for requirement_id, source_spec, source_number, source_text in all_frozen_matrix_records():
        bindings = list(HIGH_RISK_REQUIREMENT_BINDINGS.get(requirement_id, BACKEND_REQUIREMENT_BINDINGS.get(requirement_id, [])))
        if requirement_id == "REV3-09":
            for node_id in HIGH_RISK_REQUIREMENT_BINDINGS[requirement_id]:
                if node_id not in bindings:
                    bindings.append(node_id)
        bindings = list(dict.fromkeys(bindings))
        primary = bindings[0] if bindings else "::"
        test_file, test_function = _display_parts(primary)
        section = {
            "MASTER_SPEC": "## 19. Frozen test matrix",
            "REVISION_2_AMENDMENT": "## 3. 受影響的 Tests",
            "REVISION_3_AMENDMENT": "REVISION 3 TEST MATRIX",
        }[source_spec]
        requirements.append({
            "requirement_id": requirement_id,
            "source_spec": source_spec,
            "source_section": section,
            "source_test_number": source_number,
            "source_text_verbatim": source_text,
            "test_file": test_file,
            "test_function": test_function,
            "test_name": test_function,
            "coverage_status": "DIRECT" if len(bindings) == 1 else "COMBINED_DIRECT",
            "verification_kind": "FRONTEND_CONTRACT" if test_file.startswith("frontend/") else "EXECUTION_BEHAVIOR",
            "assertion_summary": source_text,
            "binding_id": f"B-{requirement_id}",
            "bound_tests": bindings,
        })
    return {
        "schema_version": 3,
        "strategy_revision": "MA_BOX_LONG_V1",
        "spec_revision": 3,
        "spec_artifact": "MA_BOX_LONG_V1_REVISION_3.md",
        "binding_mode": "INDEPENDENT_EXPLICIT_REGISTRATION",
        "coverage_statuses": ["DIRECT", "COMBINED_DIRECT", "MISSING"],
        "source_matrix_counts": {
            "MASTER_SPEC": sum(x[1] == "MASTER_SPEC" for x in all_frozen_matrix_records()),
            "REVISION_2_AMENDMENT": sum(x[1] == "REVISION_2_AMENDMENT" for x in all_frozen_matrix_records()),
            "REVISION_3_AMENDMENT": sum(x[1] == "REVISION_3_AMENDMENT" for x in all_frozen_matrix_records()),
        },
        "requirements": requirements,
    }


if __name__ == "__main__":
    OUTPUT.write_text(json.dumps(build_payload(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT} ({len(build_payload()['requirements'])} requirements)")

