import numpy as np
import pandas as pd
import pytest

from research.xsmom import rankings, simulate, verify_spec


def frames(n=550):
    idx = pd.bdate_range("2010-01-01", periods=n, tz="UTC")
    return {s: pd.DataFrame({"open": np.linspace(90, 120+j*5, n),
                            "close": np.linspace(90, 120+j*5, n)}, index=idx)
            for j,s in enumerate(["SPY", "QQQ", "IWM", "XLRE"])}


def test_frozen_spec():
    verify_spec()


def test_rankings_lag_and_inception():
    f = frames()
    f["XLRE"] = f["XLRE"].iloc[300:]
    schedule = rankings(f)
    execution = sorted(schedule)[0]
    signal = pd.Timestamp(schedule[execution]["signal_date"], tz="UTC")
    i = f["SPY"].index.get_loc(signal)
    assert execution > signal and execution.month != signal.month
    assert "XLRE" not in schedule[execution]["ranking"]
    expected = f["SPY"].close.iloc[i-21]/f["SPY"].close.iloc[i-252]-1
    assert schedule[execution]["scores"]["SPY"] == expected
    f["SPY"].loc[f["SPY"].index[i-20]:, "close"] *= 20
    assert rankings(f)[execution] == schedule[execution]


def test_equal_weights_whole_shares_next_open_and_reconciliation():
    f = frames(); schedule = rankings(f)
    start = min(schedule); end = f["SPY"].index[-1]
    r = simulate(f, schedule, "RS", start, end, 100000, .0005, .0002)
    first = r["executions"][0]
    assert first["date"] == start.date().isoformat()
    assert first["raw_fill"] == f[first["symbol"]].loc[start,"open"]
    assert first["price"] == pytest.approx(first["raw_fill"]*1.0002)
    assert all(isinstance(e["qty"],int) for e in r["executions"])
    assert all(d["cash"] >= -1e-6 for d in r["daily"])
    assert r["daily"][-1]["holdings_count"] == 0
    assert sum(r["etf_contribution"].values()) == pytest.approx(r["daily"][-1]["equity"]-100000)
    assert all(abs(w-1/3) < .003 for w in r["monthly_holdings"][0]["weights_at_open"].values())


def test_cash_only_accrual_no_double_count():
    f = frames(); sch = rankings(f); start = min(sch); end = f["SPY"].index[-1]
    factors = {t: .001 for t in f["SPY"].index}
    r = simulate(f, sch, "SPY", start,end,100000,.0005,.0002,factors)
    for previous, current in zip(r["daily"],r["daily"][1:]):
        assert current["interest"] == pytest.approx(previous["cash"]*.001)
    assert r["metrics"]["cash_interest"] < 1000
    assert r["daily"][-1]["equity"]-100000 == pytest.approx(sum(r["etf_contribution"].values())+r["metrics"]["cash_interest"])


def test_unchanged_target_does_not_roundtrip():
    f=frames()
    for v in f.values(): v[:]=100
    sch=rankings(f)
    r=simulate(f,sch,"RS",min(sch),f["SPY"].index[-1],100000,0,0)
    assert len(r["executions"]) == 6


def test_missing_held_price_aborts():
    f=frames(); sch=rankings(f); start=min(sch)
    held=sch[start]["ranking"][0]
    f[held]=f[held].drop(f[held].index[f[held].index.get_loc(start)+1])
    with pytest.raises(KeyError):
        simulate(f,sch,"RS",start,f["SPY"].index[-1],100000,0,0)
