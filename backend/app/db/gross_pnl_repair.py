"""Atomic, backed-up migration of gross_pnl reporting fields only."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from app.backtest.pnl_reporting import ReportingRepairError, corrected_gross_pnl


def _protected_snapshot(records, audits) -> str:
    """Fingerprint every stored field except the explicitly authorized values."""
    records, audits = deepcopy(records), deepcopy(audits)
    for row in records:
        if row["result_json"]:
            payload = json.loads(row["result_json"])
            for position in payload.get("positions", []):
                position.pop("gross_pnl", None)
            row["result_json"] = payload
    for row in audits:
        payload = json.loads(row["audit_json"])
        payload.get("position", {}).pop("gross_pnl", None)
        row["audit_json"] = payload
    encoded = json.dumps([records, audits], sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _rows(db):
    return ([dict(r) for r in db.execute("SELECT * FROM backtests ORDER BY id")],
            [dict(r) for r in db.execute("SELECT * FROM position_audits ORDER BY backtest_id, position_id")])


def repair_gross_pnl(database: Path, *, apply: bool = False) -> dict:
    database = database.resolve(strict=True)
    uri = database.as_uri() + ("?mode=rw" if apply else "?mode=ro")
    with sqlite3.connect(uri, uri=True, timeout=30) as db:
        db.row_factory = sqlite3.Row
        # Prevent another writer from changing history between validation and commit.
        db.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        records, audits = _rows(db)
        before = _protected_snapshot(records, audits)
        result_updates, audit_updates, values_by_run = [], [], {}
        position_count = corrected_count = completed_count = 0
        for row in records:
            if row["status"] != "COMPLETED":
                continue
            result = json.loads(row["result_json"])
            try:
                corrected, values, changed = corrected_gross_pnl(result)
            except (ReportingRepairError, KeyError, TypeError, ValueError) as exc:
                raise ReportingRepairError(f"Backtest {row['id']}: {exc}") from exc
            completed_count += 1
            position_count += len(result.get("positions", []))
            corrected_count += changed
            values_by_run[row["id"]] = values
            if changed:
                result_updates.append((json.dumps(corrected, ensure_ascii=False), row["id"]))
        for row in audits:
            payload = json.loads(row["audit_json"])
            try:
                gross = values_by_run[row["backtest_id"]][row["position_id"]]
            except KeyError as exc:
                raise ReportingRepairError("Orphaned position audit; refusing partial migration.") from exc
            if payload["position"]["gross_pnl"] != gross:
                payload["position"]["gross_pnl"] = gross
                audit_updates.append((json.dumps(payload, ensure_ascii=False), row["backtest_id"], row["position_id"]))
        backup_path = None
        if apply and (result_updates or audit_updates):
            backup_dir = database.parent / "backups"
            backup_dir.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            backup_path = backup_dir / f"before-gross-pnl-{stamp}-{uuid4().hex[:8]}.sqlite3"
            # Use a separate read connection: backing up a connection with an
            # active write transaction would wait on its own transaction.
            with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as source:
                with sqlite3.connect(backup_path) as destination:
                    source.backup(destination)
            db.executemany("UPDATE backtests SET result_json=? WHERE id=?", result_updates)
            db.executemany("UPDATE position_audits SET audit_json=? WHERE backtest_id=? AND position_id=?", audit_updates)
            after_records, after_audits = _rows(db)
            after = _protected_snapshot(after_records, after_audits)
            if after != before:
                raise ReportingRepairError("A field other than gross_pnl changed; transaction rolled back.")
        else:
            after = before
        return {
            "mode": "applied" if apply else "dry_run",
            "completed_backtests": completed_count,
            "positions_scanned": position_count,
            "positions_corrected": corrected_count,
            "backtests_corrected": len(result_updates),
            "audit_copies_corrected": len(audit_updates),
            "protected_fields_sha256_before": before,
            "protected_fields_sha256_after": after,
            "executions_differences": 0,
            "net_pnl_differences": 0,
            "equity_differences": 0,
            "strategy_metrics_differences": 0,
            "backup": str(backup_path) if backup_path else None,
        }
