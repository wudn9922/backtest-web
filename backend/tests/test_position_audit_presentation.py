from __future__ import annotations

from copy import deepcopy

import pytest

from app.presentation.position_audit import classify_stop_execution, present_position_audit


REFERENCE_MA = 31.043206787109376
STOP = REFERENCE_MA * 0.985
OPEN = 31.899227266863253
LOW = 30.035115336865402
ACTUAL_EXECUTION = 30.571443173565676


def _audit() -> dict:
    return {
        "backtest_id": "canonical-simple",
        "position_id": "position-1",
        "ticker": "NVDA",
        "strategy": "simple",
        "position": {"entry_date": "2021-10-14", "final_exit_date": "2021-12-03"},
        "timeline": [
            {
                "date": "2021-12-03",
                "timestamp": "2021-12-03T00:00:00-05:00",
                "open": OPEN,
                "high": 32.027822639120906,
                "low": LOW,
                "close": 30.596343994140625,
                "previous_day_ma": REFERENCE_MA,
                "current_quantity_at_open": 4676,
                "current_quantity_at_close": 0,
                "thresholds": {"ma_half_stop": None},
                "events": [
                    {
                        "event": "MA_EXIT",
                        "source_event": "MA_EXIT",
                        "trigger_level": STOP,
                        "execution_price": ACTUAL_EXECUTION,
                        "shares_before": 4676,
                        "shares_sold": 4676,
                        "shares_remaining": 0,
                    }
                ],
            }
        ],
        "chart": {
            "daily_data": [
                {"timestamp": "2021-12-02T00:00:00-05:00", "reference_ma": 30.95},
                {"timestamp": "2021-12-03T00:00:00-05:00", "reference_ma": REFERENCE_MA},
                {"timestamp": "2021-12-06T00:00:00-05:00", "reference_ma": 31.10},
            ],
            "executions": [],
        },
    }


def _record() -> dict:
    return {
        "strategy": "simple",
        "parameters": {
            "slippage_pct": 0.02,
            "parameters": {"exit_below_ma_pct": 1.5},
        },
    }


def test_intraday_stop_uses_stop_as_raw_fill() -> None:
    result = classify_stop_execution(open_price=101, low_price=98, stop_price=98.5)
    assert result == {"trigger_type": "INTRADAY_STOP", "raw_fill_price": 98.5}


def test_gap_through_uses_open_as_raw_fill() -> None:
    result = classify_stop_execution(open_price=97, low_price=96, stop_price=98.5)
    assert result == {"trigger_type": "GAP_THROUGH", "raw_fill_price": 97.0}


def test_open_below_ma_but_above_actual_stop_is_not_gap_through() -> None:
    result = classify_stop_execution(open_price=99, low_price=98, stop_price=98.5)
    assert result["trigger_type"] == "INTRADAY_STOP"
    assert result["raw_fill_price"] == 98.5


def test_position_one_presentation_reconciles_ma_stop_and_execution() -> None:
    source = _audit()
    before = deepcopy(source)
    result = present_position_audit(source, _record())

    assert source == before  # API enrichment must never mutate persisted audit data.
    day = result["timeline"][0]
    assert day["thresholds"]["simple_ma_exit_stop"] == pytest.approx(STOP)
    detail = day["events"][0]["stop_execution"]
    assert detail["trigger_type"] == "INTRADAY_STOP"
    assert detail["reference_ma"] == pytest.approx(REFERENCE_MA)
    assert detail["active_stop_price"] == pytest.approx(STOP)
    assert detail["raw_fill_price"] == pytest.approx(STOP)
    assert detail["actual_execution_price"] == pytest.approx(ACTUAL_EXECUTION)
    assert detail["actual_execution_price"] == pytest.approx(STOP * (1 - 0.02 / 100))


def test_inactive_stop_is_explicitly_null_before_and_after_position() -> None:
    result = present_position_audit(_audit(), _record())
    rows = result["chart"]["daily_data"]
    assert rows[0]["simple_ma_exit_stop"] is None
    assert rows[1]["simple_ma_exit_stop"] == pytest.approx(STOP)
    assert rows[2]["simple_ma_exit_stop"] is None
    assert all(row["ma_half_stop"] is None for row in rows)

