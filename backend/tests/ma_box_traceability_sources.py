"""Extract the frozen test matrices directly from the authoritative sources.

This module deliberately performs no strategy execution.  It keeps the
traceability artifact tied to the frozen Sol responses instead of allowing a
hand-written requirement list to drift or merely match a requested count.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPECS = ROOT / "research" / "specs"
MASTER_PATH = SPECS / "MA_BOX_LONG_V1_MASTER_SOL_FROZEN_RESPONSE.md"
REV2_PATH = SPECS / "MA_BOX_LONG_V1_REVISION_2_SOL_FROZEN_RESPONSE.md"
REV3_PATH = SPECS / "MA_BOX_LONG_V1_REVISION_3_AMENDMENT_SOURCE.md"

EXPECTED_SOURCE_FINGERPRINTS = {
    "MASTER_SPEC": (24208, "b6013c9ad8b1cc356fa01a211d653e39772d8ca6c822d2cee2d1e4e53d8f61e6"),
    "REVISION_2_AMENDMENT": (10670, "048c74b53add3a4fb56bace363a025f9ed3cce49e01d7426f6ffaaba16277d5c"),
    "REVISION_3_AMENDMENT": (24937, "6eedcf3e759a452fe704a5c5675d14b3b02842d09f6e1c73e81db86d088859fa"),
}


def source_fingerprint(path: Path) -> tuple[int, str]:
    raw = path.read_bytes()
    return len(raw), hashlib.sha256(raw).hexdigest()


def _section(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    finish = text.index(end, begin)
    return text[begin:finish]


def _numbered_items(section: str) -> list[str]:
    lines = section.splitlines()
    starts = [index for index, line in enumerate(lines) if re.match(r"^\d+\.\s", line)]
    items: list[str] = []
    for offset, start in enumerate(starts):
        end = starts[offset + 1] if offset + 1 < len(starts) else len(lines)
        # Preserve source wording and code blocks while dropping only the
        # separator whitespace outside the item.  The resulting text is still
        # a verbatim contiguous source slice after the common line-ending
        # normalization used by the artifact.
        block = "\n".join(lines[start:end]).strip("\n")
        items.append(block)
    return items


def master_matrix() -> list[str]:
    text = MASTER_PATH.read_text(encoding="utf-8")
    section = _section(text, "## 19. Frozen test matrix", "## 20. Migration risks and resolutions")
    items = _numbered_items(section)
    if len(items) != 47:
        raise AssertionError(f"authoritative Master matrix changed: {len(items)}")
    return items


def revision2_matrix() -> list[str]:
    text = REV2_PATH.read_text(encoding="utf-8")
    section = _section(text, "### Formation and contacts", "## 4. 是否仍有 Ambiguity")
    items = _numbered_items(section)
    if len(items) != 21:
        raise AssertionError(f"authoritative Rev2 matrix changed: {len(items)}")
    return items


def revision3_matrix() -> list[str]:
    text = REV3_PATH.read_text(encoding="utf-8")
    section = _section(text, "REVISION 3 TEST MATRIX", "==================================================\nIMPORTANT")
    lines = section.splitlines()
    marker = lines.index("至少：")
    items = [line for line in lines[marker + 1:] if line.strip()]
    if len(items) != 9:
        raise AssertionError(f"authoritative Rev3 matrix changed: {len(items)}")
    return items


def all_frozen_matrix_records() -> list[tuple[str, str, int, str]]:
    records: list[tuple[str, str, int, str]] = []
    for index, text in enumerate(master_matrix(), 1):
        records.append((f"MASTER-{index:02d}", "MASTER_SPEC", index, text))
    for index, text in enumerate(revision2_matrix(), 1):
        records.append((f"REV2-{index:02d}", "REVISION_2_AMENDMENT", index, text))
    for index, text in enumerate(revision3_matrix(), 1):
        records.append((f"REV3-{index:02d}", "REVISION_3_AMENDMENT", index, text))
    return records
