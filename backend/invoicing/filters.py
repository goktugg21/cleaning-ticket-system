"""
Invoicing — Phase 4a list filterset.

Mirrors `extra_work.filters.ExtraWorkRequestFilter`: composes with
`selectors.scope_invoices_for` (the viewset's `get_queryset` scopes first,
then this filterset narrows the already-scoped queryset). The list action
additionally gates on `_is_provider_operator`, so a non-operator never reaches
the filter.
"""
from __future__ import annotations

from django_filters import rest_framework as df

from .models import Invoice


class InvoiceFilter(df.FilterSet):
    class Meta:
        model = Invoice
        fields = {
            "customer": ["exact"],
            "building": ["exact"],
            "status": ["exact"],
            "period_year": ["exact"],
            "period_month": ["exact"],
        }
