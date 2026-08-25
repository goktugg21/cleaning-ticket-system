"""hours2 Part 3 — what the admin week grid may PROPOSE for a person.

    "The admin week grid stops multiplying the impossible."

The week-entry dialog used to build its rows as a product — every
selected employee x every selected building x every selected job — so
a cleaner was offered rows in buildings they cannot enter and on jobs
they are not on, and the operator had to know which of the twelve rows
were real. This module answers, per person and per ISO week, the two
questions that product was a substitute for:

  * **which buildings may this person enter** — the same grant tables
    `accounts.scoping.building_ids_for` reads (`BuildingStaffVisibility`
    for STAFF, `BuildingManagerAssignment` for a BUILDING_MANAGER, the
    whole company for a COMPANY_ADMIN), narrowed to the company the
    grid is writing for;
  * **which jobs is this person on** — the ticket slots they hold
    (`TicketStaffAssignment`) and, for the week asked about, the days
    the plan put them on (`ExtraWorkPlannedHours.date`) via the ticket
    that plan spawned.

`assignments` is the week's proposal: one row per (person, ticket) the
grid seeds with the ticket's building prefilled and the hours empty.
`jobs` is the superset the manual "Add row" picker may offer — every
open ticket the person is on, any week — so an exception (they helped
on a job outside its scheduled week) stays possible without offering
a job they were never on.

## Why this lives in `reports/`

`timesheets` imports nothing from `tickets` or `extra_work` — the rule
`HourSource` and `views_week_grid` both state in as many words — and
this read needs both. `reports/` is the app that may read across:
`hour_sources.available_sources` is the sibling question ("which jobs
may hours be logged against at all") and lives here for the same
reason. This is its per-person, per-week narrowing, not a replacement.

## Scoping — nothing new is invented

  * The company is resolved by `timesheets.views_common.
    resolve_view_company`, so an out-of-scope id reads as 404 (no
    existence oracle, H-1).
  * Employees are intersected with `timesheets.scope.
    employees_of_company_queryset(company)` — the same predicate the
    grid's employee picker is filled from. An id outside it is simply
    absent from the answer, which is the same thing a fictional id
    gets.
  * Tickets go through `accounts.scoping.scope_tickets_for` and are
    pinned to the company, so a slot on another tenant's ticket can
    never surface — even if the same person somehow held one.

## Which week a slot belongs to

A slot's own `scheduled_start_at` decides; an undated slot falls back
to its ticket's `scheduled_start_at`. Both are read as LOCAL calendar
dates (`timezone.localtime`), the same rule `tickets.views_work_plan.
_local_date` applies and for the same reason: a 00:30 Amsterdam slot is
stored as 22:30 UTC the previous day, which on a Monday is the previous
WEEK. A slot with neither date is not proposed for any week — it is
still in `jobs`.

## Bounded

A person's `jobs` list is capped (`JOBS_LIMIT`) and says so
(`jobs_truncated`), because "every open ticket somebody has ever been
put on" is unbounded on a real tenant and a picker that silently drops
its tail reads as "these are all of them".

## No money, no hours

This module reads assignments and grants. It reads no `TimeEntry`, sums
nothing and multiplies nothing.
"""
from __future__ import annotations

import datetime

from django.utils import timezone

from timesheets.models import HourSource
from timesheets.weeks import week_bounds


#: Per-person cap on the "every open job you are on" list.
JOBS_LIMIT = 200


def _local_date(value) -> datetime.date | None:
    """The LOCAL calendar date of an aware datetime, or None."""
    if value is None:
        return None
    return timezone.localtime(value).date()


def _job(ticket) -> dict:
    """One offerable job, in the shape `hour_sources.available_sources`
    returns — so the grid's Job column and the picker read one shape."""
    return {
        "source_type": HourSource.TICKET,
        "source_id": ticket.id,
        "title": f"{ticket.ticket_no} — {ticket.title}",
        "building": ticket.building_id,
    }


def _open_tickets(user, company):
    """The tickets `user` may see in `company` that are not finished.

    Mirrors `hour_sources.available_sources`: "not terminal" rather
    than a list of open statuses, so a status added later does not
    quietly start appearing.
    """
    from accounts.scoping import scope_tickets_for
    from tickets.models import TicketStatus

    queryset = scope_tickets_for(user).filter(company=company)
    terminal = [
        status
        for status in (
            getattr(TicketStatus, "CLOSED", None),
            getattr(TicketStatus, "CANCELLED", None),
            getattr(TicketStatus, "REJECTED", None),
        )
        if status is not None
    ]
    if terminal:
        queryset = queryset.exclude(status__in=terminal)
    return queryset


