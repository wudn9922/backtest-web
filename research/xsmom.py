"""Frozen monthly multi-asset benchmark. Never imports a production strategy."""
from __future__ import annotations

import hashlib
import math
import numpy as np
import pandas as pd

from research import ROOT

SPEC_HASH = "377385ca92633c5077420de74caa529d102a4c49ef0433db6b499498a4f1b68c"
SPEC = ROOT / "research/specs/CROSS_SECTIONAL_MOMENTUM_BENCHMARK.md"


def verify_spec():
    assert hashlib.sha256(SPEC.read_bytes()).hexdigest() == SPEC_HASH, "Frozen specification changed"


def rankings(frames):
    calendar = frames["SPY"].index
    closes = pd.DataFrame({s: f.close.reindex(calendar) for s, f in frames.items()})
    valid = closes.notna().rolling(253).sum().eq(253)
    scores = (closes.shift(21) / closes.shift(252) - 1).where(valid)
    schedule = {}
    for i in range(len(calendar) - 1):
        t, nxt = calendar[i], calendar[i + 1]
        if t.month == nxt.month:
            continue
        ranked = sorted(scores.loc[t].dropna().items(), key=lambda x: (-x[1], x[0]))
        if len(ranked) >= 3:
            schedule[nxt] = {"signal_date": t.date().isoformat(), "eligible_count": len(ranked),
                             "ranking": [s for s, _ in ranked], "scores": dict(ranked)}
    return schedule


def metrics(rows, capital=100000):
    eq = np.array([r["equity"] for r in rows], dtype=float)
    if not len(eq):
        return {}
    ret = eq / np.r_[capital, eq[:-1]] - 1
    dd = eq / np.maximum.accumulate(np.r_[capital, eq])[1:] - 1
    days = max(1, (pd.Timestamp(rows[-1]["date"]) - pd.Timestamp(rows[0]["date"])).days + 1)
    cagr = (eq[-1] / capital) ** (365.25 / days) - 1
    std = np.std(ret, ddof=1) if len(ret) > 1 else 0
    downside = np.sqrt(np.mean(np.minimum(ret, 0) ** 2))
    mdd = float(dd.min())
    trough = int(np.argmin(dd))
    peak = int(np.argmax(np.r_[capital, eq[:trough + 1]]))
    recovery = next((rows[i]["date"] for i in range(trough + 1, len(eq)) if eq[i] >= max(capital, max(eq[:trough + 1]))), None)
    return {"total_return": float(eq[-1] / capital - 1), "cagr": float(cagr), "mdd": mdd,
            "sharpe": float(np.mean(ret) / std * np.sqrt(252)) if std else None,
            "sortino": float(np.mean(ret) / downside * np.sqrt(252)) if downside else None,
            "calmar": float(cagr / abs(mdd)) if mdd else None,
            "exposure": float(np.mean([r["invested"] / r["equity"] for r in rows])),
            "cash_pct": float(np.mean([r["cash"] / r["equity"] for r in rows])),
            "average_holdings": float(np.mean([r["holdings_count"] for r in rows])),
            "turnover": sum(r["traded_value"] for r in rows) / float(eq.mean()),
            "commission": sum(r["commission"] for r in rows),
            "slippage": sum(r["slippage"] for r in rows),
            "rebalances": sum(r["rebalance"] for r in rows),
            "cash_interest": sum(r["interest"] for r in rows),
            "drawdown_start": rows[max(0, peak - 1)]["date"], "drawdown_trough": rows[trough]["date"],
            "drawdown_recovery": recovery}


def slice_metrics(result, start, end):
    rows = result["daily"]
    selected = [r for r in rows if str(start)[:10] <= r["date"] <= str(end)[:10]]
    if not selected:
        return None
    i = next(i for i, r in enumerate(rows) if r is selected[0])
    return metrics(selected, rows[i - 1]["equity"] if i else result["capital"])


