from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from app.backtest.models import Event


@dataclass
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class EventRecorder:
    def __init__(self):
        self.events: list[Event] = []

    def add(
        self,
        *,
        timestamp: datetime,
        reference_ma: float | None,
        event: str,
        trigger: float | None,
        current: float | None,
        before_qty: int,
        after_qty: int,
        before_state: str,
        after_state: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(Event(timestamp, reference_ma, event, trigger, current, before_qty, after_qty, before_state, after_state, metadata or {}))


FillCallback = Callable[[str, float, int, str, str, datetime], None]

