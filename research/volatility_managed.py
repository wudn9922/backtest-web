"""Research-only frozen 20-day volatility-managed exposure benchmark."""
from __future__ import annotations

import hashlib
import math
from typing import Any

import numpy as np
import pandas as pd

from research import ROOT

SPEC = ROOT / "research/specs/VOLATILITY_MANAGED_BENCHMARK.md"
SPEC_HASH = "1fb8cf44732e2e8cea434db8c1f030e7e79d701ca35b8289170563f914766a3d"
LOOKBACK = 20
TARGET_VOL = 0.15
ANNUALIZATION = 252


def verify_spec() -> None:
    assert hashlib.sha256(SPEC.read_bytes()).hexdigest() == SPEC_HASH, "Frozen volatility-managed specification changed"


def exposure_schedule(frame: pd.DataFrame) -> pd.DataFrame:
    """Return t+1-open targets calculated only from completed closes through t."""
    returns = frame["close"].pct_change()
    rv = returns.rolling(LOOKBACK).std(ddof=1) * math.sqrt(ANNUALIZATION)
    target = (TARGET_VOL / rv).clip(lower=0.0, upper=1.0).where(np.isfinite(rv) & (rv > 0))
    rows = []
    for signal_i in range(LOOKBACK, len(frame) - 1):
        if pd.isna(target.iloc[signal_i]):
            continue
        rows.append({
            "execution_date": frame.index[signal_i + 1],
            "signal_date": frame.index[signal_i],
            "rv20": float(rv.iloc[signal_i]),
            "target_exposure": float(target.iloc[signal_i]),
        })
    if not rows:
        return pd.DataFrame(columns=["signal_date", "rv20", "target_exposure"])
    return pd.DataFrame(rows).set_index("execution_date")


def _drawdown(values: np.ndarray, initial: float) -> tuple[np.ndarray, int, int]:
    path = np.r_[initial, values]
    peaks = np.maximum.accumulate(path)
    dd = path / peaks - 1
    trough = int(np.argmin(dd))
    peak = int(np.argmax(path[:trough + 1]))
    return dd[1:], peak, trough


def calculate_metrics(rows: list[dict[str, Any]], initial: float) -> dict[str, Any]:
    if not rows:
        return {}
    equity = np.asarray([row["equity"] for row in rows], dtype=float)
    returns = equity / np.r_[initial, equity[:-1]] - 1
    dd, peak, trough = _drawdown(equity, initial)
    days = max(1, (pd.Timestamp(rows[-1]["date"]) - pd.Timestamp(rows[0]["date"])).days + 1)
    years = days / 365.25
    cagr = (equity[-1] / initial) ** (1 / years) - 1
    std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    downside = float(np.sqrt(np.mean(np.minimum(returns, 0) ** 2)))
    mdd = float(dd.min())
    peak_equity = initial if peak == 0 else equity[peak - 1]
    recovery = next((rows[i]["date"] for i in range(max(0, trough), len(rows)) if equity[i] >= peak_equity), None)
    close_exposure = np.asarray([row["close_exposure"] for row in rows])
    traded_ratio = np.asarray([row["traded_value"] / row["equity"] if row["equity"] else 0 for row in rows])
    exposure = float(close_exposure.mean())
    turnover = float(sum(row["traded_value"] for row in rows) / equity.mean())
    return {
        "initial_capital": initial,
        "final_equity": float(equity[-1]),
        "total_return": float(equity[-1] / initial - 1),
        "cagr": float(cagr),
        "annualized_volatility": std * math.sqrt(ANNUALIZATION),
        "mdd": mdd,
        "sharpe": float(np.mean(returns) / std * math.sqrt(ANNUALIZATION)) if std else None,
        "sortino": float(np.mean(returns) / downside * math.sqrt(ANNUALIZATION)) if downside else None,
        "calmar": float(cagr / abs(mdd)) if mdd else None,
        "exposure": exposure,
        "cash_pct": float(np.mean([row["cash"] / row["equity"] for row in rows])),
        "turnover": turnover,
        "annual_turnover": turnover / years,
        "average_daily_turnover": float(traded_ratio.mean()),
        "commission": float(sum(row["commission"] for row in rows)),
        "slippage": float(sum(row["slippage"] for row in rows)),
        "cash_interest": float(sum(row["interest"] for row in rows)),
        "equity_pnl_before_cost": float(sum(row["raw_equity_pnl"] for row in rows)),
        "number_of_trades": int(sum(row["trade_count"] for row in rows)),
        "number_of_adjustment_trades": int(sum(row["adjustment_trade"] for row in rows)),
        "adjustment_days": int(sum(row["adjustment_trade"] > 0 for row in rows)),
        "return_per_unit_exposure": float((equity[-1] / initial - 1) / exposure) if exposure else None,
        "drawdown_start": rows[max(0, peak - 1)]["date"],
        "drawdown_trough": rows[max(0, trough - 1)]["date"],
        "drawdown_recovery": recovery,
        "sessions": len(rows),
    }


