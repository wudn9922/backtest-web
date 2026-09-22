from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from ma_box_requirement_bindings import BACKEND_REQUIREMENT_BINDINGS, HIGH_RISK_REQUIREMENT_BINDINGS
from ma_box_traceability_sources import EXPECTED_SOURCE_FINGERPRINTS, all_frozen_matrix_records


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _spec_root() -> Path:
    return _root() / "research" / "specs"


def _trace_payload() -> dict:
    return json.loads((_spec_root() / "MA_BOX_LONG_V1_TEST_TRACEABILITY_REV3.json").read_text(encoding="utf-8"))


def _python_test_functions(path: Path) -> dict[str, ast.AST]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    }


def _has_real_assertion(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            return True
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            if child.func.attr in {
                "raises", "assert_", "assert_equal", "assert_allclose", "assert_array_equal",
                "assert_called_once", "assert_called_once_with", "assert_has_calls",
            }:
                return True
    return False


def _is_skipped_or_xfailed(node: ast.AST) -> bool:
    """Reject bindings that point at a test disabled by a decorator."""
    for decorator in getattr(node, "decorator_list", []):
        rendered = ast.unparse(decorator).lower()
        if "skip" in rendered or "xfail" in rendered:
            return True
    return False


def _collected_backend_nodes() -> set[str]:
    """Ask pytest itself which backend nodes are collectable."""
    backend = _root() / "backend"
    files = [
        "tests/test_ma_box_long.py",
        "tests/test_ma_box_long_revision2.py",
        "tests/test_ma_box_long_revision3.py",
        "tests/test_ma_box_traceability.py",
        "tests/test_engine_integration.py",
        "tests/test_strategy_rules.py",
        "tests/test_advanced_day1_stop.py",
    ]
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *files],
        cwd=backend, text=True, capture_output=True, check=True,
    )
    nodes: set[str] = set()
    for line in completed.stdout.splitlines():
        line = line.strip().replace("\\", "/")
        if "::test_" not in line:
            continue
        node = line.split(" ", 1)[0].split("[", 1)[0]
        if node.startswith("tests/"):
            node = "backend/" + node
        nodes.add(node)
    return nodes


def _frontend_test_titles() -> set[str]:
    source = (_root() / "frontend" / "tests" / "ma-box.test.mjs").read_text(encoding="utf-8")
    return set(re.findall(r'test\(("(?:[^"\\]|\\.)*")\s*,', source))


def _assert_binding_collected(node_id: str, collected: set[str]) -> None:
    path, function = node_id.split("::", 1)
    if path.startswith("backend/"):
        normalized = path.replace("\\", "/") + "::" + function
        assert normalized in collected, f"backend test was not collected: {node_id}"
        return
    if path.startswith("frontend/"):
        assert function in {_decode_frontend_title(x) for x in _frontend_test_titles()}, node_id
        return
    raise AssertionError(f"unsupported binding namespace: {node_id}")


def _decode_frontend_title(value: str) -> str:
    return json.loads(value)


def test_revision3_traceability_has_truthful_source_matrix_and_independent_bindings():
    payload = _trace_payload()
    requirements = payload["requirements"]
    expected = all_frozen_matrix_records()
    assert payload["strategy_revision"] == "MA_BOX_LONG_V1"
    assert payload["spec_revision"] == 3
    assert payload["binding_mode"] == "INDEPENDENT_EXPLICIT_REGISTRATION"
    assert payload["source_matrix_counts"] == {
        "MASTER_SPEC": 47,
        "REVISION_2_AMENDMENT": 21,
        "REVISION_3_AMENDMENT": 9,
    }
    assert len(requirements) == len(expected) == 77
    assert [item["requirement_id"] for item in requirements] == [item[0] for item in expected]
    collected = _collected_backend_nodes()
    required_fields = {
        "requirement_id", "source_spec", "source_section", "source_test_number", "source_text_verbatim",
        "test_file", "test_function", "test_name", "coverage_status", "verification_kind",
        "assertion_summary", "binding_id", "bound_tests",
    }
    for item, (requirement_id, source_spec, source_number, source_text) in zip(requirements, expected, strict=True):
        assert required_fields <= set(item), requirement_id
        assert item["requirement_id"] == requirement_id
        assert item["source_spec"] == source_spec
        assert item["source_test_number"] == source_number
        assert item["source_text_verbatim"] == source_text
        assert item["coverage_status"] in {"DIRECT", "COMBINED_DIRECT"}
        registered = HIGH_RISK_REQUIREMENT_BINDINGS.get(requirement_id, BACKEND_REQUIREMENT_BINDINGS[requirement_id])
        assert set(item["bound_tests"]) == set(registered)
        assert item["binding_id"] == f"B-{requirement_id}"
        assert item["test_file"] == item["bound_tests"][0].split("::", 1)[0]
        assert item["test_function"] == item["bound_tests"][0].split("::", 1)[1]
        for node_id in item["bound_tests"]:
            _assert_binding_collected(node_id, collected)
        if item["test_file"].startswith("backend/"):
            function = _python_test_functions(_root() / item["test_file"])[item["test_function"]]
            assert not _is_skipped_or_xfailed(function), f"bound test is skipped/xfail: {requirement_id}"
            assert _has_real_assertion(function), requirement_id


