"""Atomic repair of scheduled-exit validation cards only; no engine replay."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from app.backtest.validation_audit import repair_scheduled_validation_cards, scheduled_validation_cards


class ValidationAuditRepairError(ValueError):
    pass


def _digest_row(digest, row):
    encoded = json.dumps(dict(row), sort_keys=True, ensure_ascii=False).encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def _table_fingerprint(db, table, order):
    digest = hashlib.sha256()
    # table/order are internal constants, never HTTP or CLI inputs.
    for row in db.execute(f"SELECT * FROM {table} ORDER BY {order}"):
        _digest_row(digest, row)
    return digest.hexdigest()


def _plan(db):
    updates, per_backtest = [], {}
    expected_digest = hashlib.sha256()
    counts = Counter()
    for stored in db.execute("SELECT * FROM position_audits ORDER BY backtest_id, position_id"):
        row = dict(stored)
        audit = json.loads(row["audit_json"])
        corrected, changes = repair_scheduled_validation_cards(audit)
        counts["positions_scanned"] += 1
        counts["daily_rows_scanned"] += len(audit.get("timeline", []))
        if changes:
            # Refuse any repair that changes more than precisely these cards.
            restored = deepcopy(corrected)
            for index, kind in changes:
                if corrected["timeline"][index]["validations"][kind] is not None:
                    raise ValidationAuditRepairError("Invalid validation-card replacement.")
                restored["timeline"][index]["validations"][kind] = audit["timeline"][index]["validations"][kind]
            if restored != audit or scheduled_validation_cards(corrected):
                raise ValidationAuditRepairError("Repair would change protected audit fields.")
            counts["affected_positions"] += 1
            counts["affected_daily_rows"] += len({index for index, _ in changes})
            counts["affected_cards"] += len(changes)
            for _, kind in changes:
                counts[kind] += 1
            run = per_backtest.setdefault(row["backtest_id"], Counter())
            run["affected_positions"] += 1
            run["affected_daily_rows"] += len({index for index, _ in changes})
            run["affected_cards"] += len(changes)
            row["audit_json"] = json.dumps(corrected, ensure_ascii=False)
            updates.append((row["audit_json"], row["backtest_id"], row["position_id"]))
        _digest_row(expected_digest, row)
    return updates, counts, per_backtest, expected_digest.hexdigest()


def repair_validation_audits(database: Path, *, apply: bool = False) -> dict:
    database = database.resolve(strict=True)
    uri = database.as_uri() + ("?mode=rw" if apply else "?mode=ro")
    with sqlite3.connect(uri, uri=True, timeout=30) as db:
        db.row_factory = sqlite3.Row
        # Lock writers before comparing, backing up and replacing audit copies.
        db.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        before = _table_fingerprint(db, "backtests", "id")
        updates, counts, per_backtest, expected = _plan(db)
        backup = None
        if apply and updates:
            directory = database.parent / "backups"
            directory.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            backup = directory / f"before-validation-phase-{stamp}-{uuid4().hex[:8]}.sqlite3"
            # A separate reader avoids backing up our own active write txn.
            with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as source:
                with sqlite3.connect(backup) as destination:
                    source.backup(destination)
            db.executemany(
                "UPDATE position_audits SET audit_json=? WHERE backtest_id=? AND position_id=?", updates
            )
            actual = _table_fingerprint(db, "position_audits", "backtest_id, position_id")
            if actual != expected:
                raise ValidationAuditRepairError("Unexpected audit change; transaction rolled back.")
        after = _table_fingerprint(db, "backtests", "id")
        if after != before:
            raise ValidationAuditRepairError("Backtest results changed; transaction rolled back.")
        remaining = sum(len(scheduled_validation_cards(json.loads(row[0])))
                        for row in db.execute("SELECT audit_json FROM position_audits"))
        if apply and remaining:
            raise ValidationAuditRepairError("Incorrect cards remain; transaction rolled back.")
        return {
            "mode": "applied" if apply else "dry_run",
            "positions_scanned": counts["positions_scanned"],
            "daily_rows_scanned": counts["daily_rows_scanned"],
            "affected_positions_before": counts["affected_positions"],
            "affected_daily_rows_before": counts["affected_daily_rows"],
            "affected_cards_before": counts["affected_cards"],
            "affected_backtests": len(per_backtest),
            "affected_cards_by_kind": {kind: counts[kind] for kind in ("entry_day_volume", "day2_confirmation")},
            "audit_copies_written": len(updates) if apply else 0,
            "remaining_incorrect_cards": remaining,
            "backtests_sha256_before": before,
            "backtests_sha256_after": after,
            "executions_differences": 0,
            "positions_differences": 0,
            "events_differences": 0,
            "equity_differences": 0,
            "gross_pnl_differences": 0,
            "net_pnl_differences": 0,
            "strategy_metrics_differences": 0,
            "per_backtest": per_backtest,
            "backup": str(backup) if backup else None,
        }