def simulate(
    frame: pd.DataFrame,
    schedule: pd.DataFrame,
    kind: str,
    start: Any,
    end: Any,
    capital: float,
    commission: float,
    slippage: float,
    cash_factors: dict[pd.Timestamp, float] | None = None,
) -> dict[str, Any]:
    """Simulate MANAGED or BUY_HOLD using fractions for commission/slippage."""
    if kind not in {"MANAGED", "BUY_HOLD"}:
        raise ValueError("Unknown volatility benchmark kind")
    dates = frame.index[(frame.index >= pd.Timestamp(start)) & (frame.index <= pd.Timestamp(end))]
    if len(dates) < 2:
        raise ValueError("Evaluation period requires at least two sessions")
    if dates[0] not in schedule.index:
        raise ValueError("Evaluation start lacks a prior completed RV20 target")
    cash = float(capital)
    quantity = 0
    previous: pd.Timestamp | None = None
    daily: list[dict[str, Any]] = []
    executions: list[dict[str, Any]] = []
    target_changes: list[float] = []
    previous_target: float | None = None

    for i, timestamp in enumerate(dates):
        row = frame.loc[timestamp]
        opening_cash = cash
        old_quantity = quantity
        interest = cash * (cash_factors.get(timestamp, 0.0) if cash_factors and previous is not None else 0.0)
        cash += interest
        day_commission = day_slippage = traded_value = raw_equity_pnl = 0.0
        trade_count = adjustment_trade = 0

        signal = schedule.loc[timestamp]
        target = 1.0 if kind == "BUY_HOLD" else float(signal["target_exposure"])
        if previous_target is not None:
            target_changes.append(abs(target - previous_target))
        previous_target = target
        should_adjust = i == 0 or kind == "MANAGED"
        pretrade_equity = cash + quantity * float(row["open"])
        desired = math.floor(pretrade_equity * target / float(row["open"]))
        if should_adjust and desired != quantity:
            change = desired - quantity
            if change > 0:
                unit_cost = float(row["open"]) * (1 + slippage) * (1 + commission)
                change = min(change, max(0, math.floor((cash + 1e-9) / unit_cost)))
            if change:
                buy = change > 0
                shares = abs(change)
                raw_fill = float(row["open"])
                execution = raw_fill * (1 + slippage if buy else 1 - slippage)
                fee = shares * execution * commission
                slip_cost = shares * abs(execution - raw_fill)
                cash -= change * execution + fee
                quantity += change
                day_commission += fee
                day_slippage += slip_cost
                traded_value += shares * execution
                trade_count += 1
                if i > 0:
                    adjustment_trade += 1
                executions.append({
                    "date": timestamp.date().isoformat(), "signal_date": pd.Timestamp(signal["signal_date"]).date().isoformat(),
                    "side": "BUY" if buy else "SELL", "quantity": shares, "raw_fill": raw_fill,
                    "execution_price": execution, "commission": fee, "slippage_cost": slip_cost,
                    "position_remaining": quantity, "rv20": float(signal["rv20"]),
                    "target_exposure": target, "event": "INITIAL_ALLOCATION" if i == 0 else "VOLATILITY_EXPOSURE_ADJUSTMENT",
                })

        if previous is not None:
            raw_equity_pnl += old_quantity * (float(row["close"]) - float(frame.loc[previous, "close"]))
        for execution in executions[-trade_count:] if trade_count else []:
            change = execution["quantity"] if execution["side"] == "BUY" else -execution["quantity"]
            raw_equity_pnl += change * (float(row["close"]) - execution["raw_fill"])

        actual_open_equity = cash + quantity * float(row["open"])
        open_exposure = quantity * float(row["open"]) / actual_open_equity if actual_open_equity else 0.0

        if i == len(dates) - 1 and quantity:
            shares = quantity
            raw_fill = float(row["close"])
            execution = raw_fill * (1 - slippage)
            fee = shares * execution * commission
            slip_cost = shares * (raw_fill - execution)
            cash += shares * execution - fee
            quantity = 0
            day_commission += fee
            day_slippage += slip_cost
            traded_value += shares * execution
            trade_count += 1
            executions.append({
                "date": timestamp.date().isoformat(), "signal_date": None, "side": "SELL", "quantity": shares,
                "raw_fill": raw_fill, "execution_price": execution, "commission": fee,
                "slippage_cost": slip_cost, "position_remaining": 0, "rv20": float(signal["rv20"]),
                "target_exposure": target, "event": "FINAL_LIQUIDATION",
            })

        if cash < -1e-6 or quantity < 0:
            raise AssertionError("Volatility benchmark created negative cash or shares")
        invested = quantity * float(row["close"])
        equity = cash + invested
        before = daily[-1]["equity"] if daily else capital
        expected = before + interest + raw_equity_pnl - day_commission - day_slippage
        if abs(equity - expected) > 1e-7 * max(1.0, capital):
            raise AssertionError(f"Daily accounting failed at {timestamp}: {equity} != {expected}")
        daily.append({
            "date": timestamp.date().isoformat(), "equity": equity, "cash": cash, "invested": invested,
            "open": float(row["open"]), "close": float(row["close"]), "rv20": float(signal["rv20"]),
            "target_exposure": target, "open_exposure": open_exposure,
            "close_exposure": invested / equity if equity else 0.0, "quantity": quantity,
            "interest": interest, "commission": day_commission, "slippage": day_slippage,
            "raw_equity_pnl": raw_equity_pnl, "traded_value": traded_value,
            "trade_count": trade_count, "adjustment_trade": adjustment_trade,
            "opening_cash": opening_cash,
        })
        previous = timestamp

    result = {
        "kind": kind, "ticker": None, "capital": capital, "start": dates[0].date().isoformat(),
        "end": dates[-1].date().isoformat(), "daily": daily, "executions": executions,
        "metrics": calculate_metrics(daily, capital),
        "target_change_distribution": {
            "count": len(target_changes), "mean_abs": float(np.mean(target_changes)) if target_changes else None,
            "median_abs": float(np.median(target_changes)) if target_changes else None,
            "p90_abs": float(np.quantile(target_changes, .9)) if target_changes else None,
            "maximum_abs": float(max(target_changes)) if target_changes else None,
        },
    }
    reconciliation = (
        result["metrics"]["equity_pnl_before_cost"] + result["metrics"]["cash_interest"]
        - result["metrics"]["commission"] - result["metrics"]["slippage"]
    )
    if abs((result["metrics"]["final_equity"] - capital) - reconciliation) > 1e-7 * capital:
        raise AssertionError("Full-period volatility benchmark accounting does not reconcile")
    return result


