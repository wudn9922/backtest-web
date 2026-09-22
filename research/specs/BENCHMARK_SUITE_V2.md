# Benchmark Suite v2 — Frozen Specification

Frozen before the Benchmark Viability Study. Periods, costs and policy labels may vary only as predeclared research dimensions; benchmark rules and lookbacks may not change.

## Buy & Hold

- Enter maximum affordable whole shares on the first eligible evaluation-day open.
- Hold through the evaluation period and sell on the final evaluation-day close.
- Apply the same buy/sell slippage and commission model as every comparator.
- Residual cash earns 0%.

## SPY Buy & Hold

- Apply the identical Buy & Hold contract to SPY over the same evaluation dates.
- It is a cross-asset comparator, not a production strategy.

## SMA200 Trend

- Indicator: unadjusted parameter fixed at 200 completed daily closes on the dataset's consistent adjusted-price basis.
- At close t, `Close(t) > SMA200(t)` schedules long for the next trading-day open.
- At close t, `Close(t) <= SMA200(t)` schedules cash for the next trading-day open.
- A close never executes its own signal. Initial evaluation-day state uses the previous completed session's signal.
- Gap execution is the next session's actual open; no intrabar ordering policy is used.
- Final residual position sells on the evaluation period's last close.

## Donchian 20/10

- Entry level at t: maximum High over sessions t-20 through t-1.
- Exit level at t: minimum Low over sessions t-10 through t-1.
- Flat gap entry: if Open >= prior 20-day high, buy at Open. Otherwise, if High reaches the level, buy at the level.
- Existing-position gap exit: if Open <= prior 10-day low, sell at Open. Otherwise, if Low reaches the level, sell at the level.
- Existing adverse exit has priority and no same-day re-entry is allowed.
- If a flat bar has Open below entry, High reaches entry and Low also reaches exit, ordering is genuinely ambiguous: Conservative assumes entry then adverse exit; Favorable assumes the low occurred before entry; OHLC Heuristic uses Open→Low→High→Close when Close>=Open and Open→High→Low→Close otherwise.
- If entry occurs at Open, any Low touching the exit afterward is an unambiguous same-day exit under all policies.
- Final residual position sells on the evaluation period's last close.

## Shared accounting and evaluation

- Long only, one position, whole shares, no leverage.
- Baseline capital, allocation, commission and slippage are inherited unchanged from the canonical Framework v2 request.
- Data before the common evaluation start is indicator warm-up only and cannot contribute return.
- Buy & Hold begins on the same common evaluation start.

