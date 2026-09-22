"""Run the production API path against five years of daily provider data."""

from __future__ import annotations

import argparse
import json
from time import perf_counter

from fastapi.testclient import TestClient

from app.main import app


START_DATE = "2021-09-01"
END_DATE = "2026-09-01"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tickers", nargs="*", default=["NVDA", "AAPL", "SPY"])
    parser.add_argument("--strategy", choices=["advanced", "advanced_day1_stop"], default="advanced")
    args = parser.parse_args()
    with TestClient(app) as client:
        tickers = tuple(item.upper() for item in args.tickers)
        for ticker in tickers:
            started = perf_counter()
            response = client.post(
                "/api/backtests",
                json={
                    "ticker": ticker,
                    "strategy": args.strategy,
                    "start_date": START_DATE,
                    "end_date": END_DATE,
                },
            )
            runtime = perf_counter() - started
            if response.status_code != 200:
                print(json.dumps({"ticker": ticker, "status": "failed", "runtime_seconds": round(runtime, 3), "error": response.json()}, ensure_ascii=False), flush=True)
                continue
            result = response.json()
            print(
                json.dumps(
                    {
                        "ticker": ticker,
                        "strategy": args.strategy,
                        "start": START_DATE,
                        "end": END_DATE,
                        "daily_bars": result["data_coverage"]["daily_bars_count"],
                        "data_provider": result["data_coverage"].get("data_provider"),
                        "adjustment_mode": result["data_coverage"].get("adjustment_mode"),
                        "positions": result["summary"]["number_of_positions"],
                        "total_return": result["summary"]["total_return"],
                        "execution_model": result["data_coverage"]["execution_model"],
                        "warnings": result["warnings"],
                        "runtime_seconds": round(runtime, 3),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
