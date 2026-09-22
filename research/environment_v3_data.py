"""Provider-separated data acquisition and provenance for Environment v3."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.backtest.models import BacktestError
from app.data.base import normalize_ohlcv, validate_daily_ohlcv
from app.data.cache import ParquetCache
from app.data.stooq import StooqDataProvider
from app.data.yahoo import YahooDataProvider, safe_yahoo_error
from research import ROOT
from research.baseline import digest
from research.environment_v3_design import (
    ETF_RESEARCH_UNIVERSE, MEGA_CAP_TECH_UNIVERSE, PRIMARY_HISTORY, UNIVERSES,
    WARMUP_CONTRACT,
)


DATA_DIR = ROOT / "data"
LEGACY_CACHE = DATA_DIR / "cache"
RESEARCH_CACHE = DATA_DIR / "research-cache"
RATES_DIR = DATA_DIR / "research-rates" / "fred"
FRED_SERIES = "DGS3MO"
FRED_SOURCE = "Federal Reserve Bank of St. Louis FRED"
YAHOO_ADJUSTMENT = "adjusted_for_splits"
YAHOO_ACTUAL_CONTRACT = (
    "Yahoo Adj Close / raw Close factor applied to OHLC; includes Yahoo's "
    "corporate-action adjustment (splits and cash-distribution adjustment); volume unchanged."
)
_CACHE_NAME = re.compile(r"^(?P<ticker>.+)_1d_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.parquet$")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame_hash(frame: pd.DataFrame) -> str:
    return digest([
        {"date": timestamp.date().isoformat(), **{
            name: float(row[name]) for name in ("open", "high", "low", "close", "volume")
        }}
        for timestamp, row in frame.iterrows()
    ])


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _read_sidecar(path: Path) -> dict[str, Any]:
    sidecar = path.with_suffix(path.suffix + ".json")
    try:
        value = json.loads(sidecar.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _candidate_paths(ticker: str) -> list[tuple[Path, str]]:
    roots = [
        (RESEARCH_CACHE / "yahoo", "provider_specific_yahoo"),
        (RESEARCH_CACHE / "stooq", "provider_specific_stooq"),
        (LEGACY_CACHE, "legacy_formal_cache"),
    ]
    output: list[tuple[Path, str]] = []
    safe = ParquetCache.safe_ticker(ticker)
    for root, namespace in roots:
        if root.is_dir():
            output.extend((path, namespace) for path in root.glob(f"{safe}_1d_*.parquet") if path.is_file())
    return sorted(output, key=lambda item: str(item[0]))


def _requested_bounds(path: Path) -> tuple[date | None, date | None]:
    match = _CACHE_NAME.match(path.name)
    if not match:
        return None, None
    try:
        return date.fromisoformat(match.group("start")), date.fromisoformat(match.group("end"))
    except ValueError:
        return None, None


def _dataset_variants(ticker: str) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[tuple[Path, str, dict[str, Any], pd.DataFrame]]] = {}
    rejected: list[dict[str, Any]] = []
    for path, namespace in _candidate_paths(ticker):
        metadata = _read_sidecar(path)
        provider = str(metadata.get("provider") or "unknown").lower()
        adjustment = str(metadata.get("adjustment_mode") or "unknown")
        try:
            frame = normalize_ohlcv(pd.read_parquet(path))
        except Exception as exc:
            rejected.append({"path": _relative(path), "reason": "UNREADABLE_PARQUET", "safe_error": str(exc)[:200]})
            continue
        groups.setdefault((provider, adjustment), []).append((path, namespace, metadata, frame))

    variants: list[dict[str, Any]] = []
    for (provider, adjustment), fragments in sorted(groups.items()):
        ordered = sorted(fragments, key=lambda item: item[0].stat().st_mtime)
        merged = ParquetCache._merge_frames([item[3] for item in ordered], timeframe="1d")
        valid, issue = validate_daily_ohlcv(merged)
        requested_starts, requested_ends = [], []
        for path, *_ in ordered:
            start, end = _requested_bounds(path)
            if start: requested_starts.append(start)
            if end: requested_ends.append(end)
        ratios = merged.close.pct_change().dropna() if valid else pd.Series(dtype=float)
        extreme = int(((ratios <= -.60) | (ratios >= 1.50)).sum()) if len(ratios) else 0
        variants.append({
            "provider": provider,
            "adjustment_mode": adjustment,
            "adjustment_contract": YAHOO_ACTUAL_CONTRACT if provider == "yahoo" else "Provider-native contract; not assumed comparable to Yahoo.",
            "validation": {"status": "PASS" if valid else "FAIL", "issue": issue},
            "split_continuity_diagnostic": {
                "status": "NO_EXTREME_DISCONTINUITY_OBSERVED" if not extreme else "MANUAL_REVIEW_REQUIRED",
                "extreme_adjacent_close_moves": extreme,
                "note": "A continuity diagnostic cannot prove corporate-action correctness; provider provenance remains authoritative.",
            },
            "first_date": merged.index[0].date().isoformat() if len(merged) else None,
            "last_date": merged.index[-1].date().isoformat() if len(merged) else None,
            "bars": int(len(merged)),
            "ohlcv_sha256": frame_hash(merged) if valid else None,
            "earliest_requested_start": min(requested_starts).isoformat() if requested_starts else None,
            "latest_requested_end": max(requested_ends).isoformat() if requested_ends else None,
            "download_timestamp": max(
                (str(item[2].get("last_updated")) for item in ordered if item[2].get("last_updated")),
                default=datetime.fromtimestamp(max(item[0].stat().st_mtime for item in ordered)).astimezone().isoformat(),
            ),
            "fragments": [{
                "path": _relative(path), "namespace": namespace,
                "sha256": sha256_file(path),
                "metadata_sidecar": _relative(path.with_suffix(path.suffix + ".json"))
                if path.with_suffix(path.suffix + ".json").is_file() else None,
                "metadata_sidecar_exists": path.with_suffix(path.suffix + ".json").is_file(),
                "metadata_sidecar_sha256": sha256_file(path.with_suffix(path.suffix + ".json"))
                if path.with_suffix(path.suffix + ".json").is_file() else None,
                "metadata": metadata,
            } for path, namespace, metadata, _frame in ordered],
        })
    if rejected:
        variants.append({"provider": "unknown", "adjustment_mode": "unknown", "validation": {"status": "FAIL", "issue": "Rejected cache fragments"}, "rejected_fragments": rejected})
    return variants


def _primary_variant(variants: list[dict[str, Any]]) -> dict[str, Any] | None:
    matches = [row for row in variants if row.get("provider") == "yahoo" and row.get("adjustment_mode") == YAHOO_ADJUSTMENT and row.get("validation", {}).get("status") == "PASS"]
    return max(matches, key=lambda row: (row.get("bars", 0), row.get("last_date") or ""), default=None)


def build_data_manifest() -> dict[str, Any]:
    symbols = tuple(dict.fromkeys((*MEGA_CAP_TECH_UNIVERSE, *ETF_RESEARCH_UNIVERSE)))
    rows = []
    for ticker in symbols:
        variants = _dataset_variants(ticker)
        selected = _primary_variant(variants)
        requested_start = date.fromisoformat(selected["earliest_requested_start"]) if selected and selected.get("earliest_requested_start") else None
        latest_end = date.fromisoformat(selected["latest_requested_end"]) if selected and selected.get("latest_requested_end") else None
        target_requested = bool(requested_start and requested_start <= PRIMARY_HISTORY["start"] and latest_end and latest_end >= PRIMARY_HISTORY["end"])
        current_through_end = bool(selected and selected.get("last_date") and date.fromisoformat(selected["last_date"]) >= PRIMARY_HISTORY["end"])
        if not selected:
            status = "NO_VALIDATED_YAHOO_CACHE"
        elif target_requested and current_through_end:
            status = "TARGET_REQUEST_COMPLETED; ACTUAL COVERAGE MAY BEGIN AT LISTING"
        else:
            status = "LONG_HISTORY_DOWNLOAD_REQUIRED"
        rows.append({
            "ticker": ticker,
            "status": status,
            "selected_provider": selected.get("provider") if selected else None,
            "selected_adjustment_mode": selected.get("adjustment_mode") if selected else None,
            "first_date": selected.get("first_date") if selected else None,
            "last_date": selected.get("last_date") if selected else None,
            "bars": selected.get("bars", 0) if selected else 0,
            "ohlcv_sha256": selected.get("ohlcv_sha256") if selected else None,
            "download_timestamp": selected.get("download_timestamp") if selected else None,
            "target_range_was_requested": target_requested,
            "variants": variants,
        })

    def universe_readiness(name: str) -> dict[str, Any]:
        symbols = UNIVERSES[name]["symbols"]
        local = [next(row for row in rows if row["ticker"] == ticker) for ticker in symbols]
        ready = all(row["target_range_was_requested"] and row["bars"] > WARMUP_CONTRACT["largest_completed_bar_requirement"] for row in local)
        available = [row for row in local if row["bars"]]
        return {
            "status": "READY" if ready else "NOT_READY",
            "symbols": len(local),
            "validated_datasets": len(available),
            "target_requests_complete": sum(bool(row["target_range_was_requested"]) for row in local),
            "missing_or_short": [row["ticker"] for row in local if not row["target_range_was_requested"]],
            "actual_common_start": max((row["first_date"] for row in available), default=None) if len(available) == len(local) else None,
            "actual_common_end": min((row["last_date"] for row in available), default=None) if len(available) == len(local) else None,
        }

    return {
        "schema_version": 3,
        "generated_at": datetime.now().astimezone().isoformat(),
        "target_range": {key: value.isoformat() for key, value in PRIMARY_HISTORY.items()},
        "provider_specific_cache": {
            "required": True,
            "yahoo": _relative(RESEARCH_CACHE / "yahoo"),
            "stooq": _relative(RESEARCH_CACHE / "stooq"),
            "mixing_rule": "Never merge different provider or adjustment-mode groups within one ticker dataset.",
            "legacy_cache_note": "Existing cache is indexed only when its sidecar explicitly identifies provider and adjustment mode.",
        },
        "adjustment_basis_required": {"provider": "yahoo", "declared_mode": YAHOO_ADJUSTMENT, "actual_contract": YAHOO_ACTUAL_CONTRACT},
        "datasets": rows,
        "universe_readiness": {name: universe_readiness(name) for name in UNIVERSES},
        "long_history_validation_ready": all(universe_readiness(name)["status"] == "READY" for name in UNIVERSES),
        "fabricated_bars": 0,
    }


def build_universe_manifest(data_manifest: dict[str, Any]) -> dict[str, Any]:
    by_ticker = {row["ticker"]: row for row in data_manifest["datasets"]}
    universes = {}
    for name, contract in UNIVERSES.items():
        universes[name] = {
            **contract,
            "symbols": [{
                "ticker": ticker,
                "first_date": by_ticker[ticker]["first_date"],
                "last_date": by_ticker[ticker]["last_date"],
                "bars": by_ticker[ticker]["bars"],
                "coverage_status": by_ticker[ticker]["status"],
            } for ticker in contract["symbols"]],
            "readiness": data_manifest["universe_readiness"][name],
        }
    return {
        "schema_version": 3,
        "universes": universes,
        "pooling_prohibited": True,
        "point_in_time_constituents_available": False,
        "limitation": "Neither list is a historical point-in-time stock universe. ETF diversification reduces but cannot remove selection and survivorship concerns.",
    }


def _fred_url(start: date, end: date) -> str:
    return "https://fred.stlouisfed.org/graph/fredgraph.csv?" + urllib.parse.urlencode({
        "id": FRED_SERIES, "cosd": start.isoformat(), "coed": end.isoformat(),
    })


def _parse_fred_csv(payload: bytes) -> pd.Series:
    text = payload.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ValueError("FRED returned no observations")
    date_key = "observation_date" if "observation_date" in rows[0] else "DATE" if "DATE" in rows[0] else None
    if not date_key or FRED_SERIES not in rows[0]:
        raise ValueError("FRED response columns do not match the frozen DGS3MO contract")
    dates, values = [], []
    for row in rows:
        try:
            value = float(row[FRED_SERIES])
        except (TypeError, ValueError):
            continue
        dates.append(pd.Timestamp(row[date_key], tz="UTC")); values.append(value)
    series = pd.Series(values, index=pd.DatetimeIndex(dates), name="annual_yield_pct", dtype=float).sort_index()
    if series.empty or series.index.has_duplicates or (series <= -100).any() or (series > 100).any():
        raise ValueError("FRED risk-free observations failed validation")
    return series


def download_risk_free(start: date, end: date, *, timeout_seconds=20, retries=3) -> dict[str, Any]:
    """Download a real official series or fail without writing synthetic data."""
    error = None
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(2 ** (attempt - 1))
        try:
            request = urllib.request.Request(_fred_url(start, end), headers={"User-Agent": "BacktestLab-Research/3"})
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                series = _parse_fred_csv(response.read(10 * 1024 * 1024))
            break
        except Exception as exc:
            error = " ".join(str(exc).split())[:300]
    else:
        raise RuntimeError(f"Risk-free download failed; no series or manifest was written: {error}")

    RATES_DIR.mkdir(parents=True, exist_ok=True)
    path = RATES_DIR / f"{FRED_SERIES}_{start.isoformat()}_{end.isoformat()}.parquet"
    series.to_frame().to_parquet(path)
    manifest = {
        "schema_version": 1,
        "provider": FRED_SOURCE,
        "series_id": FRED_SERIES,
        "description": "3-Month Treasury Constant Maturity Rate",
        "units": "annual percent",
        "requested_start": start.isoformat(), "requested_end": end.isoformat(),
        "first_observation": series.index[0].date().isoformat(),
        "last_observation": series.index[-1].date().isoformat(),
        "observations": int(len(series)),
        "download_timestamp": datetime.now(timezone.utc).isoformat(),
        "cache_file": _relative(path), "cache_sha256": sha256_file(path),
        "series_sha256": digest([{"date": ts.date().isoformat(), "annual_yield_pct": float(value)} for ts, value in series.items()]),
        "lookahead_rule": "Observation t becomes usable only after t; each research-session accrual uses the latest observation dated on or before the prior session.",
        "compounding": "ACT/365 effective compounding on cash balance only.",
        "fabricated_observations": 0,
    }
    (DATA_DIR / "risk-free-rate-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def download_market_data(provider_name: str, symbols: tuple[str, ...], start: date, end: date) -> list[dict[str, Any]]:
    """Use one provider-specific cache; never invoke a cross-provider chain."""
    provider_name = provider_name.lower()
    cache_root = RESEARCH_CACHE / provider_name
    if provider_name == "yahoo":
        provider = YahooDataProvider(cache_root)
    elif provider_name == "stooq":
        provider = StooqDataProvider(cache_root)
    else:
        raise ValueError("provider must be yahoo or stooq")
    results = []
    for ticker in symbols:
        try:
            market = provider.get_market_data(ticker, start, end)
            valid, issue = validate_daily_ohlcv(market.daily)
            if not valid:
                raise RuntimeError(issue)
            results.append({"ticker": ticker, "status": "DOWNLOADED", "provider": market.provider, "bars": len(market.daily), "first_date": market.daily.index[0].date().isoformat(), "last_date": market.daily.index[-1].date().isoformat()})
        except BacktestError as exc:
            results.append({"ticker": ticker, "status": "FAILED", "code": exc.code, "message": safe_yahoo_error(exc.message)})
        except Exception as exc:
            results.append({"ticker": ticker, "status": "FAILED", "code": "DOWNLOAD_ERROR", "message": safe_yahoo_error(exc)})
    return results
