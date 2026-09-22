"""Reporting repair from frozen executions; never invokes a backtest or provider."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from math import isclose, isfinite
from typing import Any


class ReportingRepairError(ValueError):
    pass


def _equal(actual: float, expected: float) -> bool:
    return isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-7)


def corrected_gross_pnl(result: dict[str, Any]) -> tuple[dict[str, Any], dict[str, float], int]:
    """Change only positions[*].gross_pnl, validating the frozen trade ledger.

    Legacy positions without IDs are matched by execution order and verified
    against entry/exit timestamps, entry prices and share counts. A trailing
    open position is validated but is not a completed Position Summary row.
    """
    corrected = deepcopy(result)
    closed = []
    current = None
    for execution in result.get("executions", []):
        side = execution["side"]
        qty = execution["quantity"]
        price, fee = float(execution["price"]), float(execution["commission"])
        if isinstance(qty, bool) or int(qty) != qty or qty <= 0:
            raise ReportingRepairError("Invalid execution share quantity.")
        if not isfinite(price) or price <= 0 or not isfinite(fee) or fee < 0:
            raise ReportingRepairError("Invalid execution price or commission.")
        value = price * qty
        if not _equal(float(execution["gross_value"]), value):
            raise ReportingRepairError("Execution gross value does not match price times shares.")
        if side == "BUY":
            if current is not None:
                raise ReportingRepairError("Overlapping positions cannot be repaired.")
            current = {"entry": execution, "remaining": qty, "buy_value": value,
                       "sell_value": 0.0, "buy_fee": fee, "sell_fees": 0.0}
        elif side == "SELL":
            if current is None or qty > current["remaining"]:
                raise ReportingRepairError("Sell execution has no matching shares.")
            current["remaining"] -= qty
            current["sell_value"] += value
            current["sell_fees"] += fee
        else:
            raise ReportingRepairError("Unknown execution side.")
        if execution["position_remaining"] != current["remaining"]:
            raise ReportingRepairError("Execution remaining shares do not reconcile.")
        if current["remaining"] == 0:
            current["exit"] = execution
            closed.append(current)
            current = None

    positions = corrected.get("positions", [])
    if len(positions) != len(closed):
        raise ReportingRepairError("Completed positions do not match the execution ledger.")
    values = {}
    changes = 0
    for index, (position, trade) in enumerate(zip(positions, closed), start=1):
        entry, exit_execution = trade["entry"], trade["exit"]
        if (datetime.fromisoformat(position["entry_date"]) != datetime.fromisoformat(entry["timestamp"])
                or datetime.fromisoformat(position["final_exit_date"]) != datetime.fromisoformat(exit_execution["timestamp"])
                or position["initial_shares"] != entry["quantity"]
                or position["total_shares_sold"] != entry["quantity"]
                or not _equal(position["entry_price"], entry["price"])):
            raise ReportingRepairError("Position boundaries or share counts differ from executions.")
        gross = trade["sell_value"] - trade["buy_value"]
        fees = trade["buy_fee"] + trade["sell_fees"]
        if not _equal(position["net_pnl"], gross - fees):
            raise ReportingRepairError("Frozen net PnL does not reconcile; no reporting repair applied.")
        for key, expected in (("fees", fees), ("realized_pnl", position["net_pnl"])):
            if key in position and not _equal(position[key], expected):
                raise ReportingRepairError(f"Position {key} does not reconcile.")
        old = position["gross_pnl"]
        if not (_equal(old, gross) or _equal(old, gross - trade["sell_fees"])):
            raise ReportingRepairError("Gross PnL has an unrecognized historical definition.")
        if not _equal(old, gross):
            position["gross_pnl"] = gross
            changes += 1
        values[str(position.get("position_id", f"position-{index}"))] = position["gross_pnl"]
    return corrected, values, changes
