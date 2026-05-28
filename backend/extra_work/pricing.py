"""
Sprint 28 Batch 5 — pricing resolver for the Extra Work cart flow.

Single public function: `resolve_price(service, customer, *, on=None)`.

Semantics (authoritative — master plan §5 rule #9 +
docs/project/SPRINT_28_MASTER_PLAN.md §9 decision log row for 2026-05-15):

The resolver returns the customer-specific contract price (a
`CustomerServicePrice` row) when an active row exists for the
`(service, customer)` pair on the given date. It returns `None`
otherwise.

It MUST NOT fall back to `Service.default_unit_price`. The global
default on the catalog row is a provider-side reference number for
the UI; it is NEVER what triggers the instant-ticket path. When this
resolver returns `None`, the caller (Batch 7 cart submission) routes
the line to the proposal flow instead of spawning operational
tickets immediately.

The product spec at
`docs/product/meeting-2026-05-15-system-requirements.md` §5 step 2
contains stale wording that says the resolver "falls back" to the
global default; that wording is explicitly overridden by the master
plan rule #9 + the same-day decision log. The behaviour locked in
here matches the rule, not the stale spec.

Selection rule for multiple active rows: pick the row whose
`valid_from` is latest but still <= `on`. Ties (same `valid_from`)
are broken by `id desc` so the most recently created row wins. This
gives operators a predictable "the latest contract is the current
contract" semantics.

`on` defaults to `date.today()`. Pure / read-only: no side effects.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from django.db import models

from customers.models import Customer

from .models import CustomerServicePrice, Service


def resolve_price(
    service: Service,
    customer: Customer,
    *,
    on: Optional[date] = None,
) -> Optional[CustomerServicePrice]:
    """Resolve the active `CustomerServicePrice` for (service, customer)
    on the given date. See module docstring for the locked semantics.
    """
    target = on or date.today()
    qs = (
        CustomerServicePrice.objects.filter(
            service=service,
            customer=customer,
            is_active=True,
            valid_from__lte=target,
        )
        .filter(
            models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=target)
        )
        .order_by("-valid_from", "-id")
    )
    return qs.first()
