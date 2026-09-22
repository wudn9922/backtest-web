from __future__ import annotations

"""Provider-neutral cache-first market-data coordinator."""

import re
from datetime import date
from typing import Any, Iterable

import pandas as pd

from app.backtest.models import BacktestError
from app.data.base import DataProvider, MarketData, validate_daily_ohlcv


def _safe_message(value: object) -> str:
    message = " ".join(str(value or "provider returned no additional details").split())
    message = re.sub(r"https?://\S+", "[URL omitted]", message, flags=re.IGNORECASE)
    message = re.sub(r"(?:[A-Za-z]:\\|/)(?:[^\s:]+[/\\]){2,}[^\s:]*", "[path omitted]", message)
    message = re.sub(r"(?i)(password|passwd|token|secret|authorization|cookie)\s*[=:]\s*[^\s,;]+", r"\1=[redacted]", message)
    return message[:500]


class ProviderChain(DataProvider):
    """Select complete local cache first, then resilient daily providers.

    Each provider owns a separate cache namespace.  The chain never combines
    bars from different providers in one frame, which prevents adjustment-mode
    mismatches from silently changing a backtest.
    """

    provider_key = "auto"

    def __init__(self, yahoo: DataProvider, alternative: DataProvider):
        self.yahoo = yahoo
        self.alternative = alternative
        self.providers: dict[str, DataProvider] = {
            "yahoo": yahoo,
            "alternative": alternative,
        }
        self.last_attempts: list[dict[str, Any]] = []

    def _probe_host(self, host: str) -> bool:
        """Compatibility hook for older diagnostics that patched Yahoo probes."""
        probe = getattr(self.yahoo, "_probe_host", None)
        return bool(probe(host)) if callable(probe) else False

    @staticmethod
    def _normalise_preference(value: str | None) -> str:
        value = (value or "auto").strip().lower()
        if value in {"stooq", "alternative", "alt"}:
            return "alternative"
        if value == "yahoo":
            return "yahoo"
        return "auto"

    def _order(self, preferred_provider: str | None) -> list[str]:
        preferred = self._normalise_preference(preferred_provider)
        if preferred == "alternative":
            return ["alternative", "yahoo"]
        return ["yahoo", "alternative"]

    @staticmethod
    def _cached_result(result: MarketData, key: str, attempts: list[dict[str, Any]]) -> MarketData:
        metadata = dict(result.metadata)
        metadata.update({
            "selected_provider": key,
            "provider_selection": "cache-first",
            "provider_attempts": attempts,
        })
        return MarketData(
            daily=result.daily,
            provider=result.provider or key,
            warnings=list(result.warnings),
            metadata=metadata,
        )

    def get_cached_market_data(
        self,
        ticker: str,
        start: date,
        end: date,
        preferred_provider: str = "auto",
        *,
        preferred: str | None = None,
    ) -> MarketData | None:
        if preferred is not None:
            preferred_provider = preferred
        attempts: list[dict[str, Any]] = []
        for key in self._order(preferred_provider):
            provider = self.providers[key]
            try:
                result = provider.get_cached_market_data(ticker, start, end)
            except Exception:
                result = None
            attempts.append({"provider": key, "source": "cache", "complete": bool(result)})
            if result is None:
                continue
            valid, issue = validate_daily_ohlcv(result.daily)
            if not valid:
                attempts[-1]["complete"] = False
                attempts[-1]["error_type"] = "INVALID_DATA"
                continue
            self.last_attempts = attempts
            cached_result = self._cached_result(result, key, attempts)
            if key == "yahoo" and getattr(provider, "offline_cooldown_active", lambda: False)():
                cached_result.warnings.insert(0, "Yahoo currently unavailable — using cached market data.")
                cached_result.metadata["stale_cache_fallback"] = True
            return cached_result
        self.last_attempts = attempts
        return None

    def _provider_status(self, key: str, provider: DataProvider, *, force: bool = False) -> dict[str, Any]:
        try:
            if hasattr(provider, "status_info"):
                value = provider.status_info(force=force)  # type: ignore[attr-defined]
            elif hasattr(provider, "status"):
                value = provider.status()  # type: ignore[attr-defined]
            else:
                value = {"reachable": None}
        except Exception:
            value = {"reachable": False, "error_type": "PROVIDER_CONNECTION_ERROR"}
        if not isinstance(value, dict):
            value = {}
        reachable = value.get("reachable")
        if reachable is None:
            reachable = bool(value.get("query1_reachable") or value.get("query2_reachable"))
        error_type = value.get("error_type")
        if not reachable and not error_type:
            error_type = "PROVIDER_CONNECTION_ERROR"
        cache = getattr(provider, "cache", None)
        cache_available = False
        try:
            cache_available = bool(cache.has_any("SPY", "1d")) if cache is not None else False
        except Exception:
            cache_available = False
        result = {
            "provider": key,
            "reachable": bool(reachable) if reachable is not None else None,
            "error_type": error_type,
            "cache_available": cache_available,
            "cooldown_active": bool(value.get("cooldown_active", False)),
        }
        # Yahoo host-level reachability remains useful for diagnostics; the
        # alternative provider simply omits these optional fields.
        for host_key in ("query1_reachable", "query2_reachable"):
            if host_key in value:
                result[host_key] = bool(value[host_key])
        return result

    def status_info(self, *, force: bool = False) -> dict[str, Any]:
        # The status endpoint intentionally probes both services, but each
        # provider internally caches an outage so backtests do not repeat the
        # expensive Yahoo host/retry sequence for every request.
        yahoo = self._provider_status("yahoo", self.yahoo, force=force)
        alternative = self._provider_status("alternative", self.alternative, force=force)
        providers = {"yahoo": yahoo, "alternative": alternative}
        reachable = [item.get("reachable") is True for item in providers.values()]
        if all(reachable):
            state = "online"
        elif any(reachable):
            state = "degraded"
        else:
            state = "offline"
        preferred = "yahoo" if yahoo.get("reachable") else "alternative" if alternative.get("reachable") else None
        cache_available = any(bool(item.get("cache_available")) for item in providers.values())
        return {
            "status": state,
            "providers": providers,
            "preferred_provider": preferred,
            "cache_available": cache_available,
        }

    def status(self) -> dict[str, Any]:
        return self.status_info()

    def _unavailable_error(
        self,
        ticker: str,
        start: date,
        end: date,
        preferred_provider: str,
        errors: dict[str, dict[str, Any]],
        attempts: list[dict[str, Any]],
    ) -> BacktestError:
        codes = [str(item.get("code")) for item in errors.values()]
        if codes and all(code == "NO_DATA" for code in codes):
            code = "NO_DATA"
            message = f"No daily historical data found for {ticker} in the requested range."
        else:
            code = "MARKET_DATA_PROVIDERS_UNAVAILABLE"
            message = "Market data providers are currently unavailable."
        cache_coverage = next(
            (item.get("cache_coverage") for item in errors.values() if item.get("cache_coverage")),
            None,
        )
        cache_last_updated = next(
            (item.get("cache_last_updated") for item in errors.values() if item.get("cache_last_updated")),
            None,
        )
        safe_errors = {
            key: {
                "code": value.get("code"),
                "error_type": value.get("error_type") or value.get("code"),
                "message": _safe_message(value.get("message")),
            }
            for key, value in errors.items()
        }
        return BacktestError(
            code,
            message,
            details={
                "data_kind": "daily",
                "ticker": ticker,
                "requested_start": start.isoformat(),
                "requested_end": end.isoformat(),
                "market_data_provider": preferred_provider,
                "provider_error_code": code,
                "provider_errors": safe_errors,
                "provider_attempts": attempts,
                "cache_coverage": cache_coverage,
                "cache_last_updated": cache_last_updated,
            },
        )

    def get_market_data(
        self,
        ticker: str,
        start: date,
        end: date,
        preferred_provider: str = "auto",
        *,
        preferred: str | None = None,
    ) -> MarketData:
        if preferred is not None:
            preferred_provider = preferred
        preferred = self._normalise_preference(preferred_provider)
        cached = self.get_cached_market_data(ticker, start, end, preferred)
        if cached is not None:
            return cached

        attempts = list(self.last_attempts)
        errors: dict[str, dict[str, Any]] = {}
        skipped_yahoo = False
        order = self._order(preferred)
        for key in order:
            provider = self.providers[key]
            if key == "yahoo" and getattr(provider, "offline_cooldown_active", lambda: False)():
                skipped_yahoo = True
                attempts.append({"provider": key, "source": "network", "skipped": "offline_cooldown"})
                errors[key] = {
                    "code": "PROVIDER_CONNECTION_ERROR",
                    "error_type": "PROVIDER_CONNECTION_ERROR",
                    "message": "Yahoo currently unavailable (cooldown active).",
                }
                continue
            try:
                result = provider.get_market_data(ticker, start, end)
                valid, issue = validate_daily_ohlcv(result.daily)
                if not valid:
                    raise BacktestError(
                        "INVALID_DATA",
                        f"{key} daily data failed validation: {issue}.",
                        details={"provider_error": issue},
                    )
                attempts.append({"provider": key, "source": "network", "status": "success"})
                metadata = dict(result.metadata)
                metadata.update({
                    "selected_provider": key,
                    "provider_selection": "preferred" if key == order[0] else "fallback",
                    "provider_attempts": attempts,
                })
                warnings = list(result.warnings)
                if key == "alternative" and (errors.get("yahoo") or skipped_yahoo):
                    warnings.insert(0, "Yahoo currently unavailable. Automatically using Stooq daily data.")
                self.last_attempts = attempts
                return MarketData(daily=result.daily, provider=result.provider or key, warnings=list(dict.fromkeys(warnings)), metadata=metadata)
            except BacktestError as exc:
                detail = dict(exc.details)
                errors[key] = {
                    "code": exc.code,
                    "error_type": detail.get("error_type") or exc.code,
                    "message": exc.message,
                    "cache_coverage": detail.get("cache_coverage"),
                    "cache_last_updated": detail.get("cache_last_updated"),
                }
                attempts.append({
                    "provider": key,
                    "source": "network",
                    "status": "failed",
                    "code": exc.code,
                })
            except Exception as exc:  # provider boundary: never leak traceback
                errors[key] = {
                    "code": "PROVIDER_CONNECTION_ERROR",
                    "error_type": "PROVIDER_CONNECTION_ERROR",
                    "message": _safe_message(exc),
                }
                attempts.append({
                    "provider": key,
                    "source": "network",
                    "status": "failed",
                    "code": "PROVIDER_CONNECTION_ERROR",
                })
        self.last_attempts = attempts
        raise self._unavailable_error(ticker, start, end, preferred, errors, attempts)

    def get_daily(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        return self.get_market_data(ticker, start, end).daily
