from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import uuid
from datetime import date, timedelta
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.backtest.data_preparation import prepare_daily_market_data
from app.backtest.models import BacktestError, BacktestRequest, StrategyName
from app.data.base import DataProvider
from app.ma_breakout_analytics.engine import (
    ANALYTICS_REVISION, SPEC_REVISION, SPEC_REVISION_NUMBER,
    AnalyticsConfig, analyze_study, spec_sha256,
)
from app.ma_breakout_analytics.repository import AnalyticsRepository


router = APIRouter(prefix="/api/ma-analytics/studies", tags=["ma-breakout-analytics-v1"])


class AnalyticsStudyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str = Field(min_length=1, max_length=24)
    selected_ma: int = Field(24, ge=2, le=500)
    nearby_range: int = Field(5, ge=0, le=100)
    step: int = Field(1, ge=1, le=20)
    start_date: date
    end_date: date
    direction_mode: str = "LONG_SHORT_SPLIT"
    entanglement_mode: str = "ALL"

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9.^=\-]{1,24}", value):
            raise ValueError("ticker contains unsupported characters")
        return value

    @model_validator(mode="after")
    def validate_request(self) -> "AnalyticsStudyRequest":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        if self.end_date - self.start_date > timedelta(days=365 * 20 + 5):
            raise ValueError("date range cannot exceed 20 years")
        if self.direction_mode not in {"LONG_ONLY", "SHORT_ONLY", "LONG_SHORT_SPLIT"}:
            raise ValueError("direction_mode is invalid")
        if self.entanglement_mode not in {"ALL", "EXCLUDE_ENTANGLED", "ONLY_ENTANGLED", "SPLIT_ENTANGLED_CLEAN"}:
            raise ValueError("entanglement_mode is invalid")
        self.periods()
        return self

    def periods(self) -> list[int]:
        config = AnalyticsConfig(
            ticker=self.ticker, selected_ma=self.selected_ma, nearby_range=self.nearby_range,
            step=self.step, start_date=self.start_date, end_date=self.end_date,
            direction_mode=self.direction_mode, entanglement_mode=self.entanglement_mode,
        )
        return config.periods()

    def config(self) -> AnalyticsConfig:
        return AnalyticsConfig(
            ticker=self.ticker, selected_ma=self.selected_ma, nearby_range=self.nearby_range,
            step=self.step, start_date=self.start_date, end_date=self.end_date,
            direction_mode=self.direction_mode, entanglement_mode=self.entanglement_mode,
        )


def repository(request: Request) -> AnalyticsRepository:
    return request.app.state.ma_breakout_analytics_repository


def provider(request: Request) -> DataProvider:
    return request.app.state.provider


def _fingerprint(frame: pd.DataFrame) -> str:
    canonical = frame[["open", "high", "low", "close", "volume"]].copy().sort_index()
    return hashlib.sha256(pd.util.hash_pandas_object(canonical, index=True).to_numpy().tobytes()).hexdigest()


def _provider_request(payload: AnalyticsStudyRequest) -> BacktestRequest:
    # This request only invokes the project's canonical daily provider/warm-up
    # pipeline. No legacy strategy engine or portfolio is run.
    return BacktestRequest(
        ticker=payload.ticker, strategy=StrategyName.SIMPLE,
        start_date=payload.start_date, end_date=payload.end_date,
        initial_capital=100_000.0, position_size_pct=100.0,
        execution_model="daily_conservative", execution_policy="ohlc_heuristic",
        market_data_provider="auto", commission_pct=0.05, slippage_pct=0.02,
        force_close_at_end=True,
        parameters={"ma_type": "sma", "ma_period": max(payload.periods()),
                    "breakout_trigger_pct": 1.0, "entry_stop_pct": 1.5,
                    "exit_below_ma_pct": 1.5, "atr_period": 14},
    )


def _study_or_404(repo: AnalyticsRepository, study_id: str) -> dict[str, Any]:
    item = repo.get_study(study_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "MA_ANALYTICS_STUDY_NOT_FOUND", "message": "研究不存在。"})
    return item


def _require_completed(item: dict[str, Any]) -> dict[str, Any]:
    if item["status"] == "RUNNING":
        raise HTTPException(status_code=409, detail={"code": "MA_ANALYTICS_STUDY_NOT_COMPLETE", "status": "RUNNING", "message": "研究仍在執行。"})
    if item["status"] == "FAILED":
        raise HTTPException(status_code=409, detail={"code": "MA_ANALYTICS_STUDY_FAILED", "status": "FAILED",
                                                      "error_code": item.get("error_code"),
                                                      "message": item.get("error_message") or "研究無法完成。"})
    return item.get("result") or {}


