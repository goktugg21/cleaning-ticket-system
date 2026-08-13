"""
Sprint 178 §2 — three views of the same hours, and one query each.

    by_building   per building, hours per employee, totalled
    weekly        per ISO week per employee, Mon-Sun and a total
    by_extra_work per extra work, who worked on it and how much

## Why these are not the Sprint 171 Worker Hour Report

That report exists and is not being rebuilt. Its grain is (ISO week,
worker, building, hour type, source) — the reference's own grain, one
row per combination, every payroll column on it. It answers "what does
this week's payroll run look like".

These three answer three different questions, and each COLLAPSES a
dimension the worker report keeps:

  * `by_building` drops the week and the hour type — "who worked here,
    and how much, over this period";
  * `weekly` drops the building and the hour type — "what did each
    person do each week", which is the shape a manager reads down a
    column;
  * `by_extra_work` groups by the SOURCE, which the worker report
    carries but never groups on.

Aggregating the worker report's rows in the client would have been the
other option and is worse: three screens would each re-implement the
same collapse, and the CSV and the screen would drift the first time one
of them changed.

## Why `by_extra_work` was impossible until now

It reads `(source_type, source_id)`, and until Sprint 177 nothing filled
that pair — the column existed, the filter existed, and every row said
OTHER. The job picker added there is what makes this report answerable
at all, and it is why this report will legitimately return NOTHING on
data entered before that sprint. An empty answer here is correct, not
broken.

## Scoping

Every builder goes through `filter_time_entries_for`, the same helper the
entries list uses, so no report can show an hour the actor could not
already read. The views refuse CUSTOMER_* outright; these functions do
not special-case roles, because a second role check that disagreed with
the first is worse than one.

## One query each

One aggregate over the period, bucketed in Python. Not one query per
building or per employee: a company has fifty workers and a hundred
buildings, and a per-group query is a table that takes a minute to draw.
`assertNumQueries` pins each of them.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum

from timesheets.models import TimeEntry
from timesheets.scope import filter_time_entries_for

from .hour_sources import resolve_sources, source_label

# Monday-first, matching the week grid and the worker report.
DAY_KEYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

ZERO = Decimal("0.00")


def _period(date_from: date, date_to: date) -> tuple[date, date]:
    """Order the bounds rather than trusting them.

    A hand-edited URL with `from` after `to` would otherwise return an
    empty report that looks like "no hours" instead of "you asked for a
    negative period".
    """
    return (date_from, date_to) if date_from <= date_to else (date_to, date_from)


def _base(user, date_from: date, date_to: date):
    return filter_time_entries_for(
        user,
        TimeEntry.objects.filter(date__gte=date_from, date__lte=date_to),
    )


def _employee_name(row, prefix: str = "employee__") -> str:
    return (
        row.get(f"{prefix}full_name")
        or row.get(f"{prefix}email")
        or f"#{row.get('employee_id')}"
    )


def build_employee_hours_by_building(user, date_from: date, date_to: date):
    """Per building, one line per employee, with a building total.

    Buildings are ordered by name and the NULL building sorts last under
    its own heading: `TimeEntry.building` is nullable by design, and
    dropping those rows would make the report's grand total disagree with
    the hours actually logged — the kind of quiet mismatch that costs an
    afternoon to find.
    """
    date_from, date_to = _period(date_from, date_to)
    rows = (
        _base(user, date_from, date_to)
        .values(
            "building_id",
            "building__name",
            "employee_id",
            "employee__full_name",
            "employee__email",
        )
        .annotate(hours=Sum("hours"))
        .order_by("building__name", "employee__full_name")
    )

    buildings: "OrderedDict[object, dict]" = OrderedDict()
    total = ZERO
    for row in rows:
        key = row["building_id"]
        bucket = buildings.get(key)
        if bucket is None:
            bucket = {
                "building": key,
                "building_name": row["building__name"],
                "employees": [],
                "total": ZERO,
            }
            buildings[key] = bucket
        hours = row["hours"] or ZERO
        bucket["employees"].append(
            {
                "employee": row["employee_id"],
                "employee_name": _employee_name(row),
                "hours": str(hours),
            }
        )
        bucket["total"] += hours
        total += hours

    ordered = sorted(
        buildings.values(),
        # None last: "no building" is a real bucket but not a place.
        key=lambda b: (b["building_name"] is None, b["building_name"] or ""),
    )
    for bucket in ordered:
        bucket["total"] = str(bucket["total"])

    return {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "buildings": ordered,
        "total": str(total),
    }


def build_employee_hours_weekly(user, date_from: date, date_to: date):
    """Per ISO week per employee, Mon-Sun and a total.

    The weekday bucket comes from the DATE rather than from a stored
    column: `TimeEntry` stores `iso_year`/`iso_week` (derived on save)
    but not a weekday, and deriving one on write would be an eleventh
    date column of the kind the product docs argue against.
    """
    date_from, date_to = _period(date_from, date_to)
    rows = (
        _base(user, date_from, date_to)
        .values(
            "iso_year",
            "iso_week",
            "employee_id",
            "employee__full_name",
            "employee__email",
            "date",
        )
        .annotate(hours=Sum("hours"))
        .order_by("iso_year", "iso_week", "employee__full_name")
    )

    weeks: "OrderedDict[tuple, dict]" = OrderedDict()
    total = ZERO
    for row in rows:
        week_key = (row["iso_year"], row["iso_week"])
        week = weeks.get(week_key)
        if week is None:
            week = {
                "iso_year": row["iso_year"],
                "iso_week": row["iso_week"],
                "employees": OrderedDict(),
                "total": ZERO,
            }
            weeks[week_key] = week
        employee = week["employees"].get(row["employee_id"])
        if employee is None:
            employee = {
                "employee": row["employee_id"],
                "employee_name": _employee_name(row),
                "days": {key: ZERO for key in DAY_KEYS},
                "total": ZERO,
            }
            week["employees"][row["employee_id"]] = employee
        hours = row["hours"] or ZERO
        # `weekday()` is 0=Monday, which is already the grid's order.
        employee["days"][DAY_KEYS[row["date"].weekday()]] += hours
        employee["total"] += hours
        week["total"] += hours
        total += hours

    out = []
    for week in weeks.values():
        out.append(
            {
                "iso_year": week["iso_year"],
                "iso_week": week["iso_week"],
                "total": str(week["total"]),
                "employees": [
                    {
                        "employee": employee["employee"],
                        "employee_name": employee["employee_name"],
                        "days": {
                            key: str(value)
                            for key, value in employee["days"].items()
                        },
                        "total": str(employee["total"]),
                    }
                    for employee in week["employees"].values()
                ],
            }
        )

    return {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "weeks": out,
        "total": str(total),
    }


def build_employee_hours_by_extra_work(user, date_from: date, date_to: date):
    """Per extra work, who worked on it and how much.

    Only rows whose source IS an extra work. Contract and untagged hours
    are excluded on purpose — this report answers "what went into this
    job", and an "Other" bucket holding every untagged hour in the
    company would dwarf the answer.

    The titles come from `resolve_sources`, which scopes them: an id the
    actor cannot open yields no title and renders as "Extra work #41",
    the same answer a deleted one gives. Two queries for the whole
    report, never one per row.
    """
    from timesheets.models import HourSource

    date_from, date_to = _period(date_from, date_to)
    rows = (
        _base(user, date_from, date_to)
        .filter(source_type=HourSource.EXTRA_WORK, source_id__isnull=False)
        .values(
            "source_type",
            "source_id",
            "employee_id",
            "employee__full_name",
            "employee__email",
        )
        .annotate(hours=Sum("hours"))
        .order_by("source_id", "employee__full_name")
    )
    rows = list(rows)

    titles = resolve_sources(
        user, {(row["source_type"], row["source_id"]) for row in rows}
    )

    jobs: "OrderedDict[int, dict]" = OrderedDict()
    total = ZERO
    for row in rows:
        key = row["source_id"]
        job = jobs.get(key)
        if job is None:
            job = {
                "source_type": row["source_type"],
                "source_id": key,
                "title": source_label(row["source_type"], key, titles),
                "employees": [],
                "total": ZERO,
            }
            jobs[key] = job
        hours = row["hours"] or ZERO
        job["employees"].append(
            {
                "employee": row["employee_id"],
                "employee_name": _employee_name(row),
                "hours": str(hours),
            }
        )
        job["total"] += hours
        total += hours

    ordered = sorted(jobs.values(), key=lambda j: (j["title"] or "").lower())
    for job in ordered:
        job["total"] = str(job["total"])

    return {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "extra_work": ordered,
        "total": str(total),
    }


def default_period() -> tuple[date, date]:
    """The last 28 days, ending today.

    Four weeks is the span the reference's own hour reports use, and it
    is long enough that a report opened on a Monday morning is not empty.
    """
    from django.utils import timezone

    today = timezone.localdate()
    return today - timedelta(days=27), today
