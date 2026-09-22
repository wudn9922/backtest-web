from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from app.backtest.indicators import add_indicators
from app.backtest.execution import execution_policy
from app.backtest.audit import build_position_audits, capture_strategy_snapshot, make_daily_audit
from app.backtest.metrics import calculate_metrics, monthly_returns
from app.backtest.models import BacktestError, BacktestRequest, StrategyName, StrategyState
from app.backtest.portfolio import Portfolio, initial_quantity
from app.backtest.strategies import AdvancedDay1StopMABreakout, AdvancedMABreakout, SimpleMABreakout
from app.backtest.strategies.base import Bar, EventRecorder


DAILY_EXECUTION_WARNING = (
    "This backtest uses daily OHLC data. When multiple intraday events could occur "
    "on the same day and their order cannot be determined, the engine uses "
    "conservative adverse-first assumptions."
)
EXECUTION_WARNINGS = {
    "conservative": DAILY_EXECUTION_WARNING,
    "ohlc_heuristic": "This backtest uses a heuristic intraday path assumption: up/flat days follow Open → Low → High → Close; down days follow Open → High → Low → Close. This is not a real intraday price path.",
    "favorable": "This backtest uses favorable ordering only when Daily OHLC cannot determine same-day event order. Known opening gaps and unambiguous events are still executed normally.",
}


def _number(value: Any) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


