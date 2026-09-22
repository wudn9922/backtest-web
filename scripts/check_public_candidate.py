from __future__ import annotations

"""Reject public-source personal data while preserving frozen spec evidence."""

import hashlib
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_SCAN_BYTES = 100 * 1024 * 1024
FROZEN_PATH_EXCEPTIONS = {
    "research/specs/MA_BREAKOUT_ANALYTICS_V1_REVISION_2_SOL_FROZEN_OUTPUT.txt": "f01a50e304db4e654c57a0cfb560dc98ddc0a34aa478cd6248aa498f6434c69d",
    "research/specs/MA_BREAKOUT_ANALYTICS_V1_REVISION_3.md": "0ac4a0fad9cbbc747b104b19e420e35368937e3359fd462786bd6317ad0d7647",
}
ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]+Users[\\/]|/(?:Users|home)/)")
EMAIL_ADDRESS = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PRIVATE_IP = re.compile(r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b")
PRIVATE_IP_TEST_PLACEHOLDERS = {
    "frontend/tests/network.test.mjs": {"192" + ".168.1.123"},
}


def candidate_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return sorted({item.decode("utf-8", errors="surrogateescape") for item in result.stdout.split(b"\0") if item})


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    findings: list[tuple[str, str]] = []
    scanned = 0
    seen_exceptions: set[str] = set()
    for relative in candidate_paths():
        path = ROOT / relative
        try:
            if not path.is_file():
                continue
            raw = path.read_bytes()
        except OSError:
            findings.append((relative, "UNREADABLE_CANDIDATE"))
            continue
        if relative in FROZEN_PATH_EXCEPTIONS:
            seen_exceptions.add(relative)
            if sha256(raw) != FROZEN_PATH_EXCEPTIONS[relative]:
                findings.append((relative, "FROZEN_PATH_EXCEPTION_HASH_MISMATCH"))
                continue
        if len(raw) > MAX_SCAN_BYTES or b"\0" in raw[:8192]:
            continue
        scanned += 1
        text = raw.decode("utf-8", errors="replace")
        if ABSOLUTE_PATH.search(text) and relative not in FROZEN_PATH_EXCEPTIONS:
            findings.append((relative, "ABSOLUTE_LOCAL_PATH"))
        if EMAIL_ADDRESS.search(text):
            findings.append((relative, "EMAIL_ADDRESS"))
        private_ip_text = text
        for placeholder in PRIVATE_IP_TEST_PLACEHOLDERS.get(relative, set()):
            private_ip_text = private_ip_text.replace(placeholder, "[TEST_LAN_FIXTURE]")
        if PRIVATE_IP.search(private_ip_text):
            findings.append((relative, "PRIVATE_LAN_ADDRESS"))
    for relative in sorted(set(FROZEN_PATH_EXCEPTIONS) - seen_exceptions):
        findings.append((relative, "FROZEN_PATH_EXCEPTION_MISSING"))
    if findings:
        print("Public candidate scan: FAIL")
        for relative, rule in sorted(findings):
            print(f"  {relative}: {rule}")
        return 1
    print(f"Public candidate scan: PASS ({scanned} text candidates; exact frozen-path exceptions verified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
