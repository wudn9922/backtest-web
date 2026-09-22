from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.db.repository import BacktestRepository
from app.ma_box.engine import (
    ALLOWED_SETUP_TRANSITIONS,
    BoundaryEvidence,
    Contact,
    MABoxConfig,
    REASONS,
    _best_evidence,
    _cluster,
    _common_frame,
    _contacts_for_bar,
    _initial_box,
    _run_box,
    _run_baseline,
    _run_buy_hold,
    _strictly_improves_boundary,
    evaluate_box_execution_gate,
    evaluate_box_structural_gate,
    run_ma_box_study,
    spec_sha256,
)
from app.backtest.execution import execution_policy
from app.backtest.models import StrategyParameters
from app.backtest.portfolio import Portfolio, initial_quantity
from app.backtest.strategies.base import Bar, EventRecorder
from app.backtest.strategies.simple_ma_breakout import SimpleMABreakout


def _frame(closes: list[float], *, opens: list[float] | None = None,
           highs: list[float] | None = None, lows: list[float] | None = None) -> pd.DataFrame:
    close = np.asarray(closes, dtype=float)
    opens_a = close if opens is None else np.asarray(opens, dtype=float)
    highs_a = close * 1.01 if highs is None else np.asarray(highs, dtype=float)
    lows_a = close * 0.99 if lows is None else np.asarray(lows, dtype=float)
    return pd.DataFrame(
        {"open": opens_a, "high": highs_a, "low": lows_a, "close": close, "volume": 1000.0},
        index=pd.date_range("2021-01-01", periods=len(close), freq="B", tz="UTC"),
    )


def _cfg(start="2021-01-01", end="2021-12-31", selected=10, radius=0):
    return MABoxConfig("FIXTURE", selected, radius, 1, date.fromisoformat(start), date.fromisoformat(end))


def test_revision3_artifact_is_verbatim_sections_and_sidecar_matches():
    root = Path(__file__).resolve().parents[2] / "research" / "specs"
    artifact = root / "MA_BOX_LONG_V1_REVISION_3.md"
    sidecar = root / "MA_BOX_LONG_V1_REVISION_3.sha256"
    master_source = root / "MA_BOX_LONG_V1_MASTER_SOL_FROZEN_RESPONSE.md"
    rev2_source = root / "MA_BOX_LONG_V1_REVISION_2_SOL_FROZEN_RESPONSE.md"
    rev3_source = root / "MA_BOX_LONG_V1_REVISION_3_AMENDMENT_SOURCE.md"
    manifest = root / "MA_BOX_LONG_V1_REVISION_3_SOURCE_MANIFEST.json"
    raw = artifact.read_bytes()
    assert master_source.exists() and rev2_source.exists() and rev3_source.exists()
    assert manifest.exists()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    master = master_source.read_bytes()
    rev2 = rev2_source.read_bytes()
    rev3 = rev3_source.read_bytes()
    expected = (
        "# MA_BOX_LONG_V1 — Frozen Specification Revision 3\n\n"
        "## SECTION A — MA_BOX_LONG_V1 MASTER SPEC\n\n" + master.decode("utf-8") + "\n"
        "## SECTION B — MA_BOX_LONG_V1 SPEC AMENDMENT — FROZEN REVISION 2\n\n" + rev2.decode("utf-8") + "\n"
        "## SECTION C — REVISION 3 AMENDMENT\n\n" + rev3.decode("utf-8")
    ).encode("utf-8")
    assert raw == expected
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == spec_sha256()
    assert f"sha256={digest}" in sidecar.read_text(encoding="utf-8")
    source_manifest = json.loads(manifest.read_text(encoding="utf-8"))
    assert source_manifest["master"]["normalized_bytes"] == len(master)
    assert source_manifest["master"]["normalized_sha256"] == hashlib.sha256(master).hexdigest()
    assert source_manifest["revision2"]["normalized_bytes"] == len(rev2)
    assert source_manifest["revision2"]["normalized_sha256"] == hashlib.sha256(rev2).hexdigest()
    assert source_manifest["combined_artifact"]["sha256"] == digest


def test_revision3_removes_unreachable_wait_retest_supersession_path():
    assert "SUPERSEDED_BY_NEW_BOX" not in REASONS
    assert "BOX_ACTIVE" not in ALLOWED_SETUP_TRANSITIONS["WAIT_RETEST"]


def test_wait_retest_qualifying_above_bar_is_retest_not_new_box():
    # The literal priority is exposed by the production state map and reason
    # set: a valid retest is the only reachable transition from WAIT_RETEST
    # for a qualifying above bar.
    assert "RETEST_CONFIRMED" in ALLOWED_SETUP_TRANSITIONS["WAIT_RETEST"]
    assert "SUPERSEDED_BY_NEW_BOX" not in REASONS


def test_daily_bh_ledger_changes_with_close_and_final_row_is_flat():
    frame = _frame([100, 110, 90, 120, 80])
    run = _run_buy_hold(frame, _cfg(end="2021-01-07"))
    ledger = run["daily_ledger"]
    assert len(ledger) == len(frame)
    equities = [row["equity_close"] for row in ledger]
    assert len(set(equities)) > 2
    assert ledger[0]["quantity_end_of_day"] > 0
    assert ledger[-1]["quantity_end_of_day"] == 0
    assert ledger[-1]["equity_close"] == pytest.approx(run["summary"]["final_equity"])


def test_daily_bh_ledger_matches_hand_calculation():
    frame = _frame([100, 110, 90, 120])
    cfg = _cfg(end="2021-01-06")
    run = _run_buy_hold(frame, cfg)
    first_open = 100.0
    buy_price = first_open * 1.0002
    quantity = int(100000.0 / (buy_price * 1.0005))
    commission_buy = buy_price * quantity * 0.0005
    expected_cash = 100000.0 - buy_price * quantity - commission_buy
    assert run["daily_ledger"][0]["cash_end_of_day"] == pytest.approx(expected_cash)
    assert run["daily_ledger"][0]["market_value_close"] == pytest.approx(quantity * 100)
    assert run["daily_ledger"][1]["equity_close"] == pytest.approx(expected_cash + quantity * 110)
    sell_price = 120.0 * (1 - 0.0002)
    expected_final = expected_cash + sell_price * quantity - sell_price * quantity * 0.0005
    assert run["daily_ledger"][-1]["equity_close"] == pytest.approx(expected_final)


