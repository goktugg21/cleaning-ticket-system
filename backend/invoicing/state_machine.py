"""
Invoicing — Phase 2b lifecycle state machine + reversal.

Forward-only lifecycle: DRAFT -> ISSUED -> SENT, with a back-to-concept
un-issue (ISSUED -> DRAFT). Numbering is assigned AT SEND (never on a draft
and never at issue), gapless per-company per-year via
`numbering.allocate_invoice_number`. An ISSUED-but-unsent invoice therefore
has NO number yet, which is what makes un-issue trivially safe: nothing is
consumed, so returning it to DRAFT strands no number and SENT invoices stay
perfectly gapless (numbers are only ever born on a committed document — a
SENT invoice, or a reversal at creation). A SENT invoice is IMMUTABLE — the
only mutation is a reversal (`reverse_invoice`), which auto-generates a
negated counter-invoice and releases the original's claimed EW back to
unbilled.

Mutations mirror the tickets state_machine locking pattern: @transaction.atomic
+ select_for_update on the invoice row + a precondition check on the LOCKED
status (which doubles as the concurrency / stale-status guard) + guarded
save. `allocate_invoice_number` is called INSIDE the same atomic block so the
number and the status flip commit together.

ALLOCATION-YEAR DECISION: the numbering year is the CURRENT Amsterdam-local
calendar year at NUMBER-ALLOCATION time (`timezone.localtime(now).year`) —
i.e. SEND time for a normal invoice, and creation time for a reversal — NOT
the invoice's billing `period_year`. That is what "gapless per-year sequence"
means operationally — an invoice sent in 2027 for December-2026 work still
draws from the 2027 sequence. `_issue_year` keeps its name (it is simply the
local calendar year of `now`); only WHEN it is called moved from issue to
send.
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
    """DRAFT -> ISSUED. Provider-operator only. Stamps issued_at ONLY — the
    gapless number is now assigned at SEND (`send_invoice`), NOT here, so an
    ISSUED-but-unsent invoice carries no number and can be cleanly un-issued
    back to DRAFT (`unissue_invoice`). The frozen money (Phase 2a) is
    unchanged. Returns the locked/updated row."""
    if not _is_provider_operator(actor):
        raise PermissionDenied("Only provider operators can issue invoices.")
    locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
    # Precondition on the LOCKED row also guards concurrency: if another tx
    # already issued it, status != DRAFT and this rejects (no double-issue).
    if locked.status != Invoice.Status.DRAFT:
        raise InvoiceTransitionError(
            f"Only a DRAFT invoice can be issued (current status: {locked.status})."
        )
    locked.status = Invoice.Status.ISSUED
    locked.issued_at = timezone.now()
    locked.save(update_fields=["status", "issued_at", "updated_at"])
    return locked


@transaction.atomic
def send_invoice(actor, invoice):
    """ISSUED -> SENT. Provider-operator only. Allocates the gapless
    number+year (allocation-year sequence) INSIDE this atomic block WHEN the
    invoice has none yet, then stamps sent_at. A reversal is born ISSUED WITH
    its own number (allocated at creation), so send keeps that number and only
    a numberless normal invoice is numbered here — the number is thus born on a
    committed (SENT) document and the SENT set stays gapless. SEND is
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
    update_fields = ["status", "sent_at", "updated_at"]
    if locked.number is None:
        # Numbers are BORN at send — the per-(company, year) sequence is only
        # ever advanced by a committed document. `allocate_invoice_number`
        # row-locks the sequence, so concurrent sends serialize (no collision,
        # no gap). A reversal already carries a number, so it is never
        # re-numbered here.
        year = _issue_year(now)
        number, _seq = allocate_invoice_number(locked.company_id, year)
        locked.number = number
        locked.year = year
        update_fields = ["number", "year", *update_fields]
    locked.status = Invoice.Status.SENT
    locked.sent_at = now
    locked.save(update_fields=update_fields)
    return locked


@transaction.atomic
def unissue_invoice(actor, invoice):
    """ISSUED -> DRAFT ("terug naar concept"). Provider-operator only.

    Trivially safe under number-at-send: a normal ISSUED invoice has no number
    yet, so un-issuing consumes / strands NOTHING — it just returns the draft
    to the editable pool still holding its lines. It deliberately does NOT
    release the EW claims (the live draft's InvoiceLines keep them, and
    is_invoiced stays set), so the work stays out of the unbilled pool: un-issue
    is not a delete.

    A REVERSAL is born ISSUED WITH a real number (a committed counter-document)
    and MUST NOT be un-issued — that would strand a gapless number. Rejected.
    As a defensive gaplessness guard we also refuse to un-issue ANY invoice that
    somehow already carries a number/year (e.g. a legacy row issued before the
    number-at-send switch): dropping it would leave a gap, so such a row can
    only go forward (send). Returns the locked/updated row."""
    if not _is_provider_operator(actor):
        raise PermissionDenied("Only provider operators can un-issue invoices.")
    locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if locked.status != Invoice.Status.ISSUED:
        raise InvoiceTransitionError(
            f"Only an ISSUED invoice can be un-issued (current status: {locked.status})."
        )
    if locked.is_reversal:
        raise InvoiceTransitionError(
            "A reversal is a committed counter-document; it cannot be un-issued."
        )
    if locked.number is not None or locked.year is not None:
        # Would strand an already-allocated gapless number — refuse.
        raise InvoiceTransitionError(
            "Cannot un-issue an invoice that already carries a number "
            "(it would leave a gap); send it instead."
        )
    locked.status = Invoice.Status.DRAFT
    locked.issued_at = None
    locked.save(update_fields=["status", "issued_at", "updated_at"])
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
