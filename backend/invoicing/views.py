"""
Invoicing — HTTP surface.

Phase 3 ships ONLY the provider-only PDF fetch endpoint (the Facturen UI is
Phase 4; customer visibility is Phase 5). The auth + serving pattern mirrors
`extra_work.views_proposals.ProposalPdfView`.
"""
from __future__ import annotations

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status, views
from rest_framework.response import Response

from accounts.permissions import IsAuthenticatedAndActive
from extra_work.views import _is_provider_operator  # reuse (do NOT re-implement)

from .invoice_pdf import render_invoice_pdf
from .selectors import scope_invoices_for


class InvoicePdfView(views.APIView):
    """
    GET /api/invoices/<invoice_id>/pdf/

    Render an invoice as a two-page Dutch PDF. Provider-operator only
    (403 for a customer user / staff); tenant-scoped via scope_invoices_for
    (404 for a cross-tenant or out-of-scope invoice). Customer visibility is
    Phase 5 — customer users cannot reach this endpoint here.
    """

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, invoice_id: int):
        if not _is_provider_operator(request.user):
            return Response(
                {"detail": "Only provider operators can fetch invoice PDFs."},
                status=status.HTTP_403_FORBIDDEN,
            )
        invoice = get_object_or_404(
            scope_invoices_for(request.user).select_related(
                "company", "customer", "building"
            ),
            pk=invoice_id,
        )
        pdf_bytes = render_invoice_pdf(invoice)
        filename = (
            f"factuur-{invoice.number}.pdf"
            if invoice.number
            else f"factuur-draft-{invoice.pk}.pdf"
        )
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response
