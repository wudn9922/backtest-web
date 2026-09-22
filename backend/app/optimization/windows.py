from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class RollingWindow:
    index: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    planned_test_end: date
    complete: bool

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        return {
            key: value.isoformat() if isinstance(value, date) else value
            for key, value in payload.items()
        }


def add_calendar_months(value: date, months: int) -> date:
    """Advance by calendar months, clamping only impossible month-end days."""
    ordinal = value.month - 1 + months
    year = value.year + ordinal // 12
    month = ordinal % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def build_rolling_six_month_windows(start: date, end: date) -> list[RollingWindow]:
    """Build prior-six-calendar-month train -> next-six-month test pairs.

    Boundaries are calendar boundaries.  The canonical engine later maps them
    to the actual exchange sessions present in the daily dataset.
    """
    windows: list[RollingWindow] = []
    train_start = start
    index = 1
    while True:
        test_start = add_calendar_months(train_start, 6)
        train_end = test_start - timedelta(days=1)
        if train_end > end or test_start > end:
            break
        next_boundary = add_calendar_months(test_start, 6)
        planned_test_end = next_boundary - timedelta(days=1)
        complete = planned_test_end <= end
        test_end = planned_test_end if complete else end
        if test_end <= test_start:
            break
        windows.append(RollingWindow(
            index=index,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            planned_test_end=planned_test_end,
            complete=complete,
        ))
        if not complete:
            break
        train_start = test_start
        index += 1
    return windows
