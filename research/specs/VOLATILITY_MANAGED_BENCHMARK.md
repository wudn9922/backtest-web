# VOL_MANAGED_20D_15PCT_CAP1 — frozen benchmark specification v1

Registered before any result. Research benchmark only; no strategy candidate or production registration.

## Inputs and scope

Primary instrument: SPY. Robustness universe: the frozen ETF_RESEARCH_UNIVERSE
(SPY, QQQ, IWM, DIA, XLK, XLF, XLE, XLV, XLI, XLP, XLY, XLU, XLB, XLRE).
Each ETF uses its real available history; XLRE is never backfilled. Inputs are
the immutable validated Research Environment v3 snapshot, Yahoo
`adjusted_for_splits` daily OHLCV and validated FRED DGS3MO. No download,
parameter selection or data substitution occurs during this study.

Canonical capital, commission percentage and slippage percentage are read from
the frozen production-v2 research request. Costs are applied independently to
every execution. Whole shares, long only, no leverage, no shorting.

## Signal and execution

For completed session t, compute close-to-close simple returns. RV20(t) is the
sample standard deviation (`ddof=1`) of the 20 returns ending at t, multiplied
by sqrt(252). The signal needs 21 completed closes. Target equity exposure is
`min(1.0, 0.15 / RV20(t))`; finite positive RV is required. Exposure is never
below zero or above one. It is position sizing, not a directional entry rule.

The t-close target executes only at the next trading session open. At that
open, cash interest is accrued first. Pre-trade equity is cash plus current
shares times raw open. Raw target shares are floor(pre-trade equity times
target exposure divided by raw open). If buying that quantity would exceed
cash after buy slippage and commission, reduce to the maximum affordable whole
shares. A lower target sells first. Trade only when target shares differ from
current shares. There is no threshold, band, frequency change or same-close
execution. Final remaining shares sell at the final evaluation-session close.

Buy execution price = raw fill times (1 + slippage). Sell execution price =
raw fill times (1 - slippage). Commission is execution value times commission
rate. SPY/ETF buy-and-hold uses the same engine with target exposure 1.0 at the
common first evaluation open, no interim adjustment, and the same final close.

For each ETF, data start is its first real session. The first signal date is
index 20, after 20 completed returns; common strategy/B&H evaluation starts at
index 21 (next open). Cross-ETF medians compare each ETF over its own fair
period. No ETF is forced to inherit another ETF's inception date.

## Cash, accounting and metrics

Run CASH_ZERO and CASH_RISK_FREE. Risk-free cash uses validated FRED DGS3MO,
latest observation dated on or before the prior research session, ACT/365
effective compounding, on cash balance only. Invested value earns no cash
interest. Interest becomes cash available for subsequent sizing.

Daily equity is marked at close. Price PnL before costs, cash interest,
commission and raw-versus-execution slippage cost are recorded separately and
must reconcile exactly to final equity. Daily returns include the initial
capital as first denominator. Annualized volatility is sample daily-return
standard deviation times sqrt(252). Sharpe and Sortino use zero hurdle and
sqrt(252); downside deviation is RMS of min(return,0). CAGR uses calendar
days/365.25. MDD includes initial capital; Calmar=CAGR/abs(MDD). Exposure is
mean close invested/equity; cash percentage is mean close cash/equity.
Turnover is two-sided gross execution value divided by mean daily equity;
annual turnover divides by evaluation years. Average daily turnover is gross
execution value divided by daily equity, averaged across sessions. Return per
unit exposure is total return divided by average exposure and is descriptive.

## Frozen analyses

SPY fixed periods and crises are exactly Research Environment v3
`MARKET_CYCLE_WINDOWS` and `CRISIS_EPISODES`. Window returns use the immediately
preceding full-run equity observation as denominator and retain live state.
For each crisis, report daily target/actual exposure, first target below 50%,
minimum target/actual exposure, days actual exposure below 50%, SPY B&H trough,
drawdowns, and recovery participation. Recovery date is the first post-trough
session when B&H equity regains its equity immediately before the episode;
participation is managed return divided by B&H return from trough through that
date. Timeliness is the number of trading sessions from episode start to first
target below 50%; negative means the strategy was already below 50%.

