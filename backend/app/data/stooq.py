from __future__ import annotations

"""Stooq daily OHLCV provider.

Stooq is intentionally implemented as a separate provider rather than as a
fallback hidden inside the Yahoo adapter.  Its cache lives in its own
namespace, and its bars are never concatenated with Yahoo bars because the
two services do not promise identical corporate-action adjustment semantics.
"""

import io
import multiprocessing as mp
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.backtest.models import BacktestError
from app.data.base import DataProvider, MarketData, normalize_ohlcv, validate_daily_ohlcv
from app.data.cache import CacheCoverage, ParquetCache


EMPTY_COLUMNS = ["open", "high", "low", "close", "volume"]


def safe_stooq_error(error: object) -> str:
    """Return a bounded, display-safe Stooq message."""
    message = " ".join(str(error or "Stooq returned no additional error message.").split())
    message = re.sub(r"https?://\S+", "[URL omitted]", message, flags=re.IGNORECASE)
    message = re.sub(r"(?:[A-Za-z]:\\|/)(?:[^\s:]+[/\\]){2,}[^\s:]*", "[path omitted]", message)
    message = re.sub(r"(?i)(password|passwd|token|secret|authorization|cookie)\s*[=:]\s*[^\s,;]+", r"\1=[redacted]", message)
    return message[:500]


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=EMPTY_COLUMNS)


def _stooq_symbol(ticker: str) -> str:
    normalized = ticker.strip().lower()
    # Stooq's US symbols use the ``.us`` suffix.  Preserve index symbols and
    # already-qualified symbols for future provider extensions.
    if normalized.startswith("^"):
        return normalized
    if normalized.endswith(".us"):
        return normalized
    return f"{normalized}.us"


def _csv_url(ticker: str, start: date, end: date) -> str:
    params = urllib.parse.urlencode(
        {
            "s": _stooq_symbol(ticker),
            "i": "d",
            "d1": start.strftime("%Y%m%d"),
            "d2": end.strftime("%Y%m%d"),
        }
    )
    return f"https://stooq.com/q/d/l/?{params}"


def _stooq_worker(connection, url: str, timeout: int) -> None:
    try:
        request = urllib.request.Request(
            url,
            headers={"Accept": "text/csv", "User-Agent": "BacktestLab/0.1 (+daily-data-provider)"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200) or 200)
            payload = response.read(20 * 1024 * 1024)
        if status >= 400:
            connection.send((None, f"Stooq HTTP {status}.", "upstream", status))
        else:
            connection.send((payload, None, "ok", status))
    except urllib.error.HTTPError as exc:
        kind = "rate_limited" if exc.code == 429 else "server" if exc.code >= 500 else "upstream"
        connection.send((None, f"Stooq HTTP {exc.code}: {exc.reason}.", kind, int(exc.code)))
    except (socket.timeout, TimeoutError):
        connection.send((None, "Stooq request timed out.", "timeout", None))
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        connection.send((None, f"Stooq connection error: {reason}.", "connection", None))
    except Exception as exc:  # pragma: no cover - exercised through parent result
        connection.send((None, f"Stooq request failed: {exc}.", "connection", None))
    finally:
        connection.close()


@dataclass
class _RemoteFailure:
    code: str
    message: str
    attempts: int