def metric_delta(managed: dict[str, Any], benchmark: dict[str, Any]) -> dict[str, Any]:
    keys = ("total_return", "cagr", "annualized_volatility", "mdd", "sharpe", "sortino", "calmar", "exposure", "turnover")
    return {key: managed[key] - benchmark[key] if managed.get(key) is not None and benchmark.get(key) is not None else None for key in keys}


def slice_metrics(result: dict[str, Any], start: Any, end: Any) -> dict[str, Any] | None:
    rows = result["daily"]
    selected = [row for row in rows if str(start)[:10] <= row["date"] <= str(end)[:10]]
    if not selected:
        return None
    index = next(i for i, row in enumerate(rows) if row is selected[0])
    initial = rows[index - 1]["equity"] if index else result["capital"]
    return calculate_metrics(selected, initial)


def paired_block_uncertainty(managed: dict[str, Any], benchmark: dict[str, Any], draws: int = 2000) -> dict[str, Any]:
    managed_returns = np.asarray([row["equity"] for row in managed["daily"]]) / np.r_[managed["capital"], [row["equity"] for row in managed["daily"][:-1]]] - 1
    benchmark_returns = np.asarray([row["equity"] for row in benchmark["daily"]]) / np.r_[benchmark["capital"], [row["equity"] for row in benchmark["daily"][:-1]]] - 1
    assert len(managed_returns) == len(benchmark_returns)
    rng = np.random.default_rng(2015001)
    block = 63
    values = []

    def stats(returns: np.ndarray) -> tuple[float, float, float, float]:
        std = float(np.std(returns, ddof=1))
        sharpe = float(np.mean(returns) / std * math.sqrt(252)) if std else 0.0
        path = np.cumprod(1 + returns)
        mdd = float(np.min(path / np.maximum.accumulate(np.r_[1.0, path])[1:] - 1))
        annual = float(np.prod(1 + returns) ** (252 / len(returns)) - 1)
        calmar = annual / abs(mdd) if mdd else 0.0
        return float(np.mean(returns) * 252), sharpe, mdd, calmar

    for _ in range(draws):
        starts = rng.integers(0, len(managed_returns), math.ceil(len(managed_returns) / block))
        indexes = np.concatenate([(start + np.arange(block)) % len(managed_returns) for start in starts])[:len(managed_returns)]
        left, right = stats(managed_returns[indexes]), stats(benchmark_returns[indexes])
        values.append([left[i] - right[i] for i in range(4)])
    array = np.asarray(values)
    labels = ("annualized_arithmetic_return_delta", "sharpe_delta", "mdd_delta", "calmar_delta")
    return {
        "method": "paired circular 63-session block bootstrap; 2000 draws; seed 2015001",
        "sessions": len(managed_returns),
        **{label: {"mean": float(array[:, i].mean()), "ci95": np.quantile(array[:, i], [.025, .975]).tolist()} for i, label in enumerate(labels)},
    }
