"""
Sprint 26B — Extra Work serializers.

Customer-visible serializers strip provider-internal fields
(internal_cost_note, manager_note, override_*) so a CUSTOMER_USER
never sees provider workflow. The serializer chooses the right
shape based on `context["request"].user.role`.
"""
from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from accounts.models import UserRole
from buildings.models import Building
from companies.models import Company
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
)
from customers.permissions import access_has_permission, user_can

from .models import (
    ExtraWorkCategory,
    ExtraWorkPricingLineItem,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkRoutingDecision,
    ExtraWorkStatus,
    Proposal,
    ProposalLine,
    ProposalStatus,
    ProposalTimelineEvent,
    ProposalTimelineEventType,
    Service,
)
from .pricing import resolve_price
from .proposal_state_machine import allowed_next_proposal_statuses
from .state_machine import allowed_next_statuses


def _is_customer(user) -> bool:
    return user is not None and user.role == UserRole.CUSTOMER_USER


# ---------------------------------------------------------------------------
# Pricing line item
# ---------------------------------------------------------------------------
class ExtraWorkPricingLineItemSerializer(serializers.ModelSerializer):
    """
    Provider-side serializer (full shape including internal_cost_note).
    For customer-side reads use ExtraWorkPricingLineItemCustomerSerializer.
    """

    class Meta:
        model = ExtraWorkPricingLineItem
        fields = [
            "id",
            "description",
            "unit_type",
            "quantity",
            "unit_price",
            "vat_rate",
            "subtotal",
            "vat_amount",
            "total",
            "customer_visible_note",
            "internal_cost_note",
            "created_at",
            "updated_at",
        ]
        # Stored computed totals — backend always recomputes them in
        # model.save() so frontend-supplied values would be silently
        # overwritten anyway. Mark read-only so clients don't try.
        read_only_fields = [
            "id",
            "subtotal",
            "vat_amount",
            "total",
            "created_at",
            "updated_at",
        ]

    def validate_quantity(self, value):
        if value < Decimal("0"):
            raise serializers.ValidationError("Must be non-negative.")
        return value

    def validate_unit_price(self, value):
        if value < Decimal("0"):
            raise serializers.ValidationError("Must be non-negative.")
        return value

    def validate_vat_rate(self, value):
        if value < Decimal("0"):
            raise serializers.ValidationError("Must be non-negative.")
        return value


