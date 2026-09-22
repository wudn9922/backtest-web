from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FROZEN_TESTS = (
    "tests/test_ma_box_long_revision3.py::test_revision3_artifact_is_verbatim_sections_and_sidecar_matches",
    "tests/test_ma_breakout_analytics.py::test_analytics_keeps_frozen_canonical_and_legacy_source_hashes",
    "tests/test_ma_breakout_analytics.py::test_spec_artifact_sidecar_identity_and_encoding",
)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="backtest-web-frozen-check-") as temp:
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(Path(temp) / "pytest-work"),
            *FROZEN_TESTS,
        ]
        result = subprocess.run(command, cwd=BACKEND, check=False)
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
