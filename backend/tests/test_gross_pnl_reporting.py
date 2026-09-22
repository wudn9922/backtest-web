from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.backtests import repository as repository_dependency, router
from app.backtest.engine import BacktestEngine
from app.backtest.pnl_reporting import ReportingRepairError, corrected_gross_pnl
from app.backtest.portfolio import Portfolio
from app.db.gross_pnl_repair import repair_gross_pnl
from app.db.repository import BacktestRepository


def ledger(sales, commission=.05, slippage=.02, entry=100.0, quantity=100):
    portfolio = Portfolio(200_000, commission, slippage)
    stamp = datetime(2024, 7, 8, tzinfo=timezone.utc)
    portfolio.buy(stamp, entry, quantity, "ENTRY", "ENTRY_STOP_FILLED")
    for index, (price, qty) in enumerate(sales, start=1):
        portfolio.sell(stamp + timedelta(days=index), price, qty,
                       "FIRST_TP" if index < len(sales) else "PROTECTIVE_STOP", "test")
    daily = pd.DataFrame({"high": [200.] * (len(sales) + 1), "low": [90.] * (len(sales) + 1)},
                         index=pd.date_range(stamp, periods=len(sales) + 1))
    position = BacktestEngine._positions(portfolio.executions, daily)[0]
    return portfolio, position


@pytest.mark.parametrize("sales", [[(110., 100)], [(110., 50), (100., 50)],
                                   [(110., 50), (115., 10), (120., 10), (105., 30)]])
@pytest.mark.parametrize("commission,slippage", [(0, 0), (.05, 0), (0, .02), (.05, .02)])
def test_execution_price_gross_excludes_all_commissions_and_slippage_is_not_doubled(sales, commission, slippage):
    portfolio, position = ledger(sales, commission, slippage)
    executions = portfolio.executions
    gross = sum(e.price * e.quantity for e in executions[1:]) - executions[0].price * 100
    fees = sum(e.commission for e in executions)
    raw_pnl = sum(price * qty for price, qty in sales) - 100 * 100
    assert position["gross_pnl"] == pytest.approx(gross, abs=1e-9)
    assert position["fees"] == pytest.approx(fees)
    assert position["net_pnl"] == pytest.approx(gross - fees, abs=1e-9)
    assert position["net_pnl"] == pytest.approx(portfolio.cash - 200_000, abs=1e-9)
    assert gross == pytest.approx(raw_pnl - portfolio.total_slippage_cost, abs=1e-9)
    if slippage:
        assert abs(position["net_pnl"] - (gross - fees - portfolio.total_slippage_cost)) > 1


def test_nvda_position_36_regression():
    portfolio, position = ledger([(131.24217842474133, 455), (127.41959070363235, 456)],
                                 entry=127.39411188125611, quantity=911)
    assert [e.quantity for e in portfolio.executions] == [911, 455, 456]
    assert position["gross_pnl"] == pytest.approx(1715.7137081957626, abs=1e-8)
    assert position["fees"] == pytest.approx(116.93710398510697, abs=1e-8)
    assert position["net_pnl"] == 1598.7766042106523
    assert position["gross_pnl"] - position["fees"] == pytest.approx(position["net_pnl"], abs=1e-8)


def historical_fixture(tmp_path, *, legacy=False):
    repo = BacktestRepository(tmp_path / "history.sqlite3")
    portfolio, position = ledger([(110., 50), (105., 50)])
    position["gross_pnl"] -= sum(e.commission for e in portfolio.executions if e.side == "SELL")
    if legacy:
        for key in ("position_id", "fees", "realized_pnl", "q0", "final_return"):
            position.pop(key, None)
    result = {
        "strategy_version": None if legacy else 2,
        "positions": [position], "executions": [e.as_dict() for e in portfolio.executions],
        "summary": {"final_equity": portfolio.cash, "total_return": .01, "cagr": .02,
                    "max_drawdown": -.1, "sharpe_ratio": 1.},
        "equity_curve": [{"timestamp": "2024-07-08", "strategy": 200_000}],
        "events": [{"event": "UNCHANGED"}], "drawdown": [], "reproducibility": {"slippage_pct": .02},
    }
    rid = repo.create_pending({"ticker": "TEST", "strategy": "advanced", "start_date": "2024-07-08",
                               "end_date": "2024-07-11", "parameters": {}, "initial_capital": 200_000})
    audit = {"position-1": {"position": deepcopy(position), "timeline": [{"state": "UNCHANGED"}],
                             "chart": {"executions": result["executions"]}}} if not legacy else {}
    repo.complete(rid, result, audit)
    return repo, rid


