"""Cluster-aware descriptive statistics for the Simple-v2 viability study."""
from __future__ import annotations

import math
import numpy as np


def describe(values):
    a = np.asarray([float(x) for x in values if x is not None and np.isfinite(x)], float)
    return {
        "n": len(a), "mean": float(a.mean()) if len(a) else None,
        "median": float(np.median(a)) if len(a) else None,
        "sum": math.fsum(a), "positive": int((a > 1e-9).sum()),
        "negative": int((a < -1e-9).sum()), "zero": int((abs(a) <= 1e-9).sum()),
        "q05": float(np.quantile(a, .05)) if len(a) else None,
        "q95": float(np.quantile(a, .95)) if len(a) else None,
    }


def _block(value):
    day = value[:10]
    return day[:4] + "H" + ("1" if int(day[5:7]) <= 6 else "2")


def clustered_bootstrap(rows, key, date_key="entry_date", reps=4000, seed=20260905):
    """Two-way ticker × chronological-half-year cluster bootstrap.

    All observations from the same cluster receive the same integer resampling
    weight.  This is a descriptive uncertainty interval, not an iid test.
    """
    clean = [r for r in rows if r.get(key) is not None and np.isfinite(r[key])]
    if not clean:
        return {"n": 0, "replicates": 0, "mean_ci95": None, "median_ci95": None, "point": describe([])}
    symbols = sorted({r["symbol"] for r in clean})
    blocks = sorted({_block(r[date_key]) for r in clean})
    si = np.array([symbols.index(r["symbol"]) for r in clean])
    bi = np.array([blocks.index(_block(r[date_key])) for r in clean])
    x = np.array([r[key] for r in clean], float)
    rng = np.random.default_rng(seed)
    means, medians = [], []
    for _ in range(reps):
        sw = rng.multinomial(len(symbols), np.ones(len(symbols)) / len(symbols))[si]
        bw = rng.multinomial(len(blocks), np.ones(len(blocks)) / len(blocks))[bi]
        w = sw * bw
        if not w.sum():
            continue
        means.append(float(np.average(x, weights=w)))
        medians.append(float(np.median(np.repeat(x, w))))
    return {
        "n": len(clean), "ticker_clusters": symbols, "time_block_clusters": blocks,
        "replicates": len(means), "point": describe(x),
        "equal_ticker_mean": float(np.mean([x[si == i].mean() for i in range(len(symbols))])),
        "mean_ci95": np.quantile(means, [.025, .975]).tolist(),
        "median_ci95": np.quantile(medians, [.025, .975]).tolist(),
    }


def signal_block_bootstrap(rows, selected_class, horizon, reps=4000, seed=20260905):
    """Block-resampled difference: selected signal vs all-day forward return."""
    key = f"forward_{horizon}d_from_open"
    clean = [r for r in rows if r.get(key) is not None]
    selected = [r for r in clean if r["classification"] == selected_class]
    if not selected:
        return {"selected": describe([]), "unconditional": describe([]), "mean_difference": None, "mean_difference_ci95": None}
    symbols = sorted({r["symbol"] for r in clean})
    blocks = sorted({_block(r["date"]) for r in clean})
    # Aggregate observations to ticker×half-year cells once, then resample the
    # cells.  This is algebraically identical to assigning every row its two
    # cluster weights, but avoids hundreds of millions of Python operations.
    cells = [(s, b) for s in symbols for b in blocks]
    cell_index = {cell: i for i, cell in enumerate(cells)}
    sums_all = np.zeros(len(cells)); counts_all = np.zeros(len(cells))
    sums_selected = np.zeros(len(cells)); counts_selected = np.zeros(len(cells))
    for row in clean:
        i = cell_index[row["symbol"], _block(row["date"])]
        sums_all[i] += row[key]; counts_all[i] += 1
        if row["classification"] == selected_class:
            sums_selected[i] += row[key]; counts_selected[i] += 1
    si = np.array([symbols.index(s) for s, _ in cells])
    bi = np.array([blocks.index(b) for _, b in cells])
    rng = np.random.default_rng(seed + horizon)
    symbol_weights = rng.multinomial(len(symbols), np.ones(len(symbols)) / len(symbols), size=reps)
    block_weights = rng.multinomial(len(blocks), np.ones(len(blocks)) / len(blocks), size=reps)
    weights = symbol_weights[:, si] * block_weights[:, bi]
    den_selected = weights @ counts_selected
    den_all = weights @ counts_all
    valid = (den_selected > 0) & (den_all > 0)
    values = (weights[valid] @ sums_selected / den_selected[valid] -
              weights[valid] @ sums_all / den_all[valid]).tolist()
    return {
        "selected": describe([r[key] for r in selected]),
        "unconditional": describe([r[key] for r in clean]),
        "mean_difference": float(np.mean([r[key] for r in selected]) - np.mean([r[key] for r in clean])),
        "mean_difference_ci95": np.quantile(values, [.025, .975]).tolist(),
        "replicates": len(values), "selected_count": len(selected), "all_days_count": len(clean),
    }


def winner_concentration(positions):
    positive = sorted([p for p in positions if p["net_pnl"] > 0], key=lambda p: p["net_pnl"], reverse=True)
    total_profit = math.fsum(p["net_pnl"] for p in positive)
    all_net = math.fsum(p["net_pnl"] for p in positions)
    def top(k):
        amount = math.fsum(p["net_pnl"] for p in positive[:k])
        return {"amount": amount, "share_of_gross_profit": amount / total_profit if total_profit else None,
                "share_of_net_pnl": amount / all_net if all_net else None}
    n1 = max(1, math.ceil(len(positive) * .01)) if positive else 0
    n5 = max(1, math.ceil(len(positive) * .05)) if positive else 0
    return {
        "positions": len(positions), "winners": len(positive), "total_gross_profit": total_profit,
        "total_net_pnl": all_net, "top": {str(k): top(k) for k in (1, 3, 5, 10)},
        "remove_largest_winner_net_pnl": math.fsum(p["net_pnl"] for p in positions) - (positive[0]["net_pnl"] if positive else 0),
        "trim_top_1pct_winners_net_pnl": math.fsum(p["net_pnl"] for p in positions) - math.fsum(p["net_pnl"] for p in positive[:n1]),
        "trim_top_5pct_winners_net_pnl": math.fsum(p["net_pnl"] for p in positions) - math.fsum(p["net_pnl"] for p in positive[:n5]),
        "top_positions": positive[:10],
    }
