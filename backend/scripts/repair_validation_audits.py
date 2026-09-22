"""Repair audit validation phase interpretation, never strategy results.

Run from backend: python -m scripts.repair_validation_audits [--apply]
Default: read-only scan. --apply: SQLite backup + atomic affected-audits-only repair.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3

from app.db.validation_audit_repair import ValidationAuditRepairError, repair_validation_audits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    configured = os.getenv("DATABASE_URL", "")
    if args.database:
        path = args.database
    elif configured:
        if not configured.startswith("sqlite:///"):
            parser.error("Only SQLite databases are supported.")
        path = Path(configured.removeprefix("sqlite:///"))
    else:
        path = Path(os.getenv("DATA_DIR", "../data")) / "backtests.sqlite3"
    try:
        print(json.dumps(repair_validation_audits(path, apply=args.apply), indent=2))
    except (ValidationAuditRepairError, json.JSONDecodeError, sqlite3.Error, OSError) as exc:
        parser.exit(1, f"Repair refused: {exc}\n")


if __name__ == "__main__":
    main()
