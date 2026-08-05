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

Sprint 142:
  * `ServiceCategorySerializer` gains the same `company` handling —
    writable PK on CREATE, read-only on UPDATE — plus a manual
    per-company case-insensitive name-uniqueness pre-check, replacing
    the `UniqueValidator` DRF used to derive from the now-removed
    field-level `unique=True`.
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
    ManagedUnit,
    Service,
    ServiceCategory,
)


def _resolve_effective_unit(attrs, instance):
    """Sprint 123 — shared OTHER-unit resolution for `ServiceSerializer`
    and `CustomerCustomPriceSerializer`.

    Rules (applied to `attrs` in place, returns nothing):
      * A `managed_unit` may only be set when the EFFECTIVE unit_type
        (attrs, falling back to the instance) is OTHER — for any
        concrete unit type it is forced back to None, mirroring the
        pre-existing `custom_unit_label`-forced-blank rule so a row
        switched off OTHER can never strand a stale link.
      * When `managed_unit` is set (and unit_type is OTHER),
        `custom_unit_label` is overwritten with the unit's CURRENT
        `label` — the linked unit is authoritative; any client-supplied
        `custom_unit_label` is ignored in that case. `custom_unit_label`
        stays the single value every other consumer (PDF, exports,
        lists) renders, whether or not a row has adopted the catalog.
      * When `managed_unit` is NOT set (None, the pre-Sprint-123 shape),
        behaviour is completely unchanged: the caller's existing
        blank-for-concrete / required-for-OTHER label validation runs
        exactly as before.
    """
    unit_type = attrs.get("unit_type", getattr(instance, "unit_type", None))
    managed_unit_supplied = "managed_unit" in attrs
    managed_unit = attrs.get(
        "managed_unit", getattr(instance, "managed_unit", None)
    )
    if unit_type != ExtraWorkPricingUnitType.OTHER:
        if managed_unit_supplied or instance is not None:
            attrs["managed_unit"] = None
        return None
    if managed_unit is not None:
        attrs["managed_unit"] = managed_unit
        attrs["custom_unit_label"] = managed_unit.label
        return managed_unit
    return None


class ServiceCategorySerializer(serializers.ModelSerializer):
    """Sprint 138 §2 — `service_count` / `active_service_count` are the
    numbers the catalog UI needs to decide which actions to OFFER on a
    category, rather than offering all of them and letting the operator
    discover which ones 400.

    `Service.category` is `on_delete=PROTECT` and NOT nullable, so a
    category holding ANY service is permanently undeletable; a category
    holding none is deletable whether it is active or archived. That is
    exactly `service_count == 0`. `active_service_count` is what the
    cascade-archive confirmation counts ("this will also deactivate N
    services").

    Both come from an annotation on the view's queryset (one query for
    the whole page — see `ServiceCategoryListCreateView.get_queryset`).
    The `getattr` fallback only fires for a single object that never
    went through that queryset (the CREATE/UPDATE response), so it can
    never produce an N+1 on a list.

    Sprint 142 — `company` is a writable PK on CREATE only, exactly
    mirroring `ServiceSerializer` / `ManagedUnitSerializer`: optional on
    the wire (the view's `_resolve_catalog_create_company` defaults it
    for a COMPANY_ADMIN), and pinned read-only on UPDATE. Re-pinning an
    existing category to another provider would strand every `Service`
    still inside it in a category their own company cannot see — the
    exact defect `_enforce_same_company_category` exists to prevent —
    so the field is simply not movable.
    """

    service_count = serializers.SerializerMethodField()
    active_service_count = serializers.SerializerMethodField()
    company_name = serializers.CharField(
        source="company.name", read_only=True
    )
    company = serializers.PrimaryKeyRelatedField(
        queryset=Company.objects.all(),
        required=False,
        allow_null=True,
        default=None,
    )

    class Meta:
        model = ServiceCategory
        fields = [
            "id",
            "company",
            "company_name",
            "name",
            "description",
            "is_active",
            "service_count",
            "active_service_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "company_name",
            "service_count",
            "active_service_count",
            "created_at",
            "updated_at",
        ]

    def get_fields(self):
        fields = super().get_fields()
        if self.instance is not None:
            # UPDATE path — pin `company` to its current value; see the
            # class docstring for why it must not move.
            fields["company"].read_only = True
        return fields

    def validate(self, attrs):
        """Sprint 142 — friendly-400 pre-check for the per-company,
        case/whitespace-insensitive name uniqueness.

        Needed because dropping the field-level `unique=True` also
        dropped the `UniqueValidator` DRF generated from it, and DRF
        cannot generate one for an EXPRESSION constraint
        (`Lower(Trim("name")), company`) the way it does for a plain
        `UniqueConstraint(fields=[...])`. Without this, a duplicate name
        would reach Postgres and surface as a 500 instead of the 400
        this endpoint has always returned.

        Exactly the shape `ManagedUnitSerializer.validate` uses,
        including its limitation: on a COMPANY_ADMIN's CREATE that omits
        `company`, the target is not resolved until `perform_create`
        runs, so the pre-check is skipped and the view's
        `IntegrityError` handler is the sole backstop.
        """
        name = attrs.get("name", getattr(self.instance, "name", None))
        company = attrs.get("company")
        if company is None and self.instance is not None:
            company = self.instance.company
        if name and company is not None:
            normalized = name.strip().lower()
            existing = ServiceCategory.objects.filter(company=company)
            if self.instance is not None:
                existing = existing.exclude(pk=self.instance.pk)
            if any(c.name.strip().lower() == normalized for c in existing):
                raise serializers.ValidationError(
                    {
                        "name": [
                            serializers.ErrorDetail(
                                f"A category named {name!r} already "
                                "exists for this company.",
                                code="service_category_name_not_unique",
                            )
                        ]
                    }
                )
        return attrs

    def get_service_count(self, obj) -> int:
        annotated = getattr(obj, "annotated_service_count", None)
        if annotated is not None:
            return int(annotated)
        return obj.services.count()

    def get_active_service_count(self, obj) -> int:
        annotated = getattr(obj, "annotated_active_service_count", None)
        if annotated is not None:
            return int(annotated)
        return obj.services.filter(is_active=True).count()


