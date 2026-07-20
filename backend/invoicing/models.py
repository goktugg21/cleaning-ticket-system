"""
Invoicing subsystem — Phase 1 of 5 (DATA MODEL ONLY).

This module ships the schema for the whole invoicing subsystem; the
behaviour lands in later phases on the same `feat/invoicing` branch:

  Phase 1 (this)  data model — models + migrations + numbering scaffolding.
  Phase 2         generation + lifecycle state machine + EW claim/release
                  + numbering assignment at ISSUE + reversal logic.
  Phase 3         two-page invoice PDF.
  Phase 4         provider "Facturen" UI + the "who's due" list.
  Phase 5         customer-portal visibility (SEND).

LOCKED DECISIONS this schema is built to (do NOT re-litigate here):

  * No contract entity. A contract is just an informational PDF on the
    Customer (zero behavioural effect). The billing schedule is a simple
    informational setting on the Customer.
  * An Invoice sums unbilled EXTRA WORK (claimed in Phase 2) plus an
    OPTIONAL free-text fee (amount + label). There is NO recurring
    contract-fee amount anywhere in the system.
  * Lifecycle DRAFT -> ISSUED -> SENT. Numbering assigned AT ISSUE (not
    draft), sequential, gapless, per-COMPANY per-YEAR.
  * SENT invoices are immutable — the only mutation is a reversal.
  * Reversal = an auto-generated NEGATIVE counter-invoice, editable, that
    releases the claimed EW back to unbilled (Phase 2 logic). A reversal is
    TERMINAL — you cannot reverse a reversal.
  * The invoice total is the source of truth once issued.
  * SEND = customer-portal visibility only. **EMAIL DELIVERY IS EXPLICITLY
    DEFERRED to a later version (v1 is customer-portal visibility only).**

Phase 1 is schema-only: NO transitions, NO numbering assignment, NO
generation, NO money computation, NO PDF. Those all arrive in later phases.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models


class Invoice(models.Model):
    """
    A provider invoice for one customer (optionally scoped to one building).

    See the module docstring for the full LOCKED lifecycle. Everything here
    is schema-only — transitions/numbering/generation/money-freeze arrive in
    Phase 2/3. Tenant scoping mirrors `extra_work.ExtraWorkRequest`
    (company CASCADE anchor; customer/building/created_by PROTECT).
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ISSUED = "ISSUED", "Issued"
        SENT = "SENT", "Sent"

    # Tenant-scoping anchor (mirrors ExtraWorkRequest.company).
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="invoices",
        help_text="Provider company that issues this invoice (tenant anchor).",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="invoices",
    )
    # NULL = customer-level invoice; set = per-building invoice. Phase 2
    # populates this per the customer's invoice_granularity_default.
    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.PROTECT,
        related_name="invoices",
        null=True,
        blank=True,
    )

    # NOTE: status TRANSITIONS (DRAFT -> ISSUED -> SENT, immutability of
    # SENT, reversal) are enforced by Phase 2's state machine, NOT here.
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    # Numbering — assigned AT ISSUE (Phase 2), NULL while DRAFT. `number`
    # is nullable (deliberately NOT blank="") so Postgres NULL-distinctness
    # lets many NULL-numbered drafts coexist under one company while the
    # (company, number) unique constraint still rejects a duplicate non-null
    # number within a company. `year` is the numbering year, enabling the
    # per-company-per-year gapless sequence lookup (Phase 2).
    number = models.CharField(max_length=32, null=True, blank=True)
    year = models.PositiveIntegerField(null=True, blank=True)

    issued_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    # Money caches — the invoice's OWN totals, the SOURCE OF TRUTH once
    # issued. Phase 2/3 compute + freeze these; a fresh draft starts at
    # 0.00 (mirrors ExtraWorkRequest.subtotal/vat/total_amount).
    subtotal_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    vat_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )

    # The free-text fee box (amount + label) — the ONLY non-EW money source.
    optional_fee_label = models.CharField(max_length=255, blank=True, default="")
    optional_fee_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )

    # Phase 4a — Ramazan's hand-written page-1 summary (the "samenvatting").
    # While DRAFT the provider may set this; the two-page PDF prefers it over
    # the auto-composed one-line summary when non-empty (see invoice_pdf.py).
    # Blank ("") = unset -> the PDF falls back to the auto-composed line.
    summary_text = models.TextField(blank=True, default="")

    # Reversal linkage. A reversal is an auto-generated NEGATIVE counter-
    # invoice pointing at the original via `reverses`; it releases the
    # original's claimed EW back to unbilled (Phase 2). A reversal is
    # TERMINAL — you cannot reverse a reversal (enforced in Phase 2).
    is_reversal = models.BooleanField(default=False)
    reverses = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="reversed_by",
        null=True,
        blank=True,
        help_text=(
            "The original invoice this one reverses; NULL unless "
            "is_reversal. A reversal is terminal (cannot reverse a reversal)."
        ),
    )

    # Billing period the invoice covers, stored as a (year, month) tuple
    # mirroring extra_work.billing.billing_month() (which returns
    # (invoice_date.year, invoice_date.month)). Informational: drives the
    # Phase 4 "who's due" list, gates nothing.
    period_year = models.PositiveIntegerField(null=True, blank=True)
    period_month = models.PositiveIntegerField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_invoices",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Soft-delete (mirrors ExtraWorkRequest.deleted_at). Deleting a DRAFT
    # releases its claimed EW back to unbilled (Phase 2 logic).
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            # Per-company gapless numbering. Postgres treats NULLs as
            # distinct, so multiple NULL-numbered DRAFTs coexist; a
            # duplicate non-null number within a company is rejected; the
            # same number string under a DIFFERENT company is allowed.
            models.UniqueConstraint(
                fields=["company", "number"],
                name="uniq_invoice_company_number",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["customer", "status"]),
            models.Index(fields=["company", "year"]),
            models.Index(fields=["deleted_at"]),
        ]

    def __str__(self):
        return self.number or f"DRAFT invoice #{self.pk}"


