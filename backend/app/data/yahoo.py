from __future__ import annotations

import json
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
import yfinance as yf

from app.backtest.models import BacktestError
from app.data.base import DataProvider, MarketData, normalize_ohlcv, validate_daily_ohlcv
from app.data.cache import CacheCoverage, ParquetCache


EMPTY_COLUMNS = ["open", "high", "low", "close", "volume"]
YAHOO_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")


def safe_yahoo_error(error: object) -> str:
    """Return a short display-safe upstream message without URLs or local paths."""
    message = " ".join(str(error).split()) or "Yahoo returned no additional error message."
    message = re.sub(r"https?://\S+", "[URL omitted]", message, flags=re.IGNORECASE)
    message = re.sub(r"(?:[A-Za-z]:\\|/)(?:[^\s:]+[/\\]){2,}[^\s:]*", "[path omitted]", message)
    # Do not send proxy credentials, cookies or request headers to the browser.
    message = re.sub(r"(?i)(password|passwd|token|secret|authorization|cookie)\s*[=:]\s*[^\s,;]+", r"\1=[redacted]", message)
    return message[:500]


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=EMPTY_COLUMNS)


def _chart_url(host: str, ticker: str, start: date, end: date) -> str:
    # Yahoo's chart endpoint uses an exclusive period2.  Adding one day keeps
    # the user's end date inclusive while still requesting daily bars only.
    period1 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
    end_exclusive = end + timedelta(days=1)
    period2 = int(datetime(end_exclusive.year, end_exclusive.month, end_exclusive.day, tzinfo=timezone.utc).timestamp())
    symbol = urllib.parse.quote(ticker, safe=".^=-")
    query = urllib.parse.urlencode({
        "period1": period1,
        "period2": period2,
        "interval": "1d",
        "events": "div,splits",
        "includeAdjustedClose": "true",
    })
    return f"https://{host}/v8/finance/chart/{symbol}?{query}"


def _chart_worker(connection, url: str, request_timeout: int) -> None:
    """Fetch one Yahoo chart request in an isolated process.

    A child process prevents an SSL/proxy library stuck in DNS or socket setup
    from blocking the FastAPI worker beyond the configured hard timeout.
    """
    try:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "BacktestLab/0.1 (+daily-data-provider)",
            },
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=request_timeout) as response:
            status = int(getattr(response, "status", 200) or 200)
            payload = json.loads(response.read().decode("utf-8"))
        chart = payload.get("chart") if isinstance(payload, dict) else None
        if not isinstance(chart, dict):
            connection.send((None, "Yahoo returned an invalid chart response.", "upstream", status))
        elif chart.get("error"):
            error = chart["error"]
            if isinstance(error, dict):
                message = error.get("description") or error.get("code") or "Yahoo returned an upstream error."
            else:
                message = error
            text = str(message).lower()
            kind = "no_data" if any(token in text for token in ("not found", "no data", "delisted", "invalid symbol")) else "upstream"
            connection.send((None, safe_yahoo_error(message), kind, status))
        elif not chart.get("result"):
            connection.send((None, "Yahoo returned no chart result for this ticker and date range.", "no_data", status))
        else:
            connection.send((payload, None, "ok", status))
    except urllib.error.HTTPError as exc:
        # HTTPError is also a file-like response; avoid reading an unbounded
        # error body and keep only the safe status/reason text.
        kind = "rate_limited" if exc.code == 429 else "server" if exc.code >= 500 else "upstream"
        connection.send((None, safe_yahoo_error(f"HTTP {exc.code}: {exc.reason}"), kind, int(exc.code)))
    except (socket.timeout, TimeoutError):
        connection.send((None, "Yahoo request timed out.", "timeout", None))
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        connection.send((None, safe_yahoo_error(f"Yahoo connection error: {reason}"), "connection", None))
    except Exception as exc:  # pragma: no cover - exercised through parent result
        connection.send((None, safe_yahoo_error(exc), "connection", None))
    finally:
        connection.close()


