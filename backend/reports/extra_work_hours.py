"""W3-H — the hours booked to ONE extra work, and what they cost.

    plan §2.8: "an hours grid on the Extra Work (worker x day x hour
    type) and the roll-up of budget / entered / cost."

The model was already there. `TimeEntry.source_type` / `source_id`
(Sprint 173 §1) has made hours attributable to an extra work since
before this sprint; what was missing was anything that READ them back
against the job. This module is that read.

## PLANNED AND ACTUAL, SIDE BY SIDE

The roll-up puts `ExtraWorkRequest.budget_hours` (W2-D, what we said the
job would take) next to the hours actually entered. That pairing is the
whole point of the sprint: in the reference system this comparison
cannot be made at all — `hours_planed` is written by six code paths and
read by nothing that decides anything, and its three guards are dead
(`00-connection-map.md` §4.4; live work 474 carries a budget of 1.00
against 13.5 distributed hours with no warning anywhere).

**Budget hours never touches money.** It sits beside the cost and never
feeds it: `labour_cost` is computed from the WEIGHTED ENTERED hours and
from nothing else. A budget multiplied by a rate would be a forecast
presented as a cost, and there is a test that fails if the two are ever
wired together.

## WHOSE HOURS THE CALLER SEES

The pair, both halves, as `timesheets.scope.restrict_entries_to_self`
demands in capitals: `filter_time_entries_for` answers the tenant
question, `restrict_entries_to_self` answers "whose row is it". Using
one without the other is the Sprint 182 §1 defect — a company-wide leak
of personnel data inside a correctly-scoped tenant.

So:

  * SUPER_ADMIN / COMPANY_ADMIN — the company's rows, and the cost.
  * BUILDING_MANAGER — their OWN rows only, and no cost. `visibility`
    comes back as "self" so the screen can say so rather than let
    somebody read a partial grid as the whole job.
  * STAFF and every customer-side role never reach this: the extra work
    is resolved through `extra_work.scoping.scope_extra_work_for`, which
    returns nothing for STAFF by the P0 staff-privacy decision (A4) and
    nothing outside a customer's own tenant. A worker reads their own
    hours in the timesheets module, where that same pair applies.

**W4-R, and this is why the BM answer is NO COST rather than a total.**
A one-person job's labour cost divided by its hours IS that person's
hourly rate. Handing a BUILDING_MANAGER a job total and an hours total
would hand them a wage by division on every single-worker job, which is
most of them — and a wage is exactly what the owner decided a BM does
not see. There is no partial answer that closes that: rounding it,
bucketing it or showing only the total still divides. So the cost block
is ABSENT for a BM (`cost: null`), on every job, whatever the crew size,
and the same rule keeps a BM out of the rate endpoints entirely
(`reports.labour_rate_scope`). A BM who worked on the job sees their own
hours, as they do everywhere else, and no money beside them.

## COST IS NOT COMPUTED HERE

It is computed in `reports.labour_cost`, which is the one place, and it
is handed the weighted hours this module summed. Nothing in
`timesheets/` is asked for money and nothing here multiplies by a rate.

**W4-R: it is handed them PER PERSON PER DAY, not as one total.** The
rate is now `reports.models.EmployeeHourlyRate` — one row per person
from a date — so pricing an hour needs to know whose hour it was and
which day it fell on. The aggregate below already groups at exactly
that grain for the grid, so the `HourSegment` list is a second reading
of the rows it was fetching anyway, not a second query. Handing over a
single summed figure would force the cost module to guess a rate, and
guessing is how a March raise re-prices January.

## WHY THIS IS NOT THE REPORT NEXT DOOR

`employee_hours.build_employee_hours_by_extra_work` already answers a
question that sounds like this one: it lists, for a PERIOD and across
EVERY job, who worked on what. Different question, different grain — it
has no days, no hour types, no budget and no cost, because a report page
comparing jobs does not want them.

This one answers "everything about THIS job", which is what a detail
page asks. Neither derives anything from the other; what they share is
the scope pair below, which they share by calling the same two helpers
rather than by either one re-implementing it.

## ONE AGGREGATE, WHATEVER THE CREW SIZE

Two queries: one grouped aggregate for the grid, one scalar aggregate
for the travel-cost total. A per-row lookup would be the N+1 the
`assertNumQueries` tests in this app exist to catch.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import DecimalField, F, Sum
from django.db.models.functions import Coalesce

from timesheets.models import HourSource, TimeEntry
from timesheets.scope import (
    filter_time_entries_for,
    is_timesheet_manager,
    restrict_entries_to_self,
)

from .labour_cost import HourSegment, labour_cost


#: How many day columns the grid returns, most recent first-kept.
#:
#: CLAUDE.md #8: a list built from a SERVER collection is never
#: unbounded. Rows are naturally bounded (crew x hour type); the DAYS
#: are not — a job open for a year is 250 columns, which looks fine on
#: seed data and is a wall on real data.
#:
#: The window is on the GRID only. Every total below is computed over
#: every entry, so a truncated grid never produces a truncated total —
#: and `days_omitted` says how many earlier days are not drawn, because
#: a window nobody is told about is indistinguishable from missing data.
MAX_DAY_COLUMNS = 92

_HOURS = DecimalField(max_digits=12, decimal_places=2)


def _hours(value) -> str:
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


def entries_for_extra_work(user, extra_work_id: int):
    """The entries booked to this extra work that `user` may read.

    BOTH halves of the scope pair, in the order
    `timesheets.scope.restrict_entries_to_self` documents. Exported
    rather than inlined so a future second consumer cannot apply half
    of it.
    """
    return restrict_entries_to_self(
        user,
        filter_time_entries_for(
            user,
            TimeEntry.objects.filter(
                source_type=HourSource.EXTRA_WORK,
                source_id=extra_work_id,
            ),
        ),
    )


def planned_hours_for_extra_work(user, extra_work) -> dict:
    """W6-H — the PLAN, per person per day, beside the same grid.

    THE ASYMMETRY THIS CLOSES. `TimeEntry` has always carried a `date`,
    so the actual side of this panel has always been per-day. The plan
    was one total per person, so a manager could see that somebody
    worked 6 hours on Monday and that they were planned 43 hours in
    total, and nothing on the screen could say what Monday was supposed
    to be. Now both sides have days and the comparison is per cell.

    SCOPED THE SAME WAY THE ACTUALS ARE. `entries_for_extra_work`
    narrows the actual rows to self for a non-manager; this narrows the
    planned rows by the same test, off the same `visibility` answer, so
    the two halves of one grid cannot disagree about who the caller is.
    Writing a second scoping rule here is exactly how they would.

    Undated rows are reported separately rather than dropped or dumped
    into an arbitrary column: "planned, day not decided" is a real state
    and a manager needs to see that 12 of the 43 planned hours have not
    been placed on a day yet.
    """
    from extra_work.models import ExtraWorkPlannedHours

    rows = (
        ExtraWorkPlannedHours.objects.filter(extra_work_request=extra_work)
        .select_related("user")
        .order_by("user__full_name", "user__email", "date")
    )
    if not is_timesheet_manager(user):
        rows = rows.filter(user_id=user.id)

    by_employee: dict[int, dict] = {}
    planned_days: set = set()
    total = Decimal("0")
    undated_total = Decimal("0")

    for row in rows:
        entry = by_employee.get(row.user_id)
        if entry is None:
            entry = by_employee[row.user_id] = {
                "employee_id": row.user_id,
                "employee_name": row.user.full_name or row.user.email,
                "days": {},
                "_hours": Decimal("0"),
                "_undated": Decimal("0"),
            }
        entry["_hours"] += row.hours
        total += row.hours
        if row.date is None:
            entry["_undated"] += row.hours
            undated_total += row.hours
        else:
            day = row.date.isoformat()
            planned_days.add(day)
            # (person, day) is unique by constraint, so this is an
            # assignment and not a sum.
            entry["days"][day] = _hours(row.hours)

    return {
        "days": sorted(planned_days),
        "by_employee": [
            {
                "employee_id": entry["employee_id"],
                "employee_name": entry["employee_name"],
                "days": entry["days"],
                "hours": _hours(entry["_hours"]),
                "undated_hours": _hours(entry["_undated"]),
            }
            for entry in by_employee.values()
        ],
        "total_hours": _hours(total),
        "undated_total_hours": _hours(undated_total),
    }


def extra_work_hours_report(user, extra_work) -> dict:
    """The grid, the roll-up and the cost block for one extra work."""
    entries = entries_for_extra_work(user, extra_work.id)

    # ---- the grid: worker x day x hour type, in ONE aggregate --------
    #
    # `weighted` is summed from the SNAPSHOT on each row, never from the
    # live `HourType.multiplier`: an hour booked last year carries the
    # weight it carried then, and reading the live value would re-price
    # history every time somebody edits a multiplier.
    grouped = (
        entries.values(
            "employee_id",
            "employee__full_name",
            "employee__email",
            "hour_type_id",
            "hour_type__name",
            "date",
        )
        .annotate(
            # NOT named `hours`. An annotation alias shadows the column
            # for every OTHER expression in the same `annotate()` call,
            # so `Sum(F("hours") * ...)` would resolve `F("hours")` to
            # this aggregate and Django refuses it outright ("is an
            # aggregate"). Naming it apart keeps `F("hours")` meaning the
            # column, which is what the weight has to multiply.
            summed_hours=Sum("hours"),
            weighted=Sum(
                F("hours") * F("multiplier_snapshot"), output_field=_HOURS
            ),
        )
        .order_by("employee__full_name", "hour_type__name", "date")
    )

    rows: dict[tuple[int, int], dict] = {}
    segments: list[HourSegment] = []
    all_days: set = set()
    total_hours = Decimal("0")
    total_weighted = Decimal("0")

    for record in grouped:
        key = (record["employee_id"], record["hour_type_id"])
        row = rows.get(key)
        if row is None:
            row = rows[key] = {
                "employee_id": record["employee_id"],
                # `full_name` can be blank on an account created by
                # import; the email is what an operator would recognise
                # next, and it is a provider-internal surface.
                "employee_name": (
                    record["employee__full_name"]
                    or record["employee__email"]
                ),
                "hour_type_id": record["hour_type_id"],
                "hour_type_name": record["hour_type__name"],
                "days": {},
                "_hours": Decimal("0"),
                "_weighted": Decimal("0"),
            }
        day = record["date"].isoformat()
        all_days.add(day)
        # A (worker, type, day) cell can only appear once here — it IS
        # the aggregate's grain — so this is an assignment, not a sum.
        row["days"][day] = _hours(record["summed_hours"])
        row["_hours"] += record["summed_hours"] or Decimal("0")
        row["_weighted"] += record["weighted"] or Decimal("0")
        total_hours += record["summed_hours"] or Decimal("0")
        total_weighted += record["weighted"] or Decimal("0")
        # W4-R — the costing grain: whose hours, on which day, weighted.
        # Collected from the SAME aggregate rows the grid is built from,
        # so the rate lookup costs one extra query for the whole crew
        # rather than one per cell. Every entry contributes, including
        # the days the grid window later drops: the window truncates
        # what is DRAWN, never what is counted.
        segments.append(
            HourSegment(
                employee_id=record["employee_id"],
                on_date=record["date"],
                weighted_hours=record["weighted"] or Decimal("0"),
            )
        )

    # W6-H — a day that is PLANNED but not yet worked is a column too.
    # Leaving it out would hide precisely the cell a manager is looking
    # for ("we planned Thursday and nobody booked anything").
    planned_block = planned_hours_for_extra_work(user, extra_work)
    all_days |= set(planned_block["days"])

    ordered_days = sorted(all_days)
    days_omitted = max(0, len(ordered_days) - MAX_DAY_COLUMNS)
    shown_days = ordered_days[days_omitted:]
    shown_set = set(shown_days)

    grid_rows = []
    for row in rows.values():
        grid_rows.append(
            {
                "employee_id": row["employee_id"],
                "employee_name": row["employee_name"],
                "hour_type_id": row["hour_type_id"],
                "hour_type_name": row["hour_type_name"],
                # Only the drawn columns travel; the row TOTAL below is
                # still the whole row, which is why they can differ and
                # why `days_omitted` is reported.
                "days": {
                    day: value
                    for day, value in row["days"].items()
                    if day in shown_set
                },
                "hours": _hours(row["_hours"]),
                "weighted_hours": _hours(row["_weighted"]),
            }
        )

    # ---- travel costs: one scalar aggregate over the SAME rows -------
    #
    # Summed off the entries, never off the grid above: travel is per
    # ENTRY, and the grid's grain would multiply one claim across every
    # hour-type row that shares its day.
    travel_total = entries.aggregate(
        total=Coalesce(
            Sum("travel_costs"),
            Decimal("0"),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        )
    )["total"]

    # ---- the roll-up: planned, actual, and the gap --------------------
    budget = extra_work.budget_hours
    variance = None
    if budget is not None:
        # Positive means over the budget. Hours only — this number never
        # meets a rate (see the module docstring).
        variance = _hours(total_hours - budget)

    manager = is_timesheet_manager(user)
    cost = (
        labour_cost(
            segments=segments,
            travel_costs=travel_total,
            company_id=extra_work.company_id,
        )
        if manager
        else None
    )

    return {
        "extra_work_id": extra_work.id,
        # What the caller is looking at, so the screen can say it out
        # loud. A BUILDING_MANAGER reading their own three hours against
        # a 40-hour budget must not read that as the job's total.
        "visibility": "company" if manager else "self",
        "days": shown_days,
        "days_omitted": days_omitted,
        "rows": grid_rows,
        # W6-H — the plan, per person per day, on the SAME day axis as
        # the rows above. Kept as its own block rather than merged into
        # `rows` because the actual grid's grain is (person, HOUR TYPE,
        # day) and a plan has no hour type: folding it in would have to
        # invent one, or silently attach the plan to whichever type
        # happened to be first.
        "planned": planned_block,
        "totals": {
            "hours": _hours(total_hours),
            "weighted_hours": _hours(total_weighted),
        },
        "rollup": {
            # W2-D's planning number, read and never multiplied.
            "budget_hours": (
                _hours(budget) if budget is not None else None
            ),
            "entered_hours": _hours(total_hours),
            "weighted_hours": _hours(total_weighted),
            "variance_hours": variance,
            # W6-H — what was PLANNED, as distinct from the budget. The
            # budget is the ceiling somebody agreed; this is what was
            # actually distributed across the crew. They are different
            # numbers and the screen must not conflate them.
            "planned_hours": planned_block["total_hours"],
            "planned_undated_hours": planned_block["undated_total_hours"],
        },
        # None for a non-manager: absent, not zero. The screen renders
        # the absence with its reason rather than a figure.
        "cost": cost,
    }
