from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_DIR = REPO_ROOT / "research" / "specs"
MASTER_PATH = SPEC_DIR / "MA_BREAKOUT_ANALYTICS_V1_REVISION_2_SOL_FROZEN_OUTPUT.txt"
REV3_PATH = SPEC_DIR / "MA_BREAKOUT_ANALYTICS_V1_REVISION_3_SOL_FROZEN_AMENDMENT.txt"
MASTER_RAW_BYTES = 21855
MASTER_RAW_SHA256 = "f01a50e304db4e654c57a0cfb560dc98ddc0a34aa478cd6248aa498f6434c69d"
MASTER_NORMALIZED_BYTES = 20862
MASTER_NORMALIZED_SHA256 = "d5d08500af89fce61c33c9004af23f4656bb677be10462a32c8a26641eaf66ec"
REV3_RAW_BYTES = 10759
REV3_RAW_SHA256 = "a1b80bfd9db2b4d6d1d252d050573eaf4bf40e535d698d2fee7fda38bf3b4448"
REV3_NORMALIZED_BYTES = 10270
REV3_NORMALIZED_SHA256 = "80c913dd26cb0adef57e259a4660da48bb681406e0ec25cfa947ebebdae485f1"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_source(raw: bytes) -> bytes:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("Frozen source must be UTF-8 without BOM")
    return raw.decode("utf-8", errors="strict").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def authoritative_sources() -> dict[str, dict[str, Any]]:
    entries = {
        "REV2_MASTER": (MASTER_PATH, MASTER_RAW_BYTES, MASTER_RAW_SHA256,
                        MASTER_NORMALIZED_BYTES, MASTER_NORMALIZED_SHA256),
        "REV3_AMENDMENT": (REV3_PATH, REV3_RAW_BYTES, REV3_RAW_SHA256,
                           REV3_NORMALIZED_BYTES, REV3_NORMALIZED_SHA256),
    }
    result: dict[str, dict[str, Any]] = {}
    for key, (path, raw_size, raw_hash, normalized_size, normalized_hash) in entries.items():
        raw = path.read_bytes()
        normalized = normalize_source(raw)
        actual = (len(raw), sha256(raw), len(normalized), sha256(normalized))
        expected = (raw_size, raw_hash, normalized_size, normalized_hash)
        if actual != expected:
            raise ValueError(f"Frozen source identity mismatch for {key}: {actual!r}")
        result[key] = {"path": path, "raw": raw, "normalized": normalized,
                       "raw_bytes": raw_size, "raw_sha256": raw_hash,
                       "normalized_bytes": normalized_size, "normalized_sha256": normalized_hash}
    return result


