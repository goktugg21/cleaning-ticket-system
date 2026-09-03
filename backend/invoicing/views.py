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
from extra_work.views import _is_provider_operator  # reuse (do NOT re-implement)

from .filters import InvoiceFilter
from .invoice_pdf import invoice_pdf_bytes
from .line_services import (
    add_invoice_line,
    remove_invoice_line,
    update_invoice_line,
    update_invoice_meta,
)
from .models import Invoice, InvoiceLine
from .permissions import (
    ERR_INVOICE_ADMIN_ONLY,
    INVOICE_ADMIN_ONLY_DETAIL,
    is_invoice_admin,
)
from .preview import plan_invoices
from .preview_pdf import render_preview_pdf
from .schedule import billing_day_reached
from .why_nothing import diagnose_nothing_to_invoice
from .selectors import (
    scope_customer_invoices_for,
    scope_invoices_for,
    unbilled_extra_work_through,
)
from .serializers import (
    CustomerInvoiceSerializer,
    InvoiceLineSerializer,
    InvoiceLineWriteSerializer,
    InvoiceMetaSerializer,
    InvoicePreviewSerializer,
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


def _validation_body(exc) -> dict:
    """P-15 (P-14's S4 refusal-shape finding) — the machine-standard
    `{"detail", "code"}` body: every InvoiceTransitionError now carries
    a stable code beside its sentence, like every other machine's."""
    body = {"detail": _validation_detail(exc)}
    code = getattr(exc, "code", None)
    if code:
        body["code"] = code
    return body


class InvoicePdfView(views.APIView):
    """
    GET /api/invoices/<invoice_id>/pdf/

    The invoice as a Dutch PDF: page 1 the summary, page 2+ the
    specification annex. Provider-operator only (403 for a customer user /
    staff); tenant-scoped via scope_invoices_for (404 for a cross-tenant or
    out-of-scope invoice). Customer visibility is Phase 5 — customer users
    cannot reach this endpoint here.

    Sprint 180 §1 — a SENT invoice serves its FROZEN bytes; a draft still
    renders fresh. `invoice_pdf_bytes` owns that decision so both PDF
    endpoints cannot disagree about it.
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
                "company", "customer", "building", "department", "work_type"
            ),
            pk=invoice_id,
        )
        pdf_bytes = invoice_pdf_bytes(invoice)
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
            .select_related("company", "customer", "building", "department", "work_type")
            .prefetch_related("lines", "reversed_by")
        )

    def _forbid_non_operator(self, request):
        """Return a 403 Response for a non-operator, else None."""
        if not _is_provider_operator(request.user):
            return Response(
                {"detail": "Only provider operators can manage invoices."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def _forbid_non_admin(self, request):
        """P-15 §0.1 / H-12 — issue / send / un-issue / reverse are
        company-level (CA / SA only). Operator first, so a customer or
        STAFF still gets the generic operator refusal; a BUILDING_MANAGER
        gets the sentence that names the next actor, with the stable code
        the screen renders from."""
        guard = self._forbid_non_operator(request)
        if guard is not None:
            return guard
        if not is_invoice_admin(request.user):
            return Response(
                {
                    "detail": INVOICE_ADMIN_ONLY_DETAIL,
                    "code": ERR_INVOICE_ADMIN_ONLY,
                },
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

    @action(detail=False, methods=["get"], url_path="preview")
    def preview(self, request):
        """
        Sprint 182 §2 — "if this were cut now, your invoice would be this".

        PROVIDER-ONLY, and that is a decision rather than an oversight:
        these are numbers no operator has reviewed yet. A customer who
        downloads a preview and later receives a different invoice is
        holding a document you have to argue with. `_forbid_non_operator`
        is the same gate the rest of this viewset uses.

        NOTHING IS STORED. The result is recomputed on every call, so
        there is nothing to expire, nothing to clean up, and no second
        source of drafts the month-end job would have to reconcile
        against.

        NO INVOICE NUMBER, ever — numbering happens at Send and must stay
        gapless. `InvoicePreviewSerializer` has no `number` field at all,
        so there is nothing to accidentally populate.

        The computation is `preview.plan_invoices`, which is also what
        `services.generate_draft_invoices` executes. One function, so the
        preview cannot disagree with the invoice it previews.

        Query params: `customer` (required), `year` / `month` (optional,
        defaulting to the current Amsterdam-local period).
        """
        guard = self._forbid_non_operator(request)
        if guard is not None:
            return guard
        try:
            customer_id = int(request.query_params["customer"])
        except (KeyError, TypeError, ValueError):
            return Response(
                {"detail": "customer (int) is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        today = timezone.localdate()
        try:
            year = int(request.query_params.get("year", today.year))
            month = int(request.query_params.get("month", today.month))
        except (TypeError, ValueError):
            return Response(
                {"detail": "year and month must be integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not (1 <= month <= 12):
            return Response(
                {"detail": "month must be between 1 and 12."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Resolved through the actor's customer scope so a cross-tenant id
        # is a clean 404 and never previews another tenant's money.
        customer = get_object_or_404(
            scope_customers_for(request.user), pk=customer_id
        )
        planned = plan_invoices(
            request.user,
            customer.company_id,
            customer.id,
            year,
            month,
            granularity=request.query_params.get("granularity") or None,
        )
        computed_at = timezone.now()

        # `?download=pdf` serves the same plan as a stamped document. The
        # bytes are rendered from the plan object already in hand, so the
        # PDF and the JSON cannot disagree — not even by the time it takes
        # to recompute.
        #
        # NOT `?format=pdf`: DRF reserves `format` for content negotiation
        # (`URL_FORMAT_OVERRIDE`), so that spelling makes it look for a
        # renderer called "pdf" and 404 before this code runs.
        if request.query_params.get("download") == "pdf":
            pdf_bytes = render_preview_pdf(
                company=customer.company,
                customer=customer,
                planned=planned,
                period_year=year,
                period_month=month,
                computed_at=timezone.localtime(computed_at),
            )
            response = HttpResponse(
                pdf_bytes, content_type="application/pdf"
            )
            # `preview` in the filename, and no number in it, because a
            # file that reaches somebody's desktop has to say what it is
            # without being opened.
            response["Content-Disposition"] = (
                'inline; filename="factuurvoorbeeld-'
                f'{customer.id}-{year}-{month:02d}.pdf"'
            )
            return response

        return Response(
            {
                "customer": customer.id,
                "customer_name": customer.name,
                "period_year": year,
                "period_month": month,
                # The moment this was computed. The PDF stamps the same
                # value — a preview is a photograph, not a promise, and
                # the reader needs to know when it was taken.
                "computed_at": computed_at.isoformat(),
                "invoice_count": len(planned),
                # Sprint 183 §2 — the SAME sentence the /due/ panel
                # shows, from the same function, so the two screens
                # cannot explain the same emptiness differently.
                "nothing_reason": diagnose_nothing_to_invoice(
                    request.user,
                    customer.company_id,
                    customer.id,
                    billable_count=len(planned),
                ),
                "invoices": InvoicePreviewSerializer(
                    planned, many=True, context={"request": request}
                ).data,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="due")
    def due(self, request):
        """
        The "who's due" list (informational — gates NOTHING).

        DUE COMPUTATION (documented, SoT Addendum B §B.10): for every ACTIVE,
        in-scope customer that has a billing schedule set (`invoice_day_rule`
        non-blank), report the unbilled Extra Work count + total THROUGH the
        CURRENT Amsterdam-local period (this year, this month) — i.e. every
        earned-but-unbilled row from this month or any EARLIER one, via
        `unbilled_extra_work_through`. This keeps prior-month unbilled work
        visible once the calendar month rolls over, instead of it silently
        dropping off the panel (the pre-Sprint-119 behaviour, which used the
        exact-period `unbilled_extra_work` — still correct for `generate`,
        which always targets one specific period).
        `is_due` is a soft hint derived from the customer's billing day vs
        today. The EFFECTIVE billing day is `invoice_day_of_month` when set
        (1..28), otherwise the first/last rule:
          * a specific day D (1..28) -> "reached" from day D onward within the
            month (True once today.day >= D), mirroring FIRST_OF_MONTH's
            reached-for-the-rest-of-the-month semantics.
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

        # Sprint 182 §1 — "who is scheduled" and "has their day arrived"
        # moved to `invoicing.schedule` so the new daily job triggers on
        # exactly the rule this panel reports. They were inline here; the
        # job would have been a second copy, and the two drifting apart
        # reads to an operator as "the panel said due, no invoice came".
        #
        # P-13 A (W1) — the list is no longer narrowed to
        # `scheduled_customers`. A customer whose billing day was never
        # set used to disappear from this panel entirely, taking every
        # finished, unbilled job with them — the quiet way money misses
        # month-end. Now: a SCHEDULED customer keeps their row
        # unconditionally (a zero-count row carries its nothing_reason);
        # an UNSCHEDULED customer gets a row exactly when they have
        # finished unbilled work (rule "" + day None on the wire is the
        # panel's "no billing day set" fact). The daily job still
        # triggers on `is_billing_day`, so an unscheduled customer is
        # never invoiced automatically — this only makes them visible.
        customers = (
            scope_customers_for(request.user)
            .filter(is_active=True)
            .order_by("name")
        )
        # P-12 §D.24.2 — `?company=` narrows WITHIN scope (an id outside
        # it matches nothing); the page shows one company at a time.
        company_param = request.query_params.get("company")
        if company_param and str(company_param).isdigit():
            customers = customers.filter(company_id=int(company_param))
        payload = []
        for customer in customers:
            unbilled = unbilled_extra_work_through(
                request.user, customer.company_id, customer.id, year, month
            )
            count = len(unbilled)
            scheduled = (
                customer.invoice_day_of_month is not None
                or customer.invoice_day_rule != ""
            )
            if not scheduled and count == 0:
                continue
            total = sum(
                (_earned_amounts(e)[2] for e in unbilled), Decimal("0.00")
            )
            rule = customer.invoice_day_rule
            day = customer.invoice_day_of_month
            reached = billing_day_reached(customer, today)
            payload.append(
                {
                    "customer": customer.id,
                    "customer_name": customer.name,
                    "company": customer.company_id,
                    "invoice_day_rule": rule,
                    "invoice_day_of_month": day,
                    "invoice_granularity_default": (
                        customer.invoice_granularity_default
                    ),
                    # Sprint 182 §3 — the two controls that replaced the
                    # single granularity dropdown. Reported alongside the
                    # derived legacy value so the panel can show what the
                    # operator actually set.
                    "invoice_billing_target": customer.invoice_billing_target,
                    "invoice_split": customer.invoice_split,
                    "period_year": year,
                    "period_month": month,
                    "unbilled_count": count,
                    "unbilled_total": f"{total:.2f}",
                    "is_due": reached and count > 0,
                    # Sprint 183 §2 — when there is nothing to invoice,
                    # say WHICH nothing this is. "I cannot generate
                    # anything in Due now" turned out to be correct
                    # behaviour with no explanation, and correct-but-
                    # silent reads as broken software. Carries the counts
                    # so the sentence is actionable: "61 extra works,
                    # none finished" sends an operator somewhere, "no
                    # billable work" does not.
                    "nothing_reason": diagnose_nothing_to_invoice(
                        request.user,
                        customer.company_id,
                        customer.id,
                        billable_count=count,
                    ),
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
        """Shared body for issue / send / un-issue / reverse — all four
        are company-level commits (P-15 §0.1 / H-12), so the shared gate
        here is the ADMIN one, not the operator one."""
        guard = self._forbid_non_admin(request)
        if guard is not None:
            return guard
        invoice = self.get_object()
        try:
            result = fn(request.user, invoice)
        except DjangoValidationError as exc:
            return Response(
                _validation_body(exc),
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
            .select_related("customer", "building", "department", "work_type")
            .prefetch_related("lines", "reversed_by")
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
            .select_related("customer", "building", "department", "work_type")
            .prefetch_related("lines", "reversed_by"),
            pk=invoice_id,
        )
        return Response(
            CustomerInvoiceSerializer(invoice, context={"request": request}).data
        )


class CustomerInvoicePdfView(views.APIView):
    """GET /api/invoices/my/<id>/pdf/ — the Dutch PDF (REUSES
    `invoice_pdf_bytes`, already customer-safe), but ONLY for an invoice in
    `scope_customer_invoices_for` — so a customer cannot fetch a DRAFT /
    ISSUED / other-tenant PDF by id (404). Mirrors `InvoicePdfView`.

    This scope is SENT-only, so in practice a customer always receives the
    FROZEN document — the same bytes the operator sent, not a re-render."""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, invoice_id: int):
        invoice = get_object_or_404(
            scope_customer_invoices_for(request.user).select_related(
                "company", "customer", "building", "department", "work_type"
            ),
            pk=invoice_id,
        )
        pdf_bytes = invoice_pdf_bytes(invoice)
        filename = (
            f"factuur-{invoice.number}.pdf"
            if invoice.number
            else f"factuur-{invoice.pk}.pdf"
        )
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response