class StooqDataProvider(DataProvider):
    """Free, no-key Stooq daily provider used after Yahoo in Auto mode."""

    provider_key = "stooq"
    display_name = "Stooq"
    # Stooq does not expose the same adjusted-close contract as Yahoo.  Keep
    # this provenance explicit and never merge the two provider namespaces.
    adjustment_mode = "provider_native_adjusted_for_splits"

    def __init__(self, cache_dir: Path | None = None):
        base = Path(cache_dir or Path("../data/cache"))
        self.cache = ParquetCache(base / "stooq")
        self.hard_timeout_seconds = max(5, int(os.getenv("STOOQ_REQUEST_TIMEOUT_SECONDS", "20")))
        self.max_retries = max(0, min(4, int(os.getenv("STOOQ_MAX_RETRIES", "2"))))
        self.retry_backoff_seconds = max(0.1, float(os.getenv("STOOQ_RETRY_BACKOFF_SECONDS", "1")))
        self.status_timeout_seconds = max(1, min(10, int(os.getenv("STOOQ_STATUS_TIMEOUT_SECONDS", "3"))))
        self.status_cache_seconds = max(5, int(os.getenv("STOOQ_STATUS_CACHE_SECONDS", "60")))
        self.offline_cooldown_seconds = max(30, int(os.getenv("STOOQ_OFFLINE_COOLDOWN_SECONDS", "300")))
        self._status_snapshot: dict[str, Any] | None = None
        self._status_checked_at: float | None = None
        self.last_fetch: dict[str, Any] = {}

    @staticmethod
    def _error_code(kind: str | None, status: int | None = None) -> str:
        if kind == "timeout":
            return "PROVIDER_TIMEOUT"
        if kind == "rate_limited" or status == 429:
            return "RATE_LIMITED"
        if kind in {"connection", "server"} or (status is not None and status >= 500):
            return "PROVIDER_CONNECTION_ERROR"
        if status in {400, 404} or kind == "no_data":
            return "NO_DATA"
        return "PROVIDER_CONNECTION_ERROR"

    @staticmethod
    def _coverage_dict(coverage: CacheCoverage) -> dict[str, Any]:
        value = coverage.as_dict()
        value["complete"] = coverage.complete
        value["missing_ranges"] = [
            {"start": left.isoformat(), "end": right.isoformat()}
            for left, right in coverage.missing_ranges
        ]
        return value

    def _set_fetch_metadata(
        self,
        *,
        ticker: str,
        start: date,
        end: date,
        coverage: CacheCoverage,
        source: str,
        error: str | None = None,
        error_code: str | None = None,
        warnings: list[str] | None = None,
        attempts: int = 0,
    ) -> None:
        cache_info = self._coverage_dict(coverage)
        cache_metadata = dict(coverage.metadata)
        cache_metadata.setdefault("ticker", ticker)
        cache_metadata.setdefault("provider", self.provider_key)
        cache_metadata.setdefault("adjustment_mode", self.adjustment_mode)
        cache_metadata.setdefault("first_date", cache_info.get("start"))
        cache_metadata.setdefault("last_date", cache_info.get("end"))
        cache_metadata.setdefault("last_updated", cache_info.get("last_updated"))
        self.last_fetch = {
            "provider": self.provider_key,
            "provider_display_name": self.display_name,
            "adjustment_mode": self.adjustment_mode,
            "ticker": ticker,
            "requested_start": start.isoformat(),
            "requested_end": end.isoformat(),
            "data_source": source,
            "cache_namespace": "stooq",
            "cache_available": coverage.available,
            "cache_complete": coverage.complete,
            "cache_coverage": cache_info,
            "cache_last_updated": cache_info.get("last_updated"),
            "cache_metadata": cache_metadata,
            "provider_error_code": error_code,
            "provider_error": error,
            "provider_attempts": attempts,
            "warnings": warnings or [],
        }

    def get_cached_market_data(self, ticker: str, start: date, end: date) -> MarketData | None:
        coverage = self.cache.read_coverage(ticker, "1d", start, end)
        if not coverage.complete:
            return None
        # Never consume a cache fragment explicitly attributed to another
        # provider or adjustment policy.  Legacy fragments without sidecars
        # remain compatible and receive metadata below.
        for path in coverage.paths:
            metadata = self.cache.read_metadata(path)
            cached_provider = metadata.get("provider")
            cached_adjustment = metadata.get("adjustment_mode")
            if cached_provider and cached_provider != self.provider_key:
                return None
            if cached_adjustment and cached_adjustment != self.adjustment_mode:
                return None
        frame = normalize_ohlcv(coverage.frame)
        valid, _ = validate_daily_ohlcv(frame)
        if not valid:
            return None
        for path in coverage.paths:
            if not self.cache.metadata_path(path).exists():
                self.cache.write_metadata(path, {
                    "ticker": ticker,
                    "provider": self.provider_key,
                    "adjustment_mode": self.adjustment_mode,
                    "first_date": coverage.coverage_start.isoformat() if coverage.coverage_start else None,
                    "last_date": coverage.coverage_end.isoformat() if coverage.coverage_end else None,
                    "last_updated": coverage.last_updated.isoformat() if coverage.last_updated else None,
                })
        self._set_fetch_metadata(
            ticker=ticker,
            start=start,
            end=end,
            coverage=coverage,
            source="cache",
            warnings=[
                "Using cached Stooq daily data; no network request was made. "
                f"Cache last updated: {coverage.last_updated.isoformat() if coverage.last_updated else 'unknown'}."
            ],
        )
        metadata = dict(self.last_fetch)
        warnings = list(metadata.pop("warnings", []))
        return MarketData(daily=frame, provider=self.provider_key, warnings=warnings, metadata=metadata)

    def _run_request(self, ticker: str, start: date, end: date) -> tuple[pd.DataFrame, str | None, str, int | None]:
        context = mp.get_context("spawn")
        parent, child = context.Pipe(duplex=False)
        process = context.Process(
            target=_stooq_worker,
            args=(child, _csv_url(ticker, start, end), min(10, self.hard_timeout_seconds)),
            daemon=True,
        )
        process.start()
        child.close()
        try:
            if parent.poll(self.hard_timeout_seconds):
                try:
                    payload, error, kind, status = parent.recv()
                except EOFError:
                    payload, error, kind, status = None, "Stooq data process exited without a result.", "connection", None
            else:
                payload, error, kind, status = None, f"Stooq request timed out after {self.hard_timeout_seconds} seconds.", "timeout", None
        finally:
            if process.is_alive():
                process.terminate()
            process.join(2)
            parent.close()
        if payload is None:
            return _empty_frame(), error, kind, status
        try:
            frame = self._csv_to_frame(payload)
            if frame.empty:
                return _empty_frame(), "Stooq returned no daily bars for this ticker and date range.", "no_data", status
            return frame, None, kind, status
        except Exception as exc:
            return _empty_frame(), f"Stooq response parsing failed: {exc}.", "upstream", status

    @staticmethod
    def _csv_to_frame(payload: bytes) -> pd.DataFrame:
        text = payload.decode("utf-8-sig", errors="replace")
        if not text.strip() or text.strip().lower().startswith("no data"):
            return _empty_frame()
        raw = pd.read_csv(io.StringIO(text))
        if raw.empty:
            return _empty_frame()
        raw.columns = [str(column).strip().lower().replace(" ", "_") for column in raw.columns]
        date_column = next((column for column in ("date", "timestamp") if column in raw.columns), None)
        if date_column is None:
            return _empty_frame()
        raw["timestamp"] = pd.to_datetime(raw.pop(date_column), errors="coerce", utc=True)
        raw = raw.set_index("timestamp")
        return normalize_ohlcv(raw)

    def _download_remote(self, ticker: str, start: date, end: date) -> tuple[pd.DataFrame, _RemoteFailure | None]:
        last_code = "PROVIDER_CONNECTION_ERROR"
        last_message = "Stooq returned no daily bars."
        attempts = 0
        for retry in range(self.max_retries + 1):
            if retry:
                time.sleep(self.retry_backoff_seconds * (2 ** (retry - 1)))
            frame, error, kind, status = self._run_request(ticker, start, end)
            attempts += 1
            if not frame.empty:
                valid, issue = validate_daily_ohlcv(frame)
                if valid:
                    return frame, None
                last_code = "INVALID_DATA"
                last_message = f"Stooq daily data failed validation: {issue}."
                break
            last_code = self._error_code(kind, status)
            last_message = " ".join(str(error or "Stooq returned no daily bars.").split())[:500]
            if kind == "no_data" or (status is not None and status < 500 and status != 429):
                break
        failure = _RemoteFailure(last_code, last_message, attempts)
        if failure.code in {"PROVIDER_CONNECTION_ERROR", "PROVIDER_TIMEOUT", "RATE_LIMITED"}:
            self._mark_offline(failure.code)
        return _empty_frame(), failure

    def _download(self, ticker: str, start: date, end: date) -> tuple[pd.DataFrame, str | None]:
        coverage = self.cache.read_coverage(ticker, "1d", start, end)
        if coverage.complete:
            cached = self.get_cached_market_data(ticker, start, end)
            if cached is not None:
                return cached.daily, None

        combined = coverage.frame.copy()
        missing_ranges = coverage.missing_ranges or [(start, end)]
        total_attempts = 0
        for missing_start, missing_end in missing_ranges:
            remote, failure = self._download_remote(ticker, missing_start, missing_end)
            if failure is not None:
                self._set_fetch_metadata(
                    ticker=ticker,
                    start=start,
                    end=end,
                    coverage=coverage,
                    source="cache_incomplete" if coverage.available else "alternative_failed",
                    error=failure.message,
                    error_code="CACHE_INCOMPLETE" if coverage.available else failure.code,
                    attempts=total_attempts + failure.attempts,
                )
                return _empty_frame(), failure.message
            total_attempts += 1
            combined = remote.copy() if combined.empty else pd.concat([combined, remote], axis=0, sort=False)

        frame = normalize_ohlcv(combined)
        if frame.empty:
            error = "Stooq returned no daily bars for this ticker and date range."
            self._set_fetch_metadata(
                ticker=ticker,
                start=start,
                end=end,
                coverage=coverage,
                source="alternative_failed",
                error=error,
                error_code="NO_DATA",
                attempts=total_attempts,
            )
            return _empty_frame(), error
        valid, issue = validate_daily_ohlcv(frame)
        if not valid:
            error = f"Stooq daily data failed validation: {issue}."
            self._set_fetch_metadata(
                ticker=ticker,
                start=start,
                end=end,
                coverage=coverage,
                source="invalid",
                error=error,
                error_code="INVALID_DATA",
                attempts=total_attempts,
            )
            return _empty_frame(), error
        self.cache.write(
            ticker,
            "1d",
            start,
            end,
            frame,
            metadata={
                "ticker": ticker,
                "provider": self.provider_key,
                "adjustment_mode": self.adjustment_mode,
                "first_date": min(ts.date() for ts in frame.index).isoformat(),
                "last_date": max(ts.date() for ts in frame.index).isoformat(),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            },
        )
        refreshed = self.cache.read_coverage(ticker, "1d", start, end)
        source = "stooq+cache" if coverage.available else "stooq"
        self._set_fetch_metadata(
            ticker=ticker,
            start=start,
            end=end,
            coverage=refreshed,
            source=source,
            warnings=["Stooq daily data downloaded; provider-isolated Parquet cache refreshed."],
            attempts=total_attempts,
        )
        return frame, None

    @staticmethod
    def _coverage_label(value: object) -> str:
        if not isinstance(value, dict):
            return "none"
        return f"{value.get('start') or 'none'} to {value.get('end') or 'none'} ({value.get('bars', 0)} bars)"

    def _error_for_empty(self, ticker: str, start: date, end: date, error: str | None) -> BacktestError:
        metadata = self.last_fetch or {}
        code = metadata.get("provider_error_code") or "NO_DATA"
        if code == "CACHE_INCOMPLETE":
            message = (
                "Market data provider unavailable. "
                f"Ticker: {ticker}. Requested range: {start.isoformat()} to {end.isoformat()}. "
                f"Cached Stooq coverage: {self._coverage_label(metadata.get('cache_coverage'))}. "
                "Unable to download the missing market data."
            )
        elif code == "PROVIDER_TIMEOUT":
            message = f"Stooq data provider timed out while loading daily data for {ticker}."
        elif code == "RATE_LIMITED":
            message = f"Stooq rate limited the daily data request for {ticker}."
        elif code == "PROVIDER_CONNECTION_ERROR":
            message = f"Stooq data provider could not be reached for {ticker}."
        elif code == "INVALID_DATA":
            message = f"Stooq returned invalid daily market data for {ticker}."
        else:
            message = f"No daily historical data found for {ticker} in the requested range."
            code = "NO_DATA"
        details = {
            "data_kind": "daily",
            "ticker": ticker,
            "requested_start": start.isoformat(),
            "requested_end": end.isoformat(),
            "provider": self.provider_key,
            "adjustment_mode": self.adjustment_mode,
            "provider_error": safe_stooq_error(error) if error else metadata.get("provider_error"),
            "provider_error_code": code,
            "cache_coverage": metadata.get("cache_coverage"),
            "cache_last_updated": metadata.get("cache_last_updated"),
        }
        return BacktestError(code, message, details=details)

    def get_market_data(self, ticker: str, start: date, end: date) -> MarketData:
        frame, error = self._download(ticker, start, end)
        if frame.empty:
            raise self._error_for_empty(ticker, start, end, error)
        metadata = dict(self.last_fetch)
        warnings = list(metadata.pop("warnings", []))
        return MarketData(daily=frame, provider=self.provider_key, warnings=warnings, metadata=metadata)

    def get_daily(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        frame, error = self._download(ticker, start, end)
        if frame.empty:
            raise self._error_for_empty(ticker, start, end, error)
        return frame

    def _probe(self) -> tuple[bool, str | None]:
        request = urllib.request.Request(
            _csv_url("SPY", date.today() - timedelta(days=7), date.today()),
            headers={"User-Agent": "BacktestLab/0.1"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.status_timeout_seconds) as response:
                body = response.read(1024 * 1024)
                frame = self._csv_to_frame(body)
                return (not frame.empty), None if not frame.empty else "NO_DATA"
        except urllib.error.HTTPError as exc:
            return False, self._error_code("rate_limited" if exc.code == 429 else "server" if exc.code >= 500 else "upstream", exc.code)
        except (socket.timeout, TimeoutError):
            return False, "PROVIDER_TIMEOUT"
        except Exception:
            return False, "PROVIDER_CONNECTION_ERROR"

    def _mark_offline(self, error_type: str) -> None:
        self._status_snapshot = {
            "provider": self.provider_key,
            "reachable": False,
            "error_type": error_type,
            "status": "offline",
            "cooldown_active": True,
        }
        self._status_checked_at = time.monotonic()

    def status_info(self, *, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if self._status_snapshot is not None and not force and self._status_checked_at is not None:
            age = now - self._status_checked_at
            if age < self.status_cache_seconds or (
                self._status_snapshot.get("status") == "offline" and age < self.offline_cooldown_seconds
            ):
                value = dict(self._status_snapshot)
                value["cooldown_active"] = value.get("status") == "offline" and age < self.offline_cooldown_seconds
                return value
        reachable, error_type = self._probe()
        self._status_snapshot = {
            "provider": self.provider_key,
            "reachable": reachable,
            "error_type": error_type,
            "status": "online" if reachable else "offline",
            "cooldown_active": not reachable,
        }
        self._status_checked_at = now
        return dict(self._status_snapshot)

    def status(self) -> dict[str, Any]:
        return self.status_info(force=True)
