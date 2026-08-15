"""
Sprint 165 §5 — contracted hours against worked hours.

## Why this lives in `reports/`

`timesheets` imports nothing from `contracts`, and `contracts` imports
nothing from `timesheets`. That is a hard architectural rule in this
repo, not a preference: the timesheets module has to keep working for a
company that uses nothing else, and Sprint 152's docstring says so in
as many words.

So the comparison cannot live in either of them. It lives HERE, in the
app that already reads across modules for exactly this reason —
`reports/scoping.py` reaches into tickets and extra_work today, and its
permissions layer already answers "who may see cross-module numbers".
Adding a third pair of readers is the shape this app is for. Neither
module learns about the other; a third one reads both.

## The two sides are not symmetrical, and the report says so

  * CONTRACTED hours come from `ContractLine.hours`, which is a budget
    per BILLING PERIOD, attached to a revision, optionally attached to a
    building. It has NO employee dimension — a contract says "40 hours a
    month at this building", never "40 hours of Ahmet".
  * WORKED hours come from `timesheets.TimeEntry`, which has an
    employee, a date and an optional building.

Therefore the comparison is per BUILDING, and the employee breakdown
that hangs off it is the WORKED side only. Presenting a per-employee
"contracted" figure would mean inventing an allocation nobody agreed,
so the payload keeps them separate and the UI labels them.

## The period

One calendar MONTH, because that is the only basis both sides share: a
contract's hours are normalised from its billing period to a month
(`MONTHS_PER_PERIOD`), and time entries are summed over the month's
days. A window of arbitrary dates would require pro-rating a monthly
budget across partial months, which is a second proration rule nobody
has asked for.

## Missing sides are ZERO, never dropped

A building with contracted hours and no worked hours is precisely the
row an operator needs — nobody turned up. The reverse (worked hours at
a building with no contract) is the other one. Both appear, with the
missing side as 0.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from django.db.models import Sum


ZERO = Decimal("0.00")


@dataclass
class BuildingComparison:
    building_id: Optional[int]
    building_name: str
    contracted_hours: Decimal = ZERO
    worked_hours: Decimal = ZERO
    # Worked only — see the module docstring on why there is no
    # contracted figure per employee.
    employees: list = field(default_factory=list)

    @property
    def difference(self) -> Decimal:
        """Worked minus contracted. POSITIVE means more was worked than
        contracted; negative means less. The sign is the whole point, so
        it is computed once here rather than in a template."""
        return self.worked_hours - self.contracted_hours


def month_bounds(year: int, month: int):
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    return first, last


def contracted_hours_by_building(company_ids, year: int, month: int) -> dict:
    """`{building_id or None: Decimal}` of contracted hours for the month.

    Reads `contracts` only. One query for the contracts, one for the
    lines — never one per contract.

    A contract counts for the month if it is ACTIVE and the month falls
    inside its dates. The hours come from the revision in force on the
    FIRST of that month, which is the same rule
    `contracts.billing` uses to price a period: what was agreed when the
    period began.
    """
    from contracts.models import (
        MONTHS_PER_PERIOD,
        Contract,
        ContractLifecycle,
    )
    from contracts.revisions import active_revision_ids

    first, last = month_bounds(year, month)

    contracts = list(
        Contract.objects.filter(
            company_id__in=company_ids,
            lifecycle=ContractLifecycle.ACTIVE,
            start_date__lte=last,
        )
        .filter(models_q_end_after(first))
        .prefetch_related("building_links")
    )
    if not contracts:
        return {}

    revision_ids = active_revision_ids([c.id for c in contracts], on=first)
    if not revision_ids:
        return {}

    from contracts.models import ContractLine

    # ONE query for every line of every relevant revision, grouped in
    # Python by (revision, building). A per-contract query here is the
    # per-row cost the assertNumQueries test exists to prevent.
    lines = ContractLine.objects.filter(
        revision_id__in=list(revision_ids.values())
    ).values("revision_id", "building_id", "hours")

    by_revision: dict = {}
    for line in lines:
        by_revision.setdefault(line["revision_id"], []).append(line)

    totals: dict = {}
    for contract in contracts:
        revision_id = revision_ids.get(contract.id)
        if revision_id is None:
            continue
        months = Decimal(MONTHS_PER_PERIOD[contract.billing_period])
        # A line with no building of its own belongs to the contract as
        # a whole. Rather than drop it or invent an allocation, it is
        # attributed to the contract's SINGLE building when it covers
        # exactly one, and to "no building" otherwise — an honest
        # answer in both directions.
        covered = [link.building_id for link in contract.building_links.all()]
        fallback = covered[0] if len(covered) == 1 else None
        for line in by_revision.get(revision_id, []):
            target = line["building_id"] or fallback
            monthly = (line["hours"] or ZERO) / months
            totals[target] = totals.get(target, ZERO) + monthly
    return totals


def models_q_end_after(first):
    """`end_date IS NULL OR end_date >= first` — an open-ended contract
    never stops counting."""
    from django.db.models import Q

    return Q(end_date__isnull=True) | Q(end_date__gte=first)


def worked_hours_by_building(company_ids, year: int, month: int, actor=None):
    """`({building_id or None: Decimal}, {building_id: [(employee, hours)]})`.

    Reads `timesheets` only, and both figures come from ONE aggregate
    query each — the per-building totals and the per-employee
    breakdown — rather than a query per building.

    Sprint 182 §1 — `actor` applies the privacy floor. The per-employee
    breakdown names individual colleagues and their hours, which is
    personnel data whatever the building total beside it is; a
    BUILDING_MANAGER therefore sees only their own line in it. The
    BUILDING TOTAL is deliberately left whole: a building's total worked
    hours is a building-management fact, and a BM manages buildings. That
    is the line this sprint draws — individual rows are restricted,
    building aggregates are not.

    `actor=None` keeps the un-restricted behaviour for a caller that has
    already established manager rights; every in-repo caller passes one.
    """
    from timesheets.models import TimeEntry
    from timesheets.scope import restrict_entries_to_self

    first, last = month_bounds(year, month)
    base = TimeEntry.objects.filter(
        company_id__in=company_ids, date__gte=first, date__lte=last
    )
    per_employee_base = (
        restrict_entries_to_self(actor, base) if actor is not None else base
    )

    totals = {
        row["building_id"]: row["total"] or ZERO
        for row in base.values("building_id").annotate(total=Sum("hours"))
    }

    per_employee: dict = {}
    for row in (
        per_employee_base.values(
            "building_id", "employee_id", "employee__full_name",
            "employee__email",
        )
        .annotate(total=Sum("hours"))
        .order_by("-total")
    ):
        per_employee.setdefault(row["building_id"], []).append(
            {
                "employee_id": row["employee_id"],
                "employee_name": row["employee__full_name"]
                or row["employee__email"],
                "worked_hours": row["total"] or ZERO,
            }
        )
    return totals, per_employee


def build_comparison(company_ids, year: int, month: int, actor=None) -> list:
    """The whole report: one row per building that appears on EITHER
    side, with the missing side as zero.

    The union is deliberate. A building with contracted hours and nobody
    on site is the row an operator most needs to see, and an inner join
    would hide exactly that.
    """
    from buildings.models import Building

    contracted = contracted_hours_by_building(company_ids, year, month)
    worked, per_employee = worked_hours_by_building(
        company_ids, year, month, actor=actor
    )

    building_ids = {b for b in (set(contracted) | set(worked)) if b is not None}
    names = dict(
        Building.objects.filter(id__in=building_ids).values_list("id", "name")
    )

    rows = []
    for building_id in set(contracted) | set(worked):
        rows.append(
            BuildingComparison(
                building_id=building_id,
                building_name=(
                    names.get(building_id, str(building_id))
                    if building_id is not None
                    else ""
                ),
                contracted_hours=_q(contracted.get(building_id, ZERO)),
                worked_hours=_q(worked.get(building_id, ZERO)),
                employees=per_employee.get(building_id, []),
            )
        )
    # Biggest gap first: the rows worth acting on lead.
    rows.sort(key=lambda row: (-abs(row.difference), row.building_name))
    return rows


def _q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))
