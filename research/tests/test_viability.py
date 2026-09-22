from datetime import date
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research import ROOT
from research.baseline import immutable_fingerprints, load
from research.simulation import Prepared, simulate
from research.structural_data import load_inputs
from research.viability_benchmarks import buy_and_hold, entry_zone_hold, entry_zone_signals, metric_view
from research.viability_design import COST_SCENARIOS, POLICIES, SYMBOLS, VIABILITY_GATE, walk_forward_folds
from research.viability_statistics import clustered_bootstrap


@pytest.fixture(scope="module")
def data():
    before = immutable_fingerprints()
    frozen, _ = load()
    _, frames = load_inputs()
    yield frozen, frames
    assert before == immutable_fingerprints()


def test_design_is_fixed_and_contains_no_sweep():
    assert tuple(COST_SCENARIOS) == ("BASELINE", "DOUBLE_COMMISSION", "DOUBLE_SLIPPAGE", "DOUBLE_BOTH")
    assert len(POLICIES) == 3 and len(SYMBOLS) == 11
    assert set(VIABILITY_GATE) == {"strong", "promising", "labels"}
    assert "STRONG RETROSPECTIVE EVIDENCE — FREEZE FOR FORWARD TEST" in VIABILITY_GATE["labels"]
    folds = walk_forward_folds()
    assert len(folds) == 12
    for design in ("expanding", "rolling"):
        selected = [f for f in folds if f["design"] == design]
        assert len(selected) == 6
        assert all(f["train_end"] < f["test_start"] <= f["test_end"] for f in selected)


def test_buy_and_hold_costs_whole_shares_and_two_executions(data):
    frozen, frames = data
    req = frozen["advanced"]["request_object"].model_copy(update={"ticker": "SPY", "start_date": date(2024, 1, 1), "end_date": date(2024, 3, 31)})
    p = Prepared(req, frames["SPY"])
    result = buy_and_hold(p)
    assert [e["side"] for e in result["executions"]] == ["BUY", "SELL"]
    assert isinstance(result["capital_deployment"]["whole_shares"], int)
    assert result["capital_deployment"]["residual_cash"] >= -1e-8
    assert result["summary"]["total_commission"] == pytest.approx(sum(e["commission"] for e in result["executions"]))
    assert result["summary"]["estimated_slippage_cost"] == pytest.approx(sum(e["slippage"] for e in result["executions"]))


def test_entry_zone_hold_uses_exact_production_v2_signal_and_no_tactical_exit(data):
    frozen, frames = data
    req = frozen["advanced"]["request_object"].model_copy(update={"ticker": "AAPL", "start_date": date(2024, 1, 1), "end_date": date(2025, 1, 1)})
    p = Prepared(req, frames["AAPL"])
    signals = entry_zone_signals(p)
    first = next(x for x in signals if x["classification"] == "VALID_ENTRY")
    result = entry_zone_hold(p)
    assert result["first_signal_index"] == first["index"]
    assert len(result["executions"]) == 2
    assert result["executions"][0]["reason"] == "ENTRY_ZONE_V2_HOLD_ENTRY"
    assert result["executions"][1]["reason"] == "ENTRY_ZONE_HOLD_FINAL_EXIT"
    assert result["executions"][0]["price"] == pytest.approx(first["upper_entry"] * (1 + req.slippage_pct / 100))