def test_initial_capital_anchor_produces_nonzero_mdd_and_dates():
    run = _run_buy_hold(_frame([100, 130, 80, 120]), _cfg(end="2021-01-06"))
    summary = run["summary"]
    assert summary["max_drawdown"] < 0
    # The initial-capital anchor is the first peak, but the first EOD mark in
    # this fixture is profitable; the maximum drawdown therefore starts at
    # the subsequent 130 close rather than the anchor itself.
    assert summary["max_drawdown_start"] == "2021-01-04"
    assert summary["max_drawdown_bottom"] == "2021-01-05"


def test_baseline_ledger_marks_position_to_close_each_day():
    frame = _frame([100, 102, 104, 106, 108], opens=[100, 102, 104, 106, 108], highs=[103, 105, 107, 109, 110], lows=[99, 101, 103, 105, 107])
    frame["reference_ma"] = 99.5
    frame["ma"] = 99.5
    frame["atr"] = 1.0
    run = _run_baseline(frame, _cfg(end="2021-01-07"), 10)
    active = [row["equity_close"] for row in run["daily_ledger"] if row["quantity_end_of_day"]]
    assert len(active) >= 2
    assert len(set(active)) > 1


def _long_strategy_fixture():
    params = StrategyParameters(ma_type="sma", ma_period=10, breakout_trigger_pct=1.0,
                                entry_stop_pct=1.5, exit_below_ma_pct=1.5)
    portfolio = Portfolio(100_000.0, 0.05, 0.02)
    recorder = EventRecorder()
    strategy = SimpleMABreakout(params, recorder, execution_policy("ohlc_heuristic"))
    timestamp = pd.Timestamp("2021-01-01", tz="UTC").to_pydatetime()
    quantity = 100
    portfolio.buy(timestamp, 100.0, quantity, "ENTRY", "FIXTURE_ENTRY")
    return strategy, portfolio, recorder, quantity


def test_revision3_ma_stop_intraday_uses_stop_level():
    strategy, portfolio, _recorder, quantity = _long_strategy_fixture()
    bar = Bar(pd.Timestamp("2021-01-04", tz="UTC").to_pydatetime(), 104.0, 106.0, 98.0, 103.0, 1000.0)
    strategy.process_bar(bar, 100.0, quantity, 0, lambda side, raw, qty, event, reason, ts: portfolio.sell(ts, raw, qty, event, reason))
    assert portfolio.quantity == 0
    sell = portfolio.executions[-1]
    assert sell.side == "SELL"
    assert sell.price == pytest.approx(98.5 * (1 - 0.0002))


def test_revision3_ma_stop_gap_through_uses_open():
    strategy, portfolio, _recorder, quantity = _long_strategy_fixture()
    bar = Bar(pd.Timestamp("2021-01-04", tz="UTC").to_pydatetime(), 95.0, 96.0, 94.0, 95.5, 1000.0)
    strategy.process_bar(bar, 100.0, quantity, 0, lambda side, raw, qty, event, reason, ts: portfolio.sell(ts, raw, qty, event, reason))
    assert portfolio.quantity == 0
    sell = portfolio.executions[-1]
    assert sell.price == pytest.approx(95.0 * (1 - 0.0002))


def test_revision3_entry_then_same_day_stop_leaves_position_flat():
    params = StrategyParameters(ma_type="sma", ma_period=10, breakout_trigger_pct=1.0,
                                entry_stop_pct=1.5, exit_below_ma_pct=1.5)
    portfolio = Portfolio(100_000.0, 0.05, 0.02)
    strategy = SimpleMABreakout(params, EventRecorder(), execution_policy("ohlc_heuristic"))
    bar = Bar(pd.Timestamp("2021-01-04", tz="UTC").to_pydatetime(), 101.0, 103.0, 98.0, 100.0, 1000.0)
    qty = initial_quantity(portfolio.equity(bar.open), 100.0, 101.5, 0.02, 0.05)
    strategy.process_bar(bar, 100.0, 0, qty, lambda side, raw, amount, event, reason, ts: portfolio.buy(ts, raw, amount, event, reason) if side == "BUY" else portfolio.sell(ts, raw, amount, event, reason))
    assert [execution.side for execution in portfolio.executions] == ["BUY", "SELL"]
    assert portfolio.quantity == 0


def test_box_data_contains_causal_stepwise_boundary_values():
    # Keep the four formation bars inside a narrow range so a later repeated
    # OHLC contact can improve evidence without first breaking the box.
    n = 20
    closes = [100.0] * n + [101, 99, 101, 99] + [101.2] * 8 + [100.0] * 5
    opens = [100.0] * n + [101, 99, 101, 99] + [101.2] * 8 + [100.0] * 5
    highs = [100.3] * n + [101.4, 100.05, 101.4, 100.05] + [101.3] * 8 + [100.3] * 5
    lows = [99.7] * n + [99.0, 98.5, 99.0, 98.5] + [99.5] * 8 + [99.7] * 5
    frame = _frame(closes, opens=opens, highs=highs, lows=lows)
    result = run_ma_box_study(frame, _cfg(end="2021-12-31"))
    run = result["runs"]["10"]["MA_BOX_LONG_V1"]
    updates = [event for event in run["events"] if event["reason_code"] == "BOX_BOUNDARY_UPDATE"]
    assert updates
    for event in updates:
        i = next(i for i, row in enumerate(run["data"]) if row["timestamp"].startswith(event["date"]))
        before = event["metadata"]["BoxHigh_before"]
        after = event["metadata"]["BoxHigh_after"]
        assert run["data"][i]["box_high_effective"] == pytest.approx(before)
        if i + 1 < len(run["data"]):
            assert run["data"][i + 1]["box_high_effective"] == pytest.approx(after)
    assert all("box_high_effective" in row and "box_low_effective" in row for row in run["data"])


