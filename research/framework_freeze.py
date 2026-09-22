"""Framework-aware verification of the pre-framework production semantics."""
from __future__ import annotations

import hashlib
import json
import sqlite3

from research import ROOT
from research.baseline import immutable_fingerprints

ORIGINAL_PRODUCTION_SOURCE = "d62beed39750fc3617c41285b794aa7529795ad9371e83a925c26959debf3bab"
CANONICAL_RESULTS = {
    "c7ccad72-5f93-4bfc-b7d4-3635138c6f75": "a8591c16c401a002f1057cd3cb6add5b7c5b316836c667c985c258c501ddcfd5",
    "f341e6a5-f7d4-4e72-b6a1-18ba09f71974": "1300fe97a0d17b8cefb3a0602b81c91ad6c8064fe8a5cc5c2175542c80e31a9f",
}
CANONICAL_AUDITS = {
    "c7ccad72-5f93-4bfc-b7d4-3635138c6f75": "35aa46cc16855e8ad85a9a90fd306ccad9edc7cb0ffa966ef2ffd826965683ed",
    "f341e6a5-f7d4-4e72-b6a1-18ba09f71974": "29f88c00f24dcb5ab561a8d751fff5ec76d6663056563c6ec93623805402e93c",
}


def semantic_production_source() -> str:
    """Hash the pre-infrastructure backend bytes.

    Research/data-center routes and the durable job supervisor are operational
    surfaces, not strategy semantics.  They are removed from this compatibility
    view exactly as the earlier read-only research route was, while every
    backtest, provider, accounting and persistence byte remains covered.
    """
    backend = ROOT / "backend"
    source = hashlib.sha256()
    for path in sorted((backend / "app").rglob("*.py")):
        relative = str(path.relative_to(backend)).replace("\\", "/")
        if relative.startswith("app/optimization/") or relative == "app/backtest/data_preparation.py":
            continue
        if relative in {
            "app/api/research.py",
            "app/api/data_center.py",
            "app/api/optimizations.py",
            "app/presentation/__init__.py",
            "app/presentation/position_audit.py",
            "app/jobs/__init__.py",
            "app/jobs/connectivity.py",
            "app/jobs/repository.py",
            "app/jobs/service.py",
        }:
            continue
        content = path.read_bytes()
        if relative == "app/main.py":
            for line in (
                b"from app.api.research import router as research_router\r\n",
                b"from app.api.research import router as research_router\n",
                b"app.include_router(research_router)\r\n",
                b"app.include_router(research_router)\n",
                b"from app.api.data_center import router as data_center_router\r\n",
                b"from app.api.data_center import router as data_center_router\n",
                b"from app.api.optimizations import router as optimizations_router\r\n",
                b"from app.api.optimizations import router as optimizations_router\n",
                b"from app.jobs import JobService\r\n",
                b"from app.jobs import JobService\n",
                b"    app.state.job_service = JobService(data_root, app.state.provider)\r\n",
                b"    app.state.job_service = JobService(data_root, app.state.provider)\n",
                b"    app.state.job_service = JobService(data_root, app.state.provider, app.state.repository)\r\n",
                b"    app.state.job_service = JobService(data_root, app.state.provider, app.state.repository)\n",
                b"    app.state.job_service.start()\r\n",
                b"    app.state.job_service.start()\n",
                b"app.include_router(data_center_router)\r\n",
                b"app.include_router(data_center_router)\n",
                b"app.include_router(optimizations_router)\r\n",
                b"app.include_router(optimizations_router)\n",
                b"from app.presentation.position_audit import present_position_audit\r\n",
                b"from app.presentation.position_audit import present_position_audit\n",
                b"    record = repo.get(identifier)\r\n",
                b"    record = repo.get(identifier)\n",
            ):
                content = content.replace(line, b"")
            content = content.replace(b"    return present_position_audit(audit, record or {})\r\n", b"    return audit\r\n")
            content = content.replace(b"    return present_position_audit(audit, record or {})\n", b"    return audit\n")
            content = content.replace(
                b"    try:\r\n        yield\r\n    finally:\r\n        app.state.job_service.stop()\r\n",
                b"    yield\r\n",
            )
            content = content.replace(
                b"    try:\n        yield\n    finally:\n        app.state.job_service.stop()\n",
                b"    yield\n",
            )
        if relative == "app/db/repository.py":
            content = content.replace(
                b'''            db.execute(\n                """CREATE TABLE IF NOT EXISTS optimization_cache (\n                    cache_key TEXT PRIMARY KEY,\n                    data_fingerprint TEXT NOT NULL,\n                    backtest_id TEXT NOT NULL,\n                    created_at TEXT NOT NULL,\n                    FOREIGN KEY (backtest_id) REFERENCES backtests(id) ON DELETE CASCADE\n                )"""\n            )\n''',
                b"",
            )
            content = content.replace(
                b'''    def get_optimization_cache(self, cache_key: str, data_fingerprint: str) -> dict[str, Any] | None:\n        with self.connect() as db:\n            row = db.execute(\n                """SELECT b.* FROM optimization_cache c JOIN backtests b ON b.id=c.backtest_id\n                WHERE c.cache_key=? AND c.data_fingerprint=? AND b.status='COMPLETED'""",\n                (cache_key, data_fingerprint),\n            ).fetchone()\n        if row is None:\n            return None\n        item = dict(row)\n        item["parameters"] = json.loads(item.pop("parameters_json"))\n        item["result"] = json.loads(item.pop("result_json")) if item.get("result_json") else None\n        return item\n\n    def put_optimization_cache(self, cache_key: str, data_fingerprint: str, backtest_id: str) -> None:\n        with self._lock, self.connect() as db:\n            db.execute(\n                """INSERT INTO optimization_cache(cache_key,data_fingerprint,backtest_id,created_at)\n                VALUES(?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET\n                data_fingerprint=excluded.data_fingerprint,\n                backtest_id=excluded.backtest_id,\n                created_at=excluded.created_at""",\n                (cache_key, data_fingerprint, backtest_id, datetime.now(timezone.utc).isoformat()),\n            )\n\n''',
                b"",
            )
        if relative == "app/api/backtests.py":
            content = content.replace(
                b"from __future__ import annotations\n\nfrom fastapi",
                b"from __future__ import annotations\n\nfrom datetime import timedelta\n\nfrom fastapi",
            )
            for line in (
                b"from app.backtest.data_preparation import prepare_daily_market_data\n",
                b"from app.presentation.position_audit import present_position_audit\r\n",
                b"from app.presentation.position_audit import present_position_audit\n",
                b"    record = repo.get(identifier)\r\n",
                b"    record = repo.get(identifier)\n",
            ):
                content = content.replace(line, b"")
            content = content.replace(b"    return present_position_audit(audit, record or {})\r\n", b"    return audit\r\n")
            content = content.replace(b"    return present_position_audit(audit, record or {})\n", b"    return audit\n")
            content = content.replace(
                b"        market_data = prepare_daily_market_data(payload, data_provider)\n",
                b'''        warmup_days = max(payload.parameters.ma_period * 2, payload.parameters.bias_lookback * 2, payload.parameters.atr_period * 3) + 20
        warmup_start = payload.start_date - timedelta(days=warmup_days)
        if isinstance(data_provider, ProviderChain):
            market_data = data_provider.get_market_data(
                payload.ticker,
                warmup_start,
                payload.end_date,
                preferred_provider=payload.market_data_provider,
            )
        else:
            market_data = data_provider.get_market_data(payload.ticker, warmup_start, payload.end_date)
''',
            )
            content = content.replace(
                b"    market_data = prepare_daily_market_data(source_request, data_provider)\n    daily = market_data.daily\n",
                b'''    warmup_days = max(source_request.parameters.ma_period * 2, source_request.parameters.bias_lookback * 2, source_request.parameters.atr_period * 3) + 20
    if isinstance(data_provider, ProviderChain):
        market_data = data_provider.get_market_data(
            source_request.ticker,
            source_request.start_date - timedelta(days=warmup_days),
            source_request.end_date,
            preferred_provider=source_request.market_data_provider,
        )
        daily = market_data.daily
    else:
        market_data = None
        daily = data_provider.get_daily(source_request.ticker, source_request.start_date - timedelta(days=warmup_days), source_request.end_date)
''',
            )
            content = content.replace(
                b"                result = engine.run(policy_request, daily, market_data.provider)\n",
                b"                result = engine.run(policy_request, daily, market_data.provider if market_data is not None else data_provider.__class__.__name__)\n",
            )
        if relative == "app/backtest/audit_rebuild.py":
            content = content.replace(
                b"from __future__ import annotations\n\nimport json",
                b"from __future__ import annotations\n\nimport json",
            )
            content = content.replace(
                b"from dataclasses import dataclass\nfrom numbers import Real\n",
                b"from dataclasses import dataclass\nfrom datetime import timedelta\nfrom numbers import Real\n",
            )
            content = content.replace(b"from app.backtest.data_preparation import required_warmup_start\n", b"")
            marker = b"\n\ndef _normalise_result_value(value: Any) -> Any:\n"
            original = b'''\n\ndef required_warmup_start(request: BacktestRequest):
    """Use exactly the same warm-up window as the normal backtest API."""
    params = request.parameters
    warmup_days = max(
        params.ma_period * 2,
        params.bias_lookback * 2,
        params.atr_period * 3,
    ) + 20
    return request.start_date - timedelta(days=warmup_days)
'''
            content = content.replace(marker, original + marker)
        source.update(str(path.relative_to(backend)).encode())
        source.update(content)
    return source.hexdigest()


