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

from .billing import billing_month, build_ticket_map, is_earned
from .models import ExtraWorkRequest


class ExtraWorkRequestFilter(df.FilterSet):
    # M4 — billing-month + invoice-status filters for the monthly invoice
    # view. Both reuse extra_work.billing (the SAME logic the invoice run
    # uses) and return a queryset (pk__in) so DRF pagination and the other
    # filters still compose. The already-scoped queryset is small, so the
    # one-shot materialisation to compute matching ids is cheap.
    billing_period = df.CharFilter(method="filter_billing_period")
    invoice_status = df.ChoiceFilter(
        method="filter_invoice_status",
        choices=(("completed", "completed"), ("invoiced", "invoiced")),
    )

    class Meta:
        model = ExtraWorkRequest
        fields = {
            "customer": ["exact"],
            "building": ["exact"],
            "status": ["exact", "in"],
            "routing_decision": ["exact"],
            "request_intent": ["exact", "in"],
            "created_by": ["exact"],
        }

    def filter_billing_period(self, queryset, name, value):
        # value = "YYYY-MM". Unparseable -> no rows (fail closed: never
        # silently fall through to the full set on a malformed period).
        try:
            year_s, month_s = value.split("-")
            year, month = int(year_s), int(month_s)
        except (ValueError, AttributeError):
            return queryset.none()
        if not (1 <= month <= 12):
            return queryset.none()
        ew_list = list(queryset)
        ticket_map = build_ticket_map([e.id for e in ew_list])
        ids = [
            e.id for e in ew_list
            if billing_month(e, ticket_map.get(e.id)) == (year, month)
        ]
        return queryset.filter(pk__in=ids)

    def filter_invoice_status(self, queryset, name, value):
        if value == "invoiced":
            return queryset.filter(is_invoiced=True)
        if value == "completed":
            # earned (spawned ticket CLOSED) AND not yet invoiced
            ew_list = list(queryset.filter(is_invoiced=False))
            ticket_map = build_ticket_map([e.id for e in ew_list])
            ids = [e.id for e in ew_list if is_earned(ticket_map.get(e.id))]
            return queryset.filter(pk__in=ids)
        return queryset