def extract_master_test_matrix(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    start = lines.index("## 27. Test matrix")
    end = lines.index("## 28. Remaining ambiguities")
    matrix_lines = lines[start + 1:end]
    first_label = matrix_lines.index("原始51項全部保留：")
    amendment_label = matrix_lines.index("新增本次凍結決策的direct tests：")
    old_rows = matrix_lines[first_label + 1:amendment_label]
    new_rows = matrix_lines[amendment_label + 1:]
    new_rows = new_rows[:next((index for index, line in enumerate(new_rows)
                               if line.startswith("所有 correctness tests使用")), len(new_rows))]
    range_pattern = re.compile(r"^\s*(\d+)(?:[–-](\d+))?\.\s+(.+?)\s*$")
    numbered_pattern = re.compile(r"^\s*(\d+)\.\s+(.+?)\s*$")
    result: list[dict[str, Any]] = []
    for line in old_rows:
        if not line.strip():
            continue
        match = range_pattern.fullmatch(line)
        if not match:
            raise ValueError(f"Unparsed authoritative Master matrix line: {line!r}")
        first, last = int(match.group(1)), int(match.group(2) or match.group(1))
        for number in range(first, last + 1):
            result.append({"number": number, "source_text_verbatim": line,
                           "source_section": "## 27. Test matrix / 原始51項全部保留"})
    for line in new_rows:
        if not line.strip():
            continue
        match = numbered_pattern.fullmatch(line)
        if not match:
            raise ValueError(f"Unparsed authoritative Master addendum line: {line!r}")
        result.append({"number": int(match.group(1)), "source_text_verbatim": line,
                       "source_section": "## 27. Test matrix / 新增本次凍結決策的direct tests"})
    numbers = [item["number"] for item in result]
    if numbers != list(range(1, 73)):
        raise ValueError(f"Master test matrix must expand to 1..72, got {numbers!r}")
    return result


def extract_rev3_test_matrix(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lines = text.splitlines()
    start = lines.index("## 7. 受影響 test matrix")
    end = lines.index("## 8. 是否仍有 ambiguity")
    matrix_lines = lines[start + 1:end]
    impacts_label = matrix_lines.index("原有測試中以下項目必須修改：")
    direct_label = matrix_lines.index("新增direct tests：")
    impact_lines = matrix_lines[impacts_label + 1:direct_label]
    direct_lines = matrix_lines[direct_label + 1:]
    impacts = []
    for line in impact_lines:
        if not line.strip() or line.strip() == "---":
            continue
        if not line.startswith("- "):
            raise ValueError(f"Unparsed Rev3 impacted-test line: {line!r}")
        impacts.append({"number": len(impacts) + 1, "source_text_verbatim": line,
                        "source_section": "## 7. 受影響 test matrix / 原有測試中以下項目必須修改"})
    direct_pattern = re.compile(r"^\s*(\d+)\.\s+(.+?)\s*$")
    direct = []
    for line in direct_lines:
        if not line.strip() or line.strip() == "---":
            continue
        match = direct_pattern.fullmatch(line)
        if not match:
            raise ValueError(f"Unparsed Rev3 direct test line: {line!r}")
        direct.append({"number": int(match.group(1)), "source_text_verbatim": line,
                       "source_section": "## 7. 受影響 test matrix / 新增direct tests"})
    if len(impacts) != 7 or [item["number"] for item in direct] != list(range(1, 39)):
        raise ValueError(f"Unexpected Rev3 matrix shape: impacts={len(impacts)}, direct={len(direct)}")
    return impacts, direct


def source_requirement_records() -> list[dict[str, Any]]:
    sources = authoritative_sources()
    master = extract_master_test_matrix(sources["REV2_MASTER"]["normalized"].decode("utf-8"))
    impacts, direct = extract_rev3_test_matrix(sources["REV3_AMENDMENT"]["normalized"].decode("utf-8"))
    records: list[dict[str, Any]] = []
    for item in master:
        number = item["number"]
        requirement_id = f"REV2-TEST-{number:03d}"
        superseded = number == 64
        records.append({
            "requirement_id": requirement_id,
            "source_spec": "MA_BREAKOUT_ANALYTICS_V1_REVISION_2_SOL_FROZEN_OUTPUT.txt",
            "source_section": item["source_section"],
            "source_test_number": number,
            "source_text_verbatim": item["source_text_verbatim"],
            "status": "SUPERSEDED_BY_REV3" if superseded else "ACTIVE",
            "superseded_by_requirement_id": "REV3-TEST-023" if superseded else None,
        })
    for item in impacts:
        records.append({
            "requirement_id": f"REV3-CHANGE-{item['number']:02d}",
            "source_spec": "MA_BREAKOUT_ANALYTICS_V1_REVISION_3_SOL_FROZEN_AMENDMENT.txt",
            "source_section": item["source_section"],
            "source_test_number": None,
            "source_item_number": item["number"],
            "source_text_verbatim": item["source_text_verbatim"],
            "status": "ACTIVE",
            "superseded_by_requirement_id": None,
        })
    for item in direct:
        records.append({
            "requirement_id": f"REV3-TEST-{item['number']:02d}",
            "source_spec": "MA_BREAKOUT_ANALYTICS_V1_REVISION_3_SOL_FROZEN_AMENDMENT.txt",
            "source_section": item["source_section"],
            "source_test_number": item["number"],
            "source_text_verbatim": item["source_text_verbatim"],
            "status": "ACTIVE",
            "superseded_by_requirement_id": None,
        })
    return records
