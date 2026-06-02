"""Pure recurrence date arithmetic (Sprint 11B Batch 2).

No DB access. The model carries no weekday / byday rules, so every
series anchors strictly on `start_date` and advances by a fixed step
per `Frequency`.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Iterator, Optional

from .models import Frequency


def add_months(d: date, n: int) -> date:
    """Add `n` calendar months to `d`, clamping the day to the target
    month's last valid day (e.g. Jan 31 + 1 month -> Feb 28/29)."""
    # Zero-based month index makes the divmod wrap clean.
    month_index = d.month - 1 + n
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def iter_occurrence_dates(
    frequency: str,
    start_date: date,
    range_start: date,
    range_end: date,
    end_date: Optional[date] = None,
) -> Iterator[date]:
    """Yield each occurrence date in [max(start_date, range_start),
    range_end] (inclusive), anchored on `start_date`.

    Advancing step per frequency: WEEKLY +7d, BIWEEKLY +14d, MONTHLY
    +1 calendar month (day clamped). Dates before `range_start` are
    skipped but advancing continues. `end_date` (inclusive) stops the
    series. The loop is bounded by `range_end` / `end_date` so it can
    never run away.
    """
    current = start_date
    while current <= range_end and (end_date is None or current <= end_date):
        if current >= range_start:
            yield current
        current = _advance(frequency, current)


def _advance(frequency: str, current: date) -> date:
    if frequency == Frequency.WEEKLY:
        return current + timedelta(days=7)
    if frequency == Frequency.BIWEEKLY:
        return current + timedelta(days=14)
    if frequency == Frequency.MONTHLY:
        return add_months(current, 1)
    # Unknown frequency: refuse to spin. Jumping past range_end ends the
    # generator immediately rather than looping forever on an unhandled
    # enum value.
    raise ValueError(f"Unsupported frequency: {frequency!r}")
