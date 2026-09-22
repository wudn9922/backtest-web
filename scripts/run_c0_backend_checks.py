from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
MA_BOX = [
    "tests/test_ma_box_long.py",
    "tests/test_ma_box_long_revision2.py",
    "tests/test_ma_box_long_revision3.py",
    "tests/test_ma_box_traceability.py",
]
ANALYTICS = [
    "tests/test_ma_breakout_analytics.py",
    "tests/test_ma_breakout_analytics_traceability.py",
]
LEGACY_IGNORES = [
    "--ignore=tests/test_ma_box_long.py",
    "--ignore=tests/test_ma_box_long_revision2.py",
    "--ignore=tests/test_ma_box_long_revision3.py",
    "--ignore=tests/test_ma_box_traceability.py",
    "--ignore=tests/test_ma_breakout_analytics.py",
    "--ignore=tests/test_ma_breakout_analytics_traceability.py",
]
SUITES = (
    ("MA_BOX", MA_BOX, 99),
    ("Analytics + traceability", ANALYTICS, 110),
    ("Legacy remainder", ["tests", *LEGACY_IGNORES], 246),
    ("All backend", ["tests"], 455),
)


def summarize_xml(path: Path, output: str) -> dict[str, int]:
    root = ET.parse(path).getroot()
    cases = root.findall(".//testcase")
    failures = sum(len(case.findall("failure")) for case in cases)
    errors = sum(len(case.findall("error")) for case in cases)
    skipped_nodes = [node for case in cases for node in case.findall("skipped")]
    xfail = sum(
        1
        for node in skipped_nodes
        if "xfail" in (node.attrib.get("type", "") + node.attrib.get("message", "")).casefold()
    )
    skipped = len(skipped_nodes) - xfail
    deselected_match = re.search(r"\b(\d+) deselected\b", output)
    warnings_match = re.search(r"\b(\d+) warnings?\b", output)
    return {
        "collected": len(cases),
        "passed": len(cases) - failures - errors - len(skipped_nodes),
        "failed": failures + errors,
        "skipped": skipped,
        "xfail": xfail,
        "deselected": int(deselected_match.group(1)) if deselected_match else 0,
        "warnings": int(warnings_match.group(1)) if warnings_match else 0,
    }


def main() -> int:
    failed = False
    with tempfile.TemporaryDirectory(prefix="backtest-web-c0-pytest-") as temp_dir:
        for index, (name, selection, minimum) in enumerate(SUITES, start=1):
            xml_path = Path(temp_dir) / f"suite-{index}.xml"
            pytest_temp = Path(temp_dir) / f"pytest-work-{index}"
            command = [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--basetemp",
                str(pytest_temp),
                "--junitxml",
                str(xml_path),
                *selection,
            ]
            result = subprocess.run(
                command,
                cwd=BACKEND,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            output = result.stdout + result.stderr
            if result.returncode != 0 or not xml_path.exists():
                print(f"{name}: FAIL (pytest exit {result.returncode})")
                print(output[-6000:])
                failed = True
                continue
            counts = summarize_xml(xml_path, output)
            status = (
                "PASS"
                if counts["passed"] >= minimum
                and counts["failed"] == 0
                and counts["skipped"] == 0
                and counts["xfail"] == 0
                and counts["deselected"] == 0
                else "FAIL"
            )
            print(
                f"{name}: {status} | passed={counts['passed']} (minimum {minimum}), "
                f"failed={counts['failed']}, skipped={counts['skipped']}, xfail={counts['xfail']}, "
                f"deselected={counts['deselected']}, warnings={counts['warnings']}"
            )
            if status != "PASS":
                print(output[-6000:])
                for case in ET.parse(xml_path).getroot().findall(".//testcase"):
                    issue = case.find("error")
                    if issue is None:
                        issue = case.find("failure")
                    if issue is not None:
                        node_id = f"{case.attrib.get('classname', '')}::{case.attrib.get('name', '')}"
                        detail = (issue.text or issue.attrib.get("message", "")).strip()
                        print(f"First failing node: {node_id}")
                        print(detail[-2500:])
                        break
                failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
