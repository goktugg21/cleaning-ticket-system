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
    # Per-current-user actions block. Lets BM / CUSTOMER_USER (who
    # cannot self-introspect via the admin-only
    # `/api/users/<id>/effective-permissions/` endpoint) learn what they
    # can do on THIS specific Extra Work request. Note: STAFF never
    # reaches this serializer (the scoping helper returns `.none()` for
    # STAFF) so the action booleans intentionally do not branch on the
    # STAFF role; the resolver-side helpers return False for STAFF
    # anyway, but we document the precondition explicitly.
    actions = serializers.SerializerMethodField()

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
            "actions",
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

    def _resolve_allowed_next_statuses(self, obj):
        """Cached single computation shared by the top-level
        `allowed_next_statuses` field and the `actions` block. Keyed by
        the EW id on the serializer instance — both callers fire on the
        same render and must not drift.
        """
        cache = getattr(self, "_allowed_next_cache", None)
        if cache is not None and cache[0] == obj.id:
            return cache[1]
        user = (
            self.context.get("request").user
            if self.context.get("request")
            else None
        )
        if user is None or not user.is_authenticated:
            result: list = []
        else:
            result = list(allowed_next_statuses(user, obj))
        self._allowed_next_cache = (obj.id, result)
        return result

    def get_allowed_next_statuses(self, obj):
        return self._resolve_allowed_next_statuses(obj)

    def get_actions(self, obj):
        """Per-current-user, per-EW capability block.

        Booleans are computed against `request.user` and THIS EW's
        (customer, building). Mirrors the resolver shape used by
        `accounts.effective_actions.compute_effective_actions` so the
        per-record answer agrees with the admin endpoint when SA/CA
        call both — but is also reachable to BM / CUSTOMER_USER who
        cannot call the admin endpoint at all.

        STAFF never reaches an EW detail endpoint
        (`extra_work.scoping.scope_extra_work_for` returns `.none()`).
        The action booleans intentionally do not branch on the STAFF
        role; the underlying resolvers return False for STAFF and the
        endpoint gate makes the question moot.
        """
        from accounts.effective_actions import (
            _any_customer_approve_key,
            _customer_can,
            _target_provider_in_scope,
        )

        from .models import ExtraWorkStatus

        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None

        if user is None or not user.is_authenticated:
            return {
                "allowed_next_statuses": [],
                "can_prepare_extra_work_proposal": False,
                "can_override_customer_decision": False,
                "can_view_pricing": False,
                "can_view_proposal_pdf": False,
                "can_approve": False,
                "can_reject": False,
            }

        allowed = self._resolve_allowed_next_statuses(obj)
        role = getattr(user, "role", None)
        customer = obj.customer
        building = obj.building
        in_provider_scope = _target_provider_in_scope(user, customer, building)

        is_super = role == UserRole.SUPER_ADMIN
        is_ca_in = role == UserRole.COMPANY_ADMIN and in_provider_scope
        is_bm_in = role == UserRole.BUILDING_MANAGER and in_provider_scope
        is_customer = role == UserRole.CUSTOMER_USER

        # Proposal preparation — provider-side. SA / CA in scope always;
        # BM in assigned building is gated by the B6 revocable key.
        # STAFF / CUSTOMER_USER always False.
        if is_super or is_ca_in:
            can_prepare_extra_work_proposal = True
        elif is_bm_in:
            from accounts.permissions_v2 import user_has_osius_permission
            can_prepare_extra_work_proposal = user_has_osius_permission(
                user,
                "osius.building_manager.prepare_extra_work_proposal",
                building_id=building.id,
            )
        else:
            can_prepare_extra_work_proposal = False

        # Customer-decision override — same shape as ticket analog.
        # Compute authority first, then tighten so the answer reflects
        # CURRENT record state, not just authority — the override is
        # only meaningful at the customer-decision step (PRICING_PROPOSED).
        if is_super or is_ca_in:
            has_override_authority = True
        elif is_bm_in:
            from accounts.permissions_v2 import user_has_osius_permission
            has_override_authority = user_has_osius_permission(
                user,
                "osius.building_manager.override_customer_decision",
                building_id=building.id,
            )
        else:
            has_override_authority = False
        can_override_customer_decision = (
            has_override_authority
            and obj.status == ExtraWorkStatus.PRICING_PROPOSED
        )

        # Pricing visibility. Provider operators in scope see prices
        # regardless of the B6 prep override (B6 only revokes the
        # ability to SEND a proposal, not to view prices). Customer
        # sees pricing iff they hold any extra_work approve_* key
        # (`_any_customer_approve_key` mirrors the resolver in
        # effective_actions.compute_effective_actions).
        if is_super or is_ca_in or is_bm_in:
            can_view_pricing = True
        elif is_customer:
            can_view_pricing = _any_customer_approve_key(
                user, customer, building, "extra_work"
            )
        else:
            can_view_pricing = False
        # PDF access mirrors pricing visibility — viewing pricing
        # implies the right to render the printable proposal. Kept as
        # a separate boolean in case backend later splits them.
        can_view_proposal_pdf = can_view_pricing

        # Approve / Reject depend on the EW's status. The EW
        # customer-decision phase is `PRICING_PROPOSED`. Customer with
        # any approve_* key may decide; a provider with
        # `can_override_customer_decision` may also drive
        # (apply_transition coerces is_override + requires reason).
        # When the EW is NOT in PRICING_PROPOSED, every actor gets
        # False — locking the action booleans to the live state machine.
        in_decision_phase = obj.status == ExtraWorkStatus.PRICING_PROPOSED
        if not in_decision_phase:
            can_approve = False
            can_reject = False
        elif is_customer:
            customer_can_decide = (
                _any_customer_approve_key(user, customer, building, "extra_work")
                or (
                    obj.created_by_id == user.id
                    and _customer_can(
                        user, customer, building, "customer.extra_work.approve_own"
                    )
                )
            )
            can_approve = customer_can_decide
            can_reject = customer_can_decide
        else:
            can_approve = can_override_customer_decision
            can_reject = can_override_customer_decision

        return {
            "allowed_next_statuses": list(allowed),
            "can_prepare_extra_work_proposal": can_prepare_extra_work_proposal,
            "can_override_customer_decision": can_override_customer_decision,
            "can_view_pricing": can_view_pricing,
            "can_view_proposal_pdf": can_view_proposal_pdf,
            "can_approve": can_approve,
            "can_reject": can_reject,
        }

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
    note = serializers.SerializerMethodField()
    is_override = serializers.BooleanField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    def get_changed_by_email(self, obj):
        return obj.changed_by.email if obj.changed_by else None

    def get_note(self, obj):
        # B1 (system-business-logic-and-workflows.md §7 + §13) — when a
        # CUSTOMER_USER reads the timeline, redact provider-authored
        # notes. The free-text `note` field is shared by provider
        # operators (who may write internal coordination, internal cost
        # context, or any provider-side commentary into a transition
        # note) and customers (their own reject reason). Customers must
        # see only customer-authored or system-authored notes.
        request = self.context.get("request") if self.context else None
        viewer = getattr(request, "user", None) if request else None
        if (
            viewer is not None
            and getattr(viewer, "role", None) == UserRole.CUSTOMER_USER
        ):
            author = obj.changed_by
            if author is not None and getattr(author, "role", None) != UserRole.CUSTOMER_USER:
                return ""
        return obj.note or ""


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
    # Sprint 28 Batch 15.4 — customer-supplied reject reason. Required
    # (non-blank after .strip()) when a CUSTOMER_USER drives a
    # PRICING_PROPOSED -> CUSTOMER_REJECTED transition WITHOUT
    # is_override (the provider override path already requires its own
    # `override_reason`). Threaded into the status-history `note` by
    # the view layer so it surfaces on the existing timeline UI
    # without a new persistence column.
    customer_reject_reason = serializers.CharField(
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

    B2 (system-business-logic-and-workflows.md §7.0) — Extra Work is
    always a cart of line items. When the caller omits the `lines`
    array (or sends `lines=[]`), the serializer auto-seeds one
    `ProposalLine` per `ExtraWorkRequestItem` on the parent EW. For
    each seeded line, the contract resolver
    (`extra_work.pricing.resolve_price`) is consulted with the cart
    item's own `requested_date`; when a contract row is returned,
    `unit_price` and `vat_pct` are pre-filled from it. For cart
    lines without a contract row, both fields default to `0.00`
    and the operator is expected to fill them in before SEND. No
    metadata marker is written on the line (per the B2 spec —
    `customer_explanation` is customer-visible business text, not
    an internal flag; "is this line contract-priced" is derived
    by re-calling `resolve_price` at validation / read time).

    When the caller sends explicit `lines`, the original behaviour
    is preserved: the serializer creates exactly the rows the
    client described. SEND-time validation (see
    `proposal_state_machine.apply_proposal_transition`) is the
    safety net that catches a mismatch between proposal lines and
    cart items regardless of whether the lines were auto-seeded
    or hand-built.
    """

    # B2 — `lines` is no longer required on the wire. When omitted
    # or empty, the serializer reads the parent EW's cart and seeds
    # one ProposalLine per ExtraWorkRequestItem. See the create()
    # method below.
    lines = ProposalLineAdminSerializer(many=True, required=False)

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

            # B2 — auto-seed from cart items when the caller omits or
            # sends an empty `lines` array. The cart drives the
            # proposal shape; the operator only edits prices /
            # explanations afterwards.
            if not lines_data:
                customer = extra_work_request.customer
                cart_items = list(
                    extra_work_request.line_items.all().order_by("id")
                )
                for item in cart_items:
                    contract = resolve_price(
                        item.service,
                        customer,
                        on=item.requested_date,
                    )
                    if contract is not None:
                        unit_price = contract.unit_price
                        vat_pct = contract.vat_pct
                    else:
                        # Custom line — operator must set the price
                        # before SEND. The SEND-time gate refuses
                        # unit_price=0 without a customer_explanation.
                        unit_price = Decimal("0.00")
                        vat_pct = Decimal("21.00")
                    ProposalLine.objects.create(
                        proposal=proposal,
                        service=item.service,
                        description="",
                        quantity=item.quantity,
                        unit_type=item.unit_type,
                        unit_price=unit_price,
                        vat_pct=vat_pct,
                        customer_explanation="",
                        internal_note="",
                        is_approved_for_spawn=True,
                    )
            else:
                for line in lines_data:
                    ProposalLine.objects.create(
                        proposal=proposal,
                        service=line.get("service"),
                        description=line.get("description", ""),
                        quantity=line["quantity"],
                        unit_type=line["unit_type"],
                        unit_price=line["unit_price"],
                        vat_pct=line.get("vat_pct", Decimal("21.00")),
                        customer_explanation=line.get(
                            "customer_explanation", ""
                        ),
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
    # Per-current-user actions block. Surfaces buttons the viewer is
    # actually allowed to click on THIS proposal in its current state.
    # Critical product-rule: BM with the prep key revoked must still
    # see `can_view_proposal_pricing=True` + `can_view_proposal_pdf=True`
    # — the revocation only removes the ability to MUTATE / SEND, not
    # to read pricing.
    actions = serializers.SerializerMethodField()
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
            "actions",
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

    def _resolve_allowed_next_statuses(self, obj):
        """Cached single computation shared by the top-level
        `allowed_next_statuses` field and the `actions` block."""
        cache = getattr(self, "_allowed_next_cache", None)
        if cache is not None and cache[0] == obj.id:
            return cache[1]
        user = (
            self.context.get("request").user
            if self.context.get("request")
            else None
        )
        if user is None or not user.is_authenticated:
            result: list = []
        else:
            result = list(allowed_next_proposal_statuses(user, obj))
        self._allowed_next_cache = (obj.id, result)
        return result

    def get_allowed_next_statuses(self, obj):
        return self._resolve_allowed_next_statuses(obj)

    def get_actions(self, obj):
        """Per-current-user, per-proposal capability block.

        Rules:
          * Pricing + PDF visibility = "anyone who could meaningfully
            consume the prices". Provider operators in scope always;
            BM in scope NEVER loses pricing access even when the prep
            key is revoked (product rule — only mutation is locked).
            Customer iff they hold any extra_work approve_* key.
          * Mutating actions (edit_lines / send / cancel / direct_publish)
            require provider operator in scope, and for BM additionally
            the prep key. They also require the proposal to be in the
            right status (DRAFT for edit/send/direct_publish; DRAFT or
            SENT for cancel).
          * Approve / Reject only when proposal is SENT and the actor
            is either a customer with approve_* OR a provider with
            override authority.
        """
        from accounts.effective_actions import (
            _any_customer_approve_key,
            _target_provider_in_scope,
        )
        from accounts.permissions_v2 import user_has_osius_permission

        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None

        if user is None or not user.is_authenticated:
            return {
                "allowed_next_statuses": [],
                "can_view_proposal_pricing": False,
                "can_view_proposal_pdf": False,
                "can_edit_lines": False,
                "can_send": False,
                "can_cancel": False,
                "can_approve": False,
                "can_reject": False,
                "can_direct_publish": False,
            }

        allowed = self._resolve_allowed_next_statuses(obj)
        role = getattr(user, "role", None)
        extra_work = obj.extra_work_request
        customer = extra_work.customer
        building = extra_work.building
        in_provider_scope = _target_provider_in_scope(user, customer, building)

        is_super = role == UserRole.SUPER_ADMIN
        is_ca_in = role == UserRole.COMPANY_ADMIN and in_provider_scope
        is_bm_in = role == UserRole.BUILDING_MANAGER and in_provider_scope
        is_customer = role == UserRole.CUSTOMER_USER

        # Pricing visibility — provider operators in scope ALWAYS see
        # prices; the BM prep-key revocation does NOT remove pricing
        # visibility (only the ability to mutate / SEND). This is the
        # critical product-rule the brief flags. Customer sees pricing
        # iff they could meaningfully decide on it.
        if is_super or is_ca_in or is_bm_in:
            can_view_proposal_pricing = True
        elif is_customer:
            can_view_proposal_pricing = _any_customer_approve_key(
                user, customer, building, "extra_work"
            )
        else:
            can_view_proposal_pricing = False
        can_view_proposal_pdf = can_view_proposal_pricing

        # BM prep key — gates every mutation provider-side. SA / CA
        # bypass (the key defaults True for them at the resolver).
        if is_bm_in:
            bm_has_prep = user_has_osius_permission(
                user,
                "osius.building_manager.prepare_extra_work_proposal",
                building_id=building.id,
            )
            bm_has_override = user_has_osius_permission(
                user,
                "osius.building_manager.override_customer_decision",
                building_id=building.id,
            )
        else:
            bm_has_prep = False
            bm_has_override = False

        provider_can_mutate = is_super or is_ca_in or (is_bm_in and bm_has_prep)

        # Lines may only be edited while DRAFT (mirrors the
        # `proposal_not_draft` view-level guard in views_proposals.py).
        can_edit_lines = bool(
            provider_can_mutate and obj.status == ProposalStatus.DRAFT
        )

        # SEND requires DRAFT + parent EW in UNDER_REVIEW + the cart-
        # coverage / contract-price validations (the state-machine
        # gate). We surface True when the *role gate* would pass — the
        # cart validations can still fail at POST time and the
        # frontend should display the error from the transition
        # endpoint. The parent-status guard is cheap and accurate, so
        # we DO include it here so the frontend doesn't render a Send
        # button against a REQUESTED parent (which would always 400).
        can_send = bool(
            provider_can_mutate
            and obj.status == ProposalStatus.DRAFT
            and extra_work.status == ExtraWorkStatus.UNDER_REVIEW
        )

        # Cancel is allowed from DRAFT or SENT. SENT cancellation is
        # coerced to is_override + requires reason (mirrors the
        # `provider_driven_sent_cancel` block in
        # apply_proposal_transition); the action boolean only reports
        # the role gate, not the reason requirement.
        can_cancel = bool(
            provider_can_mutate
            and obj.status in {ProposalStatus.DRAFT, ProposalStatus.SENT}
        )

        # Approve / Reject — SENT proposal only. Customer with
        # approve_* OR provider with override authority.
        in_sent = obj.status == ProposalStatus.SENT
        if not in_sent:
            can_approve = False
            can_reject = False
        elif is_customer:
            # Mirrors `_user_can_drive_proposal_transition`'s customer
            # branch: approve_location at the pair, OR (creator AND
            # approve_own at the pair).
            from customers.permissions import user_can
            customer_can_decide = user_can(
                user, customer.id, building.id, "customer.extra_work.approve_location"
            ) or (
                extra_work.created_by_id == user.id
                and user_can(
                    user, customer.id, building.id, "customer.extra_work.approve_own"
                )
            )
            can_approve = customer_can_decide
            can_reject = customer_can_decide
        else:
            # Provider override path. SA / CA always; BM if both prep
            # AND override keys granted (the proposal state machine
            # rejects with `bm_override_disabled` otherwise).
            if is_super or is_ca_in:
                provider_can_decide = True
            elif is_bm_in:
                provider_can_decide = bm_has_prep and bm_has_override
            else:
                provider_can_decide = False
            can_approve = provider_can_decide
            can_reject = provider_can_decide

        # Direct-publish: tightened so the answer reflects CURRENT
        # record state, not just authority — derive from the already-
        # computed `can_send` so the two cannot drift (direct-publish
        # internally does DRAFT->SENT first, so every send precondition
        # must hold). SA / CA in scope: True iff can_send. BM in scope:
        # True iff can_send AND the override key is granted (direct-
        # publish then does the SENT->CUSTOMER_APPROVED override leg).
        # Customer / STAFF: always False.
        if is_super or is_ca_in:
            can_direct_publish = can_send
        elif is_bm_in:
            can_direct_publish = can_send and bm_has_override
        else:
            can_direct_publish = False

        return {
            "allowed_next_statuses": list(allowed),
            "can_view_proposal_pricing": can_view_proposal_pricing,
            "can_view_proposal_pdf": can_view_proposal_pdf,
            "can_edit_lines": can_edit_lines,
            "can_send": can_send,
            "can_cancel": can_cancel,
            "can_approve": can_approve,
            "can_reject": can_reject,
            "can_direct_publish": can_direct_publish,
        }

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
    note = serializers.SerializerMethodField()
    is_override = serializers.BooleanField(read_only=True)
    override_reason = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(read_only=True)

    def get_changed_by_email(self, obj):
        return obj.changed_by.email if obj.changed_by else None

    def _viewer_is_customer(self):
        # B1 — shared helper for the note + override_reason redaction.
        request = self.context.get("request") if self.context else None
        viewer = getattr(request, "user", None) if request else None
        return (
            viewer is not None
            and getattr(viewer, "role", None) == UserRole.CUSTOMER_USER
        )

    def _author_is_provider(self, obj):
        author = obj.changed_by
        return author is not None and getattr(author, "role", None) != UserRole.CUSTOMER_USER

    def get_note(self, obj):
        # B1 (system-business-logic-and-workflows.md §7 + §13) — customer
        # readers see only customer-authored or system-authored notes.
        if self._viewer_is_customer() and self._author_is_provider(obj):
            return ""
        return obj.note or ""

    def get_override_reason(self, obj):
        # B1 — `override_reason` is provider-only context by definition.
        # Always redacted for customer readers, regardless of authorship.
        # (Provider-driven customer-decision overrides are the only
        # transitions that populate this field, so the row will always
        # have a provider author too — but we redact unconditionally to
        # make the contract obvious.)
        if self._viewer_is_customer():
            return ""
        return obj.override_reason or ""


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
