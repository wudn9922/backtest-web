"""Read-only canonical inputs. Never construct a repository or call an API."""
import hashlib
import json
import sqlite3
import pandas as pd

from research import ROOT
from app.backtest.models import BacktestRequest

IDS = {"simple": "c7ccad72-5f93-4bfc-b7d4-3635138c6f75", "advanced": "f341e6a5-f7d4-4e72-b6a1-18ba09f71974"}
CACHE = ROOT / "data/cache/NVDA_1d_2020-12-03_2026-09-01.parquet"
EXPECTED_ADVANCED_SOURCE_SHA256 = "bfd021e54b45b72ab4a679e83e494b924691b21f6abca05beb83786e56f6d7b8"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def normalize_timestamps(value):
    """Comparison only: old saved Simple uses NY offset, newer Advanced uses UTC."""
    if isinstance(value, dict):
        return {k: normalize_timestamps(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_timestamps(v) for v in value]
    if isinstance(value, str) and len(value) >= 19 and value[4] == "-" and value[10] == "T":
        ts = pd.Timestamp(value)
        if ts.tzinfo is not None:
            return ts.tz_convert("UTC").isoformat()
    return value


def immutable_fingerprints():
    db = hashlib.sha256()
    with sqlite3.connect((ROOT / "data/backtests.sqlite3").as_uri() + "?mode=ro", uri=True) as conn:
        for table, order in [("backtests", "id"), ("position_audits", "backtest_id,position_id")]:
            for row in conn.execute(f"SELECT * FROM {table} ORDER BY {order}"):
                value = json.dumps(row, ensure_ascii=False).encode()
                db.update(len(value).to_bytes(8, "big")); db.update(value)
    source = hashlib.sha256()
    backend = ROOT / "backend"
    for path in sorted((backend / "app").rglob("*.py")):
        source.update(str(path.relative_to(backend)).encode()); source.update(path.read_bytes())
    return {"database_and_audits": db.hexdigest(), "production_source": source.hexdigest(),
            "parquet": hashlib.sha256(CACHE.read_bytes()).hexdigest()}


def load():
    source = ROOT / "backend/app/backtest/strategies/advanced_ma_breakout.py"
    if hashlib.sha256(source.read_bytes()).hexdigest() != EXPECTED_ADVANCED_SOURCE_SHA256:
        raise RuntimeError("Production Advanced source changed: revalidate the isolated research copy before use")
    frozen = {}
    with sqlite3.connect((ROOT / "data/backtests.sqlite3").as_uri() + "?mode=ro", uri=True) as conn:
        for name, ident in IDS.items():
            request, result = conn.execute("SELECT parameters_json,result_json FROM backtests WHERE id=?", (ident,)).fetchone()
            req = BacktestRequest.model_validate_json(request)
            res = json.loads(result)
            assert req.ticker == "NVDA" and req.execution_policy == "conservative" and res["strategy_version"] == 2
            frozen[name] = {"id": ident, "request": json.loads(request), "result": res,
                            "request_object": req, "result_sha256": digest(res)}
    a, s = frozen["advanced"], frozen["simple"]
    for key in ("start_date", "end_date", "initial_capital", "commission_pct", "slippage_pct", "position_size_pct"):
        assert a["request"][key] == s["request"][key]
    assert a["request"]["parameters"] == s["request"]["parameters"]
    assert normalize_timestamps(a["result"]["daily_data"]) == normalize_timestamps(s["result"]["daily_data"])
    daily = pd.read_parquet(CACHE)
    period = daily.loc[[a["request_object"].start_date <= t.date() <= a["request_object"].end_date for t in daily.index]]
    for saved, (ts, row) in zip(a["result"]["daily_data"], period.iterrows()):
        assert pd.Timestamp(saved["timestamp"]) == ts
        assert all(saved[k] == row[k] for k in ("open", "high", "low", "close", "volume"))
    assert len(period) == len(a["result"]["daily_data"])
    return frozen, daily