class ManagedUnitSerializer(serializers.ModelSerializer):
    """Sprint 123 — read/write serializer for the per-company managed
    unit catalog (`ManagedUnit`). Mirrors `ServiceSerializer`'s
    `company` handling exactly: optional on the wire on CREATE (the
    view defaults it for a COMPANY_ADMIN, same
    `_resolve_catalog_create_company` helper), read-only on UPDATE
    (re-pinning an existing unit to a different provider would strand
    every Service / CustomerCustomPrice row already linked to it).

    `label` is declared with `trim_whitespace=False` so `validate()`
    owns the stripping (matching the `custom_unit_label` field's own
    convention elsewhere in this module) — a whitespace-only label must
    reach the validator intact rather than being silently trimmed to a
    blank first.

    The case/whitespace-insensitive uniqueness pre-check here is a
    friendly-400 convenience layer; `ManagedUnit`'s
    `UniqueConstraint(Lower(Trim("label")), "company", ...)` is the
    real DB-level backstop for a race condition or a direct-ORM write.
    """

    company_name = serializers.CharField(
        source="company.name", read_only=True
    )
    company = serializers.PrimaryKeyRelatedField(
        queryset=Company.objects.all(),
        required=False,
        allow_null=True,
        default=None,
    )
    label = serializers.CharField(max_length=50, trim_whitespace=False)

    class Meta:
        model = ManagedUnit
        fields = [
            "id",
            "company",
            "company_name",
            "label",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "company_name", "created_at", "updated_at"]

    def get_fields(self):
        fields = super().get_fields()
        if self.instance is not None:
            fields["company"].read_only = True
        return fields

    def validate_label(self, value):
        stripped = (value or "").strip()
        if not stripped:
            raise serializers.ValidationError(
                serializers.ErrorDetail(
                    "label must not be blank.",
                    code="managed_unit_label_required",
                )
            )
        return stripped

    def validate(self, attrs):
        label = attrs.get("label", getattr(self.instance, "label", None))
        company = attrs.get("company")
        if company is None and self.instance is not None:
            company = self.instance.company
        # `company` may still be None here on CREATE when a COMPANY_ADMIN
        # omitted it (the view resolves + defaults it in perform_create,
        # AFTER this validate() runs) -- skip the pre-check in that case
        # and rely on the DB constraint as the sole backstop; the view
        # cannot re-run this same friendly check post-resolution without
        # duplicating the query, so a race there surfaces as a 500-turned
        # -400 via the IntegrityError handler in the view instead.
        if label and company is not None:
            normalized = label.lower()
            existing = ManagedUnit.objects.filter(company=company)
            if self.instance is not None:
                existing = existing.exclude(pk=self.instance.pk)
            if any(u.label.strip().lower() == normalized for u in existing):
                raise serializers.ValidationError(
                    {
                        "label": [
                            serializers.ErrorDetail(
                                f"A unit named {label!r} already exists "
                                "for this company.",
                                code="managed_unit_label_not_unique",
                            )
                        ]
                    }
                )
        return attrs


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
    # may omit it; the view's `_resolve_catalog_create_company`
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
    # Sprint 123 — optional managed-unit catalog link (only meaningful
    # for unit_type=OTHER; see `_resolve_effective_unit`). Cross-company
    # ownership (managed_unit.company == the row's company) is checked
    # in the view AFTER company resolution, not here — see
    # `views_catalog.py::_enforce_same_company_managed_unit`.
    managed_unit = serializers.PrimaryKeyRelatedField(
        queryset=ManagedUnit.objects.all(),
        required=False,
        allow_null=True,
    )
    managed_unit_label = serializers.CharField(
        source="managed_unit.label", read_only=True, default=None
    )
    # Sprint 138 §1 — does ANY CustomerServicePrice row reference this
    # service, active or ARCHIVED? `CustomerServicePrice.service` is
    # `on_delete=PROTECT`, and Sprint 137 item 2 established that
    # "deleting" a price archives it rather than destroying it — so a
    # service that has ever been priced for any customer is permanently
    # undeletable, and the operator's archived prices still block it.
    # That produced the "Deleted 0 service(s), 1 failed" screen: the UI
    # offered Delete on a row where it could never succeed, and the 400
    # named prices the operator believed he had already deleted.
    #
    # The UI uses this to offer Deactiveren instead of Delete. Sourced
    # from an `Exists` annotation on the view queryset (ONE subquery for
    # the whole page, no per-row query); the `getattr` fallback only
    # fires for a single un-annotated object (the CREATE/UPDATE
    # response), so it cannot become an N+1 on a list.
    has_price_rows = serializers.SerializerMethodField()

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
            "managed_unit",
            "managed_unit_label",
            "default_unit_price",
            "default_vat_pct",
            "is_active",
            "has_price_rows",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "company_name",
            "category_name",
            "managed_unit_label",
            "has_price_rows",
            "created_at",
            "updated_at",
        ]

    def get_has_price_rows(self, obj) -> bool:
        annotated = getattr(obj, "annotated_has_price_rows", None)
        if annotated is not None:
            return bool(annotated)
        return obj.customer_prices.exists()

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
        # Sprint 123 — resolve managed_unit FIRST: nulls it out for a
        # non-OTHER row, or (when set) overwrites custom_unit_label with
        # the linked unit's current label. Composes with the unchanged
        # RF-2 logic below by construction — see the helper's docstring.
        _resolve_effective_unit(attrs, self.instance)
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
    # Sprint 123 — optional managed-unit catalog link (see
    # ServiceSerializer's identical field + `_resolve_effective_unit`).
    # Cross-company ownership (managed_unit.company == customer.company)
    # is checked in the view, which is the only place that already knows
    # the URL-bound customer at validate() time.
    managed_unit = serializers.PrimaryKeyRelatedField(
        queryset=ManagedUnit.objects.all(),
        required=False,
        allow_null=True,
    )
    managed_unit_label = serializers.CharField(
        source="managed_unit.label", read_only=True, default=None
    )

    class Meta:
        model = CustomerCustomPrice
        fields = [
            "id",
            "custom_name",
            "unit_type",
            "unit_type_display",
            "custom_unit_label",
            "managed_unit",
            "managed_unit_label",
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
            "managed_unit_label",
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
        # Sprint 123 — resolve managed_unit FIRST; see ServiceSerializer's
        # identical call for the full rationale.
        _resolve_effective_unit(attrs, self.instance)
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
