from __future__ import annotations

"""Dedicated additive persistence for MA_BREAKOUT_ANALYTICS_V1."""

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class AnalyticsRepository:
    """Uses an independent SQLite connection and analytics-only tables."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _initialize(self) -> None:
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS ma_breakout_analytics_studies (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    ticker TEXT NOT NULL,
                    status TEXT NOT NULL,
                    analytics_revision TEXT NOT NULL,
                    spec_revision TEXT NOT NULL,
                    spec_revision_number INTEGER NOT NULL,
                    spec_hash TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    data_fingerprint TEXT,
                    provider TEXT,
                    config_json TEXT NOT NULL,
                    result_json TEXT,
                    error_code TEXT,
                    error_message TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_ma_analytics_studies_created
                    ON ma_breakout_analytics_studies(created_at DESC);
                CREATE TABLE IF NOT EXISTS ma_breakout_analytics_events (
                    study_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    sma_period INTEGER NOT NULL,
                    direction TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    PRIMARY KEY(study_id, event_id),
                    FOREIGN KEY(study_id) REFERENCES ma_breakout_analytics_studies(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_ma_analytics_events_period
                    ON ma_breakout_analytics_events(study_id, sma_period, direction);
                CREATE TABLE IF NOT EXISTS ma_breakout_target_outcomes (
                    study_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    condition_type TEXT NOT NULL,
                    observation_origin TEXT NOT NULL,
                    outcome_json TEXT NOT NULL,
                    PRIMARY KEY(study_id,event_id,target_type,condition_type,observation_origin),
                    FOREIGN KEY(study_id,event_id) REFERENCES ma_breakout_analytics_events(study_id,event_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS ma_breakout_target_session_audit (
                    study_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    condition_type TEXT NOT NULL,
                    observation_origin TEXT NOT NULL,
                    session_index INTEGER NOT NULL,
                    audit_json TEXT NOT NULL,
                    PRIMARY KEY(study_id,event_id,target_type,condition_type,observation_origin,session_index),
                    FOREIGN KEY(study_id,event_id,target_type,condition_type,observation_origin)
                        REFERENCES ma_breakout_target_outcomes(study_id,event_id,target_type,condition_type,observation_origin)
                        ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS ma_breakout_failure_outcomes (
                    study_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    outcome_json TEXT NOT NULL,
                    PRIMARY KEY(study_id,event_id),
                    FOREIGN KEY(study_id,event_id) REFERENCES ma_breakout_analytics_events(study_id,event_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS ma_breakout_aggregates (
                    study_id TEXT NOT NULL,
                    aggregate_id TEXT NOT NULL,
                    period INTEGER NOT NULL,
                    aggregate_type TEXT NOT NULL,
                    aggregate_json TEXT NOT NULL,
                    PRIMARY KEY(study_id,aggregate_id),
                    FOREIGN KEY(study_id) REFERENCES ma_breakout_analytics_studies(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS ma_breakout_aggregate_members (
                    study_id TEXT NOT NULL,
                    aggregate_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    membership_type TEXT NOT NULL,
                    PRIMARY KEY(study_id,aggregate_id,event_id,membership_type),
                    FOREIGN KEY(study_id,aggregate_id) REFERENCES ma_breakout_aggregates(study_id,aggregate_id) ON DELETE CASCADE,
                    FOREIGN KEY(study_id,event_id) REFERENCES ma_breakout_analytics_events(study_id,event_id) ON DELETE CASCADE
                );
            """)

    def create_running(self, *, study_id: str, config: dict[str, Any], analytics_revision: str,
                       spec_revision: str, spec_revision_number: int, spec_hash: str,
                       config_hash: str) -> dict[str, Any]:
        with self._lock, self.connect() as db:
            db.execute("""INSERT INTO ma_breakout_analytics_studies
                (id,created_at,ticker,status,analytics_revision,spec_revision,spec_revision_number,
                 spec_hash,config_hash,config_json)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (study_id, _now(), config["ticker"], "RUNNING", analytics_revision,
                 spec_revision, spec_revision_number, spec_hash, config_hash, _dump(config)))
        return self.get_study(study_id) or {}

    def complete(self, study_id: str, result: dict[str, Any]) -> None:
        with self._lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""UPDATE ma_breakout_analytics_studies SET status='COMPLETED', completed_at=?,
                data_fingerprint=?, provider=?, result_json=?, error_code=NULL, error_message=NULL WHERE id=?""",
                (_now(), result.get("data_fingerprint"), result.get("provider"), _dump(result), study_id))
            db.executemany("INSERT INTO ma_breakout_analytics_events VALUES (?,?,?,?,?)", [
                (study_id, x["event_id"], x["sma_period"], x["direction"], _dump(x)) for x in result.get("events", [])
            ])
            db.executemany("INSERT INTO ma_breakout_target_outcomes VALUES (?,?,?,?,?,?)", [
                (study_id, x["event_id"], x["target_type"], x["condition_type"], x["observation_origin"], _dump(x))
                for x in result.get("target_outcomes", [])
            ])
            session_rows = []
            for outcome in result.get("target_session_audit", []):
                # The engine includes a deterministic ordinal, so a target's
                # per-session audit remains uniquely ordered when persisted.
                key = (outcome["study_id"], outcome["event_id"], outcome["target_type"],
                       outcome["condition_type"], outcome["observation_origin"])
                session_rows.append((study_id, *key[1:], int(outcome["session_index"]), _dump(outcome)))
            db.executemany("INSERT INTO ma_breakout_target_session_audit VALUES (?,?,?,?,?,?,?)", session_rows)
            db.executemany("INSERT INTO ma_breakout_failure_outcomes VALUES (?,?,?)", [
                (study_id, x["event_id"], _dump(x)) for x in result.get("failure_outcomes", [])
            ])
            db.executemany("INSERT INTO ma_breakout_aggregates VALUES (?,?,?,?,?)", [
                (study_id, x["aggregate_id"], x["period"], x["aggregate_type"], _dump({k: v for k, v in x.items() if k != "members"}))
                for x in result.get("aggregates", [])
            ])
            members = []
            for aggregate in result.get("aggregates", []):
                for member in aggregate.get("members", []):
                    members.append((study_id, aggregate["aggregate_id"], member["event_id"], member["membership_type"]))
            db.executemany("INSERT INTO ma_breakout_aggregate_members VALUES (?,?,?,?)", members)

    def fail(self, study_id: str, error_code: str, error_message: str) -> None:
        with self._lock, self.connect() as db:
            db.execute("UPDATE ma_breakout_analytics_studies SET status='FAILED', completed_at=?, error_code=?, error_message=? WHERE id=?",
                       (_now(), error_code[:80], " ".join(error_message.split())[:500], study_id))

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["config"] = json.loads(result.pop("config_json"))
        raw = result.pop("result_json")
        result["result"] = json.loads(raw) if raw else None
        return result

    def get_study(self, study_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM ma_breakout_analytics_studies WHERE id=?", (study_id,)).fetchone()
        return self._decode(row)

    def list_studies(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM ma_breakout_analytics_studies ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._decode(row) for row in rows if row is not None]

    def members(self, study_id: str, aggregate_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("""SELECT m.event_id,m.membership_type,e.event_json
                FROM ma_breakout_aggregate_members m JOIN ma_breakout_analytics_events e
                USING(study_id,event_id) WHERE m.study_id=? AND m.aggregate_id=? ORDER BY e.sma_period,e.event_id""",
                (study_id, aggregate_id)).fetchall()
        return [{"event_id": r["event_id"], "membership_type": r["membership_type"], "event": json.loads(r["event_json"])} for r in rows]

    def counts(self) -> dict[str, int]:
        tables = ["ma_breakout_analytics_studies", "ma_breakout_analytics_events", "ma_breakout_target_outcomes",
                  "ma_breakout_target_session_audit", "ma_breakout_failure_outcomes", "ma_breakout_aggregates",
                  "ma_breakout_aggregate_members"]
        with self.connect() as db:
            return {table: int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}