class InvoiceLine(models.Model):
    """
    One line on an `Invoice`. Two origins:

      * auto-generated from an unbilled Extra Work row (`extra_work` set) —
        Phase 2 claims/releases EW through this link; a reversal releases
        them back to unbilled.
      * hand-added free-text line (`extra_work` NULL) — Phase 3/4 lets the
        provider edit + add lines.

    Money shape MIRRORS `extra_work.ProposalLine` (quantity / unit_price /
    vat_pct + computed line_subtotal / line_vat / line_total) so the Phase 3
    two-page invoice PDF can reuse the proposal-PDF rendering conventions.

    Schema-only in Phase 1: the computed line_* values default to 0.00 and
    are populated by Phase 2/3 compute logic — there is NO save()-time
    recompute here yet (unlike ProposalLine, whose save() recomputes).

    The page-2 detail of the two-page PDF is "EW month / work performed /
    date": `period_year`+`period_month` = the EW billing month (mirrors
    billing.billing_month()); `description` = work performed; `performed_on`
    = the work date.
    """

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    # Line order on the PDF.
    ordering = models.PositiveIntegerField(default=0)

    description = models.TextField(blank=True, default="")

    # Source EW row (NULL for hand-added lines). SET_NULL so the line
    # survives a hard-deleted EW; mirrors the codebase "source back-link"
    # convention (EW source-ticket / Contact.user).
    extra_work = models.ForeignKey(
        "extra_work.ExtraWorkRequest",
        on_delete=models.SET_NULL,
        related_name="invoice_lines",
        null=True,
        blank=True,
    )

    # Money — mirrors ProposalLine. Defaults let Phase-1 rows be created
    # before any compute logic exists (Phase 2/3 populate the line_* caches).
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    vat_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("21.00")
    )
    line_subtotal = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    line_vat = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    line_total = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )

    # Page-2 detail columns ("EW month / work performed / date"). The month
    # mirrors billing.billing_month()'s (year, month) tuple convention.
    period_year = models.PositiveIntegerField(null=True, blank=True)
    period_month = models.PositiveIntegerField(null=True, blank=True)
    performed_on = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["invoice", "ordering", "id"]
        indexes = [
            models.Index(fields=["invoice"]),
            models.Index(fields=["extra_work"]),
        ]

    def __str__(self):
        return f"Line {self.ordering} of invoice #{self.invoice_id}"


class InvoiceNumberSequence(models.Model):
    """
    Phase 2b — the per-(company, year) GAPLESS invoice-number counter.

    This table is the ONLY authority for issue numbers. At issue (and at
    reversal) `invoicing.numbering.allocate_invoice_number` get_or_creates the
    (company, year) row, re-fetches it with select_for_update (so concurrent
    allocations serialize on the row lock — mirroring the tickets
    state_machine locking pattern), increments `last_number`, and formats
    "YYYY-NNNN". There is always exactly ONE row to lock per sequence, so
    there is no empty-set race and numbering stays gapless per company + year.
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="invoice_number_sequences",
    )
    year = models.PositiveIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "year"],
                name="uniq_invoice_seq_company_year",
            ),
        ]
        indexes = [models.Index(fields=["company", "year"])]

    def __str__(self):
        return f"seq {self.company_id}/{self.year} = {self.last_number}"
