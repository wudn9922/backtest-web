from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_TEXT_SCAN_BYTES = 100 * 1024 * 1024
PLACEHOLDER = re.compile(
    r"^(?:example|dummy|sample|placeholder|changeme|replace(?:[-_].*)?|your[-_].*|test(?:[-_].*)?|fixture(?:[-_].*)?|not[-_].*|x{4,}|<[^>]+>|\$\{[^}]+\})$",
    re.IGNORECASE,
)
PATTERNS = (
    ("AWS_ACCESS_KEY_ID", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GITHUB_TOKEN", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{30,})\b")),
    ("PRIVATE_KEY_HEADER", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
)
HIGH_RISK_ASSIGNMENT = re.compile(
    r"(?m)^\s*(?:export\s+)?(?P<name>[A-Z][A-Z0-9_]*(?:API_KEY|API_TOKEN|ACCESS_TOKEN|AUTH_TOKEN|CLIENT_SECRET|PRIVATE_KEY|ACCESS_KEY|SECRET_KEY|PASSWORD|CREDENTIALS?))\s*[:=]\s*['\"]?(?P<value>[A-Za-z0-9_./+=:-]{6,})['\"]?\s*(?:#.*)?$"
)
NARROW_CLOUDFLARE_ASSIGNMENT = re.compile(
    r"\b(?:CLOUDFLARE_API_TOKEN|CF_API_TOKEN|CLOUDFLARE_API_KEY)\b\s*[:=]\s*['\"]?([^\s\"'#]{20,})", re.IGNORECASE
)
SERVICE_ACCOUNT_TYPE = re.compile(r"\"type\"\s*:\s*\"service_account\"", re.IGNORECASE)
SERVICE_ACCOUNT_PRIVATE_KEY = re.compile(r"\"private_key\"\s*:", re.IGNORECASE)


def candidate_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return sorted({item.decode("utf-8", errors="surrogateescape") for item in result.stdout.split(b"\0") if item})


def placeholder(value: str) -> bool:
    cleaned = value.strip().strip("\"'` ").strip()
    return not cleaned or bool(PLACEHOLDER.fullmatch(cleaned))


def scan_text(text: str) -> set[str]:
    findings = {rule for rule, pattern in PATTERNS if pattern.search(text)}
    if SERVICE_ACCOUNT_TYPE.search(text) and SERVICE_ACCOUNT_PRIVATE_KEY.search(text):
        findings.add("GCP_SERVICE_ACCOUNT_JSON")
    if any(not placeholder(match.group(1)) for match in NARROW_CLOUDFLARE_ASSIGNMENT.finditer(text)):
        findings.add("CLOUDFLARE_TOKEN_ASSIGNMENT")
    for match in HIGH_RISK_ASSIGNMENT.finditer(text):
        if not placeholder(match.group("value")):
            findings.add("HIGH_RISK_SECRET_ASSIGNMENT")
    return findings


def main() -> int:
    findings = []
    scanned = 0
    unscanned_text_files = []
    for relative in candidate_paths():
        path = ROOT / Path(relative)
        try:
            size = path.stat().st_size
            if not path.is_file():
                continue
            if size > MAX_TEXT_SCAN_BYTES:
                unscanned_text_files.append(relative)
                continue
            raw = path.read_bytes()
        except OSError:
            findings.append((relative, "UNREADABLE_CANDIDATE"))
            continue
        if b"\0" in raw[:8192]:
            continue
        scanned += 1
        text = raw.decode("utf-8", errors="replace")
        for rule in sorted(scan_text(text)):
            findings.append((relative, rule))

    if findings or unscanned_text_files:
        print("Secret scan: FAIL")
        for relative, rule in sorted(findings):
            print(f"  {relative}: {rule}")
        for relative in sorted(unscanned_text_files):
            print(f"  {relative}: TEXT_FILE_OVER_SCAN_LIMIT")
        print("Only path and rule identifiers are emitted; detected values are never printed.")
        return 1
    print(f"Secret scan: PASS ({scanned} text candidates scanned; no credential values found)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
