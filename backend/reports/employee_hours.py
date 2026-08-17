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

Every builder goes through `_base`, which applies the SAME PAIR the
entries list applies — `filter_time_entries_for` (the tenant floor, H-1)
and `restrict_entries_to_self` (the privacy floor) — so no report can
show an hour the actor could not already read. The views refuse
CUSTOMER_* outright; these functions do not special-case roles, because a
second role check that disagreed with the first is worse than one.

Sprint 182 §1: only the first half was applied until then, which made
every report in this module readable across the whole company by a
BUILDING_MANAGER.

## The company / building filter (Sprint 180 §1)

`scope` is the `ResolvedScope` the Reports page's own company and
building pickers produce, already validated by `reports.scoping.
resolve_scope` — an actor who may not reach the requested company or
building never gets here, they get a 403. So this layer applies it as
what it is: two extra equality filters on the SAME queryset, never a
second visibility rule. The narrowing is applied on top of
`filter_time_entries_for`, never instead of it: a filter may only ever
show LESS than the actor's own scope.

## One query each

One aggregate over the period, bucketed in Python. Not one query per
building or per employee: a company has fifty workers and a hundred
buildings, and a per-group query is a table that takes a minute to draw.
`assertNumQueries` pins each of them — including with a filter applied,
because a filter that turned a bounded report into a per-group query
would be the same defect arriving by a different door.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum

from timesheets.models import TimeEntry
from timesheets.scope import filter_time_entries_for, restrict_entries_to_self

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


def _base(user, date_from: date, date_to: date, scope=None):
    """The scoped entries of the period, optionally narrowed by the page's
    company / building pickers.

    `scope` is `None` (no filter asked) or a `ResolvedScope`. Both its
    fields are independently optional, so "all companies, this building"
    is expressible — which is what a BUILDING_MANAGER's page sends.
    """
    # Sprint 182 §1 — BOTH halves of the pair. `filter_time_entries_for`
    # answers the tenant question; `restrict_entries_to_self` answers
    # "whose row is it". This called only the first, so a
    # BUILDING_MANAGER — who is not a timesheet manager — read every
    # colleague's hours company-wide through all three of these reports
    # and through the summary cards that share this helper.
    queryset = restrict_entries_to_self(
        user,
        filter_time_entries_for(
            user,
            TimeEntry.objects.filter(date__gte=date_from, date__lte=date_to),
        ),
    )
    if scope is not None:
        if scope.company is not None:
            queryset = queryset.filter(company_id=scope.company.id)
        if scope.building is not None:
            # Entries with NO building drop out of a per-building
            # question by definition. That is the answer, not a loss:
            # "how much was worked HERE" cannot count an hour that says
            # it was worked nowhere.
            queryset = queryset.filter(building_id=scope.building.id)
    return queryset


def _employee_name(row, prefix: str = "employee__") -> str:
    return (
        row.get(f"{prefix}full_name")
        or row.get(f"{prefix}email")
        or f"#{row.get('employee_id')}"
    )


