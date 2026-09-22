from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "research" / "cloud" / "GATE_C0_PRECHANGE_BASELINE.json"
OUTPUT = ROOT / "research" / "cloud" / "CLOUD_SOURCE_BASELINE_MANIFEST.json"


def file_identity(relative: str) -> dict[str, object]:
    path = ROOT / relative
    raw = path.read_bytes()
    return {"path": relative, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def command_version(args: list[str]) -> str | None:
    if os.name == "nt" and args[0] == "pnpm":
        args = ["pnpm.cmd", *args[1:]]
    try:
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else None


def traceability_counts() -> dict[str, object]:
    ma_box = json.loads((ROOT / "research/specs/MA_BOX_LONG_V1_TEST_TRACEABILITY_REV3.json").read_text(encoding="utf-8"))
    analytics = json.loads((ROOT / "research/specs/MA_BREAKOUT_ANALYTICS_V1_TEST_TRACEABILITY_REV3.json").read_text(encoding="utf-8"))
    ma_coverage = Counter(item["coverage_status"] for item in ma_box["requirements"])
    analytics_requirements = analytics["requirements"]
    analytics_status = Counter(item.get("status", "ACTIVE") for item in analytics_requirements)
    return {
        "ma_box_long_v1_rev3": {
            "source_requirements": len(ma_box["requirements"]),
            "source_matrix_counts": ma_box["source_matrix_counts"],
            "coverage": dict(sorted(ma_coverage.items())),
        },
        "ma_breakout_analytics_v1_rev3": {
            "source_requirements": len(analytics_requirements),
            "active_requirements": analytics["requirement_counts"]["active"],
            "superseded_requirements": analytics["requirement_counts"]["superseded_by_rev3"],
            "status_counts": dict(sorted(analytics_status.items())),
            "active_coverage_counts": analytics["active_coverage_counts"],
        },
    }


def main() -> int:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    spec_fingerprints = baseline["spec_fingerprints"]
    for identity in spec_fingerprints.values():
        actual = file_identity(identity["path"])
        if actual["bytes"] != identity["bytes"] or actual["sha256"] != identity["sha256"]:
            raise SystemExit(f"Frozen specification mismatch at {identity['path']}; manifest not written.")

    canonical = {}
    for relative, item in baseline["canonical_hashes"].items():
        actual = file_identity(f"backend/{relative}")
        if actual["sha256"] != item["expected_sha256"]:
            raise SystemExit(f"Frozen canonical source mismatch at backend/{relative}; manifest not written.")
        canonical[relative] = actual

    package = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    lock_text = (ROOT / "frontend/pnpm-lock.yaml").read_text(encoding="utf-8")
    next_match = re.search(r"(?m)^  next@(\d+\.\d+\.\d+):", lock_text)
    if not next_match:
        raise SystemExit("Could not determine the locked Next.js version.")
    branch = command_version(["git", "branch", "--show-current"])
    if branch != "main":
        raise SystemExit(f"Expected the local Gate C0 branch to be main; found {branch!r}.")

    requirements_identity = file_identity("backend/requirements.txt")
    frontend_identity = {
        "name": package["name"],
        "version": package["version"],
        "node_version_tested_locally": command_version(["node", "--version"]),
        "pnpm_version_tested_locally": command_version(["pnpm", "--version"]),
        "next_version_resolved_by_lockfile": next_match.group(1),
        "package_json": file_identity("frontend/package.json"),
        "lockfile": file_identity("frontend/pnpm-lock.yaml"),
    }
    docker_identities = {
        relative: file_identity(relative)
        for relative in (
            "backend/Dockerfile",
            "frontend/Dockerfile",
            "docker-compose.yml",
            "docker-compose.prod.yml",
        )
        if (ROOT / relative).is_file()
    }
    result = {
        "schema_version": 1,
        "manifest_type": "GATE_C0_SOURCE_BASELINE",
        "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "project_version_state": {
            "frontend_version": package["version"],
            "backend_version": "not separately versioned in the current local application",
            "git_branch": branch,
            "initial_commit_sha": "not duplicated in the manifest to avoid self-reference; inspect Git HEAD and the Gate C0 report",
            "remote": "not configured; user GitHub authentication/authorization not present",
        },
        "canonical_file_hashes": canonical,
        "frozen_spec_fingerprints": spec_fingerprints,
        "frontend_package_identity": frontend_identity,
        "backend_python_identity": {
            "python_version_tested_locally": sys.version.split()[0],
            "ci_python_version": "3.12",
            "dependency_manifest": requirements_identity,
            "note": "Current requirements are compatibility ranges; CI installs from the manifest. This C0 record does not alter runtime dependency semantics.",
        },
        "key_docker_identity": docker_identities,
        "traceability_counts": traceability_counts(),
        "expected_production_database_rows_audit_only": baseline["production_database"]["counts"],
        "prechange_tree_manifest": {
            "file_count": baseline["current_project_tree_manifest"]["file_count"],
            "canonical_json_sha256": baseline["current_project_tree_manifest"]["canonical_json_sha256"],
            "baseline_artifact": "research/cloud/GATE_C0_PRECHANGE_BASELINE.json",
        },
        "deployment_state": "No cloud resources or remote repository were created by Gate C0.",
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    print(f"Canonical files: {len(canonical)}; frozen spec fingerprints: {len(spec_fingerprints)}")
    print(f"Analytics traceability: {result['traceability_counts']['ma_breakout_analytics_v1_rev3']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