def _building_ids_by_employee(employees, company) -> dict[int, set[int]]:
    """`{employee_id: {building ids they may enter in this company}}`.

    The same three tables `accounts.scoping.building_ids_for` reads, in
    three queries for the whole selection rather than one per person.
    Narrowed to ACTIVE buildings of THIS company: a grant on a retired
    building is not a place hours can be filed today.
    """
    from accounts.models import UserRole
    from buildings.models import (
        Building,
        BuildingManagerAssignment,
        BuildingStaffVisibility,
    )
    from companies.models import CompanyUserMembership

    by_role: dict[str, list[int]] = {}
    for employee in employees:
        by_role.setdefault(employee.role, []).append(employee.id)

    active = Building.objects.filter(company=company, is_active=True)
    out: dict[int, set[int]] = {employee.id: set() for employee in employees}

    staff_ids = by_role.get(UserRole.STAFF, [])
    if staff_ids:
        for user_id, building_id in BuildingStaffVisibility.objects.filter(
            user_id__in=staff_ids, building__in=active
        ).values_list("user_id", "building_id"):
            out[user_id].add(building_id)

    bm_ids = by_role.get(UserRole.BUILDING_MANAGER, [])
    if bm_ids:
        for user_id, building_id in BuildingManagerAssignment.objects.filter(
            user_id__in=bm_ids, building__in=active
        ).values_list("user_id", "building_id"):
            out[user_id].add(building_id)

    ca_ids = by_role.get(UserRole.COMPANY_ADMIN, [])
    if ca_ids:
        members = set(
            CompanyUserMembership.objects.filter(
                user_id__in=ca_ids, company=company
            ).values_list("user_id", flat=True)
        )
        if members:
            every = set(active.values_list("id", flat=True))
            for user_id in members:
                out[user_id] |= every

    return out


def week_assignments(user, company, employees, iso_year: int, iso_week: int) -> dict:
    """The per-person proposal for one ISO week. See the module docstring.

    `employees` is an already-eligible iterable of `User` rows (the view
    intersects the requested ids with `employees_of_company_queryset`).
    """
    from extra_work.models import ExtraWorkPlannedHours
    from tickets.models import StaffAssignmentSlotStatus, TicketStaffAssignment

    monday, sunday = week_bounds(iso_year, iso_week)
    employees = list(employees)
    employee_ids = [employee.id for employee in employees]

    tickets = _open_tickets(user, company)

    # ---- the slots, any date, on open tickets in scope ---------------
    #
    # ONE query for the whole selection. A cancelled slot is a person
    # who was taken OFF the job and must not be proposed for it.
    slots = (
        TicketStaffAssignment.objects.filter(
            user_id__in=employee_ids, ticket__in=tickets
        )
        .exclude(slot_status=StaffAssignmentSlotStatus.CANCELLED)
        .select_related("ticket")
        .order_by("-ticket_id", "-id")
    )

    jobs_by_employee: dict[int, dict[int, dict]] = {
        employee_id: {} for employee_id in employee_ids
    }
    week_by_employee: dict[int, dict[int, dict]] = {
        employee_id: {} for employee_id in employee_ids
    }
    for slot in slots:
        ticket = slot.ticket
        job = _job(ticket)
        jobs_by_employee[slot.user_id].setdefault(ticket.id, job)
        # The slot's own day decides; an undated slot falls back to the
        # ticket's day. Neither: not this week's proposal.
        day = _local_date(slot.scheduled_start_at) or _local_date(
            ticket.scheduled_start_at
        )
        if day is not None and monday <= day <= sunday:
            week_by_employee[slot.user_id].setdefault(ticket.id, job)

    # ---- the plan's days, via the ticket the plan spawned ------------
    #
    # "Ahmet is planned for Tuesday on extra work X" proposes a row on
    # X's operational ticket for Ahmet, whether or not a slot has been
    # cut for him yet — the plan IS the proposal. Two queries, never one
    # per person: the planned (person, extra work) pairs of the week,
    # then the open spawned tickets of those extra works, in scope.
    planned_pairs = list(
        ExtraWorkPlannedHours.objects.filter(
            user_id__in=employee_ids,
            date__gte=monday,
            date__lte=sunday,
            extra_work_request__company=company,
        ).values_list("user_id", "extra_work_request_id")
    )
    if planned_pairs:
        planned_ews = {pair[1] for pair in planned_pairs}
        spawned_by_ew: dict[int, list] = {}
        for ticket in tickets.filter(
            extra_work_request_id__in=planned_ews
        ).only("id", "ticket_no", "title", "building_id", "extra_work_request_id"):
            spawned_by_ew.setdefault(ticket.extra_work_request_id, []).append(
                ticket
            )
        for user_id, ew_id in planned_pairs:
            for ticket in spawned_by_ew.get(ew_id, []):
                job = _job(ticket)
                week_by_employee[user_id].setdefault(ticket.id, job)
                jobs_by_employee[user_id].setdefault(ticket.id, job)

    buildings = _building_ids_by_employee(employees, company)

    people = []
    for employee in employees:
        jobs = list(jobs_by_employee[employee.id].values())
        truncated = len(jobs) > JOBS_LIMIT
        people.append(
            {
                "employee": employee.id,
                "building_ids": sorted(buildings.get(employee.id, set())),
                "assignments": sorted(
                    week_by_employee[employee.id].values(),
                    key=lambda job: job["source_id"],
                ),
                "jobs": sorted(
                    jobs[:JOBS_LIMIT], key=lambda job: -job["source_id"]
                ),
                "jobs_truncated": truncated,
            }
        )

    return {
        "company": company.id,
        "iso_year": iso_year,
        "iso_week": iso_week,
        "week_start": monday.isoformat(),
        "week_end": sunday.isoformat(),
        "employees": people,
    }
