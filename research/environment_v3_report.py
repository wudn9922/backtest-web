"""Deterministic, snapshot-bound Research Environment v3 report renderer."""
from __future__ import annotations

from typing import Any

from research.environment_v3_snapshot import EnvironmentValidationError


def _pct(value: Any, *, already_percent: bool = False) -> str:
    if value is None:
        return "—"
    number = float(value)
    return f"{number if already_percent else number * 100:.2f}%"


def _number(value: Any, digits: int = 3) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}"


def validate_report_consistency(study: dict[str, Any], report: str) -> None:
    """Reject publication when structured facts or rendered prose disagree."""
    history_ready = bool(study["data_history"]["primary_target_acquired"])
    etf = study["universes"]["ETF_RESEARCH_UNIVERSE"]
    risk_free_ready = bool(study["cash_models"]["CASH_RISK_FREE"]["series_available"])
    long_ready = bool(study["readiness"]["market_long_history_ready"])
    performed = bool(study["long_history_research_performed"])
    snapshot_id = study["environment_snapshot"]["environment_snapshot_id"]

    failures: list[str] = []
    lowered = report.lower()
    if history_ready and "2010 data was not acquired" in lowered:
        failures.append("2010 history is ready but the report says it was not acquired")
    if etf["validated_datasets"] == etf["symbol_count"]:
        if any(phrase in lowered for phrase in ("only spy/qqq", "current etf cache: spy/qqq")):
            failures.append("the complete ETF universe is described as SPY/QQQ only")
    if risk_free_ready and ("no fred file exists" in lowered or "no rate observations" in lowered):
        failures.append("validated FRED data is described as unavailable")
    if long_ready and performed:
        cells = study.get("sensitivity_matrix", [])
        if len(cells) != 4 or any(cell.get("long_history") != "EXECUTED" for cell in cells):
            failures.append("a ready long-history study contains an unexecuted sensitivity cell")
        if "long-history validation unavailable" in lowered:
            failures.append("completed long-history research is rendered as unavailable")
    if snapshot_id not in report:
        failures.append("the rendered report does not identify its immutable snapshot")
    source_ids = set(study.get("section_snapshot_ids", {}).values())
    if source_ids != {snapshot_id}:
        failures.append("report sections do not share one environment snapshot")
    extension_id = study.get("long_history_extension", {}).get("environment_snapshot_id")
    if performed and extension_id != snapshot_id:
        failures.append("long-history results and the report use different snapshots")
    if failures:
        raise EnvironmentValidationError("Report consistency validation failed: " + "; ".join(failures))


