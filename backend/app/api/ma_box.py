from __future__ import annotations

from datetime import date, timedelta
import csv
import hashlib
import io
import json
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.backtest.data_preparation import prepare_daily_market_data
from app.backtest.models import BacktestError, BacktestRequest, StrategyName
from app.data.base import DataProvider
from app.db.repository import BacktestRepository
from app.ma_box.engine import MABoxConfig, SPEC_REVISION_NUMBER, config_sha256, run_ma_box_study, spec_sha256


# The study API is deliberately namespaced below ``/studies``.  It keeps the
# new strategy's persistence/API contract separate from every legacy backtest
# endpoint (and makes it impossible for a study id to be mistaken for a
# legacy backtest id).
router = APIRouter(prefix="/api/ma-box/studies", tags=["ma-box-long-v1"])


class MABoxStudyRequest(BaseModel):
    """Dedicated request model; deliberately not part of the legacy selector."""

    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=24)
    selected_ma: int = Field(20, ge=2, le=500)
    nearby_range: int = Field(5, ge=0, le=100)
    step: int = Field(1, ge=1, le=20)
    start_date: date
    end_date: date

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        value = value.strip().upper()
        import re
        if not re.fullmatch(r"[A-Z0-9.\^=\-]{1,24}", value):
            raise ValueError("ticker contains unsupported characters")
        return value

    @model_validator(mode="after")
    def dates_valid(self) -> "MABoxStudyRequest":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        if self.end_date - self.start_date > timedelta(days=365 * 20 + 5):
            raise ValueError("date range cannot exceed 20 years")
        if not self.periods():
            raise ValueError("nearby range does not produce any supported SMA period")
        return self

    def periods(self) -> list[int]:
        lower = max(2, self.selected_ma - self.nearby_range)
        upper = min(500, self.selected_ma + self.nearby_range)
        periods = list(range(lower, upper + 1, self.step))
        if lower <= self.selected_ma <= upper and self.selected_ma not in periods:
            periods.append(self.selected_ma)
            periods.sort()
        return periods


def repository(request: Request) -> BacktestRepository:
    return request.app.state.repository


def provider(request: Request) -> DataProvider:
    return request.app.state.provider


def _require_completed(study: dict[str, Any]) -> None:
    """Use one lifecycle contract for every result-bearing endpoint."""
    if study["status"] == "RUNNING":
        raise HTTPException(status_code=409, detail={
            "code": "MA_BOX_STUDY_NOT_COMPLETE", "status": "RUNNING",
            "message": "MA_BOX_LONG_V1 study is still running.",
        })
    if study["status"] == "FAILED":
        error = study.get("result") or {}
        raise HTTPException(status_code=409, detail={
            "code": "MA_BOX_STUDY_FAILED", "status": "FAILED",
            "message": error.get("error_message", "MA_BOX_LONG_V1 study failed."),
        })


def _fingerprint(frame: pd.DataFrame) -> str:
    canonical = frame[["open", "high", "low", "close", "volume"]].copy().sort_index()
    values = pd.util.hash_pandas_object(canonical, index=True).to_numpy().tobytes()
    return hashlib.sha256(values).hexdigest()


def _canonical_request(payload: MABoxStudyRequest) -> BacktestRequest:
    # This request is only the provider/warm-up adapter. It is never persisted
    # in the legacy backtests table and never enters the legacy selector.
    return BacktestRequest(
        ticker=payload.ticker, strategy=StrategyName.SIMPLE,
        start_date=payload.start_date, end_date=payload.end_date,
        initial_capital=100_000.0, position_size_pct=100.0,
        execution_model="daily_conservative", execution_policy="ohlc_heuristic",
        market_data_provider="auto", commission_pct=0.05,
        slippage_pct=0.02, force_close_at_end=True,
        parameters={"ma_type": "sma", "ma_period": max(payload.periods()),
                    "breakout_trigger_pct": 1.0, "entry_stop_pct": 1.5,
                    "exit_below_ma_pct": 1.5},
    )


@router.get("")
def list_ma_box_studies(repo: BacktestRepository = Depends(repository)):
    return repo.list_ma_box_studies()


