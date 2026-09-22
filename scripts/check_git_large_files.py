from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIMIT_BYTES = 10 * 1024 * 1024
ALLOWLIST = ROOT / "scripts" / "git_large_file_allowlist.json"


def git_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return sorted({item.decode("utf-8", errors="surrogateescape") for item in result.stdout.split(b"\0") if item})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    config = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    allowlist = config.get("files", {})
    if not isinstance(allowlist, dict):
        print("Large-file allowlist must contain an object at 'files'.", file=sys.stderr)
        return 2

    encountered = set()
    violations = []
    large_count = 0
    for relative in git_paths():
        path = ROOT / Path(relative)
        if not path.is_file():
            continue
        size = path.stat().st_size
        if size <= LIMIT_BYTES:
            continue
        large_count += 1
        entry = allowlist.get(relative)
        size_mib = size / (1024 * 1024)
        if not isinstance(entry, dict):
            violations.append(f"{relative} ({size_mib:.2f} MiB): not explicitly allowlisted")
            continue
        required = {"reason", "owner", "expected_sha256"}
        missing = sorted(required - entry.keys())
        if missing:
            violations.append(f"{relative} ({size_mib:.2f} MiB): allowlist missing {', '.join(missing)}")
            continue
        actual = sha256(path)
        encountered.add(relative)
        if actual.lower() != str(entry["expected_sha256"]).lower():
            violations.append(f"{relative} ({size_mib:.2f} MiB): SHA-256 does not match allowlist")
        else:
            print(f"ALLOWLISTED {relative} ({size_mib:.2f} MiB); reason/owner recorded")

    stale = sorted(set(allowlist) - encountered)
    violations.extend(f"{relative}: stale allowlist entry (file not tracked or not larger than 10 MiB)" for relative in stale)
    if violations:
        print("Large-file policy: FAIL")
        for item in violations:
            print(f"  {item}")
        print("Only reviewed source or test-fixture assets may be allowlisted; do not add local data, databases, or caches.")
        return 1
    print(f"Large-file policy: PASS ({large_count} candidate files over 10 MiB; all excluded or validly allowlisted)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
