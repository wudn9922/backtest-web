from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .models import Execution


@dataclass
class Portfolio:
    cash: float
    commission_pct: float
    slippage_pct: float
    quantity: int = 0
    average_cost: float = 0.0
    total_commission: float = 0.0
    total_slippage_cost: float = 0.0
    executions: list[Execution] = field(default_factory=list)

    def equity(self, mark_price: float) -> float:
        return self.cash + self.quantity * mark_price

    def buy(self, timestamp: datetime, raw_price: float, quantity: int, event_type: str, reason: str) -> Execution:
        price = raw_price * (1 + self.slippage_pct / 100)
        affordable = int(self.cash / (price * (1 + self.commission_pct / 100)))
        quantity = max(0, min(quantity, affordable))
        if quantity == 0:
            raise ValueError("insufficient cash for one whole share")
        gross = price * quantity
        commission = gross * self.commission_pct / 100
        slip = max(0.0, price - raw_price) * quantity
        old_value = self.average_cost * self.quantity
        self.cash -= gross + commission
        self.quantity += quantity
        self.average_cost = (old_value + gross + commission) / self.quantity
        self.total_commission += commission
        self.total_slippage_cost += slip
        execution = Execution(timestamp, "BUY", price, quantity, gross, commission, slip, self.quantity, event_type, reason)
        self.executions.append(execution)
        return execution

    def sell(self, timestamp: datetime, raw_price: float, quantity: int, event_type: str, reason: str) -> Execution:
        quantity = max(0, min(quantity, self.quantity))
        if quantity == 0:
            raise ValueError("cannot sell zero shares")
        price = raw_price * (1 - self.slippage_pct / 100)
        gross = price * quantity
        commission = gross * self.commission_pct / 100
        slip = max(0.0, raw_price - price) * quantity
        self.cash += gross - commission
        self.quantity -= quantity
        self.total_commission += commission
        self.total_slippage_cost += slip
        execution = Execution(timestamp, "SELL", price, quantity, gross, commission, slip, self.quantity, event_type, reason)
        self.executions.append(execution)
        if self.quantity == 0:
            self.average_cost = 0.0
        return execution


def initial_quantity(equity: float, allocation_pct: float, raw_price: float, slippage_pct: float, commission_pct: float) -> int:
    allocation = equity * allocation_pct / 100
    execution_price = raw_price * (1 + slippage_pct / 100)
    return int(allocation / (execution_price * (1 + commission_pct / 100)))

