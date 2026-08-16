"""
Invoicing — Phase 4a serializers.

Read shape for the provider Facturen UI (`InvoiceSerializer` +
`InvoiceLineSerializer`), plus thin WRITE serializers that validate the
line-mutation / meta-edit request bodies before handing off to the Part B
services (`line_services`). Money + lifecycle logic lives in the services; the
serializers are validation/shape only.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import Invoice, InvoiceLine


class InvoicePreviewLineSerializer(serializers.Serializer):
    """Sprint 182 §2 — one row of a PLANNED invoice.

    Shaped from an `ExtraWorkRequest`, not an `InvoiceLine`, because no
    line exists: nothing is stored. The field names deliberately mirror
    `InvoiceLineSerializer` so the frontend renders a preview and a real
    invoice through the same table.
    """

    extra_work = serializers.IntegerField(source="id", read_only=True)
    description = serializers.CharField(source="title", read_only=True)
    line_subtotal = serializers.SerializerMethodField()
    line_vat = serializers.SerializerMethodField()
    line_total = serializers.SerializerMethodField()

    def _amounts(self, ew):
        """This row's money FOR THE CUSTOMER being previewed.

        Sprint 185 E §2 — the plan carries a per-Extra-Work amounts map
        (the customer's share on a shared building, the whole earned
        amount everywhere else) and the row has to read it. Without this
        the preview contradicted itself: the totals came from the plan
        and were the customer's part, while every LINE printed the
        undivided figure — rows of 100 adding up to a total of 60.

        The map arrives through the serializer context, put there by the
        parent that owns the plan. Falling back to the earned amounts
        keeps a line serialized outside a plan (tests, future callers)
        honest rather than crashing.
        """
        from .services import _earned_amounts

        amounts = self.context.get("plan_amounts") or {}
        return amounts.get(ew.id) or _earned_amounts(ew)

    def get_line_subtotal(self, ew):
        return f"{self._amounts(ew)[0] or 0:.2f}"

    def get_line_vat(self, ew):
        return f"{self._amounts(ew)[1] or 0:.2f}"

    def get_line_total(self, ew):
        return f"{self._amounts(ew)[2] or 0:.2f}"


class InvoicePreviewSerializer(serializers.Serializer):
    """Sprint 182 §2 — one invoice that WOULD be created.

    No `id` and no `number`, deliberately: a preview is not an invoice and
    must never be mistaken for one. Numbering happens at Send and has to
    stay gapless, so nothing on this shape can carry a number.
    """

    building = serializers.IntegerField(source="building_id", allow_null=True)
    building_name = serializers.SerializerMethodField()
    department = serializers.IntegerField(
        source="department_id", allow_null=True
    )
    work_type = serializers.IntegerField(source="work_type_id", allow_null=True)
    granularity = serializers.CharField()
    subtotal_amount = serializers.SerializerMethodField()
    vat_amount = serializers.SerializerMethodField()
    total_amount = serializers.SerializerMethodField()
    line_count = serializers.SerializerMethodField()
    lines = serializers.SerializerMethodField()

    def get_building_name(self, plan):
        # The plan owns this, so the PREVIEW PDF labels the same plan the
        # same way (`preview_pdf.render_preview_pdf`).
        return plan.building_name

    def get_subtotal_amount(self, plan):
        return f"{plan.subtotal:.2f}"

    def get_vat_amount(self, plan):
        return f"{plan.vat:.2f}"

    def get_total_amount(self, plan):
        return f"{plan.total:.2f}"

    def get_line_count(self, plan):
        return len(plan.extra_works)

    def get_lines(self, plan):
        # Sprint 185 E §2 — the plan's own per-row amounts travel with
        # the rows, so a line and the total above it are the same money.
        context = dict(self.context)
        context["plan_amounts"] = getattr(plan, "amounts", {}) or {}
        return InvoicePreviewLineSerializer(
            plan.extra_works, many=True, context=context
        ).data


class InvoiceLineSerializer(serializers.ModelSerializer):
    """Read shape for one invoice line (both origins). `extra_work` is the
    source-EW id (NULL for a hand-added line)."""

    class Meta:
        model = InvoiceLine
        fields = [
            "id",
            "ordering",
            "description",
            "extra_work",
            "quantity",
            "unit_price",
            "vat_pct",
            "line_subtotal",
            "line_vat",
            "line_total",
            "period_year",
            "period_month",
            "performed_on",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class InvoiceSerializer(serializers.ModelSerializer):
    """Read shape for one invoice (with its lines) for the Facturen UI."""

    customer_name = serializers.CharField(source="customer.name", read_only=True)
    building_name = serializers.SerializerMethodField()
    # Sprint 132 — set only for an invoice generated at
    # PER_BUILDING_DEPARTMENT_WORK_TYPE granularity; null on every other
    # invoice (mirrors building/building_name's own null-when-unset shape).
    # The combined "<department> - <work type>" display label is composed
    # at RENDER time (frontend `formatInvoiceGroupLabel`, or the PDF's own
    # helper) from these two names — never stored pre-joined.
    department_name = serializers.SerializerMethodField()
    work_type_name = serializers.SerializerMethodField()
    lines = InvoiceLineSerializer(many=True, read_only=True)
    # Sprint 122 (Part B2) — the number of the reversal that credited THIS
    # invoice, if any (null otherwise). Provider-side, so shown regardless of
    # whether that reversal has been sent yet (ISSUED-but-unsent still means
    # "already superseded" from the operator's point of view — see the
    # unsent-credit-note nudge on the reversal's own detail page). Reads the
    # `reverses` reverse relation via `.all()` so a `prefetch_related
    # ("reversed_by")` queryset avoids N+1 on the list endpoint; sorted in
    # Python (not `.order_by()`) so that prefetch cache is actually used.
    credited_by_number = serializers.SerializerMethodField()
    # Sprint 183 §3 — WHO created this invoice, and the label to show.
    #
    # `created_by` was WRITE-ONLY until this sprint: the column was
    # populated and read by no serializer, PDF or list. That is precisely
    # why the month-end job could attribute drafts to a COMPANY_ADMIN who
    # had not created them and nobody noticed — nothing displayed it. It
    # is exposed now BECAUSE the fix is otherwise invisible: an operator
    # has to be able to see that the nightly run, not a colleague,
    # produced these.
    #
    # `created_by_label` is a SerializerMethodField rather than a
    # `source="created_by.email"` CharField deliberately. On a NULL FK,
    # DRF turns the attribute traversal into `SkipField` and OMITS the
    # key entirely — the exact shape that caught Sprint 180's
    # status-history payload. A method field always emits, so a
    # system-created invoice reads "System" instead of a missing key the
    # frontend has to guess about.
    created_by_label = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id",
            "status",
            "number",
            "year",
            "company",
            "customer",
            "customer_name",
            "building",
            "building_name",
            "department",
            "department_name",
            "work_type",
            "work_type_name",
            "period_year",
            "period_month",
            "subtotal_amount",
            "vat_amount",
            "total_amount",
            "optional_fee_label",
            "optional_fee_amount",
            "summary_text",
            "is_reversal",
            "reverses",
            "credited_by_number",
            "issued_at",
            "sent_at",
            # Sprint 180 §1 — is this document FROZEN, and how long is it?
            # Provider-side only. `pdf_frozen_at` is NULL for every draft and
            # for any invoice sent before the freeze existed (those freeze on
            # first access or via `manage.py freeze_invoice_pdfs`), so it
            # doubles as the operator-visible backfill progress indicator.
            # `pdf_page_count` is what makes "an invoice can run to eight
            # pages" checkable from the list without opening each one.
            #
            # `pdf_sha256` is deliberately NOT exposed: it is the integrity
            # witness the tests and a future audit read from the row, and no
            # screen has a use for a hex digest.
            "pdf_frozen_at",
            "pdf_page_count",
            "created_by",
            "created_by_label",
            "created_at",
            "updated_at",
            "lines",
        ]
        read_only_fields = fields

    def get_building_name(self, obj: Invoice):
        return obj.building.name if obj.building_id else None

    def get_department_name(self, obj: Invoice):
        return obj.department.name if obj.department_id else None

    def get_work_type_name(self, obj: Invoice):
        return obj.work_type.name if obj.work_type_id else None

    def get_credited_by_number(self, obj: Invoice):
        reversals = sorted(obj.reversed_by.all(), key=lambda r: r.id, reverse=True)
        return reversals[0].number if reversals else None

    def get_created_by_label(self, obj: Invoice):
        """Who to show as the author. Never blank, never "Unassigned".

        Sprint 183 §3 — a NULL `created_by` means the system created this
        invoice, and it has to READ that way. "Unassigned" was the wrong
        fallback once already this month (Sprint 180's timeline rendered
        a system row as "Unassigned", which names nobody and still
        implies somebody); the label is resolved here, server-side, so
        every consumer gets the same word without re-deciding it.

        A real actor shows their email — the same identifier every other
        provider-side surface in this app uses for a person.
        """
        if obj.created_by_id is None:
            return "System"
        return getattr(obj.created_by, "email", "") or "System"


class CustomerInvoiceLineSerializer(serializers.ModelSerializer):
    """Phase 5 — REDACTED customer read shape for one invoice line.

    Exposes only what a customer should see on their own invoice. Dropped vs
    the provider `InvoiceLineSerializer`:
      * `extra_work` — the internal ExtraWorkRequest id (a provider-internal
        reference; the customer must never see it). THE key redaction.
      * `id` / `ordering` — internal line plumbing; the customer needs neither
        (the list renders in model order; no line-level actions exist).
      * `created_at` / `updated_at` — internal row timestamps.
    """

    class Meta:
        model = InvoiceLine
        fields = [
            "description",
            "quantity",
            "unit_price",
            "vat_pct",
            "line_subtotal",
            "line_vat",
            "line_total",
            "period_year",
            "period_month",
            "performed_on",
        ]
        read_only_fields = fields


class CustomerInvoiceSerializer(serializers.ModelSerializer):
    """Phase 5 — REDACTED customer read shape for one invoice (with lines).

    Keeps `id` (needed to link to the customer detail / PDF endpoints) plus the
    customer-facing document fields. Dropped vs the provider `InvoiceSerializer`
    (each for a reason):
      * `company` — the provider's internal company id (tenant reference).
      * `customer` — the customer's own id; not needed for display
        (customer_name is shown) — kept to display-only fields.
      * `year` — the internal numbering year, already encoded in `number`
        ("YYYY-NNNN").
      * `reverses` — the internal id of the original invoice a credit note
        reverses; would leak another invoice's pk.
      * `created_at` / `updated_at` — internal row timestamps; the
        customer-relevant dates are `issued_at` / `sent_at`.
      * line-level `extra_work` / `id` / `ordering` / timestamps — see
        `CustomerInvoiceLineSerializer`.
    `status` is always SENT in this scope (kept; harmless) and `is_reversal`
    is kept so a credit note reads as such.

    Sprint 122 (Part B2) — `credited_by_number` (the reversing credit note's
    `number`, nothing else) so a credited original stops reading as an open
    debt. Deliberately gated on the reversal itself being SENT (not merely
    existing): the customer scope is SENT-only, so this must never reveal an
    ISSUED-but-unsent reversal before the operator has deliberately sent it —
    that would leak a document the customer cannot otherwise see or open.
    """

    customer_name = serializers.CharField(source="customer.name", read_only=True)
    building_name = serializers.SerializerMethodField()
    # Sprint 132 — same informational shape as building_name; what the
    # invoice covers is customer-facing content, not provider-internal
    # (unlike e.g. the line-level `extra_work` id, which stays redacted).
    department_name = serializers.SerializerMethodField()
    work_type_name = serializers.SerializerMethodField()
    lines = CustomerInvoiceLineSerializer(many=True, read_only=True)
    credited_by_number = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id",
            "number",
            "status",
            "customer_name",
            "building_name",
            "department_name",
            "work_type_name",
            "period_year",
            "period_month",
            "subtotal_amount",
            "vat_amount",
            "total_amount",
            "optional_fee_label",
            "optional_fee_amount",
            "summary_text",
            "is_reversal",
            "credited_by_number",
            "issued_at",
            "sent_at",
            "lines",
        ]
        read_only_fields = fields

    def get_building_name(self, obj: Invoice):
        return obj.building.name if obj.building_id else None

    def get_department_name(self, obj: Invoice):
        return obj.department.name if obj.department_id else None

    def get_work_type_name(self, obj: Invoice):
        return obj.work_type.name if obj.work_type_id else None

    def get_credited_by_number(self, obj: Invoice):
        sent_reversals = sorted(
            (r for r in obj.reversed_by.all() if r.status == Invoice.Status.SENT),
            key=lambda r: r.id,
            reverse=True,
        )
        return sent_reversals[0].number if sent_reversals else None


class InvoiceLineWriteSerializer(serializers.Serializer):
    """Validate an add / update line body. No defaults: only the keys the
    client actually sent land in `validated_data`, so the Part B services
    apply their own defaults (add) and PATCH edits only the supplied fields
    (update, `partial=True`)."""

    description = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=False
    )
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    unit_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    vat_pct = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False
    )
    period_year = serializers.IntegerField(required=False, allow_null=True)
    period_month = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=12
    )
    performed_on = serializers.DateField(required=False, allow_null=True)


class InvoiceMetaSerializer(serializers.Serializer):
    """Validate a PATCH /invoices/<id>/ body — the DRAFT page-1 meta:
    hand-written summary + optional free-text fee."""

    summary_text = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=False
    )
    optional_fee_label = serializers.CharField(
        required=False, allow_blank=True, max_length=255
    )
    optional_fee_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True
    )