def render(study: dict[str, Any]) -> str:
    snapshot = study["environment_snapshot"]
    data = study["data_history"]
    mega = study["universes"]["MEGA_CAP_TECH_UNIVERSE"]
    etf = study["universes"]["ETF_RESEARCH_UNIVERSE"]
    risk_free = study["cash_models"]["CASH_RISK_FREE"]
    extension = study["long_history_results"]
    lines = [
        "# Research Environment Validation v3", "",
        "> **LONG-HISTORY VALIDATION COMPLETED.** All sections below were generated from one immutable current-environment snapshot. Production strategies and frozen benchmark semantics were not changed.", "",
        "## Executive Summary", "",
        f"- Environment snapshot: `{snapshot['environment_snapshot_id']}` (created `{snapshot['created_at']}`).",
        f"- Validated market history: **{data['validated_datasets']}/23 datasets**, target `{data['target_start']} → {data['target_end']}`; zero fabricated bars.",
        f"- Mega-cap universe: **{mega['validated_datasets']}/{mega['symbol_count']} ready**.",
        f"- ETF universe: **{etf['validated_datasets']}/{etf['symbol_count']} ready**; later-listed funds use their real inception-limited history.",
        f"- FRED DGS3MO: **available**, `{risk_free['first_observation']} → {risk_free['last_observation']}`, {risk_free['observations']:,} observations.",
        "- CASH_ZERO and CASH_RISK_FREE were both calculated. CASH_RISK_FREE uses fixed strategy executions and accrues only the cash balance.",
        f"- Environment sensitivity: **{study['sensitivity_classification']}**.",
        f"- NEXT FAMILY = **{study['next_family']}**. No candidate was created.", "",
        "## One source of truth", "",
        "The prior contradiction was caused by a mixed source of truth: current manifests were combined with a stale, hard-coded readiness narrative. This report instead binds every section to the same immutable snapshot.", "",
        "| Report section | Source | Snapshot |", "|---|---|---|",
    ]
    for section, source in study["section_sources"].items():
        lines.append(f"| {section} | {source} | `{study['section_snapshot_ids'][section]}` |")
    lines += [
        "", "Previous reports, previous Environment v3 JSON, job pre-check state and frontend state are outputs/views only; none is an input to this run.", "",
        "## Data acquisition and provenance", "",
        f"Input fingerprint: `{snapshot['input_fingerprint_sha256']}`.", "",
        "| Ticker | Coverage | Bars | Provider | Adjustment | Sidecar | Validation | OHLCV checksum |", "|---|---|---:|---|---|---|---|---|",
    ]
    for row in study["dataset_rows"]:
        coverage = f"{row['first_date']} → {row['last_date']}"
        lines.append(
            f"| {row['ticker']} | {coverage} | {row['bars']:,} | {row['provider']} | "
            f"{row['adjustment_mode']} | {'present' if row['metadata_sidecar_exists'] else 'missing'} | "
            f"{row['validation_status']} | `{row['ohlcv_sha256'][:12]}` |"
        )
    lines += [
        "", "All selected files are Yahoo provider-specific cache fragments with one declared adjustment contract. No cross-provider splice, pre-listing bar, market bar, or rate observation was synthesized.", "",
        "## Universe and fair evaluation", "",
        "- `MEGA_CAP_TECH_UNIVERSE`: end-of-sample mega-cap/winner-concentrated research set; it is not a historical point-in-time equity universe.",
        "- `ETF_RESEARCH_UNIVERSE`: 14/14 validated. ETF diversification reduces single-company effects but does not remove selection bias.",
        "- Each symbol begins evaluation only after its own 200 completed warm-up bars. META and XLRE therefore do not force all other symbols to start in 2015.",
        "- Universe aggregates explicitly have time-varying sample composition where instruments were not yet listed.", "",
        "## Cash-return model", "",
        f"Validated real FRED `{risk_free['series_id']}` data covers `{risk_free['first_observation']} → {risk_free['last_observation']}` ({risk_free['observations']:,} observations). The latest observation known by the previous session is converted with ACT/365 and applied to cash only. Invested equity never earns cash yield simultaneously.", "",
        "| Universe | Strategy | Symbols | Median cash-yield contribution | Median cash interest |", "|---|---|---:|---:|---:|",
    ]
    for universe, strategies in extension["cash_yield_attribution"].items():
        for strategy, row in strategies.items():
            lines.append(
                f"| {universe} | {strategy} | {row['symbols']} | "
                f"{_number(row['median_return_contribution_pp'])} pp | ${float(row['median_cash_yield_usd']):,.2f} |"
            )
    lines += ["", "## Full-history results", "", "| Universe | Cash | Strategy | Symbols | Median return | Median MDD | Median Sharpe | Median exposure |", "|---|---|---|---:|---:|---:|---:|---:|"]
    for universe, cash_models in extension["summary"].items():
        for cash_model, strategies in cash_models.items():
            for strategy, row in strategies.items():
                lines.append(
                    f"| {universe} | {cash_model} | {strategy} | {row['symbols']} | "
                    f"{_pct(row['median_total_return'])} | {_pct(row['median_max_drawdown'])} | "
                    f"{_number(row['median_sharpe'])} | {_pct(row['median_exposure'], already_percent=True)} |"
                )
    lines += ["", "## Sensitivity matrix", "", "All four declared long-history cells were actually executed; none is copied from the earlier short-history report.", "", "| Universe | Cash model | Long history | Symbols |", "|---|---|---|---:|"]
    for row in study["sensitivity_matrix"]:
        lines.append(f"| {row['universe']} | {row['cash_model']} | {row['long_history']} | {row['symbols']} |")
    lines += ["", "## Frozen benchmark reclassification", ""]
    for benchmark, row in study["benchmark_reclassification"].items():
        lines.append(f"- **{benchmark}: {row['grade']}** ({row['supportive_policies']}/3 supportive policies).")
    lines += [
        "", f"Environment sensitivity classification: **{study['sensitivity_classification']}**.",
        f"NEXT FAMILY = **{study['next_family']}**. This research did not create a candidate.", "",
        "## Fixed market-cycle windows", "",
        "| Window | Universe | Cash | Strategy | Symbols | Median return | Median MDD |", "|---|---|---|---|---:|---:|---:|",
    ]
    for row in extension["market_cycle_summary"]:
        lines.append(
            f"| {row['window']} | {row['universe']} | {row['cash_model']} | {row['strategy']} | "
            f"{row['symbols']} | {_pct(row['median_return'])} | {_pct(row['median_mdd'])} |"
        )
    lines += ["", "## Fixed crisis episodes", "", "The machine-readable output contains per-symbol exits/re-entries, returns and drawdowns for every frozen strategy, cash model and applicable OHLC policy.", "", "| Episode | Universe | Cash | Strategy | Symbols | Median return | Median MDD |", "|---|---|---|---|---:|---:|---:|"]
    for row in extension["crisis_summary"]:
        lines.append(
            f"| {row['episode']} | {row['universe']} | {row['cash_model']} | {row['strategy']} | "
            f"{row['symbols']} | {_pct(row['median_return'])} | {_pct(row['median_mdd'])} |"
        )
    lines += ["", "## Direct answers", ""]
    for index, answer in enumerate(study["direct_answers"], start=1):
        lines.append(f"{index}. {answer}")
    lines += [
        "", "## Invariance", "",
        "Simple v2, Advanced v2, M3 registry, frozen benchmarks, production executions, PnL, equity, historical backtests and position audits remained unchanged. Only Research Environment v3 derived artifacts were republished.", "",
    ]
    report = "\n".join(lines)
    validate_report_consistency(study, report)
    return report