@pytest.mark.parametrize("legacy", [False, True])
def test_historical_repair_only_changes_gross_and_is_idempotent(tmp_path, legacy):
    repo, rid = historical_fixture(tmp_path, legacy=legacy)
    original = repo.get(rid)
    original_audit = repo.get_position_audit(rid, "position-1")
    preview = repair_gross_pnl(repo.path)
    assert preview["positions_corrected"] == 1
    assert repo.get(rid) == original
    assert not (tmp_path / "backups").exists()
    report = repair_gross_pnl(repo.path, apply=True)
    assert report["positions_corrected"] == 1
    assert report["protected_fields_sha256_before"] == report["protected_fields_sha256_after"]
    current = repo.get(rid)
    corrected = current["result"]["positions"][0]["gross_pnl"]
    current["result"]["positions"][0]["gross_pnl"] = original["result"]["positions"][0]["gross_pnl"]
    assert current == original  # Every other column and nested result field is identical.
    if original_audit:
        current_audit = repo.get_position_audit(rid, "position-1")
        assert current_audit["position"]["gross_pnl"] == corrected
        current_audit["position"]["gross_pnl"] = original_audit["position"]["gross_pnl"]
        assert current_audit == original_audit
    with sqlite3.connect(report["backup"]) as db:
        saved = json.loads(db.execute("SELECT result_json FROM backtests WHERE id=?", (rid,)).fetchone()[0])
        assert saved == original["result"]
    second = repair_gross_pnl(repo.path, apply=True)
    assert second["positions_corrected"] == second["audit_copies_corrected"] == 0
    assert second["backup"] is None


def test_repair_refuses_corrupt_ledger_without_any_writes(tmp_path):
    repo, rid = historical_fixture(tmp_path)
    result = repo.get(rid)["result"]
    result["executions"][1]["quantity"] += 1
    with repo.connect() as db:
        db.execute("UPDATE backtests SET result_json=? WHERE id=?", (json.dumps(result), rid))
    before = repo.get(rid)
    before_audit = repo.get_position_audit(rid, "position-1")
    with pytest.raises(ReportingRepairError):
        repair_gross_pnl(repo.path, apply=True)
    assert repo.get(rid) == before
    assert repo.get_position_audit(rid, "position-1") == before_audit
    assert not (tmp_path / "backups").exists()


def test_repaired_api_history_and_inspector_share_the_same_gross_value(tmp_path):
    repo, rid = historical_fixture(tmp_path)
    history = repo.list()
    repair_gross_pnl(repo.path, apply=True)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[repository_dependency] = lambda: repo
    with TestClient(app) as client:
        result = client.get(f"/api/backtests/{rid}").json()["result"]
        audit = client.get(f"/api/backtests/{rid}/positions/position-1/audit").json()
        position = result["positions"][0]
        assert position == audit["position"]
        assert position["gross_pnl"] - position["fees"] == pytest.approx(position["net_pnl"])
        assert client.get("/api/backtests").json() == history


def test_reporting_correction_does_not_mutate_input():
    portfolio, position = ledger([(110., 50), (105., 50)])
    result = {"positions": [position], "executions": [e.as_dict() for e in portfolio.executions]}
    before = deepcopy(result)
    corrected, _, changes = corrected_gross_pnl(result)
    assert result == before == corrected
    assert changes == 0
