"""
Sprint 28 Batch 5 — serializers for the provider service catalog
(`ServiceCategory`, `Service`) and the per-customer contract-price
rows (`CustomerServicePrice`).

The catalog serializers are intentionally explicit about their field
list so an accidental future addition of an internal-only column on
the model is NOT silently exposed on the wire.

The customer-pricing serializer marks `customer` as read-only — the
URL kwarg owns the binding so a PATCH/POST body cannot smuggle a
different customer. The view layer supplies `customer=...` via
`.save()`.

Sprint 3B:
  * `ServiceSerializer.company` is a writable PK on create; SA may
    pick any company; COMPANY_ADMIN must pick one they belong to
    (view-layer enforces). Read-only after create.
  * `to_representation` strips `default_unit_price` and
    `default_vat_pct` for actors that do not pass
    `catalog_scope.can_view_provider_defaults` — the SoT §5.7/§5.8
    floor: STAFF and CUSTOMER_USER never see provider defaults;
    cross-company provider operators don't either.
  * `CustomerServicePriceSerializer.validate` rejects writes where
    `service.company_id != customer.company_id` (stable code
    `service_customer_company_mismatch`).
"""
from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from companies.models import Company

from .catalog_scope import can_view_provider_defaults
from .models import (
    CustomerCustomPrice,
    CustomerServicePrice,
    ExtraWorkPricingUnitType,
    Service,
    ServiceCategory,
)


class ServiceCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceCategory
        fields = [
            "id",
            "name",
            "description",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ServiceSerializer(serializers.ModelSerializer):
    """Read/write serializer for `extra_work.Service`.

    `category` is a writable PK; `category_name` is a read-only
    convenience field so the catalog UI does not need a second fetch
    to display the parent category name.

    `default_unit_price` and `default_vat_pct` are non-negative
    decimals (the validators on the model enforce >= 0; the
    serializer's `validate_*` methods give a friendly 400 instead of
    a generic ValidationError). Sprint 3B strips both fields from
    the response payload for actors that fail
    `can_view_provider_defaults`.

    `company` is a writable PK on CREATE only (write-once); the
    view layer validates the actor is allowed to write to that
    company. On UPDATE the field is read-only — re-pinning an
    existing Service to a different provider is destructive
    relative to historical CustomerServicePrice / ExtraWork
    references and is out of scope for this sprint.
    """

    category_name = serializers.CharField(
        source="category.name", read_only=True
    )
    company_name = serializers.CharField(
        source="company.name", read_only=True
    )
    # Sprint 3B — `company` is OPTIONAL on the wire (CA frontend
    # may omit it; the view's `_resolve_service_create_company`
    # defaults to the actor's own company). When supplied, the
    # view runs the cross-company guard before saving.
    company = serializers.PrimaryKeyRelatedField(
        queryset=Company.objects.all(),
        required=False,
        allow_null=True,
        default=None,
    )
    # RF-2 (mirror) — declared explicitly with trim_whitespace=False so the
    # validate() rule owns the stripping: a supplied whitespace-only label
    # must reach the validator intact (DRF's default trimming would collapse
    # it to a legal blank first). Same shape as the ProposalLine field.
    custom_unit_label = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
    )

    class Meta:
        model = Service
        fields = [
            "id",
            "company",
            "company_name",
            "category",
            "category_name",
            "name",
            "description",
            "unit_type",
            "custom_unit_label",
            "default_unit_price",
            "default_vat_pct",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "company_name",
            "category_name",
            "created_at",
            "updated_at",
        ]

    def get_fields(self):
        fields = super().get_fields()
        if self.instance is not None:
            # UPDATE path — pin `company` to its current value;
            # re-pinning is destructive (see class docstring).
            fields["company"].read_only = True
        return fields

    def validate_default_unit_price(self, value):
        if value is not None and value < Decimal("0"):
            raise serializers.ValidationError(
                "default_unit_price must be non-negative."
            )
        return value

    def validate_default_vat_pct(self, value):
        if value is not None and value < Decimal("0"):
            raise serializers.ValidationError(
                "default_vat_pct must be non-negative."
            )
        return value

    def validate(self, attrs):
        # RF-2 (mirror of CustomerCustomPriceSerializer) — the unit label
        # only carries meaning for OTHER. Resolve the effective unit_type +
        # label (a PATCH may change either field independently). For a
        # concrete unit type the label is forced blank so a row can never
        # persist a label that contradicts its unit. For OTHER the (stripped)
        # label is REQUIRED — an "Other" unit with no name renders as nothing.
        unit_type = attrs.get(
            "unit_type", getattr(self.instance, "unit_type", None)
        )
        if unit_type != ExtraWorkPricingUnitType.OTHER:
            if "custom_unit_label" in attrs or self.instance is not None:
                attrs["custom_unit_label"] = ""
        else:
            label = attrs.get(
                "custom_unit_label",
                getattr(self.instance, "custom_unit_label", ""),
            )
            label = (label or "").strip()
            if not label:
                raise serializers.ValidationError(
                    {
                        "custom_unit_label": [
                            serializers.ErrorDetail(
                                "A unit name is required when the unit "
                                "type is Other.",
                                code="custom_unit_label_required",
                            )
                        ]
                    }
                )
            attrs["custom_unit_label"] = label
        return attrs

    # Sprint 3B — role-aware default-price stripping. Provider
    # operators in scope see `default_unit_price` + `default_vat_pct`;
    # STAFF / CUSTOMER_USER / out-of-scope operators don't. The
    # fields are dropped from the rendered dict so a CUSTOMER_USER
    # response is truly free of provider-side reference prices
    # (this is the SoT §5.7 + §11.1 floor: "Customer must not see
    # provider default prices" — backend is the gate, frontend
    # MUST NOT infer).
    _PROVIDER_DEFAULT_FIELDS = ("default_unit_price", "default_vat_pct")

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request") if self.context else None
        viewer = getattr(request, "user", None) if request else None
        if not can_view_provider_defaults(viewer, instance):
            for field in self._PROVIDER_DEFAULT_FIELDS:
                data.pop(field, None)
        return data


