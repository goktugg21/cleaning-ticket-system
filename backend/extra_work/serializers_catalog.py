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
"""
from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from .models import CustomerServicePrice, Service, ServiceCategory


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
    a generic ValidationError).
    """

    category_name = serializers.CharField(
        source="category.name", read_only=True
    )

    class Meta:
        model = Service
        fields = [
            "id",
            "category",
            "category_name",
            "name",
            "description",
            "unit_type",
            "default_unit_price",
            "default_vat_pct",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "category_name", "created_at", "updated_at"]

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
        return attrs
