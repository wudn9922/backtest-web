"""Research-only benchmarks and common reporting helpers.

No provider, database, repository, API, or production strategy is mutated.
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

from app.backtest.engine import BacktestEngine
from app.backtest.execution import evaluate_entry_zone
from app.backtest.metrics import calculate_metrics
from app.backtest.portfolio import Portfolio, initial_quantity


METRICS = (
    "total_return", "cagr", "max_drawdown", "sharpe_ratio", "sortino_ratio",
    "calmar_ratio", "win_rate", "profit_factor", "number_of_positions",
    "exposure_pct", "average_holding_days", "total_commission",
    "estimated_slippage_cost",
)


def _finalize(prepared, portfolio, equity_values, exposure_days, name):
    equity = pd.Series(equity_values, index=prepared.period.index, dtype=float)
    # This argument only populates calculate_metrics.buy_hold_return; benchmark
    # comparisons use the separately costed BUY_AND_HOLD result below.
    raw_reference = prepared.request.initial_capital * prepared.period.close / prepared.period.close.iloc[0]
    positions = BacktestEngine._positions(portfolio.executions, prepared.period)
    summary, drawdown = calculate_metrics(
        equity, raw_reference, positions, prepared.request.initial_capital,
        exposure_days, len(equity), portfolio.total_commission,
        portfolio.total_slippage_cost,
        sum(x.side == "SELL" for x in portfolio.executions),
    )
    values = np.asarray(equity_values, float)
    fractions = []
    quantity = 0
    executions_by_date = {}
    for execution in portfolio.executions:
        executions_by_date.setdefault(execution.timestamp.date().isoformat(), []).append(execution)
    for (timestamp, row), value in zip(prepared.period.iterrows(), values):
        for execution in executions_by_date.get(timestamp.date().isoformat(), []):
            quantity = execution.position_remaining
        fractions.append(quantity * float(row.close) / value if value else 0.0)
    traded = math.fsum(x.gross_value for x in portfolio.executions)
    avg_equity = float(values.mean())
    years = max((prepared.period.index[-1] - prepared.period.index[0]).days / 365.25, 1 / 365.25)
    exposure = {
        "time_in_market_pct": exposure_days / len(values) * 100 if len(values) else 0,
        "average_close_capital_exposure_pct": float(np.mean(fractions)) * 100 if fractions else 0,
        "average_close_cash_pct": (1 - float(np.mean(fractions))) * 100 if fractions else 100,
        "gross_traded_notional": traded,
        "two_sided_turnover": traded / avg_equity if avg_equity else 0,
        "annualized_two_sided_turnover": traded / avg_equity / years if avg_equity else 0,
        "number_of_entries": sum(x.side == "BUY" for x in portfolio.executions),
    }
    return {
        "name": name,
        "summary": summary,
        "exposure": exposure,
        "positions": positions,
        "executions": [x.as_dict() for x in portfolio.executions],
        "equity": [{"timestamp": t.isoformat(), "strategy": float(v)} for t, v in equity.items()],
        "drawdown": [{"timestamp": t.isoformat(), "drawdown": float(v)} for t, v in drawdown.items()],
    }


def buy_and_hold(prepared):
    """One costed opening buy and one costed final-close sell."""
    req = prepared.request
    pf = Portfolio(req.initial_capital, req.commission_pct, req.slippage_pct)
    first_ts, first = prepared.period.index[0], prepared.period.iloc[0]
    qty = initial_quantity(req.initial_capital, req.position_size_pct, float(first.open), req.slippage_pct, req.commission_pct)
    pf.buy(first_ts.to_pydatetime(), float(first.open), qty, "ENTRY", "BUY_AND_HOLD_ENTRY")
    values = []
    for index, (timestamp, row) in enumerate(prepared.period.iterrows()):
        if index == len(prepared.period) - 1:
            pf.sell(timestamp.to_pydatetime(), float(row.close), pf.quantity, "FINAL_EXIT", "BUY_AND_HOLD_FINAL_EXIT")
        values.append(pf.equity(float(row.close)))
    result = _finalize(prepared, pf, values, len(values), "BUY_AND_HOLD")
    result["capital_deployment"] = {
        "entry_date": first_ts.date().isoformat(),
        "raw_entry_price": float(first.open),
        "execution_price": result["executions"][0]["price"],
        "whole_shares": qty,
        "initial_deployed_gross": result["executions"][0]["gross_value"],
        "initial_commission": result["executions"][0]["commission"],
        "residual_cash": req.initial_capital - result["executions"][0]["gross_value"] - result["executions"][0]["commission"],
        "cash_return_assumption": 0.0,
        "final_raw_price": float(prepared.period.iloc[-1].close),
    }
    return result


def entry_zone_signals(prepared):
    p = prepared.request.parameters
    rows = []
    for index, (bar, ma, *_rest) in enumerate(prepared.rows):
        decision = evaluate_entry_zone(
            bar_open=bar.open, bar_high=bar.high, reference_ma=ma,
            breakout_trigger_pct=p.breakout_trigger_pct,
            entry_stop_pct=p.entry_stop_pct,
        )
        kind = "VALID_ENTRY" if decision.filled else "ENTRY_ZONE_MISSED" if decision.missed else "ARMED_UNFILLED" if decision.armed else "NO_SIGNAL"
        rows.append({
            "index": index, "date": bar.timestamp.date().isoformat(), "classification": kind,
            "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close,
            "reference_ma": ma, "lower_entry": decision.lower_entry, "upper_entry": decision.upper_entry,
            "raw_fill": decision.fill_price, "entry_allowed": decision.entry_allowed,
        })
    return rows


def entry_zone_hold(prepared):
    req = prepared.request
    pf = Portfolio(req.initial_capital, req.commission_pct, req.slippage_pct)
    signals = entry_zone_signals(prepared)
    values = []
    entry_index = None
    for index, ((bar, *_), signal) in enumerate(zip(prepared.rows, signals)):
        if pf.quantity == 0 and entry_index is None and signal["classification"] == "VALID_ENTRY":
            qty = initial_quantity(pf.equity(bar.open), req.position_size_pct, signal["raw_fill"], req.slippage_pct, req.commission_pct)
            pf.buy(bar.timestamp, signal["raw_fill"], qty, "ENTRY", "ENTRY_ZONE_V2_HOLD_ENTRY")
            entry_index = index
        if index == len(prepared.rows) - 1 and pf.quantity:
            pf.sell(bar.timestamp, bar.close, pf.quantity, "FINAL_EXIT", "ENTRY_ZONE_HOLD_FINAL_EXIT")
        values.append(pf.equity(bar.close))
    result = _finalize(prepared, pf, values, 0 if entry_index is None else len(values) - entry_index, "ENTRY_ZONE_HOLD")
    result["first_signal_index"] = entry_index
    return result


def independent_signal_horizon(prepared, signal, horizon):
    """Costed, fixed-horizon hold for one signal; never reinvests or re-enters."""
    target = signal["index"] + horizon
    if target >= len(prepared.rows):
        return {"complete": False, "target_date": None}
    req = prepared.request
    entry_bar = prepared.rows[signal["index"]][0]
    exit_bar = prepared.rows[target][0]
    pf = Portfolio(req.initial_capital, req.commission_pct, req.slippage_pct)
    qty = initial_quantity(req.initial_capital, req.position_size_pct, signal["raw_fill"], req.slippage_pct, req.commission_pct)
    buy = pf.buy(entry_bar.timestamp, signal["raw_fill"], qty, "ENTRY", "ENTRY_ZONE_V2_FIXED_HORIZON")
    sell = pf.sell(exit_bar.timestamp, exit_bar.close, qty, "FINAL_EXIT", f"RESEARCH_{horizon}D_HORIZON")
    net = pf.cash - req.initial_capital
    return {
        "complete": True, "target_date": exit_bar.timestamp.date().isoformat(), "sessions_after_entry": horizon,
        "q0": qty, "entry_execution_price": buy.price, "exit_execution_price": sell.price,
        "commission": pf.total_commission, "slippage_cost": pf.total_slippage_cost,
        "net_pnl": net, "return_on_initial_capital": net / req.initial_capital,
        "return_on_entry_cost": net / (buy.gross_value + buy.commission),
    }


def metric_view(result):
    summary, exposure = result["summary"], result["exposure"]
    return {
        **{key: summary.get(key) for key in METRICS},
        "turnover": exposure["two_sided_turnover"],
        "average_close_capital_exposure_pct": exposure["average_close_capital_exposure_pct"],
        "cash_pct": exposure["average_close_cash_pct"],
    }


def metric_delta(left, right):
    """right minus left; return and MDD are in percentage points."""
    def diff(key):
        a, b = left.get(key), right.get(key)
        return None if a is None or b is None else b - a
    return {
        "return_pp": 100 * diff("total_return"), "cagr_pp": 100 * diff("cagr"),
        "mdd_pp": 100 * diff("max_drawdown"), "sharpe": diff("sharpe_ratio"),
        "sortino": diff("sortino_ratio"), "calmar": diff("calmar_ratio"),
        "exposure_pp": diff("average_close_capital_exposure_pct"),
        "time_in_market_pp": diff("exposure_pct"), "turnover": diff("turnover"),
    }


def comparison_label(simple, hold):
    delta = metric_delta(hold, simple)
    if (simple["sharpe_ratio"] is not None and hold["sharpe_ratio"] is not None and
            simple["calmar_ratio"] is not None and hold["calmar_ratio"] is not None and
            delta["sharpe"] > 0 and delta["calmar"] > 0 and delta["mdd_pp"] >= 0):
        return "RISK_ADJUSTED_WIN"
    if delta["return_pp"] > 0:
        return "RETURN_WIN"
    if abs(delta["return_pp"]) <= 1 and delta["sharpe"] is not None and abs(delta["sharpe"]) <= .10:
        return "DRAW"
    return "LOSS"


def exposure_normalized(metrics):
    fraction = metrics["average_close_capital_exposure_pct"] / 100
    return {
        "return_per_average_exposure": metrics["total_return"] / fraction if fraction > 0 else None,
        "absolute_drawdown_per_average_exposure": abs(metrics["max_drawdown"]) / fraction if fraction > 0 else None,
        "average_exposure_fraction": fraction,
        "cash_return_assumption": 0.0,
        "warning": "Descriptive only: exposure varies through time and this ratio is not a recognized risk-adjusted performance measure.",
    }
