"""
Pure-functional business-hours math.

No database access. Operates on tz-aware UTC datetimes; converts internally to
the project timezone (settings.TIME_ZONE) to reason about local business
windows. Two public functions:

- add_business_seconds(start, seconds): walk `seconds` of business time
  forward from `start` and return the resulting UTC datetime.
- business_seconds_between(start, end): how much business time elapsed
  between `start` and `end` (both tz-aware, end >= start).

Business hours are configurable via:
  settings.SLA_BUSINESS_HOURS_START  (hour, minute)
  settings.SLA_BUSINESS_HOURS_END    (hour, minute)
  settings.SLA_BUSINESS_DAYS         iterable of weekdays (Mon=0)

The window is half-open: [start, end). 17:00 sharp is *not* inside the window.
"""
from __future__ import annotations

import datetime
from datetime import timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.conf import settings


def project_tz() -> ZoneInfo:
    return ZoneInfo(settings.TIME_ZONE)


def _business_days() -> tuple[int, ...]:
    return tuple(settings.SLA_BUSINESS_DAYS)


def _business_start_time() -> datetime.time:
    hour, minute = settings.SLA_BUSINESS_HOURS_START
    return datetime.time(hour, minute)


def _business_end_time() -> datetime.time:
    hour, minute = settings.SLA_BUSINESS_HOURS_END
    return datetime.time(hour, minute)


def _is_business_day(date_local: datetime.date) -> bool:
    return date_local.weekday() in _business_days()


def _window_for(
    date_local: datetime.date, tz: ZoneInfo
) -> tuple[datetime.datetime, datetime.datetime]:
    start = datetime.datetime.combine(date_local, _business_start_time(), tzinfo=tz)
    end = datetime.datetime.combine(date_local, _business_end_time(), tzinfo=tz)
    return start, end


def _next_business_day(date_local: datetime.date) -> datetime.date:
    next_day = date_local + timedelta(days=1)
    while not _is_business_day(next_day):
        next_day += timedelta(days=1)
    return next_day


def _advance_to_next_window_start(
    local_dt: datetime.datetime, tz: ZoneInfo
) -> datetime.datetime:
    if _is_business_day(local_dt.date()):
        window_start, window_end = _window_for(local_dt.date(), tz)
        if local_dt < window_start:
            return window_start
        if local_dt < window_end:
            return local_dt
    next_date = _next_business_day(local_dt.date())
    next_start, _ = _window_for(next_date, tz)
    return next_start


def is_business_open(when: datetime.datetime) -> bool:
    if when.tzinfo is None:
        raise ValueError("when must be tz-aware")
    tz = project_tz()
    local = when.astimezone(tz)
    if not _is_business_day(local.date()):
        return False
    window_start, window_end = _window_for(local.date(), tz)
    return window_start <= local < window_end


def add_business_seconds(
    start: datetime.datetime, seconds: int
) -> datetime.datetime:
    if start.tzinfo is None:
        raise ValueError("start must be tz-aware")
    if seconds < 0:
        raise ValueError("seconds must be non-negative")

    tz = project_tz()
    cur = start.astimezone(tz)
    cur = _advance_to_next_window_start(cur, tz)

    if seconds == 0:
        return cur.astimezone(dt_timezone.utc)

    remaining = float(seconds)
    while remaining > 0:
        _, window_end = _window_for(cur.date(), tz)
        room = (window_end - cur).total_seconds()
        if remaining <= room:
            cur = cur + timedelta(seconds=remaining)
            remaining = 0
        else:
            remaining -= room
            next_date = _next_business_day(cur.date())
            cur, _ = _window_for(next_date, tz)

    return cur.astimezone(dt_timezone.utc)


def business_seconds_between(
    start: datetime.datetime, end: datetime.datetime
) -> int:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be tz-aware")
    if end < start:
        raise ValueError("end must be >= start")
    if start == end:
        return 0

    tz = project_tz()
    cur = start.astimezone(tz)
    end_local = end.astimezone(tz)

    cur = _advance_to_next_window_start(cur, tz)
    if cur >= end_local:
        return 0

    total = 0.0
    while cur < end_local:
        _, window_end = _window_for(cur.date(), tz)
        boundary = min(window_end, end_local)
        if boundary > cur:
            total += (boundary - cur).total_seconds()
        if window_end >= end_local:
            break
        next_date = _next_business_day(cur.date())
        cur, _ = _window_for(next_date, tz)

    return int(total)
