"""Rebuild one completed backtest's Position Inspector audit snapshots safely.

Run from ``backend`` after the audit renderer has been updated:

    .venv\\Scripts\\python.exe scripts\\rebuild_position_audits.py <backtest-id>

The command is local/cache-only.  It refuses to write if a deterministic replay
does not exactly match the stored execution, position, equity, metric, and
event invariants.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

# Make the command work both as ``python scripts/...`` and ``python -m`` from
# a checkout, without relying on a caller-provided PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backtest.audit_rebuild import AuditRebuildError, rebuild_position_audits
from app.main import app


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely rebuild one backtest's position audit snapshots from local daily cache.")
    parser.add_argument("backtest_id", help="Completed backtest UUID")
    args = parser.parse_args()

    try:
        with TestClient(app):
            report = rebuild_position_audits(
                backtest_id=args.backtest_id,
                repository=app.state.repository,
                data_provider=app.state.provider,
            )
    except AuditRebuildError as exc:
        print(json.dumps({"status": "refused", "message": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "rebuilt", **report.as_dict()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - command entrypoint
    raise SystemExit(main())
