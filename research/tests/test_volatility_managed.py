from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from research.volatility_managed import TARGET_VOL, exposure_schedule, simulate, verify_spec


def frame(n=90):
    index = pd.bdate_range("2020-01-02", periods=n, tz="UTC")
    returns = np.tile([.01, -.01], n // 2 + 1)[:n]
    close = 100 * np.cumprod(1 + returns)
    return pd.DataFrame({"open": close * .999, "close": close}, index=index)


def test_frozen_spec_hash():
    verify_spec()


def test_rv20_uses_completed_returns_and_executes_next_open():
    data = frame()
    schedule = exposure_schedule(data)
    first_execution = schedule.index[0]
    signal = pd.Timestamp(schedule.iloc[0]["signal_date"])
    assert signal == data.index[20]
    assert first_execution == data.index[21]
    expected = data.close.pct_change().iloc[1:21].std(ddof=1) * math.sqrt(252)
    assert schedule.iloc[0].rv20 == pytest.approx(expected)
    old = schedule.iloc[0].to_dict()
    data.loc[first_execution:, "close"] *= 7
    assert exposure_schedule(data).iloc[0].to_dict() == old


def test_target_exposure_cap_and_formula():
    data = frame()
    schedule = exposure_schedule(data)
    row = schedule.iloc[0]
    assert row.target_exposure == pytest.approx(min(1.0, TARGET_VOL / row.rv20))
    assert 0 < schedule.target_exposure.min() <= schedule.target_exposure.max() <= 1


def test_next_open_whole_shares_costs_and_accounting():
    data = frame(); schedule = exposure_schedule(data)
    start = schedule.index[0]
    result = simulate(data, schedule, "MANAGED", start, data.index[-1], 100000, .0005, .0002)
    first = result["executions"][0]
    assert first["date"] == start.date().isoformat()
    assert first["raw_fill"] == data.loc[start, "open"]
    assert first["execution_price"] == pytest.approx(first["raw_fill"] * 1.0002)
    assert isinstance(first["quantity"], int)
    assert all(0 <= row["open_exposure"] <= 1.000001 for row in result["daily"])
    metric = result["metrics"]
    assert metric["final_equity"] - 100000 == pytest.approx(
        metric["equity_pnl_before_cost"] + metric["cash_interest"] - metric["commission"] - metric["slippage"]
    )


def test_cash_interest_only_applies_to_cash():
    data = frame(); schedule = exposure_schedule(data); start = schedule.index[0]
    factors = {timestamp: .001 for timestamp in data.index}
    result = simulate(data, schedule, "MANAGED", start, data.index[-1], 100000, 0, 0, factors)
    for previous, current in zip(result["daily"], result["daily"][1:]):
        assert current["interest"] == pytest.approx(previous["cash"] * .001)
        assert current["interest"] < previous["equity"] * .001 + 1e-9


def test_identical_target_quantity_creates_no_adjustment_trade():
    data = frame(45)
    schedule = exposure_schedule(data)
    schedule.loc[:, "target_exposure"] = .5
    data.loc[:, ["open", "close"]] = 100
    result = simulate(data, schedule, "MANAGED", schedule.index[0], data.index[-1], 100000, 0, 0)
    assert [row["event"] for row in result["executions"]] == ["INITIAL_ALLOCATION", "FINAL_LIQUIDATION"]
    assert result["metrics"]["number_of_adjustment_trades"] == 0


def test_buy_and_hold_uses_same_fair_start_and_no_interim_adjustment():
    data = frame(); schedule = exposure_schedule(data); start = schedule.index[0]
    result = simulate(data, schedule, "BUY_HOLD", start, data.index[-1], 100000, .0005, .0002)
    assert result["start"] == start.date().isoformat()
    assert len(result["executions"]) == 2
    assert result["executions"][0]["event"] == "INITIAL_ALLOCATION"
    assert result["executions"][-1]["event"] == "FINAL_LIQUIDATION"
