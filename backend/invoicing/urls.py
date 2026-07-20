"""Invoicing URL routes. Mounted at /api/invoices/ in config.urls."""
from django.urls import path

from .views import InvoicePdfView

urlpatterns = [
    path("<int:invoice_id>/pdf/", InvoicePdfView.as_view(), name="invoice-pdf"),
]
