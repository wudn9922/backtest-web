from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd

from app.ma_box.engine import MABoxConfig, evaluate_box_execution_gate, evaluate_box_structural_gate, run_ma_box_study, spec_sha256


class FakeProvider:
    def __init__(self, frame):
        self.frame = frame

    def get_market_data(self, ticker, start, end):
        from app.data.base import MarketData
        return MarketData(self.frame, "fake", [], {"provider_display_name": "Fake", "adjustment_mode": "test"})


def frame_from_prices(prices: list[float], *, spread: float = 0.01) -> pd.DataFrame:
    close = np.asarray(prices, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * (1 + spread),
            "low": close * (1 - spread),
            "close": close,
            "volume": 1000.0,
        },
        index=pd.date_range("2021-01-01", periods=len(close), freq="B", tz="UTC"),
    )


def cfg(selected=10, radius=0, start="2021-01-01", end="2021-12-31"):
    return MABoxConfig("TEST", selected, radius, 1, date.fromisoformat(start), date.fromisoformat(end))


def test_revision_three_spec_artifact_is_immutable_and_hashed():
    digest = spec_sha256()
    assert len(digest) == 64
    manifest = Path(__file__).resolve().parents[2] / "research" / "specs" / "MA_BOX_LONG_V1_REVISION_3_SOURCE_MANIFEST.json"
    expected = json.loads(manifest.read_text(encoding="utf-8"))["combined_artifact"]["sha256"]
    assert digest == expected
    assert digest != "44173f0e3666fed4aec8906627904446dca242db2dffbaf71d254ffa6c5b7d1b"


def test_study_rejects_non_frozen_execution_configuration():
    prices = list(np.linspace(100, 140, 100))
    with np.testing.assert_raises(ValueError):
        run_ma_box_study(frame_from_prices(prices), MABoxConfig("TEST", 10, 0, 1,
                          date(2021, 1, 1), date(2021, 12, 31), slippage_pct=0.03))


def test_wait_retest_has_no_twenty_session_timeout():
    # The alternating formation creates a box; the later prices remain above
    # the box and never touch the MA, so WAIT_RETEST must remain structural,
    # not expire merely because 20 sessions elapsed.
    prices = [100.0] * 24 + [101.0, 99.0, 101.0, 100.0, 106.0] + [106.0] * 35
    result = run_ma_box_study(frame_from_prices(prices, spread=0.02), cfg(10, 0))
    events = result["runs"]["10"]["MA_BOX_LONG_V1"]["events"]
    reasons = [x["reason_code"] for x in events]
    assert "RETEST_WAIT_EXPIRED" not in reasons


def test_revision_two_contact_pools_keep_wicks_on_their_own_side():
    from app.ma_box.engine import _contacts_for_bar

    row = pd.Series({"open": 101.0, "high": 110.0, "low": 90.0, "close": 99.0})
    upper = _contacts_for_bar(1, pd.Timestamp("2021-01-04", tz="UTC"), row, 100.0, 100.0, "upper")
    lower = _contacts_for_bar(1, pd.Timestamp("2021-01-04", tz="UTC"), row, 100.0, 100.0, "lower")
    assert {item.field for item in upper} == {"high", "open"}
    assert {item.field for item in lower} == {"low", "close"}


def test_common_start_uses_requested_period_warmup_and_bh_is_matched():
    prices = list(np.linspace(100, 140, 100))
    result = run_ma_box_study(frame_from_prices(prices), cfg(10, 0))
    assert result["evaluation_start"] == result["data_provenance"]["evaluation_start"]
    assert result["buy_and_hold"]["data"][0]["timestamp"].startswith(result["evaluation_start"])
    assert result["runs"]["10"]["MA_BOX_LONG_V1"]["data"][0]["timestamp"] == result["buy_and_hold"]["data"][0]["timestamp"]


def test_buy_and_hold_single_session_still_has_forced_close():
    result = run_ma_box_study(frame_from_prices([100.0] * 40), cfg(10, 0, start="2021-02-25", end="2021-02-25"))
    # The requested range contains one usable evaluation bar after the MA
    # warm-up; the B&H ledger must still close that bar rather than leaving a
    # live position at study end.
    bh = result["buy_and_hold"]
    assert bh["executions"]
    assert bh["executions"][-1]["side"] == "SELL"
    assert bh["executions"][-1]["reason"] == "FORCED_END_OF_TEST_EXIT"