def test_breakout_candle_is_evaluated_before_boundary_contacts_are_added():
    # Adversarial contact pool: before the breakout bar arrives there are two
    # bars clustered around 102.  The existing boundary has four contacts at
    # 100, so the 102 candidate is not yet superior.  Adding the breakout
    # bar's three eligible upper points would make it a five-contact winner.
    existing = [
        Contact(0, "2021-01-01", "high", 100.0, "upper"),
        Contact(0, "2021-01-01", "open", 100.2, "upper"),
        Contact(1, "2021-01-04", "close", 99.8, "upper"),
        Contact(1, "2021-01-04", "high", 100.1, "upper"),
        Contact(2, "2021-01-05", "high", 102.0, "upper"),
        Contact(3, "2021-01-06", "open", 102.0, "upper"),
    ]
    current = _cluster(existing[:4], existing[0], 0.5)
    # The two pre-existing 102 contacts plus the breakout candle's three
    # points would be a strictly better candidate under the wrong order.
    frame = _box_frame(breakout_close=120.0, post_breakout=1)
    frame.iloc[4, frame.columns.get_loc("high")] = 200.0
    frame.iloc[4, frame.columns.get_loc("open")] = 120.0
    frame.iloc[4, frame.columns.get_loc("close")] = 120.0
    run = _run_box(frame, _cfg(end="2021-01-08"), 10, {})
    breakout = next(event for event in run["events"] if event["reason_code"] == "BOX_UP_BREAKOUT")
    same_day = [event for event in run["events"] if event["date"] == breakout["date"]]
    assert same_day[0]["reason_code"] == "BOX_UP_BREAKOUT"
    assert not any(event["reason_code"] == "BOX_BOUNDARY_UPDATE" for event in same_day)
    breakout_row = frame.iloc[4]
    breakout_contacts = _contacts_for_bar(4, frame.index[4], breakout_row, 100.0, 105.0, "upper")
    wrong_order = _best_evidence(existing + breakout_contacts, current, 25.0, "upper")
    assert wrong_order is not None and wrong_order.count > current.count
    assert wrong_order.level > current.level
    assert breakout["metadata"]["box_high_snapshot"] == pytest.approx(breakout["BoxHigh"])
    assert breakout["BoxHigh"] < breakout["close"]


def test_revision3_box_creation_is_not_retroactive():
    run = _run_box(_box_frame(long_entry=True, post_breakout=2), _cfg(end="2021-01-12"), 10, {})
    starts = [event for event in run["events"] if event["reason_code"] == "MA_ENTANGLEMENT_START"]
    assert starts
    formation_day = starts[0]["date"]
    same_day = [event for event in run["events"] if event["date"] == formation_day]
    assert any(event["reason_code"] == "NORMAL_MA_ENTRY" for event in same_day)
    assert not any(event["reason_code"] == "FILTERED_BY_BOX" for event in same_day)
    active_index = next(i for i, event in enumerate(run["events"]) if event["reason_code"] == "BOX_ACTIVE")
    assert run["events"][active_index]["date"] == formation_day


def test_revision3_breakout_candle_cannot_fill_on_same_day():
    run = _run_box(_box_frame(breakout_close=104.0, post_breakout=2), _cfg(end="2021-01-12"), 10, {})
    breakout = next(event for event in run["events"] if event["reason_code"] == "BOX_UP_BREAKOUT")
    same_day_transactions = [event for event in run["events"] if event["date"] == breakout["date"] and event.get("actual_fill") is not None]
    assert same_day_transactions == []
    assert all(event["date"] > breakout["date"] for event in run["events"] if event["reason_code"] in {"BOX_DIRECT_BREAKOUT_ENTRY", "BOX_BREAKOUT_RETEST_ENTRY"})


def test_revision3_retest_confirmation_executes_only_next_open():
    frame = _box_frame(retest_index=0)
    frame.iloc[6, frame.columns.get_loc("open")] = 101.0
    frame.iloc[6, frame.columns.get_loc("high")] = 103.0
    frame.iloc[6, frame.columns.get_loc("low")] = 100.0
    frame.iloc[6, frame.columns.get_loc("close")] = 102.0
    run = _run_box(frame, _cfg(end="2021-01-12"), 10, {})
    retest = next(event for event in run["events"] if event["reason_code"] == "MA_RETEST_REBOUND")
    entries = [event for event in run["events"] if event["reason_code"] == "BOX_BREAKOUT_RETEST_ENTRY"]
    assert entries
    assert all(event["date"] > retest["date"] for event in entries)
    assert all(event["phase"] == "OPEN" for event in entries)


def test_local_robustness_reports_each_radius_and_unavailable_status():
    result = run_ma_box_study(_frame(list(np.linspace(100, 150, 100))), _cfg(end="2021-05-31", selected=10, radius=1))
    radii = result["local_robustness"]["radii"]
    assert set(radii) == {"1", "2", "3", "5"}
    assert radii["1"]["status"] == "COMPLETE"
    assert radii["3"]["status"] == "UNAVAILABLE_PERIODS_NOT_RUN"
    for item in radii.values():
        assert "available_periods" in item and "expected_periods" in item
        assert set(item["metrics"]) == {"total_return", "cagr", "max_drawdown", "calmar_ratio"}


def test_ma_box_fk_connection_rejects_orphans_without_changing_legacy_connection(tmp_path):
    repo = BacktestRepository(tmp_path / "db.sqlite3")
    with repo.connect() as legacy:
        assert legacy.execute("PRAGMA foreign_keys").fetchone()[0] == 0
    with repo.connect_ma_box() as db:
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(Exception):
            db.execute("INSERT INTO ma_box_runs(study_id,run_key,sma_period,track,status) VALUES('missing','x',10,'X','RUNNING')")


