from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

from research.cash_models import ResearchCashPortfolio, RiskFreeCashModel, ZeroCashModel
from research.environment_v3_design import ETF_RESEARCH_UNIVERSE, MEGA_CAP_TECH_UNIVERSE
from research.baseline import digest
from research.environment_v3_data import sha256_file
from research.environment_v3_report import render, validate_report_consistency
from research.environment_v3_snapshot import (
    EnvironmentValidationError,
    assert_snapshot_immutable,
    build_environment_snapshot,
    validate_risk_free_input,
)


ROOT = Path(__file__).resolve().parents[2]


def test_universes_are_predeclared_and_do_not_create_a_candidate():
    assert MEGA_CAP_TECH_UNIVERSE == ("NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "AVGO", "SPY", "QQQ")
    assert ETF_RESEARCH_UNIVERSE == ("SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB", "XLRE")
    registry = json.loads((ROOT / "data/research-candidate-registry.json").read_text(encoding="utf-8"))
    assert registry["candidate_count"] == 3
    assert [row["candidate_id"] for row in registry["candidates"]] == ["SIMPLE_V2", "ADVANCED_V2", "M3"]


def test_zero_cash_model_is_exactly_zero_and_never_changes_cash():
    model = ZeroCashModel()
    result = model.accrue(1234.56, pd.Timestamp("2025-01-03", tz="UTC"), pd.Timestamp("2025-01-06", tz="UTC"))
    assert result.calendar_days == 3
    assert result.interest == 0
    assert result.closing_cash == 1234.56


def test_risk_free_model_is_lag_safe_and_uses_act_365():
    series = pd.Series(
        [5.0, 99.0],
        index=pd.DatetimeIndex([pd.Timestamp("2025-01-02", tz="UTC"), pd.Timestamp("2025-01-04", tz="UTC")]),
    )
    model = RiskFreeCashModel(series)
    result = model.accrue(1000, pd.Timestamp("2025-01-02", tz="UTC"), pd.Timestamp("2025-01-03", tz="UTC"))
    expected = 1000 * ((1.05 ** (1 / 365)) - 1)
    assert result.annual_rate_pct == 5
    assert result.observation_date == "2025-01-02"
    assert result.interest == pytest.approx(expected)
    assert result.annual_rate_pct != 99


def test_cash_interest_applies_to_cash_balance_not_invested_market_value():
    series = pd.Series([5.0], index=pd.DatetimeIndex([pd.Timestamp("2025-01-02", tz="UTC")]))
    portfolio = ResearchCashPortfolio(1000, 0, 0, RiskFreeCashModel(series))
    portfolio.quantity = 10
    portfolio.accrue_before_open(pd.Timestamp("2025-01-02", tz="UTC"))
    result = portfolio.accrue_before_open(pd.Timestamp("2025-01-03", tz="UTC"))
    assert result.interest == pytest.approx(1000 * ((1.05 ** (1 / 365)) - 1))
    assert portfolio.cash == pytest.approx(1000 + result.interest)


def test_environment_outputs_are_truthful_reproducible_and_rendered():
    study = json.loads((ROOT / "data/research-environment-v3.json").read_text(encoding="utf-8"))
    data = json.loads((ROOT / "data/research-data-manifest-v3.json").read_text(encoding="utf-8"))
    universes = json.loads((ROOT / "data/research-universes.json").read_text(encoding="utf-8"))
    assert study["candidate_created"] is False
    assert study["optimization_performed"] is False
    assert study["benchmark_definitions_modified"] is False
    assert study["production_strategies_modified"] is False
    assert study["next_family"] == "NONE"
    assert study["long_history_research_performed"] is True
    assert study["readiness"]["research_validation_ready"] is True
    for artifact in study["methodology_fingerprints"].values():
        assert hashlib.sha256((ROOT / artifact["path"]).read_bytes()).hexdigest() == artifact["sha256"]
    assert data["fabricated_bars"] == 0
    assert universes["point_in_time_constituents_available"] is False
    assert universes["pooling_prohibited"] is True
    assert {row["ticker"] for row in data["datasets"]} == set(MEGA_CAP_TECH_UNIVERSE) | set(ETF_RESEARCH_UNIVERSE)
    assert hashlib.sha256((ROOT / study["data_manifest"]["path"]).read_bytes()).hexdigest() == study["data_manifest"]["sha256"]
    assert hashlib.sha256((ROOT / study["universe_manifest"]["path"]).read_bytes()).hexdigest() == study["universe_manifest"]["sha256"]
    assert render(study) == (ROOT / "reports/research-environment-v3.md").read_text(encoding="utf-8")
    assert study["cash_models"]["CASH_RISK_FREE"]["series_available"] is True
    assert study["risk_free_research_performed"] is True
    assert all(row["long_history"] == "EXECUTED" for row in study["sensitivity_matrix"])
    assert study["universes"]["ETF_RESEARCH_UNIVERSE"]["validated_datasets"] == 14
    assert all(row["metadata_sidecar_exists"] for row in study["dataset_rows"])


def test_environment_build_preserves_canonical_execution_and_audit_fingerprints():
    study = json.loads((ROOT / "data/research-environment-v3.json").read_text(encoding="utf-8"))
    immutable = study["immutability"]
    assert immutable["before"] == immutable["after"]
    assert immutable["executions_differences"] == 0
    assert immutable["pnl_differences"] == 0
    assert immutable["equity_differences"] == 0
    assert immutable["audits_differences"] == 0
    assert all(row["executions_differences"] == 0 and row["equity_differences"] == 0 for row in study["canonical_replay"].values())


def test_current_market_snapshot_ignores_previous_report_conclusions():
    snapshot = build_environment_snapshot(persist=False)
    assert snapshot["source_inventory"]["previous_report"].startswith("output only")
    assert snapshot["readiness"]["market_long_history_ready"] is True
    assert snapshot["coverage"]["datasets"] == 23
    assert snapshot["coverage"]["etf"]["validated_datasets"] == 14


def test_environment_snapshot_is_immutable():
    snapshot = build_environment_snapshot(persist=False)
    assert_snapshot_immutable(snapshot)
    changed = deepcopy(snapshot)
    changed["readiness"]["risk_free_ready"] = False
    with pytest.raises(EnvironmentValidationError, match="content changed"):
        assert_snapshot_immutable(changed)


def test_validated_risk_free_file_is_available_and_absent_is_unavailable(tmp_path):
    assert validate_risk_free_input(data_dir=tmp_path)["ready"] is False
    rates = tmp_path / "research-rates/fred/rates.parquet"
    rates.parent.mkdir(parents=True)
    series = pd.Series(
        [0.1, 4.8],
        index=pd.DatetimeIndex([pd.Timestamp("2010-01-04", tz="UTC"), pd.Timestamp("2026-09-01", tz="UTC")]),
        name="annual_yield_pct",
    )
    series.to_frame().to_parquet(rates)
    manifest = {
        "series_id": "DGS3MO", "provider": "FRED", "requested_start": "2010-01-01",
        "requested_end": "2026-09-01", "first_observation": "2010-01-04",
        "last_observation": "2026-09-01", "observations": 2,
        "cache_file": "research-rates/fred/rates.parquet", "cache_sha256": sha256_file(rates),
        "series_sha256": digest([
            {"date": "2010-01-04", "annual_yield_pct": 0.1},
            {"date": "2026-09-01", "annual_yield_pct": 4.8},
        ]),
        "fabricated_observations": 0,
    }
    (tmp_path / "risk-free-rate-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    validated = validate_risk_free_input(data_dir=tmp_path)
    assert validated["ready"] is True
    assert validated["observations"] == 2


def test_contradictory_report_is_rejected_for_ready_snapshot():
    study = json.loads((ROOT / "data/research-environment-v3.json").read_text(encoding="utf-8"))
    with pytest.raises(EnvironmentValidationError, match="2010 history"):
        validate_report_consistency(study, "2010 data was not acquired " + study["environment_snapshot"]["environment_snapshot_id"])
    with pytest.raises(EnvironmentValidationError, match="ETF universe"):
        validate_report_consistency(study, "Current ETF cache: SPY/QQQ only " + study["environment_snapshot"]["environment_snapshot_id"])
    with pytest.raises(EnvironmentValidationError, match="FRED"):
        validate_report_consistency(study, "No FRED file exists " + study["environment_snapshot"]["environment_snapshot_id"])
