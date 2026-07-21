"""
Invoicing — HTTP surface.

  Phase 3  provider-only PDF fetch endpoint (`InvoicePdfView`).
  Phase 4a  the provider Invoice REST surface (`InvoiceViewSet`): list / due /
            retrieve / generate / issue / send / reverse / delete + editable
            draft lines (add / update / remove) + meta PATCH (summary + fee).
  Phase 5   the CUSTOMER read surface (`CustomerInvoice*View`, mounted under
            /api/invoices/my/): a CUSTOMER_USER's own SENT invoices (list /
            detail / PDF), read-only + REDACTED. Kept SEPARATE from the
            provider surface so the gates don't tangle.

Every provider invoice mutation is PROVIDER-OPERATOR-gated (403 for a customer
user / staff) + TENANT-SCOPED via `selectors.scope_invoices_for` (404 for a
cross-tenant / out-of-scope invoice). The customer read is scoped by the
SEPARATE `selectors.scope_customer_invoices_for` (membership-level, SENT-only).
The auth + serving pattern mirrors `extra_work.views`.
"""
from __future__ import annotations

import calendar
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, views, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import IsAuthenticatedAndActive
from accounts.scoping import scope_customers_for
from customers.models import Customer
from extra_work.views import _is_provider_operator  # reuse (do NOT re-implement)

from .filters import InvoiceFilter
from .invoice_pdf import render_invoice_pdf
from .line_services import (
    add_invoice_line,
    remove_invoice_line,
    update_invoice_line,
    update_invoice_meta,
)
from .models import Invoice, InvoiceLine
from .selectors import (
    scope_customer_invoices_for,
    scope_invoices_for,
    unbilled_extra_work,
)
from .serializers import (
    CustomerInvoiceSerializer,
    InvoiceLineSerializer,
    InvoiceLineWriteSerializer,
    InvoiceMetaSerializer,
    InvoiceSerializer,
)
from .services import _earned_amounts, delete_draft_invoice, generate_draft_invoices
from .state_machine import (
    issue_invoice,
    reverse_invoice,
    send_invoice,
    unissue_invoice,
)


def _validation_detail(exc) -> str:
    """Flatten a Django ValidationError (raised by the services / state
    machine on a non-DRAFT edit or an illegal transition) into a string."""
    messages = getattr(exc, "messages", None)
    if messages:
        return " ".join(messages)
    return str(exc)


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


