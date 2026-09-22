from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class BacktestRepository:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def connect_ma_box(self) -> sqlite3.Connection:
        """Open a MA_BOX-only connection with FK enforcement enabled.

        Legacy callers continue to use ``connect`` unchanged.  Keeping the
        pragma on this dedicated connection avoids changing historical
        backtest runtime semantics while making the additive research schema
        enforce its declared relationships.
        """
        connection = self.connect()
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self.connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS backtests (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    initial_capital REAL NOT NULL,
                    final_equity REAL,
                    total_return REAL,
                    cagr REAL,
                    max_drawdown REAL,
                    sharpe REAL,
                    strategy_version INTEGER,
                    status TEXT NOT NULL,
                    result_json TEXT
                )"""
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(backtests)").fetchall()}
            if "strategy_version" not in columns:
                db.execute("ALTER TABLE backtests ADD COLUMN strategy_version INTEGER")
            db.execute("CREATE INDEX IF NOT EXISTS idx_backtests_created_at ON backtests(created_at DESC)")
            db.execute(
                """CREATE TABLE IF NOT EXISTS position_audits (
                    backtest_id TEXT NOT NULL,
                    position_id TEXT NOT NULL,
                    audit_json TEXT NOT NULL,
                    PRIMARY KEY (backtest_id, position_id),
                    FOREIGN KEY (backtest_id) REFERENCES backtests(id) ON DELETE CASCADE
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS optimization_cache (
                    cache_key TEXT PRIMARY KEY,
                    data_fingerprint TEXT NOT NULL,
                    backtest_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (backtest_id) REFERENCES backtests(id) ON DELETE CASCADE
                )"""
            )
            # MA_BOX_LONG_V1 is an additive research namespace.  These tables
            # deliberately have no foreign keys into legacy backtests so an
            # experiment can never relabel or mutate historical production
            # results.
            db.execute(
                """CREATE TABLE IF NOT EXISTS ma_box_studies (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    ticker TEXT NOT NULL,
                    status TEXT NOT NULL,
                    strategy_revision TEXT NOT NULL,
                    spec_revision TEXT NOT NULL,
                    spec_revision_number INTEGER NOT NULL DEFAULT 3,
                    spec_hash TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    data_fingerprint TEXT,
                    provider TEXT,
                    config_json TEXT NOT NULL,
                    result_json TEXT
                )"""
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_ma_box_studies_created_at ON ma_box_studies(created_at DESC)")
            db.execute(
                """CREATE TABLE IF NOT EXISTS ma_box_runs (
                    study_id TEXT NOT NULL,
                    run_key TEXT NOT NULL,
                    sma_period INTEGER NOT NULL,
                    track TEXT NOT NULL,
                    status TEXT NOT NULL,
                    spec_revision_number INTEGER NOT NULL DEFAULT 3,
                    spec_hash TEXT NOT NULL DEFAULT '',
                    result_json TEXT,
                    PRIMARY KEY(study_id, run_key),
                    FOREIGN KEY(study_id) REFERENCES ma_box_studies(id) ON DELETE CASCADE
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS ma_box_events (
                    study_id TEXT NOT NULL,
                    run_key TEXT NOT NULL,
                    event_index INTEGER NOT NULL,
                    spec_revision_number INTEGER NOT NULL DEFAULT 3,
                    spec_hash TEXT NOT NULL DEFAULT '',
                    event_json TEXT NOT NULL,
                    PRIMARY KEY(study_id, run_key, event_index),
                    FOREIGN KEY(study_id) REFERENCES ma_box_studies(id) ON DELETE CASCADE
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS ma_box_counterfactual_trades (
                    study_id TEXT NOT NULL,
                    sma_period INTEGER NOT NULL,
                    trade_index INTEGER NOT NULL,
                    spec_revision_number INTEGER NOT NULL DEFAULT 3,
                    spec_hash TEXT NOT NULL DEFAULT '',
                    counterfactual_trade_id TEXT,
                    source_baseline_position_id TEXT,
                    entry_date TEXT,
                    entry_raw_fill REAL,
                    entry_actual_fill REAL,
                    entry_quantity INTEGER,
                    entry_commission REAL,
                    entry_slippage_cost REAL,
                    exit_date TEXT,
                    exit_reason TEXT,
                    exit_raw_fill REAL,
                    exit_actual_fill REAL,
                    exit_quantity INTEGER,
                    exit_commission REAL,
                    exit_slippage_cost REAL,
                    gross_pnl REAL,
                    net_pnl REAL,
                    mfe REAL,
                    mae REAL,
                    holding_days INTEGER,
                    trade_json TEXT NOT NULL,
                    PRIMARY KEY(study_id, sma_period, trade_index),
                    FOREIGN KEY(study_id) REFERENCES ma_box_studies(id) ON DELETE CASCADE
                )"""
            )
            # Additive, idempotent migrations for databases created by the
            # earlier implementation.  MA_BOX tables are independent of the
            # legacy connection semantics and currently have no production
            # rows, so the frozen revision default is safe for old test rows.
            migration_columns = {
                "ma_box_studies": {
                    "spec_revision_number": "INTEGER NOT NULL DEFAULT 3",
                },
                "ma_box_runs": {
                    "spec_revision_number": "INTEGER NOT NULL DEFAULT 3",
                    "spec_hash": "TEXT NOT NULL DEFAULT ''",
                },
                "ma_box_events": {
                    "spec_revision_number": "INTEGER NOT NULL DEFAULT 3",
                    "spec_hash": "TEXT NOT NULL DEFAULT ''",
                },
                "ma_box_counterfactual_trades": {
                    "spec_revision_number": "INTEGER NOT NULL DEFAULT 3",
                    "spec_hash": "TEXT NOT NULL DEFAULT ''",
                    "counterfactual_trade_id": "TEXT",
                    "source_baseline_position_id": "TEXT",
                    "entry_date": "TEXT",
                    "entry_raw_fill": "REAL",
                    "entry_actual_fill": "REAL",
                    "entry_quantity": "INTEGER",
                    "entry_commission": "REAL",
                    "entry_slippage_cost": "REAL",
                    "exit_date": "TEXT",
                    "exit_reason": "TEXT",
                    "exit_raw_fill": "REAL",
                    "exit_actual_fill": "REAL",
                    "exit_quantity": "INTEGER",
                    "exit_commission": "REAL",
                    "exit_slippage_cost": "REAL",
                    "gross_pnl": "REAL",
                    "net_pnl": "REAL",
                    "mfe": "REAL",
                    "mae": "REAL",
                    "holding_days": "INTEGER",
                },
            }
            for table, columns_to_add in migration_columns.items():
                existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
                for column, definition in columns_to_add.items():
                    if column not in existing:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            db.execute("PRAGMA optimize")

    def create_pending(self, request: dict[str, Any]) -> str:
        identifier = str(uuid.uuid4())
        with self._lock, self.connect() as db:
            db.execute(
                """INSERT INTO backtests
                (id, created_at, ticker, strategy, start_date, end_date, parameters_json, initial_capital, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'RUNNING')""",
                (
                    identifier,
                    datetime.now(timezone.utc).isoformat(),
                    request["ticker"], request["strategy"], request["start_date"], request["end_date"],
                    json.dumps(request, ensure_ascii=False), request["initial_capital"],
                ),
            )
        return identifier

    def complete(self, identifier: str, result: dict[str, Any], position_audits: dict[str, dict[str, Any]] | None = None) -> None:
        summary = result["summary"]
        with self._lock, self.connect() as db:
            db.execute(
                """UPDATE backtests SET final_equity=?, total_return=?, cagr=?, max_drawdown=?, sharpe=?, strategy_version=?, status='COMPLETED', result_json=? WHERE id=?""",
                (summary["final_equity"], summary["total_return"], summary["cagr"], summary["max_drawdown"], summary["sharpe_ratio"], result.get("strategy_version"), json.dumps(result, ensure_ascii=False), identifier),
            )
            db.execute("DELETE FROM position_audits WHERE backtest_id=?", (identifier,))
            for position_id, audit in (position_audits or {}).items():
                stored = {**audit, "backtest_id": identifier}
                db.execute(
                    "INSERT INTO position_audits (backtest_id, position_id, audit_json) VALUES (?, ?, ?)",
                    (identifier, position_id, json.dumps(stored, ensure_ascii=False)),
                )

    def fail(self, identifier: str, message: str) -> None:
        with self._lock, self.connect() as db:
            db.execute("UPDATE backtests SET status='FAILED', result_json=? WHERE id=?", (json.dumps({"error": message}), identifier))

    def list(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("""SELECT id, created_at, ticker, strategy, start_date, end_date, parameters_json,
                initial_capital, final_equity, total_return, cagr, max_drawdown, sharpe, strategy_version, status
                FROM backtests ORDER BY created_at DESC""").fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["parameters"] = json.loads(item.pop("parameters_json"))
            output.append(item)
        return output

    def get(self, identifier: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM backtests WHERE id=?", (identifier,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["parameters"] = json.loads(item.pop("parameters_json"))
        item["result"] = json.loads(item.pop("result_json")) if item.get("result_json") else None
        return item

    def get_position_audit(self, identifier: str, position_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT audit_json FROM position_audits WHERE backtest_id=? AND position_id=?",
                (identifier, position_id),
            ).fetchone()
        return json.loads(row["audit_json"]) if row else None

    def get_optimization_cache(self, cache_key: str, data_fingerprint: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                """SELECT b.* FROM optimization_cache c JOIN backtests b ON b.id=c.backtest_id
                WHERE c.cache_key=? AND c.data_fingerprint=? AND b.status='COMPLETED'""",
                (cache_key, data_fingerprint),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["parameters"] = json.loads(item.pop("parameters_json"))
        item["result"] = json.loads(item.pop("result_json")) if item.get("result_json") else None
        return item

    def put_optimization_cache(self, cache_key: str, data_fingerprint: str, backtest_id: str) -> None:
        with self._lock, self.connect() as db:
            db.execute(
                """INSERT INTO optimization_cache(cache_key,data_fingerprint,backtest_id,created_at)
                VALUES(?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET
                data_fingerprint=excluded.data_fingerprint,
                backtest_id=excluded.backtest_id,
                created_at=excluded.created_at""",
                (cache_key, data_fingerprint, backtest_id, datetime.now(timezone.utc).isoformat()),
            )

    def replace_position_audits(self, identifier: str, position_audits: dict[str, dict[str, Any]]) -> bool:
        """Atomically replace only the separately stored position-audit payloads.

        Backtest result JSON, summary fields, and execution history are
        deliberately not touched here.  This is used by audit-only repairs
        after their deterministic replay has proven that all strategy-result
        invariants are unchanged.
        """
        serialized: list[tuple[str, str]] = []
        for position_id, audit in position_audits.items():
            stored = {**audit, "backtest_id": identifier}
            serialized.append((position_id, json.dumps(stored, ensure_ascii=False)))

        with self._lock, self.connect() as db:
            exists = db.execute("SELECT 1 FROM backtests WHERE id=?", (identifier,)).fetchone()
            if exists is None:
                return False
            db.execute("DELETE FROM position_audits WHERE backtest_id=?", (identifier,))
            db.executemany(
                "INSERT INTO position_audits (backtest_id, position_id, audit_json) VALUES (?, ?, ?)",
                [(identifier, position_id, payload) for position_id, payload in serialized],
            )
        return True

    def delete(self, identifier: str) -> bool:
        with self._lock, self.connect() as db:
            db.execute("DELETE FROM position_audits WHERE backtest_id=?", (identifier,))
            cursor = db.execute("DELETE FROM backtests WHERE id=?", (identifier,))
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # MA_BOX_LONG_V1 additive research persistence
    # ------------------------------------------------------------------
    def create_ma_box_study(self, *, config: dict[str, Any], strategy_revision: str,
                            spec_revision: str, spec_hash: str, config_hash: str,
                            data_fingerprint: str | None, provider: str | None,
                            spec_revision_number: int = 3) -> str:
        identifier = str(uuid.uuid4())
        with self._lock, self.connect_ma_box() as db:
            db.execute(
                """INSERT INTO ma_box_studies
                (id,created_at,ticker,status,strategy_revision,spec_revision,spec_revision_number,spec_hash,
                 config_hash,data_fingerprint,provider,config_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (identifier, datetime.now(timezone.utc).isoformat(), str(config.get("ticker", "")).upper(),
                 "RUNNING", strategy_revision, spec_revision, int(spec_revision_number), spec_hash, config_hash,
                 data_fingerprint, provider, json.dumps(config, ensure_ascii=False, sort_keys=True)),
            )
        return identifier

    def complete_ma_box_study(self, identifier: str, result: dict[str, Any]) -> None:
        with self._lock, self.connect_ma_box() as db:
            db.execute(
                "UPDATE ma_box_studies SET status='COMPLETED',completed_at=?,result_json=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), json.dumps(result, ensure_ascii=False), identifier),
            )
            db.execute("DELETE FROM ma_box_runs WHERE study_id=?", (identifier,))
            db.execute("DELETE FROM ma_box_events WHERE study_id=?", (identifier,))
            db.execute("DELETE FROM ma_box_counterfactual_trades WHERE study_id=?", (identifier,))
            for period, bundle in result.get("runs", {}).items():
                for track, run in bundle.items():
                    run_key = f"{period}:{track}"
                    db.execute(
                        "INSERT INTO ma_box_runs(study_id,run_key,sma_period,track,status,spec_revision_number,spec_hash,result_json) VALUES(?,?,?,?,?,?,?,?)",
                        (identifier, run_key, int(period), track, "COMPLETED", int(run.get("spec_revision_number", 3)),
                         str(run.get("spec_hash", "")), json.dumps(run, ensure_ascii=False)),
                    )
                    for event_index, event in enumerate(run.get("events", [])):
                        db.execute(
                            "INSERT INTO ma_box_events(study_id,run_key,event_index,spec_revision_number,spec_hash,event_json) VALUES(?,?,?,?,?,?)",
                            (identifier, run_key, event_index, int(event.get("spec_revision_number", 3)),
                             str(event.get("spec_hash", "")), json.dumps(event, ensure_ascii=False)),
                        )
                    for trade_index, trade in enumerate(run.get("counterfactual_trades", [])):
                        trade_fields = (
                            str(trade.get("counterfactual_trade_id", f"counterfactual-{trade.get('position_id', trade_index)}")),
                            str(trade.get("source_baseline_position_id", trade.get("position_id", ""))),
                            trade.get("entry_date"), trade.get("entry_raw_fill"), trade.get("entry_actual_fill"),
                            trade.get("entry_quantity", trade.get("initial_shares")), trade.get("entry_commission"),
                            trade.get("entry_slippage_cost"), trade.get("exit_date", trade.get("final_exit_date")),
                            trade.get("exit_reason", trade.get("exit_final_close_reason")), trade.get("exit_raw_fill"),
                            trade.get("exit_actual_fill"), trade.get("exit_quantity", trade.get("total_shares_sold")),
                            trade.get("exit_commission"), trade.get("exit_slippage_cost"), trade.get("gross_pnl"),
                            trade.get("net_pnl"), trade.get("mfe", trade.get("maximum_favorable_excursion")),
                            trade.get("mae", trade.get("maximum_adverse_excursion")), trade.get("holding_days"),
                        )
                        db.execute(
                            """INSERT INTO ma_box_counterfactual_trades(
                                study_id,sma_period,trade_index,spec_revision_number,spec_hash,
                                counterfactual_trade_id,source_baseline_position_id,entry_date,
                                entry_raw_fill,entry_actual_fill,entry_quantity,entry_commission,
                                entry_slippage_cost,exit_date,exit_reason,exit_raw_fill,
                                exit_actual_fill,exit_quantity,exit_commission,exit_slippage_cost,
                                gross_pnl,net_pnl,mfe,mae,holding_days,trade_json)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (identifier, int(period), trade_index, int(trade.get("spec_revision_number", 3)),
                             str(trade.get("spec_hash", "")), *trade_fields, json.dumps(trade, ensure_ascii=False)),
                        )
            bh = result.get("buy_and_hold")
            if bh is not None:
                db.execute(
                    "INSERT INTO ma_box_runs(study_id,run_key,sma_period,track,status,spec_revision_number,spec_hash,result_json) VALUES(?,?,?,?,?,?,?,?)",
                    (identifier, "bh:BUY_AND_HOLD", 0, "BUY_AND_HOLD", "COMPLETED", int(bh.get("spec_revision_number", 3)),
                     str(bh.get("spec_hash", "")), json.dumps(bh, ensure_ascii=False)),
                )

    def update_ma_box_study_identity(self, identifier: str, *, config_hash: str,
                                     data_fingerprint: str | None, provider: str | None) -> None:
        with self._lock, self.connect_ma_box() as db:
            db.execute(
                "UPDATE ma_box_studies SET config_hash=?,data_fingerprint=?,provider=? WHERE id=?",
                (config_hash, data_fingerprint, provider, identifier),
            )

    def fail_ma_box_study(self, identifier: str, message: str, *, error_code: str = "MA_BOX_STUDY_FAILED") -> None:
        with self._lock, self.connect_ma_box() as db:
            db.execute(
                "UPDATE ma_box_studies SET status='FAILED',completed_at=?,result_json=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), json.dumps({"error_code": error_code, "error_message": message}, ensure_ascii=False), identifier),
            )

    def list_ma_box_studies(self) -> list[dict[str, Any]]:
        with self.connect_ma_box() as db:
            rows = db.execute(
                "SELECT id,created_at,completed_at,ticker,status,strategy_revision,spec_revision,spec_revision_number,spec_hash,config_hash,data_fingerprint,provider,config_json FROM ma_box_studies ORDER BY created_at DESC"
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["config"] = json.loads(item.pop("config_json"))
            output.append(item)
        return output

    def get_ma_box_study(self, identifier: str) -> dict[str, Any] | None:
        with self.connect_ma_box() as db:
            row = db.execute("SELECT * FROM ma_box_studies WHERE id=?", (identifier,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["config"] = json.loads(item.pop("config_json"))
        item["result"] = json.loads(item.pop("result_json")) if item.get("result_json") else None
        return item

    def get_ma_box_run(self, study_id: str, period: int, track: str) -> dict[str, Any] | None:
        run_key = "bh:BUY_AND_HOLD" if track == "BUY_AND_HOLD" else f"{period}:{track}"
        with self.connect_ma_box() as db:
            row = db.execute("SELECT result_json FROM ma_box_runs WHERE study_id=? AND run_key=?", (study_id, run_key)).fetchone()
        return json.loads(row["result_json"]) if row and row["result_json"] else None
