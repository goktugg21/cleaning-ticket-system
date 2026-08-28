"""Invoicing URL routes. Mounted at /api/invoices/ in config.urls.

Explicit paths are listed FIRST so they resolve before the router's `<pk>/`
detail route: the Phase-3 provider PDF fetch, then the Phase-5 CUSTOMER read
surface under `my/` (else `/api/invoices/my/` would be caught by the router's
`<pk>/` detail route with pk="my"). The Phase-4a provider REST surface is the
DefaultRouter-registered ViewSet (mirrors `extra_work.urls`).
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CustomerInvoiceDetailView,
    CustomerInvoiceListView,
    CustomerInvoicePdfView,
    InvoicePdfView,
    InvoiceViewSet,
)
from .views_at_risk import BillingMonthAtRiskView


router = DefaultRouter()
router.register(r"", InvoiceViewSet, basename="invoice")


urlpatterns = [
    path("<int:invoice_id>/pdf/", InvoicePdfView.as_view(), name="invoice-pdf"),
    # WP-1 G4 — the billing-month guard (must precede the router include,
    # like `my/`, or the `<pk>/` detail route would eat "at-risk").
    path(
        "at-risk/",
        BillingMonthAtRiskView.as_view(),
        name="invoice-at-risk",
    ),
    # Phase 5 — customer read surface (must precede the router include).
    path("my/", CustomerInvoiceListView.as_view(), name="customer-invoice-list"),
    path(
        "my/<int:invoice_id>/",
        CustomerInvoiceDetailView.as_view(),
        name="customer-invoice-detail",
    ),
    path(
        "my/<int:invoice_id>/pdf/",
        CustomerInvoicePdfView.as_view(),
        name="customer-invoice-pdf",
    ),
    path("", include(router.urls)),
]
