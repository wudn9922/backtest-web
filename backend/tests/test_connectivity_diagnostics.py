from __future__ import annotations

import json
from datetime import date

import pytest

from app.jobs.connectivity import _classify, _parse_fred, write_fred_smoke_cache


@pytest.mark.parametrize(
    ("has_data", "kind", "status_code", "expected"),
    [
        (True, "ok", 200, ("online", None)),
        (False, "rate_limited", 429, ("restricted", "RATE_LIMITED")),
        (False, "server", 503, ("restricted", "UPSTREAM_UNAVAILABLE")),
        (False, "connection", None, ("offline", "PROVIDER_CONNECTION_ERROR")),
        (False, "timeout", None, ("offline", "PROVIDER_TIMEOUT")),
        (False, "upstream", 200, ("validation_failed", "PROVIDER_VALIDATION_FAILED")),
    ],
)
def test_provider_status_classification(has_data, kind, status_code, expected):
    assert _classify(has_data, kind, status_code) == expected


def test_fred_probe_accepts_official_csv_schema_and_rejects_other_content():
    payload = b"observation_date,DGS3MO\n2026-08-31,4.25\n2026-09-01,.\n"
    assert _parse_fred(payload) == 1
    with pytest.raises(ValueError, match="schema"):
        _parse_fred(b"date,value\n2026-08-31,4.25\n")


def test_fred_smoke_cache_contains_only_real_probe_payload(tmp_path, monkeypatch):
    payload = b"observation_date,DGS3MO\n2026-08-31,4.25\n"
    monkeypatch.setattr(
        "app.jobs.connectivity.fetch_fred_sample",
        lambda *_args: (payload, 1, 200),
    )
    result = write_fred_smoke_cache(tmp_path, date(2026, 8, 31), date(2026, 9, 1))
    assert result["fabricated_observations"] == 0
    assert result["cache_written"] and result["manifest_written"]
    manifest = json.loads((tmp_path / "connectivity-smoke" / "risk-free-smoke-manifest.json").read_text(encoding="utf-8"))
    assert manifest["observations"] == 1 and manifest["fabricated_observations"] == 0