@router.post("", status_code=201)
def create_ma_box_study(payload: MABoxStudyRequest, repo: BacktestRepository = Depends(repository), data_provider: DataProvider = Depends(provider)):
    provider_request = _canonical_request(payload)
    # Persist the lifecycle row before touching the provider or engine.  This
    # makes failures observable as FAILED rather than disappearing as a 500.
    config = MABoxConfig(
        ticker=payload.ticker, selected_ma=payload.selected_ma,
        nearby_range=payload.nearby_range, step=payload.step,
        start_date=payload.start_date, end_date=payload.end_date,
        initial_capital=100_000.0, position_size_pct=100.0,
        commission_pct=0.05, slippage_pct=0.02, force_close_at_end=True,
    )
    spec_hash = spec_sha256()
    pending_id = repo.create_ma_box_study(
        config=config.as_dict(), strategy_revision="MA_BOX_LONG_V1",
        spec_revision="MA_BOX_LONG_V1_REVISION_3", spec_hash=spec_hash,
        config_hash=config_sha256(config, spec_hash=spec_hash, data_fingerprint=None),
        data_fingerprint=None, provider=None, spec_revision_number=SPEC_REVISION_NUMBER,
    )
    try:
        market = prepare_daily_market_data(
            provider_request, data_provider,
            evaluation_start=payload.start_date,
            evaluation_end=payload.end_date,
            ma_period=max(payload.periods()),
        )
        data_fingerprint = _fingerprint(market.daily)
        final_config_hash = config_sha256(config, spec_hash=spec_hash, data_fingerprint=data_fingerprint)
        repo.update_ma_box_study_identity(pending_id, config_hash=final_config_hash,
                                          data_fingerprint=data_fingerprint, provider=market.provider)
        result = run_ma_box_study(market.daily, config, provider=market.provider,
                                  data_fingerprint=data_fingerprint, spec_hash=spec_hash)
        result["data_provenance"].update({
            "provider_display_name": market.metadata.get("provider_display_name", market.provider),
            "adjustment_mode": market.metadata.get("adjustment_mode"),
            "data_source": market.metadata.get("data_source"),
            "cache_coverage": market.metadata.get("cache_coverage"),
            "warnings": market.warnings,
        })
        result["study_id"] = pending_id
        repo.complete_ma_box_study(pending_id, result)
        return result
    except BacktestError as exc:
        repo.fail_ma_box_study(pending_id, exc.message, error_code=exc.code)
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message, **exc.details}) from exc
    except ValueError as exc:
        repo.fail_ma_box_study(pending_id, str(exc), error_code="MA_BOX_INVALID_DATA")
        raise HTTPException(status_code=422, detail={"code": "MA_BOX_INVALID_DATA", "message": str(exc)}) from exc
    except Exception as exc:
        repo.fail_ma_box_study(pending_id, "MA_BOX_LONG_V1 study failed.", error_code="MA_BOX_STUDY_FAILED")
        raise HTTPException(status_code=500, detail={"code": "MA_BOX_STUDY_FAILED", "message": "MA_BOX_LONG_V1 study failed."}) from exc


@router.get("/{study_id}")
def get_ma_box_study(study_id: str, repo: BacktestRepository = Depends(repository)):
    item = repo.get_ma_box_study(study_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "MA_BOX_NOT_FOUND", "message": "MA_BOX_LONG_V1 study not found."})
    return item


@router.get("/{study_id}/summary")
def get_ma_box_summary(study_id: str, repo: BacktestRepository = Depends(repository)):
    item = repo.get_ma_box_study(study_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "MA_BOX_NOT_FOUND", "message": "MA_BOX_LONG_V1 study not found."})
    _require_completed(item)
    result = item.get("result") or {}
    return {"study_id": study_id, "status": item["status"], "config": item["config"],
            "spec_revision": item["spec_revision"], "spec_hash": item["spec_hash"],
            "spec_revision_number": item["spec_revision_number"],
            "data_fingerprint": item["data_fingerprint"], "data_provenance": result.get("data_provenance"),
            "evaluation_start": result.get("evaluation_start"), "evaluation_end": result.get("evaluation_end"),
            "selected_summary": result.get("selected_summary"), "periods": result.get("periods", [])}


