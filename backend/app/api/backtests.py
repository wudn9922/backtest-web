from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.backtest.data_preparation import prepare_daily_market_data
from app.backtest.engine import BacktestEngine
from app.backtest.diagnostics import build_day1_stop_diagnostic, comparable_request_signature, find_matching_advanced
from app.backtest.models import BacktestError, BacktestRequest, StrategyName
from app.backtest.sensitivity import POLICY_ORDER, STRATEGY_ORDER, build_ambiguity_sensitivity
from app.data.base import DataProvider
from app.data.fallback import ProviderChain
from app.db.repository import BacktestRepository
from app.presentation.position_audit import present_position_audit


router = APIRouter(prefix="/api/backtests", tags=["backtests"])


def repository(request: Request) -> BacktestRepository:
    return request.app.state.repository


def provider(request: Request) -> DataProvider:
    return request.app.state.provider


@router.post("")
def create_backtest(payload: BacktestRequest, repo: BacktestRepository = Depends(repository), data_provider: DataProvider = Depends(provider)):
    request_data = payload.model_dump(mode="json")
    if payload.strategy != StrategyName.ADVANCED_DAY1_STOP:
        # Keep persisted Simple/Advanced parameter payloads backward-identical;
        # the variant-only field is irrelevant to those strategies.
        request_data["parameters"].pop("day1_stop_pct", None)
    identifier = repo.create_pending(request_data)
    daily_bars_count = 0
    context = {
        "ticker": payload.ticker,
        "requested_start": payload.start_date.isoformat(),
        "requested_end": payload.end_date.isoformat(),
        "execution_model": payload.execution_model,
        "execution_timeframe": "daily",
        "execution_policy": payload.execution_policy,
        "market_data_provider": payload.market_data_provider,
    }
    try:
        market_data = prepare_daily_market_data(payload, data_provider)
        daily = market_data.daily
        daily_bars_count = len(daily)
        engine = BacktestEngine()
        result = engine.run(payload, daily, market_data.provider)
        if market_data.warnings:
            result["warnings"] = list(dict.fromkeys([*market_data.warnings, *result.get("warnings", [])]))
        # Keep the engine's strategy calculations independent from the provider,
        # while exposing enough provenance for a user to understand a cached or
        # refreshed run.  Nested metadata is intentionally JSON-safe and contains
        # no paths, credentials, or raw response bodies.
        fetch_metadata = dict(market_data.metadata)
        result["data_coverage"].update({
            "data_provider": market_data.provider,
            "provider_display_name": fetch_metadata.get("provider_display_name", market_data.provider),
            "adjustment_mode": fetch_metadata.get("adjustment_mode"),
            "market_data_provider": payload.market_data_provider,
            "data_source": fetch_metadata.get("data_source", "unknown"),
            "cache_available": bool(fetch_metadata.get("cache_available", False)),
            "cache_complete": bool(fetch_metadata.get("cache_complete", False)),
            "cache_last_updated": fetch_metadata.get("cache_last_updated"),
            "cache_coverage": fetch_metadata.get("cache_coverage"),
            "yahoo_error": fetch_metadata.get("yahoo_error"),
            "provider_error": fetch_metadata.get("provider_error"),
            "provider_attempts": fetch_metadata.get("provider_attempts"),
        })
        result["reproducibility"]["data_fetch"] = fetch_metadata
        result["id"] = identifier
        repo.complete(identifier, result, engine.position_audits)
        return result
    except BacktestError as exc:
        repo.fail(identifier, exc.message)
        detail = {
            "code": exc.code,
            "message": exc.message,
            **exc.details,
            # Keep the user's requested range as the primary context.  The
            # provider may also have a larger warm-up range in its details.
            **context,
            "daily_bars_count": daily_bars_count,
            "yahoo_error": exc.details.get("yahoo_error"),
        }
        if exc.details.get("requested_start") and exc.details.get("requested_start") != context["requested_start"]:
            detail["provider_requested_start"] = exc.details["requested_start"]
        if exc.details.get("requested_end") and exc.details.get("requested_end") != context["requested_end"]:
            detail["provider_requested_end"] = exc.details["requested_end"]
        raise HTTPException(
            status_code=exc.status_code,
            detail=detail,
        ) from exc
    except Exception as exc:
        repo.fail(identifier, str(exc))
        raise HTTPException(status_code=500, detail={
            "code": "BACKTEST_FAILED",
            "message": "Backtest failed. Check data coverage and parameters.",
            **context,
            "daily_bars_count": daily_bars_count,
            "yahoo_error": None,
        }) from exc


@router.get("")
def list_backtests(repo: BacktestRepository = Depends(repository)):
    return repo.list()