def test_no_box_when_crossing_candles_close_on_one_side():
    prices = [100] * 30 + [100, 100, 100, 100, 100, 100]
    result = run_ma_box_study(frame_from_prices(prices), cfg(10, 0))
    events = result["runs"]["10"]["MA_BOX_LONG_V1"]["events"]
    assert not any(x["reason_code"] == "MA_ENTANGLEMENT_START" for x in events)


def test_entanglement_requires_three_qualifying_and_side_switch():
    # A stable segment followed by three alternating closes whose ranges cross
    # the completed SMA.  The fixture is intentionally small and deterministic.
    prices = [100.0] * 20 + [101.0, 99.0, 101.0, 100.0, 103.0, 106.0]
    result = run_ma_box_study(frame_from_prices(prices, spread=0.03), cfg(10, 0))
    events = result["runs"]["10"]["MA_BOX_LONG_V1"]["events"]
    assert any(x["reason_code"] == "MA_ENTANGLEMENT_START" for x in events)
    assert any(x["reason_code"] == "BOX_ACTIVE" for x in events)


def test_box_blocks_normal_entry_and_keeps_counterfactual_separate():
    prices = [100.0] * 20 + [101.0, 99.0, 101.0, 100.0, 104.0, 106.0, 108.0, 110.0]
    result = run_ma_box_study(frame_from_prices(prices, spread=0.03), cfg(10, 0))
    run = result["runs"]["10"]["MA_BOX_LONG_V1"]
    assert "counterfactual_summary" in run
    assert all(x.get("reason_code") != "NORMAL_MA_ENTRY" or x.get("setup_state_before") != "BOX_ACTIVE" for x in run["events"])


def test_results_are_deterministic_including_event_ids():
    prices = list(np.linspace(100, 160, 130))
    first = run_ma_box_study(frame_from_prices(prices), cfg(10, 1))
    second = run_ma_box_study(frame_from_prices(prices), cfg(10, 1))
    assert first["config_hash"] == second["config_hash"]
    assert first["runs"]["10"]["MA_BOX_LONG_V1"]["events"] == second["runs"]["10"]["MA_BOX_LONG_V1"]["events"]
    assert first["runs"]["10"]["MA_BOX_LONG_V1"]["executions"] == second["runs"]["10"]["MA_BOX_LONG_V1"]["executions"]


def test_nearby_periods_have_independent_runs():
    result = run_ma_box_study(frame_from_prices(list(np.linspace(100, 160, 130))), cfg(10, 2))
    assert result["periods"] == [8, 9, 10, 11, 12]
    assert set(result["runs"]) == {"8", "9", "10", "11", "12"}
    assert all(result["runs"][str(p)]["MA_BOX_LONG_V1"]["sma_period"] == p for p in result["periods"])


def test_revision_two_stage_direct_gate_is_box_high_based():
    # The public study result preserves the frozen risk-gate metadata.  A
    # breakout's eligibility is intentionally represented by BoxHigh and the
    # next-session stop, never by the breakout close.
    prices = [100.0] * 24 + [101.0, 99.0, 101.0, 100.0, 103.0, 104.0, 105.0, 106.0]
    result = run_ma_box_study(frame_from_prices(prices, spread=0.03), cfg(10, 0))
    run = result["runs"]["10"]["MA_BOX_LONG_V1"]
    breakout_events = [x for x in run["events"] if x["reason_code"] == "BOX_UP_BREAKOUT"]
    for event in breakout_events:
        assert "box_high_snapshot" in event["metadata"]
        assert "stop_next" in event["metadata"]
        assert "indicative_close_risk" not in event["metadata"]


def test_revision_two_stage_gate_structural_then_execution():
    assert evaluate_box_structural_gate(105.0, 100.0)["eligible"] is True
    assert evaluate_box_structural_gate(110.0, 100.0)["reason"] == "NO_ENTRY_BOX_RISK_GT_5"
    safe = evaluate_box_execution_gate(104.0, 100.0, 0.02)
    assert safe["eligible"] is True
    gap = evaluate_box_execution_gate(106.0, 100.0, 0.02)
    assert gap["reason"] == "NO_ENTRY_GAP_RISK_GT_5"


def test_execution_gate_rejects_open_at_or_below_stop():
    rejected = evaluate_box_execution_gate(99.9, 100.0, 0.02)
    assert rejected["eligible"] is False
    assert rejected["reason"] == "NO_ENTRY_OPEN_AT_OR_BELOW_STOP"


def test_structural_gate_rejects_nonpositive_risk():
    rejected = evaluate_box_structural_gate(99.0, 100.0)
    assert rejected["eligible"] is False
    assert rejected["reason"] == "NO_ENTRY_BOX_RISK_NOT_POSITIVE"


