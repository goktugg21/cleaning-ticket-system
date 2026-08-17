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

## Every reference column, and where each comes from

Sprint 172 §5 — the owner chose to build them all. Half already
existed and needed WIRING, not inventing; the theme of that sprint is
that features sit beside each other without touching.

  Personeelsnr.       StaffProfile.personnel_number      ADDED
  Medewerker          User.full_name                     had it
  Kostenplaats naam   Building.name — in the reference
                      the cost centre IS the building    WIRED
  Kostenplaats code   Building.cost_centre_code          ADDED
  Ordernr.            Building.order_number              ADDED
  Plaats              Building.city                      WIRED
  Handeling           ContractHours.work_type            WIRED
  Debiteur            the Customer behind the building   WIRED
  MACHT               TimeEntry.is_authorised            ADDED (flag —
                      meaning unconfirmed, see the model)
  Urencode            HourType.code                      ADDED
  Uursoort            HourType.name                      had it
  Contr. uren         ContractHours weekly total         WIRED
  Reiskosten          TimeEntry.travel_costs             ADDED

A value that cannot exist for a row is NULL here and an em dash on
screen — never a blank cell and never a zero standing in for
"unknown". A zero travel cost is a claim that nobody travelled; an
absent one is a claim that nobody said.

## The contract-hours column, and why this module may read it

`timesheets` may not import `contracts` and vice versa. Neither rule is
in play here: `ContractHours` lives in `timesheets`, and this module is
in `reports`, the app that exists to read across. The contracted figure
beside the worked one is the whole point of the accounting report, and
it is the same join `hours_comparison.py` already makes.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum

from timesheets.contract_hours import in_force_between
from timesheets.models import ContractHours, ContractHoursStatus, TimeEntry
from timesheets.scope import (
    filter_contract_hours_for,
    filter_time_entries_for,
    restrict_contract_hours_to_self,
    restrict_entries_to_self,
)


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
    # Clamp to the year's OWN last ISO week, which is 52 or 53 — never a
    # hardcoded 52.
    #
    # Sprint 188 §CI: this used to catch the ValueError and clamp to 52.
    # In a 53-WEEK ISO year that silently dropped a whole week: 2026 has
    # 53, so `year=2026&week=51&weeks=4` covered W51-52 and lost W53's
    # hours while the response still said four weeks. December 28th is in
    # the last ISO week of its year by definition, which is the standard
    # way to ask how many weeks a year has.
    last_iso_week = date(iso_year, 12, 28).isocalendar()[1]
    end = date.fromisocalendar(iso_year, min(last_week, last_iso_week), 7)
    return start, end


#: Which standing-agreement statuses count as an agreement.
#:
#: DRAFT is excluded because `ContractHoursStatus`'s own docstring says so
#: in as many words: "Nothing downstream reads a DRAFT row as an
#: agreement." SAVED is INCLUDED — it is submitted for review, and a
#: company that never uses the approve step would otherwise see an empty
#: contracted column forever, which is a silent regression dressed as
#: strictness. If payroll should read APPROVED only, that is this one
#: constant and nothing else.
_CONTRACTED_STATUSES = (
    ContractHoursStatus.SAVED,
    ContractHoursStatus.APPROVED,
)


def _iso_week_bounds(iso_year: int, iso_week: int) -> tuple[date, date]:
    """Monday and Sunday of one ISO week."""
    monday = date.fromisocalendar(iso_year, iso_week, 1)
    return monday, monday + timedelta(days=6)


