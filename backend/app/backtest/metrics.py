from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def _safe(value: float | np.floating | None) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return float(value)


def drawdown_details(equity: pd.Series) -> tuple[pd.Series, dict[str, Any]]:
    running_max = equity.cummax()
    drawdown = equity / running_max - 1
    bottom = drawdown.idxmin()
    start = equity.loc[:bottom].idxmax()
    peak = running_max.loc[bottom]
    later = equity.loc[bottom:]
    recovered = later[later >= peak]
    recovery = recovered.index[0] if len(recovered) else None
    return drawdown, {
        "max_drawdown": float(drawdown.min()),
        "max_drawdown_start": pd.Timestamp(start).date().isoformat(),
        "max_drawdown_bottom": pd.Timestamp(bottom).date().isoformat(),
        "recovery_date": pd.Timestamp(recovery).date().isoformat() if recovery is not None else None,
    }


def monthly_returns(equity: pd.Series) -> list[dict[str, Any]]:
    values = equity.resample("ME").last().pct_change().dropna()
    return [{"year": int(ts.year), "month": int(ts.month), "return": float(value)} for ts, value in values.items()]


def calculate_metrics(equity: pd.Series, benchmark: pd.Series, positions: list[dict], initial_capital: float, exposure_days: int, total_days: int, total_commission: float, slippage: float, sell_count: int) -> tuple[dict[str, Any], pd.Series]:
    returns = equity.pct_change().fillna(0)
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1 / 365.25)
    final = float(equity.iloc[-1])
    total_return = final / initial_capital - 1
    cagr = (final / initial_capital) ** (1 / years) - 1 if final > 0 else -1
    std = returns.std(ddof=0)
    sharpe = returns.mean() / std * math.sqrt(252) if std > 0 else None
    downside = returns[returns < 0]
    downside_std = downside.std(ddof=0)
    sortino = returns.mean() / downside_std * math.sqrt(252) if downside_std > 0 else None
    drawdown, dd = drawdown_details(equity)
    calmar = cagr / abs(dd["max_drawdown"]) if dd["max_drawdown"] < 0 else None
    bh_return = float(benchmark.iloc[-1] / benchmark.iloc[0] - 1)
    pnls = [float(p["net_pnl"]) for p in positions]
    trade_returns = [float(p["return_pct"]) / 100 for p in positions]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit, gross_loss = sum(wins), abs(sum(losses))
    summary = {
        "initial_capital": initial_capital,
        "final_equity": final,
        "total_return": total_return,
        "cagr": cagr,
        "buy_hold_return": bh_return,
        "alpha_vs_buy_hold": total_return - bh_return,
        **dd,
        "sharpe_ratio": _safe(sharpe),
        "sortino_ratio": _safe(sortino),
        "calmar_ratio": _safe(calmar),
        "number_of_positions": len(positions),
        "number_of_sell_executions": sell_count,
        "win_rate": len(wins) / len(pnls) if pnls else 0,
        "profit_factor": gross_profit / gross_loss if gross_loss else (None if not gross_profit else 999.0),
        "average_trade_return": _safe(np.mean(trade_returns)) if trade_returns else None,
        "median_trade_return": _safe(np.median(trade_returns)) if trade_returns else None,
        "average_winner": _safe(np.mean(wins)) if wins else None,
        "average_loser": _safe(np.mean(losses)) if losses else None,
        "best_trade": max(pnls) if pnls else None,
        "worst_trade": min(pnls) if pnls else None,
        "average_holding_days": _safe(np.mean([p["holding_days"] for p in positions])) if positions else None,
        "exposure_pct": exposure_days / total_days * 100 if total_days else 0,
        "total_commission": total_commission,
        "estimated_slippage_cost": slippage,
    }
    return summary, drawdown

