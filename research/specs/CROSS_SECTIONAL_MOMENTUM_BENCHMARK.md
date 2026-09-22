# XSMOM_12_1_TOP3 — frozen benchmark specification v2

Version 2 correction: report provenance extraction must obtain provider and
adjustment_mode from the selected validated variant, not absent top-level
manifest fields. Version 1 rendered null provenance labels; calculations
already selected Yahoo adjusted_for_splits correctly. No ranking, allocation,
execution, accounting, cost, evaluation or gate rule changes. Preserve v1 hash
9d2a25fac583bfc4f09a52ee3f91b2158277269370f3e21c0f71619e0064fb35 and results
for exact numeric comparison. This correction is reporting-only.

Registered before any benchmark result. Research benchmark only; no candidate registration.

Universe: SPY QQQ IWM DIA XLK XLF XLE XLV XLI XLP XLY XLU XLB XLRE.
Use the validated Environment v3 snapshot, Yahoo adjusted_for_splits OHLC,
2010-01-01 through 2026-09-01. No downloads. This is a fixed modern ETF list,
not a survivorship-free universe; price returns omit dividend cash flows.

At the last completed SPY trading session of each calendar month t, an ETF is
eligible only if it has observations on the last 253 consecutive SPY sessions
including t. Score = Close[t-21] / Close[t-252] - 1. Rank descending, ties by
alphabetical ticker. Select top min(3, eligible count). One or two eligible
ETFs receive equal weights; zero means no rebalance and a readiness error.
Minimum readiness for the primary study is three eligible ETFs. XLRE joins
only after its own complete lookback. Never backfill missing prices.

All signals execute at the next SPY trading session OPEN. The common initial
evaluation day is the next open after the first month-end with readiness.
SPY and QQQ buy-and-hold enter this same day. Equal-weight universe uses the
same eligible list and same monthly next-open rebalance schedule.

Every rebalance targets equal weights, including retained holdings. Compute
pre-trade open equity, divide by selected count, and floor whole-share targets
after a uniform buy-cost reserve of (1+slippage)*(1+commission). Sell excess
first, then buy deficits in alphabetical order subject to cash affordability.
No leverage, shorting or fractional shares. Do not sell/buy unchanged shares.
Final liquidation is at the final study session CLOSE, with normal costs.
Daily marking is at close. Missing held-asset bars abort instead of filling.
All execution is at known open/terminal close: all three OHLC policies are
identical, with no invented intrabar differences.

Initial capital and percent costs are loaded and frozen from canonical v2
request before results. Stress cases: baseline, 2x commission, 2x slippage,
2x both. Additionally zero-cost run for gross-before-cost comparison, not
parameter selection. Cash models ZERO and validated FRED DGS3MO previous-
known observation ACT/365 effective compounding on prior-session cash only.
Interest is available for subsequent rebalances; never paid on ETF value.

Metrics: daily return uses initial capital as first denominator; CAGR calendar
days/365.25; Sharpe and Sortino use zero hurdle and sqrt(252); downside RMS
includes zero nonnegative returns; MDD includes initial equity; Calmar=CAGR/
abs(MDD); exposure=mean close invested/equity; turnover=sum gross traded value/
mean equity (two-sided). Trade holding duration is FIFO whole-share weighted
sessions. Report fees/slippage separately; no double deduction.

Calendar/cycle/crisis analysis slices continuous equity, including prior close
as denominator. Use Environment v3 fixed cycles/crisis definitions unchanged.
Retrospective walk-forward: six-month tests after two years from common
evaluation start, advancing six months; expanding and trailing two-year train
windows. No fitting/gate/candidate selection. Test folds start fresh cash and
use the most recent completed month-end ranking known before test open, then
monthly schedule. Both designs have identical tests by construction. Final
short fold retained and flagged. Training metrics descriptive only.

Uncertainty: paired monthly log-return differences, circular 12-month block
bootstrap, 2000 draws, fixed seed 1201252; annualized mean difference and 95%
interval, median realized calendar-period return delta. Months are not iid.

Concentration: additive dollar mark-to-market contribution by ETF and year,
positive-profit denominator and net denominator separately; one exclusion run
removes ETF with largest baseline RS dollar contribution, explicitly post-hoc
sensitivity only, same evaluation period. Annual weights include QQQ+XLK.

Predeclared family gate, CASH_ZERO primary: PROMISING requires positive full
return and Sharpe delta against BOTH SPY and equal-weight, MDD no more than
5 percentage points worse than either, majority positive return deltas in
fixed cycle windows and test folds against both, and positive return deltas
under doubled both costs. STRONG additionally requires improved MDD against
both, >=2/3 positive cycle/fold breadth, bootstrap lower bounds >0 against
both, and positive excess return after best-ETF removal against both original
comparators. Otherwise NOT SUPPORTED. CASH_RISK_FREE cannot alone upgrade.
Only PROMISING/STRONG permits NEXT FAMILY=CROSS_SECTIONAL_MOMENTUM; otherwise
NONE. No candidate is created. No claim of true OOS or production readiness.

Any implementation bug requiring semantic correction requires a new version
and hash with reason before corrected results. Spec and input hashes are
checked at completion. Production histories, audits, source and registry are
fingerprinted before/after.
