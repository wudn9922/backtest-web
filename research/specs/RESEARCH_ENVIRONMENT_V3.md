# Research Environment Validation v3 — Frozen Methodology

Status: research infrastructure only. This document creates no strategy candidate and changes no production or benchmark semantics.

## Target history

- Primary request: 2010-01-01 through 2026-09-01.
- Optional archive request: 2005-01-01 through 2009-12-31 where a real instrument existed.
- Missing pre-listing bars are never synthesized.
- Different providers or adjustment contracts are never combined within a ticker dataset.

## Universes

- `MEGA_CAP_TECH_UNIVERSE`: NVDA, AAPL, MSFT, GOOGL, AMZN, META, TSLA, AMD, AVGO, SPY, QQQ.
- `ETF_RESEARCH_UNIVERSE`: SPY, QQQ, IWM, DIA, XLK, XLF, XLE, XLV, XLI, XLP, XLY, XLU, XLB, XLRE.
- Results are reported separately. Neither universe is historical point-in-time constituent data.

## Frozen comparators

- Costed Buy & Hold.
- Frozen SMA200: completed `Close(t)` versus `SMA200(t)` schedules action at the next trading-day open.
- Frozen Donchian 20/10: current-day entry and exit thresholds use only prior completed bars and retain all frozen Daily OHLC policy/gap semantics.
- Frozen Simple v2 and Advanced v2 may be reported; their strategy semantics cannot change.

## Fair evaluation start

For every comparison group: DATA START → 200 completed warm-up bars → common EVALUATION START. Buy & Hold begins at the identical evaluation start and cannot receive warm-up-period return.

## Cash models

- `CASH_ZERO`: uninvested cash earns zero.
- `CASH_RISK_FREE`: use only a real, checksummed FRED DGS3MO series. An observation dated t cannot be used on t. The latest observation dated on or before the prior research session applies to the following interval. Accrual is cash-only and uses `(1 + annual_yield/100)^(calendar_days/365) - 1`.
- No rate series means no risk-free result.

## Descriptive time analysis

Fixed market-cycle windows: 2010–2012, 2013–2015, 2016–2018, 2019–2021, 2022–2023, 2024–2026. Calendar-year, rolling 6M/12M, and retrospective walk-forward tables do not optimize parameters.

Fixed crisis descriptions: 2011 correction, 2015–2016 correction, 2018 Q4, 2020 crash, and 2022 bear market. Regime labels are descriptive only and never enter trading decisions.

## Reclassification gate

SMA200 and Donchian may be reclassified only after real long-history and ETF-universe inputs exist with compatible provenance. Allowed grades remain `NOT SUPPORTED`, `PROMISING — FAMILY WORTH STUDYING`, and `STRONG RETROSPECTIVE EVIDENCE`. Adding cash yield alone cannot automatically upgrade a grade.

If required history or rates are unavailable, output `LONG-HISTORY VALIDATION UNAVAILABLE`; do not infer missing cells, fabricate data, or create a candidate.

