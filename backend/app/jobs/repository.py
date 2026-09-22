from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TERMINAL_STATUSES = {"COMPLETED", "PARTIAL_SUCCESS", "FAILED", "FAILED_VALIDATION", "CANCELLED"}
ACTIVE_STATUSES = {"QUEUED", "RUNNING"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobRepository:
    """Small durable queue stored outside the production backtest tables."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def _initialize(self) -> None:
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                """CREATE TABLE IF NOT EXISTS background_jobs (
                    id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    progress_current INTEGER NOT NULL DEFAULT 0,
                    progress_total INTEGER NOT NULL DEFAULT 0,
                    current_item TEXT,
                    message TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    errors_json TEXT NOT NULL DEFAULT '[]',
                    result_json TEXT NOT NULL DEFAULT '{}'
                )"""
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON background_jobs(created_at DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON background_jobs(status)")
            db.execute(
                """CREATE TABLE IF NOT EXISTS provider_health (
                    provider TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    last_checked_at TEXT,
                    last_success_at TEXT,
                    last_error_type TEXT,
                    safe_message TEXT
                )"""
            )
            # Structure chart artifacts are kept outside the potentially large
            # job result JSON.  They are train-only, top-five audit payloads
            # and can therefore be fetched on demand without re-running data
            # preparation or touching Test data.
            db.execute(
                """CREATE TABLE IF NOT EXISTS optimization_structure_artifacts (
                    job_id TEXT NOT NULL,
                    window_index INTEGER NOT NULL,
                    ma_period INTEGER NOT NULL,
                    structure_spec_hash TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    PRIMARY KEY (job_id, window_index, ma_period)
                )"""
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_structure_artifacts_job ON optimization_structure_artifacts(job_id, window_index)")
            
    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        item["errors"] = json.loads(item.pop("errors_json") or "[]")
        item["result"] = json.loads(item.pop("result_json") or "{}")
        return item

    def recover_interrupted(self) -> list[str]:
        with self._lock, self.connect() as db:
            db.execute(
                "UPDATE background_jobs SET status='QUEUED', started_at=NULL, current_item=NULL, message=? WHERE status='RUNNING'",
                ("服務重新啟動，工作將從安全檢查點繼續。",),
            )
            rows = db.execute("SELECT id FROM background_jobs WHERE status='QUEUED' ORDER BY created_at").fetchall()
        return [str(row["id"]) for row in rows]

    def create(self, job_type: str, payload: dict[str, Any], total: int = 0) -> tuple[dict[str, Any], bool]:
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        with self._lock, self.connect() as db:
            row = db.execute(
                "SELECT * FROM background_jobs WHERE job_type=? AND payload_json=? AND status IN ('QUEUED','RUNNING') ORDER BY created_at DESC LIMIT 1",
                (job_type, encoded),
            ).fetchone()
            if row:
                return self._decode(row) or {}, False
            identifier = str(uuid.uuid4())
            db.execute(
                """INSERT INTO background_jobs
                (id, job_type, status, created_at, progress_total, message, payload_json)
                VALUES (?, ?, 'QUEUED', ?, ?, ?, ?)""",
                (identifier, job_type, utc_now(), int(total), "工作已排入佇列。", encoded),
            )
            row = db.execute("SELECT * FROM background_jobs WHERE id=?", (identifier,)).fetchone()
        return self._decode(row) or {}, True

    def get(self, identifier: str) -> dict[str, Any] | None:
        with self.connect() as db:
            return self._decode(db.execute("SELECT * FROM background_jobs WHERE id=?", (identifier,)).fetchone())

    def list(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM background_jobs ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 100)),)).fetchall()
        return [self._decode(row) or {} for row in rows]

    def list_by_type(self, job_type: str, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM background_jobs WHERE job_type=? ORDER BY created_at DESC LIMIT ?",
                (job_type, max(1, min(limit, 100))),
            ).fetchall()
        return [self._decode(row) or {} for row in rows]

    def cancel(self, identifier: str) -> bool:
        """Request cancellation without killing the worker mid-engine-run.

        Long jobs observe the durable CANCELLED state between canonical runs,
        so a service restart cannot accidentally resume a cancelled job.
        """
        with self._lock, self.connect() as db:
            cursor = db.execute(
                """UPDATE background_jobs SET status='CANCELLED', finished_at=?, current_item=NULL,
                message=? WHERE id=? AND status IN ('QUEUED','RUNNING')""",
                (utc_now(), "工作已取消。", identifier),
            )
        return cursor.rowcount > 0

    def mark_running(self, identifier: str) -> None:
        with self._lock, self.connect() as db:
            db.execute(
                "UPDATE background_jobs SET status='RUNNING', started_at=COALESCE(started_at, ?), finished_at=NULL, message=? WHERE id=?",
                (utc_now(), "工作正在執行。", identifier),
            )

    def progress(self, identifier: str, current: int, total: int, current_item: str | None, message: str, *, errors: list[dict[str, Any]] | None = None, result: dict[str, Any] | None = None) -> None:
        fields = ["progress_current=?", "progress_total=?", "current_item=?", "message=?"]
        values: list[Any] = [int(current), int(total), current_item, message]
        if errors is not None:
            fields.append("errors_json=?"); values.append(json.dumps(errors, ensure_ascii=False))
        if result is not None:
            fields.append("result_json=?"); values.append(json.dumps(result, ensure_ascii=False))
        values.append(identifier)
        with self._lock, self.connect() as db:
            db.execute(f"UPDATE background_jobs SET {', '.join(fields)} WHERE id=?", values)

    def finish(self, identifier: str, status: str, message: str, *, errors: list[dict[str, Any]] | None = None, result: dict[str, Any] | None = None) -> None:
        if status not in TERMINAL_STATUSES:
            raise ValueError("invalid terminal job status")
        with self._lock, self.connect() as db:
            db.execute(
                """UPDATE background_jobs SET status=?, finished_at=?, current_item=NULL, message=?,
                errors_json=COALESCE(?, errors_json), result_json=COALESCE(?, result_json) WHERE id=?""",
                (
                    status, utc_now(), message,
                    json.dumps(errors, ensure_ascii=False) if errors is not None else None,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    identifier,
                ),
            )

    def provider_health(self) -> dict[str, dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM provider_health ORDER BY provider").fetchall()
        return {str(row["provider"]): dict(row) for row in rows}

    def update_provider(self, provider: str, status: str, error_type: str | None = None, message: str | None = None) -> None:
        checked = utc_now()
        with self._lock, self.connect() as db:
            previous = db.execute("SELECT last_success_at FROM provider_health WHERE provider=?", (provider,)).fetchone()
            last_success = checked if status == "online" else (previous["last_success_at"] if previous else None)
            db.execute(
                """INSERT INTO provider_health(provider,status,last_checked_at,last_success_at,last_error_type,safe_message)
                VALUES(?,?,?,?,?,?) ON CONFLICT(provider) DO UPDATE SET
                status=excluded.status,last_checked_at=excluded.last_checked_at,last_success_at=excluded.last_success_at,
                last_error_type=excluded.last_error_type,safe_message=excluded.safe_message""",
                (provider, status, checked, last_success, error_type, message),
            )

    def put_structure_artifact(
        self,
        job_id: str,
        window_index: int,
        ma_period: int,
        structure_spec_hash: str,
        artifact: dict[str, Any],
    ) -> None:
        """Persist/replace one numerical Train chart artifact atomically."""
        encoded = json.dumps(artifact, ensure_ascii=False, allow_nan=False)
        with self._lock, self.connect() as db:
            db.execute(
                """INSERT INTO optimization_structure_artifacts
                (job_id, window_index, ma_period, structure_spec_hash, artifact_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(job_id, window_index, ma_period) DO UPDATE SET
                structure_spec_hash=excluded.structure_spec_hash,
                artifact_json=excluded.artifact_json""",
                (job_id, int(window_index), int(ma_period), str(structure_spec_hash), encoded),
            )

    def get_structure_artifact(
        self,
        job_id: str,
        window_index: int,
        ma_period: int,
        structure_spec_hash: str | None = None,
    ) -> dict[str, Any] | None:
        with self.connect() as db:
            query = """SELECT structure_spec_hash, artifact_json
                       FROM optimization_structure_artifacts
                       WHERE job_id=? AND window_index=? AND ma_period=?"""
            row = db.execute(query, (job_id, int(window_index), int(ma_period))).fetchone()
        if row is None or (structure_spec_hash is not None and row["structure_spec_hash"] != structure_spec_hash):
            return None
        artifact = json.loads(row["artifact_json"] or "{}")
        if isinstance(artifact, dict):
            artifact.setdefault("structure_spec_hash", row["structure_spec_hash"])
        return artifact

    def list_structure_artifacts(self, job_id: str, window_index: int | None = None) -> list[dict[str, Any]]:
        with self.connect() as db:
            if window_index is None:
                rows = db.execute(
                    """SELECT window_index, ma_period, structure_spec_hash, artifact_json
                       FROM optimization_structure_artifacts WHERE job_id=?
                       ORDER BY window_index, ma_period""",
                    (job_id,),
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT window_index, ma_period, structure_spec_hash, artifact_json
                       FROM optimization_structure_artifacts
                       WHERE job_id=? AND window_index=? ORDER BY ma_period""",
                    (job_id, int(window_index)),
                ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            artifact = json.loads(row["artifact_json"] or "{}")
            output.append({
                "job_id": job_id,
                "window_index": int(row["window_index"]),
                "ma_period": int(row["ma_period"]),
                "structure_spec_hash": row["structure_spec_hash"],
                "artifact": artifact,
            })
        return output

    def copy_structure_artifacts(
        self,
        source_job_id: str,
        target_job_id: str,
        structure_spec_hash: str | None = None,
        implementation_revision: str | None = None,
    ) -> int:
        """Copy cached Top-5 artifacts to a new job, never aliasing job ids.

        ``implementation_revision`` is optional for backwards compatibility
        with the generic repository API.  Structure-mode cache reuse passes
        the current revision, so a legacy artifact whose JSON predates the
        corrected selector is never copied into a new result.  Existing rows
        remain untouched.
        """
        with self._lock, self.connect() as db:
            if structure_spec_hash is None:
                rows = db.execute(
                    "SELECT window_index, ma_period, structure_spec_hash, artifact_json FROM optimization_structure_artifacts WHERE job_id=?",
                    (source_job_id,),
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT window_index, ma_period, structure_spec_hash, artifact_json
                       FROM optimization_structure_artifacts WHERE job_id=? AND structure_spec_hash=?""",
                    (source_job_id, structure_spec_hash),
                ).fetchall()
            eligible_rows = []
            for row in rows:
                if implementation_revision is not None:
                    try:
                        artifact = json.loads(row["artifact_json"] or "{}")
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(artifact, dict) or artifact.get("structure_implementation_revision") != implementation_revision:
                        continue
                eligible_rows.append(row)
            for row in eligible_rows:
                db.execute(
                    """INSERT INTO optimization_structure_artifacts
                    (job_id, window_index, ma_period, structure_spec_hash, artifact_json)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(job_id, window_index, ma_period) DO UPDATE SET
                    structure_spec_hash=excluded.structure_spec_hash,
                    artifact_json=excluded.artifact_json""",
                    (target_job_id, row["window_index"], row["ma_period"], row["structure_spec_hash"], row["artifact_json"]),
                )
        return len(eligible_rows)
