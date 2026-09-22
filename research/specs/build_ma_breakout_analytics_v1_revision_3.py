from __future__ import annotations

"""Build the immutable analytics specification from the two frozen Sol outputs."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE_PATHS = {
    "revision_2_master": ROOT / "MA_BREAKOUT_ANALYTICS_V1_REVISION_2_SOL_FROZEN_OUTPUT.txt",
    "revision_3_amendment": ROOT / "MA_BREAKOUT_ANALYTICS_V1_REVISION_3_SOL_FROZEN_AMENDMENT.txt",
}
OUTPUT = ROOT / "MA_BREAKOUT_ANALYTICS_V1_REVISION_3.md"
SIDECAR = ROOT / "MA_BREAKOUT_ANALYTICS_V1_REVISION_3.sha256"
MANIFEST = ROOT / "MA_BREAKOUT_ANALYTICS_V1_REVISION_3_SOURCE_MANIFEST.json"

SOURCE_IDENTITIES = {
    "revision_2_master": {
        "raw_bytes": 21855,
        "raw_sha256": "f01a50e304db4e654c57a0cfb560dc98ddc0a34aa478cd6248aa498f6434c69d",
        "normalized_bytes": 20862,
        "normalized_sha256": "d5d08500af89fce61c33c9004af23f4656bb677be10462a32c8a26641eaf66ec",
        "begins_with": "結論：Repo 稽核已完成，A–F 六項結果性決策均可凍結。沒有修改任何程式、測試、資料庫或既有規格。",
        "ends_with": "MA_BREAKOUT_ANALYTICS_V1 REVISION 2  \nMASTER SPEC REVIEW COMPLETE",
    },
    "revision_3_amendment": {
        "raw_bytes": 10759,
        "raw_sha256": "a1b80bfd9db2b4d6d1d252d050573eaf4bf40e535d698d2fee7fda38bf3b4448",
        "normalized_bytes": 10270,
        "normalized_sha256": "80c913dd26cb0adef57e259a4660da48bb681406e0ec25cfa947ebebdae485f1",
        "begins_with": "## 1. Revised Sideways definition",
        "ends_with": "MA_BREAKOUT_ANALYTICS_V1 SPEC FROZEN REVISION 3",
    },
}

NON_AUTHORITATIVE_PROMPT_FILES = {
    ROOT / "MA_BREAKOUT_ANALYTICS_V1_REVISION_2_MASTER_SOURCE.txt",
    ROOT / "MA_BREAKOUT_ANALYTICS_V1_REVISION_3_AMENDMENT.md",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_raw_source(raw: bytes) -> bytes:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("Frozen Sol source must not contain a UTF-8 BOM")
    text = raw.decode("utf-8", errors="strict").replace("\r\n", "\n").replace("\r", "\n")
    return text.encode("utf-8")


def load_authoritative_source(key: str, path: Path | None = None) -> tuple[bytes, bytes]:
    if key not in SOURCE_PATHS or key not in SOURCE_IDENTITIES:
        raise ValueError(f"Unknown frozen source key: {key}")
    expected_path = SOURCE_PATHS[key].resolve()
    actual_path = (path or SOURCE_PATHS[key]).resolve()
    if actual_path != expected_path:
        raise ValueError(f"Non-authoritative source path rejected for {key}: {actual_path}")

    raw = actual_path.read_bytes()
    identity = SOURCE_IDENTITIES[key]
    if len(raw) != identity["raw_bytes"] or digest(raw) != identity["raw_sha256"]:
        raise ValueError(f"Frozen Sol raw source identity mismatch for {key}")

    normalized = normalize_raw_source(raw)
    text = normalized.decode("utf-8")
    if not text.startswith(identity["begins_with"]):
        raise ValueError(f"Frozen Sol source opening mismatch for {key}")
    if not text.endswith(identity["ends_with"]):
        raise ValueError(f"Frozen Sol source ending mismatch for {key}")
    if len(normalized) != identity["normalized_bytes"] or digest(normalized) != identity["normalized_sha256"]:
        raise ValueError(f"Frozen Sol normalized source identity mismatch for {key}")
    return raw, normalized


def build() -> dict:
    sources: dict[str, dict[str, object]] = {}
    normalized: dict[str, bytes] = {}
    for key, path in SOURCE_PATHS.items():
        raw, canonical = load_authoritative_source(key)
        identity = SOURCE_IDENTITIES[key]
        normalized[key] = canonical
        sources[key] = {
            "path": path.name,
            "authority": "SOL_FROZEN_OUTPUT",
            "raw_bytes": len(raw),
            "raw_sha256": digest(raw),
            "normalized_bytes": len(canonical),
            "normalized_sha256": digest(canonical),
            "normalized_eof_newline": canonical.endswith(b"\n"),
        }
        assert sources[key]["raw_bytes"] == identity["raw_bytes"]
        assert sources[key]["raw_sha256"] == identity["raw_sha256"]

    section_a = (
        b"<!-- BEGIN SOURCE A: AUTHORITATIVE SOL FROZEN REVISION 2 OUTPUT -->\n"
        + normalized["revision_2_master"]
        + b"\n<!-- END SOURCE A -->"
    )
    section_b = (
        b"<!-- BEGIN SOURCE B: AUTHORITATIVE SOL FROZEN REVISION 3 AMENDMENT -->\n"
        + normalized["revision_3_amendment"]
        + b"\n<!-- END SOURCE B -->"
    )
    combined = section_a + b"\n\n" + section_b + b"\n"
    if combined.count(b"\r") or not combined.endswith(b"\n") or combined.endswith(b"\n\n"):
        raise RuntimeError("Combined artifact is not canonical UTF-8/LF with one trailing newline")

    OUTPUT.write_bytes(combined)
    artifact_hash = digest(combined)
    SIDECAR.write_text(f"{artifact_hash}  {OUTPUT.name}\n", encoding="ascii", newline="\n")
    manifest = {
        "strategy_revision": "MA_BREAKOUT_ANALYTICS_V1",
        "spec_revision": 3,
        "source_identity_policy": "RAW_SOURCE_IDENTITY_AND_NORMALIZED_ARTIFACT_IDENTITY_ARE_DISTINCT",
        "source_normalization": "UTF-8 strict; CRLF/CR to LF; preserve source EOF exactly",
        "sources": sources,
        "combined_artifact": {
            "path": OUTPUT.name,
            "bytes": len(combined),
            "lines": combined.count(b"\n"),
            "sha256": artifact_hash,
        },
        "encoding": "UTF-8",
        "bom": False,
        "line_endings": "LF",
        "trailing_newlines": 1,
        "non_authoritative_sources": [
            {
                "path": "MA_BREAKOUT_ANALYTICS_V1_REVISION_2_MASTER_SOURCE.txt",
                "role": "EARLIER_REQUEST_PROMPT_NOT_A_FROZEN_SOL_OUTPUT",
            },
            {
                "path": "MA_BREAKOUT_ANALYTICS_V1_REVISION_3_AMENDMENT.md",
                "role": "AMENDMENT_REQUEST_PROMPT_NOT_A_FROZEN_SOL_OUTPUT",
            },
        ],
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
    return manifest


if __name__ == "__main__":
    build()
