"""Validation decisions happen at CLOSE; their scheduled exits happen at OPEN."""
from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3

import pytest

from app.backtest.audit import make_daily_audit
from app.backtest.models import BacktestRequest, Event, Execution
from app.backtest.strategies.base import Bar
from app.backtest.validation_audit import repair_scheduled_validation_cards
from app.db.repository import BacktestRepository
from app.db.validation_audit_repair import ValidationAuditRepairError, repair_validation_audits


def validation_audit(name, phase, *, day="2026-01-26", volume=124_799_600,
                     previous_volume=142_748_100, scheduled=False):
    stamp = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    request = BacktestRequest(ticker="NVDA", strategy="advanced",
                              start_date=date(2021, 9, 1), end_date=date(2026, 9, 1))
    before = {"state": "PENDING_FULL_EXIT_NEXT_OPEN" if scheduled else "LONG_VALIDATING_DAY1",
              "quantity": 627, "q0": 627, "entry_price": 188.96427814219666,
              "entry_day": "2026-01-23", "first_tp_triggered": False,
              "break_day_low": None, "break_day": None,
              "bias_extreme_active": False, "atr_extreme_active": False}
    after = {**before, "state": "CLOSED" if scheduled else "PENDING_FULL_EXIT_NEXT_OPEN",
             "quantity": 0 if scheduled else 627}
    metadata = {} if phase is None else {"phase": phase}
    event = Event(stamp, 186.057568359375, name,
                  186.93200550896393 if scheduled else previous_volume * 1.1,
                  186.93200550896393 if scheduled else volume,
                  627, after["quantity"], before["state"], after["state"], metadata)
    executions = []
    if scheduled:
        price = 186.89461910786213
        reason = "DAY2_CLOSE_CONFIRMATION_FAIL" if name.startswith("DAY2") else name
        executions = [Execution(stamp, "SELL", price, 627, price * 627,
                                price * 627 * .0005, 0, 0, "FINAL_EXIT", reason)]
    inputs = dict(request=request, bar=Bar(stamp, 186.93200550896393, 188.88960930416175,
                                          185.76343263076708, 186.2428436279297, volume),
                  current_ma=185.95069885253906, reference_ma=186.057568359375,
                  reference_atr=5.3, bias_sigma=.039, previous_day_volume=previous_volume,
                  open_snapshot=before, close_snapshot=after, events=[event], executions=executions)
    original = deepcopy(inputs)
    audit = make_daily_audit(**inputs)
    assert inputs == original  # The presentation layer cannot mutate engine inputs.
    return audit


def test_position67_close_volume_fail_is_shown_once_with_entry_day_values():
    row = validation_audit("VOLUME_CONFIRMATION_FAIL", "CLOSE", day="2026-01-23",
                           volume=142_748_100, previous_volume=139_636_600)
    validation = row["validations"]["entry_day_volume"]
    assert validation == {"current_volume": 142_748_100, "previous_day_volume": 139_636_600,
                          "increase_pct": pytest.approx(2.2282839885817918),
                          "required_pct": 10, "status": "FAIL"}
    assert row["events"][0]["metadata"]["phase"] == "CLOSE"


def test_position67_next_open_exit_does_not_repeat_entry_day_volume_validation():
    row = validation_audit("VOLUME_CONFIRMATION_FAIL", "OPEN", scheduled=True)
    assert row["validations"]["entry_day_volume"] is None
    event = row["events"][0]
    assert event["source_event"] == "VOLUME_CONFIRMATION_FAIL"
    assert event["metadata"]["phase"] == "OPEN"
    assert event["shares_sold"] == 627 and event["shares_remaining"] == 0
    assert event["execution_price"] == 186.89461910786213


@pytest.mark.parametrize("name", ["DAY2_CONFIRMATION_FAIL", "DAY2_CLOSE_CONFIRMATION_FAIL"])
def test_day2_scheduled_open_exit_is_not_a_new_close_validation(name):
    row = validation_audit(name, "OPEN", scheduled=True)
    assert row["validations"]["day2_confirmation"] is None
    assert row["events"][0]["shares_remaining"] == 0


@pytest.mark.parametrize("name,kind", [
    ("VOLUME_CONFIRMATION_PASS", "entry_day_volume"),
    ("VOLUME_CONFIRMATION_FAIL", "entry_day_volume"),
    ("DAY2_CONFIRMATION_PASS", "day2_confirmation"),
    ("DAY2_CONFIRMATION_FAIL", "day2_confirmation"),
])
def test_close_validation_is_preserved_but_missing_phase_is_not_guessed(name, kind):
    assert validation_audit(name, "CLOSE")["validations"][kind] is not None
    assert validation_audit(name, None)["validations"][kind] is None