@router.get("/{study_id}/runs/{period}/{track}")
def get_ma_box_run(study_id: str, period: int, track: str, repo: BacktestRepository = Depends(repository)):
    study = repo.get_ma_box_study(study_id)
    if study is None:
        raise HTTPException(status_code=404, detail={"code": "MA_BOX_NOT_FOUND", "message": "MA_BOX_LONG_V1 study not found."})
    _require_completed(study)
    run = repo.get_ma_box_run(study_id, period, track)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "MA_BOX_RUN_NOT_FOUND", "message": "MA_BOX_LONG_V1 run not found."})
    return {"study_id": study_id, "period": period, "track": track, "run": run}


@router.get("/{study_id}/chart/{period}")
def get_ma_box_chart(study_id: str, period: int, repo: BacktestRepository = Depends(repository)):
    study = repo.get_ma_box_study(study_id)
    if study is None:
        raise HTTPException(status_code=404, detail={"code": "MA_BOX_NOT_FOUND", "message": "MA_BOX_LONG_V1 study not found."})
    _require_completed(study)
    run = repo.get_ma_box_run(study_id, period, "MA_BOX_LONG_V1")
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "MA_BOX_RUN_NOT_FOUND", "message": "MA_BOX_LONG_V1 chart run not found."})
    return {"study_id": study_id, "period": period, "daily_data": run.get("data", []),
            "events": run.get("events", []), "executions": run.get("executions", []),
            "positions": run.get("positions", []), "equity_curve": run.get("equity_curve", []),
            "drawdown_curve": run.get("drawdown_curve", []), "daily_ledger": run.get("daily_ledger", [])}


@router.get("/{study_id}/counterfactuals/{period}")
def get_ma_box_counterfactuals(study_id: str, period: int, repo: BacktestRepository = Depends(repository)):
    item = repo.get_ma_box_study(study_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "MA_BOX_NOT_FOUND", "message": "MA_BOX_LONG_V1 study not found."})
    _require_completed(item)
    run = repo.get_ma_box_run(study_id, period, "MA_BOX_LONG_V1")
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "MA_BOX_RUN_NOT_FOUND", "message": "MA_BOX_LONG_V1 run not found."})
    return {"study_id": study_id, "period": period, "summary": run.get("counterfactual_summary", {}),
            "trades": run.get("counterfactual_trades", [])}


@router.get("/{study_id}/export/{period}")
def export_ma_box_run(study_id: str, period: int, format: str = "json", repo: BacktestRepository = Depends(repository)):
    study = repo.get_ma_box_study(study_id)
    if study is None:
        raise HTTPException(status_code=404, detail={"code": "MA_BOX_NOT_FOUND", "message": "MA_BOX_LONG_V1 study not found."})
    _require_completed(study)
    run = repo.get_ma_box_run(study_id, period, "MA_BOX_LONG_V1")
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "MA_BOX_RUN_NOT_FOUND", "message": "MA_BOX_LONG_V1 run not found."})
    normalized = format.strip().lower()
    if normalized == "json":
        return {"study_id": study_id, "period": period, "format": "json", "audit": run}
    if normalized in {"csv", "trades.csv"}:
        buffer = io.StringIO()
        positions = run.get("positions", [])
        fields = ["position_id", "entry_date", "entry_price", "final_exit_date", "exit_final_close_reason",
                  "q0", "gross_pnl", "net_pnl", "return_pct", "holding_days"]
        writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(positions)
        return Response(content=buffer.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="MA_BOX_LONG_V1_SMA{period}_trades.csv"'})
    if normalized in {"counterfactual", "counterfactual.csv", "counterfactuals", "counterfactuals.csv"}:
        buffer = io.StringIO()
        trades = run.get("counterfactual_trades", [])
        fields = [
            "counterfactual_trade_id", "source_baseline_position_id", "sma_period",
            "entry_date", "entry_raw_fill", "entry_actual_fill", "entry_quantity",
            "entry_commission", "entry_slippage_cost", "exit_date", "exit_reason",
            "exit_raw_fill", "exit_actual_fill", "exit_quantity", "exit_commission",
            "exit_slippage_cost", "gross_pnl", "net_pnl", "mfe", "mae", "holding_days",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(trades)
        return Response(content=buffer.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="MA_BOX_LONG_V1_SMA{period}_counterfactuals.csv"'})
    raise HTTPException(status_code=422, detail={"code": "MA_BOX_EXPORT_FORMAT_UNSUPPORTED", "message": "只支援 JSON 或 CSV 匯出。"})
