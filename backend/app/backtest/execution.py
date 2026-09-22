from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PolicyName = Literal["conservative", "ohlc_heuristic", "favorable"]


@dataclass(frozen=True)
class IntrabarDecision:
    event: str
    ambiguous: bool = False
    chosen_path: str | None = None


@dataclass(frozen=True)
class EntryZoneDecision:
    lower_entry: float
    upper_entry: float
    entry_allowed: bool
    armed: bool
    filled: bool
    missed: bool
    fill_price: float | None = None


def evaluate_entry_zone(
    *,
    bar_open: float,
    bar_high: float,
    reference_ma: float,
    breakout_trigger_pct: float,
    entry_stop_pct: float,
) -> EntryZoneDecision:
    """Shared v2 entry rule: never chase an opening print above UpperEntry."""
    lower = reference_ma + reference_ma * breakout_trigger_pct / 100
    upper = reference_ma + reference_ma * entry_stop_pct / 100
    tolerance = max(abs(upper), 1.0) * 1e-12
    if bar_open - upper > tolerance:
        return EntryZoneDecision(lower, upper, False, False, False, True)
    armed = bar_open >= lower or bar_high >= lower
    filled = armed and bar_high >= upper
    return EntryZoneDecision(lower, upper, True, armed, filled, False, upper if filled else None)


class DailyIntrabarExecutionPolicy:
    """Deterministic ordering for events whose order Daily OHLC cannot reveal."""

    name: PolicyName = "conservative"
    display_name = "Conservative"

    @staticmethod
    def downward_fill(bar_open: float, trigger: float) -> float:
        return bar_open if bar_open <= trigger else trigger

    @staticmethod
    def upward_fill(bar_open: float, trigger: float) -> float:
        return bar_open if bar_open >= trigger else trigger

    def entry_vs_adverse(self, *, bar_open: float, bar_close: float, entry_level: float) -> IntrabarDecision:
        if bar_open >= entry_level:
            return IntrabarDecision("ENTRY_FIRST", False, "open-entry-then-adverse")
        return IntrabarDecision("ENTRY_FIRST", True, "conservative-entry-first")

    def stop_vs_profit(self, *, bar_open: float, bar_close: float) -> IntrabarDecision:
        return IntrabarDecision("RISK", True, "conservative-adverse-first")

    def choose(self, *, stop_touched: bool, profit_touched: bool, bar_open: float = 0, bar_close: float = 0) -> IntrabarDecision:
        if stop_touched and profit_touched:
            return self.stop_vs_profit(bar_open=bar_open, bar_close=bar_close)
        if stop_touched:
            return IntrabarDecision("RISK")
        if profit_touched:
            return IntrabarDecision("PROFIT")
        return IntrabarDecision("NONE")


class DailyConservativeExecutionPolicy(DailyIntrabarExecutionPolicy):
    """Resolve unknowable Daily OHLC paths using adverse-first assumptions."""

    @staticmethod
    def choose(*, stop_touched: bool, profit_touched: bool, bar_open: float = 0, bar_close: float = 0) -> IntrabarDecision:
        if stop_touched and profit_touched:
            return IntrabarDecision("RISK", True, "conservative-adverse-first")
        if stop_touched:
            return IntrabarDecision("RISK")
        if profit_touched:
            return IntrabarDecision("PROFIT")
        return IntrabarDecision("NONE")


class DailyFavorableExecutionPolicy(DailyIntrabarExecutionPolicy):
    """Use the favorable feasible ordering only when the daily path is ambiguous."""

    name: PolicyName = "favorable"
    display_name = "Favorable"

    def entry_vs_adverse(self, *, bar_open: float, bar_close: float, entry_level: float) -> IntrabarDecision:
        if bar_open >= entry_level:
            return IntrabarDecision("ENTRY_FIRST", False, "open-entry-then-adverse")
        return IntrabarDecision("ADVERSE_FIRST", True, "favorable-low-before-entry")

    def stop_vs_profit(self, *, bar_open: float, bar_close: float) -> IntrabarDecision:
        return IntrabarDecision("PROFIT", True, "favorable-profit-first")


class DailyOHLCHeuristicExecutionPolicy(DailyIntrabarExecutionPolicy):
    """Heuristic only: green bar O-L-H-C, red bar O-H-L-C."""

    name: PolicyName = "ohlc_heuristic"
    display_name = "OHLC Heuristic"

    def entry_vs_adverse(self, *, bar_open: float, bar_close: float, entry_level: float) -> IntrabarDecision:
        if bar_open >= entry_level:
            return IntrabarDecision("ENTRY_FIRST", False, "open-entry-then-adverse")
        if bar_close >= bar_open:
            return IntrabarDecision("ADVERSE_FIRST", True, "ohlc-open-low-high-close")
        return IntrabarDecision("ENTRY_FIRST", True, "ohlc-open-high-low-close")

    def stop_vs_profit(self, *, bar_open: float, bar_close: float) -> IntrabarDecision:
        if bar_close >= bar_open:
            return IntrabarDecision("RISK", True, "ohlc-open-low-high-close")
        return IntrabarDecision("PROFIT", True, "ohlc-open-high-low-close")


def execution_policy(name: PolicyName) -> DailyIntrabarExecutionPolicy:
    policies = {
        "conservative": DailyConservativeExecutionPolicy,
        "ohlc_heuristic": DailyOHLCHeuristicExecutionPolicy,
        "favorable": DailyFavorableExecutionPolicy,
    }
    return policies[name]()


# Backward-compatible import for existing integrations. New code and results
# identify the policy by its explicit daily execution name.
ConservativeIntrabarPolicy = DailyConservativeExecutionPolicy
