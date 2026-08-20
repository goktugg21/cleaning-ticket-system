"""W7 — planned hours beside worked hours, per person, for ONE job.

    The owner: "If I enter who is supposed to work how many hours, I
    need to be able to see that information in the operational ticket as
    well. If the work is completed, I need to be able to compare: I
    planned this person for X hours. How many hours did they actually
    work?"

Both halves of that comparison already existed and neither could be
read next to the other from an operational screen.
`ExtraWorkPlannedHours` is the plan; `TimeEntry.source_type =
EXTRA_WORK` is the actual; `reports.extra_work_hours` already puts them
in one response. What it could not do is serve the question here,
because that response carries a labour COST and is therefore refused to
STAFF outright — and STAFF are half the people the comparison is about.

So this module answers the smaller question and answers it for
everybody who works the job: per person, planned, worked, and the gap.
No money, no day grid, no hour types, no budget ceiling.

## WHY IT IS NOT THE PANEL NEXT DOOR

`extra_work_hours_report` is the JOB'S full hours picture: a
worker x day x hour-type grid, the budget roll-up, and the cost. It is a
manager's screen and it is served to managers.

This is one question with three numbers in it, mounted where the work
actually happens. Different audience, different grain, and — the part
that matters — a different privacy floor, because with no cost in the
response STAFF may read their own line.

Neither derives from the other. What they share is the pair of scope
helpers below, which they share by CALLING them rather than by either
one restating the rule.

## WHOSE ROWS

Both halves come from `extra_work_hours`' own exported helpers, so there
is exactly one definition of "whose hours are these":

  * `entries_for_extra_work` applies `filter_time_entries_for` AND
    `restrict_entries_to_self` — the pair `timesheets.scope` documents
    in capitals, where using one without the other is a company-wide
    leak of personnel data inside a correctly-scoped tenant.
  * `planned_hours_for_extra_work` narrows the PLAN by the same
    `is_timesheet_manager` test, so the two sides of one row cannot
    disagree about who the caller is.

SUPER_ADMIN and COMPANY_ADMIN read the crew. BUILDING_MANAGER and STAFF
read their own line and nothing else, and `visibility` says which of
those two answers this is — so the screen can title itself honestly
rather than let one person's row be read as the whole job.

Every customer-side role is refused at the door
(`reports.permissions.IsPlannedHoursConsumer`). Planned hours are an
internal staffing decision; a customer buys an outcome.

## PLANNED HOURS NEVER TOUCH MONEY

Nothing in this module multiplies anything by a rate, and the response
carries no money field of any kind. That is the same rule
`ExtraWorkPlannedHours` states on the model and `extra_work_hours`
states in its docstring, restated here because this is the module that
would be tempted: it already has hours per person, which is one join
away from a wage.

## NO ROW IS EVER A ZERO IT DID NOT EARN

`planned_hours` is None for somebody who worked without being planned,
and the job's planned total is None when nobody has been planned at
all. Rendering 0.00 there would state that we planned nobody for no
hours, which is a decision; "not planned" is the absence of one. Any
difference derived from a None plan is None for the same reason.

An actual of 0.00 IS a real zero and is reported as one: a person who is
on the plan and has booked nothing yet is exactly what a manager opens
this panel to find.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum

from timesheets.scope import is_timesheet_manager

from .extra_work_hours import entries_for_extra_work, planned_hours_for_extra_work


def _hours(value) -> str:
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


def planned_vs_actual_report(user, extra_work) -> dict:
    """Per person: planned, worked, and the difference. Plus job totals."""
    # ---- the plan -----------------------------------------------------
    #
    # Reusing the W6-H reader rather than writing a second aggregate:
    # its per-person totals are already summed and — the reason that
    # matters — its self-narrowing is the same one the actuals below
    # get. A private aggregate here would be a second place for the
    # privacy rule to be forgotten.
    #
    # Its `hours` come back as exact 2dp strings, so `Decimal(...)`
    # round-trips them without loss; dated and undated planned hours are
    # both in that total, which is right for this question — a plan that
    # has not been placed on a day is still a plan.
    planned_block = planned_hours_for_extra_work(user, extra_work)
    planned_by_id: dict[int, Decimal] = {}
    names: dict[int, str] = {}
    for row in planned_block["by_employee"]:
        planned_by_id[row["employee_id"]] = Decimal(row["hours"])
        names[row["employee_id"]] = row["employee_name"]

    # ---- the actual ---------------------------------------------------
    #
    # ONE grouped aggregate for the whole crew, not a lookup per person.
    # RAW hours, never `multiplier_snapshot`-weighted: the question is
    # how long somebody was on the job, and a weight is a payroll
    # instrument that would make a night shift read as more hours than
    # were worked.
    actual_rows = (
        entries_for_extra_work(user, extra_work.id)
        .values("employee_id", "employee__full_name", "employee__email")
        .annotate(total=Sum("hours"))
    )
    actual_by_id: dict[int, Decimal] = {}
    for record in actual_rows:
        employee_id = record["employee_id"]
        actual_by_id[employee_id] = record["total"] or Decimal("0")
        names.setdefault(
            employee_id,
            record["employee__full_name"] or record["employee__email"],
        )

    # ---- one row per person on either side ----------------------------
    #
    # The union, not the plan: somebody who worked the job without ever
    # being planned onto it is precisely the case the owner is looking
    # for, and keying off the plan would hide them.
    people = []
    for employee_id in sorted(names, key=lambda pk: (names[pk] or "").lower()):
        planned = planned_by_id.get(employee_id)
        actual = actual_by_id.get(employee_id, Decimal("0"))
        people.append(
            {
                "employee_id": employee_id,
                "employee_name": names[employee_id],
                "planned_hours": _hours(planned) if planned is not None else None,
                "actual_hours": _hours(actual),
                "difference_hours": (
                    _hours(actual - planned) if planned is not None else None
                ),
            }
        )

    has_plan = bool(planned_by_id)
    planned_total = sum(planned_by_id.values(), Decimal("0"))
    actual_total = sum(actual_by_id.values(), Decimal("0"))

    return {
        "extra_work_id": extra_work.id,
        # "company" = the crew. "self" = this caller's own line and
        # nothing else, which is what a BUILDING_MANAGER and a STAFF
        # user get. The screen titles itself off this rather than
        # letting one row be read as the whole job.
        "visibility": "company" if is_timesheet_manager(user) else "self",
        # False = nobody visible to this caller has been planned. The
        # screen says that in words; it must not fall back to zeros.
        "has_plan": has_plan,
        "people": people,
        "totals": {
            "planned_hours": _hours(planned_total) if has_plan else None,
            "actual_hours": _hours(actual_total),
            "difference_hours": (
                _hours(actual_total - planned_total) if has_plan else None
            ),
        },
    }