class ExtraWorkPricingLineItemCustomerSerializer(serializers.ModelSerializer):
    """
    Customer-facing line item — DROPS `internal_cost_note`. Used in
    the nested representation on ExtraWorkRequestDetailSerializer
    when the requesting user is a CUSTOMER_USER.
    """

    class Meta:
        model = ExtraWorkPricingLineItem
        fields = [
            "id",
            "description",
            "unit_type",
            "quantity",
            "unit_price",
            "vat_rate",
            "subtotal",
            "vat_amount",
            "total",
            "customer_visible_note",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Sprint 28 Batch 6 — cart line item
# ---------------------------------------------------------------------------
class ExtraWorkRequestItemSerializer(serializers.ModelSerializer):
    """
    Nested line-item serializer for the Extra Work cart flow.

    Used in two roles:
      * Read-only on `ExtraWorkRequestDetailSerializer.line_items`.
      * Write-only nested input on `ExtraWorkRequestCreateSerializer`,
        accepting the per-line `service` + `quantity` + `requested_date`
        + `customer_note`. `unit_type` is denormalised from the
        chosen `Service.unit_type` by the parent serializer's
        `create()` — clients do NOT supply it on the wire.

    `service` is **required on the wire** for new submissions (the
    Batch 6 contract: no service ⇒ proposal-only line, and the
    cart flow only accepts catalog-linked lines). The DB column is
    NULL-allowed only so the migration backfill can adopt legacy
    single-line rows; the serializer never accepts NULL.
    """

    service = serializers.PrimaryKeyRelatedField(
        queryset=Service.objects.all(),
    )
    service_name = serializers.CharField(
        source="service.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = ExtraWorkRequestItem
        fields = [
            "id",
            "service",
            "service_name",
            "quantity",
            "unit_type",
            "requested_date",
            "customer_note",
        ]
        read_only_fields = [
            "id",
            "service_name",
            # `unit_type` is denormalised by the parent serializer at
            # create time from Service.unit_type — clients must not
            # supply it.
            "unit_type",
        ]

    def validate_quantity(self, value):
        if value <= Decimal("0"):
            raise serializers.ValidationError(
                "Quantity must be greater than zero."
            )
        return value

    def validate_service(self, value):
        if value is None:
            raise serializers.ValidationError(
                "Service is required for new line items."
            )
        if not value.is_active:
            raise serializers.ValidationError(
                "Cannot order an inactive service."
            )
        return value


# ---------------------------------------------------------------------------
# Extra Work — list (lean)
# ---------------------------------------------------------------------------
class ExtraWorkRequestListSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source="company.name", read_only=True)
    building_name = serializers.CharField(source="building.name", read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    created_by_email = serializers.CharField(
        source="created_by.email", read_only=True
    )

    class Meta:
        model = ExtraWorkRequest
        fields = [
            "id",
            "company",
            "company_name",
            "building",
            "building_name",
            "customer",
            "customer_name",
            "title",
            "category",
            "urgency",
            "status",
            # Sprint 28 Batch 6 — cart routing taxonomy. Surfaced on
            # the lean list shape so the inbox / overview UIs can
            # branch on INSTANT vs PROPOSAL without a detail fetch.
            "routing_decision",
            "subtotal_amount",
            "vat_amount",
            "total_amount",
            "created_by",
            "created_by_email",
            "requested_at",
            "updated_at",
            "pricing_proposed_at",
            "customer_decided_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Extra Work — detail (role-aware)
# ---------------------------------------------------------------------------
class ExtraWorkRequestDetailSerializer(serializers.ModelSerializer):
    """
    Role-aware detail serializer. Provider operators see every
    field. CUSTOMER_USER never sees `manager_note`,
    `internal_cost_note`, `override_*`, or pricing-item
    `internal_cost_note` rows.
    """

    company_name = serializers.CharField(source="company.name", read_only=True)
    building_name = serializers.CharField(source="building.name", read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    created_by_email = serializers.CharField(
        source="created_by.email", read_only=True
    )
    pricing_line_items = serializers.SerializerMethodField()
    line_items = ExtraWorkRequestItemSerializer(many=True, read_only=True)
    allowed_next_statuses = serializers.SerializerMethodField()

    class Meta:
        model = ExtraWorkRequest
        fields = [
            "id",
            "company",
            "company_name",
            "building",
            "building_name",
            "customer",
            "customer_name",
            "title",
            "description",
            "category",
            "category_other_text",
            "urgency",
            "preferred_date",
            "status",
            # Sprint 28 Batch 6 — cart routing taxonomy + nested line
            # items. routing_decision is computed at submission time by
            # the create serializer and is read-only thereafter (Batch 7
            # will act on the value; Batch 6 only stores it).
            "routing_decision",
            "line_items",
            "customer_visible_note",
            "pricing_note",
            # Provider-only fields below — explicitly stripped for
            # CUSTOMER_USER in to_representation().
            "manager_note",
            "internal_cost_note",
            "override_by",
            "override_reason",
            "override_at",
            # Computed totals (always visible).
            "subtotal_amount",
            "vat_amount",
            "total_amount",
            # Bookkeeping.
            "created_by",
            "created_by_email",
            "requested_at",
            "updated_at",
            "pricing_proposed_at",
            "customer_decided_at",
            "pricing_line_items",
            "allowed_next_statuses",
        ]
        read_only_fields = [
            "id",
            "company",
            "company_name",
            "building",
            "building_name",
            "customer",
            "customer_name",
            "status",
            "routing_decision",
            "subtotal_amount",
            "vat_amount",
            "total_amount",
            "created_by",
            "created_by_email",
            "requested_at",
            "updated_at",
            "override_by",
            "override_at",
            "pricing_proposed_at",
            "customer_decided_at",
        ]

    _PROVIDER_ONLY_FIELDS = (
        "manager_note",
        "internal_cost_note",
        "override_by",
        "override_reason",
        "override_at",
    )

    def get_pricing_line_items(self, obj):
        user = self.context.get("request").user if self.context.get("request") else None
        qs = obj.pricing_line_items.all()
        if _is_customer(user):
            return ExtraWorkPricingLineItemCustomerSerializer(qs, many=True).data
        return ExtraWorkPricingLineItemSerializer(qs, many=True).data

    def get_allowed_next_statuses(self, obj):
        user = self.context.get("request").user if self.context.get("request") else None
        if user is None or not user.is_authenticated:
            return []
        return list(allowed_next_statuses(user, obj))

    def to_representation(self, instance):
        data = super().to_representation(instance)
        user = self.context.get("request").user if self.context.get("request") else None
        if _is_customer(user):
            for field in self._PROVIDER_ONLY_FIELDS:
                data.pop(field, None)
        return data


# ---------------------------------------------------------------------------
# Extra Work — create
# ---------------------------------------------------------------------------
class ExtraWorkRequestCreateSerializer(serializers.ModelSerializer):
    """
    Customer-side create. Resolves company from the customer
    (CustomerBuildingMembership guarantees a single customer can
    only live under one company), enforces that:
      * the customer belongs to the building via
        CustomerBuildingMembership,
      * the actor has an active CustomerUserBuildingAccess row for
        the (customer, building) pair AND that row resolves
        `customer.extra_work.create`,
      * category=OTHER requires category_other_text,
      * Sprint 28 Batch 6: at least one `line_items` entry is
        supplied, each line references a distinct active Service,
        each line carries a `requested_date`, and `quantity > 0`.
        The serializer denormalises `Service.unit_type` onto each
        new `ExtraWorkRequestItem` at create time so a later catalog
        edit cannot rewrite the historical cart line's pricing
        semantics.

    Routing decision: after creating the line items, the serializer
    calls `resolve_price(line.service, request.customer, on=line.
    requested_date)` per line. If EVERY line resolves to an active
    `CustomerServicePrice` the request's `routing_decision` is set
    to "INSTANT"; if ANY line returns None the value is "PROPOSAL".
    The value is stored on the request and read back through the
    detail serializer; Batch 6 does NOT spawn tickets or trigger a
    state transition based on it (Batch 7 will).
    """

    building = serializers.PrimaryKeyRelatedField(
        queryset=Building.objects.filter(is_active=True)
    )
    customer = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.filter(is_active=True)
    )
    line_items = ExtraWorkRequestItemSerializer(many=True)

    class Meta:
        model = ExtraWorkRequest
        fields = [
            "id",
            "building",
            "customer",
            "title",
            "description",
            "category",
            "category_other_text",
            "urgency",
            "preferred_date",
            "line_items",
        ]
        read_only_fields = ["id"]

    def validate_line_items(self, value):
        # Empty cart -> reject. The Batch 6 contract requires at
        # least one line item; no implicit single-line fallback.
        if not value:
            raise serializers.ValidationError(
                "At least one line item is required."
            )

        # Defense in depth: a duplicate service entry in the same
        # cart is ambiguous (which requested_date / quantity wins?)
        # and rejected at the serializer layer. Same-service-twice-
        # with-different-dates is a future feature.
        seen_service_ids = set()
        for line in value:
            service = line.get("service")
            sid = service.pk if service is not None else None
            if sid is not None and sid in seen_service_ids:
                raise serializers.ValidationError(
                    "Duplicate service in cart: each service may "
                    "appear only once per submission."
                )
            seen_service_ids.add(sid)

        return value

    def validate(self, attrs):
        request = self.context["request"]
        user = request.user

        building = attrs["building"]
        customer = attrs["customer"]

        # Single-company invariant: the customer's company is the
        # only valid `company` for this Extra Work request, and the
        # building must belong to it.
        if customer.company_id != building.company_id:
            raise serializers.ValidationError(
                "Building and customer must belong to the same company."
            )

        # Customer must be linked to the building.
        if not CustomerBuildingMembership.objects.filter(
            customer=customer, building=building
        ).exists():
            raise serializers.ValidationError(
                "Customer is not linked to the selected building."
            )

        if attrs.get("category") == ExtraWorkCategory.OTHER and not attrs.get(
            "category_other_text", ""
        ).strip():
            raise serializers.ValidationError(
                {
                    "category_other_text": (
                        "Required when category is OTHER."
                    )
                }
            )

        # Customer-side permission resolution.
        if user.role == UserRole.CUSTOMER_USER:
            if not user_can(
                user,
                customer.id,
                building.id,
                "customer.extra_work.create",
            ):
                raise serializers.ValidationError(
                    "You do not have permission to create Extra Work "
                    "for this customer/building."
                )
        elif user.role in {
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        }:
            # Provider operators may create on behalf of the
            # customer. Scope check: SUPER_ADMIN is global;
            # COMPANY_ADMIN must be in the building's company;
            # BUILDING_MANAGER must be assigned to the building.
            from accounts.permissions_v2 import user_has_osius_permission

            if user.role != UserRole.SUPER_ADMIN and not user_has_osius_permission(
                user,
                "osius.ticket.view_building",
                building_id=building.id,
            ):
                raise serializers.ValidationError(
                    "You do not have provider-side scope to create "
                    "Extra Work in this building."
                )
        else:
            raise serializers.ValidationError(
                "This role cannot create Extra Work."
            )

        return attrs

    def create(self, validated_data):
        from django.db import transaction

        line_items_data = validated_data.pop("line_items", [])
        validated_data["company"] = validated_data["customer"].company
        validated_data["created_by"] = self.context["request"].user
        validated_data["status"] = ExtraWorkStatus.REQUESTED

        # Sprint 28 Batch 6 — parent + line items + routing decision
        # all land inside a single transaction so a half-created cart
        # (parent saved, no lines) is never observable.
        with transaction.atomic():
            request = super().create(validated_data)

            customer = request.customer
            all_lines_have_contract = True
            for line in line_items_data:
                service = line["service"]
                # Denormalise unit_type at create time — see model
                # docstring for the "pin the historical pricing
                # semantics" rationale.
                ExtraWorkRequestItem.objects.create(
                    extra_work_request=request,
                    service=service,
                    quantity=line["quantity"],
                    unit_type=service.unit_type,
                    requested_date=line["requested_date"],
                    customer_note=line.get("customer_note", ""),
                )
                # Per master plan §5 rule #9 + 2026-05-15 decision
                # log: resolver-returns-None ⇒ proposal; only an
                # active CustomerServicePrice row triggers the
                # instant-ticket path. Service.default_unit_price
                # does NOT count.
                price_row = resolve_price(
                    service,
                    customer,
                    on=line["requested_date"],
                )
                if price_row is None:
                    all_lines_have_contract = False

            request.routing_decision = (
                ExtraWorkRoutingDecision.INSTANT
                if all_lines_have_contract
                else ExtraWorkRoutingDecision.PROPOSAL
            )
            request.save(update_fields=["routing_decision", "updated_at"])

            # Sprint 28 Batch 7 — instant-route auto-spawn. When every
            # cart line resolved to a customer-specific contract price
            # (routing_decision="INSTANT"), the customer's submission
            # IS the approval: no proposal phase, spawn operational
            # tickets and advance the parent to CUSTOMER_APPROVED. The
            # spawn runs INSIDE this transaction.atomic() so a partial
            # failure (e.g. a contract row deactivated mid-flight) rolls
            # the parent + line-items + tickets back together.
            if request.routing_decision == ExtraWorkRoutingDecision.INSTANT:
                # Imported lazily to avoid circular import:
                # `instant_tickets.py` imports from this app's models +
                # state_machine, and a top-level import would create a
                # cycle through `serializers.py`.
                from .instant_tickets import spawn_tickets_for_request

                spawn_tickets_for_request(
                    request, actor=self.context["request"].user
                )

        return request


# ---------------------------------------------------------------------------
# Status history
# ---------------------------------------------------------------------------
class ExtraWorkStatusHistorySerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    old_status = serializers.CharField(read_only=True)
    new_status = serializers.CharField(read_only=True)
    changed_by_email = serializers.SerializerMethodField()
    note = serializers.CharField(read_only=True)
    is_override = serializers.BooleanField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    def get_changed_by_email(self, obj):
        return obj.changed_by.email if obj.changed_by else None


# ---------------------------------------------------------------------------
# Transition payload
# ---------------------------------------------------------------------------
class ExtraWorkTransitionSerializer(serializers.Serializer):
    to_status = serializers.ChoiceField(choices=ExtraWorkStatus.choices)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    is_override = serializers.BooleanField(default=False)
    override_reason = serializers.CharField(
        required=False, allow_blank=True, default=""
    )


# ---------------------------------------------------------------------------
# Sprint 28 Batch 8 — proposal serializers
# ---------------------------------------------------------------------------
class ProposalLineAdminSerializer(serializers.ModelSerializer):
    """
    Full provider-side proposal-line serializer. Carries both
    `customer_explanation` (customer-visible) and `internal_note`
    (provider-only). Used for write paths and admin reads.
    """

    service_name = serializers.CharField(
        source="service.name", read_only=True, default=None
    )

    class Meta:
        model = ProposalLine
        fields = [
            "id",
            "proposal",
            "service",
            "service_name",
            "description",
            "quantity",
            "unit_type",
            "unit_price",
            "vat_pct",
            "customer_explanation",
            "internal_note",
            "is_approved_for_spawn",
            "line_subtotal",
            "line_vat",
            "line_total",
            "created_at",
            "updated_at",
        ]
        # `proposal` is supplied by the view via `serializer.save(
        # proposal=...)` on the line-create endpoint OR populated by
        # the parent `ProposalCreateSerializer.create()` in the
        # nested-write path. Clients never POST it on the wire.
        read_only_fields = [
            "id",
            "proposal",
            "service_name",
            "line_subtotal",
            "line_vat",
            "line_total",
            "created_at",
            "updated_at",
        ]

    def validate_quantity(self, value):
        if value <= Decimal("0"):
            raise serializers.ValidationError(
                "Quantity must be greater than zero."
            )
        return value

    def validate_service(self, value):
        if value is None:
            return value
        if not value.is_active:
            raise serializers.ValidationError(
                "Cannot reference an inactive service."
            )
        return value

    def validate(self, attrs):
        # Ad-hoc lines must carry a description. When this serializer
        # is used in PATCH mode, fall back to the instance's existing
        # service/description so a partial edit doesn't trip on
        # unrelated fields.
        instance = getattr(self, "instance", None)
        service = attrs.get("service", getattr(instance, "service", None))
        description = attrs.get(
            "description", getattr(instance, "description", "")
        )
        if service is None and not (description or "").strip():
            raise serializers.ValidationError(
                {"description": "Required when service is not set."}
            )
        return attrs


class ProposalLineCustomerSerializer(serializers.ModelSerializer):
    """
    Customer-facing proposal-line serializer — DROPS `internal_note`.
    Used for any read path where the requesting user is a
    CUSTOMER_USER.
    """

    service_name = serializers.CharField(
        source="service.name", read_only=True, default=None
    )

    class Meta:
        model = ProposalLine
        fields = [
            "id",
            "service",
            "service_name",
            "description",
            "quantity",
            "unit_type",
            "unit_price",
            "vat_pct",
            "customer_explanation",
            "line_subtotal",
            "line_vat",
            "line_total",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ProposalCreateSerializer(serializers.ModelSerializer):
    """
    Write serializer for `POST /api/extra-work/<id>/proposals/`.

    Accepts a nested `lines` array (admin shape — provider-side
    create). The parent EW is supplied by the URL kwarg, not the
    payload; the view passes it via `serializer.save(extra_work_
    request=...)`.

    Parent-EW status guard: rejects when the parent is not in
    REQUESTED or UNDER_REVIEW. Also rejects when an open proposal
    (DRAFT or SENT) already exists — the partial UniqueConstraint
    enforces the same invariant at the DB level, but pre-checking
    here gives a clean ValidationError instead of an IntegrityError.
    """

    lines = ProposalLineAdminSerializer(many=True)

    class Meta:
        model = Proposal
        fields = ["id", "lines"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        extra_work_request: ExtraWorkRequest = self.context.get(
            "extra_work_request"
        )
        if extra_work_request is None:
            raise serializers.ValidationError(
                "extra_work_request missing from context."
            )
        # Parent EW must be in a state that accepts a new proposal.
        if extra_work_request.status not in {
            ExtraWorkStatus.REQUESTED,
            ExtraWorkStatus.UNDER_REVIEW,
        }:
            raise serializers.ValidationError(
                {
                    "detail": (
                        "Cannot create a proposal: parent Extra Work "
                        f"request is in status '{extra_work_request.status}'."
                    ),
                    "code": "proposal_create_invalid_parent_status",
                }
            )
        # One open proposal at a time (DRAFT or SENT). 1:N over
        # history is allowed; parallel open drafts are not.
        if Proposal.objects.filter(
            extra_work_request=extra_work_request,
            status__in=[ProposalStatus.DRAFT, ProposalStatus.SENT],
        ).exists():
            raise serializers.ValidationError(
                {
                    "detail": (
                        "An open proposal already exists for this "
                        "Extra Work request."
                    ),
                    "code": "proposal_open_already_exists",
                }
            )
        return attrs

    def create(self, validated_data):
        from django.db import transaction

        lines_data = validated_data.pop("lines", [])
        extra_work_request: ExtraWorkRequest = self.context[
            "extra_work_request"
        ]
        actor = self.context["request"].user
        with transaction.atomic():
            proposal = Proposal.objects.create(
                extra_work_request=extra_work_request,
                status=ProposalStatus.DRAFT,
                created_by=actor,
            )
            for line in lines_data:
                ProposalLine.objects.create(
                    proposal=proposal,
                    service=line.get("service"),
                    description=line.get("description", ""),
                    quantity=line["quantity"],
                    unit_type=line["unit_type"],
                    unit_price=line["unit_price"],
                    vat_pct=line.get("vat_pct", Decimal("21.00")),
                    customer_explanation=line.get("customer_explanation", ""),
                    internal_note=line.get("internal_note", ""),
                    is_approved_for_spawn=line.get(
                        "is_approved_for_spawn", True
                    ),
                )
            proposal.recompute_totals()
            # Refresh from DB so the totals computed by recompute_totals
            # are reflected on the instance returned to the caller.
            proposal.refresh_from_db()
            ProposalTimelineEvent.objects.create(
                proposal=proposal,
                event_type=ProposalTimelineEventType.CREATED,
                actor=actor,
                customer_visible=True,
                metadata={},
            )
        return proposal


class ProposalListSerializer(serializers.ModelSerializer):
    """Lean shape for `GET /api/extra-work/<id>/proposals/`."""

    class Meta:
        model = Proposal
        fields = [
            "id",
            "extra_work_request",
            "status",
            "subtotal_amount",
            "vat_amount",
            "total_amount",
            "sent_at",
            "customer_decided_at",
            "created_at",
        ]
        read_only_fields = fields


class ProposalDetailSerializer(serializers.ModelSerializer):
    """
    Role-aware detail serializer. Provider operators see every
    field. CUSTOMER_USER never sees `override_by`, `override_reason`,
    `override_at`; per-line `internal_note` is stripped via the
    customer line serializer.
    """

    lines = serializers.SerializerMethodField()
    allowed_next_statuses = serializers.SerializerMethodField()
    created_by_email = serializers.CharField(
        source="created_by.email", read_only=True
    )

    class Meta:
        model = Proposal
        fields = [
            "id",
            "extra_work_request",
            "status",
            "lines",
            "subtotal_amount",
            "vat_amount",
            "total_amount",
            "sent_at",
            "customer_decided_at",
            "override_by",
            "override_reason",
            "override_at",
            "created_by",
            "created_by_email",
            "created_at",
            "updated_at",
            "allowed_next_statuses",
        ]
        read_only_fields = fields

    _PROVIDER_ONLY_FIELDS = (
        "override_by",
        "override_reason",
        "override_at",
    )

    def get_lines(self, obj):
        user = (
            self.context.get("request").user
            if self.context.get("request")
            else None
        )
        qs = obj.lines.all().select_related("service")
        if _is_customer(user):
            return ProposalLineCustomerSerializer(qs, many=True).data
        return ProposalLineAdminSerializer(qs, many=True).data

    def get_allowed_next_statuses(self, obj):
        user = (
            self.context.get("request").user
            if self.context.get("request")
            else None
        )
        if user is None or not user.is_authenticated:
            return []
        return list(allowed_next_proposal_statuses(user, obj))

    def to_representation(self, instance):
        data = super().to_representation(instance)
        user = (
            self.context.get("request").user
            if self.context.get("request")
            else None
        )
        if _is_customer(user):
            for field in self._PROVIDER_ONLY_FIELDS:
                data.pop(field, None)
        return data


class ProposalTransitionSerializer(serializers.Serializer):
    """Mirror `ExtraWorkTransitionSerializer` for proposals."""

    to_status = serializers.ChoiceField(choices=ProposalStatus.choices)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    is_override = serializers.BooleanField(default=False)
    override_reason = serializers.CharField(
        required=False, allow_blank=True, default=""
    )


class ProposalStatusHistorySerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    old_status = serializers.CharField(read_only=True)
    new_status = serializers.CharField(read_only=True)
    changed_by_email = serializers.SerializerMethodField()
    note = serializers.CharField(read_only=True)
    is_override = serializers.BooleanField(read_only=True)
    override_reason = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    def get_changed_by_email(self, obj):
        return obj.changed_by.email if obj.changed_by else None


class ProposalTimelineEventAdminSerializer(serializers.ModelSerializer):
    """Provider-side timeline serializer — includes `metadata`."""

    actor_email = serializers.SerializerMethodField()

    class Meta:
        model = ProposalTimelineEvent
        fields = [
            "id",
            "proposal",
            "event_type",
            "actor",
            "actor_email",
            "customer_visible",
            "metadata",
            "created_at",
        ]
        read_only_fields = fields

    def get_actor_email(self, obj):
        return obj.actor.email if obj.actor else None


class ProposalTimelineEventCustomerSerializer(serializers.ModelSerializer):
    """Customer-facing timeline serializer — STRIPS `metadata`
    entirely. Provider-only context (override reasons etc.) cannot
    leak through this surface."""

    actor_email = serializers.SerializerMethodField()

    class Meta:
        model = ProposalTimelineEvent
        fields = [
            "id",
            "event_type",
            "actor_email",
            "customer_visible",
            "created_at",
        ]
        read_only_fields = fields

    def get_actor_email(self, obj):
        return obj.actor.email if obj.actor else None