def test_entry_zone_signal_uses_previous_day_ma_and_future_horizon_is_censored(data):
    frozen, frames = data
    req = frozen["advanced"]["request_object"].model_copy(update={"ticker": "QQQ"})
    p = Prepared(req, frames["QQQ"])
    signals = entry_zone_signals(p)
    for signal in signals[:25]:
        timestamp = p.period.index[signal["index"]]
        assert signal["reference_ma"] == pytest.approx(p.enriched["ma"].shift(1).loc[timestamp])
        assert signal["lower_entry"] == pytest.approx(signal["reference_ma"] * (1 + req.parameters.breakout_trigger_pct / 100))
        assert signal["upper_entry"] == pytest.approx(signal["reference_ma"] * (1 + req.parameters.entry_stop_pct / 100))
    valid = next(x for x in reversed(signals) if x["classification"] == "VALID_ENTRY")
    from research.viability_benchmarks import independent_signal_horizon
    horizon = independent_signal_horizon(p, valid, 60)
    assert horizon["complete"] == (valid["index"] + 60 < len(p.rows))
    missed = next(x for x in signals if x["classification"] == "ENTRY_ZONE_MISSED")
    assert missed["open"] > missed["upper_entry"] and not missed["entry_allowed"]


@pytest.mark.parametrize("policy", POLICIES)
def test_research_simple_and_advanced_are_still_production_parity(data, policy):
    frozen, frames = data
    p = Prepared(frozen["advanced"]["request_object"].model_copy(update={"execution_policy": policy}), frames["NVDA"])
    simple = simulate(p, simple=True, policy=policy)
    advanced = simulate(p, policy=policy)
    assert simple["summary"]["number_of_positions"] > 0
    assert advanced["summary"]["number_of_positions"] > 0
    if policy == "conservative":
        assert metric_view(simple)["total_return"] == frozen["simple"]["result"]["summary"]["total_return"]
        assert metric_view(advanced)["total_return"] == frozen["advanced"]["result"]["summary"]["total_return"]
        assert metric_view(simple)["average_close_capital_exposure_pct"] == pytest.approx(41.74579791234935)
        assert metric_view(advanced)["average_close_capital_exposure_pct"] == pytest.approx(12.67667424969951)
        assert metric_view(simple)["exposure_pct"] == frozen["simple"]["result"]["summary"]["exposure_pct"]


def test_cluster_bootstrap_keeps_ticker_and_time_blocks_together():
    rows = [{"symbol": symbol, "entry_date": day, "value": value}
            for symbol in ("A", "B") for day, value in (("2024-01-03", 1), ("2024-02-03", 1), ("2024-07-03", -1), ("2024-08-03", -1))]
    first = clustered_bootstrap(rows, "value", reps=200)
    second = clustered_bootstrap(rows, "value", reps=200)
    assert first == second
    assert first["ticker_clusters"] == ["A", "B"]
    assert first["time_block_clusters"] == ["2024H1", "2024H2"]


def test_saved_viability_artifacts_reconcile_if_present():
    path = ROOT / "data/simple-v2-strategy-viability.json"
    if not path.exists():
        pytest.skip("viability report not generated yet")
    body = json.loads(path.read_text(encoding="utf-8"))
    entry = json.loads((ROOT / body["entry_zone"]["data_file"]).read_text(encoding="utf-8"))
    folds = json.loads((ROOT / body["walk_forward_file"]).read_text(encoding="utf-8"))
    from research.baseline import digest
    assert digest(entry) == body["entry_zone_data_sha256"]
    assert digest(folds) == body["walk_forward_sha256"]
    assert len(folds["rows"]) == 396
    assert len(entry["rows"]) == 11 * 1255
    from research.framework_freeze import assert_frozen_artifact_fingerprint
    assert body["immutability"]["before"] == body["immutability"]["after"]
    assert_frozen_artifact_fingerprint(body["immutability"]["before"])
    assert body["decision"]["classification"] in VIABILITY_GATE["labels"]
    assert not body["optimization_performed"] and not body["production_strategies_modified"]


def test_saved_report_reproduces_if_present():
    path = ROOT / "data/simple-v2-strategy-viability.json"
    if not path.exists():
        pytest.skip("viability report not generated yet")
    from research.viability_report import render
    body = json.loads(path.read_text(encoding="utf-8"))
    assert render(body) == (ROOT / "reports/simple-v2-strategy-viability.md").read_text(encoding="utf-8")
