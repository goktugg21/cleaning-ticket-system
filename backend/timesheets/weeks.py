"""
Sprint 152 — ISO week helpers and the week-lock gate.

The lock rule in one place, because it is checked from four directions
(entry create, entry update, entry delete, and the date-move that
crosses a boundary) and a rule spread over four call sites is a rule
that ends up enforced in three of them.

INVARIANT (see `models.WeekLock`): absence of a row = the week is OPEN.
"""
from __future__ import annotations

import datetime as _dt

from rest_framework import serializers

from .models import WeekLock


# Stable error code for every "the week is closed" rejection. HTTP 400,
# not 403: the actor is permitted to write here, the target week is what
# refuses. (The permission cases are separately 403 — see
# `permissions.py`.)
ERR_WEEK_CLOSED = "week_closed"


def iso_week_of(date):
    """`(iso_year, iso_week)` for a date. The single place
    `date.isocalendar()` is read outside `TimeEntry.save`, so the two
    can never disagree about which week a date belongs to.
    """
    iso_year, iso_week, _weekday = date.isocalendar()
    return iso_year, iso_week


def week_bounds(iso_year: int, iso_week: int):
    """`(monday, sunday)` dates for an ISO week. Used by the summary /
    export layer to label a week with real dates rather than making
    every consumer redo the ISO arithmetic.
    """
    monday = _dt.date.fromisocalendar(iso_year, iso_week, 1)
    return monday, monday + _dt.timedelta(days=6)


def is_week_closed(company_id: int, iso_year: int, iso_week: int) -> bool:
    """True iff a `WeekLock` row exists for this company + ISO week."""
    if company_id is None:
        return False
    return WeekLock.objects.filter(
        company_id=company_id, iso_year=iso_year, iso_week=iso_week
    ).exists()


def closed_weeks_for(company_id: int) -> set[tuple[int, int]]:
    """Every closed `(iso_year, iso_week)` pair for one company, in ONE
    query — so a list or a report can mark N weeks without running N
    lookups.
    """
    if company_id is None:
        return set()
    return {
        (row[0], row[1])
        for row in WeekLock.objects.filter(company_id=company_id).values_list(
            "iso_year", "iso_week"
        )
    }


def enforce_week_open(company_id: int, date, *, field="date"):
    """Raise a 400 `week_closed` if `date` falls in a closed week of
    `company_id`. Returns silently otherwise.

    Called with the OLD date and again with the NEW one on a date edit,
    which is what makes a move INTO a closed week and a move OUT OF one
    both rejections rather than only the first.
    """
    if date is None:
        return
    iso_year, iso_week = iso_week_of(date)
    if is_week_closed(company_id, iso_year, iso_week):
        raise serializers.ValidationError(
            {
                field: [
                    serializers.ErrorDetail(
                        (
                            f"Week {iso_year}-W{iso_week:02d} is closed. "
                            "Ask an administrator to reopen it before "
                            "changing hours in it."
                        ),
                        code=ERR_WEEK_CLOSED,
                    )
                ]
            }
        )