def test_revision3_traceability_matrix_is_one_to_one_and_has_no_orphan_ids():
    payload = _trace_payload()
    ids = [item["requirement_id"] for item in payload["requirements"]]
    assert len(ids) == len(set(ids))
    expected_ids = [item[0] for item in all_frozen_matrix_records()]
    assert ids == expected_ids
    assert set(BACKEND_REQUIREMENT_BINDINGS) == set(expected_ids)
    assert set(HIGH_RISK_REQUIREMENT_BINDINGS) <= set(expected_ids)


def test_revision3_traceability_verifies_authoritative_source_fingerprints_and_verbatim_sections():
    root = _spec_root()
    master = (root / "MA_BOX_LONG_V1_MASTER_SOL_FROZEN_RESPONSE.md").read_bytes()
    rev2 = (root / "MA_BOX_LONG_V1_REVISION_2_SOL_FROZEN_RESPONSE.md").read_bytes()
    rev3 = (root / "MA_BOX_LONG_V1_REVISION_3_AMENDMENT_SOURCE.md").read_bytes()
    # Keep these literals in the direct regression rather than reading the
    # manifest or a mutable helper constant.  Modifying a source file,
    # manifest, artifact and sidecar together must still fail this assertion.
    assert (len(master), hashlib.sha256(master).hexdigest()) == (
        24208, "b6013c9ad8b1cc356fa01a211d653e39772d8ca6c822d2cee2d1e4e53d8f61e6"
    )
    assert (len(rev2), hashlib.sha256(rev2).hexdigest()) == (
        10670, "048c74b53add3a4fb56bace363a025f9ed3cce49e01d7426f6ffaaba16277d5c"
    )
    assert (len(rev3), hashlib.sha256(rev3).hexdigest()) == (
        24937, "6eedcf3e759a452fe704a5c5675d14b3b02842d09f6e1c73e81db86d088859fa"
    )
    expected = (
        "# MA_BOX_LONG_V1 — Frozen Specification Revision 3\n\n"
        "## SECTION A — MA_BOX_LONG_V1 MASTER SPEC\n\n" + master.decode("utf-8") + "\n"
        "## SECTION B — MA_BOX_LONG_V1 SPEC AMENDMENT — FROZEN REVISION 2\n\n" + rev2.decode("utf-8") + "\n"
        "## SECTION C — REVISION 3 AMENDMENT\n\n" + rev3.decode("utf-8")
    ).encode("utf-8")
    artifact = (root / "MA_BOX_LONG_V1_REVISION_3.md").read_bytes()
    assert artifact == expected
    digest = hashlib.sha256(artifact).hexdigest()
    sidecar = (root / "MA_BOX_LONG_V1_REVISION_3.sha256").read_text(encoding="utf-8")
    assert f"sha256={digest}" in sidecar
    manifest = json.loads((root / "MA_BOX_LONG_V1_REVISION_3_SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["master"]["normalized_bytes"] == len(master)
    assert manifest["master"]["normalized_sha256"] == hashlib.sha256(master).hexdigest()
    assert manifest["revision2"]["normalized_bytes"] == len(rev2)
    assert manifest["revision2"]["normalized_sha256"] == hashlib.sha256(rev2).hexdigest()
    assert manifest["revision3"]["normalized_bytes"] == len(rev3)
    assert manifest["revision3"]["normalized_sha256"] == hashlib.sha256(rev3).hexdigest()
    assert manifest["combined_artifact"]["sha256"] == digest
