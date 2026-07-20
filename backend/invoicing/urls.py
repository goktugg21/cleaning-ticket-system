"""Invoicing URL routes. Mounted at /api/invoices/ in config.urls.

The Phase-3 PDF fetch endpoint is an explicit path (listed FIRST so it
resolves before the router's `<pk>/` detail route); the Phase-4a Invoice
REST surface is a DefaultRouter-registered ViewSet (mirrors
`extra_work.urls`).
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import InvoicePdfView, InvoiceViewSet


router = DefaultRouter()
router.register(r"", InvoiceViewSet, basename="invoice")


urlpatterns = [
    path("<int:invoice_id>/pdf/", InvoicePdfView.as_view(), name="invoice-pdf"),
    path("", include(router.urls)),
]
