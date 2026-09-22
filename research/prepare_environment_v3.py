"""PowerShell-friendly Environment v3 acquisition/manifest CLI.

Run this from the user's normal Windows environment.  It deliberately does not
fall back across market-data providers: each provider has its own cache root and
its own adjustment contract.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from research import ROOT
from research.environment_v3_data import (
    build_data_manifest, build_universe_manifest, download_market_data,
    download_risk_free,
)
from research.environment_v3_design import (
    ETF_RESEARCH_UNIVERSE, MEGA_CAP_TECH_UNIVERSE, PRIMARY_HISTORY,
)


def write_manifests() -> tuple[dict, dict]:
    market = build_data_manifest()
    universes = build_universe_manifest(market)
    (ROOT / "data/research-data-manifest-v3.json").write_text(
        json.dumps(market, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    (ROOT / "data/research-universes.json").write_text(
        json.dumps(universes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return market, universes


def selected_symbols(name: str) -> tuple[str, ...]:
    if name == "mega":
        return MEGA_CAP_TECH_UNIVERSE
    if name == "etf":
        return ETF_RESEARCH_UNIVERSE
    return tuple(dict.fromkeys((*MEGA_CAP_TECH_UNIVERSE, *ETF_RESEARCH_UNIVERSE)))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Prepare Research Environment Validation v3 inputs")
    parser.add_argument("--mode", choices=("manifest", "market", "risk-free", "all"), default="manifest")
    parser.add_argument("--universe", choices=("mega", "etf", "all"), default="all")
    parser.add_argument("--provider", choices=("yahoo", "stooq"), default="yahoo")
    parser.add_argument("--start", type=date.fromisoformat, default=PRIMARY_HISTORY["start"])
    parser.add_argument("--end", type=date.fromisoformat, default=PRIMARY_HISTORY["end"])
    parser.add_argument("--include-pre-2010", action="store_true", help="Request 2005-01-01 onward where the instrument exists")
    args = parser.parse_args(argv)
    start = date(2005, 1, 1) if args.include_pre_2010 else args.start
    result: dict[str, object] = {"mode": args.mode, "network_requested": args.mode != "manifest"}
    if args.mode in {"market", "all"}:
        result["market_downloads"] = download_market_data(args.provider, selected_symbols(args.universe), start, args.end)
    if args.mode in {"risk-free", "all"}:
        try:
            result["risk_free"] = download_risk_free(start, args.end)
        except RuntimeError as exc:
            result["risk_free"] = {"status": "FAILED", "message": str(exc)}
    market, universes = write_manifests()
    result["manifest"] = {
        "long_history_validation_ready": market["long_history_validation_ready"],
        "universe_readiness": market["universe_readiness"],
        "files": ["data/research-data-manifest-v3.json", "data/research-universes.json"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    failed = any(row.get("status") == "FAILED" for row in result.get("market_downloads", [])) if isinstance(result.get("market_downloads"), list) else False
    if isinstance(result.get("risk_free"), dict) and result["risk_free"].get("status") == "FAILED":
        failed = True
    return 2 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

