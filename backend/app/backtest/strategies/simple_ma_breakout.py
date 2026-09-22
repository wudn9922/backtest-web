from __future__ import annotations

from dataclasses import dataclass

from app.backtest.execution import DailyConservativeExecutionPolicy, DailyIntrabarExecutionPolicy, evaluate_entry_zone
from app.backtest.models import StrategyParameters, StrategyState

from .base import Bar, EventRecorder, FillCallback


@dataclass
class SimpleState:
    state: StrategyState = StrategyState.FLAT


class SimpleMABreakout:
    def __init__(self, parameters: StrategyParameters, recorder: EventRecorder, execution_policy: DailyIntrabarExecutionPolicy | None = None):
        self.p = parameters
        self.state = SimpleState()
        self.events = recorder
        self.execution_policy = execution_policy or DailyConservativeExecutionPolicy()

    def process_bar(self, bar: Bar, reference_ma: float, qty: int, buy_qty: int, fill: FillCallback) -> None:
        before_state = self.state.state
        if qty > 0:
            level = reference_ma * (1 - self.p.exit_below_ma_pct / 100)
            if bar.low <= level:
                raw = self.execution_policy.downward_fill(bar.open, level)
                fill("SELL", raw, qty, "FINAL_EXIT", "MA_EXIT", bar.timestamp)
                self.state.state = StrategyState.CLOSED
                self.events.add(timestamp=bar.timestamp, reference_ma=reference_ma, event="MA_EXIT", trigger=level, current=raw, before_qty=qty, after_qty=0, before_state=before_state, after_state=self.state.state)
            return

        entry_zone = evaluate_entry_zone(
            bar_open=bar.open, bar_high=bar.high, reference_ma=reference_ma,
            breakout_trigger_pct=self.p.breakout_trigger_pct, entry_stop_pct=self.p.entry_stop_pct,
        )
        if entry_zone.missed:
            self.events.add(
                timestamp=bar.timestamp, reference_ma=reference_ma, event="ENTRY_ZONE_MISSED",
                trigger=entry_zone.upper_entry, current=bar.open, before_qty=0, after_qty=0,
                before_state=before_state, after_state=self.state.state,
                metadata={"reference_ma": reference_ma, "lower_entry": entry_zone.lower_entry, "upper_entry": entry_zone.upper_entry, "open": bar.open, "entry_allowed": False, "entry_missed": True, "reason": "GAP_ABOVE_ENTRY_ZONE"},
            )
            return
        if self.state.state in (StrategyState.FLAT, StrategyState.CLOSED) and entry_zone.armed:
            self.state.state = StrategyState.ENTRY_ARMED
            self.events.add(timestamp=bar.timestamp, reference_ma=reference_ma, event="BREAKOUT_TRIGGERED", trigger=entry_zone.lower_entry, current=max(bar.open, entry_zone.lower_entry), before_qty=0, after_qty=0, before_state=before_state, after_state=self.state.state)
        if self.state.state == StrategyState.ENTRY_ARMED and entry_zone.filled:
            entry = entry_zone.upper_entry
            raw = float(entry_zone.fill_price)
            fill("BUY", raw, buy_qty, "ENTRY", "ENTRY_STOP_FILLED", bar.timestamp)
            self.state.state = StrategyState.LONG_NORMAL
            self.events.add(timestamp=bar.timestamp, reference_ma=reference_ma, event="ENTRY_STOP_FILLED", trigger=entry, current=raw, before_qty=0, after_qty=buy_qty, before_state=StrategyState.ENTRY_ARMED, after_state=self.state.state, metadata={"lower_entry": entry_zone.lower_entry, "upper_entry": entry_zone.upper_entry, "entry_allowed": True, "entry_missed": False, "entry_execution_price": raw})
            exit_level = reference_ma * (1 - self.p.exit_below_ma_pct / 100)
            if bar.low <= exit_level:
                decision = self.execution_policy.entry_vs_adverse(bar_open=bar.open, bar_close=bar.close, entry_level=entry)
                if decision.ambiguous:
                    self.events.add(
                        timestamp=bar.timestamp,
                        reference_ma=reference_ma,
                        event="DAILY_INTRABAR_AMBIGUITY",
                        trigger=exit_level,
                        current=bar.low,
                        before_qty=buy_qty,
                        after_qty=buy_qty,
                        before_state=self.state.state,
                        after_state=self.state.state,
                        metadata={"policy": self.execution_policy.name, "chosen_path": decision.chosen_path, "phase": "INTRADAY_RANGE", "simultaneous_conditions": ["ENTRY_LEVEL", "MA_EXIT"]},
                    )
                if decision.event == "ADVERSE_FIRST":
                    return
                raw_exit = self.execution_policy.downward_fill(bar.open, exit_level) if bar.open >= entry else exit_level
                fill("SELL", raw_exit, buy_qty, "FINAL_EXIT", "MA_EXIT", bar.timestamp)
                before_exit = self.state.state
                self.state.state = StrategyState.CLOSED
                self.events.add(timestamp=bar.timestamp, reference_ma=reference_ma, event="MA_EXIT", trigger=exit_level, current=raw_exit, before_qty=buy_qty, after_qty=0, before_state=before_exit, after_state=self.state.state)

    def end_day(self) -> None:
        if self.state.state == StrategyState.ENTRY_ARMED:
            self.state.state = StrategyState.FLAT