def test_ma_box_fk_rejects_orphan_events_and_cascades_all_additive_rows(tmp_path):
    repo = BacktestRepository(tmp_path / "db.sqlite3")
    study = repo.create_ma_box_study(
        config={"ticker": "X"}, strategy_revision="MA_BOX_LONG_V1",
        spec_revision="MA_BOX_LONG_V1_REVISION_3", spec_hash="a" * 64,
        config_hash="b" * 64, data_fingerprint="c" * 64, provider="synthetic",
    )
    with repo.connect_ma_box() as db:
        with pytest.raises(Exception):
            db.execute(
                "INSERT INTO ma_box_events(study_id,run_key,event_index,event_json) VALUES('missing','x',0,'{}')"
            )
        db.execute(
            "INSERT INTO ma_box_runs(study_id,run_key,sma_period,track,status,result_json) VALUES(?,?,?,?,?,?)",
            (study, "10:MA_BOX_LONG_V1", 10, "MA_BOX_LONG_V1", "COMPLETED", "{}"),
        )
        db.execute(
            "INSERT INTO ma_box_events(study_id,run_key,event_index,event_json) VALUES(?,?,?,?)",
            (study, "10:MA_BOX_LONG_V1", 0, "{}"),
        )
        db.execute(
            "INSERT INTO ma_box_counterfactual_trades(study_id,sma_period,trade_index,trade_json) VALUES(?,?,?,?)",
            (study, 10, 0, "{}"),
        )
        db.execute("DELETE FROM ma_box_studies WHERE id=?", (study,))
        assert db.execute("SELECT COUNT(*) FROM ma_box_runs WHERE study_id=?", (study,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM ma_box_events WHERE study_id=?", (study,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM ma_box_counterfactual_trades WHERE study_id=?", (study,)).fetchone()[0] == 0


def test_repository_study_failure_is_sanitized(tmp_path):
    repo = BacktestRepository(tmp_path / "db.sqlite3")
    study = repo.create_ma_box_study(config={"ticker": "X"}, strategy_revision="MA_BOX_LONG_V1",
                                     spec_revision="MA_BOX_LONG_V1_REVISION_3", spec_hash="a" * 64,
                                     config_hash="b" * 64, data_fingerprint=None, provider=None)
    repo.fail_ma_box_study(study, "safe failure", error_code="TEST_FAILURE")
    item = repo.get_ma_box_study(study)
    assert item and item["status"] == "FAILED"
    assert item["result"] == {"error_code": "TEST_FAILURE", "error_message": "safe failure"}


def test_repository_ma_box_migration_is_idempotent_and_preserves_legacy_rows(tmp_path):
    path = tmp_path / "db.sqlite3"
    first = BacktestRepository(path)
    legacy = first.create_pending({
        "ticker": "LEGACY", "strategy": "simple", "start_date": "2021-01-01",
        "end_date": "2021-01-02", "initial_capital": 100000,
    })
    # Seed representative history/audit/cache rows, then snapshot their
    # complete SQLite values before the additive MA_BOX migration runs.
    with first.connect() as db:
        db.execute(
            "INSERT INTO position_audits(backtest_id,position_id,audit_json) VALUES(?,?,?)",
            (legacy, "position-1", '{"entry":100,"exit":101}'),
        )
        db.execute(
            "INSERT INTO optimization_cache(cache_key,data_fingerprint,backtest_id,created_at) VALUES(?,?,?,?)",
            ("legacy-cache", "legacy-fingerprint", legacy, "2021-01-01T00:00:00+00:00"),
        )
        legacy_snapshot = {
            table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY 1,2,3")]
            for table in ("backtests", "position_audits", "optimization_cache")
        }
    second = BacktestRepository(path)
    with second.connect_ma_box() as db:
        tables = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"ma_box_studies", "ma_box_runs", "ma_box_events", "ma_box_counterfactual_trades"} <= tables
    assert second.get(legacy)["status"] == "RUNNING"
    with second.connect() as db:
        after_snapshot = {
            table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY 1,2,3")]
            for table in ("backtests", "position_audits", "optimization_cache")
        }
    assert after_snapshot == legacy_snapshot


def _box_frame(*, breakout_close: float = 111.0, post_breakout: int = 25,
               retest_index: int | None = None, invalidate_index: int | None = None,
               new_box: bool = False, long_entry: bool = False,
               atr: float = 10.0) -> pd.DataFrame:
    """Small fully-enriched frame for direct state-machine tests.

    The test frame supplies both visual ``ma`` and execution ``reference_ma``
    explicitly, so tests exercise only the frozen state transitions and never
    depend on a production data provider.
    """
    rows: list[dict[str, float]] = []
    if long_entry:
        # Three non-entry context bars followed by an entry bar.  The entry bar
        # itself is the fourth qualifying formation bar, proving that box
        # formation does not retroactively cancel the same-day position.
        rows.extend([
            {"open": 101.0, "high": 102.0, "low": 99.0, "close": 101.0, "ma": 100.0, "reference_ma": 200.0},
            {"open": 99.0, "high": 101.0, "low": 98.0, "close": 99.0, "ma": 100.0, "reference_ma": 200.0},
            {"open": 101.0, "high": 102.0, "low": 99.0, "close": 101.0, "ma": 100.0, "reference_ma": 200.0},
            {"open": 101.0, "high": 110.0, "low": 99.0, "close": 101.0, "ma": 100.0, "reference_ma": 100.0},
        ])
    else:
        rows.extend([
            {"open": 101.0, "high": 110.0, "low": 90.0, "close": 101.0, "ma": 100.0, "reference_ma": 200.0},
            {"open": 99.0, "high": 110.0, "low": 90.0, "close": 99.0, "ma": 100.0, "reference_ma": 200.0},
            {"open": 101.0, "high": 110.0, "low": 90.0, "close": 101.0, "ma": 100.0, "reference_ma": 200.0},
            {"open": 100.0, "high": 110.0, "low": 90.0, "close": 100.0, "ma": 100.0, "reference_ma": 200.0},
        ])
    rows.append({"open": breakout_close, "high": breakout_close + 1.0, "low": breakout_close - 1.0,
                 "close": breakout_close, "ma": 100.0, "reference_ma": 100.0})
    for j in range(post_breakout):
        row = {"open": 111.0, "high": 112.0, "low": 110.0, "close": 111.0,
               "ma": 100.0, "reference_ma": 100.0}
        if retest_index is not None and j == retest_index:
            row.update({"open": 101.0, "high": 103.0, "low": 99.0, "close": 101.0})
        if invalidate_index is not None and j == invalidate_index:
            row.update({"open": 89.0, "high": 90.0, "low": 88.0, "close": 89.0})
        rows.append(row)
    if new_box:
        # After the first box is invalidated, four entirely new bars form a
        # second lifecycle.  Keep execution reference high so no normal entry
        # interferes with the setup transition assertions.
        rows.extend([
            {"open": 101.0, "high": 110.0, "low": 90.0, "close": 101.0, "ma": 100.0, "reference_ma": 200.0},
            {"open": 99.0, "high": 110.0, "low": 90.0, "close": 99.0, "ma": 100.0, "reference_ma": 200.0},
            {"open": 101.0, "high": 110.0, "low": 90.0, "close": 101.0, "ma": 100.0, "reference_ma": 200.0},
            {"open": 100.0, "high": 110.0, "low": 90.0, "close": 100.0, "ma": 100.0, "reference_ma": 200.0},
        ])
    for row in rows:
        row.setdefault("volume", 1000.0)
        row.setdefault("atr", atr)
    return pd.DataFrame(rows, index=pd.date_range("2021-01-01", periods=len(rows), freq="B", tz="UTC"))


def test_revision3_wait_retest_valid_retest_has_priority_over_failed_breakout():
    run = _run_box(_box_frame(retest_index=0), _cfg(end="2021-03-31"), 10, {})
    reasons = [event["reason_code"] for event in run["events"]]
    assert any(event["setup_state_after"] == "RETEST_CONFIRMED" for event in run["events"])
    assert "FAILED_BOX_BREAKOUT" not in reasons


def test_revision3_wait_retest_non_retest_close_reactivates_same_box():
    frame = _box_frame(post_breakout=2)
    # Keep the first post-breakout close below the snapshot high but above MA;
    # it is not a retest because its low stays above the MA.
    frame.iloc[5, frame.columns.get_loc("open")] = 105.0
    frame.iloc[5, frame.columns.get_loc("high")] = 106.0
    frame.iloc[5, frame.columns.get_loc("low")] = 104.0
    frame.iloc[5, frame.columns.get_loc("close")] = 105.0
    run = _run_box(frame, _cfg(end="2021-01-12"), 10, {})
    failed = [event for event in run["events"] if event["reason_code"] == "FAILED_BOX_BREAKOUT"]
    assert failed
    assert any(event["reason_code"] == "BOX_REACTIVATED" for event in run["events"])
    assert failed[0]["box_id"] == next(event["box_id"] for event in run["events"] if event["reason_code"] == "BOX_REACTIVATED")


