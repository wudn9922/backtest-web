from __future__ import annotations

import hashlib
import json

from fastapi.testclient import TestClient

from app.main import app


def test_framework_endpoint_is_read_only_and_returns_frozen_registry(monkeypatch, tmp_path):
    catalog = {
        "schema_version": 2,
        "no_new_candidate_created": True,
        "registry": {"append_only": True, "candidates": [
            {"candidate_id": "SIMPLE_V2", "research_status": "REJECTED"},
            {"candidate_id": "ADVANCED_V2", "research_status": "REJECTED"},
            {"candidate_id": "M3", "research_status": "REJECTED", "production_selector_value": None},
        ]},
    }
    (tmp_path / "research-framework-v2-catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setenv("RESEARCH_DATA_DIR", str(tmp_path))
    response = TestClient(app).get("/api/research/framework")
    assert response.status_code == 200
    assert response.json() == catalog
    assert "no-store" in response.headers["cache-control"]
    assert TestClient(app).post("/api/research/framework").status_code == 405


def test_xsmom_summary_and_report_do_not_register_candidate(monkeypatch, tmp_path):
    data, reports = tmp_path / "data", tmp_path / "reports"
    data.mkdir(); reports.mkdir()
    registry = {"candidates": [{"candidate_id": "SIMPLE_V2"}]}
    (data / "research-framework-v2-catalog.json").write_text(json.dumps({"registry": registry}))
    (data / "research-history-index.json").write_text('{"studies": []}')
    study = {k: {} for k in ("registration", "cash_models")}
    study.update(study="XSMOM_12_1_TOP3",grade="NOT SUPPORTED",next_family="NONE",
                 evaluation_start="2011-02-01",evaluation_end="2026-09-01")
    (data / "cross-sectional-momentum-benchmark.json").write_text(json.dumps(study))
    (reports / "cross-sectional-momentum-benchmark.md").write_text("# frozen benchmark")
    monkeypatch.setenv("RESEARCH_DATA_DIR",str(data)); monkeypatch.setenv("RESEARCH_REPORTS_DIR",str(reports))
    client=TestClient(app)
    result=client.get("/api/research/framework")
    assert result.json()["registry"]==registry
    assert result.json()["xsmom_benchmark"]==study
    assert "no-store" in result.headers["cache-control"]
    assert client.get("/api/research/reports/cross-sectional-momentum-benchmark").status_code==200
    assert client.get("/api/research/reports/cross-sectional-momentum-benchmark-secrets").status_code==404


def test_volatility_benchmark_summary_and_report_do_not_register_candidate(monkeypatch, tmp_path):
    data, reports = tmp_path / "data", tmp_path / "reports"
    data.mkdir(); reports.mkdir()
    registry = {"candidates": [{"candidate_id": "SIMPLE_V2"}, {"candidate_id": "ADVANCED_V2"}, {"candidate_id": "M3"}]}
    (data / "research-framework-v2-catalog.json").write_text(json.dumps({"registry": registry}))
    (data / "research-history-index.json").write_text('{"studies": []}')
    study = {
        "study": "VOL_MANAGED_20D_15PCT_CAP1", "title": "20 日波動度管理曝險",
        "evidence_grade": "NOT SUPPORTED", "next_family": "NONE", "registration": {},
        "evaluation": {}, "parameters": {}, "primary_spy": {}, "robustness_summary": {},
        "crisis_analysis": {}, "cost_stress_spy": {}, "cash_decomposition": {}, "walk_forward_summary": {},
    }
    (data / "volatility-managed-benchmark.json").write_text(json.dumps(study))
    (reports / "volatility-managed-benchmark.md").write_text("# frozen benchmark")
    monkeypatch.setenv("RESEARCH_DATA_DIR", str(data)); monkeypatch.setenv("RESEARCH_REPORTS_DIR", str(reports))
    client = TestClient(app)
    response = client.get("/api/research/framework")
    assert response.status_code == 200
    assert response.json()["volatility_managed_benchmark"] == study
    assert response.json()["registry"] == registry
    assert "no-store" in response.headers["cache-control"]
    assert client.get("/api/research/reports/volatility-managed-benchmark").status_code == 200
    assert client.get("/api/research/reports/volatility-managed-secret").status_code == 404


def test_report_endpoint_only_serves_whitelisted_history(monkeypatch, tmp_path):
    data, reports = tmp_path / "data", tmp_path / "reports"
    data.mkdir(); reports.mkdir()
    report = reports / "simple.md"
    report.write_text("# frozen", encoding="utf-8")
    history = {"studies": [{"report_id": "simple", "report_file": "simple.md", "report_sha256": hashlib.sha256(report.read_bytes()).hexdigest()}]}
    (data / "research-history-index.json").write_text(json.dumps(history), encoding="utf-8")
    monkeypatch.setenv("RESEARCH_DATA_DIR", str(data))
    monkeypatch.setenv("RESEARCH_REPORTS_DIR", str(reports))
    client = TestClient(app)
    assert client.get("/api/research/reports/simple").status_code == 200
    assert client.get("/api/research/reports/../secrets").status_code == 404
    assert client.get("/api/research/reports/not-indexed").status_code == 404


def test_catalog_keeps_only_frozen_rejected_candidates_with_environment_overlay(monkeypatch, tmp_path):
    catalog_fixture = {
        "schema_version": 2,
        "no_new_candidate_created": True,
        "registry": {"append_only": True, "candidates": [
            {"candidate_id": "SIMPLE_V2", "research_status": "REJECTED"},
            {"candidate_id": "ADVANCED_V2", "research_status": "REJECTED"},
            {"candidate_id": "M3", "research_status": "REJECTED", "production_selector_value": None},
        ]},
        "benchmark_viability": {"next_family": "NONE", "candidate_created": False},
        "history": {"studies": [
            {"report_id": "benchmark-viability"},
            {"report_id": "research-environment-v3"},
        ]},
    }
    environment_fixture = {
        "study": "RESEARCH_ENVIRONMENT_V3",
        "long_history_validation_status": "COMPLETED",
        "data_history": {},
        "universes": {
            "MEGA_CAP_TECH_UNIVERSE": {"validated_datasets": 11},
            "ETF_RESEARCH_UNIVERSE": {"validated_datasets": 14},
        },
        "cash_models": {},
        "data_manifest": {},
        "universe_manifest": {},
        "sensitivity_classification": {},
        "next_family": "NONE",
        "environment_snapshot": {"environment_snapshot_id": "env3-c0-fixture"},
        "readiness": {"candidate_created": False, "risk_free_ready": True},
    }
    (tmp_path / "research-framework-v2-catalog.json").write_text(json.dumps(catalog_fixture), encoding="utf-8")
    (tmp_path / "research-environment-v3.json").write_text(json.dumps(environment_fixture), encoding="utf-8")
    monkeypatch.setenv("RESEARCH_DATA_DIR", str(tmp_path))
    response = TestClient(app).get("/api/research/framework")
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    catalog = response.json()
    rows = catalog["registry"]["candidates"]
    assert [row["candidate_id"] for row in rows] == ["SIMPLE_V2", "ADVANCED_V2", "M3"]
    assert all(row["research_status"] == "REJECTED" for row in rows)
    assert next(row for row in rows if row["candidate_id"] == "M3")["production_selector_value"] is None
    assert catalog["benchmark_viability"]["next_family"] == "NONE"
    assert catalog["benchmark_viability"]["candidate_created"] is False
    assert {row["report_id"] for row in catalog["history"]["studies"]} >= {"benchmark-viability"}
    environment = catalog["research_environment"]
    assert environment["candidate_created"] is False
    assert environment["next_family"] == "NONE"
    assert environment["status"] == "COMPLETED"
    assert environment["universes"]["MEGA_CAP_TECH_UNIVERSE"]["validated_datasets"] == 11
    assert environment["universes"]["ETF_RESEARCH_UNIVERSE"]["validated_datasets"] == 14
    assert environment["readiness"]["risk_free_ready"] is True
    assert environment["environment_snapshot"]["environment_snapshot_id"] == "env3-c0-fixture"
    assert {row["report_id"] for row in catalog["history"]["studies"]} >= {"research-environment-v3"}


def test_current_environment_endpoint_returns_latest_snapshot_without_cache(monkeypatch, tmp_path):
    snapshot = {
        "long_history_validation_status": "COMPLETED",
        "readiness": {"research_validation_ready": True},
        "universes": {"ETF_RESEARCH_UNIVERSE": {"validated_datasets": 14}},
    }
    (tmp_path / "research-environment-v3.json").write_text(json.dumps(snapshot), encoding="utf-8")
    monkeypatch.setenv("RESEARCH_DATA_DIR", str(tmp_path))
    response = TestClient(app).get("/api/research/environment/current")
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    value = response.json()
    assert value == snapshot
    assert value["long_history_validation_status"] == "COMPLETED"
    assert value["readiness"]["research_validation_ready"] is True
    assert value["universes"]["ETF_RESEARCH_UNIVERSE"]["validated_datasets"] == 14
