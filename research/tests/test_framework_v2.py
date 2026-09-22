from __future__ import annotations

import json
import hashlib
from types import SimpleNamespace

import pandas as pd

from app.backtest.models import BacktestRequest
from research.framework_benchmarks import donchian_20_10, sma200_trend, spy_buy_and_hold
from research.framework_v2 import BENCHMARKS, COST_STRESS, DAILY_POLICIES, UNIVERSE, VIABILITY_GATE


def prepared(frame, ticker="TEST"):
    request = BacktestRequest(
        ticker=ticker, strategy="simple", start_date=frame.index[0].date(), end_date=frame.index[-1].date(),
        commission_pct=0.05, slippage_pct=0.02,
    )
    return SimpleNamespace(request=request, period=frame, enriched=frame)


def frame(rows):
    index = pd.date_range("2025-01-02", periods=len(rows), freq="B", tz="UTC")
    return pd.DataFrame(rows, index=index, columns=["open", "high", "low", "close", "volume"])


def test_framework_contracts_are_fixed_and_have_no_new_candidate():
    assert UNIVERSE == ("AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "AVGO", "SPY", "QQQ")
    assert DAILY_POLICIES == ("conservative", "ohlc_heuristic", "favorable")
    assert set(BENCHMARKS) == {"BUY_AND_HOLD", "SPY_BUY_AND_HOLD", "SMA200_TREND", "DONCHIAN_20_10"}
    assert set(COST_STRESS) == {"BASELINE", "DOUBLE_COMMISSION", "DOUBLE_SLIPPAGE", "DOUBLE_BOTH"}
    assert len(VIABILITY_GATE["comparators"]) == 4


def test_sma200_close_signal_executes_only_at_next_open():
    rows = [[100, 101, 99, 100, 1000] for _ in range(199)]
    rows += [[100, 102, 99, 101, 1000], [110, 112, 109, 111, 1000], [112, 113, 111, 112, 1000]]
    data = frame(rows)
    result = sma200_trend(prepared(data))
    buys = [row for row in result["executions"] if row["side"] == "BUY"]
    assert len(buys) == 1
    assert pd.Timestamp(buys[0]["timestamp"]) == data.index[200]
    assert buys[0]["price"] == 110 * 1.0002


def test_donchian_entry_uses_prior_twenty_highs_not_current_high():
    rows = [[95, 100, 90, 95, 1000] for _ in range(20)]
    rows += [[99, 200, 95, 150, 1000], [151, 152, 149, 151, 1000]]
    data = frame(rows)
    result = donchian_20_10(prepared(data), "conservative")
    buy = next(row for row in result["executions"] if row["side"] == "BUY")
    assert pd.Timestamp(buy["timestamp"]) == data.index[20]
    assert buy["price"] == 100 * 1.0002
    assert result["contract"]["levels"] == "completed prior sessions only"


def test_spy_benchmark_has_exactly_one_costed_round_trip():
    data = frame([[100, 102, 99, 101, 1000], [102, 104, 101, 103, 1000]])
    result = spy_buy_and_hold(prepared(data, "SPY"))
    assert result["name"] == "SPY_BUY_AND_HOLD"
    assert [row["side"] for row in result["executions"]] == ["BUY", "SELL"]
    assert result["summary"]["total_commission"] > 0
    assert result["summary"]["estimated_slippage_cost"] > 0


def test_registry_is_append_only_and_baselines_are_rejected():
    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    registry = json.loads((root / "data/research-candidate-registry.json").read_text(encoding="utf-8"))
    assert registry["append_only"] is True
    assert registry["candidate_count"] == 3
    assert all(row["research_status"] == "REJECTED" for row in registry["candidates"])
    assert all(row["spec_sha256"] for row in registry["candidates"])


def test_donchian_genuine_entry_stop_ambiguity_obeys_all_three_frozen_policies():
    rows = [[95, 100, 90, 95, 1000] for _ in range(20)]
    # The final bar stays below the prior 20-day entry channel so the fixture
    # contains exactly one entry episode under every policy.
    rows += [[95, 101, 89, 100, 1000], [99, 99, 91, 99, 1000]]
    data = frame(rows)
    conservative = donchian_20_10(prepared(data), "conservative")
    heuristic = donchian_20_10(prepared(data), "ohlc_heuristic")
    favorable = donchian_20_10(prepared(data), "favorable")
    assert len(conservative["executions"]) == 2
    assert len(heuristic["executions"]) == len(favorable["executions"]) == 2
    assert conservative["executions"][1]["price"] < heuristic["executions"][1]["price"]
    assert conservative["ambiguous_days"] == [data.index[20].date().isoformat()]
    assert heuristic["ambiguous_days"] == favorable["ambiguous_days"] == conservative["ambiguous_days"]


def test_donchian_open_entry_then_low_is_unambiguous_under_every_policy():
    rows = [[95, 100, 90, 95, 1000] for _ in range(20)]
    rows += [[100, 101, 89, 99, 1000], [99, 100, 98, 99, 1000]]
    data = frame(rows)
    results = [donchian_20_10(prepared(data), policy) for policy in ("conservative", "ohlc_heuristic", "favorable")]
    assert all(result["ambiguous_days"] == [] for result in results)
    assert all(result["executions"][1]["reason"] == "DONCHIAN_10_LOW_EXIT" for result in results)
    assert len({result["executions"][1]["price"] for result in results}) == 1


def test_saved_benchmark_study_reconciles_spec_report_and_freezes_registry():
    from research.benchmark_viability_report import render
    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    study = json.loads((root / "data/benchmark-viability-study.json").read_text(encoding="utf-8"))
    folds = json.loads((root / "data/benchmark-walk-forward-folds.json").read_text(encoding="utf-8"))
    spec = root / study["benchmark_spec"]["path"]
    assert hashlib.sha256(spec.read_bytes()).hexdigest() == study["benchmark_spec"]["sha256"]
    assert hashlib.sha256((root / study["walk_forward_file"]).read_bytes()).hexdigest() == study["walk_forward_sha256"]
    assert study["data"]["data_start"] == "2020-12-03"
    assert study["data"]["evaluation_start"] == "2021-09-21"
    assert study["data"]["warmup_completed_bars"] == 200
    assert not study["candidate_created"] and not study["optimization_performed"] and not study["benchmark_parameters_changed"]
    assert study["next_family"] == "NONE"
    assert len(folds["rows"]) == 2 * 7 * 11 * 7
    assert render(study) == (root / "reports/benchmark-viability-study.md").read_text(encoding="utf-8")
    registry = root / "data/research-candidate-registry.json"
    assert hashlib.sha256(registry.read_bytes()).hexdigest() == study["immutability"]["registry_sha256"]


def test_sma200_saved_policy_rows_are_exactly_identical():
    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    study = json.loads((root / "data/benchmark-viability-study.json").read_text(encoding="utf-8"))
    for symbol in ("NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "AVGO", "SPY", "QQQ"):
        rows = [r for r in study["full_period"] if r["symbol"] == symbol and r["benchmark"] == "SMA200_TREND"]
        assert len(rows) == 3
        assert rows[0]["metrics"] == rows[1]["metrics"] == rows[2]["metrics"]