def build_employee_hours_by_building(user, date_from: date, date_to: date, scope=None):
    """Per building, one line per employee, with a building total.

    Buildings are ordered by name and the NULL building sorts last under
    its own heading: `TimeEntry.building` is nullable by design, and
    dropping those rows would make the report's grand total disagree with
    the hours actually logged — the kind of quiet mismatch that costs an
    afternoon to find.
    """
    date_from, date_to = _period(date_from, date_to)
    rows = (
        _base(user, date_from, date_to, scope)
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


def _empty_days() -> dict:
    return {key: ZERO for key in DAY_KEYS}


def _add_day(days: dict, day: date, hours: Decimal) -> None:
    # `weekday()` is 0=Monday, which is already the grid's order.
    days[DAY_KEYS[day.weekday()]] += hours


def _days_as_strings(days: dict) -> dict:
    return {key: str(value) for key, value in days.items()}


def build_employee_hours_weekly(user, date_from: date, date_to: date, scope=None):
    """Per ISO week per employee, Mon-Sun and a total.

    The weekday bucket comes from the DATE rather than from a stored
    column: `TimeEntry` stores `iso_year`/`iso_week` (derived on save)
    but not a weekday, and deriving one on write would be an eleventh
    date column of the kind the product docs argue against.

    ## Sprint 180 §3 — the two things payroll reads that were missing

    **The hour-type split.** A week of 40 hours is not one fact: normal,
    overtime and sick hours are paid differently, and a report that sums
    them into one number cannot be handed to whoever runs payroll. The
    dimension is already on the row — `TimeEntry.hour_type` is NOT NULL
    and the worker-hour report has carried it since Sprint 171 — so this
    is a `values()` entry and a second bucket level, not a new
    computation. The employee's own row keeps the combined figure; the
    split hangs UNDER it, so the shape the screen already showed is
    still the shape it shows.

    **The per-weekday column totals.** "How many hours did the whole
    team work on Wednesday" was answerable only by reading a column with
    a finger. `day_totals` per week is that row, and the payload also
    carries a period-wide one — both summed from the same buckets the
    rows are, so the totals row can never disagree with the rows above
    it.

    Neither costs a query: both are the same single aggregate, bucketed
    differently in Python.
    """
    date_from, date_to = _period(date_from, date_to)
    rows = (
        _base(user, date_from, date_to, scope)
        .values(
            "iso_year",
            "iso_week",
            "employee_id",
            "employee__full_name",
            "employee__email",
            # Sprint 180 §3 — the hour type is part of the GRAIN now.
            # `hour_type` is NOT NULL on a TimeEntry, so there is no
            # "untyped" bucket to invent.
            "hour_type_id",
            "hour_type__name",
            "hour_type__code",
            "date",
        )
        .annotate(hours=Sum("hours"))
        .order_by("iso_year", "iso_week", "employee__full_name", "hour_type__name")
    )

    weeks: "OrderedDict[tuple, dict]" = OrderedDict()
    total = ZERO
    period_day_totals = _empty_days()
    for row in rows:
        week_key = (row["iso_year"], row["iso_week"])
        week = weeks.get(week_key)
        if week is None:
            week = {
                "iso_year": row["iso_year"],
                "iso_week": row["iso_week"],
                "employees": OrderedDict(),
                "day_totals": _empty_days(),
                "hour_types": OrderedDict(),
                "total": ZERO,
            }
            weeks[week_key] = week
        employee = week["employees"].get(row["employee_id"])
        if employee is None:
            employee = {
                "employee": row["employee_id"],
                "employee_name": _employee_name(row),
                "days": _empty_days(),
                "hour_types": OrderedDict(),
                "total": ZERO,
            }
            week["employees"][row["employee_id"]] = employee
        hour_type = employee["hour_types"].get(row["hour_type_id"])
        if hour_type is None:
            hour_type = {
                "hour_type": row["hour_type_id"],
                "hour_type_name": row["hour_type__name"],
                # An empty code in the database is "nobody filled it in";
                # None is the ONE absent-value test the UI already has.
                "hour_type_code": row["hour_type__code"] or None,
                "days": _empty_days(),
                "total": ZERO,
            }
            employee["hour_types"][row["hour_type_id"]] = hour_type

        hours = row["hours"] or ZERO
        day = row["date"]
        _add_day(employee["days"], day, hours)
        _add_day(hour_type["days"], day, hours)
        _add_day(week["day_totals"], day, hours)
        _add_day(period_day_totals, day, hours)
        employee["total"] += hours
        hour_type["total"] += hours
        week["total"] += hours
        total += hours

        # The week-level split, for the totals row and the summary card.
        week_type = week["hour_types"].get(row["hour_type_id"])
        if week_type is None:
            week_type = {
                "hour_type": row["hour_type_id"],
                "hour_type_name": row["hour_type__name"],
                "hour_type_code": row["hour_type__code"] or None,
                "total": ZERO,
            }
            week["hour_types"][row["hour_type_id"]] = week_type
        week_type["total"] += hours

    out = []
    for week in weeks.values():
        out.append(
            {
                "iso_year": week["iso_year"],
                "iso_week": week["iso_week"],
                "total": str(week["total"]),
                "day_totals": _days_as_strings(week["day_totals"]),
                "hour_types": [
                    {**bucket, "total": str(bucket["total"])}
                    for bucket in sorted(
                        week["hour_types"].values(),
                        key=lambda b: (b["hour_type_name"] or "").lower(),
                    )
                ],
                "employees": [
                    {
                        "employee": employee["employee"],
                        "employee_name": employee["employee_name"],
                        "days": _days_as_strings(employee["days"]),
                        "total": str(employee["total"]),
                        "hour_types": [
                            {
                                "hour_type": bucket["hour_type"],
                                "hour_type_name": bucket["hour_type_name"],
                                "hour_type_code": bucket["hour_type_code"],
                                "days": _days_as_strings(bucket["days"]),
                                "total": str(bucket["total"]),
                            }
                            for bucket in sorted(
                                employee["hour_types"].values(),
                                key=lambda b: (b["hour_type_name"] or "").lower(),
                            )
                        ],
                    }
                    for employee in week["employees"].values()
                ],
            }
        )

    return {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "weeks": out,
        "day_totals": _days_as_strings(period_day_totals),
        "total": str(total),
    }


def build_employee_hours_by_extra_work(
    user, date_from: date, date_to: date, scope=None
):
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
        _base(user, date_from, date_to, scope)
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


def build_employee_hours_summaries(user, date_from: date, date_to: date, scope=None):
    """The three hours figures the CARDS show, without building the reports.

    Sprint 180 §2 — the four report cards were a title, a line and a
    button in a grid whose other cards carry a chart, so they rendered as
    tall empty rectangles. A card must say what it found before it is
    opened.

    ## Why this is not "call the four reports"

    It could have been: each builder already returns a `total`. But the
    by-building and weekly builders fetch every (building, employee, day)
    row of the period to produce it, and the ticket report builds a dict
    per ticket — all of it discarded to print four numbers on a card that
    loads on every visit to the Reports page.

    These are three `aggregate()` calls: no row list, no Python
    bucketing, a constant amount of data back whatever the period holds.

    ## Why the totals still cannot drift from the reports

    They read the SAME `_base` queryset with the SAME scope. `total_hours`
    here is `SUM(hours)` over exactly the rows the by-building report
    sums per bucket, which is why the by-building and weekly cards carry
    the same hours figure — they are two groupings of one set of hours,
    and a card that showed two different totals for them would be
    reporting a bug that does not exist.

    ## Query cost

    Three, flat. The distinct week count is its own query because
    counting distinct PAIRS (`iso_year`, `iso_week`) is not something
    `aggregate()` expresses without a database-specific concat, and one
    extra bounded query is cheaper than a portability problem.
    """
    from django.db.models import Count

    from timesheets.models import HourSource

    date_from, date_to = _period(date_from, date_to)
    base = _base(user, date_from, date_to, scope)

    overall = base.aggregate(
        total_hours=Sum("hours"),
        entries=Count("id"),
        employees=Count("employee_id", distinct=True),
        buildings=Count("building_id", distinct=True),
    )
    # `Count(distinct=True)` skips NULLs, so a period whose ONLY hours
    # carry no building reports zero buildings — which is the truth, and
    # is why the by-building report keeps its own "(no building)" bucket.
    weeks = base.values("iso_year", "iso_week").distinct().count()

    extra_work = base.filter(
        source_type=HourSource.EXTRA_WORK, source_id__isnull=False
    ).aggregate(
        total_hours=Sum("hours"),
        entries=Count("id"),
        employees=Count("employee_id", distinct=True),
        jobs=Count("source_id", distinct=True),
    )

    def _hours(value):
        return str(value if value is not None else ZERO)

    return {
        "hours_building": {
            "total_hours": _hours(overall["total_hours"]),
            "entries": overall["entries"],
            "employees": overall["employees"],
            "buildings": overall["buildings"],
        },
        "hours_weekly": {
            "total_hours": _hours(overall["total_hours"]),
            "entries": overall["entries"],
            "employees": overall["employees"],
            "weeks": weeks,
        },
        "hours_extra_work": {
            "total_hours": _hours(extra_work["total_hours"]),
            "entries": extra_work["entries"],
            "employees": extra_work["employees"],
            "jobs": extra_work["jobs"],
        },
    }


def default_period() -> tuple[date, date]:
    """The last 28 days, ending today.

    Four weeks is the span the reference's own hour reports use, and it
    is long enough that a report opened on a Monday morning is not empty.
    """
    from django.utils import timezone

    today = timezone.localdate()
    return today - timedelta(days=27), today