@router.get("/{identifier}/diagnostics/day1-stop")
def get_day1_stop_diagnostic(identifier: str, baseline_backtest_id: str | None = None, repo: BacktestRepository = Depends(repository)):
    variant = repo.get(identifier)
    if variant is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Backtest not found."})
    if variant["strategy"] != "advanced_day1_stop" or variant["status"] != "COMPLETED" or not variant["result"]:
        raise HTTPException(status_code=400, detail={"code": "INVALID_DIAGNOSTIC_SOURCE", "message": "Run a completed Advanced + Day1 3% Stop backtest before opening this diagnostic."})
    if baseline_backtest_id:
        baseline = repo.get(baseline_backtest_id)
        if baseline is None:
            raise HTTPException(status_code=404, detail={"code": "BASELINE_NOT_FOUND", "message": "The selected Advanced baseline backtest was not found."})
        compatible = baseline["strategy"] == "advanced" and comparable_request_signature(baseline["parameters"]) == comparable_request_signature(variant["parameters"])
        if not compatible:
            raise HTTPException(status_code=400, detail={"code": "BASELINE_PARAMETERS_MISMATCH", "message": "The Advanced baseline must use the same ticker, dates, costs, sizing, and shared strategy parameters."})
    else:
        summary = find_matching_advanced(variant, repo.list())
        baseline = repo.get(summary["id"]) if summary else None
    if baseline is None or not baseline.get("result"):
        raise HTTPException(status_code=409, detail={"code": "MATCHING_BASELINE_REQUIRED", "message": "Run the existing Advanced strategy with the same ticker, dates, costs, sizing, and shared parameters first."})
    return build_day1_stop_diagnostic(variant_record=variant, baseline_record=baseline)


@router.post("/{identifier}/diagnostics/ambiguity-sensitivity")
def run_ambiguity_sensitivity(identifier: str, repo: BacktestRepository = Depends(repository), data_provider: DataProvider = Depends(provider)):
    source = repo.get(identifier)
    if source is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Backtest not found."})
    if source["strategy"] != StrategyName.ADVANCED_DAY1_STOP.value or source["status"] != "COMPLETED":
        raise HTTPException(status_code=400, detail={"code": "INVALID_SENSITIVITY_SOURCE", "message": "Run a completed Advanced + Day1 3% Stop backtest first."})

    source_request = BacktestRequest.model_validate(source["parameters"])
    market_data = prepare_daily_market_data(source_request, data_provider)
    daily = market_data.daily
    records: dict[tuple[str, str], dict] = {}
    strategy_values = {
        "advanced": StrategyName.ADVANCED,
        "advanced_day1_stop": StrategyName.ADVANCED_DAY1_STOP,
    }
    for strategy_name in STRATEGY_ORDER:
        for policy_name in POLICY_ORDER:
            policy_request = source_request.model_copy(update={"strategy": strategy_values[strategy_name], "execution_policy": policy_name})
            request_data = policy_request.model_dump(mode="json")
            if strategy_name == "advanced":
                request_data["parameters"].pop("day1_stop_pct", None)
            new_id = repo.create_pending(request_data)
            try:
                engine = BacktestEngine()
                result = engine.run(policy_request, daily, market_data.provider)
                result["id"] = new_id
                repo.complete(new_id, result, engine.position_audits)
                records[(strategy_name, policy_name)] = repo.get(new_id)
            except Exception as exc:
                repo.fail(new_id, str(exc))
                raise

    legacy = next((
        repo.get(item["id"]) for item in repo.list()
        if item.get("strategy_version") is None
        and item.get("status") == "COMPLETED"
        and item.get("strategy") == StrategyName.ADVANCED_DAY1_STOP.value
        and item.get("ticker") == source["ticker"]
        and item.get("start_date") == source["start_date"]
        and item.get("end_date") == source["end_date"]
    ), None)
    return build_ambiguity_sensitivity(records=records, legacy_record=legacy)


@router.get("/{identifier}")
def get_backtest(identifier: str, repo: BacktestRepository = Depends(repository)):
    item = repo.get(identifier)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Backtest not found."})
    return item


@router.get("/{identifier}/positions/{position_id}/audit")
def get_position_audit(identifier: str, position_id: str, repo: BacktestRepository = Depends(repository)):
    audit = repo.get_position_audit(identifier, position_id)
    if audit is None:
        if repo.get(identifier) is None:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Backtest not found."})
        raise HTTPException(status_code=404, detail={"code": "POSITION_AUDIT_NOT_FOUND", "message": "Position audit is unavailable. Legacy backtests must be run again to generate audit data."})
    record = repo.get(identifier)
    return present_position_audit(audit, record or {})


@router.delete("/{identifier}", status_code=204)
def delete_backtest(identifier: str, repo: BacktestRepository = Depends(repository)):
    if not repo.delete(identifier):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Backtest not found."})