class CustomerServicePriceSerializer(serializers.ModelSerializer):
    """Read/write serializer for `extra_work.CustomerServicePrice`.

    `customer` is read-only — the URL kwarg owns the binding so a
    body-level `customer` cannot redirect the row to another tenant.
    The view's `perform_create` / `get_object` supply the customer.

    Validation:
      * `valid_to`, when set, must be on or after `valid_from`.
      * `unit_price` and `vat_pct` must be non-negative.
    """

    customer = serializers.PrimaryKeyRelatedField(read_only=True)
    service_name = serializers.CharField(
        source="service.name", read_only=True
    )

    class Meta:
        model = CustomerServicePrice
        fields = [
            "id",
            "service",
            "service_name",
            "customer",
            "unit_price",
            "vat_pct",
            "valid_from",
            "valid_to",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "service_name",
            "customer",
            "created_at",
            "updated_at",
        ]

    def validate_unit_price(self, value):
        if value is not None and value < Decimal("0"):
            raise serializers.ValidationError(
                "unit_price must be non-negative."
            )
        return value

    def validate_vat_pct(self, value):
        if value is not None and value < Decimal("0"):
            raise serializers.ValidationError(
                "vat_pct must be non-negative."
            )
        return value

    def validate(self, attrs):
        # `valid_from` / `valid_to` interplay. On PATCH only one of
        # the two may be present in the payload — fall back to the
        # instance value for the other.
        valid_from = attrs.get(
            "valid_from",
            getattr(self.instance, "valid_from", None),
        )
        valid_to = attrs.get(
            "valid_to",
            getattr(self.instance, "valid_to", None),
        )
        if valid_from is not None and valid_to is not None:
            if valid_to < valid_from:
                raise serializers.ValidationError(
                    {"valid_to": "valid_to must be on or after valid_from."}
                )

        # Sprint 3B — cross-company guard. The price's `service`
        # company MUST match the URL-bound customer's company.
        # The view layer supplies the customer via
        # `serializer.save(customer=...)`; on CREATE the customer
        # is not in `attrs` yet, so we read it from the view's
        # context. On UPDATE the customer is fixed by the URL
        # (and the FK is read-only), so we compare against
        # `self.instance.customer`.
        service = attrs.get(
            "service", getattr(self.instance, "service", None)
        )
        if service is not None:
            customer = None
            view = self.context.get("view") if self.context else None
            if self.instance is not None:
                customer = self.instance.customer
            elif view is not None and hasattr(view, "_get_customer"):
                # Defensive — the view exposes a `_get_customer`
                # helper that already runs the per-company perm
                # check. Reuse it so we honour the same 403 path
                # before the 400 below has a chance to fire.
                try:
                    customer = view._get_customer()
                except Exception:  # noqa: BLE001 - any failure here
                    # is a 403 / 404 the view will surface on its
                    # own; leave the cross-company check for now.
                    customer = None
            if (
                customer is not None
                and service.company_id is not None
                and customer.company_id != service.company_id
            ):
                raise serializers.ValidationError(
                    {
                        "service": [
                            serializers.ErrorDetail(
                                "Service belongs to a different "
                                "provider company than the "
                                "customer.",
                                code="service_customer_company_mismatch",
                            )
                        ]
                    }
                )
        return attrs


