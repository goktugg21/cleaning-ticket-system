"""
Invoicing — Phase 4a: editable-draft line + meta services.

While an invoice is DRAFT the provider may freely edit its lines and a
hand-written page-1 summary (+ the optional fee). Issue/send make the invoice
IMMUTABLE — every mutation here guards via `_assert_draft` (which layers
`state_machine.assert_mutable` — the SENT guard — over an explicit DRAFT
check, so ISSUED is rejected too). After any mutation the invoice's frozen
subtotal/vat/total RECOMPUTE from the live lines (+ optional fee) via
`services.recompute_invoice_totals`, keeping the invoice the source of truth.

Two line origins (mirrors the `InvoiceLine` model docstring):
  * EW-linked line (`extra_work` set) — its amount may be edited IN PLACE; the
    claim link survives an edit. REMOVING it RELEASES that EW back to unbilled
    (clear `is_invoiced`/`invoiced_at` — the Phase-2a release semantics) so it
    can be re-invoiced later.
  * hand-added line (`extra_work` NULL) — claims nothing; freely added / edited
    / removed.

All mutations are provider-operator-gated (PermissionDenied otherwise) and
DRAFT-only (ValidationError otherwise). Tenant scoping is enforced at the HTTP
layer (`scope_invoices_for`); these service helpers operate on an
already-resolved invoice/line.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from rest_framework.exceptions import PermissionDenied

from extra_work.models import ExtraWorkRequest, compute_line_amounts
from extra_work.views import _is_provider_operator  # reuse (do NOT re-implement)

from .models import Invoice, InvoiceLine
from .services import recompute_invoice_totals
from .state_machine import assert_mutable

# Sentinel so update_invoice_meta can distinguish "field omitted" from an
# explicit None / "".
_UNSET = object()

# The fields update_invoice_line may set (everything money-affecting recomputes
# the line + the invoice totals afterwards).
_EDITABLE_LINE_FIELDS = frozenset(
    {
        "description",
        "quantity",
        "unit_price",
        "vat_pct",
        "period_year",
        "period_month",
        "performed_on",
    }
)
_MONEY_LINE_FIELDS = frozenset({"quantity", "unit_price", "vat_pct"})


def _assert_operator(actor):
    if not _is_provider_operator(actor):
        raise PermissionDenied("Only provider operators can edit invoices.")


def _assert_draft(invoice):
    # SENT -> InvoiceTransitionError (a ValidationError subclass);
    # ISSUED -> the explicit DRAFT check below. Only DRAFT is editable.
    assert_mutable(invoice)
    if invoice.status != Invoice.Status.DRAFT:
        raise ValidationError(
            "Only DRAFT invoices can be edited "
            f"(current status: {invoice.status})."
        )


def add_invoice_line(
    actor,
    invoice,
    *,
    description="",
    quantity=Decimal("1.00"),
    unit_price=Decimal("0.00"),
    vat_pct=Decimal("21.00"),
    period_year=None,
    period_month=None,
    performed_on=None,
):
    """Add a HAND-ADDED line (extra_work=NULL, claims nothing) to a DRAFT
    invoice, compute its money from qty/unit_price/vat_pct (mirrors
    `compute_line_amounts`), append at the next ordering, and recompute the
    invoice totals. Returns the new line."""
    _assert_operator(actor)
    _assert_draft(invoice)

    quantity = Decimal(str(quantity))
    unit_price = Decimal(str(unit_price))
    vat_pct = Decimal(str(vat_pct))

    with transaction.atomic():
        line_sub, line_vat, line_tot = compute_line_amounts(
            quantity, unit_price, vat_pct
        )
        next_ordering = (
            invoice.lines.aggregate(m=Max("ordering"))["m"] or 0
        ) + 1
        line = InvoiceLine.objects.create(
            invoice=invoice,
            ordering=next_ordering,
            description=description or "",
            extra_work=None,  # hand-added claims nothing
            quantity=quantity,
            unit_price=unit_price,
            vat_pct=vat_pct,
            line_subtotal=line_sub,
            line_vat=line_vat,
            line_total=line_tot,
            period_year=period_year,
            period_month=period_month,
            performed_on=performed_on,
        )
        recompute_invoice_totals(invoice)
    return line


def update_invoice_line(actor, line, **fields):
    """Edit a DRAFT invoice line (BOTH origins — an EW-linked line's amount is
    editable in place, the claim link is untouched). Accepts
    description/quantity/unit_price/vat_pct/period_year/period_month/
    performed_on; recomputes the line's money then the invoice totals. Returns
    the updated line."""
    invoice = line.invoice
    _assert_operator(actor)
    _assert_draft(invoice)

    with transaction.atomic():
        for key, value in fields.items():
            if key not in _EDITABLE_LINE_FIELDS:
                continue
            if key in _MONEY_LINE_FIELDS and value is not None:
                value = Decimal(str(value))
            setattr(line, key, value)
        line.line_subtotal, line.line_vat, line.line_total = compute_line_amounts(
            line.quantity, line.unit_price, line.vat_pct
        )
        line.save()
        recompute_invoice_totals(invoice)
    return line


def remove_invoice_line(actor, line):
    """Remove a DRAFT invoice line. If the line is EW-linked, RELEASE its EW
    back to unbilled (clear is_invoiced/invoiced_at — Phase-2a release
    semantics) BEFORE deleting the line, so the work can be re-invoiced. A
    hand-added line claims nothing, so nothing is released. Recomputes the
    invoice totals. Returns the invoice."""
    invoice = line.invoice
    _assert_operator(actor)
    _assert_draft(invoice)

    with transaction.atomic():
        if line.extra_work_id is not None:
            ExtraWorkRequest.objects.filter(id=line.extra_work_id).update(
                is_invoiced=False, invoiced_at=None
            )
        line.delete()
        recompute_invoice_totals(invoice)
    return invoice


def update_invoice_meta(
    actor,
    invoice,
    *,
    summary_text=_UNSET,
    optional_fee_label=_UNSET,
    optional_fee_amount=_UNSET,
):
    """Edit a DRAFT invoice's page-1 meta: the hand-written `summary_text` and
    the optional free-text fee (label + amount). Only the fields explicitly
    passed are changed. Recomputes the invoice totals (the fee affects them).
    Returns the invoice."""
    _assert_operator(actor)
    _assert_draft(invoice)

    update_fields: list[str] = []
    with transaction.atomic():
        if summary_text is not _UNSET:
            invoice.summary_text = summary_text or ""
            update_fields.append("summary_text")
        if optional_fee_label is not _UNSET:
            invoice.optional_fee_label = optional_fee_label or ""
            update_fields.append("optional_fee_label")
        if optional_fee_amount is not _UNSET:
            invoice.optional_fee_amount = (
                Decimal(str(optional_fee_amount))
                if optional_fee_amount is not None
                else None
            )
            update_fields.append("optional_fee_amount")
        if update_fields:
            invoice.save(update_fields=update_fields + ["updated_at"])
        # Always recompute: even a summary-only edit is cheap, and a fee change
        # must re-derive totals. Recompute reads the (now-updated) fee.
        recompute_invoice_totals(invoice)
    return invoice
