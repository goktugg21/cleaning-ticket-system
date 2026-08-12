"""
Sprint 171 §4 — the Worker Hour Report.

The accounting breakdown at the end of the hours chain: entries,
contract hours, approval, and now the report that comes out of them.

## Why it lives here and not in `timesheets`

It reads `timesheets.TimeEntry` and nothing else today, so `timesheets`
could have hosted it. It lives in `reports/` anyway, for two reasons
that are about where it is GOING rather than where it is: the reference
report carries a contract-hours column beside the worked one, and that
is a cross-module read the moment it is added — `timesheets` may not
import `contracts`. And `reports/` is already the app whose permission
layer answers "who may see cross-module numbers", which this is.

## The shape

One row per (ISO week, worker, building, hour type), with the seven
weekday columns and a total. That is the reference's grain, and it is
the grain the source data has: a `TimeEntry` carries exactly those
four dimensions plus a date, so nothing has to be invented or split.

## One query

The whole report is ONE aggregate over the period, bucketed in Python
by weekday. Not one query per week and not one per worker: the
reference shows four weeks at a time and a company can have fifty
workers, which is 200 queries for a table. `assertNumQueries` pins it.

## What we do NOT hold

The reference also shows personnel number, contract hours, cost-centre
name and code, order number, place, action, debtor, authorisation, hour
code and travel costs. We hold none of them, and this module invents
none — an empty column that looks like data is worse than an absent
one. They are listed in the sprint report as a decision for the owner:
each is a new field on a model.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum

from timesheets.models import TimeEntry
from timesheets.scope import filter_time_entries_for


WEEKDAY_KEYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def week_span(iso_year: int, first_week: int, week_count: int):
    """The `(start, end)` dates covering `week_count` ISO weeks.

    Inclusive of both ends: a report over W29–W32 must contain W32's
    Sunday, and an exclusive end silently drops one day per period —
    the kind of error that only shows up as "the last week is short".
    """
    start = date.fromisocalendar(iso_year, first_week, 1)
    last_week = first_week + max(1, week_count) - 1
    try:
        end = date.fromisocalendar(iso_year, last_week, 7)
    except ValueError:
        # A year with 52 weeks asked for W53: clamp to its last week
        # rather than raising. The operator asked for "four weeks from
        # W51", which is a reasonable thing to ask in December.
        end = date.fromisocalendar(iso_year, 52, 7)
    return start, end


def build_worker_hours(user, iso_year: int, first_week: int, week_count: int):
    """The report payload, scoped to what `user` may see.

    Scoping goes through `filter_time_entries_for`, the same helper the
    entries list uses, so this report can never show an hour the actor
    could not already read. CUSTOMER_* roles are refused at the view;
    this function does not special-case them, because a second
    role-check that disagreed with the first is worse than one.
    """
    start, end = week_span(iso_year, first_week, week_count)

    rows = (
        filter_time_entries_for(
            user,
            TimeEntry.objects.filter(date__gte=start, date__lte=end),
        )
        .values(
            "iso_week",
            "employee_id",
            "employee__full_name",
            "employee__email",
            "building_id",
            "building__name",
            "hour_type_id",
            "hour_type__name",
            "hour_type__standard_slot",
            "date",
        )
        .annotate(hours=Sum("hours"))
        .order_by("iso_week", "employee__full_name", "building__name")
    )

    buckets: dict[tuple, dict] = {}
    for row in rows:
        key = (
            row["iso_week"],
            row["employee_id"],
            row["building_id"],
            row["hour_type_id"],
        )
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "iso_week": row["iso_week"],
                "employee_id": row["employee_id"],
                "employee_name": row["employee__full_name"]
                or row["employee__email"],
                "building_id": row["building_id"],
                # NULL is a legitimate value — hours not tied to a
                # location — so it reads as "no building" rather than
                # being dropped from the report.
                "building_name": row["building__name"],
                "hour_type_id": row["hour_type_id"],
                "hour_type_name": row["hour_type__name"],
                "hour_type_standard_slot": row["hour_type__standard_slot"],
                **{day: Decimal("0.00") for day in WEEKDAY_KEYS},
                "total": Decimal("0.00"),
            }
            buckets[key] = bucket
        weekday = WEEKDAY_KEYS[row["date"].weekday()]
        hours = row["hours"] or Decimal("0.00")
        bucket[weekday] += hours
        bucket["total"] += hours

    ordered = sorted(
        buckets.values(),
        key=lambda b: (
            b["iso_week"],
            (b["employee_name"] or "").lower(),
            (b["building_name"] or ""),
        ),
    )

    return {
        "iso_year": iso_year,
        "first_week": first_week,
        "week_count": week_count,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "weeks": sorted({b["iso_week"] for b in ordered}),
        "rows": [
            {
                **row,
                **{day: str(row[day]) for day in WEEKDAY_KEYS},
                "total": str(row["total"]),
            }
            for row in ordered
        ],
        "totals": {
            "rows": len(ordered),
            "hours": str(sum((b["total"] for b in ordered), Decimal("0.00"))),
            "weeks": len({b["iso_week"] for b in ordered}),
            "workers": len({b["employee_id"] for b in ordered}),
        },
    }
