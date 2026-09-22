from __future__ import annotations

"""Canonical Daily OHLC preparation shared by API and orchestration tools.

This module deliberately owns only provider range selection.  Indicator
calculation, the evaluation boundary, and every strategy decision remain in
``BacktestEngine``.
"""

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.backtest.models import BacktestError, BacktestRequest
from app.data.base import DataProvider, MarketData, normalize_ohlcv, validate_daily_ohlcv
from app.data.cache import ParquetCache
from app.data.fallback import ProviderChain


def required_warmup_days(request: BacktestRequest, *, ma_period: int | None = None) -> int:
    """Return the existing canonical calendar pre-roll convention.

    ``ma_period`` lets a batch prepare once for its largest requested MA.  This
    is the same formula historically used by the normal backtest API; moving it
    here prevents optimizer drift without changing strategy semantics.
    """
    params = request.parameters
    period = int(ma_period if ma_period is not None else params.ma_period)
    return max(period * 2, params.bias_lookback * 2, params.atr_period * 3) + 20


def required_warmup_start(
    request: BacktestRequest,
    *,
    evaluation_start: date | None = None,
    ma_period: int | None = None,
) -> date:
    start = evaluation_start or request.start_date
    return start - timedelta(days=required_warmup_days(request, ma_period=ma_period))


def prepare_daily_market_data(
    request: BacktestRequest,
    provider: DataProvider,
    *,
    evaluation_start: date | None = None,
    evaluation_end: date | None = None,
    ma_period: int | None = None,
) -> MarketData:
    """Load one canonical Daily OHLC frame with indicator pre-roll."""
    start = required_warmup_start(
        request,
        evaluation_start=evaluation_start,
        ma_period=ma_period,
    )
    end = evaluation_end or request.end_date
    if isinstance(provider, ProviderChain):
        try:
            return provider.get_market_data(
                request.ticker,
                start,
                end,
                preferred_provider=request.market_data_provider,
            )
        except BacktestError:
            # If upstream is offline and the desired pre-roll is unavailable,
            # the canonical engine can still initialise indicators from a
            # complete evaluation-period cache.  It will expose the later
            # ``first_strategy_date`` rather than silently trading on NaNs.
            fallback = _validated_research_cache(provider, request, start, end)
            full_preroll = fallback is not None
            if fallback is None:
                fallback = provider.get_cached_market_data(
                    request.ticker,
                    evaluation_start or request.start_date,
                    end,
                    preferred_provider=request.market_data_provider,
                )
            if fallback is None:
                fallback = _validated_research_cache(
                    provider,
                    request,
                    evaluation_start or request.start_date,
                    end,
                )
            if fallback is None:
                raise
            metadata = dict(fallback.metadata)
            metadata.update({
                "warmup_fallback": not full_preroll,
                "desired_warmup_start": start.isoformat(),
                "available_from": fallback.daily.index[0].date().isoformat(),
            })
            warnings = list(fallback.warnings)
            if not full_preroll:
                warnings.append(
                    "Complete pre-roll was unavailable. The engine used cached data "
                    "from the evaluation period and begins only on the first date "
                    "where every required indicator is fully initialized."
                )
            return MarketData(
                daily=fallback.daily,
                provider=fallback.provider,
                warnings=list(dict.fromkeys(warnings)),
                metadata=metadata,
            )
    return provider.get_market_data(request.ticker, start, end)


def _validated_research_cache(
    chain: ProviderChain,
    request: BacktestRequest,
    start: date,
    end: date,
) -> MarketData | None:
    """Read a complete same-provider research cache without mixing sources.

    The data center stores long-history files in provider-specific namespaces.
    This read-only fallback accepts one such file only when its sidecar confirms
    the exact provider and adjustment contract of the selected provider.
    """
    attempts: list[dict[str, Any]] = []
    for key in chain._order(request.market_data_provider):
        concrete = chain.providers[key]
        primary_cache = getattr(concrete, "cache", None)
        provider_key = str(getattr(concrete, "provider_key", key))
        adjustment = getattr(concrete, "adjustment_mode", None)
        if primary_cache is None:
            continue
        root = Path(primary_cache.root).resolve().parent / "research-cache" / provider_key
        cache = ParquetCache(root)
        coverage = cache.read_coverage(request.ticker, "1d", start, end)
        attempts.append({"provider": provider_key, "source": "research_cache", "complete": coverage.complete})
        if not coverage.complete:
            continue
        valid_contract = True
        for path in coverage.paths:
            metadata = cache.read_metadata(path)
            if metadata.get("provider") not in (None, provider_key):
                valid_contract = False
            if adjustment and metadata.get("adjustment_mode") not in (None, adjustment):
                valid_contract = False
        frame = normalize_ohlcv(coverage.frame)
        valid, _ = validate_daily_ohlcv(frame)
        if not valid_contract or not valid:
            continue
        updated = coverage.last_updated.isoformat() if coverage.last_updated else None
        return MarketData(
            daily=frame,
            provider=provider_key,
            warnings=[
                "Using validated provider-specific long-history cache; no market-data providers were queried."
            ],
            metadata={
                "provider": provider_key,
                "provider_display_name": getattr(concrete, "display_name", provider_key),
                "adjustment_mode": adjustment,
                "data_source": "validated_research_cache",
                "cache_available": True,
                "cache_complete": True,
                "cache_last_updated": updated,
                "cache_coverage": coverage.as_dict(),
                "provider_attempts": attempts,
            },
        )
    return None
