"""W10 — the weekly sheet is never blank.

Entering a normal week meant typing the same pattern for the same people
every Monday. The pattern was already written down: `ContractHours` says
this person works these hours on these days at this building, from this
date until that one. Nothing read it into the sheet.

So the question "should this person's normal hours fill their weeks?"
is answered ONCE, on the agreement, by `ContractHours.auto_fill`. This
module is what that answer does.

## It writes ordinary worked-hour rows, and invents no table

`ContractHours` owns the AGREEMENT. `TimeEntry` owns WORKED hours. A
filled row is a `TimeEntry` in the ordinary sense, written in the DRAFT
state the week already has, and from that moment the sheet owns it: an
operator edits it exactly like a row they typed, and the next fill
leaves it alone. There is no third model and no second place to write a
worked hour.

## Idempotent, by the only rule that survives editing

A re-run must never double a row, and it must never fight a human. Both
follow from ONE rule: **if that employee already has any row in that
week, the week is theirs and the fill does not touch it.**

Not "skip rows that match", which would re-add a row somebody
deliberately deleted, and would fight anyone who corrected 8.00 to 6.00
by writing the 8.00 back beside it. The unit of ownership is the week,
because the week is the unit the operator works in and the unit the
lock applies to.

## What it refuses

  * a week outside `valid_from..valid_to` — the window does the
    remembering, so an agreement that ended in March stops filling in
    April without anybody switching it off
  * a CLOSED week — `weeks.enforce_week_open` governs every write in
    this module and a generated row is not an exception
  * a day whose agreed hours are zero — a zero row asserts somebody
    worked nothing, which is a claim; an absent row is the absence of
    one
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from .models import ContractHours, HourSource, TimeEntry
from .serializers import snapshot_multiplier
from .weeks import is_week_closed

#: Monday-first, matching `ContractHours`' own seven columns and
#: `date.weekday()`.
_DAY_FIELDS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


@dataclass(frozen=True)
class FillResult:
    """What one fill did. `skipped_*` are counted rather than silently
    dropped so a caller can say why nothing happened."""

    created: int = 0
    skipped_existing: int = 0
    skipped_window: int = 0
    skipped_closed: int = 0

    def __add__(self, other: "FillResult") -> "FillResult":
        return FillResult(
            self.created + other.created,
            self.skipped_existing + other.skipped_existing,
            self.skipped_window + other.skipped_window,
            self.skipped_closed + other.skipped_closed,
        )

    def as_dict(self) -> dict:
        return {
            "created": self.created,
            "skipped_existing": self.skipped_existing,
            "skipped_window": self.skipped_window,
            "skipped_closed": self.skipped_closed,
        }


def week_days(iso_year: int, iso_week: int) -> list[date]:
    """The seven dates of an ISO week, Monday first."""
    monday = date.fromisocalendar(iso_year, iso_week, 1)
    return [monday + timedelta(days=i) for i in range(7)]


def _agreements_for_week(
    company_id: int, days: list[date], employee_id: int | None = None
):
    """Auto-fill agreements whose window overlaps this week at all.

    Overlap, not containment: an agreement that starts on Wednesday
    fills Wednesday to Sunday, and the per-day check below drops the
    days before it. The alternative — requiring the whole week — would
    silently skip the first and last week of every agreement.

    `employee_id` narrows it to ONE person. That is what lets a worker
    fill their own week without writing a row for a colleague — see
    `fill_week`.
    """
    first, last = days[0], days[-1]
    narrowed = (
        {} if employee_id is None else {"employee_id": employee_id}
    )
    return (
        ContractHours.objects.filter(
            company_id=company_id,
            auto_fill=True,
            valid_from__lte=last,
            **narrowed,
        )
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=first))
        .select_related("employee", "hour_type", "building")
        # Ties resolved the way this module already resolves them
        # everywhere else: the latest agreement in force wins.
        .order_by("employee_id", "building_id", "-valid_from", "-id")
    )


@transaction.atomic
def fill_week(
    company_id: int,
    iso_year: int,
    iso_week: int,
    *,
    actor,
    employee_id: int | None = None,
) -> FillResult:
    """Materialise one company-week from its auto-fill agreements.

    Safe to call as often as you like: see the module docstring for why
    the unit of idempotency is the employee-week.

    W12 — `employee_id` fills ONE person's week and nobody else's. The
    unit of idempotency is already the employee-week, so narrowing the
    agreements is the whole change: the same rules, applied to one row
    of the crew instead of all of them. It exists because "my hours"
    is opened by a worker, and a worker asking for their own contracted
    week must not write hours for the colleague at the next building.
    """
    days = week_days(iso_year, iso_week)

    if is_week_closed(company_id, iso_year, iso_week):
        return FillResult(skipped_closed=1)

    agreements = list(_agreements_for_week(company_id, days, employee_id))
    if not agreements:
        return FillResult()

    # Whose weeks are already spoken for. ONE query for the whole week
    # rather than one per agreement.
    taken = set(
        TimeEntry.objects.filter(
            company_id=company_id,
            iso_year=iso_year,
            iso_week=iso_week,
            employee_id__in={a.employee_id for a in agreements},
        ).values_list("employee_id", flat=True)
    )

    # One agreement per employee+building: the queryset is ordered so
    # the row in force is first, and a later, older row for the same
    # pair must not fill a second time.
    seen_pairs: set[tuple[int, int | None]] = set()
    result = FillResult()

    for agreement in agreements:
        pair = (agreement.employee_id, agreement.building_id)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        if agreement.employee_id in taken:
            result += FillResult(skipped_existing=1)
            continue

        multiplier = snapshot_multiplier(agreement.hour_type)
        wrote_any = False

        for index, day in enumerate(days):
            if day < agreement.valid_from:
                result += FillResult(skipped_window=1)
                continue
            if agreement.valid_to is not None and day > agreement.valid_to:
                result += FillResult(skipped_window=1)
                continue

            hours = getattr(agreement, _DAY_FIELDS[index]) or Decimal("0.00")
            if hours <= 0:
                continue

            # The ordinary model write, so `save()` derives iso_year /
            # iso_week from the date and the weighted total stays
            # consistent with every hand-typed row.
            TimeEntry.objects.create(
                company_id=agreement.company_id,
                employee_id=agreement.employee_id,
                building_id=agreement.building_id,
                hour_type=agreement.hour_type,
                date=day,
                hours=hours,
                multiplier_snapshot=multiplier,
                # WHERE the hour came from, using the vocabulary the
                # entries table already filters on.
                source_type=HourSource.CONTRACT,
                source_id=agreement.id,
                created_by=actor,
            )
            wrote_any = True

        if wrote_any:
            result += FillResult(created=1)
            # A second agreement for the same person in this week must
            # not fill on top of the first.
            taken.add(agreement.employee_id)

    return result
