from __future__ import annotations

from datetime import date

from app.backtest.models import StrategyState

from .advanced_ma_breakout import AdvancedMABreakout
from .base import Bar, FillCallback


class AdvancedDay1StopMABreakout(AdvancedMABreakout):
    """Advanced MA Breakout with an entry-day-only full stop."""

    def _handle_entry_day_risk(self, bar: Bar, *, trading_day: date, reference_ma: float, fill: FillCallback) -> bool:
        stop_level = reference_ma * (1 - self.p.day1_stop_pct / 100)
        if bar.low > stop_level or not self.s.current_qty:
            return False
        entry_level = reference_ma * (1 + self.p.entry_stop_pct / 100)
        decision = self.execution_policy.entry_vs_adverse(bar_open=bar.open, bar_close=bar.close, entry_level=entry_level)
        self._entry_adverse_preceded = decision.event == "ADVERSE_FIRST"
        conditions = ["ENTRY_LEVEL", "DAY1_FULL_STOP"]
        first_target = (self.s.entry_price or float("inf")) * (1 + self.p.first_tp_pct / 100)
        if bar.high >= first_target:
            conditions.append("FIRST_TP")
        if decision.ambiguous:
            self._log_daily_ambiguity(bar, reference_ma, self.s.current_qty, self.s.state, decision.chosen_path, conditions)
        if decision.event == "ADVERSE_FIRST":
            return False
        before_qty, before_state = self.s.current_qty, self.s.state
        # When the daily path is unknowable, preserve the engine's adverse
        # gap rule as well: an Open already below the stop is the worse fill.
        raw = self.execution_policy.downward_fill(bar.open, stop_level)
        self._sell(bar, raw, self.s.current_qty, "DAY1_FULL_STOP", "DAY1_FULL_STOP", fill)
        self.s.state = StrategyState.CLOSED
        self._log(
            bar,
            reference_ma,
            "DAY1_FULL_STOP",
            raw,
            stop_level,
            before_qty,
            before_state,
            {"entry_day_only": True, "open_below_stop_before_entry": bar.open <= stop_level},
        )
        return True