def test_ma_box_revision_and_tolerance_are_persisted_in_result():
    prices = [100.0] * 30 + list(np.linspace(100, 140, 80))
    result = run_ma_box_study(frame_from_prices(prices), cfg(10, 0))
    assert result["study_revision"] == "MA_BOX_LONG_V1"
    assert result["spec_revision"] == "MA_BOX_LONG_V1_REVISION_3"
    assert result["runs"]["10"]["MA_BOX_LONG_V1"]["spec_hash"] == result["spec_hash"]
    assert result["buy_and_hold"]["spec_hash"] == result["spec_hash"]
    run = result["runs"]["10"]["MA_BOX_LONG_V1"]
    assert run["boundary_tolerance"]["mode"] == "ATR_NORMALIZED"
    assert run["boundary_tolerance"]["multiplier"] == 0.10


def test_run_provenance_keeps_baseline_track_revision_distinct():
    result = run_ma_box_study(frame_from_prices(list(np.linspace(100, 140, 80))), cfg(10, 0))
    assert result["runs"]["10"]["MA_LONG_BASELINE"]["strategy_revision"] == "MA_LONG_BASELINE"
    assert result["runs"]["10"]["MA_BOX_LONG_V1"]["strategy_revision"] == "MA_BOX_LONG_V1"


def test_ma_box_api_is_dedicated_and_persists_without_legacy_selector(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    prices = [100.0] * 20 + [101.0, 99.0, 101.0, 100.0, 104.0, 106.0, 108.0, 110.0]
    frame = frame_from_prices(prices, spread=0.03)
    with TestClient(app) as client:
        app.state.provider = FakeProvider(frame)
        response = client.post("/api/ma-box/studies", json={
            "ticker": "TEST", "selected_ma": 10, "nearby_range": 1, "step": 1,
            "start_date": "2021-01-01", "end_date": "2021-02-15",
        })
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["study_revision"] == "MA_BOX_LONG_V1"
        assert payload["spec_hash"]
        assert payload["spec_revision_number"] == 3
        study_id = payload["study_id"]
        summary = client.get(f"/api/ma-box/studies/{study_id}/summary")
        assert summary.status_code == 200
        assert summary.json()["spec_revision"] == "MA_BOX_LONG_V1_REVISION_3"
        assert summary.json()["spec_revision_number"] == 3
        assert client.get(f"/api/ma-box/studies/{study_id}/runs/10/MA_BOX_LONG_V1").status_code == 200
        export = client.get(f"/api/ma-box/studies/{study_id}/export/10?format=csv")
        assert export.status_code == 200
        assert "position_id" in export.text
        counterfactual = client.get(f"/api/ma-box/studies/{study_id}/counterfactuals/10")
        assert counterfactual.status_code == 200
        assert counterfactual.json()["trades"]
        required = {"entry_raw_fill", "entry_actual_fill", "entry_quantity", "entry_commission",
                    "entry_slippage_cost", "exit_raw_fill", "exit_actual_fill", "exit_commission",
                    "exit_slippage_cost", "gross_pnl", "net_pnl", "mfe", "mae", "holding_days"}
        assert required <= set(counterfactual.json()["trades"][0])
        cf_export = client.get(f"/api/ma-box/studies/{study_id}/export/10?format=counterfactual.csv")
        assert cf_export.status_code == 200
        assert required <= set(cf_export.text.splitlines()[0].split(","))


def test_no_lookahead_future_mutation_does_not_change_prior_events():
    prices = [100.0] * 24 + [101.0, 99.0, 101.0, 100.0, 104.0, 106.0, 108.0, 110.0] + list(np.linspace(111, 125, 35))
    original = frame_from_prices(prices, spread=0.03)
    mutated = original.copy()
    cutoff = 42
    mutated.iloc[cutoff + 1:, mutated.columns.get_loc("open")] = 65.0
    mutated.iloc[cutoff + 1:, mutated.columns.get_loc("high")] = 70.0
    mutated.iloc[cutoff + 1:, mutated.columns.get_loc("low")] = 60.0
    mutated.iloc[cutoff + 1:, mutated.columns.get_loc("close")] = 66.0
    first = run_ma_box_study(original, cfg(10, 0))
    second = run_ma_box_study(mutated, cfg(10, 0))
    first_events = [x for x in first["runs"]["10"]["MA_BOX_LONG_V1"]["events"] if x["date"] <= original.index[cutoff].date().isoformat()]
    second_events = [x for x in second["runs"]["10"]["MA_BOX_LONG_V1"]["events"] if x["date"] <= original.index[cutoff].date().isoformat()]
    assert first_events == second_events
