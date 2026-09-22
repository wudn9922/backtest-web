from __future__ import annotations

"""Validate the repository's active GitHub-only zero-cost configuration."""

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
ALLOWED_RUNNER = "ubuntu-24.04"
DISALLOWED_WORKFLOW_TOKENS = (
    "ubuntu-latest",
    "ubuntu-22.04",
    "windows-",
    "macos-",
    "self-hosted",
    "larger-runner",
    "gpu",
    "actions/cache",
    "actions/upload-artifact",
    "google-github-actions",
    "gcloud",
    "terraform",
    "firestore",
    "cloud run",
    "cloudflare",
    "render.com",
    "azure/",
    "aws-actions",
)
DISALLOWED_REPOSITORY_FILES = (
    ".lfsconfig",
    "CODEOWNERS",  # A public source gate must not silently introduce a paid owner workflow.
)


def workflow_files() -> list[Path]:
    if not WORKFLOWS.exists():
        return []
    return sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])


def main() -> int:
    findings: list[tuple[str, str]] = []
    workflows = workflow_files()
    if not workflows:
        findings.append((".github/workflows", "NO_WORKFLOW_FOUND"))

    for path in workflows:
        relative = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        lowered = text.casefold()
        runners = re.findall(r"(?mi)^\s*runs-on:\s*([^#\r\n]+)", text)
        if not runners:
            findings.append((relative, "RUNNER_NOT_DECLARED"))
        for runner in runners:
            normalized = runner.strip().strip("[]\"'").casefold()
            if normalized != ALLOWED_RUNNER:
                findings.append((relative, f"DISALLOWED_RUNNER:{runner.strip()}"))
        for token in DISALLOWED_WORKFLOW_TOKENS:
            if token in lowered:
                findings.append((relative, f"DISALLOWED_WORKFLOW_TOKEN:{token}"))
        if not re.search(r"(?mi)^permissions:\s*\r?$", text) or not re.search(
            r"(?mi)^\s+contents:\s*read\s*$", text
        ):
            findings.append((relative, "READ_ONLY_CONTENTS_PERMISSION_REQUIRED"))
        for prohibited in ("contents: write", "pages: write", "id-token: write", "pull_request_target"):
            if prohibited in lowered:
                findings.append((relative, f"PROHIBITED_PERMISSION_OR_EVENT:{prohibited}"))

    for relative in DISALLOWED_REPOSITORY_FILES:
        if (ROOT / relative).exists():
            findings.append((relative, "DISALLOWED_REPOSITORY_CONFIGURATION"))
    attributes = ROOT / ".gitattributes"
    if attributes.exists() and "filter=lfs" in attributes.read_text(encoding="utf-8", errors="replace").casefold():
        findings.append((".gitattributes", "GIT_LFS_FILTER_CONFIGURED"))
    package_files = [ROOT / "package.json", ROOT / "frontend" / "package.json"]
    for package in package_files:
        if package.exists() and "publishconfig" in package.read_text(encoding="utf-8", errors="replace").casefold():
            findings.append((package.relative_to(ROOT).as_posix(), "PACKAGE_PUBLISHING_CONFIGURED"))

    if findings:
        print("Zero-cost policy: FAIL")
        for relative, reason in sorted(set(findings)):
            print(f"  {relative}: {reason}")
        return 1
    print(f"Zero-cost policy: PASS ({len(workflows)} workflow(s); runner={ALLOWED_RUNNER}; read-only CI)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