@router.get("")
def list_studies(repo: AnalyticsRepository = Depends(repository)):
    rows = repo.list_studies()
    return [{k: v for k, v in row.items() if k != "result"} for row in rows]


@router.post("", status_code=201)
def create_study(payload: AnalyticsStudyRequest, repo: AnalyticsRepository = Depends(repository),
                 data_provider: DataProvider = Depends(provider)):
    study_id = str(uuid.uuid4())
    config = payload.config()
    config_json = config.as_dict()
    frozen_hash = spec_sha256()
    config_hash = hashlib.sha256(json.dumps(config_json, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    repo.create_running(study_id=study_id, config=config_json, analytics_revision=ANALYTICS_REVISION,
                        spec_revision=SPEC_REVISION, spec_revision_number=SPEC_REVISION_NUMBER,
                        spec_hash=frozen_hash, config_hash=config_hash)
    try:
        prepared = prepare_daily_market_data(
            _provider_request(payload), data_provider,
            evaluation_start=payload.start_date, evaluation_end=payload.end_date,
            ma_period=max(payload.periods()),
        )
        fingerprint = _fingerprint(prepared.daily)
        result = analyze_study(prepared.daily, config, provider=prepared.provider,
                               data_fingerprint=fingerprint, study_id=study_id)
        result["data_provenance"] = {
            "provider": prepared.provider, "provider_display_name": prepared.metadata.get("provider_display_name", prepared.provider),
            "adjustment_mode": prepared.metadata.get("adjustment_mode"),
            "data_source": prepared.metadata.get("data_source"), "warnings": prepared.warnings,
            "data_start": prepared.daily.index[0].date().isoformat(),
            "data_end": prepared.daily.index[-1].date().isoformat(),
            "bars_including_warmup": len(prepared.daily), "fingerprint": fingerprint,
        }
        repo.complete(study_id, result)
        return {k: v for k, v in result.items() if k not in {"events", "target_outcomes", "target_session_audit", "failure_outcomes", "aggregates", "charts"}}
    except BacktestError as exc:
        repo.fail(study_id, exc.code, exc.message)
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message, **exc.details}) from exc
    except ValueError as exc:
        repo.fail(study_id, "MA_ANALYTICS_INVALID_DATA", str(exc))
        raise HTTPException(status_code=422, detail={"code": "MA_ANALYTICS_INVALID_DATA", "message": str(exc)}) from exc
    except Exception as exc:
        repo.fail(study_id, "MA_ANALYTICS_STUDY_FAILED", "MA_BREAKOUT_ANALYTICS_V1 study failed.")
        raise HTTPException(status_code=500, detail={"code": "MA_ANALYTICS_STUDY_FAILED", "message": "研究無法完成。"}) from exc


@router.get("/{study_id}")
def get_study(study_id: str, repo: AnalyticsRepository = Depends(repository)):
    item = _study_or_404(repo, study_id)
    if item["status"] != "COMPLETED":
        return {k: v for k, v in item.items() if k != "result"}
    return {k: v for k, v in item.items() if k != "result"} | {
        "summary": item["result"].get("period_summary"),
        "periods": item["result"].get("periods"),
    }


@router.get("/{study_id}/summary")
def get_summary(study_id: str, repo: AnalyticsRepository = Depends(repository)):
    item = _study_or_404(repo, study_id)
    result = _require_completed(item)
    return {"study_id": study_id, "status": item["status"], "config": item["config"],
            "spec_revision": item["spec_revision"], "spec_revision_number": item["spec_revision_number"],
            "spec_hash": item["spec_hash"], "config_hash": item["config_hash"],
            "data_fingerprint": item["data_fingerprint"], "data_provenance": result.get("data_provenance"),
            "periods": result.get("periods"), "period_summary": result.get("period_summary"),
            "aggregates": result.get("aggregates"), "reference_entry_label": result.get("reference_entry_label")}


@router.get("/{study_id}/events")
def get_events(study_id: str, period: int | None = None, direction: str | None = None,
               cohort: str | None = None, repo: AnalyticsRepository = Depends(repository)):
    item = _study_or_404(repo, study_id)
    result = _require_completed(item)
    rows = result.get("events", [])
    if period is not None: rows = [x for x in rows if x["sma_period"] == period]
    if direction is not None: rows = [x for x in rows if x["direction"] == direction.upper()]
    if cohort is not None: rows = [x for x in rows if x["entanglement_cohort"] == cohort.upper()]
    return {"study_id": study_id, "count": len(rows), "events": rows}


