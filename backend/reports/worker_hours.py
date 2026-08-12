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
from timesheets.models import ContractHours, TimeEntry
from timesheets.scope import filter_contract_hours_for, filter_time_entries_for


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

    contracted: dict[tuple, Decimal] = {}
    actions: dict[tuple, str] = {}
    agreements = in_force_between(
        filter_contract_hours_for(user, ContractHours.objects.all()),
        start,
        end,
    ).select_related("work_type")
    for agreement in agreements:
        key = (agreement.employee_id, agreement.building_id)
        contracted[key] = contracted.get(key, Decimal("0.00")) + (
            agreement.weekly_total or Decimal("0.00")
        )
        if agreement.work_type_id and key not in actions:
            actions[key] = agreement.work_type.name

    for bucket in buckets.values():
        bucket["debtor"] = debtors.get(bucket["building_id"])
        pair = (bucket["employee_id"], bucket["building_id"])
        bucket["contracted_hours"] = contracted.get(pair)
        bucket["action"] = actions.get(pair)

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
