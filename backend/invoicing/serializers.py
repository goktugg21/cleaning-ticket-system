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
    lines = InvoiceLineSerializer(many=True, read_only=True)

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
            "issued_at",
            "sent_at",
            "created_at",
            "updated_at",
            "lines",
        ]
        read_only_fields = fields

    def get_building_name(self, obj: Invoice):
        return obj.building.name if obj.building_id else None


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
    """

    customer_name = serializers.CharField(source="customer.name", read_only=True)
    building_name = serializers.SerializerMethodField()
    lines = CustomerInvoiceLineSerializer(many=True, read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "number",
            "status",
            "customer_name",
            "building_name",
            "period_year",
            "period_month",
            "subtotal_amount",
            "vat_amount",
            "total_amount",
            "optional_fee_label",
            "optional_fee_amount",
            "summary_text",
            "is_reversal",
            "issued_at",
            "sent_at",
            "lines",
        ]
        read_only_fields = fields

    def get_building_name(self, obj: Invoice):
        return obj.building.name if obj.building_id else None


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
