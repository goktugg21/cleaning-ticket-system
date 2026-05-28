"""
Sprint 28 follow-up — Extra Work query-param filterset.

Mirrors `tickets.filters.TicketFilter` for the cart-shaped Extra Work
list. Composes with `extra_work.scoping.scope_extra_work_for` (the
view-level `get_queryset` runs scope first, then the filterset
narrows the already-scoped queryset). A CUSTOMER_USER passing a
`?customer=` value outside their own access rows therefore receives
zero rows rather than a 403 / 404 — same defence-in-depth shape the
ticket list uses.

Currently the only filter exposed here is the headline `?customer=<id>`
used by the customer detail "Extra Work" tab. Additional filters
(building, status, urgency, routing_decision) can be added the same
way without redesigning the surface.
"""
from __future__ import annotations

from django_filters import rest_framework as df

from .models import ExtraWorkRequest


class ExtraWorkRequestFilter(df.FilterSet):
    class Meta:
        model = ExtraWorkRequest
        fields = {
            "customer": ["exact"],
            "building": ["exact"],
            "status": ["exact", "in"],
            "routing_decision": ["exact"],
        }