def _contracted_by_week(user, start: date, end: date):
    """`({(week, employee, building, hour_type): weekly_total}, {...: action})`.

    Sprint 182 §2 — the contracted column, rebuilt. It had four separate
    defects, and because they compounded, the number payroll reads could
    be wrong in four different directions at once:

    1. **It SUMMED every overlapping agreement** instead of resolving the
       one in force. Two successive agreements — the old one ending, the
       new one starting — both overlap the window, so a worker whose
       contract changed mid-report was reported as contracted for the
       sum of both. `active_contract_hours` documents the rule this
       system already uses ("the latest `valid_from` at or before the
       date, ties broken by `-id`"); it just was not applied here.
    2. **A DRAFT counted.** It passed `ContractHours.objects.all()`, so a
       half-written row nobody had submitted was read as an agreement —
       contradicting the model's own status docstring. See
       `_CONTRACTED_STATUSES`.
    3. **It keyed on `(employee, building)`** while the report row's
       grain is `(week, employee, building, hour_type, source)`. Every
       hour-type row of a person at a building therefore showed the SAME
       contracted figure — the sum of that person's agreements across all
       hour types — so a sick-leave row claimed the normal-hours contract
       as its own.
    4. **The fourth, read from the code rather than handed to me: there
       was no WEEK in the key at all.** The report is per ISO week and
       can span many (`week_count`), but `in_force_between(start, end)`
       was asked once for the WHOLE span and its answer written onto
       every week's rows. An agreement in force for only the first week
       of a four-week report was reported as contracted in all four; one
       that ended in week 31 kept appearing in weeks 32, 33 and 34. The
       column was not describing the week its row is about.

    The resolution combines the two rules this codebase already has,
    rather than inventing a third: the WEEK overlap test from
    `in_force_between` (Sprint 168 §2 — an agreement starting on Tuesday
    is genuinely part of that week) picks the candidates, and
    `active_contract_hours`'s latest-wins ordering (Sprint 167 §3) picks
    the winner among them.

    Cost: still ONE query for the whole report, grouped in Python. A
    per-week or per-row query here is exactly the N+1 `assertNumQueries`
    exists to catch, and the fix must not buy correctness with it.
    """
    agreements = list(
        restrict_contract_hours_to_self(
            user,
            in_force_between(
                filter_contract_hours_for(
                    user,
                    ContractHours.objects.filter(
                        status__in=_CONTRACTED_STATUSES
                    ),
                ),
                start,
                end,
            ),
        )
        .select_related("work_type")
        # Latest agreement last, so the straightforward "last one wins"
        # loop below implements `active_contract_hours`'s documented
        # ordering (latest `valid_from`, ties broken by the higher id).
        .order_by("valid_from", "id")
    )
    if not agreements:
        return {}, {}

    contracted: dict[tuple, Decimal] = {}
    actions: dict[tuple, str] = {}

    # Every ISO week the report covers, derived from the span rather than
    # from the rows — a week with no worked hours still has a contract,
    # and asking the rows would hide exactly that case.
    cursor = start
    while cursor <= end:
        iso_year, iso_week, _ = cursor.isocalendar()
        week_start, week_end = _iso_week_bounds(iso_year, iso_week)
        for agreement in agreements:
            # The same overlap test `in_force_between` applies, now asked
            # of ONE week instead of the whole span.
            if agreement.valid_from > week_end:
                continue
            if agreement.valid_to is not None and agreement.valid_to < week_start:
                continue
            key = (
                iso_week,
                agreement.employee_id,
                agreement.building_id,
                agreement.hour_type_id,
            )
            # Overwrite, never add: the ordering above means the last
            # writer is the agreement in force.
            contracted[key] = agreement.weekly_total or Decimal("0.00")
            actions[key] = (
                agreement.work_type.name if agreement.work_type_id else None
            )
        cursor = week_start + timedelta(days=7)

    return contracted, {k: v for k, v in actions.items() if v}


