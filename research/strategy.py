from __future__ import annotations

import math
from datetime import date

from app.backtest.execution import DailyConservativeExecutionPolicy, DailyIntrabarExecutionPolicy, evaluate_entry_zone
from app.backtest.models import AdvancedStrategyState, StrategyParameters, StrategyState

from app.backtest.strategies.base import Bar, EventRecorder, FillCallback
from research.modules import Modules, FULL


class ResearchAdvanced:
    """Research-only gated copy of v2. ALL-ON parity is a mandatory test.

    Never registered in API/production. No parameter values are changed.
    """
    def __init__(self, parameters: StrategyParameters, recorder: EventRecorder, execution_policy: DailyIntrabarExecutionPolicy | None = None, modules: Modules = FULL, *, first_tp_fraction: float = .5):
        if first_tp_fraction not in (.25, .5):
            raise ValueError("Only the frozen 25% checkpoint and original 50% are supported")
        self.first_tp_divisor = 4 if first_tp_fraction == .25 else 2
        self.modules = modules
        self.p = parameters
        self.s = AdvancedStrategyState()
        self.events = recorder
        self.execution_policy = execution_policy or DailyConservativeExecutionPolicy()

    def _log(self, bar: Bar, ref_ma: float | None, event: str, trigger: float | None, current: float | None, before_qty: int, before_state: StrategyState, metadata: dict | None = None) -> None:
        self.events.add(timestamp=bar.timestamp, reference_ma=ref_ma, event=event, trigger=trigger, current=current, before_qty=before_qty, after_qty=self.s.current_qty, before_state=before_state, after_state=self.s.state, metadata=metadata)

    def _sell(self, bar: Bar, raw: float, qty: int, event: str, reason: str, fill: FillCallback) -> None:
        fill("SELL", raw, qty, event, reason, bar.timestamp)
        self.s.current_qty -= qty
        if self.s.current_qty == 0:
            self.s.state = StrategyState.CLOSED

    def partial_allowed(self) -> bool:
        return self.s.partial_tp_allowed(self.p.minimum_position_pct_q0)

    def _extreme_thresholds(self, reference_ma: float, sigma: float | None, reference_atr: float | None) -> tuple[float | None, float | None]:
        bias_threshold = None
        atr_threshold = None
        if self.modules.bias and sigma is not None and not math.isnan(sigma):
            bias_threshold = reference_ma * (1 + self.p.bias_sigma_multiple * sigma)
        if self.modules.atr and reference_atr is not None and not math.isnan(reference_atr):
            atr_threshold = reference_ma + self.p.atr_multiple * reference_atr
        return bias_threshold, atr_threshold

    def update_extreme_edges(self, daily_high: float, reference_ma: float, sigma: float | None, reference_atr: float | None) -> tuple[bool, list[str]]:
        """Update independent daily High threshold states and return rising edges."""
        bias_threshold, atr_threshold = self._extreme_thresholds(reference_ma, sigma, reference_atr)
        bias_now = bool(bias_threshold is not None and daily_high >= bias_threshold)
        atr_now = bool(atr_threshold is not None and daily_high >= atr_threshold)
        edges: list[str] = []
        if bias_now and not self.s.bias_extreme_active:
            edges.append("BIAS")
        if atr_now and not self.s.atr_extreme_active:
            edges.append("ATR")
        # A daily condition can become active during range evaluation, but it
        # is only allowed to re-arm after the completed bar in end_day().
        if bias_now:
            self.s.bias_extreme_active = True
        if atr_now:
            self.s.atr_extreme_active = True
        return bool(edges), edges

    def _log_daily_ambiguity(self, bar: Bar, reference_ma: float, before_qty: int, before_state: StrategyState, chosen_path: str | None = None, conditions: list[str] | None = None) -> None:
        self._log(
            bar,
            reference_ma,
            "DAILY_INTRABAR_AMBIGUITY",
            None,
            None,
            before_qty,
            before_state,
            {"policy": self.execution_policy.name, "chosen_path": chosen_path, "phase": "INTRADAY_RANGE", "simultaneous_conditions": conditions or []},
        )

    def _handle_entry_day_risk(self, bar: Bar, *, trading_day: date, reference_ma: float, fill: FillCallback) -> bool:
        """Original Advanced same-day risk: MA threshold sells current half."""
        if not self.modules.ma_break:
            return False
        half_level = reference_ma * (1 - self.p.ma_risk_pct / 100)
        if bar.low > half_level or not self.s.current_qty:
            return False
        entry_level = reference_ma * (1 + self.p.entry_stop_pct / 100)
        decision = self.execution_policy.entry_vs_adverse(bar_open=bar.open, bar_close=bar.close, entry_level=entry_level)
        self._entry_adverse_preceded = decision.event == "ADVERSE_FIRST"
        if decision.ambiguous:
            self._log_daily_ambiguity(bar, reference_ma, self.s.current_qty, self.s.state, decision.chosen_path, ["ENTRY_LEVEL", "MA_HALF_STOP"])
        if decision.event == "ADVERSE_FIRST":
            return False
        risk_qty = max(1, self.s.current_qty // 2)
        risk_before, risk_state = self.s.current_qty, self.s.state
        # The opening price predates this inferred entry, so an adverse move
        # after entry fills at the threshold.
        self._sell(bar, half_level, risk_qty, "MA_HALF_EXIT", "MA_BREAK_HALF_EXIT", fill)
        self.s.break_day = trading_day
        self.s.break_day_low = bar.low
        self.s.state = StrategyState.BREAK_PROTECTION
        self._log(bar, reference_ma, "BREAK_HALF_TRIGGERED", half_level, half_level, risk_before, risk_state)
        self._log(bar, reference_ma, "BREAK_PROTECTION_STARTED", bar.low, bar.low, self.s.current_qty, self.s.state)
        return True

    def process_bar(
        self,
        bar: Bar,
        *,
        trading_day: date,
        reference_ma: float,
        reference_atr: float | None,
        bias_sigma: float | None,
        buy_qty: int,
        fill: FillCallback,
    ) -> None:
        before_qty, before_state = self.s.current_qty, self.s.state
        self._entry_adverse_preceded = False
        profit_first_ambiguity = False

        # PHASE 1 / priority 1: a prior close can schedule a full exit at open.
        if self.s.pending_next_open_exit_reason and self.s.current_qty:
            reason = self.s.pending_next_open_exit_reason
            self._sell(bar, bar.open, self.s.current_qty, "FINAL_EXIT", reason, fill)
            self.s.pending_next_open_exit_reason = None
            self.s.day2_validation_pending = False
            self._log(bar, reference_ma, reason, bar.open, bar.open, before_qty, before_state, {"phase": "OPEN"})
            return

        # PHASE 1/2: existing-position adverse events precede favorable events.
        if self.s.current_qty:
            first_target = (self.s.entry_price or math.inf) * (1 + self.p.first_tp_pct / 100)
            protective = max(self.s.entry_price or 0, reference_ma * (1 - self.p.ma_risk_pct / 100))
            half_level = reference_ma * (1 - self.p.ma_risk_pct / 100)
            first_target_touched = bool(self.modules.first_tp and not self.s.first_tp_triggered and bar.high >= first_target)
            bias_threshold, atr_threshold = self._extreme_thresholds(reference_ma, bias_sigma, reference_atr)
            extreme_touched = bool(
                self.s.first_tp_triggered
                and ((bias_threshold is not None and bar.high >= bias_threshold) or (atr_threshold is not None and bar.high >= atr_threshold))
            )
            protective_touched = bool(self.modules.protective and self.s.first_tp_triggered and bar.low <= protective)
            # If +3% and its newly activated protective stop are both in this
            # daily range, the worse feasible path activates the regime without
            # a favorable partial sale, then exits in full.
            newly_activated_protective = bool(self.modules.protective and first_target_touched and bar.low <= protective)
            break_touched = bool(self.modules.ma_break and (self.modules.protective or not self.s.first_tp_triggered) and self.s.break_day_low is not None and self.s.break_day != trading_day and bar.low < self.s.break_day_low)
            half_touched = bool(self.modules.ma_break and not self.s.first_tp_triggered and self.s.break_day_low is None and bar.low <= half_level)
            adverse_touched = protective_touched or newly_activated_protective or break_touched or half_touched
            favorable_touched = first_target_touched or extreme_touched
            decision = self.execution_policy.choose(stop_touched=adverse_touched, profit_touched=favorable_touched, bar_open=bar.open, bar_close=bar.close)
            if decision.ambiguous:
                adverse_conditions = []
                if protective_touched or newly_activated_protective:
                    adverse_conditions.append("PROTECTIVE_STOP")
                if break_touched:
                    adverse_conditions.append("BREAK_DAY_LOW")
                if half_touched:
                    adverse_conditions.append("MA_HALF_STOP")
                favorable_conditions = (["FIRST_TP"] if first_target_touched else []) + (["EXTREME_TP"] if extreme_touched else [])
                self._log_daily_ambiguity(bar, reference_ma, before_qty, before_state, decision.chosen_path, adverse_conditions + favorable_conditions)
            profit_first_ambiguity = decision.ambiguous and decision.event == "PROFIT"

            # Priority 2: protective full stop, including same-day activation.
            if (protective_touched or newly_activated_protective) and not profit_first_ambiguity:
                if newly_activated_protective:
                    self.s.first_tp_triggered = True
                    self._log(bar, reference_ma, "FIRST_TP_TRIGGERED", first_target, first_target, before_qty, before_state, {"partial_sale_suppressed": True})
                raw = protective if newly_activated_protective else self.execution_policy.downward_fill(bar.open, protective)
                self._sell(bar, raw, self.s.current_qty, "PROTECTIVE_STOP", "PROTECTIVE_STOP", fill)
                self._log(bar, reference_ma, "PROTECTIVE_STOP_TRIGGERED", protective, raw, before_qty, before_state)
                return

            # Priority 3: BreakDayLow is strictly broken from the next day.
            if break_touched and not profit_first_ambiguity:
                level = float(self.s.break_day_low)
                raw = self.execution_policy.downward_fill(bar.open, level)
                self._sell(bar, raw, self.s.current_qty, "BREAK_LOW_EXIT", "BREAK_DAY_LOW_BROKEN", fill)
                self._log(bar, reference_ma, "BREAK_LOW_BROKEN", level, raw, before_qty, before_state)
                return

            # Priority 4: sell half of current shares. Any same-day favorable
            # event is suppressed by the daily adverse-first policy.
            if half_touched and not profit_first_ambiguity:
                qty = max(1, self.s.current_qty // 2)
                raw = self.execution_policy.downward_fill(bar.open, half_level)
                self._sell(bar, raw, qty, "MA_HALF_EXIT", "MA_BREAK_HALF_EXIT", fill)
                self.s.break_day = trading_day
                self.s.break_day_low = bar.low
                self.s.state = StrategyState.BREAK_PROTECTION
                self._log(bar, reference_ma, "BREAK_HALF_TRIGGERED", half_level, raw, before_qty, before_state)
                self._log(bar, reference_ma, "BREAK_PROTECTION_STARTED", bar.low, bar.low, self.s.current_qty, self.s.state)
                return

        # Priority 5: new daily entry. EntryLevel is above Trigger, so a High
        # that reaches EntryLevel proves both upward levels were crossed.
        entered_today = False
        if not self.s.current_qty:
            entry_zone = evaluate_entry_zone(
                bar_open=bar.open, bar_high=bar.high, reference_ma=reference_ma,
                breakout_trigger_pct=self.p.breakout_trigger_pct, entry_stop_pct=self.p.entry_stop_pct,
            )
            if entry_zone.missed:
                self._log(
                    bar, reference_ma, "ENTRY_ZONE_MISSED", entry_zone.upper_entry, bar.open, 0, before_state,
                    {"reference_ma": reference_ma, "lower_entry": entry_zone.lower_entry, "upper_entry": entry_zone.upper_entry, "open": bar.open, "entry_allowed": False, "entry_missed": True, "reason": "GAP_ABOVE_ENTRY_ZONE"},
                )
                return
            if self.s.state in (StrategyState.FLAT, StrategyState.CLOSED) and entry_zone.armed:
                self.s = AdvancedStrategyState(state=StrategyState.ENTRY_ARMED)
                self._log(bar, reference_ma, "BREAKOUT_TRIGGERED", entry_zone.lower_entry, max(bar.open, entry_zone.lower_entry), 0, before_state)
            if self.s.state == StrategyState.ENTRY_ARMED and entry_zone.filled:
                entry = entry_zone.upper_entry
                raw = float(entry_zone.fill_price)
                fill("BUY", raw, buy_qty, "ENTRY", "ENTRY_STOP_FILLED", bar.timestamp)
                self.s.entry_timestamp = bar.timestamp
                self.s.entry_day = trading_day
                self.s.state = StrategyState.LONG_VALIDATING_DAY1
                self._log(bar, reference_ma, "ENTRY_STOP_FILLED", entry, raw, 0, StrategyState.ENTRY_ARMED, {"phase": "OPEN" if bar.open >= entry else "INTRADAY_RANGE", "lower_entry": entry_zone.lower_entry, "upper_entry": entry_zone.upper_entry, "entry_allowed": True, "entry_missed": False, "entry_execution_price": raw})
                entered_today = True

                if self._handle_entry_day_risk(bar, trading_day=trading_day, reference_ma=reference_ma, fill=fill):
                    return
            else:
                return

        # Priority 6: first +3% target. Reaching it changes the regime even when
        # the minimum-position rule blocks the partial sale.
        first_target = (self.s.entry_price or math.inf) * (1 + self.p.first_tp_pct / 100)
        if self.modules.first_tp and not self.s.first_tp_triggered and bar.high >= first_target:
            protective = max(self.s.entry_price or 0, reference_ma * (1 - self.p.ma_risk_pct / 100))
            if self.modules.protective and bar.low <= protective and not self._entry_adverse_preceded and not profit_first_ambiguity:
                self._log_daily_ambiguity(bar, reference_ma, self.s.current_qty, self.s.state, conditions=["FIRST_TP", "PROTECTIVE_STOP"])
                self.s.first_tp_triggered = True
                self._log(bar, reference_ma, "FIRST_TP_TRIGGERED", first_target, first_target, self.s.current_qty, self.s.state, {"partial_sale_suppressed": True})
                qty_before, state_before = self.s.current_qty, self.s.state
                self._sell(bar, protective, self.s.current_qty, "PROTECTIVE_STOP", "PROTECTIVE_STOP", fill)
                self._log(bar, reference_ma, "PROTECTIVE_STOP_TRIGGERED", protective, protective, qty_before, state_before)
                return
            raw = self.execution_policy.upward_fill(bar.open, first_target)
            qty_before, state_before = self.s.current_qty, self.s.state
            self.s.first_tp_triggered = True
            if not self.modules.first_tp_partial:
                # Research only: waive the sale, not the signal or regime switch.
                pass
            elif self.partial_allowed():
                qty = max(1, self.s.current_qty // self.first_tp_divisor)
                self._sell(bar, raw, qty, "FIRST_TP", "FIRST_TAKE_PROFIT", fill)
            else:
                self._log(bar, reference_ma, "PARTIAL_TP_BLOCKED_MIN_POSITION", first_target, raw, qty_before, state_before)
            if self.s.current_qty:
                self.s.state = StrategyState.POST_FIRST_TP
            self._log(bar, reference_ma, "FIRST_TP_TRIGGERED", first_target, raw, qty_before, state_before)
            if self.modules.protective and profit_first_ambiguity and bar.low <= protective and self.s.current_qty:
                stop_before, stop_state = self.s.current_qty, self.s.state
                self._sell(bar, protective, self.s.current_qty, "PROTECTIVE_STOP", "PROTECTIVE_STOP", fill)
                self._log(bar, reference_ma, "PROTECTIVE_STOP_TRIGGERED", protective, protective, stop_before, stop_state, {"ordered_after_profit": True})
                return

        # Priority 7: independent Bias/ATR daily rising edges. Simultaneous
        # edges update both states but execute one 10%-of-Q0 sale.
        if self.s.current_qty and self.s.first_tp_triggered and (self.modules.bias or self.modules.atr):
            bias_threshold, atr_threshold = self._extreme_thresholds(reference_ma, bias_sigma, reference_atr)
            edge, sources = self.update_extreme_edges(bar.high, reference_ma, bias_sigma, reference_atr)
            thresholds = {"BIAS": bias_threshold, "ATR": atr_threshold}
            for source in sources:
                self._log(bar, reference_ma, f"{source}_EXTREME_ENTER", thresholds[source], bar.high, self.s.current_qty, self.s.state)
            if edge and self.s.extreme_tp_count < self.p.max_extreme_tp_count:
                trigger_price = min(float(thresholds[source]) for source in sources if thresholds[source] is not None)
                raw = self.execution_policy.upward_fill(bar.open, trigger_price)
                qty_before, state_before = self.s.current_qty, self.s.state
                if self.partial_allowed():
                    qty = min(self.s.current_qty, max(1, int((self.s.q0 or 0) * self.p.extreme_tp_pct_q0 / 100)))
                    self._sell(bar, raw, qty, "EXTREME_TP", "+".join(sources) + "_EXTREME", fill)
                    self.s.extreme_tp_count += 1
                    self._log(bar, reference_ma, "EXTREME_TP_EXECUTED", trigger_price, raw, qty_before, state_before, {"sources": sources, "count": self.s.extreme_tp_count})
                else:
                    self._log(bar, reference_ma, "PARTIAL_TP_BLOCKED_MIN_POSITION", trigger_price, raw, qty_before, state_before, {"sources": sources})
            if profit_first_ambiguity and protective_touched and self.s.current_qty:
                stop_before, stop_state = self.s.current_qty, self.s.state
                raw_stop = self.execution_policy.downward_fill(bar.open, protective)
                self._sell(bar, raw_stop, self.s.current_qty, "PROTECTIVE_STOP", "PROTECTIVE_STOP", fill)
                self._log(bar, reference_ma, "PROTECTIVE_STOP_TRIGGERED", protective, raw_stop, stop_before, stop_state, {"ordered_after_profit": True})

    def end_day(
        self,
        *,
        trading_day: date,
        daily_close: float,
        daily_high: float,
        daily_low: float,
        daily_volume: float,
        previous_day_volume: float | None,
        current_day_ma: float,
        timestamp,
        reference_ma: float,
        reference_atr: float | None = None,
        bias_sigma: float | None = None,
    ) -> None:
        """PHASE 3: perform only completed-close validations and re-arming."""
        dummy = Bar(timestamp, daily_close, daily_high, daily_low, daily_close, daily_volume)
        if self.s.state == StrategyState.ENTRY_ARMED:
            self.s.state = StrategyState.FLAT
            return
        if not self.s.current_qty:
            return

        if self.s.break_day == trading_day:
            self.s.break_day_low = daily_low

        # Priority 8: Day 1 volume versus the previous completed trading day.
        if self.s.entry_day == trading_day:
            self.s.entry_day_close = daily_close
            self.s.entry_day_volume = daily_volume
            self.s.previous_day_volume = previous_day_volume
            threshold = (previous_day_volume or math.inf) * (1 + self.p.volume_increase_pct / 100)
            before = self.s.state
            if self.modules.volume and (previous_day_volume is None or daily_volume < threshold):
                self.s.pending_next_open_exit_reason = "VOLUME_CONFIRMATION_FAIL"
                self.s.day2_validation_pending = False
                self.s.state = StrategyState.PENDING_FULL_EXIT_NEXT_OPEN
                self._log(dummy, reference_ma, "VOLUME_CONFIRMATION_FAIL", threshold, daily_volume, self.s.current_qty, before, {"phase": "CLOSE"})
            else:
                self.s.day2_validation_pending = self.modules.day2
                self.s.state = StrategyState.LONG_VALIDATING_DAY2
                if self.modules.volume:
                    self._log(dummy, reference_ma, "VOLUME_CONFIRMATION_PASS", threshold, daily_volume, self.s.current_qty, before, {"phase": "CLOSE"})
                if not self.modules.day2:
                    self.s.state = StrategyState.POST_FIRST_TP if self.s.first_tp_triggered else (StrategyState.BREAK_PROTECTION if self.s.break_day_low is not None else StrategyState.LONG_NORMAL)

        # Priority 9: the next trading day's close must be strictly greater.
        elif self.modules.day2 and self.s.day2_validation_pending:
            before = self.s.state
            self.s.day2_validation_pending = False
            if daily_close <= (self.s.entry_day_close or math.inf):
                self.s.pending_next_open_exit_reason = "DAY2_CLOSE_CONFIRMATION_FAIL"
                self.s.state = StrategyState.PENDING_FULL_EXIT_NEXT_OPEN
                self._log(dummy, reference_ma, "DAY2_CONFIRMATION_FAIL", self.s.entry_day_close, daily_close, self.s.current_qty, before, {"phase": "CLOSE"})
            else:
                self.s.state = StrategyState.POST_FIRST_TP if self.s.first_tp_triggered else (StrategyState.BREAK_PROTECTION if self.s.break_day_low is not None else StrategyState.LONG_NORMAL)
                self._log(dummy, reference_ma, "DAY2_CONFIRMATION_PASS", self.s.entry_day_close, daily_close, self.s.current_qty, before, {"phase": "CLOSE"})

        # Priority 10: the one intentional current-day MA exception. It is
        # evaluated only after the entire daily bar and MA(t) are complete.
        if self.modules.ma_break and self.s.break_day_low is not None and self.s.break_day != trading_day and daily_low > current_day_ma:
            before = self.s.state
            self.s.break_day = None
            self.s.break_day_low = None
            if not self.s.pending_next_open_exit_reason:
                self.s.state = StrategyState.POST_FIRST_TP if self.s.first_tp_triggered else (StrategyState.LONG_VALIDATING_DAY2 if self.s.day2_validation_pending else StrategyState.LONG_NORMAL)
            self._log(dummy, reference_ma, "BREAK_PROTECTION_RESET", current_day_ma, daily_low, self.s.current_qty, before, {"uses_current_day_completed_ma": True, "phase": "CLOSE"})

        # Daily edge re-arming uses the completed day's High, never Close and
        # never a partially formed intraday price.
        if self.s.first_tp_triggered and self.s.current_qty:
            bias_threshold, atr_threshold = self._extreme_thresholds(reference_ma, bias_sigma, reference_atr)
            if self.s.bias_extreme_active and bias_threshold is not None and daily_high < bias_threshold:
                before = self.s.state
                self.s.bias_extreme_active = False
                self._log(dummy, reference_ma, "BIAS_EXTREME_EXIT", bias_threshold, daily_high, self.s.current_qty, before, {"phase": "CLOSE"})
            if self.s.atr_extreme_active and atr_threshold is not None and daily_high < atr_threshold:
                before = self.s.state
                self.s.atr_extreme_active = False
                self._log(dummy, reference_ma, "ATR_EXTREME_EXIT", atr_threshold, daily_high, self.s.current_qty, before, {"phase": "CLOSE"})
