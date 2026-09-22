from __future__ import annotations

import json

from tests.ma_breakout_analytics_requirement_bindings import MA_BREAKOUT_ANALYTICS_REQUIREMENT_BINDINGS
from tests.ma_breakout_analytics_traceability_support import source_requirement_records
from tests.validate_ma_breakout_analytics_traceability import MATRIX_PATH, validate_traceability


def _matrix() -> dict:
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


def _collected() -> dict[str, set[str]]:
    return {
        nodeid.split("[", 1)[0]: set()
        for nodeids in MA_BREAKOUT_ANALYTICS_REQUIREMENT_BINDINGS.values()
        for nodeid in nodeids
    }


def test_traceability_source_rows_are_exact_and_registry_is_independent():
    matrix = _matrix()
    source_rows = source_requirement_records()
    assert [row["requirement_id"] for row in matrix["requirements"]] == [row["requirement_id"] for row in source_rows]
    assert all(actual["source_text_verbatim"] == expected["source_text_verbatim"]
               for actual, expected in zip(matrix["requirements"], source_rows, strict=True))
    assert set(MA_BREAKOUT_ANALYTICS_REQUIREMENT_BINDINGS) == {row["requirement_id"] for row in source_rows}
    assert matrix["requirement_counts"]["total_source_requirements"] == 117
    assert matrix["requirement_counts"]["superseded_by_rev3"] == 1


def test_traceability_validator_rejects_fabricated_requirement_id():
    matrix = _matrix()
    matrix["requirements"].append({"requirement_id": "FABRICATED-999"})
    assert any("IDs/order" in message for message in validate_traceability(
        matrix, MA_BREAKOUT_ANALYTICS_REQUIREMENT_BINDINGS, _collected()))


def test_traceability_validator_rejects_paraphrased_source_text():
    matrix = _matrix()
    matrix["requirements"][0]["source_text_verbatim"] = "paraphrased instead of frozen source"
    assert any("source_text_verbatim" in message for message in validate_traceability(
        matrix, MA_BREAKOUT_ANALYTICS_REQUIREMENT_BINDINGS, _collected()))


def test_traceability_validator_rejects_forged_source_fingerprint():
    matrix = _matrix()
    matrix["source_fingerprints"]["revision_3"]["raw_sha256"] = "0" * 64
    assert any("source_fingerprints" in message for message in validate_traceability(
        matrix, MA_BREAKOUT_ANALYTICS_REQUIREMENT_BINDINGS, _collected()))


def test_traceability_validator_rejects_json_only_binding():
    matrix = _matrix()
    requirement_id = "REV2-TEST-001"
    registry = dict(MA_BREAKOUT_ANALYTICS_REQUIREMENT_BINDINGS)
    registry.pop(requirement_id)
    assert any(requirement_id in message for message in validate_traceability(matrix, registry, _collected()))


def test_traceability_validator_rejects_uncollected_bound_test():
    matrix = _matrix()
    collected = _collected()
    nodeid = MA_BREAKOUT_ANALYTICS_REQUIREMENT_BINDINGS["REV2-TEST-001"][0]
    collected.pop(nodeid.split("[", 1)[0])
    assert any("not collected" in message for message in validate_traceability(
        matrix, MA_BREAKOUT_ANALYTICS_REQUIREMENT_BINDINGS, collected))


def test_traceability_validator_rejects_skip_and_xfail_bindings():
    matrix = _matrix()
    collected = _collected()
    nodeid = MA_BREAKOUT_ANALYTICS_REQUIREMENT_BINDINGS["REV2-TEST-001"][0]
    collected[nodeid.split("[", 1)[0]] = {"skip"}
    assert any("skip/xfail" in message for message in validate_traceability(
        matrix, MA_BREAKOUT_ANALYTICS_REQUIREMENT_BINDINGS, collected))
    collected[nodeid.split("[", 1)[0]] = {"xfail"}
    assert any("skip/xfail" in message for message in validate_traceability(
        matrix, MA_BREAKOUT_ANALYTICS_REQUIREMENT_BINDINGS, collected))