class BacktestEngine:
    code_version = "0.4.0-entry-zone-v2"
    strategy_version = 2

    def run(self, request: BacktestRequest, daily: pd.DataFrame, provider: str = "synthetic") -> dict[str, Any]:
        self.position_audits: dict[str, dict[str, Any]] = {}
        self._validate_frame(daily)
        p = request.parameters
        enriched = add_indicators(
            daily,
            ma_type=p.ma_type,
            ma_period=p.ma_period,
            atr_period=p.atr_period,
            bias_lookback=p.bias_lookback,
        )
        requested_mask = [request.start_date <= idx.date() <= request.end_date for idx in enriched.index]
        requested_period = enriched.loc[requested_mask].copy()
        required = ["reference_ma"] if request.strategy == StrategyName.SIMPLE else ["reference_ma", "reference_atr", "reference_bias_sigma"]
        usable = requested_period.dropna(subset=required)
        if usable.empty:
            code = "NOT_ENOUGH_MA_LOOKBACK" if request.strategy == StrategyName.SIMPLE else "NOT_ENOUGH_BIAS_HISTORY"
            raise BacktestError(code, "Not enough completed indicator history for the requested period.")
        first_usable = usable.index[0]
        period = requested_period.loc[first_usable:]

        recorder = EventRecorder()
        policy = execution_policy(request.execution_policy)
        if request.strategy == StrategyName.SIMPLE:
            strategy = SimpleMABreakout(p, recorder, policy)
        elif request.strategy == StrategyName.ADVANCED_DAY1_STOP:
            strategy = AdvancedDay1StopMABreakout(p, recorder, policy)
        else:
            strategy = AdvancedMABreakout(p, recorder, policy)
        portfolio = Portfolio(request.initial_capital, request.commission_pct, request.slippage_pct)
        previous_daily = enriched.shift(1)
        equity_rows: list[dict[str, Any]] = []
        daily_audits: list[dict[str, Any]] = []
        warnings = [EXECUTION_WARNINGS[request.execution_policy]]
        exposure_days = 0

        for day_index, (daily_ts, day_row) in enumerate(period.iterrows()):
            trading_day = daily_ts.date()
            reference_ma = float(day_row["reference_ma"])
            reference_atr = _number(day_row.get("reference_atr"))
            sigma = _number(day_row.get("reference_bias_sigma"))
            bar = Bar(
                daily_ts.to_pydatetime(),
                *(float(day_row[name]) for name in ["open", "high", "low", "close", "volume"]),
            )
            previous_volume = _number(previous_daily.loc[daily_ts, "volume"]) if daily_ts in previous_daily.index else None
            open_snapshot = capture_strategy_snapshot(strategy, portfolio.quantity)
            event_start = len(recorder.events)
            execution_start = len(portfolio.executions)
            entry_level = reference_ma + reference_ma * p.entry_stop_pct / 100
            entry_raw = max(bar.open, entry_level)
            buy_qty = initial_quantity(
                portfolio.equity(bar.open),
                request.position_size_pct,
                entry_raw,
                request.slippage_pct,
                request.commission_pct,
            )

            def fill(side: str, raw_price: float, qty: int, event_type: str, reason: str, timestamp: datetime) -> None:
                if side == "BUY":
                    execution = portfolio.buy(timestamp, raw_price, qty, event_type, reason)
                    if isinstance(strategy, AdvancedMABreakout):
                        # P0 and Q0 are based on the actual initial execution.
                        strategy.s.entry_price = execution.price
                        strategy.s.q0 = execution.quantity
                        strategy.s.current_qty = execution.quantity
                else:
                    portfolio.sell(timestamp, raw_price, qty, event_type, reason)

            if isinstance(strategy, SimpleMABreakout):
                strategy.process_bar(bar, reference_ma, portfolio.quantity, buy_qty, fill)
                strategy.end_day()
            else:
                strategy.process_bar(
                    bar,
                    trading_day=trading_day,
                    reference_ma=reference_ma,
                    reference_atr=reference_atr,
                    bias_sigma=sigma,
                    buy_qty=buy_qty,
                    fill=fill,
                )
                strategy.end_day(
                    trading_day=trading_day,
                    daily_close=bar.close,
                    daily_high=bar.high,
                    daily_low=bar.low,
                    daily_volume=bar.volume,
                    previous_day_volume=previous_volume,
                    current_day_ma=float(day_row["ma"]),
                    timestamp=bar.timestamp,
                    reference_ma=reference_ma,
                    reference_atr=reference_atr,
                    bias_sigma=sigma,
                )

            had_exposure = bool(open_snapshot["quantity"] or portfolio.quantity or any(item.side == "BUY" for item in portfolio.executions[execution_start:]))
            if day_index == len(period) - 1 and portfolio.quantity and request.force_close_at_end:
                portfolio.sell(bar.timestamp, bar.close, portfolio.quantity, "FINAL_EXIT", "END_OF_BACKTEST")
                if isinstance(strategy, AdvancedMABreakout):
                    strategy.s.current_qty = 0
                    strategy.s.state = StrategyState.CLOSED
                else:
                    strategy.state.state = StrategyState.CLOSED
            close_snapshot = capture_strategy_snapshot(strategy, portfolio.quantity)
            daily_audits.append(make_daily_audit(
                request=request,
                bar=bar,
                current_ma=_number(day_row.get("ma")),
                reference_ma=reference_ma,
                reference_atr=reference_atr,
                bias_sigma=sigma,
                previous_day_volume=previous_volume,
                open_snapshot=open_snapshot,
                close_snapshot=close_snapshot,
                events=recorder.events[event_start:],
                executions=portfolio.executions[execution_start:],
            ))
            if had_exposure:
                exposure_days += 1
            equity_rows.append({"timestamp": daily_ts, "equity": portfolio.equity(bar.close), "close": bar.close})

        if not equity_rows:
            raise BacktestError("NO_DAILY_BARS", "No usable daily bars overlap the strategy period.")
        equity_frame = pd.DataFrame(equity_rows).set_index("timestamp")
        equity = equity_frame["equity"]
        first_price = equity_frame["close"].iloc[0]
        benchmark = request.initial_capital * equity_frame["close"] / first_price
        positions = self._positions(portfolio.executions, period)
        self.position_audits = build_position_audits(
            backtest_id=None,
            ticker=request.ticker,
            strategy=request.strategy.value,
            positions=positions,
            daily_audits=daily_audits,
            enriched=enriched,
            executions=portfolio.executions,
        )
        summary, drawdown = calculate_metrics(
            equity,
            benchmark,
            positions,
            request.initial_capital,
            exposure_days,
            len(equity),
            portfolio.total_commission,
            portfolio.total_slippage_cost,
            sum(e.side == "SELL" for e in portfolio.executions),
        )
        ambiguity_dates = {event.timestamp.date() for event in recorder.events if event.event == "DAILY_INTRABAR_AMBIGUITY"}
        ambiguity_positions = sum(
            any(datetime.fromisoformat(str(position["entry_date"])).date() <= day <= datetime.fromisoformat(str(position["final_exit_date"])).date() for day in ambiguity_dates)
            for position in positions
        )
        summary["ambiguous_days"] = len(ambiguity_dates)
        summary["ambiguous_positions"] = ambiguity_positions
        summary["intrabar_assumption"] = policy.display_name
        if not positions:
            warnings.append("No trades generated")

        warmup_bars = int(sum(idx.date() < request.start_date for idx in enriched.index))
        coverage = {
            "daily_bars_count": len(requested_period),
            "warmup_bars_count": warmup_bars,
            "first_strategy_date": first_usable.date().isoformat(),
            "last_strategy_date": period.index[-1].date().isoformat(),
            "missing_trading_days": 0,
            "data_provider": provider,
            "execution_model": request.execution_model,
            "execution_policy": request.execution_policy,
        }
        reproducibility_parameters = request.parameters.model_dump()
        if request.strategy != StrategyName.ADVANCED_DAY1_STOP:
            reproducibility_parameters.pop("day1_stop_pct", None)
        daily_output = [
            {
                "timestamp": ts.isoformat(),
                **{key: _number(row.get(key)) for key in ["open", "high", "low", "close", "volume", "ma", "reference_ma"]},
            }
            for ts, row in period.iterrows()
        ]
        equity_output = [
            {"timestamp": ts.isoformat(), "strategy": float(equity.loc[ts]), "buy_hold": float(benchmark.loc[ts])}
            for ts in equity.index
        ]
        drawdown_output = [{"timestamp": ts.isoformat(), "drawdown": float(value)} for ts, value in drawdown.items()]
        return {
            "strategy_version": self.strategy_version,
            "summary": summary,
            "equity_curve": equity_output,
            "drawdown": drawdown_output,
            "daily_data": daily_output,
            "executions": [item.as_dict() for item in portfolio.executions],
            "positions": positions,
            "events": [item.as_dict() for item in recorder.events],
            "monthly_returns": monthly_returns(equity),
            "warnings": warnings,
            "data_coverage": coverage,
            "reproducibility": {
                "strategy_parameters": reproducibility_parameters,
                "data_provider": provider,
                "execution_model": request.execution_model,
                "execution_policy": request.execution_policy,
                "commission_pct": request.commission_pct,
                "slippage_pct": request.slippage_pct,
                "code_version": self.code_version,
                "strategy_version": self.strategy_version,
                "daily_first_timestamp": daily.index[0].isoformat(),
                "daily_last_timestamp": daily.index[-1].isoformat(),
            },
        }

    @staticmethod
    def _validate_frame(daily: pd.DataFrame) -> None:
        needed = {"open", "high", "low", "close", "volume"}
        if daily.empty:
            raise BacktestError("NO_HISTORICAL_DATA", "No daily historical data.")
        if not needed.issubset(daily.columns):
            raise BacktestError("INVALID_DATA_SCHEMA", "Daily OHLCV columns are required.")
        if daily.index.tz is None:
            raise BacktestError("DATA_TIMEZONE_MISMATCH", "Daily timestamps must be timezone-aware.")
        if daily.index.has_duplicates:
            raise BacktestError("INVALID_DATA_SCHEMA", "Daily timestamps must be unique.")

    @staticmethod
    def _positions(executions, daily: pd.DataFrame) -> list[dict[str, Any]]:
        result, current = [], None
        for execution in executions:
            if execution.side == "BUY":
                current = {
                    "position_id": f"position-{len(result) + 1}",
                    "entry_date": execution.timestamp.isoformat(),
                    "entry_price": execution.price,
                    "initial_shares": execution.quantity,
                    "total_shares_sold": 0,
                    "buy_cost": execution.gross_value + execution.commission,
                    "sell_proceeds": 0.0,
                    "sell_execution_value": 0.0,
                    "fees": execution.commission,
                    "final_exit_date": None,
                    "exit_final_close_reason": None,
                }
            elif current:
                current["total_shares_sold"] += execution.quantity
                current["sell_proceeds"] += execution.gross_value - execution.commission
                # Reporting only: execution prices include slippage, but gross
                # trading PnL excludes every commission. Keep net cash accounting
                # above unchanged, including its original floating-point order.
                current["sell_execution_value"] += execution.price * execution.quantity
                current["fees"] += execution.commission
                if execution.position_remaining == 0:
                    current["final_exit_date"] = execution.timestamp.isoformat()
                    current["exit_final_close_reason"] = execution.reason
                    net = current["sell_proceeds"] - current["buy_cost"]
                    entry_day = datetime.fromisoformat(current["entry_date"]).date()
                    holding = max(0, (execution.timestamp.date() - entry_day).days)
                    sliced = daily[(daily.index.date >= entry_day) & (daily.index.date <= execution.timestamp.date())]
                    entry_price = current["entry_price"]
                    current.update({
                        "gross_pnl": current["sell_execution_value"] - current["initial_shares"] * entry_price,
                        "net_pnl": net,
                        "realized_pnl": net,
                        "q0": current["initial_shares"],
                        "final_return": net / current["buy_cost"],
                        "return_pct": net / current["buy_cost"] * 100,
                        "holding_days": holding,
                        "maximum_favorable_excursion": float(sliced["high"].max() / entry_price - 1) if len(sliced) else None,
                        "maximum_adverse_excursion": float(sliced["low"].min() / entry_price - 1) if len(sliced) else None,
                    })
                    current.pop("buy_cost")
                    current.pop("sell_proceeds")
                    current.pop("sell_execution_value")
                    result.append(current)
                    current = None
        return result