@dataclass
class _RemoteFailure:
    code: str
    message: str
    host_errors: list[str]
    hosts_attempted: list[str]


class YahooDataProvider(DataProvider):
    """Yahoo daily OHLCV provider with cache-first, resilient host fallback."""

    provider_key = "yahoo"
    display_name = "Yahoo Finance"
    adjustment_mode = "adjusted_for_splits"

    def __init__(self, cache_dir: Path | None = None):
        self.cache = ParquetCache(cache_dir or Path("../data/cache"))
        self.yfinance_cache = self.cache.root / ".yfinance"
        self.yfinance_cache.mkdir(parents=True, exist_ok=True)
        # Keep yfinance's cache location configured for compatibility with old
        # installations and saved cache layouts.  Daily requests themselves use
        # the Yahoo chart endpoint so query1/query2 fallback is deterministic.
        try:
            yf.set_tz_cache_location(str(self.yfinance_cache))
        except Exception:
            pass
        self.hard_timeout_seconds = max(5, int(os.getenv("YAHOO_REQUEST_TIMEOUT_SECONDS", "20")))
        self.max_retries = max(0, min(5, int(os.getenv("YAHOO_MAX_RETRIES", "3"))))
        self.retry_backoff_seconds = max(0.1, float(os.getenv("YAHOO_RETRY_BACKOFF_SECONDS", "1")))
        self.status_timeout_seconds = max(1, min(10, int(os.getenv("YAHOO_STATUS_TIMEOUT_SECONDS", "3"))))
        self.offline_cooldown_seconds = max(30, int(os.getenv("YAHOO_OFFLINE_COOLDOWN_SECONDS", "300")))
        self.status_cache_seconds = max(5, int(os.getenv("YAHOO_STATUS_CACHE_SECONDS", "60")))
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
        if status in {400, 404}:
            return "NO_DATA"
        if kind == "no_data":
            return "NO_DATA"
        return "PROVIDER_CONNECTION_ERROR"

    @staticmethod
    def _coverage_dict(coverage: CacheCoverage) -> dict[str, Any]:
        value = coverage.as_dict()
        value["complete"] = coverage.complete
        value["missing_ranges"] = [
            {"start": start.isoformat(), "end": end.isoformat()}
            for start, end in coverage.missing_ranges
        ]
        return value

    def _run_request(self, host: str, ticker: str, start: date, end: date) -> tuple[pd.DataFrame, str | None, str, int | None]:
        url = _chart_url(host, ticker, start, end)
        context = mp.get_context("spawn")
        parent_connection, child_connection = context.Pipe(duplex=False)
        process = context.Process(
            target=_chart_worker,
            args=(child_connection, url, min(10, self.hard_timeout_seconds)),
            daemon=True,
        )
        process.start()
        child_connection.close()
        try:
            if parent_connection.poll(self.hard_timeout_seconds):
                try:
                    payload, error, kind, status = parent_connection.recv()
                except EOFError:
                    payload, error, kind, status = None, f"Yahoo data process exited without a result (exit code {process.exitcode}).", "connection", None
            else:
                payload, error, kind, status = None, f"Yahoo request timed out after {self.hard_timeout_seconds} seconds.", "timeout", None
        finally:
            if process.is_alive():
                process.terminate()
            process.join(2)
            parent_connection.close()
        if payload is None:
            return _empty_frame(), safe_yahoo_error(error), kind, status
        try:
            return self._chart_to_frame(payload), None, kind, status
        except Exception as exc:
            return _empty_frame(), safe_yahoo_error(f"Yahoo response parsing failed: {exc}"), "upstream", status

    @staticmethod
    def _chart_to_frame(payload: dict[str, Any]) -> pd.DataFrame:
        chart = payload.get("chart", {})
        result = (chart.get("result") or [None])[0]
        if not isinstance(result, dict):
            return _empty_frame()
        timestamps = result.get("timestamp") or []
        quote_rows = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        adj_rows = ((result.get("indicators") or {}).get("adjclose") or [{}])[0]
        adjusted_close = adj_rows.get("adjclose") if isinstance(adj_rows, dict) else None
        records: list[dict[str, Any]] = []
        for index, timestamp in enumerate(timestamps):
            row = {name: (quote_rows.get(name) or [None] * len(timestamps))[index] for name in EMPTY_COLUMNS}
            # Chart's adjusted close allows OHLC to remain split-consistent like
            # yfinance auto_adjust=True while volume remains unadjusted.
            raw_close = row.get("close")
            adjusted = adjusted_close[index] if adjusted_close and index < len(adjusted_close) else None
            if raw_close not in (None, 0) and adjusted is not None:
                factor = float(adjusted) / float(raw_close)
                for name in ["open", "high", "low", "close"]:
                    if row[name] is not None:
                        row[name] = float(row[name]) * factor
            records.append({"timestamp": pd.to_datetime(timestamp, unit="s", utc=True), **row})
        if not records:
            return _empty_frame()
        frame = pd.DataFrame.from_records(records).set_index("timestamp")
        return normalize_ohlcv(frame)

    def _download_remote(self, ticker: str, start: date, end: date) -> tuple[pd.DataFrame, _RemoteFailure | None]:
        host_errors: list[str] = []
        hosts_attempted: list[str] = []
        last_code = "PROVIDER_CONNECTION_ERROR"
        # One initial pass plus at most max_retries retries.  Backoff is 1, 2,
        # 4 seconds by default and is never unbounded.
        for attempt in range(self.max_retries + 1):
            if attempt:
                time.sleep(self.retry_backoff_seconds * (2 ** (attempt - 1)))
            retryable_failure_seen = False
            for host in YAHOO_HOSTS:
                hosts_attempted.append(host)
                frame, error, kind, status = self._run_request(host, ticker, start, end)
                if not frame.empty:
                    return frame, None
                safe_error = safe_yahoo_error(error or "Yahoo returned no daily bars.")
                host_errors.append(f"{host}: {safe_error}")
                last_code = self._error_code(kind, status)
                retryable_failure_seen = retryable_failure_seen or kind in {"connection", "timeout", "rate_limited", "server"}
                # A valid no-data/upstream response is still tried on the second
                # hostname, but does not consume an unbounded retry loop.
            if not retryable_failure_seen:
                break
            # All hosts failed this pass.  Retry only the finite number configured.
        failure = _RemoteFailure(
            code=last_code,
            message="; ".join(host_errors[-len(YAHOO_HOSTS) * (self.max_retries + 1):])[:1000],
            host_errors=host_errors,
            hosts_attempted=hosts_attempted,
        )
        if failure.code in {"PROVIDER_CONNECTION_ERROR", "PROVIDER_TIMEOUT", "RATE_LIMITED"}:
            self._mark_offline(failure.code)
        return _empty_frame(), failure

    def _set_fetch_metadata(self, *, ticker: str, start: date, end: date, coverage: CacheCoverage, source: str,
                            yahoo_error: str | None = None, error_code: str | None = None,
                            hosts_attempted: list[str] | None = None, warnings: list[str] | None = None) -> None:
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
            "cache_available": coverage.available,
            "cache_complete": coverage.complete,
            "cache_coverage": cache_info,
            "cache_last_updated": cache_info.get("last_updated"),
            "cache_metadata": cache_metadata,
            "yahoo_error": yahoo_error,
            "provider_error_code": error_code,
            "yahoo_hosts_attempted": hosts_attempted or [],
            "warnings": warnings or [],
        }

    def get_cached_market_data(self, ticker: str, start: date, end: date) -> MarketData | None:
        """Read a complete Yahoo cache fragment without probing the network."""
        coverage = self.cache.read_coverage(ticker, "1d", start, end)
        if not coverage.complete:
            return None
        # A cache directory may contain files created before provenance
        # sidecars were introduced.  Missing metadata is tolerated and is
        # backfilled below, but an explicit provider/adjustment mismatch must
        # never be silently consumed as Yahoo data.
        for path in coverage.paths:
            metadata = self.cache.read_metadata(path)
            cached_provider = metadata.get("provider")
            cached_adjustment = metadata.get("adjustment_mode")
            if cached_provider and cached_provider != self.provider_key:
                return None
            if cached_adjustment and cached_adjustment != self.adjustment_mode:
                return None
        frame = normalize_ohlcv(coverage.frame)
        valid, issue = validate_daily_ohlcv(frame)
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
        warning = (
            "Using cached Yahoo daily data; Yahoo was not queried. "
            f"Cache last updated: {coverage.last_updated.isoformat() if coverage.last_updated else 'unknown'}."
        )
        self._set_fetch_metadata(
            ticker=ticker,
            start=start,
            end=end,
            coverage=coverage,
            source="cache",
            warnings=[warning],
        )
        metadata = dict(self.last_fetch)
        warnings = list(metadata.pop("warnings", []))
        metadata["cache_validation"] = "ok"
        return MarketData(daily=frame, provider=self.provider_key, warnings=warnings, metadata=metadata)

    def _download(self, ticker: str, start: date, end: date, interval: str) -> tuple[pd.DataFrame, str | None]:
        if interval != "1d":
            # Daily-only mode deliberately does not call Yahoo intraday APIs.
            coverage = self.cache.read_coverage(ticker, interval, start, end)
            self._set_fetch_metadata(ticker=ticker, start=start, end=end, coverage=coverage, source="unsupported")
            return _empty_frame(), "Only daily OHLC data is supported by this provider."

        coverage = self.cache.read_coverage(ticker, interval, start, end)
        # Cache-first is strict: complete coverage does not make a network call.
        if coverage.complete:
            frame = normalize_ohlcv(coverage.frame)
            valid, issue = validate_daily_ohlcv(frame)
            if not valid:
                self._set_fetch_metadata(
                    ticker=ticker,
                    start=start,
                    end=end,
                    coverage=coverage,
                    source="cache_invalid",
                    yahoo_error=f"Cached Yahoo data failed validation: {issue}",
                    error_code="INVALID_DATA",
                )
                return _empty_frame(), f"Cached Yahoo data failed validation: {issue}"
            self._set_fetch_metadata(
                ticker=ticker,
                start=start,
                end=end,
                coverage=coverage,
                source="cache",
                warnings=[
                    "Using cached market data (cache-first); Yahoo was not queried. "
                    f"Cache last updated: {coverage.last_updated.isoformat() if coverage.last_updated else 'unknown'}."
                ],
            )
            return frame, None

        combined = coverage.frame.copy()
        missing_ranges = coverage.missing_ranges or [(start, end)]
        failures: list[_RemoteFailure] = []
        all_hosts: list[str] = []
        fetched_any = False
        for missing_start, missing_end in missing_ranges:
            remote, failure = self._download_remote(ticker, missing_start, missing_end)
            if failure is not None:
                failures.append(failure)
                all_hosts.extend(failure.hosts_attempted)
                break
            fetched_any = True
            if not remote.empty:
                combined = remote.copy() if combined.empty else pd.concat([combined, remote], axis=0, sort=False)

        if failures:
            failure = failures[0]
            # A partial cache is useful for diagnostics but must never be used as
            # a silently truncated backtest.  Only complete coverage may fall back.
            self._set_fetch_metadata(
                ticker=ticker,
                start=start,
                end=end,
                coverage=coverage,
                source="cache_incomplete",
                yahoo_error=failure.message,
                error_code="CACHE_INCOMPLETE" if coverage.available else failure.code,
                hosts_attempted=all_hosts,
            )
            # Do not hand a partial frame to the engine: that would silently
            # shorten the requested backtest.  The safe error below includes the
            # partial cache coverage so the user can decide how to proceed.
            return _empty_frame(), failure.message

        frame = normalize_ohlcv(combined)
        if frame.empty:
            failure = _RemoteFailure("NO_DATA", "Yahoo returned no daily bars for this ticker and date range.", all_hosts, all_hosts)
            self._set_fetch_metadata(ticker=ticker, start=start, end=end, coverage=coverage, source="yahoo", yahoo_error=failure.message, error_code=failure.code, hosts_attempted=all_hosts)
            return _empty_frame(), failure.message
        valid, issue = validate_daily_ohlcv(frame)
        if not valid:
            failure = _RemoteFailure("INVALID_DATA", f"Yahoo daily data failed validation: {issue}", all_hosts, all_hosts)
            self._set_fetch_metadata(
                ticker=ticker,
                start=start,
                end=end,
                coverage=coverage,
                source="invalid",
                yahoo_error=failure.message,
                error_code=failure.code,
                hosts_attempted=all_hosts,
            )
            return _empty_frame(), failure.message
        # Save the requested merged range as a new canonical fragment.  Existing
        # fragments remain untouched, so a failed refresh cannot destroy data.
        self.cache.write(
            ticker,
            interval,
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
        refreshed = self.cache.read_coverage(ticker, interval, start, end)
        source = "yahoo+cache" if coverage.available else "yahoo"
        self._set_fetch_metadata(
            ticker=ticker,
            start=start,
            end=end,
            coverage=refreshed,
            source=source,
            warnings=["Yahoo daily data downloaded; local Parquet cache refreshed."] if fetched_any else [],
            hosts_attempted=all_hosts,
        )
        return frame, None

    def _error_for_empty(self, ticker: str, start: date, end: date, error: str | None) -> BacktestError:
        metadata = self.last_fetch or {}
        # Preserve the small public compatibility contract used by callers that
        # replace ``_download`` in tests or custom integrations.  Normal Yahoo
        # requests always populate ``last_fetch`` and use the richer error codes
        # below.
        if not metadata:
            return BacktestError(
                "YAHOO_DAILY_DATA_UNAVAILABLE",
                f"Yahoo daily data is unavailable for {ticker}. Check the ticker and requested dates.",
                details={"data_kind": "daily", "yahoo_error": safe_yahoo_error(error) if error else None},
            )
        code = metadata.get("provider_error_code") or "NO_DATA"
        if code == "CACHE_INCOMPLETE":
            message = (
                "Market data provider unavailable. "
                f"Ticker: {ticker}. Requested range: {start.isoformat()} to {end.isoformat()}. "
                f"Cached coverage: {self._coverage_label(metadata.get('cache_coverage'))}. "
                "Yahoo connection failed. Unable to download the missing market data."
            )
        elif code == "PROVIDER_TIMEOUT":
            message = f"Yahoo data provider timed out while loading daily data for {ticker}. Please retry later."
        elif code == "RATE_LIMITED":
            message = f"Yahoo rate limited the daily data request for {ticker}. Please wait and retry later."
        elif code == "PROVIDER_CONNECTION_ERROR":
            message = f"Market data provider unavailable for {ticker}. Yahoo could not be reached."
        elif code == "INVALID_DATA":
            message = f"Yahoo returned invalid daily market data for {ticker}."
        else:
            message = f"No daily historical data found for {ticker} in the requested range."
            code = "NO_DATA"
        details = {
            "data_kind": "daily",
            "ticker": ticker,
            "requested_start": start.isoformat(),
            "requested_end": end.isoformat(),
            "execution_timeframe": "daily",
            "yahoo_error": safe_yahoo_error(error) if error else metadata.get("yahoo_error"),
            "cache_coverage": metadata.get("cache_coverage"),
            "cache_last_updated": metadata.get("cache_last_updated"),
            "yahoo_hosts_attempted": metadata.get("yahoo_hosts_attempted", []),
            "provider_error_code": code,
            "provider": self.provider_key,
            "adjustment_mode": self.adjustment_mode,
        }
        return BacktestError(code, message, details=details)

    @staticmethod
    def _coverage_label(value: object) -> str:
        if not isinstance(value, dict):
            return "none"
        start, end = value.get("start"), value.get("end")
        bars = value.get("bars", 0)
        return f"{start or 'none'} to {end or 'none'} ({bars} bars)"

    def get_market_data(self, ticker: str, start: date, end: date) -> MarketData:
        frame, yahoo_error = self._download(ticker, start, end, "1d")
        metadata = dict(self.last_fetch)
        if frame.empty:
            raise self._error_for_empty(ticker, start, end, yahoo_error)
        warnings = list(metadata.pop("warnings", []))
        metadata.setdefault("provider", self.provider_key)
        metadata.setdefault("adjustment_mode", self.adjustment_mode)
        return MarketData(daily=frame, provider=self.provider_key, warnings=warnings, metadata=metadata)

    def get_daily(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        frame, yahoo_error = self._download(ticker, start, end, "1d")
        if frame.empty:
            raise self._error_for_empty(ticker, start, end, yahoo_error)
        return frame

    def _probe_host(self, host: str) -> bool:
        # Status probes are deliberately tiny and do not expose their error text.
        url = _chart_url(host, "SPY", date.today() - timedelta(days=3), date.today())
        request = urllib.request.Request(url, headers={"User-Agent": "BacktestLab/0.1"}, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.status_timeout_seconds) as response:
                if int(getattr(response, "status", 200) or 200) >= 400:
                    return False
                payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
                return bool((payload.get("chart") or {}).get("result"))
        except Exception:
            return False

    def _mark_offline(self, error_type: str) -> None:
        """Remember an outage so every backtest does not repeat long retries."""
        self._status_snapshot = {
            "provider": self.provider_key,
            "reachable": False,
            "error_type": error_type,
            "query1_reachable": False,
            "query2_reachable": False,
            "status": "offline",
            "cooldown_active": True,
        }
        self._status_checked_at = time.monotonic()

    def _mark_online(self, query1: bool, query2: bool) -> dict[str, Any]:
        state = "online" if query1 and query2 else "degraded" if query1 or query2 else "offline"
        error_type = None if state != "offline" else "PROVIDER_CONNECTION_ERROR"
        self._status_snapshot = {
            "provider": self.provider_key,
            "reachable": bool(query1 or query2),
            "error_type": error_type,
            "query1_reachable": query1,
            "query2_reachable": query2,
            "status": state,
            "cooldown_active": state == "offline",
        }
        self._status_checked_at = time.monotonic()
        return dict(self._status_snapshot)

    def offline_cooldown_active(self) -> bool:
        if not self._status_snapshot or self._status_snapshot.get("status") != "offline":
            return False
        checked = self._status_checked_at or 0.0
        active = time.monotonic() - checked < self.offline_cooldown_seconds
        self._status_snapshot["cooldown_active"] = active
        return active

    def status_info(self, *, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if self._status_snapshot is not None and not force and self._status_checked_at is not None:
            age = now - self._status_checked_at
            if age < self.status_cache_seconds or self.offline_cooldown_active():
                result = dict(self._status_snapshot)
                result["cooldown_active"] = self.offline_cooldown_active()
                return result
        query1 = self._probe_host(YAHOO_HOSTS[0])
        query2 = self._probe_host(YAHOO_HOSTS[1])
        return self._mark_online(query1, query2)

    def status(self) -> dict[str, Any]:
        # Preserve the small direct-provider compatibility shape used by older
        # integrations.  The application endpoint exposes the richer provider
        # chain shape from ``status_info`` instead.
        info = self.status_info(force=True)
        return {
            "provider": self.provider_key,
            "query1_reachable": bool(info.get("query1_reachable")),
            "query2_reachable": bool(info.get("query2_reachable")),
            "cache_available": bool(any(self.cache.root.glob("*_1d_*.parquet"))),
            "status": info.get("status", "offline"),
        }
