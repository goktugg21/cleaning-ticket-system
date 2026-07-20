"""
Invoicing — Phase 2a services: draft generation (claim) + release.

Scope of this phase (Option 1, the invoice is the single source of
"invoiced"):

  * generate_draft_invoices — roll up a customer's unbilled Extra Work for
    a (year, month) into DRAFT invoice(s), one per building or one for the
    whole customer, and CLAIM the consumed EW atomically.
  * delete_draft_invoice — release a DRAFT's claimed EW back to unbilled.

Explicitly NOT in this phase: lifecycle transitions, numbering assignment
(number/year stay NULL here — Phase 2b), reversal, PDF, UI.

Every ExtraWorkRequest is tied to exactly one building (FK NON-nullable,
PROTECT), so there is no buildingless / company-wide EW; per-building
generation groups cleanly by `building_id`. (Revisit only if EW ever
becomes buildingless.)
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from customers.models import Customer
from extra_work.billing import billing_month, build_ticket_map
from extra_work.models import ExtraWorkRequest
from extra_work.views import _is_provider_operator  # reuse (do NOT re-implement)

from .models import Invoice, InvoiceLine
from .selectors import unbilled_extra_work

_TWO_PLACES = Decimal("0.01")


def recompute_invoice_totals(invoice):
    """Recompute + persist the invoice's FROZEN subtotal/vat/total from its
    LIVE lines plus the optional fee, and return the invoice.

    This is the editable-draft source-of-truth recompute (Phase 4a): after
    any line add/edit/remove or a fee change, the invoice's own totals are
    re-derived from the current lines so the invoice stays the single source
    of truth. DRAFT-only callers (the line/meta services guard the status);
    issued/sent invoices are immutable.

    FEE-VAT TREATMENT (documented decision): the optional fee is treated as a
    VAT-exempt (0% BTW) additional post. It is added to BOTH the subtotal and
    the total and contributes NOTHING to the VAT figure. This is the
    least-surprising rule and keeps the invariant `subtotal + vat == total`
    intact:  (Σ line_subtotal + fee) + (Σ line_vat) == Σ line_total + fee.
    The page-1 fee box is a free-text amount with no VAT breakdown, so rolling
    it in VAT-free matches exactly what the provider typed.
    """
    agg = invoice.lines.aggregate(
        sub=Sum("line_subtotal"), vat=Sum("line_vat"), tot=Sum("line_total")
    )
    subtotal = agg["sub"] or Decimal("0.00")
    vat = agg["vat"] or Decimal("0.00")
    total = agg["tot"] or Decimal("0.00")
    fee = invoice.optional_fee_amount or Decimal("0.00")
    invoice.subtotal_amount = (subtotal + fee).quantize(_TWO_PLACES)
    invoice.vat_amount = vat.quantize(_TWO_PLACES)
    invoice.total_amount = (total + fee).quantize(_TWO_PLACES)
    invoice.save(
        update_fields=[
            "subtotal_amount",
            "vat_amount",
            "total_amount",
            "updated_at",
        ]
    )
    return invoice


def _earned_amounts(ew):
    """(subtotal, vat, total) for an EARNED EW — mirrors
    reports.dimensions._amounts_for_state for the 'earned' state: prefer the
    frozen FINAL amounts, fall back to the quoted estimate only when
    final_total_amount is NULL (legacy / fixed-price rows)."""
    if ew.final_total_amount is not None:
        return (
            ew.final_subtotal_amount,
            ew.final_vat_amount,
            ew.final_total_amount,
        )
    return (ew.subtotal_amount, ew.vat_amount, ew.total_amount)


def _derive_vat_pct(subtotal, vat):
    """A display-only blended VAT % so the ProposalLine-shaped line stays
    internally consistent. The authoritative figures are line_subtotal /
    line_vat / line_total (taken straight from the EW earned amounts); this
    percent is cosmetic for the Phase-3 PDF."""
    if subtotal and subtotal != Decimal("0"):
        return (vat / subtotal * Decimal("100")).quantize(_TWO_PLACES)
    return Decimal("21.00")


def _create_draft(actor, company_id, customer_id, year, month, building_id, ews):
    """Create ONE draft Invoice for the given EW list and CLAIM them.

    One InvoiceLine PER EW carrying the EW's earned subtotal/vat/total (the
    exact per-pricing-line split inside an EW is NOT reproduced — the earned
    total is carried on the single summary line; quantity=1, unit_price=the
    earned subtotal, vat_pct=blended). Assumes the caller is inside an
    atomic block.
    """
    invoice = Invoice.objects.create(
        company_id=company_id,
        customer_id=customer_id,
        building_id=building_id,
        status=Invoice.Status.DRAFT,
        number=None,  # numbering is Phase 2b — NOT assigned here
        year=None,
        period_year=year,
        period_month=month,
        created_by=actor,
    )
    ticket_map = build_ticket_map([e.id for e in ews])
    now = timezone.now()
    subtotal = Decimal("0.00")
    vat = Decimal("0.00")
    total = Decimal("0.00")
    for i, ew in enumerate(ews):
        ticket = ticket_map.get(ew.id)
        line_sub, line_vat, line_tot = _earned_amounts(ew)
        bm = billing_month(ew, ticket)  # (year, month) for included rows
        performed_on = None
        if ticket is not None and ticket.closed_at is not None:
            # Same Europe/Amsterdam localtime rule as billing_month.
            performed_on = timezone.localtime(ticket.closed_at).date()
        InvoiceLine.objects.create(
            invoice=invoice,
            ordering=i,
            description=ew.title,
            extra_work=ew,  # durable claim link (release nulls/soft-deletes)
            quantity=Decimal("1.00"),
            unit_price=line_sub,
            vat_pct=_derive_vat_pct(line_sub, line_vat),
            line_subtotal=line_sub,
            line_vat=line_vat,
            line_total=line_tot,
            period_year=bm[0] if bm else year,
            period_month=bm[1] if bm else month,
            performed_on=performed_on,
        )
        subtotal += line_sub
        vat += line_vat
        total += line_tot
        # CLAIM: the is_invoiced flag is the fast Option-1 exclusion; the
        # InvoiceLine.extra_work link is the durable claim. Both are set on
        # claim and cleared on release.
        ew.is_invoiced = True
        ew.invoiced_at = now
        ew.save(update_fields=["is_invoiced", "invoiced_at", "updated_at"])

    invoice.subtotal_amount = subtotal
    invoice.vat_amount = vat
    invoice.total_amount = total
    invoice.save(
        update_fields=[
            "subtotal_amount",
            "vat_amount",
            "total_amount",
            "updated_at",
        ]
    )
    return invoice


def generate_draft_invoices(
    actor, company_id, customer_id, year, month, granularity=None
):
    """
    Roll up (company, customer)'s unbilled EW for (year, month) into DRAFT
    invoice(s) and claim the consumed EW.

    granularity:
      * "CUSTOMER"     -> ONE draft (building=NULL) with every building's
                          unbilled EW.
      * "PER_BUILDING" -> one draft per building that has unbilled EW.
      * None           -> the customer's `invoice_granularity_default`.

    Provider-operator only (403 otherwise). Every read is tenant-scoped via
    scope_extra_work_for, so an actor cannot generate across tenants — an
    out-of-scope (company, customer) simply yields an empty unbilled pool
    and NO invoice is created. Generating twice is safe: the first call
    claims the EW, so the second finds nothing unbilled and returns [] (no
    empty draft is created, no double-claim).
    """
    if not _is_provider_operator(actor):
        raise PermissionDenied("Only provider operators can generate invoices.")

    if granularity is None:
        customer = Customer.objects.filter(
            id=customer_id, company_id=company_id
        ).first()
        granularity = (
            customer.invoice_granularity_default
            if customer is not None
            else Customer.InvoiceGranularity.CUSTOMER
        )

    unbilled = unbilled_extra_work(actor, company_id, customer_id, year, month)
    if not unbilled:
        # Idempotent: nothing to claim -> do NOT create an empty draft.
        return []

    created = []
    with transaction.atomic():
        if granularity == Customer.InvoiceGranularity.PER_BUILDING:
            by_building: dict[int, list] = {}
            for ew in unbilled:
                by_building.setdefault(ew.building_id, []).append(ew)
            # Deterministic order (by building id) for stable output.
            for building_id in sorted(by_building):
                created.append(
                    _create_draft(
                        actor,
                        company_id,
                        customer_id,
                        year,
                        month,
                        building_id,
                        by_building[building_id],
                    )
                )
        else:  # CUSTOMER (default)
            created.append(
                _create_draft(
                    actor,
                    company_id,
                    customer_id,
                    year,
                    month,
                    None,
                    unbilled,
                )
            )
    return created


def delete_draft_invoice(actor, invoice):
    """
    Release a DRAFT invoice: soft-delete it and release every EW its lines
    claim back to unbilled (clear is_invoiced=False + invoiced_at=NULL).

    Soft-delete (not hard) is the canonical release: the lines stay linked
    but their invoice is now soft-deleted, so the Option-1 unbilled query
    reappears the EW (no LIVE claim) AND is_invoiced is cleared.

    Provider-operator only. DRAFT-only — issued/sent invoices are immutable;
    the full ISSUED/SENT immutability guard lands in Phase 2b, but we hard-
    assert DRAFT here so a non-draft can never be deleted through this path.
    """
    if not _is_provider_operator(actor):
        raise PermissionDenied("Only provider operators can delete invoices.")
    if invoice.status != Invoice.Status.DRAFT:
        raise ValidationError(
            "Only DRAFT invoices can be deleted "
            "(ISSUED/SENT immutability enforced in Phase 2b)."
        )

    with transaction.atomic():
        ew_ids = list(
            invoice.lines.filter(extra_work__isnull=False).values_list(
                "extra_work_id", flat=True
            )
        )
        if ew_ids:
            ExtraWorkRequest.objects.filter(id__in=ew_ids).update(
                is_invoiced=False, invoiced_at=None
            )
        invoice.deleted_at = timezone.now()
        invoice.save(update_fields=["deleted_at", "updated_at"])
    return invoice