def _historical_fixture(tmp_path):
    repo = BacktestRepository(tmp_path / "history.sqlite3")
    rid = repo.create_pending({"ticker": "NVDA", "strategy": "advanced",
                               "start_date": "2021-09-01", "end_date": "2026-09-01",
                               "initial_capital": 100000, "parameters": {}})
    first = validation_audit("VOLUME_CONFIRMATION_FAIL", "CLOSE", day="2026-01-23",
                             volume=142_748_100, previous_volume=139_636_600)
    final = validation_audit("VOLUME_CONFIRMATION_FAIL", "OPEN", scheduled=True)
    # Preserve the known historical reporting bug as migration input.
    final["validations"]["entry_day_volume"] = {
        "current_volume": 124_799_600, "previous_day_volume": 142_748_100,
        "increase_pct": -12.573547388721806, "required_pct": 10, "status": "FAIL",
    }
    position = {"position_id": "position-67", "entry_price": 188.96427814219666,
                "q0": 627, "gross_pnl": -1297.6762145277462,
                "net_pnl": -1415.5079788156436, "fees": 117.83176428789344}
    result = {"strategy_version": 2, "positions": [position],
              "executions": [deepcopy(final["events"][0])],
              "events": first["events"] + final["events"],
              "equity_curve": [{"equity": 98584.49202118436}],
              "summary": {"final_equity": 98584.49202118436, "total_return": -.014155079788156436,
                          "cagr": -.0028, "max_drawdown": -.02, "sharpe_ratio": -.1}}
    audit = {"position_id": "position-67", "position": position,
             "timeline": [first, final], "chart": {"executions": result["executions"]}}
    unaffected = {"position_id": "position-68", "timeline": [deepcopy(first)],
                  "chart": {"executions": []}}
    repo.complete(rid, result, {"position-67": audit, "position-68": unaffected})
    return repo, rid


def _raw_records(path):
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        return (db.execute("SELECT * FROM backtests ORDER BY id").fetchall(),
                db.execute("SELECT * FROM position_audits ORDER BY backtest_id, position_id").fetchall())


def test_historical_rebuild_only_changes_false_card_not_execution_pnl_or_equity(tmp_path):
    repo, rid = _historical_fixture(tmp_path)
    before = _raw_records(repo.path)
    original = repo.get_position_audit(rid, "position-67")
    preview = repair_validation_audits(repo.path)
    assert preview["affected_positions_before"] == preview["affected_daily_rows_before"] == 1
    assert preview["audit_copies_written"] == 0
    assert _raw_records(repo.path) == before
    assert not (tmp_path / "backups").exists()

    report = repair_validation_audits(repo.path, apply=True)
    assert report["audit_copies_written"] == 1
    assert report["remaining_incorrect_cards"] == 0
    assert report["backtests_sha256_before"] == report["backtests_sha256_after"]
    after = _raw_records(repo.path)
    assert after[0] == before[0]  # Entire results, metrics, executions, PnL and equity bytes.
    assert after[1][1] == before[1][1]  # Unaffected audit is not even reserialized.
    corrected = repo.get_position_audit(rid, "position-67")
    assert corrected["timeline"][0] == original["timeline"][0]
    assert corrected["timeline"][1]["validations"]["entry_day_volume"] is None
    corrected["timeline"][1]["validations"]["entry_day_volume"] = original["timeline"][1]["validations"]["entry_day_volume"]
    assert corrected == original
    assert _raw_records(Path(report["backup"])) == before
    assert repair_validation_audits(repo.path, apply=True)["backup"] is None
    assert _raw_records(repo.path) == after


@pytest.mark.parametrize("name", ["DAY2_CONFIRMATION_FAIL", "DAY2_CLOSE_CONFIRMATION_FAIL"])
def test_historical_day2_exit_card_removed_without_changing_true_close_card(name):
    decision = validation_audit("DAY2_CONFIRMATION_FAIL", "CLOSE")
    final = validation_audit(name, "OPEN", scheduled=True)
    final["validations"]["day2_confirmation"] = {"day1_close": 100, "day2_close": 100, "status": "FAIL"}
    original = {"timeline": [decision, final]}
    preserved = deepcopy(original)
    corrected, changes = repair_scheduled_validation_cards(original)
    assert original == preserved
    assert changes == [(1, "day2_confirmation")]
    assert corrected["timeline"][0] == decision
    assert corrected["timeline"][1]["validations"]["day2_confirmation"] is None
    assert corrected["timeline"][1]["events"] == final["events"]


def test_historical_repair_never_guesses_missing_metadata():
    row = validation_audit("VOLUME_CONFIRMATION_FAIL", None)
    row["validations"]["entry_day_volume"] = {"status": "FAIL"}
    audit = {"timeline": [row]}
    corrected, changes = repair_scheduled_validation_cards(audit)
    assert corrected == audit and changes == []


def test_rebuild_rejects_unrelated_audit_mutations(tmp_path, monkeypatch):
    repo, _ = _historical_fixture(tmp_path)
    before = _raw_records(repo.path)

    def corrupt_repair(audit):
        repaired, changes = repair_scheduled_validation_cards(audit)
        repaired["position"]["net_pnl"] = 999
        return repaired, changes

    monkeypatch.setattr("app.db.validation_audit_repair.repair_scheduled_validation_cards", corrupt_repair)
    with pytest.raises(ValidationAuditRepairError, match="protected audit fields"):
        repair_validation_audits(repo.path, apply=True)
    assert _raw_records(repo.path) == before


def test_rebuild_rolls_back_if_database_trigger_changes_backtest_results(tmp_path):
    repo, _ = _historical_fixture(tmp_path)
    with repo.connect() as db:
        db.execute("""CREATE TRIGGER unexpected_change AFTER UPDATE ON position_audits
                      BEGIN UPDATE backtests SET final_equity = 1; END""")
    before = _raw_records(repo.path)
    with pytest.raises(ValidationAuditRepairError, match="Backtest results changed"):
        repair_validation_audits(repo.path, apply=True)
    assert _raw_records(repo.path) == before