Post-crash rebound cost for 2020_CRASH and 2022_BEAR starts at the B&H trough
inside the frozen episode and ends 21, 63 and 126 trading sessions later (or
the dataset end, flagged incomplete). It compares continuous managed and B&H
equity returns; no strategy is restarted at the trough.

Robustness applies identical 20/15/cap1 rules to all 14 ETFs. Report counts and
medians for Sharpe, MDD, CAGR and Calmar deltas versus each ETF's B&H under both
cash models. Cash-zero is primary evidence.

Retrospective walk-forward uses six-month chronological test folds after two
years from each ETF's evaluation start, advancing six months. Each test starts
with fresh capital at the first test open and uses the completed RV target from
the prior session. The final short fold is retained and flagged. Expanding
train starts at the ETF evaluation start; rolling train uses the prior two
years. Train windows never select or change a parameter. Because parameters
are fixed, expanding and rolling share identical test results and are not
counted as independent evidence. CASH_ZERO and CASH_RISK_FREE are both stored.

Cost stress is baseline, 2x commission, 2x slippage and 2x both for SPY and all
ETF robustness cells. A zero-cost run reports gross benefit; no cost scenario
changes signal parameters. Turnover diagnostics report adjustment executions,
days adjusted, average daily and annual turnover, and the distribution of
absolute target-exposure changes. No rebalance band is inferred.

Uncertainty uses paired managed/B&H daily returns for SPY CASH_ZERO, circular
63-trading-session block bootstrap, 2,000 draws, seed 2015001. Each sampled
block preserves pairing. Report 95% intervals for annualized arithmetic return
delta, Sharpe delta, MDD delta and Calmar delta. MDD remains descriptive; daily
observations are not treated as iid.

## Predeclared evidence gate

CASH_ZERO is primary. `PROMISING — FAMILY WORTH STUDYING` requires all:

1. SPY Sharpe, Sortino and Calmar deltas are positive.
2. SPY MDD improves by at least 5 percentage points.
3. SPY CAGR sacrifice is no more than 3 percentage points annually.
4. At least 4 of 6 fixed periods have positive Sharpe and Calmar deltas with
   MDD no worse, and CAGR sacrifice no more than 5 percentage points.
5. At least 8/14 ETFs improve Sharpe, MDD and Calmar; median Sharpe, MDD and
   Calmar deltas are positive; median CAGR sacrifice is no worse than 3 points.
6. A majority of unique CASH_ZERO test folds improve both Sharpe and MDD, and
   at least half improve Calmar. Expanding/rolling duplicates count once.
7. Under 2x commission plus 2x slippage, SPY still satisfies items 1–3 and at
   least 8/14 ETFs still improve Sharpe and Calmar.
8. SPY volatility management's improvement over B&H cannot be explained solely
   by cash interest: the CASH_ZERO result itself must satisfy items 1–7.

`STRONG RETROSPECTIVE EVIDENCE` additionally requires: at least 5/6 fixed
periods support; at least 10/14 ETFs improve Sharpe, MDD and Calmar; at least
two-thirds of unique test folds improve Sharpe, MDD and Calmar; 95% block
bootstrap lower bounds for Sharpe and Calmar deltas are above zero; SPY CAGR
sacrifice is no more than 2 points; and cost-stressed breadth remains at least
10/14.

Every other outcome is `NOT SUPPORTED`. CASH_RISK_FREE may describe cash drag
but cannot by itself upgrade a grade. PROMISING or STRONG sets `NEXT FAMILY =
VOLATILITY_MANAGED_EXPOSURE`; otherwise `NEXT FAMILY = NONE`. The benchmark is
never called production-ready and VOL_001 is not created in this study.

Any semantic implementation correction after results requires a new spec
version and SHA-256 with the reason recorded. Input files, this spec, canonical
production histories/audits/source, and candidate registry are hashed before
and after the study.
