"""Pure recurrence date arithmetic (recurring day-model).

No DB access. WEEKLY / BIWEEKLY jobs run on a chosen SET of ISO weekdays;
MONTHLY anchors on `start_date`'s day-of-month (clamped) exactly as
before. The engine is bounded by `range_end` / `end_date` so it can never
run away.

Backward compatibility: when `weekdays` is empty for a WEEKLY / BIWEEKLY
job the engine falls back to `{start_date.isoweekday()}`, which reproduces
the legacy single-weekday +7d / +14d series byte-for-byte. MONTHLY is
unchanged.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Iterable, Iterator, Optional

from .models import Frequency
from .weekdays import parse_weekdays


def add_months(d: date, n: int) -> date:
    """Add `n` calendar months to `d`, clamping the day to the target
    month's last valid day (e.g. Jan 31 + 1 month -> Feb 28/29)."""
    # Zero-based month index makes the divmod wrap clean.
    month_index = d.month - 1 + n
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def _normalize_weekdays(weekdays, start_date: date) -> set[int]:
    """Coerce the caller-supplied weekday set into a usable set of ISO
    weekday ints, falling back to start_date's own weekday when empty.

    Accepts either the stored CSV string or an iterable of ints, so both
    the model (`job.weekdays`) and a pre-parsed list work."""
    if weekdays is None:
        parsed: Iterable[int] = []
    elif isinstance(weekdays, str):
        parsed = parse_weekdays(weekdays)
    else:
        parsed = [int(w) for w in weekdays]
    result = {w for w in parsed if 1 <= int(w) <= 7}
    if not result:
        # Empty / unset => legacy single-weekday behaviour.
        return {start_date.isoweekday()}
    return result


def _biweekly_on_week(start_date: date, d: date) -> bool:
    """True when `d` falls in an "on" week for a BIWEEKLY series anchored
    on `start_date`'s ISO week. Week parity is measured between the Monday
    of each date's week, so it is robust across month / year boundaries.
    Week 0 (start_date's own week) is "on"; week 1 is "off"; etc."""
    monday_start = start_date - timedelta(days=start_date.weekday())
    monday_d = d - timedelta(days=d.weekday())
    weeks = (monday_d - monday_start).days // 7
    return weeks % 2 == 0


def iter_occurrence_dates(
    frequency: str,
    start_date: date,
    range_start: date,
    range_end: date,
    end_date: Optional[date] = None,
    weekdays=None,
) -> Iterator[date]:
    """Yield each occurrence date in [max(start_date, range_start),
    min(range_end, end_date)] (inclusive).

    WEEKLY   -> the chosen weekday set, every week.
    BIWEEKLY -> the chosen weekday set, on alternating weeks anchored on
                start_date's ISO week.
    MONTHLY  -> same-day-each-month from start_date (day clamped);
                `weekdays` is ignored.

    `weekdays` may be the stored CSV string, an iterable of ISO weekday
    ints, or None. None / empty for WEEKLY / BIWEEKLY falls back to
    start_date's own weekday (legacy single-weekday behaviour).
    """
    if frequency == Frequency.MONTHLY:
        # Unchanged: step +1 calendar month from start_date, clamping the
        # day. Kept byte-identical to the pre-day-model engine.
        current = start_date
        while current <= range_end and (
            end_date is None or current <= end_date
        ):
            if current >= range_start:
                yield current
            current = add_months(current, 1)
        return

    if frequency not in (Frequency.WEEKLY, Frequency.BIWEEKLY):
        # Unknown frequency: refuse to spin (matches the old contract).
        raise ValueError(f"Unsupported frequency: {frequency!r}")

    wanted = _normalize_weekdays(weekdays, start_date)
    biweekly = frequency == Frequency.BIWEEKLY

    # Day-by-day scan over the bounded window. The horizon is capped at
    # MAX_GENERATION_DAYS_AHEAD (365), so this is at most a few hundred
    # iterations per job — simple and obviously correct.
    effective_end = range_end if end_date is None else min(range_end, end_date)
    lower = max(start_date, range_start)
    current = lower
    while current <= effective_end:
        if current.isoweekday() in wanted and (
            not biweekly or _biweekly_on_week(start_date, current)
        ):
            yield current
        current += timedelta(days=1)
