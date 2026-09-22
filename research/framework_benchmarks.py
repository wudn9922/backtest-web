"""Fixed, research-only benchmark implementations for Framework v2."""
from __future__ import annotations

import pandas as pd

from app.backtest.execution import execution_policy
from app.backtest.portfolio import Portfolio, initial_quantity
from research.viability_benchmarks import _finalize, buy_and_hold


def spy_buy_and_hold(spy_prepared):
    """The SPY comparator uses the exact same costed contract as Buy & Hold."""
    result = buy_and_hold(spy_prepared)
    result["name"] = "SPY_BUY_AND_HOLD"
    return result


def sma200_trend(prepared):
    """Close/SMA200 signal at t, always executed at the next session open."""
    req = prepared.request
    period = prepared.period.copy()
    source = prepared.enriched if hasattr(prepared, "enriched") else period
    sma = source["close"].rolling(200, min_periods=200).mean()
    period["sma200"] = sma.reindex(period.index)
    pf = Portfolio(req.initial_capital, req.commission_pct, req.slippage_pct)
    values, exposure_days = [], 0
    first_location = source.index.get_loc(period.index[0])
    previous_signal = False if first_location == 0 else bool(
        pd.notna(sma.iloc[first_location - 1]) and
        float(source.iloc[first_location - 1].close) > float(sma.iloc[first_location - 1])
    )
    for index, (timestamp, row) in enumerate(period.iterrows()):
        # This open can act only on yesterday's completed close/SMA200 signal.
        if previous_signal and not pf.quantity:
            qty = initial_quantity(pf.equity(float(row.open)), req.position_size_pct, float(row.open), req.slippage_pct, req.commission_pct)
            if qty:
                pf.buy(timestamp.to_pydatetime(), float(row.open), qty, "ENTRY", "SMA200_NEXT_OPEN_ENTRY")
        elif not previous_signal and pf.quantity:
            pf.sell(timestamp.to_pydatetime(), float(row.open), pf.quantity, "FINAL_EXIT", "SMA200_NEXT_OPEN_EXIT")
        if pf.quantity:
            exposure_days += 1
        current_signal = bool(pd.notna(row.sma200) and float(row.close) > float(row.sma200))
        if index == len(period) - 1 and pf.quantity:
            pf.sell(timestamp.to_pydatetime(), float(row.close), pf.quantity, "FINAL_EXIT", "SMA200_END_OF_STUDY")
        values.append(pf.equity(float(row.close)))
        previous_signal = current_signal
    result = _finalize(prepared, pf, values, exposure_days, "SMA200_TREND")
    result["contract"] = {"signal": "Close(t) > SMA200(t)", "execution": "next trading day open", "period": 200}
    return result


def donchian_20_10(prepared, policy_name="conservative"):
    """Prior-completed Donchian 20/10 with policy-aware same-day ambiguity."""
    req = prepared.request
    period = prepared.period.copy()
    source = prepared.enriched if hasattr(prepared, "enriched") else period
    upper = source["high"].shift(1).rolling(20, min_periods=20).max().reindex(period.index)
    lower = source["low"].shift(1).rolling(10, min_periods=10).min().reindex(period.index)
    execution_policy(policy_name)  # validate the frozen public policy name
    pf = Portfolio(req.initial_capital, req.commission_pct, req.slippage_pct)
    values, exposure_days, ambiguous_days = [], 0, []
    for timestamp, row in period.iterrows():
        up, down = upper.loc[timestamp], lower.loc[timestamp]
        had_position = bool(pf.quantity)
        if had_position and pd.notna(down) and float(row.low) <= float(down):
            raw = float(row.open) if float(row.open) <= float(down) else float(down)
            pf.sell(timestamp.to_pydatetime(), raw, pf.quantity, "FINAL_EXIT", "DONCHIAN_10_LOW_EXIT")
        elif not had_position and pd.notna(up) and float(row.high) >= float(up):
            raw_entry = float(row.open) if float(row.open) >= float(up) else float(up)
            open_entry = float(row.open) >= float(up)
            same_day_stop = pd.notna(down) and float(row.low) <= float(down)
            qty = initial_quantity(pf.equity(float(row.open)), req.position_size_pct, raw_entry, req.slippage_pct, req.commission_pct)
            if qty:
                pf.buy(timestamp.to_pydatetime(), raw_entry, qty, "ENTRY", "DONCHIAN_20_BREAKOUT")
                if same_day_stop and open_entry:
                    raw = float(row.open) if float(row.open) <= float(down) else float(down)
                    pf.sell(timestamp.to_pydatetime(), raw, pf.quantity, "FINAL_EXIT", "DONCHIAN_10_LOW_EXIT")
                elif same_day_stop:
                    ambiguous_days.append(timestamp.date().isoformat())
                    # Favorable and a bullish OHLC heuristic place the low before
                    # the breakout. Conservative (and bearish heuristic) execute
                    # the post-entry adverse path.
                    adverse = policy_name == "conservative" or (policy_name == "ohlc_heuristic" and float(row.close) < float(row.open))
                    if adverse:
                        pf.sell(timestamp.to_pydatetime(), float(down), pf.quantity, "FINAL_EXIT", "DONCHIAN_10_LOW_EXIT")
        if pf.quantity:
            exposure_days += 1
        if timestamp == period.index[-1] and pf.quantity:
            pf.sell(timestamp.to_pydatetime(), float(row.close), pf.quantity, "FINAL_EXIT", "DONCHIAN_END_OF_STUDY")
        values.append(pf.equity(float(row.close)))
    result = _finalize(prepared, pf, values, exposure_days, "DONCHIAN_20_10")
    result["contract"] = {"entry_lookback": 20, "exit_lookback": 10, "levels": "completed prior sessions only", "policy": policy_name}
    result["ambiguous_days"] = ambiguous_days
    return result
