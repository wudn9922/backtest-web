"""Shared prices/accounting, isolated rule implementation; no IO or persistence."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math
import numpy as np
import pandas as pd

from app.backtest.engine import BacktestEngine
from app.backtest.execution import execution_policy
from app.backtest.indicators import add_indicators
from app.backtest.metrics import calculate_metrics
from app.backtest.models import BacktestRequest, StrategyState
from app.backtest.portfolio import Portfolio, initial_quantity
from app.backtest.strategies.simple_ma_breakout import SimpleMABreakout
from app.backtest.strategies.base import Bar, EventRecorder
from research.modules import FULL, Modules
from research.evidence_strategy import EvidenceAdvanced


@dataclass
class Prepared:
    request: BacktestRequest
    daily: pd.DataFrame

    def __post_init__(self):
        p = self.request.parameters
        self.enriched = add_indicators(self.daily, ma_type=p.ma_type, ma_period=p.ma_period,
                                       atr_period=p.atr_period, bias_lookback=p.bias_lookback)
        mask = [self.request.start_date <= i.date() <= self.request.end_date for i in self.enriched.index]
        self.period = self.enriched.loc[mask]
        if self.period[["reference_ma", "reference_atr", "reference_bias_sigma"]].isna().any().any():
            raise ValueError("Research requires the identical fully warmed-up dates for every variant")
        previous = self.enriched.shift(1)
        self.rows = []
        for ts, row in self.period.iterrows():
            bar = Bar(ts.to_pydatetime(), *(float(row[k]) for k in ["open", "high", "low", "close", "volume"]))
            self.rows.append((bar, float(row.reference_ma), float(row.reference_atr),
                              float(row.reference_bias_sigma), float(previous.loc[ts, "volume"]), float(row.ma)))
        self.dates = [b.timestamp.date().isoformat() for b, *_ in self.rows]
        self.date_index = {d: i for i, d in enumerate(self.dates)}


def simulate(prepared: Prepared, modules: Modules = FULL, *, anchor: dict | None = None,
             simple: bool = False, policy: str = "conservative", trace: bool = False,
             first_tp_fraction: float = .5, horizon_sessions: int | None = None, ma_mode: str = "full") -> dict:
    req = prepared.request
    if not req.force_close_at_end:
        raise ValueError("This study requires the canonical end-of-period liquidation")
    rec = EventRecorder()
    if horizon_sessions is not None and (anchor is None or not isinstance(horizon_sessions, int) or horizon_sessions < 1):
        raise ValueError("Fixed horizons require one anchored lifecycle and a positive session count")
    strategy = SimpleMABreakout(req.parameters, rec, execution_policy(policy)) if simple else EvidenceAdvanced(req.parameters, rec, execution_policy(policy), modules=modules, first_tp_fraction=first_tp_fraction, ma_mode=ma_mode)
    start = 0 if anchor is None else prepared.date_index[anchor["entry_date"][:10]]
    finish = len(prepared.rows) - 1 if horizon_sessions is None else min(start+horizon_sessions, len(prepared.rows)-1)
    # Ample independent funding prevents rounding/affordability changing fixed Q0.
    capital = req.initial_capital if anchor is None else 2 * anchor["entry_price"] * anchor["initial_shares"] * (1 + req.commission_pct / 100)
    pf = Portfolio(capital, req.commission_pct, req.slippage_pct)
    eq = []; exposure_days = 0; timeline = []
    for index in range(start, finish+1):
        bar, ma, atr, sigma, prev_volume, current_ma = prepared.rows[index]
        before_qty = pf.quantity
        execution_start = len(pf.executions)
        event_start = len(rec.events)
        state_open = asdict(strategy.state if simple else strategy.s) if trace else None
        entry_level = ma + ma * req.parameters.entry_stop_pct / 100
        quantity = anchor["initial_shares"] if anchor is not None else initial_quantity(
            pf.equity(bar.open), req.position_size_pct, max(bar.open, entry_level), req.slippage_pct, req.commission_pct)

        def fill(side, raw, qty, event, reason, timestamp):
            if side == "BUY":
                if anchor is not None and pf.executions:
                    raise AssertionError("An anchored lifecycle cannot create another entry")
                ex = pf.buy(timestamp, raw, qty, event, reason)
                if anchor is not None:
                    assert ex.quantity == anchor["initial_shares"]
                    assert ex.price == anchor["entry_price"]
                    assert pd.Timestamp(ex.timestamp) == pd.Timestamp(anchor["entry_date"])
                if not simple:
                    strategy.s.entry_price = ex.price
                    strategy.s.q0 = ex.quantity
                    strategy.s.current_qty = ex.quantity
            else:
                if qty > pf.quantity or qty <= 0:
                    raise AssertionError("Invalid research sell quantity")
                pf.sell(timestamp, raw, qty, event, reason)

        if simple:
            strategy.process_bar(bar, ma, pf.quantity, quantity, fill)
            strategy.end_day()
        else:
            strategy.process_bar(bar, trading_day=bar.timestamp.date(), reference_ma=ma,
                                 reference_atr=atr, bias_sigma=sigma, buy_qty=quantity, fill=fill)
            strategy.end_day(trading_day=bar.timestamp.date(), daily_close=bar.close,
                             daily_high=bar.high, daily_low=bar.low, daily_volume=bar.volume,
                             previous_day_volume=prev_volume, current_day_ma=current_ma,
                             timestamp=bar.timestamp, reference_ma=ma, reference_atr=atr, bias_sigma=sigma)
            assert strategy.s.current_qty == pf.quantity
        had_exposure = bool(before_qty or pf.quantity or any(e.side == "BUY" for e in pf.executions[execution_start:]))
        if index == finish and pf.quantity:
            reason = "END_OF_BACKTEST" if horizon_sessions is None or start+horizon_sessions > finish else "RESEARCH_40_SESSION_HORIZON" if horizon_sessions == 40 else "RESEARCH_FIXED_HORIZON"
            pf.sell(bar.timestamp, bar.close, pf.quantity, "FINAL_EXIT", reason)
            if not simple:
                strategy.s.current_qty = 0
                strategy.s.state = StrategyState.CLOSED
        if had_exposure:
            exposure_days += 1
        if trace:
            timeline.append({"date":bar.timestamp.date().isoformat(),
                **{k:getattr(bar,k) for k in ["open","high","low","close","volume"]},
                "reference_ma":ma,"reference_atr":atr,"bias_sigma":sigma,"current_ma":current_ma,
                "quantity_open":before_qty,"quantity_close":pf.quantity,"state_open":state_open,
                "state_close":asdict(strategy.state if simple else strategy.s),
                "events":[e.as_dict() for e in rec.events[event_start:]],
                "executions":[e.as_dict() for e in pf.executions[execution_start:]]})
        eq.append({"timestamp": bar.timestamp.isoformat(), "strategy": pf.equity(bar.close),
                   "cash": pf.cash, "market_value": pf.quantity * bar.close, "quantity": pf.quantity,
                   "inventory_fraction_q0": (pf.quantity / strategy.s.q0 if not simple and strategy.s.q0 else (1.0 if pf.quantity else 0.0)),
                   "had_exposure": had_exposure})
        if anchor is not None and pf.executions and pf.quantity == 0:
            break
    positions = BacktestEngine._positions(pf.executions, prepared.period)
    result = {"positions": positions, "executions": [e.as_dict() for e in pf.executions],
              "events": [e.as_dict() for e in rec.events], "equity": eq}
    if trace:
        result["timeline"] = timeline
    if horizon_sessions is not None:
        result["horizon"] = {"sessions_after_entry":horizon_sessions, "target_date":prepared.dates[finish],
                             "complete_horizon_available":start+horizon_sessions <= finish,
                             "actual_exit_date":positions[0]["final_exit_date"][:10] if positions else None,
                             "reinvest_after_exit":False}
    if anchor is not None:
        assert len(positions) == 1, "Anchor must complete exactly one lifecycle"
        return result
    equity = pd.Series([r["strategy"] for r in eq], index=prepared.period.index)
    benchmark = req.initial_capital * prepared.period["close"] / prepared.period["close"].iloc[0]
    summary, _ = calculate_metrics(equity, benchmark, positions, req.initial_capital, exposure_days, len(eq),
                                   pf.total_commission, pf.total_slippage_cost, sum(e.side == "SELL" for e in pf.executions))
    result["summary"] = summary
    result["exposure"] = exposure_statistics(result)
    return result


def exposure_statistics(result: dict) -> dict:
    eq = result["equity"]
    fractions = [r["market_value"] / r["strategy"] if r["strategy"] else 0 for r in eq]
    exposed = [r for r in eq if r["had_exposure"]]
    invested_close = [r for r in eq if r["quantity"] > 0]
    buys = [e for e in result["executions"] if e["side"] == "BUY"]
    avg_equity = float(np.mean([r["strategy"] for r in eq]))
    traded = math.fsum(e["gross_value"] for e in result["executions"])
    years = (pd.Timestamp(eq[-1]["timestamp"]) - pd.Timestamp(eq[0]["timestamp"])).days / 365.25
    return {"time_in_market_pct": len(exposed) / len(eq) * 100,
            "average_close_capital_exposure_pct": float(np.mean(fractions)) * 100,
            "average_close_cash_pct": (1 - float(np.mean(fractions))) * 100,
            "average_inventory_q0_when_exposed_pct": float(np.mean([r["inventory_fraction_q0"] for r in exposed])) * 100 if exposed else 0,
            "average_inventory_q0_on_positive_close_pct": float(np.mean([r["inventory_fraction_q0"] for r in invested_close])) * 100 if invested_close else 0,
            "average_entry_notional": float(np.mean([e["gross_value"] for e in buys])) if buys else 0,
            "average_entry_shares": float(np.mean([e["quantity"] for e in buys])) if buys else 0,
            "gross_traded_notional": traded, "two_sided_turnover": traded / avg_equity,
            "annualized_two_sided_turnover": traded / avg_equity / years,
            "number_of_entries": len(buys)}