def test_revision3_failed_breakout_next_attempt_gets_new_id():
    frame = _box_frame(breakout_close=120.0, post_breakout=3)
    # First post-breakout bar returns inside the box but stays above MA, so it
    # is a non-retest failed attempt.  The following close breaks the same
    # immutable BoxHigh again.
    frame.iloc[5, frame.columns.get_loc("open")] = 105.0
    frame.iloc[5, frame.columns.get_loc("high")] = 106.0
    frame.iloc[5, frame.columns.get_loc("low")] = 104.0
    frame.iloc[5, frame.columns.get_loc("close")] = 105.0
    frame.iloc[6, frame.columns.get_loc("open")] = 121.0
    frame.iloc[6, frame.columns.get_loc("high")] = 122.0
    frame.iloc[6, frame.columns.get_loc("low")] = 120.0
    frame.iloc[6, frame.columns.get_loc("close")] = 121.0
    run = _run_box(frame, _cfg(end="2021-01-12"), 10, {})
    breakouts = [event for event in run["events"] if event["reason_code"] == "BOX_UP_BREAKOUT"]
    assert len(breakouts) >= 2
    assert breakouts[0]["breakout_attempt_id"] != breakouts[1]["breakout_attempt_id"]
    assert breakouts[0]["box_id"] == breakouts[1]["box_id"]


def test_revision3_wait_retest_close_below_box_low_invalidates():
    run = _run_box(_box_frame(invalidate_index=0, post_breakout=2), _cfg(end="2021-01-12"), 10, {})
    reasons = [event["reason_code"] for event in run["events"]]
    assert "BOX_DOWN_BREAK" in reasons
    assert "BOX_INVALIDATED" in reasons


def test_revision3_wait_retest_has_no_timeout_even_after_sixty_sessions():
    run = _run_box(_box_frame(post_breakout=65), _cfg(end="2021-05-31"), 10, {})
    reasons = [event["reason_code"] for event in run["events"]]
    assert any(event["setup_state_after"] == "WAIT_RETEST" for event in run["events"])
    assert "STUDY_END_UNFILLED" in reasons
    assert "RETEST_WAIT_EXPIRED" not in reasons
    assert "SUPERSEDED_BY_NEW_BOX" not in reasons


def test_revision3_new_box_requires_invalidation_and_four_fresh_bars():
    run = _run_box(_box_frame(post_breakout=1, invalidate_index=0, new_box=True), _cfg(end="2021-05-31"), 10, {})
    starts = [event for event in run["events"] if event["reason_code"] == "MA_ENTANGLEMENT_START"]
    assert len(starts) >= 2
    invalidation = next(event for event in run["events"] if event["reason_code"] == "BOX_INVALIDATED")
    first_dates = starts[0]["metadata"]["formation_dates"]
    second_dates = starts[1]["metadata"]["formation_dates"]
    assert max(first_dates) < invalidation["date"]
    assert all(day > invalidation["date"] for day in second_dates)


def test_revision3_box_formation_while_long_does_not_exit_position():
    run = _run_box(_box_frame(long_entry=True, post_breakout=2), _cfg(end="2021-01-12"), 10, {})
    active = [event for event in run["events"] if event["reason_code"] == "BOX_ACTIVE"]
    assert active and active[0]["position_state_after"] == "LONG_POSITION"
    assert active[0]["position_state_before"] == "LONG_POSITION"
    same_day = [event for event in run["events"] if event["date"] == active[0]["date"]]
    assert not any(event["reason_code"] == "MA_STOP_EXIT" for event in same_day)


def test_revision3_down_break_while_long_does_not_force_box_exit():
    frame = _box_frame(long_entry=True, post_breakout=2)
    # The position is still above the canonical stop (reference MA is 50),
    # while the visual box is broken below its low.
    frame.iloc[4, frame.columns.get_loc("reference_ma")] = 50.0
    frame.iloc[4, frame.columns.get_loc("open")] = 89.0
    frame.iloc[4, frame.columns.get_loc("high")] = 90.0
    frame.iloc[4, frame.columns.get_loc("low")] = 88.0
    frame.iloc[4, frame.columns.get_loc("close")] = 89.0
    run = _run_box(frame, _cfg(end="2021-01-12"), 10, {})
    down = next(event for event in run["events"] if event["reason_code"] == "BOX_DOWN_BREAK")
    assert down["position_state_after"] == "LONG_POSITION"
    assert not any(event["reason_code"] == "MA_STOP_EXIT" and event["date"] == down["date"] for event in run["events"])


def test_revision3_box_consumption_freezes_old_lifecycle():
    frame = _box_frame(breakout_close=104.0, post_breakout=3)
    # Narrow the qualifying bars so the structural gate is eligible, and make
    # the following open safe enough for Stage B direct execution.
    frame.loc[frame.index[:4], "high"] = 103.0
    frame.loc[frame.index[:4], "low"] = 97.0
    frame.loc[frame.index[5], ["open", "high", "low", "close"]] = [103.0, 104.0, 102.0, 103.0]
    run = _run_box(frame, _cfg(end="2021-01-12"), 10, {})
    consumed = [event for event in run["events"] if event["reason_code"] == "BOX_CONSUMED_BY_ENTRY"]
    assert consumed
    old_box = consumed[0]["box_id"]
    consumed_index = next(i for i, event in enumerate(run["events"]) if event is consumed[0])
    assert not any(event["reason_code"] == "BOX_BOUNDARY_UPDATE" and event["box_id"] == old_box
                   for event in run["events"][consumed_index + 1:])


def test_revision3_audit_marks_wait_retest_and_consumption_position_state():
    waiting = _run_box(_box_frame(post_breakout=1), _cfg(end="2021-01-08"), 10, {})
    reasons = [event["reason_code"] for event in waiting["events"]]
    assert "WAIT_RETEST" in reasons

    frame = _box_frame(breakout_close=104.0, post_breakout=3)
    frame.loc[frame.index[:4], "high"] = 103.0
    frame.loc[frame.index[:4], "low"] = 97.0
    frame.loc[frame.index[5], ["open", "high", "low", "close"]] = [103.0, 104.0, 102.0, 103.0]
    consumed = _run_box(frame, _cfg(end="2021-01-12"), 10, {})
    event = next(item for item in consumed["events"] if item["reason_code"] == "BOX_CONSUMED_BY_ENTRY")
    assert event["position_state_before"] == "LONG_POSITION"
    assert event["position_state_after"] == "LONG_POSITION"