@router.get("/{study_id}/events/{event_id:path}")
def get_event(study_id: str, event_id: str, repo: AnalyticsRepository = Depends(repository)):
    item = _study_or_404(repo, study_id)
    result = _require_completed(item)
    event = next((x for x in result.get("events", []) if x["event_id"] == event_id), None)
    if event is None:
        raise HTTPException(status_code=404, detail={"code": "MA_ANALYTICS_EVENT_NOT_FOUND", "message": "事件不存在。"})
    return {"event": event,
            "targets": [x for x in result.get("target_outcomes", []) if x["event_id"] == event_id],
            "target_session_audit": [x for x in result.get("target_session_audit", []) if x["event_id"] == event_id],
            "failure_path": next((x for x in result.get("failure_outcomes", []) if x["event_id"] == event_id), None)}


@router.get("/{study_id}/targets")
def get_targets(study_id: str, period: int | None = None, origin: str | None = None,
                repo: AnalyticsRepository = Depends(repository)):
    item = _study_or_404(repo, study_id)
    result = _require_completed(item)
    period_by_id = {x["event_id"]: x["sma_period"] for x in result.get("events", [])}
    rows = result.get("target_outcomes", [])
    if period is not None: rows = [x for x in rows if period_by_id.get(x["event_id"]) == period]
    if origin is not None: rows = [x for x in rows if x["observation_origin"] == origin.upper()]
    return {"study_id": study_id, "count": len(rows), "target_outcomes": rows}


@router.get("/{study_id}/failure-paths")
def get_failure_paths(study_id: str, period: int | None = None, repo: AnalyticsRepository = Depends(repository)):
    item = _study_or_404(repo, study_id)
    result = _require_completed(item)
    rows = result.get("failure_outcomes", [])
    if period is not None: rows = [x for x in rows if x.get("sma_period") == period]
    return {"study_id": study_id, "count": len(rows), "failure_outcomes": rows}


@router.get("/{study_id}/aggregates/{aggregate_id}/members")
def get_aggregate_members(study_id: str, aggregate_id: str, repo: AnalyticsRepository = Depends(repository)):
    item = _study_or_404(repo, study_id)
    _require_completed(item)
    rows = repo.members(study_id, aggregate_id)
    if not rows:
        raise HTTPException(status_code=404, detail={"code": "MA_ANALYTICS_AGGREGATE_NOT_FOUND", "message": "統計群組不存在或沒有成員。"})
    return {"study_id": study_id, "aggregate_id": aggregate_id, "count": len(rows), "members": rows}


@router.get("/{study_id}/chart/{period}")
def get_chart(study_id: str, period: int, repo: AnalyticsRepository = Depends(repository)):
    item = _study_or_404(repo, study_id)
    result = _require_completed(item)
    chart = (result.get("charts") or {}).get(str(period))
    if chart is None:
        raise HTTPException(status_code=404, detail={"code": "MA_ANALYTICS_PERIOD_NOT_FOUND", "message": "均線週期沒有研究結果。"})
    return {"study_id": study_id, "period": period, "daily_data": chart,
            "events": [x for x in result.get("events", []) if x["sma_period"] == period],
            "failures": [x for x in result.get("failure_outcomes", []) if x.get("sma_period") == period],
            "target_outcomes": [x for x in result.get("target_outcomes", [])
                                if next((e["sma_period"] for e in result.get("events", []) if e["event_id"] == x["event_id"]), None) == period],
            "target_session_audit": [x for x in result.get("target_session_audit", [])
                                      if next((e["sma_period"] for e in result.get("events", []) if e["event_id"] == x["event_id"]), None) == period]}


@router.get("/{study_id}/export")
def export_study(study_id: str, format: str = Query("json", pattern="^(json|events.csv|aggregates.csv)$"),
                 repo: AnalyticsRepository = Depends(repository)):
    item = _study_or_404(repo, study_id)
    result = _require_completed(item)
    if format == "json":
        return {k: v for k, v in result.items() if k != "charts"} | {"charts": result.get("charts")}
    if format == "events.csv":
        rows = result.get("events", [])
        filename = f"{result.get('ticker','study')}_ma_breakout_events.csv"
    else:
        rows = result.get("aggregates", [])
        filename = f"{result.get('ticker','study')}_ma_breakout_aggregates.csv"
    fields = sorted({key for row in rows for key, value in row.items() if key != "members" and not isinstance(value, (dict, list))})
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return Response(buffer.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
