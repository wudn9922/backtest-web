"""Persist and print the formal NVDA Entry Zone v2 3x3 validation matrix."""

from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

from fastapi.testclient import TestClient

from app.backtest.sensitivity import analyze_legacy_entry_chasing
from app.main import app


START_DATE = "2021-09-01"
END_DATE = "2026-09-01"
STRATEGIES = ("simple", "advanced", "advanced_day1_stop")
POLICIES = ("conservative", "ohlc_heuristic", "favorable")


def main() -> None:
    report: dict = {"ticker": "NVDA", "start_date": START_DATE, "end_date": END_DATE, "matrix": [], "legacy": {}}
    with TestClient(app) as client:
        old_history = client.get("/api/backtests").json()
        legacy_records = {}
        for strategy in STRATEGIES:
            summary = next((item for item in old_history if item.get("strategy_version") is None and item["status"] == "COMPLETED" and item["ticker"] == "NVDA" and item["strategy"] == strategy and item["start_date"] == START_DATE and item["end_date"] == END_DATE), None)
            record = client.get(f"/api/backtests/{summary['id']}").json() if summary else None
            legacy_records[strategy] = record
            report["legacy"][strategy] = analyze_legacy_entry_chasing(record)

        new_results = {}
        for strategy in STRATEGIES:
            for policy in POLICIES:
                started = perf_counter()
                response = client.post("/api/backtests", json={
                    "ticker": "NVDA", "strategy": strategy, "start_date": START_DATE,
                    "end_date": END_DATE, "execution_policy": policy,
                })
                if response.status_code != 200:
                    raise RuntimeError(f"{strategy}/{policy}: {response.status_code} {response.text}")
                result = response.json()
                new_results[(strategy, policy)] = result
                report["matrix"].append({
                    "strategy": strategy,
                    "policy": policy,
                    "backtest_id": result["id"],
                    "strategy_version": result["strategy_version"],
                    "positions": result["summary"]["number_of_positions"],
                    "entry_zone_missed": sum(event["event"] == "ENTRY_ZONE_MISSED" for event in result["events"]),
                    "ambiguous_positions": result["summary"]["ambiguous_positions"],
                    "day1_stops": sum(event["event"] == "DAY1_FULL_STOP" for event in result["events"]),
                    "total_return": result["summary"]["total_return"],
                    "cagr": result["summary"]["cagr"],
                    "mdd": result["summary"]["max_drawdown"],
                    "sharpe": result["summary"]["sharpe_ratio"],
                    "runtime_seconds": round(perf_counter() - started, 3),
                })

        for strategy, legacy in legacy_records.items():
            analysis = report["legacy"][strategy]
            if not legacy:
                continue
            new_result = new_results[(strategy, "conservative")]
            new_buys = {str(item["timestamp"])[:10] for item in new_result["executions"] if item["side"] == "BUY"}
            missed_dates = {str(item["timestamp"])[:10] for item in new_result["events"] if item["event"] == "ENTRY_ZONE_MISSED"}
            for entry in analysis["entries"]:
                entry["new_version_did_not_buy_that_day"] = entry["date"] not in new_buys
                entry["new_version_logged_entry_zone_missed"] = entry["date"] in missed_dates

    output = Path(__file__).resolve().parents[2] / "data" / "entry-zone-v2-validation.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