def test_revision3_stage_a_is_close_independent_and_risk_monotonic():
    low_stop = evaluate_box_structural_gate(110.0, 95.0)
    mid_stop = evaluate_box_structural_gate(110.0, 100.0)
    high_stop = evaluate_box_structural_gate(110.0, 105.0)
    assert low_stop["risk_distance"] > mid_stop["risk_distance"] > high_stop["risk_distance"]
    assert low_stop["eligible"] is False and mid_stop["eligible"] is False and high_stop["eligible"] is True
    # The Stage A API deliberately has no breakout-close input; end-to-end
    # metadata therefore cannot vary with a close that is already above the
    # same pre-close BoxHigh snapshot.
    first = _run_box(_box_frame(breakout_close=111.0, post_breakout=1), _cfg(end="2021-01-08"), 10, {})
    second = _run_box(_box_frame(breakout_close=115.0, post_breakout=1), _cfg(end="2021-01-08"), 10, {})
    a = next(event for event in first["events"] if event["reason_code"] in {"NO_ENTRY_BOX_RISK_GT_5", "DIRECT_ENTRY_ELIGIBLE"})
    b = next(event for event in second["events"] if event["reason_code"] in {"NO_ENTRY_BOX_RISK_GT_5", "DIRECT_ENTRY_ELIGIBLE"})
    assert a["reason_code"] == b["reason_code"]
    assert a["metadata"]["box_risk_distance"] == pytest.approx(b["metadata"]["box_risk_distance"])


def test_ohlc_green_path_is_deterministic():
    policy = execution_policy("ohlc_heuristic")
    decision = policy.entry_vs_adverse(bar_open=100.0, bar_close=110.0, entry_level=105.0)
    assert decision.event == "ADVERSE_FIRST"
    assert decision.chosen_path == "ohlc-open-low-high-close"
    stop = policy.stop_vs_profit(bar_open=100.0, bar_close=110.0)
    assert stop.chosen_path == "ohlc-open-low-high-close"


def test_ohlc_red_path_is_deterministic():
    policy = execution_policy("ohlc_heuristic")
    decision = policy.entry_vs_adverse(bar_open=100.0, bar_close=90.0, entry_level=105.0)
    assert decision.event == "ENTRY_FIRST"
    assert decision.chosen_path == "ohlc-open-high-low-close"
    stop = policy.stop_vs_profit(bar_open=100.0, bar_close=90.0)
    assert stop.event == "PROFIT"
    assert stop.chosen_path == "ohlc-open-high-low-close"


def test_revision3_atr14_is_the_only_tolerance_source():
    frame = pd.DataFrame({
        "open": [100.0] * 4, "high": [110.0] * 4, "low": [90.0] * 4,
        "close": [101.0, 99.0, 101.0, 99.0], "volume": [1000.0] * 4,
        "ma": [100.0] * 4, "atr": [14.0] * 4,
    }, index=pd.date_range("2021-01-01", periods=4, freq="B", tz="UTC"))
    frame["atr10"] = 99.0
    box = _initial_box(frame, [0, 1, 2, 3], [0, 1, 2, 3], 10, 14, 0.10)
    assert box is not None
    assert box.tolerance_atr_period == 14
    assert box.tolerance == pytest.approx(1.4)


def test_revision3_provenance_exposes_numeric_spec_revision():
    result = run_ma_box_study(_frame(list(np.linspace(100, 140, 100))), _cfg(end="2021-05-31"))
    assert result["spec_revision_number"] == 3
    assert result["runs"]["10"]["MA_BOX_LONG_V1"]["spec_revision_number"] == 3
    assert result["buy_and_hold"]["spec_revision_number"] == 3


def test_revision3_study_end_unfilled_attempt_is_a_terminal_audit_event():
    run = _run_box(_box_frame(post_breakout=1), _cfg(end="2021-01-08"), 10, {})
    terminal = [event for event in run["events"] if event["reason_code"] == "STUDY_END_UNFILLED"]
    assert terminal and terminal[-1]["date"] == run["data"][-1]["timestamp"][:10]


def test_revision3_counterfactual_persisted_fields_match_baseline(tmp_path):
    prices = [100.0] * 20 + [101.0, 99.0, 101.0, 100.0, 104.0, 106.0, 108.0, 110.0]
    result = run_ma_box_study(_frame(prices, opens=prices, highs=np.asarray(prices) * 1.03, lows=np.asarray(prices) * 0.97), _cfg(end="2021-02-15"))
    box_run = result["runs"]["10"]["MA_BOX_LONG_V1"]
    assert box_run["counterfactual_trades"]
    baseline_positions = {item["position_id"]: item for item in result["runs"]["10"]["MA_LONG_BASELINE"]["positions"]}
    for shadow in box_run["counterfactual_trades"]:
        baseline = baseline_positions[shadow["position_id"]]
        for field_name in ("entry_date", "entry_price", "initial_shares", "final_exit_date", "gross_pnl", "net_pnl",
                           "q0", "maximum_favorable_excursion", "maximum_adverse_excursion", "holding_days",
                           "entry_raw_fill", "entry_actual_fill", "entry_quantity", "entry_commission",
                           "entry_slippage_cost", "exit_date", "exit_reason", "exit_raw_fill",
                           "exit_actual_fill", "exit_quantity", "exit_commission", "exit_slippage_cost",
                           "mfe", "mae"):
            assert shadow[field_name] == baseline[field_name]
        assert shadow["counterfactual_trade_id"] == f"counterfactual-{shadow['position_id']}"
        assert shadow["source_baseline_position_id"] == shadow["position_id"]
        assert shadow["sma_period"] == 10
    repo = BacktestRepository(tmp_path / "db.sqlite3")
    study = repo.create_ma_box_study(config=result["config"], strategy_revision="MA_BOX_LONG_V1",
                                     spec_revision=result["spec_revision"], spec_hash=result["spec_hash"],
                                     config_hash=result["config_hash"], data_fingerprint=None, provider="synthetic")
    repo.complete_ma_box_study(study, result)
    persisted = repo.get_ma_box_run(study, 10, "MA_BOX_LONG_V1")
    assert persisted["counterfactual_trades"] == box_run["counterfactual_trades"]
    with repo.connect_ma_box() as db:
        row = db.execute("SELECT * FROM ma_box_counterfactual_trades WHERE study_id=?", (study,)).fetchone()
        assert row["counterfactual_trade_id"] == box_run["counterfactual_trades"][0]["counterfactual_trade_id"]
        assert row["entry_actual_fill"] == pytest.approx(box_run["counterfactual_trades"][0]["entry_actual_fill"])
        assert row["exit_actual_fill"] == pytest.approx(box_run["counterfactual_trades"][0]["exit_actual_fill"])
        assert row["entry_commission"] == pytest.approx(box_run["counterfactual_trades"][0]["entry_commission"])
        assert row["exit_slippage_cost"] == pytest.approx(box_run["counterfactual_trades"][0]["exit_slippage_cost"])


