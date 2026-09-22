"""Validate representative NVDA position audits against stored engine logs."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi.testclient import TestClient

from app.main import app


def _day(value: str):
    return datetime.fromisoformat(value).date()


def _position_for_event(positions: list[dict], events: list[dict], source_event: str) -> dict | None:
    event = next((item for item in events if item["event"] == source_event), None)
    if not event:
        return None
    event_day = _day(event["timestamp"])
    return next((position for position in positions if _day(position["entry_date"]) <= event_day <= _day(position["final_exit_date"])), None)


def _consistency_errors(audit: dict, result: dict) -> list[str]:
    errors: list[str] = []
    timeline = audit["timeline"]
    if not timeline:
        return ["empty timeline"]
    position = audit["position"]
    if timeline[0]["date"] != position["entry_date"][:10] or timeline[-1]["date"] != position["final_exit_date"][:10]:
        errors.append("timeline boundaries do not match position")
    if timeline[0]["current_quantity_at_open"] != 0 or timeline[-1]["current_quantity_at_close"] != 0:
        errors.append("position boundary quantities are not flat")
    for previous, current in zip(timeline, timeline[1:]):
        if previous["current_quantity_at_close"] != current["current_quantity_at_open"]:
            errors.append(f"quantity discontinuity {previous['date']} -> {current['date']}")

    global_events = {(item["timestamp"][:10], item["event"]) for item in result["events"]}
    chart_executions = audit["chart"]["executions"]
    execution_signatures = {(item["timestamp"][:10], round(item["price"], 8), item["quantity"], item["event_type"], item["reason"]) for item in chart_executions}
    for day in timeline:
        for event in day["events"]:
            source = event["source_event"]
            if (day["date"], source) not in global_events and not any(source in {item["event_type"], item["reason"]} for item in chart_executions if item["timestamp"][:10] == day["date"]):
                errors.append(f"audit event missing from source logs: {day['date']} {source}")
            if event["execution_price"] is not None:
                matching = [item for item in chart_executions if item["timestamp"][:10] == day["date"] and abs(item["price"] - event["execution_price"]) < 1e-7]
                if not matching:
                    errors.append(f"audit execution price missing from execution log: {day['date']} {source}")
    result_execs = {
        (item["timestamp"][:10], round(item["price"], 8), item["quantity"], item["event_type"], item["reason"])
        for item in result["executions"]
        if position["entry_date"][:10] <= item["timestamp"][:10] <= position["final_exit_date"][:10]
    }
    if execution_signatures != result_execs:
        errors.append("position execution slice differs from backtest execution log")
    return errors


def main() -> None:
    with TestClient(app) as client:
        response = client.post("/api/backtests", json={"ticker": "NVDA", "strategy": "advanced", "start_date": "2021-09-01", "end_date": "2026-09-01"})
        response.raise_for_status()
        result = response.json()
        positions = result["positions"]
        selected = {
            "profit": next((item for item in positions if item["net_pnl"] > 0), None),
            "loss": next((item for item in positions if item["net_pnl"] < 0), None),
            "ma_half_exit": _position_for_event(positions, result["events"], "BREAK_HALF_TRIGGERED"),
            "first_tp": _position_for_event(positions, result["events"], "FIRST_TP_TRIGGERED"),
            "daily_ambiguity": _position_for_event(positions, result["events"], "DAILY_INTRABAR_AMBIGUITY"),
        }
        report: dict[str, object] = {"backtest_id": result["id"], "positions": len(positions), "categories": {}}
        for category, position in selected.items():
            if position is None:
                report["categories"][category] = {"found": False}
                continue
            audit_response = client.get(f"/api/backtests/{result['id']}/positions/{position['position_id']}/audit")
            audit_response.raise_for_status()
            audit = audit_response.json()
            errors = _consistency_errors(audit, result)
            report["categories"][category] = {
                "found": True,
                "position_id": position["position_id"],
                "entry": position["entry_date"][:10],
                "exit": position["final_exit_date"][:10],
                "net_pnl": position["net_pnl"],
                "timeline_days": len(audit["timeline"]),
                "daily_events": sum(len(day["events"]) for day in audit["timeline"]),
                "consistency_errors": errors,
            }
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
