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

from django.db.models import F, Q
from django_filters import rest_framework as df

from .billing import billing_month, build_ticket_map, is_earned
from .models import ExtraWorkRequest


class ExtraWorkRequestFilter(df.FilterSet):
    # M4 — billing-month + invoice-status filters for the monthly invoice
    # view. Both reuse extra_work.billing (the SAME logic the invoice run
    # uses) and return a queryset (pk__in) so DRF pagination and the other
    # filters still compose. The already-scoped queryset is small, so the
    # one-shot materialisation to compute matching ids is cheap.
    # Sprint 143 §6 — filter by CATALOG category, server-side.
    #
    # The list page's "Categorie" dropdown used to filter on the
    # `ExtraWorkCategory` ENUM, client-side, and this FilterSet had no
    # `category` field at all. It now filters on the real
    # `ServiceCategory` a request's ordered lines came from.
    #
    # Matched against `ExtraWorkRequestItem.snapshot_service_category_name`
    # — the denormalised string written at order time — NOT the live FK.
    # That is deliberate and is what makes the "deleted categories" group
    # possible: the snapshot survives a rename and outlives the category
    # itself, so history stays filterable after the catalog moves on. A
    # live-FK join would silently drop exactly those requests.
    category = df.CharFilter(method="filter_category")

    # Sprint 173 §4 — find the late work and the work started early.
    #
    # Both are DERIVED, so both filter in the database rather than by
    # calling the model property per row: a property filter would
    # materialise the whole table to answer one question. The rule the
    # queries express is the same one `is_overdue` /
    # `started_before_plan` express in Python, and a test pins that the
    # two agree — two definitions of "late" is exactly the drift this
    # sprint is meant to remove.
    overdue = df.BooleanFilter(method="filter_overdue")
    started_early = df.BooleanFilter(method="filter_started_early")
    deadline_before = df.DateFilter(field_name="deadline", lookup_expr="lte")
    deadline_after = df.DateFilter(field_name="deadline", lookup_expr="gte")

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
            # Sprint 127 — per-customer label filters, by id. Both are plain
            # FK `exact` filters so they compose with the existing customer +
            # building filters (the reference implementation filters all four
            # together: Customer + Building + Department + Work Type).
            "department": ["exact"],
            "work_type": ["exact"],
            "status": ["exact", "in"],
            "routing_decision": ["exact"],
            "request_intent": ["exact", "in"],
            "created_by": ["exact"],
        }

    def filter_overdue(self, queryset, name, value):
        from django.utils import timezone

        from .models import ExtraWorkStatus

        if value is None:
            return queryset
        finished = [
            ExtraWorkStatus.COMPLETED,
            ExtraWorkStatus.CANCELLED,
            ExtraWorkStatus.CUSTOMER_REJECTED,
        ]
        late = Q(deadline__isnull=False, deadline__lt=timezone.localdate()) & ~Q(
            status__in=finished
        )
        return queryset.filter(late) if value else queryset.exclude(late)

    def filter_started_early(self, queryset, name, value):
        """Work that began before its planned window opened.

        NOT blocked, only findable — the father was explicit that people
        do this deliberately. The point is that it can be cleaned up
        rather than discovered months later.
        """
        from django.db.models import Min

        from .models import ExtraWorkStatus

        if value is None:
            return queryset
        annotated = queryset.annotate(
            first_start=Min(
                "status_history__created_at",
                filter=Q(
                    status_history__new_status__in=[
                        ExtraWorkStatus.IN_PROGRESS,
                        ExtraWorkStatus.COMPLETED,
                    ]
                ),
            )
        )
        early = Q(preferred_date__isnull=False, first_start__date__lt=F(
            "preferred_date"
        ))
        return (
            annotated.filter(early) if value else annotated.exclude(early)
        )

    def filter_category(self, queryset, name, value):
        """`?category=<name>` — requests holding at least one line
        ordered from a category of that name. Case-insensitive exact
        match on the snapshot, `distinct()` because the join to line
        items multiplies rows."""
        raw = (value or "").strip()
        if not raw:
            return queryset
        return queryset.filter(
            line_items__snapshot_service_category_name__iexact=raw
        ).distinct()

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