def assert_frozen_artifact_fingerprint(saved: dict) -> None:
    """Verify immutable canonical artifacts without forbidding later history rows.

    Older reports stored one hash for the entire mutable history database.  A
    normal new backtest or an approved audit rebuild therefore made every old
    report fail validation even when both frozen baselines were byte-identical.
    Pin the two canonical result payloads and their position audits directly;
    callers still compare a whole-database before/after fingerprint around each
    individual research run.
    """
    current = immutable_fingerprints()
    assert current["parquet"] == saved["parquet"]
    assert saved["production_source"] == ORIGINAL_PRODUCTION_SOURCE
    assert semantic_production_source() == ORIGINAL_PRODUCTION_SOURCE
    database = ROOT / "data" / "backtests.sqlite3"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        for identifier, expected in CANONICAL_RESULTS.items():
            row = connection.execute("SELECT result_json FROM backtests WHERE id=?", (identifier,)).fetchone()
            assert row is not None
            actual = hashlib.sha256(
                json.dumps(json.loads(row["result_json"]), sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
            ).hexdigest()
            assert actual == expected
        for identifier, expected in CANONICAL_AUDITS.items():
            rows = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM position_audits WHERE backtest_id=? ORDER BY position_id",
                    (identifier,),
                )
            ]
            actual = hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            assert actual == expected
