# Advanced v2 ablation research

This directory is deliberately outside `backend/app`. No API or production
strategy imports it. Parameters and costs never vary. `strategy.py` is a gated
research copy, not a replacement for `AdvancedMABreakout`.

Run from the repository root with the backend virtual environment:

```powershell
backend\.venv\Scripts\python.exe -B -m pytest research/tests -q -p no:cacheprovider
backend\.venv\Scripts\python.exe -B -m research.run_ablation
backend\.venv\Scripts\python.exe -B -m research.report
```

The research command prints machine-readable JSON to stdout. The report command
reads `data/advanced-v2-ablation.json` and prints Markdown. Neither command writes
the database, cache, audits, production files, or artifacts; reviewed output is
saved separately. SQLite is opened with `mode=ro`.

## Dependency semantics

- Volume off bypasses only its gate; Day1 close/volume remain observed and Day2
  confirmation can still run. This is a declared research intervention.
- Day2 off removes its gate; volume remains independent.
- MA Break off disables pre-First-TP half-risk and Break Protection/reset. It
  does not remove the MA component of the separately enabled protective stop.
- First TP family off disables the First TP regime, protective stop, and both
  extreme modules. Pre-TP MA risk remains active throughout.
- The bridge First TP step enables the one-time half sale and regime switch;
  until the next step adds Protective, there is no post-TP protective stop.
- Protective off does not reactivate the old MA risk loop after First TP.
  Remaining shares may survive until end-of-study liquidation. Report terminal
  closures explicitly; do not interpret this as a deployable alternative.
- Bias/ATR remain independent; disabling either removes that threshold/edge,
  not its numerical parameter. Both false removes all extreme sales.
- CORE is Entry Zone v2 plus end-of-study exit only. It is not Simple, and it
  is not a new production strategy.

## Evidence and safety

Canonical Simple and Advanced are read by fixed IDs. Both must reproduce
executions, net PnL, equity and metrics with the current production engine.
Research ALL-ON must also reproduce them. Old Simple UTC-offset strings and
entry-zone audit metadata differ in presentation only; no saved records change.
Sub-nanodollar historical gross-reporting floating-point differences are tested
separately from exact net/equity parity.

Matched-entry runs force the original entry day, actual price and Q0, simulate
one lifecycle only, and never re-enter. Their lifecycles can overlap and cannot
be summed into a feasible portfolio return. Simple episode controls use the
Simple entry/Q0, not the smaller quantity of an actual Advanced trade.

Ranking is descriptive for this sample: fewer than five changed anchors or
a one-position portfolio with over half changed lifecycles terminally closed
is labelled sample/horizon-limited. Negligible requires less than 1 pp return,
1 pp MDD and $1,000 aggregate anchored effect. Consistent signs in return, MDD
and anchored PnL yield adds-value/drag; mixed signs are trade-offs. This is not
a statistical significance test or an optimization objective.
# Additional fixed-parameter policy and First TP studies

`python -B -m research.run_policy_family A` and `B` print offline JSON to stdout.
`python -B -m research.policy_family_report A` and `B` render the saved JSON as Markdown to stdout.
They never call providers, persist a backtest, rebuild audits, or write the database.

`research/ambiguity.py` classifies OHLC identifiability independently of engine flags. Opening events,
closing constraints and the v2 no-chase entry zone are distinguished. Existing three policy implementations
are replayed unchanged; this is not a newly defined tick-path engine. Differences on identifiable days
are reported separately. Exact policy-invariant matched cohorts are also provided.

First TP decomposition introduces only `Modules.first_tp_partial` (default true). Signal and downstream
dependencies remain explicit. The 8 fixed boolean P/S/E cells measure module interactions, not parameter
optimization. Protective-off never silently restores the MA half-stop regime; end-of-study censoring is
therefore a material limitation. The two requested protective-off names are explicit aliases.

Both saved artifacts are regression-tested against fresh runs, ignoring runtime only. Anchored outputs
retain canonical position IDs. The original ablation reports and all canonical historical records stay intact.

## First TP structural robustness (research only)

The five fixed A/B/C/D/E structures live in `structural_study.py`. Only the
explicit D checkpoint uses 25% current quantity; no other partial ratio is
accepted. The default research implementation still matches production's 50%.
This is not registered as an API strategy and never changes strategy parameters.

`structural_data.py --acquire-network` uses the existing ProviderChain and cache
infrastructure for the eleven specified symbols. It does not overwrite existing
cached files. Reviewed acquisition output is frozen in
`data/first-tp-structural-inputs.json`; later numerical runs validate file/content
hashes and do not access the network. Yahoo's legacy split-adjustment label is
distinguished from its actual adjusted-close OHLC contract. Unverified native
Stooq adjustment is excluded instead of mixed with the Yahoo baseline.

```powershell
backend\.venv\Scripts\python.exe -B -m research.run_structural
backend\.venv\Scripts\python.exe -B -m research.structural_report
backend\.venv\Scripts\python.exe -B -m pytest research/tests -q -p no:cacheprovider
```

These commands print JSON/Markdown to stdout. The reviewed artifacts are
`data/first-tp-structural-robustness.json` and
`reports/first-tp-structural-robustness.md`.

The 40-session study treats entry day as day zero. Natural exits are absorbing
cash states; otherwise remaining shares are sold at the 40th subsequent session
close with normal costs. All entries without that full evaluation horizon are
excluded from headline estimates, irrespective of their earlier exit outcome.
It is an independent one-position experiment, not portfolio performance.

Tests cover all-symbol/all-policy production parity, integer quarter sales,
unchanged MA half sales, fixed anchors, minimum-position rules, no future-data
dependence, censor exclusions, all saved numerical results, report reproduction,
and immutable production/canonical/history/audit data.

## Simple v2 strategy viability gate

`research.viability_*` is an isolated benchmark and evidence layer. It freezes
production Simple v2 and Advanced v2, adds one costed Buy & Hold benchmark and
one Entry-Zone-v2 hold benchmark, and runs fixed full-period, subperiod,
retrospective walk-forward, ambiguity, cost, concentration and tail-risk
diagnostics. It does not register a strategy or call a provider.

The viability/ambiguity/train gates live in `viability_design.py` so their
thresholds exist before result computation. Signal forward-return lifecycles may
overlap and are never represented as portfolio returns. Statistical intervals
resample ticker and chronological half-year blocks; no ticker × period × policy
cell is treated as an iid observation.

```powershell
backend\.venv\Scripts\python.exe -B -m research.run_viability --write --progress
backend\.venv\Scripts\python.exe -B -m pytest research/tests/test_viability.py -q -p no:cacheprovider
```

The command produces only the requested `simple-v2-*` research artifacts. The
SQLite history, position audits, Parquet caches and `backend/app` source remain
read-only and their before/after hashes are embedded in the report.