class CustomerCustomPriceSerializer(serializers.ModelSerializer):
    """M5 A — read/write serializer for CustomerCustomPrice. `customer`
    is read-only — the URL kwarg owns the binding. valid_to (if set)
    must be >= valid_from; unit_price / vat_pct must be non-negative.

    RF-2 — `custom_unit_label` is the operator-supplied unit name and is
    only meaningful when `unit_type == OTHER`. Two symmetric rules on the
    effective unit type (a PATCH may move either field independently):
    OTHER REQUIRES a non-empty label (HTTP 400 with code
    `custom_unit_label_required`) — an "Other" unit with no name renders
    as nothing on the price line; any concrete unit type forces the
    label blank rather than rejecting, so switching an existing OTHER row
    to a concrete unit cannot strand a stale label. A legacy empty-label
    OTHER row (created before this rule) must therefore supply a label on
    its next update — intentional.
    """

    customer = serializers.PrimaryKeyRelatedField(read_only=True)
    unit_type_display = serializers.CharField(
        source="get_unit_type_display", read_only=True
    )

    class Meta:
        model = CustomerCustomPrice
        fields = [
            "id",
            "custom_name",
            "unit_type",
            "unit_type_display",
            "custom_unit_label",
            "customer",
            "unit_price",
            "vat_pct",
            "valid_from",
            "valid_to",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "unit_type_display",
            "customer",
            "created_at",
            "updated_at",
        ]

    def validate_unit_price(self, value):
        if value is not None and value < Decimal("0"):
            raise serializers.ValidationError("unit_price must be non-negative.")
        return value

    def validate_vat_pct(self, value):
        if value is not None and value < Decimal("0"):
            raise serializers.ValidationError("vat_pct must be non-negative.")
        return value

    def validate(self, attrs):
        valid_from = attrs.get(
            "valid_from", getattr(self.instance, "valid_from", None)
        )
        valid_to = attrs.get(
            "valid_to", getattr(self.instance, "valid_to", None)
        )
        # RF-2 — the unit label only carries meaning for OTHER. Resolve
        # the effective unit_type + label (a PATCH may change either field
        # independently). For a concrete unit type the label is forced
        # blank so a row can never persist a label that contradicts its
        # unit. For OTHER the (stripped) label is REQUIRED — an "Other"
        # unit with no name renders as nothing on the price line.
        unit_type = attrs.get(
            "unit_type", getattr(self.instance, "unit_type", None)
        )
        if unit_type != ExtraWorkPricingUnitType.OTHER:
            if "custom_unit_label" in attrs or self.instance is not None:
                attrs["custom_unit_label"] = ""
        else:
            label = attrs.get(
                "custom_unit_label",
                getattr(self.instance, "custom_unit_label", ""),
            )
            label = (label or "").strip()
            if not label:
                raise serializers.ValidationError(
                    {
                        "custom_unit_label": [
                            serializers.ErrorDetail(
                                "A unit name is required when the unit "
                                "type is Other.",
                                code="custom_unit_label_required",
                            )
                        ]
                    }
                )
            attrs["custom_unit_label"] = label

        if valid_from is not None and valid_to is not None and valid_to < valid_from:
            raise serializers.ValidationError(
                {"valid_to": "valid_to must be on or after valid_from."}
            )
        return attrs
