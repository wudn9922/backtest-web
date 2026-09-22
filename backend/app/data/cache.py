from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class CacheCoverage:
    """A merged view of the local files relevant to one request.

    Cache files are intentionally allowed to have different ranges (for example,
    a warm-up file and a later refresh).  The provider uses this object to avoid
    downloading a range that is already present and to report an incomplete
    cache safely when an upstream provider is unavailable.
    """

    frame: pd.DataFrame
    paths: list[Path]
    requested_start: date
    requested_end: date
    coverage_start: date | None
    coverage_end: date | None
    missing_ranges: list[tuple[date, date]]
    last_updated: datetime | None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return not self.missing_ranges and self.coverage_start is not None and self.coverage_end is not None

    @property
    def available(self) -> bool:
        return not self.frame.empty

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.coverage_start.isoformat() if self.coverage_start else None,
            "end": self.coverage_end.isoformat() if self.coverage_end else None,
            "bars": int(len(self.frame)),
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }


class ParquetCache:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def safe_ticker(ticker: str) -> str:
        return ticker.replace("/", "_").replace("^", "_")

    def path(self, ticker: str, timeframe: str, start: date, end: date) -> Path:
        safe = self.safe_ticker(ticker)
        return self.root / f"{safe}_{timeframe}_{start.isoformat()}_{end.isoformat()}.parquet"

    @staticmethod
    def metadata_path(path: Path) -> Path:
        """Sidecar path for provider/adjustment provenance metadata."""
        return path.with_suffix(path.suffix + ".json")

    def read(self, ticker: str, timeframe: str, start: date, end: date) -> pd.DataFrame | None:
        path = self.path(ticker, timeframe, start, end)
        return pd.read_parquet(path) if path.exists() else None

    def write(
        self,
        ticker: str,
        timeframe: str,
        start: date,
        end: date,
        frame: pd.DataFrame,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path(ticker, timeframe, start, end)
        frame.to_parquet(path)
        if metadata is not None:
            self.write_metadata(path, metadata)

    def write_metadata(self, path: Path, metadata: dict[str, Any]) -> None:
        """Write an informational JSON sidecar without touching Parquet data."""
        # Sidecars are informational only.  Never fail a successful data fetch
        # because a non-critical metadata value is not serializable.
        safe_metadata: dict[str, Any]
        try:
            safe_metadata = json.loads(json.dumps(metadata, ensure_ascii=False, default=str))
        except Exception:
            safe_metadata = {"provider": metadata.get("provider"), "adjustment_mode": metadata.get("adjustment_mode")}
        try:
            self.metadata_path(path).write_text(
                json.dumps(safe_metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def read_metadata(self, path: Path) -> dict[str, Any]:
        """Read a cache sidecar, returning an empty mapping when absent/bad."""
        sidecar = self.metadata_path(path)
        if not sidecar.exists():
            return {}
        try:
            value = json.loads(sidecar.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def _candidate_paths(self, ticker: str, timeframe: str) -> list[Path]:
        """Find all cache fragments for a ticker/timeframe.

        The filename format is controlled by this application, and the ticker is
        validated before a request reaches the provider.  We still use an exact
        prefix and only return files to prevent arbitrary path traversal.
        """
        prefix = f"{self.safe_ticker(ticker)}_{timeframe}_"
        return sorted(
            path for path in self.root.glob(f"{prefix}*.parquet")
            if path.is_file() and path.name.startswith(prefix)
        )

    @staticmethod
    def _normalise_frame(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame
        out = frame.copy()
        index = pd.DatetimeIndex(out.index)
        if index.tz is None:
            index = index.tz_localize("UTC")
        else:
            index = index.tz_convert("UTC")
        out.index = index
        out.index.name = "timestamp"
        return out.sort_index()

    @staticmethod
    def _merge_frames(frames: list[pd.DataFrame], timeframe: str | None = None) -> pd.DataFrame:
        non_empty = [ParquetCache._normalise_frame(frame) for frame in frames if frame is not None and not frame.empty]
        if not non_empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        merged = pd.concat(non_empty, axis=0, sort=False)
        if timeframe == "1d":
            # Older cache fragments may use exchange-local midnight while newer
            # fragments use UTC midnight.  Timestamp deduplication alone would
            # treat those as two bars for one trading date and break the engine's
            # unique-index invariant.  Keep one row per calendar trading date.
            dates = pd.Series(merged.index.date, index=merged.index)
            merged = merged.assign(_cache_trading_date=dates.to_numpy())
            merged = merged[~merged["_cache_trading_date"].duplicated(keep="last")].drop(columns=["_cache_trading_date"])
        else:
            merged = merged[~merged.index.duplicated(keep="last")]
        merged = merged.sort_index()
        return merged

    @staticmethod
    def _missing_ranges(frame: pd.DataFrame, start: date, end: date) -> list[tuple[date, date]]:
        """Return only clear leading/trailing or multi-week internal gaps.

        Exchange holidays make a strict business-day calendar unreliable without
        an exchange calendar dependency.  Bounds are therefore the authoritative
        completeness check, while an internal gap larger than seven calendar days
        is treated as a missing fragment and fetched explicitly.
        """
        if start > end:
            return []
        if frame.empty:
            return [(start, end)]
        available = [timestamp.date() for timestamp in pd.DatetimeIndex(frame.index)]
        first, last = min(available), max(available)
        missing: list[tuple[date, date]] = []
        # A request may begin/end on a weekend or a short exchange holiday.  Do
        # not mistake those non-trading days for an incomplete cache; a gap of
        # more than a week is a reliable signal that a market-data fragment is
        # actually missing.
        if first > start and (first - start).days > 7:
            missing.append((start, first - timedelta(days=1)))
        if last < end and (end - last).days > 7:
            missing.append((last + timedelta(days=1), end))
        for previous, current in zip(available, available[1:]):
            if (current - previous).days > 7:
                missing.append((previous + timedelta(days=1), current - timedelta(days=1)))
        return missing

    def read_coverage(self, ticker: str, timeframe: str, start: date, end: date) -> CacheCoverage:
        paths = self._candidate_paths(ticker, timeframe)
        frames: list[pd.DataFrame] = []
        used_paths: list[Path] = []
        for path in paths:
            try:
                frame = pd.read_parquet(path)
            except Exception:
                # A corrupt fragment must not crash a request.  The provider can
                # attempt to refresh it or report an incomplete cache instead.
                continue
            if frame is None or frame.empty:
                continue
            normalised = self._normalise_frame(frame)
            if normalised.empty:
                continue
            dates = normalised.index.date
            if dates.max() >= start and dates.min() <= end:
                frames.append(normalised)
                used_paths.append(path)
        # Newer fragments win when overlapping daily data has different timezone
        # representations.  This keeps a refresh deterministic while retaining
        # older files for dates that were not refreshed.
        if timeframe == "1d" and used_paths:
            ordered = sorted(zip(used_paths, frames), key=lambda item: item[0].stat().st_mtime)
            used_paths, frames = [item[0] for item in ordered], [item[1] for item in ordered]
        merged = self._merge_frames(frames, timeframe=timeframe)
        if not merged.empty:
            requested = merged[(merged.index.date >= start) & (merged.index.date <= end)]
            coverage_start = min(ts.date() for ts in merged.index)
            coverage_end = max(ts.date() for ts in merged.index)
        else:
            requested = merged
            coverage_start = None
            coverage_end = None
        # Only the requested slice is returned to callers.  Coverage bounds use
        # the merged fragments so warm-up requests can be joined safely.
        missing = self._missing_ranges(requested, start, end)
        latest = max((path.stat().st_mtime for path in used_paths), default=None)
        last_updated = datetime.fromtimestamp(latest).astimezone() if latest is not None else None
        sidecar_metadata: dict[str, Any] = {}
        for path in used_paths:
            value = self.read_metadata(path)
            if value:
                sidecar_metadata.update(value)
        return CacheCoverage(
            frame=requested,
            paths=used_paths,
            requested_start=start,
            requested_end=end,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            missing_ranges=missing,
            last_updated=last_updated,
            metadata=sidecar_metadata,
        )

    def has_any(self, ticker: str, timeframe: str = "1d") -> bool:
        return bool(self._candidate_paths(ticker, timeframe))

    def describe(self, ticker: str, timeframe: str = "1d") -> dict[str, Any]:
        paths = self._candidate_paths(ticker, timeframe)
        coverage = self.read_coverage(ticker, timeframe, date.min, date.max) if paths else None
        if coverage is None or not coverage.available:
            return {"available": False, "start": None, "end": None, "bars": 0, "last_updated": None}
        return {"available": True, **coverage.as_dict()}
