from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.backtest.diagnostics import build_day1_stop_diagnostic, find_matching_advanced
from app.backtest.models import BacktestRequest


def request(strategy: str) -> dict:
    return BacktestRequest(
        ticker="NVDA",
        strategy=strategy,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 3, 1),
        commission_pct=0,
        slippage_pct=0,
    ).model_dump(mode="json")


def position(identifier: str, *, pnl: float, reason: str) -> dict:
    return {
        "position_id": identifier,
        "entry_date": "2025-01-02T00:00:00+00:00",
        "entry_price": 101.5,
        "final_exit_date": "2025-01-02T00:00:00+00:00" if reason == "DAY1_FULL_STOP" else "2025-01-20T00:00:00+00:00",
        "exit_final_close_reason": reason,
        "net_pnl": pnl,
        "return_pct": pnl / 10_150 * 100,
    }


def records():
    start = date(2025, 1, 2)
    daily = [
        {
            "timestamp": f"{start + timedelta(days=index)}T00:00:00+00:00",
            "open": 100 + index,
            "high": 105 + index,
            "low": 97 if index == 0 else 99 + index,
            "close": 100 + index,
            "volume": 1_000,
            "reference_ma": 100,
        }
        for index in range(25)
    ]
    variant_position = position("position-1", pnl=-450, reason="DAY1_FULL_STOP")
    baseline_position = position("position-7", pnl=1_000, reason="PROTECTIVE_STOP")
    variant = {
        "id": "variant", "ticker": "NVDA", "strategy": "advanced_day1_stop", "start_date": "2025-01-01", "end_date": "2025-03-01", "status": "COMPLETED",
        "parameters": request("advanced_day1_stop"),
        "result": {
            "daily_data": daily,
            "positions": [variant_position],
            "executions": [
                {"timestamp": daily[0]["timestamp"], "side": "BUY", "price": 101.5, "reason": "ENTRY_STOP_FILLED"},
                {"timestamp": daily[0]["timestamp"], "side": "SELL", "price": 97, "reason": "DAY1_FULL_STOP"},
            ],
            "events": [{"timestamp": daily[0]["timestamp"], "event": "DAILY_INTRABAR_AMBIGUITY", "metadata": {"simultaneous_conditions": ["ENTRY_LEVEL", "DAY1_FULL_STOP"]}}],
            "summary": {"total_return": -.1, "final_equity": 90_000},
        },
    }
    baseline = {
        "id": "baseline", "ticker": "NVDA", "strategy": "advanced", "start_date": "2025-01-01", "end_date": "2025-03-01", "status": "COMPLETED",
        "parameters": request("advanced"), "result": {"positions": [baseline_position], "summary": {"total_return": .1, "final_equity": 110_000}},
    }
    return variant, baseline


def test_day1_stop_diagnostic_calculates_forward_returns_groups_and_comparison():
    variant, baseline = records()
    report = build_day1_stop_diagnostic(variant_record=variant, baseline_record=baseline)
    assert report["day1_full_stop_count"] == 1
    assert report["daily_intrabar_ambiguity_count"] == 1
    stop = report["stops"][0]
    assert stop["day1_stop_price"] == 97
    assert stop["loss_pct"] == pytest.approx((97 / 101.5 - 1) * 100)
    assert stop["forward_5d_pct"] == pytest.approx((105 / 97 - 1) * 100)
    assert report["group_statistics"]["ambiguous"]["median_20_day_forward_return_pct"] == pytest.approx((120 / 97 - 1) * 100)
    comparison = report["comparison"]["all_divergences"][0]
    assert comparison["original_advanced"]["position_id"] == "position-7"
    assert comparison["day1_stop_strategy"]["position_id"] == "position-1"
    assert comparison["pnl_difference"] == -1450
    assert len(report["comparison"]["largest_return_damage"]) == 1
    assert report["comparison"]["largest_improvements"] == []
    assert report["backtest_comparison"]["total_return_difference"] == pytest.approx(-.2)
    assert report["backtest_comparison"]["final_equity_difference"] == -20_000


def test_matching_baseline_ignores_only_variant_day1_parameter():
    variant, baseline = records()
    summary = {key: value for key, value in baseline.items() if key != "result"}
    assert find_matching_advanced(variant, [summary]) == summary
    mismatched = {**summary, "parameters": {**summary["parameters"], "commission_pct": .5}}
    assert find_matching_advanced(variant, [mismatched]) is None