def build_worker_hours(user, iso_year: int, first_week: int, week_count: int):
    """The report payload, scoped to what `user` may see.

    Scoping goes through the SAME PAIR the entries list uses —
    `filter_time_entries_for` for the tenant floor (H-1) and
    `restrict_entries_to_self` for the privacy floor — so this report can
    never show an hour the actor could not already read. CUSTOMER_* roles
    are refused at the view; this function does not special-case them,
    because a second role-check that disagreed with the first is worse
    than one.

    **Sprint 182 §1 — this docstring used to say exactly that while the
    code applied only the first half.** A BUILDING_MANAGER is not a
    timesheet manager (`timesheets.scope.is_timesheet_manager`), so
    without `restrict_entries_to_self` they read every colleague's hours,
    personnel number and travel-cost claims across the whole company.
    Not a tenant breach — the company scope held — but a privacy hole
    inside it, reachable through the Reports page, and the file asserted
    it was closed. The pair is applied now, and the same pair is applied
    to the contracted-hours read below.
    """
    start, end = week_span(iso_year, first_week, week_count)

    rows = (
        restrict_entries_to_self(
            user,
            filter_time_entries_for(
                user,
                TimeEntry.objects.filter(date__gte=start, date__lte=end),
            ),
        )
        .values(
            "iso_week",
            "employee_id",
            "employee__full_name",
            "employee__email",
            # Sprint 172 §5 — every reference column, joined in the ONE
            # aggregate rather than fetched per row. A per-row lookup of
            # the customer behind a building is exactly the N+1 the
            # query-count test exists to catch.
            "employee__staff_profile__personnel_number",
            "building_id",
            "building__name",
            "building__city",
            "building__cost_centre_code",
            "building__order_number",
            # Sprint 173 §1 — the source is part of the row's GRAIN, not
            # a decoration: two hours on the same day for the same
            # worker, one from a ticket and one from the contract, are
            # two different facts and must not be summed into one row.
            "source_type",
            "source_id",
            "hour_type_id",
            "hour_type__name",
            "hour_type__code",
            "hour_type__standard_slot",
            "is_authorised",
            "travel_costs",
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
            row["source_type"],
            row["source_id"],
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
                "source_type": row["source_type"],
                "source_id": row["source_id"],
                # Filled after the loop, from ONE query per source type.
                "source_label": None,
                "hour_type_id": row["hour_type_id"],
                "hour_type_name": row["hour_type__name"],
                "hour_type_code": row["hour_type__code"] or None,
                "hour_type_standard_slot": row["hour_type__standard_slot"],
                # An empty string in the database is "nobody filled it
                # in", and the screen shows an em dash for it. Coercing
                # to None here means the UI has ONE absent-value test
                # rather than one per column.
                "personnel_number": row[
                    "employee__staff_profile__personnel_number"
                ]
                or None,
                "cost_centre_name": row["building__name"],
                "cost_centre_code": row["building__cost_centre_code"] or None,
                "order_number": row["building__order_number"] or None,
                "place": row["building__city"] or None,
                # Filled after the loop: both need a second, BOUNDED
                # query rather than one per row.
                "debtor": None,
                "action": None,
                "contracted_hours": None,
                "is_authorised": row["is_authorised"],
                "travel_costs": Decimal("0.00")
                if row["travel_costs"] is not None
                else None,
                **{day: Decimal("0.00") for day in WEEKDAY_KEYS},
                "total": Decimal("0.00"),
            }
            buckets[key] = bucket
        weekday = WEEKDAY_KEYS[row["date"].weekday()]
        hours = row["hours"] or Decimal("0.00")
        bucket[weekday] += hours
        bucket["total"] += hours
        # Travel costs SUM across the row's days: the report row is a
        # week, and two trips in one week are two costs. NULL stays NULL
        # until something is actually claimed — an absent claim is not a
        # claim of zero.
        if row["travel_costs"] is not None:
            bucket["travel_costs"] = (
                bucket["travel_costs"] or Decimal("0.00")
            ) + row["travel_costs"]

    # ---- the two columns that need a second read -------------------
    #
    # BOTH are bounded: one query for every building in the report and
    # one for every contract-hours row in the window, joined in Python.
    # A per-row lookup would be N+1 twice over, which is exactly what
    # `assertNumQueries` is there to catch.
    building_ids = {b["building_id"] for b in buckets.values() if b["building_id"]}
    debtors: dict[int, str] = {}
    if building_ids:
        from customers.models import CustomerBuildingMembership

        for membership in CustomerBuildingMembership.objects.filter(
            building_id__in=building_ids
        ).select_related("customer"):
            # First customer wins where a building serves several: the
            # reference prints ONE debtor per row, and picking the
            # lowest id is at least stable between runs. Recorded rather
            # than hidden — a building under two customers is a real
            # shape in this system.
            debtors.setdefault(membership.building_id, membership.customer.name)

    contracted, actions = _contracted_by_week(user, start, end)

    # Sprint 173 §1 — resolve every source in ONE pass. The resolver
    # scopes through the same helpers the ticket and extra-work lists
    # use, so an id the actor could not open yields no title.
    from .hour_sources import resolve_sources, source_label

    source_titles = resolve_sources(
        user,
        {(b["source_type"], b["source_id"]) for b in buckets.values()},
    )

    for bucket in buckets.values():
        bucket["source_label"] = source_label(
            bucket["source_type"], bucket["source_id"], source_titles
        )
        bucket["debtor"] = debtors.get(bucket["building_id"])
        # Sprint 182 §2 — the key is the report row's OWN grain: the week,
        # the person, the building AND the hour type. It used to be
        # (employee, building), which is a coarser thing than the row it
        # was being written onto.
        key = (
            bucket["iso_week"],
            bucket["employee_id"],
            bucket["building_id"],
            bucket["hour_type_id"],
        )
        bucket["contracted_hours"] = contracted.get(key)
        bucket["action"] = actions.get(key)

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
                # Decimals as STRINGS, never floats: money and hours in
                # this codebase do not go through binary floating point,
                # and JSON has no decimal type. `None` stays `None` so
                # the UI can tell "nothing claimed" from "0.00 claimed".
                "contracted_hours": (
                    str(row["contracted_hours"])
                    if row["contracted_hours"] is not None
                    else None
                ),
                "travel_costs": (
                    str(row["travel_costs"])
                    if row["travel_costs"] is not None
                    else None
                ),
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