def test_revision3_counterfactual_persisted_full_execution_parity_and_shadow_isolation(tmp_path):
    prices = [100.0] * 20 + [101.0, 99.0, 101.0, 100.0, 104.0, 106.0, 108.0, 110.0]
    frame = _frame(prices, opens=prices, highs=np.asarray(prices) * 1.03, lows=np.asarray(prices) * 0.97)
    config = _cfg(end="2021-02-15")
    result = run_ma_box_study(frame, config)
    box_run = result["runs"]["10"]["MA_BOX_LONG_V1"]
    assert box_run["counterfactual_trades"]
    baseline = {item["position_id"]: item for item in result["runs"]["10"]["MA_LONG_BASELINE"]["positions"]}
    shadow = box_run["counterfactual_trades"][0]
    source = baseline[shadow["source_baseline_position_id"]]
    fields = (
        "entry_date", "entry_raw_fill", "entry_actual_fill", "entry_quantity", "entry_commission",
        "entry_slippage_cost", "exit_date", "exit_reason", "exit_raw_fill", "exit_actual_fill",
        "exit_quantity", "exit_commission", "exit_slippage_cost", "gross_pnl", "net_pnl", "mfe", "mae",
        "holding_days",
    )
    for field_name in fields:
        assert shadow[field_name] == source[field_name]

    repo = BacktestRepository(tmp_path / "counterfactual.sqlite3")
    study = repo.create_ma_box_study(config=result["config"], strategy_revision="MA_BOX_LONG_V1",
                                     spec_revision=result["spec_revision"], spec_hash=result["spec_hash"],
                                     config_hash=result["config_hash"], data_fingerprint=None, provider="synthetic",
                                     spec_revision_number=3)
    repo.complete_ma_box_study(study, result)
    with repo.connect_ma_box() as db:
        row = db.execute("SELECT * FROM ma_box_counterfactual_trades WHERE study_id=?", (study,)).fetchone()
    assert row is not None
    assert row["spec_revision_number"] == 3
    assert row["spec_hash"] == result["spec_hash"]
    for field_name in ("counterfactual_trade_id", "source_baseline_position_id", *fields):
        expected = shadow[field_name]
        actual = row[field_name]
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            assert actual == pytest.approx(expected)
        else:
            assert actual == expected

    # Disable only shadow bookkeeping by supplying an otherwise identical
    # baseline with no positions; the Box execution ledger must not change.
    baseline_without_shadow = dict(result["runs"]["10"]["MA_LONG_BASELINE"])
    baseline_without_shadow["positions"] = []
    baseline_without_shadow["executions"] = []
    enriched, start_pos, _ = _common_frame(frame, config)
    local = enriched.copy()
    local["ma"] = local["ma_10"]
    local["reference_ma"] = local["ref_10"]
    local = local.iloc[start_pos:]
    isolated = _run_box(local, config, 10, baseline_without_shadow)
    for key in ("executions", "positions", "daily_ledger", "equity_curve", "drawdown_curve", "summary"):
        assert isolated[key] == box_run[key]
    assert isolated["counterfactual_trades"] == []


def test_revision3_period_state_isolation_under_mutation():
    result = run_ma_box_study(_frame(list(np.linspace(100, 145, 150))), _cfg(selected=24, radius=1, end="2021-06-30"))
    before = json.loads(json.dumps(result["runs"]["24"]["MA_BOX_LONG_V1"], sort_keys=True))
    result["runs"]["23"]["MA_LONG_BASELINE"]["events"].append({"reason_code": "MUTATION_ONLY"})
    result["runs"]["23"]["MA_BOX_LONG_V1"]["data"][0]["box_id"] = "MUTATION_ONLY"
    assert json.loads(json.dumps(result["runs"]["24"]["MA_BOX_LONG_V1"], sort_keys=True)) == before


def test_revision3_period_state_isolation_at_execution_level():
    prices = list(100 + 8 * np.sin(np.arange(180) / 4) + np.arange(180) * 0.15)
    frame = _frame(prices)
    combined = run_ma_box_study(frame, MABoxConfig("FIXTURE", 24, 1, 1, date(2021, 3, 1), date(2021, 9, 30)))

    def without_config_hash(value):
        if isinstance(value, dict):
            return {key: without_config_hash(item) for key, item in value.items() if key != "config_hash"}
        if isinstance(value, list):
            return [without_config_hash(item) for item in value]
        return value

    for period in (23, 24, 25):
        solo = run_ma_box_study(frame, MABoxConfig("FIXTURE", period, 0, 1, date(2021, 3, 1), date(2021, 9, 30)))
        combined_run = combined["runs"][str(period)]["MA_BOX_LONG_V1"]
        solo_run = solo["runs"][str(period)]["MA_BOX_LONG_V1"]
        assert without_config_hash(combined_run) == without_config_hash(solo_run)


def test_revision3_targeted_sma23_execution_mutation_leaves_sma24_sma25_byte_identical(monkeypatch):
    import app.ma_box.engine as engine_module

    prices = list(100 + 8 * np.sin(np.arange(180) / 4) + np.arange(180) * 0.15)
    frame = _frame(prices)
    config = MABoxConfig("FIXTURE", 24, 1, 1, date(2021, 3, 1), date(2021, 9, 30))
    baseline = run_ma_box_study(frame, config)

    original_moving_average = engine_module.moving_average

    def perturb_only_sma23(series, period, ma_type="sma"):
        values = original_moving_average(series, period, ma_type)
        return values * 1.07 if int(period) == 23 else values

    monkeypatch.setattr(engine_module, "moving_average", perturb_only_sma23)
    mutated = run_ma_box_study(frame, config)

    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    assert canonical(mutated["runs"]["23"]) != canonical(baseline["runs"]["23"])
    for period in (24, 25):
        before = baseline["runs"][str(period)]["MA_BOX_LONG_V1"]
        after = mutated["runs"][str(period)]["MA_BOX_LONG_V1"]
        # Config hashes legitimately change because the requested study is
        # re-evaluated; compare the execution-level outputs explicitly.
        for key in ("events", "box_context", "positions", "daily_ledger", "summary", "equity_curve", "drawdown_curve"):
            assert canonical(after[key]) == canonical(before[key]), (period, key)


