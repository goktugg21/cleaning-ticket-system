"""
Sprint 167 §3 — resolving WHICH standing agreement is in force.

One public function, `active_contract_hours(...)`, plus the queryset
helper the screens use.

The rule, and where it comes from: the row in force on a date is the one
with the latest `valid_from` at or before it, ties broken by `-id`. That
is the same discipline `extra_work.pricing.resolve_price` applies to
`CustomerServicePrice` validity windows, copied deliberately rather than
reinvented — "the latest agreement at or before this date is the current
agreement" already means something in this system, and two different
answers to that question would be a bug that only shows up in hours.

It imports nothing from `extra_work` (or from `contracts`). Different
module, different entity, same discipline.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from django.db.models import Q
from django.utils import timezone


def in_force_on(queryset, on: Optional[date] = None):
    """Narrow a `ContractHours` queryset to the rows whose validity
    window covers `on` (default today).

    A row with `valid_to` NULL is open-ended and always covers a date at
    or after its `valid_from`.
    """
    target = on or timezone.localdate()
    return queryset.filter(valid_from__lte=target).filter(
        Q(valid_to__isnull=True) | Q(valid_to__gte=target)
    )


def active_contract_hours(employee, building, hour_type, on=None):
    """The ONE agreement in force for this (employee, building, hour
    type) on `on`, or None.

    Returns None rather than a zero row when nothing covers the date:
    "there was no agreement" and "the agreement was zero hours" are
    different facts, and a report that conflated them would show a
    building as fully staffed when nobody had agreed anything.
    """
    from .models import ContractHours

    return (
        in_force_on(
            ContractHours.objects.filter(
                employee=employee, building=building, hour_type=hour_type
            ),
            on,
        )
        .order_by("-valid_from", "-id")
        .first()
    )
