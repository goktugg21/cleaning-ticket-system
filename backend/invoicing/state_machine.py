"""
Invoicing — Phase 2b lifecycle state machine + reversal.

Forward-only lifecycle: DRAFT -> ISSUED -> SENT. Numbering is assigned AT
ISSUE (never on a draft), gapless per-company per-year via
`numbering.allocate_invoice_number`. A SENT invoice is IMMUTABLE — the only
mutation is a reversal (`reverse_invoice`), which auto-generates a negated
counter-invoice and releases the original's claimed EW back to unbilled.

Mutations mirror the tickets state_machine locking pattern: @transaction.atomic
+ select_for_update on the invoice row + a precondition check on the LOCKED
status (which doubles as the concurrency / stale-status guard) + guarded
save. `allocate_invoice_number` is called INSIDE the same atomic block so the
number and the status flip commit together.

ISSUE-YEAR DECISION: the numbering year is the CURRENT Amsterdam-local
calendar year at issue time (`timezone.localtime(now).year`), NOT the
invoice's billing `period_year`. That is what "gapless per-year sequence"
means operationally — invoices issued in 2027 for December-2026 work still
draw from the 2027 sequence. Documented here + in the checklist.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from extra_work.models import ExtraWorkRequest
from extra_work.views import _is_provider_operator  # reuse (do NOT re-implement)

from .models import Invoice, InvoiceLine
from .numbering import allocate_invoice_number


class InvoiceTransitionError(ValidationError):
    """Raised on an illegal invoice lifecycle transition."""


def _issue_year(now):
    # Amsterdam-local calendar year — see the module ISSUE-YEAR DECISION.
    return timezone.localtime(now).year


def assert_mutable(invoice):
    """Guard for future edit/delete paths: a SENT invoice is IMMUTABLE — its
    only mutation is a reversal. Callers that edit or delete an invoice must
    call this first. (delete_draft_invoice already rejects any non-DRAFT, so
    ISSUED + SENT are both blocked from deletion.)"""
    if invoice.status == Invoice.Status.SENT:
        raise InvoiceTransitionError(
            "A SENT invoice is immutable; reverse it instead."
        )


@transaction.atomic
def issue_invoice(actor, invoice):
    """DRAFT -> ISSUED. Provider-operator only. Assigns the gapless
    number+year (current-calendar-year sequence) and stamps issued_at. The
    frozen money (Phase 2a) is unchanged. Returns the locked/updated row."""
    if not _is_provider_operator(actor):
        raise PermissionDenied("Only provider operators can issue invoices.")
    locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
    # Precondition on the LOCKED row also guards concurrency: if another tx
    # already issued it, status != DRAFT and this rejects (no double-issue).
    if locked.status != Invoice.Status.DRAFT:
        raise InvoiceTransitionError(
            f"Only a DRAFT invoice can be issued (current status: {locked.status})."
        )
    now = timezone.now()
    year = _issue_year(now)
    number, _seq = allocate_invoice_number(locked.company_id, year)
    locked.number = number
    locked.year = year
    locked.status = Invoice.Status.ISSUED
    locked.issued_at = now
    locked.save(
        update_fields=["number", "year", "status", "issued_at", "updated_at"]
    )
    return locked


@transaction.atomic
def send_invoice(actor, invoice):
    """ISSUED -> SENT. Provider-operator only. Stamps sent_at. SEND is
    customer-portal visibility only (surfaced in Phase 5); no email (deferred).
    Returns the locked/updated row."""
    if not _is_provider_operator(actor):
        raise PermissionDenied("Only provider operators can send invoices.")
    locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if locked.status != Invoice.Status.ISSUED:
        raise InvoiceTransitionError(
            f"Only an ISSUED invoice can be sent (current status: {locked.status})."
        )
    now = timezone.now()
    locked.status = Invoice.Status.SENT
    locked.sent_at = now
    locked.save(update_fields=["status", "sent_at", "updated_at"])
    return locked


@transaction.atomic
def reverse_invoice(actor, invoice):
    """
    Reverse a SENT invoice: auto-generate a NEGATED counter-invoice and
    release the original's claimed EW back to unbilled.

    Provider-operator only. The original MUST be SENT and NOT itself a
    reversal (a reversal is TERMINAL — you cannot reverse a reversal).

    The reversal:
      * is created already-ISSUED (a real counter-document; it consumes a
        real number from the same per-company-per-year sequence). Editing a
        reversal is a Phase-4 UI concern; here it is the auto-generated mirror.
      * carries is_reversal=True + reverses=original + negated invoice totals.
      * mirrors each original line with NEGATED line amounts, but with
        extra_work=NULL — the reversal is a monetary counter-entry and does
        NOT re-claim EW.

    The ORIGINAL is left SENT on the books (NOT soft-deleted); only its EW
    claim is released (is_invoiced=False + invoiced_at=NULL) so the work
    returns to the unbilled pool and can be correctly re-invoiced.

    Returns the reversal invoice.
    """
    if not _is_provider_operator(actor):
        raise PermissionDenied("Only provider operators can reverse invoices.")
    original = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if original.status != Invoice.Status.SENT:
        raise InvoiceTransitionError(
            f"Only a SENT invoice can be reversed (current status: {original.status})."
        )
    if original.is_reversal:
        raise InvoiceTransitionError(
            "A reversal is terminal; it cannot itself be reversed."
        )

    now = timezone.now()
    year = _issue_year(now)
    number, _seq = allocate_invoice_number(original.company_id, year)

    reversal = Invoice.objects.create(
        company_id=original.company_id,
        customer_id=original.customer_id,
        building_id=original.building_id,
        status=Invoice.Status.ISSUED,  # a real, already-issued counter-document
        number=number,
        year=year,
        issued_at=now,
        is_reversal=True,
        reverses=original,
        period_year=original.period_year,
        period_month=original.period_month,
        subtotal_amount=-original.subtotal_amount,
        vat_amount=-original.vat_amount,
        total_amount=-original.total_amount,
        optional_fee_label=original.optional_fee_label,
        optional_fee_amount=(
            -original.optional_fee_amount
            if original.optional_fee_amount is not None
            else None
        ),
        created_by=actor,
    )
    # Negated mirror lines. extra_work=NULL — the reversal does NOT re-claim
    # EW; it is a monetary counter-entry only.
    for line in original.lines.all().order_by("ordering", "id"):
        InvoiceLine.objects.create(
            invoice=reversal,
            ordering=line.ordering,
            description=line.description,
            extra_work=None,
            quantity=line.quantity,
            unit_price=-line.unit_price,
            vat_pct=line.vat_pct,
            line_subtotal=-line.line_subtotal,
            line_vat=-line.line_vat,
            line_total=-line.line_total,
            period_year=line.period_year,
            period_month=line.period_month,
            performed_on=line.performed_on,
        )

    # Release the ORIGINAL's claimed EW back to unbilled. Do NOT soft-delete
    # the original — it stays SENT; the reversal is the counter-entry.
    ew_ids = list(
        original.lines.filter(extra_work__isnull=False).values_list(
            "extra_work_id", flat=True
        )
    )
    if ew_ids:
        ExtraWorkRequest.objects.filter(id__in=ew_ids).update(
            is_invoiced=False, invoiced_at=None
        )
    return reversal