def simulate(frames, schedule, kind, start, end, capital, commission, slippage, cash_factors=None, exclude=None):
    """Fractions, not percentage points, for costs. No borrowed cash."""
    calendar = frames["SPY"].index
    dates = calendar[(calendar >= pd.Timestamp(start)) & (calendar <= pd.Timestamp(end))]
    opens = {s: f.open.to_dict() for s, f in frames.items()}
    closes = {s: f.close.to_dict() for s, f in frames.items()}
    qty = {s: 0 for s in frames}
    lots = {s: [] for s in frames}
    cash = float(capital)
    trades, daily, holdings, durations = [], [], [], []
    contribution = dict.fromkeys(frames, 0.0)
    previous = None
    for i, t in enumerate(dates):
        old_qty, old_cash = qty.copy(), cash
        interest = cash * (cash_factors.get(t, 0) if cash_factors and previous is not None else 0)
        cash += interest
        traded = fees = slip_cost = 0.0
        day_trades = []

        def execute(symbol, change, raw, phase):
            nonlocal cash, traded, fees, slip_cost
            if not change:
                return
            buy = change > 0
            price = raw * (1 + slippage if buy else 1 - slippage)
            count = abs(change)
            fee = count * price * commission
            cash -= change * price + fee
            qty[symbol] += change
            traded += count * price
            fees += fee
            slip_cost += count * abs(price - raw)
            event = {"date": t.date().isoformat(), "symbol": symbol, "side": "BUY" if buy else "SELL",
                     "qty": count, "raw_fill": raw, "price": price, "commission": fee,
                     "slippage": count * abs(price - raw), "remaining": qty[symbol], "phase": phase}
            trades.append(event); day_trades.append(event)
            if buy:
                lots[symbol].append([i, count])
            else:
                left = count
                while left:
                    opened, available = lots[symbol][0]
                    used = min(left, available)
                    durations.append({"symbol": symbol, "sessions": i - opened, "shares": used})
                    left -= used; lots[symbol][0][1] -= used
                    if not lots[symbol][0][1]:
                        lots[symbol].pop(0)

        rebalance = (i == 0 or t in schedule) and (kind not in ("SPY", "QQQ") or i == 0)
        selected = []
        if rebalance:
            known = max(k for k in schedule if k <= t)
            signal = schedule[known]
            rank = [s for s in signal["ranking"] if s != exclude]
            selected = [kind] if kind in ("SPY", "QQQ") else (rank[:3] if kind == "RS" else rank)
            if not selected:
                raise ValueError("No eligible ETF")
            equity_open = cash + sum(qty[s] * opens[s][t] for s in qty if qty[s])
            targets = {s: math.floor(equity_open / len(selected) / opens[s][t] / ((1 + slippage) * (1 + commission))) if s in selected else 0 for s in qty}
            for s in sorted(qty):
                if targets[s] < qty[s]:
                    execute(s, targets[s] - qty[s], opens[s][t], "OPEN")
            for s in sorted(selected):
                need = max(0, targets[s] - qty[s])
                affordable = max(0, math.floor((cash + 1e-9) / (opens[s][t] * (1 + slippage) * (1 + commission))))
                execute(s, min(need, affordable), opens[s][t], "OPEN")
            holdings.append({"date": t.date().isoformat(), **signal, "selected": selected,
                             "quantities": {s: q for s, q in qty.items() if q},
                             "weights_at_open": {s: qty[s] * opens[s][t] / equity_open for s in selected}})
        if i == len(dates) - 1:
            for s in sorted(qty):
                if qty[s]:
                    execute(s, -qty[s], closes[s][t], "FINAL_CLOSE")
        if cash < -1e-6 or any(q < 0 for q in qty.values()):
            raise AssertionError("Negative cash or shares")
        invested = sum(q * closes[s][t] for s, q in qty.items() if q)
        increments = {}
        for s in qty:
            value = (old_qty[s] * (closes[s][t] - closes[s][previous]) if old_qty[s] and previous is not None else 0)
            for e in day_trades:
                if e["symbol"] == s:
                    change = e["qty"] if e["side"] == "BUY" else -e["qty"]
                    value += change * (closes[s][t] - e["price"]) - e["commission"]
            increments[s] = value
            contribution[s] += value
        equity = cash + invested
        before = daily[-1]["equity"] if daily else capital
        assert abs(equity - before - interest - sum(increments.values())) < 1e-6 * max(1, capital)
        daily.append({"date": t.date().isoformat(), "equity": equity, "cash": cash, "invested": invested,
                      "holdings_count": sum(q > 0 for q in qty.values()), "quantities": {s:q for s,q in qty.items() if q},
                      "weights": {s: q * closes[s][t] / equity for s,q in qty.items() if q},
                      "contribution": increments, "interest": interest, "commission": fees,
                      "slippage": slip_cost, "traded_value": traded, "rebalance": int(rebalance)})
        previous = t
    result = {"kind": kind, "capital": capital, "daily": daily, "executions": trades,
              "monthly_holdings": holdings, "etf_contribution": contribution,
              "holding_durations": durations, "metrics": metrics(daily, capital)}
    result["metrics"]["average_holding_sessions"] = (sum(d["sessions"] * d["shares"] for d in durations) / sum(d["shares"] for d in durations)) if durations else None
    return result


def paired_uncertainty(a, b, draws=2000):
    def monthly(result):
        e = pd.Series({r["date"]: r["equity"] for r in result["daily"]})
        e.index = pd.to_datetime(e.index)
        m = e.resample("ME").last()
        return np.log(m / m.shift(1).fillna(result["capital"]))
    diff = (monthly(a) - monthly(b)).dropna().to_numpy()
    rng = np.random.default_rng(1201252)
    means = []
    for _ in range(draws):
        starts = rng.integers(0, len(diff), math.ceil(len(diff) / 12))
        sample = np.concatenate([diff[(s + np.arange(12)) % len(diff)] for s in starts])[:len(diff)]
        means.append(float(sample.mean() * 12))
    return {"method": "paired circular 12-month block bootstrap; 2000 draws; seed 1201252",
            "annualized_mean_log_return_delta": float(diff.mean() * 12),
            "ci95": np.quantile(means, [.025, .975]).tolist(), "months": len(diff)}