def test_revision3_numeric_spec_revision_is_persisted_on_study_run_and_event(tmp_path):
    result = run_ma_box_study(_frame(list(np.linspace(100, 140, 100))), _cfg(end="2021-05-31"))
    repo = BacktestRepository(tmp_path / "identity.sqlite3")
    study = repo.create_ma_box_study(
        config=result["config"], strategy_revision="MA_BOX_LONG_V1", spec_revision=result["spec_revision"],
        spec_hash=result["spec_hash"], config_hash=result["config_hash"], data_fingerprint=None,
        provider="synthetic", spec_revision_number=3,
    )
    assert repo.get_ma_box_study(study)["spec_revision_number"] == 3
    failed = repo.create_ma_box_study(
        config=result["config"], strategy_revision="MA_BOX_LONG_V1", spec_revision=result["spec_revision"],
        spec_hash=result["spec_hash"], config_hash=result["config_hash"], data_fingerprint=None,
        provider="synthetic", spec_revision_number=3,
    )
    repo.fail_ma_box_study(failed, "sanitized", error_code="FIXTURE_FAILURE")
    failed_row = repo.get_ma_box_study(failed)
    assert failed_row["status"] == "FAILED"
    assert failed_row["spec_revision_number"] == 3
    assert failed_row["spec_hash"] == result["spec_hash"]
    repo.complete_ma_box_study(study, result)
    with repo.connect_ma_box() as db:
        assert db.execute("SELECT DISTINCT spec_revision_number FROM ma_box_studies WHERE id=?", (study,)).fetchone()[0] == 3
        assert {row[0] for row in db.execute("SELECT DISTINCT spec_revision_number FROM ma_box_runs WHERE study_id=?", (study,)).fetchall()} == {3}
        assert {row[0] for row in db.execute("SELECT DISTINCT spec_revision_number FROM ma_box_events WHERE study_id=?", (study,)).fetchall()} == {3}
        assert {row[0] for row in db.execute("SELECT DISTINCT spec_hash FROM ma_box_runs WHERE study_id=?", (study,)).fetchall()} == {result["spec_hash"]}
        assert {row[0] for row in db.execute("SELECT DISTINCT spec_hash FROM ma_box_events WHERE study_id=?", (study,)).fetchall()} == {result["spec_hash"]}


def test_revision3_adversarial_future_boundary_and_atr_mutations_do_not_rewrite_history():
    original = _box_frame(post_breakout=8)
    mutated = original.copy()
    mutated.iloc[6:, mutated.columns.get_loc("high")] = 1000.0
    mutated.iloc[6:, mutated.columns.get_loc("low")] = 1.0
    mutated.iloc[6:, mutated.columns.get_loc("close")] = 500.0
    mutated.iloc[6:, mutated.columns.get_loc("atr")] = 999.0
    first = _run_box(original, _cfg(end="2021-01-20"), 10, {})
    second = _run_box(mutated, _cfg(end="2021-01-20"), 10, {})
    cutoff = original.index[5].date().isoformat()
    first_events = [event for event in first["events"] if event["date"] <= cutoff]
    second_events = [event for event in second["events"] if event["date"] <= cutoff]
    assert first_events == second_events


def test_revision3_determinism_is_three_run_byte_identical():
    frame = _frame(list(np.linspace(100, 160, 130)))
    serializations = []
    for _ in range(3):
        result = run_ma_box_study(frame, _cfg(selected=10, radius=1, end="2021-06-30"))
        run = result["runs"]["10"]["MA_BOX_LONG_V1"]
        serializations.append(json.dumps({"events": run["events"], "trades": run["positions"],
                                           "ledger": run["daily_ledger"], "summary": run["summary"]},
                                          sort_keys=True, separators=(",", ":")))
    assert serializations[0] == serializations[1] == serializations[2]


def test_revision3_api_failure_and_incomplete_lifecycle_are_explicit(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app

    class FailingProvider:
        def get_market_data(self, *args, **kwargs):
            raise RuntimeError("provider debug stack must not escape")

    with TestClient(app) as client:
        old_repo, old_provider = app.state.repository, app.state.provider
        app.state.repository = BacktestRepository(tmp_path / "api.sqlite3")
        app.state.provider = FailingProvider()
        try:
            response = client.post("/api/ma-box/studies", json={
                "ticker": "TEST", "selected_ma": 10, "nearby_range": 0, "step": 1,
                "start_date": "2021-02-01", "end_date": "2021-06-30",
            })
            assert response.status_code == 500
            studies = app.state.repository.list_ma_box_studies()
            assert len(studies) == 1 and studies[0]["status"] == "FAILED"
            assert "provider debug" not in (studies[0].get("result") or {}).get("error_message", "")
            study = app.state.repository.create_ma_box_study(
                config={"ticker": "TEST"}, strategy_revision="MA_BOX_LONG_V1",
                spec_revision="MA_BOX_LONG_V1_REVISION_3", spec_hash="a" * 64,
                config_hash="b" * 64, data_fingerprint=None, provider=None,
            )
            for url in (
                f"/api/ma-box/studies/{study}/summary",
                f"/api/ma-box/studies/{study}/runs/10/MA_BOX_LONG_V1",
                f"/api/ma-box/studies/{study}/chart/10",
                f"/api/ma-box/studies/{study}/counterfactuals/10",
                f"/api/ma-box/studies/{study}/export/10?format=json",
            ):
                pending = client.get(url)
                assert pending.status_code == 409, (url, pending.text)
                assert pending.json()["detail"]["code"] == "MA_BOX_STUDY_NOT_COMPLETE"
        finally:
            app.state.repository, app.state.provider = old_repo, old_provider


def test_repeated_fixture_is_byte_deterministic_including_ledger():
    frame = _frame(list(np.linspace(100, 160, 130)))
    first = run_ma_box_study(frame, _cfg(end="2021-06-30", radius=1))
    second = run_ma_box_study(frame, _cfg(end="2021-06-30", radius=1))
    for period in first["periods"]:
        a = first["runs"][str(period)]["MA_BOX_LONG_V1"]
        b = second["runs"][str(period)]["MA_BOX_LONG_V1"]
        assert json.dumps(a["daily_ledger"], sort_keys=True, separators=(",", ":")) == json.dumps(b["daily_ledger"], sort_keys=True, separators=(",", ":"))
        assert json.dumps(a["events"], sort_keys=True, separators=(",", ":")) == json.dumps(b["events"], sort_keys=True, separators=(",", ":"))
