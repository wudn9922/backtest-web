"""Research acquisition via the existing providers; never open the history DB.

CLI emits a manifest to stdout. New market cache files use the production cache
writer. Already cached bars, canonical records and audit snapshots are read only.
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
import sys

import pandas as pd

from research import ROOT
from research.baseline import CACHE, digest, immutable_fingerprints
from app.backtest.models import BacktestError
from app.data.base import validate_daily_ohlcv
from app.data.cache import ParquetCache
from app.data.fallback import ProviderChain
from app.data.yahoo import YahooDataProvider
from app.data.stooq import StooqDataProvider

SYMBOLS = ("NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "AVGO", "SPY", "QQQ")
FETCH_START = date(2020, 12, 3)
START = date(2021, 9, 1)
END = date(2026, 9, 1)
MANIFEST = ROOT / "data/first-tp-structural-inputs.json"


def frame_hash(frame):
    return digest([{ "date": ts.date().isoformat(), **{k:float(row[k]) for k in ("open","high","low","close","volume")}}
                   for ts, row in frame.iterrows()])


def admissible(provider, adjustment):
    # The legacy label is imprecise: actual Yahoo code multiplies OHLC by
    # adjusted_close/close (including dividend adjustment). Stooq's native
    # adjustment contract is not verified equivalent and is excluded.
    return provider == "yahoo" and adjustment == "adjusted_for_splits"


def acquire(*, network=False):
    before = immutable_fingerprints()
    root = ROOT / "data/cache"
    existing = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob("*.parquet*") if p.is_file()}
    yahoo, stooq = YahooDataProvider(root), StooqDataProvider(root)
    chain = ProviderChain(yahoo, stooq)
    rows = []; previous_outage = None
    for ticker in SYMBOLS:
        print(f"Data: {ticker}", file=sys.stderr, flush=True)
        row = {"symbol":ticker, "requested_warmup_start":str(FETCH_START), "requested_start":str(START), "requested_end":str(END)}
        try:
            market = chain.get_cached_market_data(ticker, FETCH_START, END)
            if market is None:
                if not network:
                    raise BacktestError("CACHE_UNAVAILABLE", "No complete cached dataset; use --acquire-network to request it.")
                if previous_outage and yahoo.offline_cooldown_active() and stooq.status_info().get("cooldown_active"):
                    raise BacktestError("PROVIDERS_OFFLINE_COOLDOWN", "Both existing providers failed; avoiding repeated requests during their outage cooldown.", details=previous_outage)
                market = chain.get_market_data(ticker, FETCH_START, END)
            frame = market.daily
            cache = yahoo.cache if market.provider == "yahoo" else stooq.cache
            coverage = cache.read_coverage(ticker, "1d", FETCH_START, END)
            paths = coverage.paths
            # Pin NVDA to the exact canonical Parquet instead of a possible
            # newer overlapping cache fragment. Do not refresh or rewrite it.
            if ticker == "NVDA":
                canonical = pd.read_parquet(CACHE)
                row["canonical_vs_merged_cache_equal"] = frame_hash(frame) == frame_hash(canonical)
                frame, paths = canonical, [CACHE]
            valid, issue = validate_daily_ohlcv(frame)
            if not valid:
                raise BacktestError("INVALID_DATA", str(issue))
            sidecars = [cache.read_metadata(p) for p in paths]
            adjustment = market.metadata.get("adjustment_mode")
            consistent = admissible(market.provider, adjustment) and all(
                m.get("provider") == market.provider and m.get("adjustment_mode") == adjustment for m in sidecars)
            period = frame.loc[[START <= ts.date() <= END for ts in frame.index]]
            row.update(status="included" if consistent else "excluded_adjustment_basis", provider=market.provider,
                       adjustment_mode=adjustment,
                       actual_adjustment_contract="Yahoo adjusted_close / close applied to OHLC; volume unchanged" if market.provider=="yahoo" else "Unverified provider-native adjustment",
                       first_date=frame.index[0].date().isoformat(), last_date=frame.index[-1].date().isoformat(),
                       bars=len(frame), period_bars=len(period), warmup_bars=sum(ts.date()<START for ts in frame.index),
                       first_strategy_date=period.index[0].date().isoformat() if len(period) else None,
                       last_strategy_date=period.index[-1].date().isoformat() if len(period) else None,
                       ohlcv_sha256=frame_hash(frame), cache_metadata=sidecars,
                       paths=[p.relative_to(ROOT).as_posix() for p in paths],
                       file_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                       metadata=market.metadata, warnings=market.warnings,
                       exclusion_reason=None if consistent else "Provider/adjustment provenance differs from canonical Yahoo; unsafe to pool.")
        except BacktestError as exc:
            row.update(status="unavailable", provider=None, adjustment_mode=None, bars=0, period_bars=0,
                       error_code=exc.code, error=exc.message, details=exc.details)
            if exc.code == "MARKET_DATA_PROVIDERS_UNAVAILABLE":
                previous_outage = exc.details
        rows.append(row)
    after = immutable_fingerprints()
    assert before == after
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==sha for p,sha in existing.items())
    return {"schema_version":1,"network_requested":network,"symbols":rows,
            "existing_cache_unchanged":True,"immutability":{"before":before,"after":after,"unchanged":True}}


def load_inputs():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    frames = {}
    for row in manifest["symbols"]:
        if row["status"] != "included":
            continue
        for p, sha in row["file_sha256"].items():
            if hashlib.sha256((ROOT/p).read_bytes()).hexdigest() != sha:
                raise ValueError(f"Frozen research data changed: {row['symbol']}")
        frame = pd.read_parquet(ROOT/row["paths"][0]) if len(row["paths"])==1 else ParquetCache._merge_frames(
            [pd.read_parquet(ROOT/p) for p in row["paths"]], timeframe="1d")
        frame = frame.loc[[FETCH_START <= ts.date() <= END for ts in frame.index]]
        assert frame_hash(frame) == row["ohlcv_sha256"]
        frames[row["symbol"]] = frame
    return manifest, frames


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(acquire(network="--acquire-network" in sys.argv), ensure_ascii=False, default=str, allow_nan=False))
