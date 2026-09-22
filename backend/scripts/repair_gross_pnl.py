"""Run python -m scripts.repair_gross_pnl [--apply] from backend.

Default is a read-only dry run. --apply backs up SQLite and changes only stored
gross_pnl fields in results and inspector copies; no provider or engine replay.
"""
import argparse
import json
import os
from pathlib import Path

from app.backtest.pnl_reporting import ReportingRepairError
from app.db.gross_pnl_repair import repair_gross_pnl


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
        print(json.dumps(repair_gross_pnl(path, apply=args.apply), indent=2))
    except ReportingRepairError as exc:
        parser.exit(1, f"Repair refused: {exc}\n")


if __name__ == "__main__":
    main()