class InvoiceViewSet(viewsets.GenericViewSet):
    """
    The provider Invoice REST surface (Phase 4a). Bare `GenericViewSet` — every
    handler is defined explicitly so it can enforce the operator gate BEFORE
    any work (a customer user / staff gets a stable 403, never an empty 200 /
    404). Tenant scoping is `scope_invoices_for` (company-granularity); a
    cross-tenant id is a 404 via `get_object`.

    Routes (mounted at /api/invoices/ via a DefaultRouter registered at r""):
      GET    /                    list (filter: customer/building/status/
                                       period_year/period_month)
      GET    /due/                the "who's due" list (informational)
      POST   /generate/           generate_draft_invoices
      GET    /<id>/               retrieve (with lines)
      PATCH  /<id>/               update_invoice_meta (summary + fee, DRAFT)
      DELETE /<id>/               delete_draft_invoice (soft-delete + release)
      POST   /<id>/issue/         issue_invoice
      POST   /<id>/send/          send_invoice (allocates the number)
      POST   /<id>/unissue/       unissue_invoice (ISSUED -> DRAFT)
      POST   /<id>/reverse/       reverse_invoice (returns the reversal)
      POST   /<id>/lines/         add_invoice_line
      PATCH  /<id>/lines/<lid>/   update_invoice_line
      DELETE /<id>/lines/<lid>/   remove_invoice_line
    The Phase-3 GET /<id>/pdf/ stays on `InvoicePdfView`.
    """

    permission_classes = [IsAuthenticatedAndActive]
    filterset_class = InvoiceFilter
    serializer_class = InvoiceSerializer

    def get_queryset(self):
        return (
            scope_invoices_for(self.request.user)
            .select_related("company", "customer", "building")
            .prefetch_related("lines")
        )

    def _forbid_non_operator(self, request):
        """Return a 403 Response for a non-operator, else None."""
        if not _is_provider_operator(request.user):
            return Response(
                {"detail": "Only provider operators can manage invoices."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    # -- collection --------------------------------------------------------

    def list(self, request):
        guard = self._forbid_non_operator(request)
        if guard is not None:
            return guard
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = InvoiceSerializer(
                page, many=True, context={"request": request}
            )
            return self.get_paginated_response(serializer.data)
        serializer = InvoiceSerializer(
            qs, many=True, context={"request": request}
        )
        return Response(serializer.data)

    @action(detail=False, methods=["post"], url_path="generate")
    def generate(self, request):
        guard = self._forbid_non_operator(request)
        if guard is not None:
            return guard
        try:
            customer_id = int(request.data["customer"])
            year = int(request.data["year"])
            month = int(request.data["month"])
        except (KeyError, TypeError, ValueError):
            return Response(
                {"detail": "customer (int), year (int), month (1-12) are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not (1 <= month <= 12):
            return Response(
                {"detail": "month must be between 1 and 12."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        granularity = request.data.get("granularity") or None
        # Resolve the customer through the actor's customer scope so a
        # cross-tenant customer id is a clean 404 (never leaks / generates).
        customer = get_object_or_404(
            scope_customers_for(request.user), pk=customer_id
        )
        try:
            created = generate_draft_invoices(
                request.user,
                customer.company_id,
                customer.id,
                year,
                month,
                granularity,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": _validation_detail(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            InvoiceSerializer(
                created, many=True, context={"request": request}
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["get"], url_path="due")
    def due(self, request):
        """
        The "who's due" list (informational — gates NOTHING).

        DUE COMPUTATION (documented): for every ACTIVE, in-scope customer that
        has a billing schedule set (`invoice_day_rule` non-blank), report the
        unbilled Extra Work count + total for the CURRENT Amsterdam-local
        period (this year, this month), reusing `unbilled_extra_work` (so the
        per-customer figures match exactly what a generate run would claim).
        `is_due` is a soft hint derived from the day rule vs today:
          * FIRST_OF_MONTH -> billing day is the 1st, so it is "reached" for
            the whole current month (True whenever there is unbilled work).
          * LAST_OF_MONTH  -> reached only on the last calendar day of the
            month.
        `is_due = billing_day_reached AND unbilled_count > 0`. It drives a UI
        "due now" badge only; it enforces nothing.
        """
        guard = self._forbid_non_operator(request)
        if guard is not None:
            return guard
        today = timezone.localdate()
        year, month = today.year, today.month
        last_day = calendar.monthrange(year, month)[1]

        customers = (
            scope_customers_for(request.user)
            .filter(is_active=True)
            .exclude(invoice_day_rule="")
            .order_by("name")
        )
        payload = []
        for customer in customers:
            unbilled = unbilled_extra_work(
                request.user, customer.company_id, customer.id, year, month
            )
            count = len(unbilled)
            total = sum(
                (_earned_amounts(e)[2] for e in unbilled), Decimal("0.00")
            )
            rule = customer.invoice_day_rule
            if rule == Customer.InvoiceDayRule.FIRST_OF_MONTH:
                billing_day_reached = True
            elif rule == Customer.InvoiceDayRule.LAST_OF_MONTH:
                billing_day_reached = today.day == last_day
            else:  # defensive — the queryset already excludes blank rules
                billing_day_reached = False
            payload.append(
                {
                    "customer": customer.id,
                    "customer_name": customer.name,
                    "company": customer.company_id,
                    "invoice_day_rule": rule,
                    "invoice_granularity_default": (
                        customer.invoice_granularity_default
                    ),
                    "period_year": year,
                    "period_month": month,
                    "unbilled_count": count,
                    "unbilled_total": f"{total:.2f}",
                    "is_due": billing_day_reached and count > 0,
                }
            )
        return Response(payload, status=status.HTTP_200_OK)

    # -- detail ------------------------------------------------------------

    def retrieve(self, request, pk=None):
        guard = self._forbid_non_operator(request)
        if guard is not None:
            return guard
        invoice = self.get_object()  # 404 if out-of-scope
        return Response(
            InvoiceSerializer(invoice, context={"request": request}).data
        )

    def partial_update(self, request, pk=None):
        """PATCH /invoices/<id>/ — edit the DRAFT page-1 meta (summary + fee)."""
        guard = self._forbid_non_operator(request)
        if guard is not None:
            return guard
        invoice = self.get_object()
        serializer = InvoiceMetaSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            updated = update_invoice_meta(
                request.user, invoice, **serializer.validated_data
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": _validation_detail(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            InvoiceSerializer(updated, context={"request": request}).data
        )

    def destroy(self, request, pk=None):
        """DELETE /invoices/<id>/ — soft-delete a DRAFT + release its EW."""
        guard = self._forbid_non_operator(request)
        if guard is not None:
            return guard
        invoice = self.get_object()
        try:
            delete_draft_invoice(request.user, invoice)
        except DjangoValidationError as exc:
            return Response(
                {"detail": _validation_detail(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _transition(self, request, fn, *, created=False):
        """Shared body for issue / send / reverse."""
        guard = self._forbid_non_operator(request)
        if guard is not None:
            return guard
        invoice = self.get_object()
        try:
            result = fn(request.user, invoice)
        except DjangoValidationError as exc:
            return Response(
                {"detail": _validation_detail(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            InvoiceSerializer(result, context={"request": request}).data,
            status=(
                status.HTTP_201_CREATED if created else status.HTTP_200_OK
            ),
        )

    @action(detail=True, methods=["post"], url_path="issue")
    def issue(self, request, pk=None):
        return self._transition(request, issue_invoice)

    @action(detail=True, methods=["post"], url_path="send")
    def send(self, request, pk=None):
        return self._transition(request, send_invoice)

    @action(detail=True, methods=["post"], url_path="unissue")
    def unissue(self, request, pk=None):
        # ISSUED -> DRAFT ("back to concept"). Numberless under number-at-send,
        # so this strands no gapless number; state machine rejects a reversal
        # or any already-numbered row.
        return self._transition(request, unissue_invoice)

    @action(detail=True, methods=["post"], url_path="reverse")
    def reverse(self, request, pk=None):
        # reverse_invoice returns a NEW counter-invoice -> 201.
        return self._transition(request, reverse_invoice, created=True)

    # -- draft lines -------------------------------------------------------

    @action(detail=True, methods=["post"], url_path="lines")
    def add_line(self, request, pk=None):
        guard = self._forbid_non_operator(request)
        if guard is not None:
            return guard
        invoice = self.get_object()
        serializer = InvoiceLineWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            line = add_invoice_line(
                request.user, invoice, **serializer.validated_data
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": _validation_detail(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            InvoiceLineSerializer(line).data, status=status.HTTP_201_CREATED
        )

    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"lines/(?P<line_id>[^/.]+)",
    )
    def line_detail(self, request, pk=None, line_id=None):
        guard = self._forbid_non_operator(request)
        if guard is not None:
            return guard
        invoice = self.get_object()
        line = get_object_or_404(InvoiceLine, pk=line_id, invoice=invoice)
        if request.method == "DELETE":
            try:
                remove_invoice_line(request.user, line)
            except DjangoValidationError as exc:
                return Response(
                    {"detail": _validation_detail(exc)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(status=status.HTTP_204_NO_CONTENT)
        # PATCH
        serializer = InvoiceLineWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            line = update_invoice_line(
                request.user, line, **serializer.validated_data
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": _validation_detail(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(InvoiceLineSerializer(line).data)


# ---------------------------------------------------------------------------
# Phase 5 — the CUSTOMER read surface (mounted under /api/invoices/my/).
#
# Read-only + REDACTED. Every endpoint scopes through
# `scope_customer_invoices_for` (membership-level, SENT-only, non-deleted), so
# a DRAFT / ISSUED / cross-customer / cross-tenant id is a 404 — never a leak.
# A non-CUSTOMER_USER (provider / staff / anon) gets an empty list / 404 (the
# scope returns .none()), NOT a 500. The provider endpoints stay 403 for a
# customer via `_is_provider_operator` (unchanged).
# ---------------------------------------------------------------------------


class CustomerInvoiceListView(views.APIView):
    """GET /api/invoices/my/ — the caller's own SENT invoices (redacted),
    most-recent-first. Flat array (not paginated) — a customer's invoice
    count is bounded by their monthly billing cadence."""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request):
        qs = (
            scope_customer_invoices_for(request.user)
            .select_related("customer", "building")
            .prefetch_related("lines")
            .order_by("-sent_at", "-id")
        )
        serializer = CustomerInvoiceSerializer(
            qs, many=True, context={"request": request}
        )
        return Response(serializer.data)


class CustomerInvoiceDetailView(views.APIView):
    """GET /api/invoices/my/<id>/ — one of the caller's own SENT invoices
    (redacted). 404 for anything outside `scope_customer_invoices_for`
    (DRAFT / ISSUED / other customer / other tenant / soft-deleted)."""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, invoice_id: int):
        invoice = get_object_or_404(
            scope_customer_invoices_for(request.user)
            .select_related("customer", "building")
            .prefetch_related("lines"),
            pk=invoice_id,
        )
        return Response(
            CustomerInvoiceSerializer(invoice, context={"request": request}).data
        )


class CustomerInvoicePdfView(views.APIView):
    """GET /api/invoices/my/<id>/pdf/ — the two-page Dutch PDF (REUSES
    `render_invoice_pdf`, already customer-safe), but ONLY for an invoice in
    `scope_customer_invoices_for` — so a customer cannot fetch a DRAFT /
    ISSUED / other-tenant PDF by id (404). Mirrors `InvoicePdfView`."""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, invoice_id: int):
        invoice = get_object_or_404(
            scope_customer_invoices_for(request.user).select_related(
                "company", "customer", "building"
            ),
            pk=invoice_id,
        )
        pdf_bytes = render_invoice_pdf(invoice)
        filename = (
            f"factuur-{invoice.number}.pdf"
            if invoice.number
            else f"factuur-{invoice.pk}.pdf"
        )
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response
