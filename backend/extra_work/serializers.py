"""
Sprint 26B — Extra Work serializers.

Customer-visible serializers strip provider-internal fields
(internal_cost_note, manager_note, override_*) so a CUSTOMER_USER
never sees provider workflow. The serializer chooses the right
shape based on `context["request"].user.role`.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from rest_framework import serializers

from accounts.models import UserRole
from accounts.permissions import is_customer_side
from buildings.models import Building
from companies.models import Company
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
    Department,
    WorkType,
)
from customers.permissions import access_has_permission, user_can

from .classification import (
    ACTOR_CUSTOMER_COMPANY_ADMIN,
    ACTOR_CUSTOMER_LOCATION_MANAGER,
    ACTOR_CUSTOMER_USER,
    ACTOR_PROVIDER,
    ACTOR_STAFF,
    IntentValidationError,
    classify_cart,
    classify_line,
    derive_default_intent,
    validate_intent_for_cart,
)
from .models import (
    CustomerCustomPrice,
    ExtraWorkBilledTo,
    ExtraWorkLinePriceSource,
    ExtraWorkPricingLineItem,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestIntent,
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
from .label_validation import (
    default_labels_for_customer,
    issued_invoice_locking_labels,
    validate_labels_for_customer,
)
from .pricing import resolve_price
from .proposal_state_machine import allowed_next_proposal_statuses
from .state_machine import allowed_next_statuses


logger = logging.getLogger(__name__)


# Sprint 176 §3 — one error code for "a customer tried to set a deadline",
# shared by the create serializer and the dates endpoint so the frontend has
# a single string to map to a localized message.
ERR_DEADLINE_PROVIDER_ONLY = "deadline_provider_only"


def _is_customer(user) -> bool:
    return user is not None and user.role == UserRole.CUSTOMER_USER


def derive_actor_kind(user, customer, building) -> str:
    """Sprint 2A — derive a coarse actor classification for intent
    validation. Single source of truth shared by the create
    serializer and the Sprint 5 preview endpoint. See
    `extra_work.classification` for the full taxonomy.

    Provider-side roles map to ACTOR_PROVIDER (intent rules treat
    Super Admin / Provider Admin / Building Manager the same; tenant/
    building scope is enforced separately in the calling serializer's
    `validate`). STAFF maps to ACTOR_STAFF.

    Customer-side: walk `CustomerUserBuildingAccess` for the actor on
    the target (customer, building) and lift the access_role into the
    matching actor kind. Missing/inactive access ⇒ baseline
    CUSTOMER_USER.
    """
    role = getattr(user, "role", None)
    if role == UserRole.STAFF:
        return ACTOR_STAFF
    if role in {
        UserRole.SUPER_ADMIN,
        UserRole.COMPANY_ADMIN,
        UserRole.BUILDING_MANAGER,
    }:
        return ACTOR_PROVIDER

    # SoT Addendum A.1 — a company-wide Customer Company Admin (the
    # membership `is_company_admin` flag) is classified as CCA across
    # ALL buildings, with no per-building access row required (the 0010
    # migration deletes the legacy per-building CCA rows).
    if CustomerUserMembership.objects.filter(
        user=user, customer=customer, is_company_admin=True
    ).exists():
        return ACTOR_CUSTOMER_COMPANY_ADMIN

    access = (
        CustomerUserBuildingAccess.objects.filter(
            membership__user=user,
            membership__customer=customer,
            building=building,
            is_active=True,
        )
        .only("access_role")
        .first()
    )
    if access is None:
        return ACTOR_CUSTOMER_USER
    if (
        access.access_role
        == CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
    ):
        return ACTOR_CUSTOMER_COMPANY_ADMIN
    if (
        access.access_role
        == CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER
    ):
        return ACTOR_CUSTOMER_LOCATION_MANAGER
    return ACTOR_CUSTOMER_USER


# ---------------------------------------------------------------------------
# Per-line pricing source (read-only fields exposed on every Extra Work
# line serializer so the frontend invoice renderer can render the
# "Source" column without re-deriving the contract/custom/needs-proposal
# label client-side).
#
# Stable enum string values surfaced as `price_source`:
#   * "CONTRACT"        — the line is anchored to an active
#                         `CustomerServicePrice` row for the (service,
#                         customer) pair. For PERSISTED proposal /
#                         pricing lines this means the line's snapshot
#                         (unit_price + vat_pct) currently matches the
#                         contract row's values; for CART lines (which
#                         have no own price snapshot yet) this means a
#                         contract row exists at the line's
#                         requested_date.
#   * "CUSTOM"          — the line's price was operator-typed and does
#                         NOT match an active contract row. For
#                         ad-hoc `ExtraWorkPricingLineItem` (no service
#                         FK) and ad-hoc ProposalLine (service=None)
#                         this is always the source.
#   * "NEEDS_PROPOSAL"  — cart line with no contract row resolvable.
#                         Only emitted by `ExtraWorkRequestItem` rows
#                         whose parent EW has not yet been priced.
#
# Snapshot vs live re-resolve rule:
#   * Cart lines (`ExtraWorkRequestItem`) have no persisted unit price
#     of their own; the live `resolve_price()` call IS the truth at
#     read time. The moment the line is folded into a Proposal, the
#     operator-typed Proposal line's unit_price becomes the snapshot.
#   * Persisted proposal / pricing lines carry their own unit_price +
#     vat_pct values. The serializer NEVER mutates those historical
#     values; the `contract_*` fields mirror the line's persisted
#     snapshot when we label it CONTRACT, so a later edit to the
#     `CustomerServicePrice` row cannot retroactively rewrite the
#     amount in a saved response.
# ---------------------------------------------------------------------------


PRICE_SOURCE_CONTRACT = "CONTRACT"
PRICE_SOURCE_CUSTOM = "CUSTOM"
PRICE_SOURCE_NEEDS_PROPOSAL = "NEEDS_PROPOSAL"


def _decimal_str(value: Decimal | None) -> str | None:
    """Render a Decimal like DRF's DecimalField does (str, 2dp)."""
    if value is None:
        return None
    return f"{value:.2f}"


# ---------------------------------------------------------------------------
# Pricing line item
# ---------------------------------------------------------------------------
class ExtraWorkPricingLineItemSerializer(serializers.ModelSerializer):
    """
    Provider-side serializer (full shape including internal_cost_note).
    For customer-side reads use ExtraWorkPricingLineItemCustomerSerializer.
    """

    # See module-level "Per-line pricing source" docblock for the
    # contract. `ExtraWorkPricingLineItem` rows are ALWAYS custom: they
    # have no `service` FK to anchor against and are operator-typed by
    # construction.
    price_source = serializers.SerializerMethodField()
    contract_unit_price = serializers.SerializerMethodField()
    contract_vat_pct = serializers.SerializerMethodField()

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
            "price_source",
            "contract_unit_price",
            "contract_vat_pct",
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
            "price_source",
            "contract_unit_price",
            "contract_vat_pct",
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

    def get_price_source(self, obj):
        return PRICE_SOURCE_CUSTOM

    def get_contract_unit_price(self, obj):
        return None

    def get_contract_vat_pct(self, obj):
        return None


class ExtraWorkPricingLineItemCustomerSerializer(serializers.ModelSerializer):
    """
    Customer-facing line item — DROPS `internal_cost_note`. Used in
    the nested representation on ExtraWorkRequestDetailSerializer
    when the requesting user is a CUSTOMER_USER.
    """

    # Mirror the admin serializer's price-source fields. The three
    # fields are customer-safe — they describe the same numbers the
    # customer already sees in `unit_price` / `vat_rate`.
    price_source = serializers.SerializerMethodField()
    contract_unit_price = serializers.SerializerMethodField()
    contract_vat_pct = serializers.SerializerMethodField()

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
            "price_source",
            "contract_unit_price",
            "contract_vat_pct",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_price_source(self, obj):
        return PRICE_SOURCE_CUSTOM

    def get_contract_unit_price(self, obj):
        return None

    def get_contract_vat_pct(self, obj):
        return None


# ---------------------------------------------------------------------------
# Sprint 28 Batch 6 — cart line item
# ---------------------------------------------------------------------------
def _validate_line_source_exclusivity(
    *, service, custom_price, custom_description
):
    """Sprint 137 item 6 — the cart line's "what is this line?" rule,
    shared by the create serializer and the preview serializer so the
    two can never drift.

    Sprint 2A made it `service` XOR `custom_description`. Item 6 adds a
    THIRD mutually-exclusive way to describe a line: `custom_price`, a
    `CustomerCustomPrice` the operator already priced for this customer.
    Exactly one of the three must be present.

    Takes explicit values rather than the `attrs` dict because the two
    callers key the field differently: the model-bound cart serializer
    maps it onto `snapshot_customer_custom_price`, the preview
    serializer is model-free and keeps the wire name.

    The stable error code stays `line_requires_service_or_description`
    for both the none-supplied and the more-than-one-supplied case —
    existing clients key on it and it already covered both.
    """
    custom_description = (custom_description or "").strip()

    supplied = sum(
        1
        for present in (
            service is not None,
            custom_price is not None,
            bool(custom_description),
        )
        if present
    )
    if supplied == 0:
        raise serializers.ValidationError(
            {
                "non_field_errors": [
                    serializers.ErrorDetail(
                        "Line must reference a service, a custom price, "
                        "or supply a custom_description.",
                        code="line_requires_service_or_description",
                    )
                ]
            }
        )
    if supplied > 1:
        raise serializers.ValidationError(
            {
                "non_field_errors": [
                    serializers.ErrorDetail(
                        "Line must carry exactly one of service, "
                        "custom_price or custom_description.",
                        code="line_requires_service_or_description",
                    )
                ]
            }
        )


def _validate_custom_price_orderable(custom_price, customer, requested_date):
    """Sprint 137 item 6 — a `CustomerCustomPrice` may only be ordered
    by the customer it belongs to, while it is active, and inside its
    validity window.

    The tenant check is the load-bearing one (RBAC H-1/H-2): the field's
    queryset spans every customer's custom prices, so without this a
    caller could name another tenant's price row by id and both leak its
    amount into the preview and pin it onto their own cart line. Mirrors
    the existing cross-company `service` guard on the same cart.

    The active + in-window checks mirror `resolve_price`'s semantics for
    contract rows, so an archived or expired custom price cannot be
    ordered at its stale amount.
    """
    if custom_price.customer_id != customer.id:
        raise serializers.ValidationError(
            {
                "line_items": [
                    serializers.ErrorDetail(
                        "Custom price does not belong to this customer.",
                        code="custom_price_foreign_customer",
                    )
                ]
            }
        )
    if not custom_price.is_active:
        raise serializers.ValidationError(
            {
                "line_items": [
                    serializers.ErrorDetail(
                        "Cannot order an archived custom price.",
                        code="custom_price_not_orderable",
                    )
                ]
            }
        )
    if custom_price.valid_from > requested_date or (
        custom_price.valid_to is not None
        and custom_price.valid_to < requested_date
    ):
        raise serializers.ValidationError(
            {
                "line_items": [
                    serializers.ErrorDetail(
                        "Custom price is not valid on the requested date.",
                        code="custom_price_not_orderable",
                    )
                ]
            }
        )


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

    Sprint 2A:
      * `service` is OPTIONAL on the wire. A line may instead carry
        a non-empty `custom_description` to express a free-text /
        ad-hoc cart line that has no catalog row. Exactly one of
        `service` or `custom_description` must be present; sending
        both — or neither — is a 400 with code
        `line_requires_service_or_description`.
      * Snapshot fields (`line_price_source`, `snapshot_*`) are
        read-only and surfaced so the frontend can render the
        per-line source without re-resolving client-side.

    Pre-Sprint-2A note: Batch 6 required `service` on the wire.
    Existing 341 tests submit catalog-linked lines; the relaxed
    rule keeps every catalog-linked submission working unchanged.
    """

    service = serializers.PrimaryKeyRelatedField(
        queryset=Service.objects.all(),
        required=False,
        allow_null=True,
        default=None,
    )
    service_name = serializers.CharField(
        source="service.name",
        read_only=True,
        default=None,
    )
    custom_description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=255,
    )
    # Sprint 137 item 6 — order a per-customer CustomerCustomPrice. The
    # queryset is unfiltered here (a nested line serializer has no
    # handle on the cart's customer); the parent serializer's validate()
    # enforces the tenant + orderability rules via
    # `_validate_custom_price_orderable`.
    custom_price = serializers.PrimaryKeyRelatedField(
        queryset=CustomerCustomPrice.objects.all(),
        source="snapshot_customer_custom_price",
        required=False,
        allow_null=True,
        default=None,
    )
    line_price_source = serializers.CharField(read_only=True)
    # Sprint 8B — actual hours worked (HOURS-unit lines). Read-only on
    # the cart-line read path; written only via the actual-hours
    # endpoint. Visible to the customer per SoT §5.12.
    actual_hours = serializers.DecimalField(
        read_only=True, max_digits=12, decimal_places=2, allow_null=True
    )
    snapshot_unit_price = serializers.DecimalField(
        read_only=True, max_digits=12, decimal_places=2
    )
    snapshot_vat_pct = serializers.DecimalField(
        read_only=True, max_digits=5, decimal_places=2
    )
    snapshot_service_name = serializers.CharField(read_only=True)
    snapshot_service_category_name = serializers.CharField(read_only=True)

    # See module-level "Per-line pricing source" docblock for the
    # contract. Cart lines have no persisted unit_price of their own
    # (they are pre-pricing rows), so the live `resolve_price()` call
    # IS the truth at read time. The moment the line is folded into a
    # Proposal, the operator-typed Proposal line's unit_price becomes
    # the snapshot and the live-resolve exception no longer applies.
    price_source = serializers.SerializerMethodField()
    contract_unit_price = serializers.SerializerMethodField()
    contract_vat_pct = serializers.SerializerMethodField()

    class Meta:
        model = ExtraWorkRequestItem
        fields = [
            "id",
            "service",
            "service_name",
            "custom_description",
            # Sprint 137 item 6 — writable on create, and surfaced on
            # read so the detail page can mark the line as ordered from
            # a custom price rather than typed free-hand.
            "custom_price",
            "quantity",
            "unit_type",
            "requested_date",
            "customer_note",
            "price_source",
            "contract_unit_price",
            "contract_vat_pct",
            # Sprint 8B — actual hours (read-only).
            "actual_hours",
            # Sprint 2A — snapshot surface (read-only).
            "line_price_source",
            "snapshot_unit_price",
            "snapshot_vat_pct",
            "snapshot_service_name",
            "snapshot_service_category_name",
        ]
        read_only_fields = [
            "id",
            "service_name",
            # `unit_type` is denormalised by the parent serializer at
            # create time from Service.unit_type (or set to OTHER for
            # ad-hoc lines) — clients must not supply it.
            "unit_type",
            "price_source",
            "contract_unit_price",
            "contract_vat_pct",
            "actual_hours",
            "line_price_source",
            "snapshot_unit_price",
            "snapshot_vat_pct",
            "snapshot_service_name",
            "snapshot_service_category_name",
        ]

    def validate_quantity(self, value):
        if value <= Decimal("0"):
            raise serializers.ValidationError(
                "Quantity must be greater than zero."
            )
        return value

    def validate_service(self, value):
        # Sprint 2A — service is OPTIONAL (ad-hoc lines have none).
        # Still reject inactive catalog rows when one IS supplied.
        if value is not None and not value.is_active:
            raise serializers.ValidationError(
                "Cannot order an inactive service."
            )
        return value

    def validate(self, attrs):
        # Sprint 2A + Sprint 137 item 6 — exactly one of `service`,
        # `custom_price` or `custom_description`. See
        # `_validate_line_source_exclusivity`.
        _validate_line_source_exclusivity(
            service=attrs.get("service"),
            custom_price=attrs.get("snapshot_customer_custom_price"),
            custom_description=attrs.get("custom_description"),
        )
        return attrs

    def _resolved_contract(self, obj):
        """Live-resolve the line's contract row at read time.

        Cart lines are pre-pricing — there is no snapshot to defend, so
        calling `resolve_price` on every render is the correct
        behaviour. Cached on the serializer instance per cart-line id
        so repeated `get_*` calls share one query per line per render.
        """
        if obj.service_id is None:
            # Legacy backfilled rows have no service FK. The Batch 6
            # migration backfilled exactly one row per legacy parent
            # and the project never spawns instant tickets for them;
            # mark them NEEDS_PROPOSAL by convention so the frontend
            # can render them consistently with new no-contract carts.
            return None
        cache = getattr(self, "_contract_cache", None)
        if cache is None:
            cache = {}
            self._contract_cache = cache
        if obj.id in cache:
            return cache[obj.id]
        parent = obj.extra_work_request
        contract = resolve_price(
            obj.service,
            parent.customer,
            on=obj.requested_date,
        )
        cache[obj.id] = contract
        return contract

    def get_price_source(self, obj):
        contract = self._resolved_contract(obj)
        if contract is None:
            return PRICE_SOURCE_NEEDS_PROPOSAL
        return PRICE_SOURCE_CONTRACT

    def get_contract_unit_price(self, obj):
        contract = self._resolved_contract(obj)
        if contract is None:
            return None
        return _decimal_str(contract.unit_price)

    def get_contract_vat_pct(self, obj):
        contract = self._resolved_contract(obj)
        if contract is None:
            return None
        return _decimal_str(contract.vat_pct)


# ---------------------------------------------------------------------------
# Sprint 180 §1/§2 — the operational-ticket link, shared by the list and
# the detail serializer.
# ---------------------------------------------------------------------------
def _spawned_tickets_for(obj):
    """The operational tickets born from this Extra Work, lowest id first.

    Resolves through the CANONICAL FK (`Ticket.extra_work_request`) and
    nothing else — the same definition `extra_work.billing.
    build_ticket_map` and `reports.dimensions` use to decide what is
    earned and what may be invoiced. `tickets.filters` unions two more
    legacy chains for its `?extra_work_request=` query param; where the
    two disagree, the money definition wins, and one list must not show
    a row as "work started" that the invoice run considers unstarted.

    Reads the view's prefetched list when it is there and falls back to
    a query when it is not (a create read-back, or a detail serializer
    nested in another module's response). Same accessor-with-fallback
    shape as `ServiceSerializer.get_has_price_rows`.
    """
    prefetched = getattr(obj, "prefetched_operational_tickets", None)
    if prefetched is not None:
        return prefetched
    return list(
        obj.operational_tickets.filter(deleted_at__isnull=True).order_by("id")
    )


def _serialize_spawned_tickets(obj):
    return [
        {
            "id": ticket.id,
            "ticket_no": ticket.ticket_no,
            "status": ticket.status,
        }
        for ticket in _spawned_tickets_for(obj)
    ]


def _has_operational_ticket(obj) -> bool:
    """Sprint 180 §1 — the ONE question the two list tracks split on.

    Prefers the view's single `Exists` annotation over the whole page
    (`views_catalog`'s `annotated_has_price_rows` precedent); falls back
    to the prefetched list, and only then to a query.
    """
    annotated = getattr(obj, "annotated_has_operational_ticket", None)
    if annotated is not None:
        return bool(annotated)
    prefetched = getattr(obj, "prefetched_operational_tickets", None)
    if prefetched is not None:
        return bool(prefetched)
    return obj.operational_tickets.filter(deleted_at__isnull=True).exists()


# ---------------------------------------------------------------------------
# Extra Work — list (lean)
# ---------------------------------------------------------------------------
class ExtraWorkRequestListSerializer(serializers.ModelSerializer):
    is_overdue = serializers.BooleanField(read_only=True)
    started_before_plan = serializers.BooleanField(read_only=True)

    # Sprint 180 §1/§2 — the reverse of `Ticket.extra_work_origin`,
    # which had no serializer field at all in either direction from the
    # Extra Work side. `has_operational_ticket` is the track split;
    # `spawned_tickets` is the number and the link.
    has_operational_ticket = serializers.SerializerMethodField()
    spawned_tickets = serializers.SerializerMethodField()

    company_name = serializers.CharField(source="company.name", read_only=True)
    building_name = serializers.CharField(source="building.name", read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    created_by_email = serializers.CharField(
        source="created_by.email", read_only=True
    )
    # Sprint 127 — per-customer labels. `allow_null` so an untagged row
    # (null FK) renders the key as null rather than dropping it (this DRF
    # version raises on the `department.name` traversal otherwise). Visible
    # to every viewer, customers included — the label is not sensitive.
    department_name = serializers.CharField(
        source="department.name", read_only=True, allow_null=True
    )
    work_type_name = serializers.CharField(
        source="work_type.name", read_only=True, allow_null=True
    )
    # Sprint 144 §1 — what the operator actually classified this request
    # as. At most one is set; a pre-144 request has neither and the
    # `category` enum below is all it has. Both surfaces render whichever
    # is present and fall back to the enum label, so the two shapes
    # coexist without a migration.
    service_category_name = serializers.CharField(
        source="service_category.name", read_only=True, allow_null=True
    )
    price_folder_name = serializers.CharField(
        source="price_folder.name", read_only=True, allow_null=True
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
            "department",
            "department_name",
            "work_type",
            "work_type_name",
            "service_category",
            "service_category_name",
            "price_folder",
            "price_folder_name",
            "title",
            "category",
            "urgency",
            "status",
            # Sprint 173 §4 — the deadline, the planned window's end, and
            # the two derived flags. These were declared on this
            # serializer but only added to the DETAIL serializer's
            # `fields`, so DRF asserted on every list call and
            # /api/extra-work/ returned 500 for everyone. They belong on
            # the list precisely because the list is where an operator
            # scans for what is overdue.
            # Sprint 174 §1 — the planned window's START travels with
            # its end: the list's planned/unplanned filter reads it, and
            # a filter reading `undefined` silently calls every row
            # unplanned.
            "preferred_date",
            "deadline",
            "planned_end_date",
            # Sprint 182 §6 — the PROVIDER's planned day. `preferred_date`
            # above is the CUSTOMER's wish (Sprint 176 §3); this is when
            # the provider says the work will actually happen, and it is
            # what lets the Work Plan schedule an extra work at all.
            "provider_planned_date",
            "is_overdue",
            "started_before_plan",
            # Sprint 28 Batch 6 — cart routing taxonomy. Surfaced on
            # the lean list shape so the inbox / overview UIs can
            # branch on INSTANT vs PROPOSAL without a detail fetch.
            "routing_decision",
            # Sprint 2A — explicit customer-facing intent.
            "request_intent",
            # Sprint 180 §1/§2 — which TRACK this row is on, and the
            # operational ticket(s) it produced. Visible to every
            # audience: the customer is entitled to know that their
            # extra work turned into scheduled work.
            "has_operational_ticket",
            "spawned_tickets",
            # Sprint 180 §3 — who the finished work is charged to. Not
            # provider-only: the customer picks it on their own create
            # form, so hiding it from them afterwards would hide their
            # own answer.
            "billed_to",
            "subtotal_amount",
            "vat_amount",
            "total_amount",
            # RF-13 (#106) — final (actual-hours) amounts on the list
            # shape so the invoices overview can compute month totals
            # with the same final-with-quoted-fallback rule the revenue
            # report uses, without a per-row detail fetch. NOT redacted
            # for customers — parity with the detail serializer, where
            # final_* is visible to the customer (it is their invoice
            # amount); only the billing metadata below is provider-only.
            "final_subtotal_amount",
            "final_vat_amount",
            "final_total_amount",
            "created_by",
            "created_by_email",
            "requested_at",
            "updated_at",
            "pricing_proposed_at",
            "customer_decided_at",
            # M4 — billing month / invoice run. Provider-only (stripped for
            # CUSTOMER_USER in to_representation, mirroring the detail
            # serializer). Read-only via read_only_fields = fields.
            "invoice_date",
            "is_invoiced",
            "invoiced_at",
        ]
        read_only_fields = fields

    # Mirror ExtraWorkRequestDetailSerializer's redaction: a CUSTOMER_USER
    # never sees billing metadata on the list either.
    _PROVIDER_ONLY_FIELDS = ("invoice_date", "is_invoiced", "invoiced_at")

    def get_has_operational_ticket(self, obj) -> bool:
        return _has_operational_ticket(obj)

    def get_spawned_tickets(self, obj):
        return _serialize_spawned_tickets(obj)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        user = self.context.get("request").user if self.context.get("request") else None
        if _is_customer(user):
            for field in self._PROVIDER_ONLY_FIELDS:
                data.pop(field, None)
        return data


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
    # Sprint 127 — per-customer labels. `allow_null` so an untagged row
    # (null FK) renders the key as null rather than dropping it. Visible to
    # every viewer, customers included — the label is not sensitive.
    department_name = serializers.CharField(
        source="department.name", read_only=True, allow_null=True
    )
    work_type_name = serializers.CharField(
        source="work_type.name", read_only=True, allow_null=True
    )
    # Sprint 144 §1 — what the operator actually classified this request
    # as. At most one is set; a pre-144 request has neither and the
    # `category` enum below is all it has. Both surfaces render whichever
    # is present and fall back to the enum label, so the two shapes
    # coexist without a migration.
    service_category_name = serializers.CharField(
        source="service_category.name", read_only=True, allow_null=True
    )
    price_folder_name = serializers.CharField(
        source="price_folder.name", read_only=True, allow_null=True
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
    # Sprint 128 §0 — whether department / work_type are locked by an issued
    # invoice, so the relabel UI renders read-only-with-reason instead of an
    # editable control that would 400 on save. DETAIL ONLY (single-object
    # fetch = one query); the list serializer deliberately omits it to avoid
    # an N+1 across every row (Sprint 120's whole reason for existing).
    labels_locked = serializers.SerializerMethodField()
    labels_locked_invoice = serializers.SerializerMethodField()
    # Sprint 180 §1/§2 — same pair as the list serializer, so a page
    # that has the detail does not have to re-derive the track or refetch
    # the ticket list to name the ticket.
    has_operational_ticket = serializers.SerializerMethodField()
    spawned_tickets = serializers.SerializerMethodField()

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
            "department",
            "department_name",
            "work_type",
            "work_type_name",
            "service_category",
            "service_category_name",
            "price_folder",
            "price_folder_name",
            "title",
            "description",
            "category",
            "category_other_text",
            "urgency",
            "preferred_date",
            # Sprint 173 §4 — the planned WINDOW and the deadline, plus
            # the two derived facts. Derived server-side so the list,
            # the detail page and the Work Plan cannot disagree about
            # what "late" or "started early" means.
            "planned_end_date",
            # Sprint 182 §6 — the PROVIDER's planned day. `preferred_date`
            # above is the CUSTOMER's wish (Sprint 176 §3); this is when
            # the provider says the work will actually happen, and it is
            # what lets the Work Plan schedule an extra work at all.
            "provider_planned_date",
            "deadline",
            "is_overdue",
            "started_before_plan",
            "status",
            # Sprint 28 Batch 6 — cart routing taxonomy + nested line
            # items. routing_decision is computed at submission time by
            # the create serializer and is read-only thereafter (Batch 7
            # will act on the value; Batch 6 only stores it).
            "routing_decision",
            # Sprint 2A — explicit customer-facing intent.
            "request_intent",
            # Sprint 180 §1/§2 — the track and the operational ticket(s).
            "has_operational_ticket",
            "spawned_tickets",
            # Sprint 180 §3 — who the finished work is charged to.
            "billed_to",
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
            # Sprint 8B — final billable amounts (NULL until actual
            # hours are entered / frozen at customer approval). Visible
            # to the customer per SoT §5.12.
            "final_subtotal_amount",
            "final_vat_amount",
            "final_total_amount",
            # M4 — billing month / invoice run. Provider-only (stripped for
            # CUSTOMER_USER in to_representation); read-only this commit,
            # provider write lands in 2b.
            "invoice_date",
            "is_invoiced",
            "invoiced_at",
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
            "labels_locked",
            "labels_locked_invoice",
        ]
        read_only_fields = [
            "id",
            "company",
            "company_name",
            "building",
            "building_name",
            "customer",
            "customer_name",
            # Sprint 127 — labels are display-only on the detail serializer
            # (the EW ViewSet has no update action; assignment is create-time
            # via ExtraWorkRequestCreateSerializer).
            "department",
            "work_type",
            "status",
            "routing_decision",
            "request_intent",
            # Sprint 180 — the track, the ticket link and the billing
            # target are all read-only HERE. `billed_to` is written at
            # CREATE time (ExtraWorkRequestCreateSerializer); this
            # ViewSet has no update action at all, so listing it as
            # writable would be a promise no endpoint keeps.
            "has_operational_ticket",
            "spawned_tickets",
            "billed_to",
            "subtotal_amount",
            "vat_amount",
            "total_amount",
            "final_subtotal_amount",
            "final_vat_amount",
            "final_total_amount",
            "invoice_date",
            "is_invoiced",
            "invoiced_at",
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
        "invoice_date",
        "is_invoiced",
        "invoiced_at",
    )

    def get_has_operational_ticket(self, obj) -> bool:
        return _has_operational_ticket(obj)

    def get_spawned_tickets(self, obj):
        return _serialize_spawned_tickets(obj)

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

    def _locking_invoice(self, obj):
        # Sprint 128 §0 — resolve once per (serializer instance, EW) so the
        # two label-lock fields share ONE query. `issued_invoice_locking_
        # labels` is the SAME predicate the relabel endpoint enforces (reused,
        # never re-derived).
        cache = self.__dict__.setdefault("_locking_invoice_cache", {})
        if obj.pk not in cache:
            cache[obj.pk] = issued_invoice_locking_labels(obj)
        return cache[obj.pk]

    def get_labels_locked(self, obj):
        return self._locking_invoice(obj) is not None

    def get_labels_locked_invoice(self, obj):
        invoice = self._locking_invoice(obj)
        if invoice is None:
            return None
        # Sprint 129 §2b — the NUMBER or null, no prose. An ISSUED-but-unsent
        # invoice has no number yet (assigned at SEND, §2A); the frontend
        # picks the localized wording for that case, so the wire never carries
        # a developer/English string.
        return invoice.number or None

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

        from .models import ExtraWorkRequestIntent, ExtraWorkStatus

        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None

        if user is None or not user.is_authenticated:
            return {
                "allowed_next_statuses": [],
                "can_prepare_extra_work_proposal": False,
                "can_override_customer_decision": False,
                "can_auto_start": False,
                "can_view_pricing": False,
                "can_view_proposal_pdf": False,
                "can_approve": False,
                "can_reject": False,
                # M1 B6 — EW message thread posting flags.
                "can_post_ew_public_reply": False,
                "can_post_ew_internal_note": False,
                "can_post_ew_customer_internal": False,
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

        # Sprint 31 — AUTO_START "Start work" affordance. A provider
        # operator in scope may start a PRICING_PROPOSED request that was
        # created with the AUTO_START_AFTER_PRICING intent WITHOUT a
        # customer approval or an override reason (the customer
        # pre-authorised it). This is NOT an override (is_override stays
        # False) so it is independent of the BM override-key — any
        # in-scope provider operator qualifies.
        can_auto_start = (
            (is_super or is_ca_in or is_bm_in)
            and obj.status == ExtraWorkStatus.PRICING_PROPOSED
            and obj.request_intent
            == ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING
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

        # M1 B6 — EW message thread POSTING flags (mirror the
        # `extra_work.message_permissions.user_may_post_ew_message_type`
        # POSTING table; role-only, since the EW-scope precondition is already
        # met by reaching this in-scope detail). The composer reads these so
        # it only offers a tier the POST will accept:
        #   PUBLIC_REPLY = CUST + MGMT + SA;  INTERNAL_NOTE = MGMT + SA;
        #   CUSTOMER_INTERNAL = CUST. Staff never (STAFF never reaches an EW
        #   detail; the flags would be False anyway).
        provider_mgmt = role in (
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        )
        can_post_ew_public_reply = is_customer or provider_mgmt
        can_post_ew_internal_note = provider_mgmt
        can_post_ew_customer_internal = is_customer

        return {
            "allowed_next_statuses": list(allowed),
            "can_prepare_extra_work_proposal": can_prepare_extra_work_proposal,
            "can_override_customer_decision": can_override_customer_decision,
            "can_auto_start": can_auto_start,
            "can_view_pricing": can_view_pricing,
            "can_view_proposal_pdf": can_view_proposal_pdf,
            "can_approve": can_approve,
            "can_reject": can_reject,
            "can_post_ew_public_reply": can_post_ew_public_reply,
            "can_post_ew_internal_note": can_post_ew_internal_note,
            "can_post_ew_customer_internal": can_post_ew_customer_internal,
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
    # Sprint 127 — optional per-customer labels. Nullable + optional so
    # every existing client keeps working; `validate()` enforces the one
    # rule (the label must belong to THIS request's customer). Queryset is
    # unscoped here because the customer is not known until validate(); the
    # same-customer check there is the real gate.
    # Sprint 186 — an extra work always ENDS UP with both, but the wire
    # stays permissive.
    #
    # The owner's requirement is that no extra work is untagged: an
    # untagged row falls out of every report that groups by them, and the
    # invoice granularity option `PER_BUILDING_DEPARTMENT_WORK_TYPE`
    # groups on exactly this pair, so a null there is an invoice nobody
    # asked for.
    #
    # The first cut of this made both fields `required=True`. That is the
    # blunt instrument: it 400s EVERY caller that ever omitted them --
    # 130 existing tests, the customer portal, and any integration -- to
    # enforce something the server can simply supply. Every customer is
    # seeded one Department and one Work type when it is created
    # (`customers/signals.py`), so the value is never in doubt.
    #
    # So: the FORM requires a choice (and pre-selects the seeded pair),
    # and `validate()` below fills in that same pair when a caller omits
    # them. Same guarantee, nobody broken.
    department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(),
        required=False,
        allow_null=True,
        default=None,
    )
    work_type = serializers.PrimaryKeyRelatedField(
        queryset=WorkType.objects.all(),
        required=False,
        allow_null=True,
        default=None,
    )
    line_items = ExtraWorkRequestItemSerializer(many=True)
    # Sprint 2A — explicit customer-facing intent. OPTIONAL on the
    # wire so existing Batch 6/7/8 clients keep working unchanged;
    # when omitted, the serializer derives a safe default from the
    # cart shape (all-agreed ⇒ DIRECT_AGREED_PRICE_ORDER, otherwise
    # REQUEST_QUOTE — never AUTO_START_AFTER_PRICING by default
    # because that flow skips customer approval and must be opt-in).
    request_intent = serializers.ChoiceField(
        choices=ExtraWorkRequest._meta.get_field("request_intent").choices,
        required=False,
        allow_null=True,
        default=None,
    )
    # Sprint 180 §3 — who the finished work is charged to, asked at
    # create time on BOTH create surfaces (the customer-facing and the
    # provider-facing one are the same React page in two roles).
    #
    # OPTIONAL on the wire and NULLABLE, which are two different things
    # and both deliberate (Sprint 182 §6). Omitting the key and sending
    # `null` now mean the same thing — "follow the customer's setting" —
    # which is the right answer for a form field nobody touched.
    #
    # The `default=BUILDING` that stood here is GONE: defaulting it
    # would write a decision nobody made, which is exactly the state
    # migration 0032 had to undo across the whole table. An explicit
    # BUILDING / CUSTOMER still overrides the customer for this one job;
    # anything else is a 400 rather than a silent fallback.
    billed_to = serializers.ChoiceField(
        choices=ExtraWorkBilledTo.choices,
        required=False,
        allow_null=True,
        default=None,
    )

    class Meta:
        model = ExtraWorkRequest
        fields = [
            "id",
            "building",
            "customer",
            "title",
            "description",
            # Sprint 144 §1 — `category` / `category_other_text` stay on
            # the wire (read-write) for API back-compat, but the create
            # FORM no longer asks: it sends `service_category` or
            # `price_folder` instead and lets the enum take its
            # `default=OTHER`.
            "category",
            "category_other_text",
            "service_category",
            "price_folder",
            # Sprint 127 — optional per-customer labels (same-customer
            # enforced in validate()).
            "department",
            "work_type",
            "urgency",
            "preferred_date",
            # Sprint 173 §4 — the planned WINDOW and the deadline, plus
            # the two derived facts. Derived server-side so the list,
            # the detail page and the Work Plan cannot disagree about
            # what "late" or "started early" means.
            "planned_end_date",
            # Sprint 182 §6 — the PROVIDER's planned day. `preferred_date`
            # above is the CUSTOMER's wish (Sprint 176 §3); this is when
            # the provider says the work will actually happen, and it is
            # what lets the Work Plan schedule an extra work at all.
            "provider_planned_date",
            "deadline",
            "is_overdue",
            "started_before_plan",
            "request_intent",
            # Sprint 180 §3 — the billing target, chosen at create time.
            "billed_to",
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
        # with-different-dates is a future feature. Ad-hoc lines
        # (Sprint 2A) intentionally bypass this check — two ad-hoc
        # lines are distinct line items, never duplicates.
        seen_service_ids = set()
        for line in value:
            service = line.get("service")
            if service is None:
                continue
            sid = service.pk
            if sid in seen_service_ids:
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

        # Sprint 186 — no extra work is left untagged.
        #
        # An untagged row falls out of every report that groups by
        # department or work type, and `PER_BUILDING_DEPARTMENT_WORK_TYPE`
        # invoices group on exactly this pair. The FORM makes the operator
        # choose (and pre-selects the seeded pair); this is the floor
        # underneath it, for every other caller.
        #
        # Filled rather than refused: every customer is seeded one of
        # each when it is created, so the answer is never in doubt, and
        # 400-ing a caller over a value the server already knows would
        # break the customer portal and every integration to enforce
        # something it can simply supply.
        if attrs.get("department") is None:
            attrs["department"] = (
                Department.objects.filter(customer=customer, is_active=True)
                .order_by("id")
                .first()
            )
        if attrs.get("work_type") is None:
            attrs["work_type"] = (
                WorkType.objects.filter(customer=customer, is_active=True)
                .order_by("id")
                .first()
            )

        # Sprint 176 §3 — the deadline is a PROVIDER commitment, so the
        # create form refuses one from a customer-side actor.
        #
        # Customers can and do create Extra Work here
        # (`customer_users_can_create_extra_work`, default on), and they
        # already have `preferred_date` — "I would like it around then".
        # The `deadline` is different in kind: it is what turns a row red
        # on the list and in the Work Plan, and what an operator is
        # measured against. A customer who could set it could make the
        # provider late by typing a date. So the customer states a wish;
        # the provider decides what it commits to.
        #
        # Read from `attrs` (the parsed field) rather than `initial_data`,
        # so this does not depend on how the serializer was constructed.
        # An explicit `null` is a no-op, not an attempt to commit the
        # provider to anything, so truthiness is the right test here.
        if is_customer_side(user) and attrs.get("deadline"):
            raise serializers.ValidationError(
                {
                    "deadline": (
                        "Only provider staff can set a deadline. Use "
                        "preferred_date to say when you would like this "
                        "done."
                    ),
                    "code": ERR_DEADLINE_PROVIDER_ONLY,
                }
            )

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

        # Sprint 127 — THE one rule of the label feature: a Department /
        # Work Type assigned to this Extra Work MUST belong to this
        # request's own customer. Sprint 127.1 extracted the check into
        # `validate_labels_for_customer` so this create path and the relabel
        # endpoint share ONE copy of the invariant (they must not drift).
        validate_labels_for_customer(
            customer,
            department=attrs.get("department"),
            work_type=attrs.get("work_type"),
        )

        # Sprint 154 §I.7 — every Extra Work carries BOTH labels.
        #
        # The owner's requirement is that Department and Work Type are
        # mandatory, with an "Algemeen" option always available when a
        # customer has defined none of their own. `customers.signals
        # .ensure_default_labels` guarantees that row exists for every
        # customer (and migration 0017 backfilled the existing ones), so
        # the UI can always offer a valid pick and defaults to it.
        #
        # Here we resolve an OMITTED label to that same "Algemeen" row
        # rather than rejecting the request. See the sprint report for
        # the full reasoning; the short version is that this makes the
        # data invariant ("no unlabelled Extra Work") hold on EVERY write
        # path, including `extra_work.conversion`, which builds its row
        # with `objects.create()` and never sees this serializer at all.
        # A serializer-level `required=True` would leave that path
        # unlabelled while breaking every existing API client.
        #
        # An explicitly-supplied label always wins; this only fills a gap.
        if attrs.get("department") is None or attrs.get("work_type") is None:
            default_department, default_work_type = default_labels_for_customer(
                customer
            )
            if attrs.get("department") is None:
                attrs["department"] = default_department
            if attrs.get("work_type") is None:
                attrs["work_type"] = default_work_type

        # Sprint 3B — every catalog-linked line's service must be
        # owned by the same provider company as the customer.
        # Ad-hoc lines (no service FK) bypass — they are operator-
        # typed and have no provider FK of their own. Mismatched
        # rows are rejected with stable code
        # `line_service_company_mismatch`.
        for index, line in enumerate(attrs.get("line_items", []) or []):
            line_service = line.get("service")
            if line_service is None:
                continue
            if line_service.company_id != customer.company_id:
                raise serializers.ValidationError(
                    {
                        "line_items": [
                            {
                                "service": [
                                    serializers.ErrorDetail(
                                        "Service belongs to a "
                                        "different provider company "
                                        "than the customer.",
                                        code=(
                                            "line_service_company_mismatch"
                                        ),
                                    )
                                ]
                            }
                            if i == index
                            else {}
                            for i, _ in enumerate(
                                attrs.get("line_items", []) or []
                            )
                        ]
                    }
                )

        # Sprint 137 item 6 — a custom-price line may only name a
        # CustomerCustomPrice belonging to THIS customer, and only
        # while it is orderable. Same tenant-scoping intent as the
        # service guard directly above (RBAC H-1/H-2).
        for line in attrs.get("line_items", []) or []:
            line_custom_price = line.get("snapshot_customer_custom_price")
            if line_custom_price is None:
                continue
            _validate_custom_price_orderable(
                line_custom_price, customer, line["requested_date"]
            )

        # Sprint 144 §1 — the `category=OTHER => category_other_text
        # required` rule is GONE from the create path. The form no longer
        # offers the enum at all, so every new request takes
        # `default=OTHER` and this rule would have made a field the
        # operator can no longer see mandatory on every single create.
        # The column and its data are untouched; only the demand is.

        # Sprint 144 §1 — at most ONE of the two classifiers. They are
        # alternatives on one control, so both being set means the client
        # is confused about which it picked, not that the request belongs
        # to both.
        if attrs.get("service_category") and attrs.get("price_folder"):
            raise serializers.ValidationError(
                {
                    "service_category": (
                        "Choose either a catalog category or a customer "
                        "price folder, not both."
                    )
                }
            )
        # Tenant scoping (RBAC H-1/H-2), same intent as the label guard:
        # a category must belong to THIS request's company and a folder
        # to THIS request's customer.
        chosen_category = attrs.get("service_category")
        if (
            chosen_category is not None
            and chosen_category.company_id != customer.company_id
        ):
            raise serializers.ValidationError(
                {
                    "service_category": (
                        "This category belongs to a different provider "
                        "company."
                    )
                }
            )
        chosen_folder = attrs.get("price_folder")
        if chosen_folder is not None and chosen_folder.customer_id != customer.id:
            raise serializers.ValidationError(
                {
                    "price_folder": (
                        "This folder belongs to a different customer."
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

    def _actor_kind(self, user, customer, building):
        # Sprint 5 — delegate to the shared module-level helper so the
        # create gate and the preview endpoint stay byte-equivalent.
        return derive_actor_kind(user, customer, building)

    def create(self, validated_data):
        from django.db import transaction

        line_items_data = validated_data.pop("line_items", [])
        supplied_intent = validated_data.pop("request_intent", None)
        validated_data["company"] = validated_data["customer"].company
        validated_data["created_by"] = self.context["request"].user
        validated_data["status"] = ExtraWorkStatus.REQUESTED

        customer = validated_data["customer"]
        building = validated_data["building"]
        user = self.context["request"].user

        # Sprint 2A — classify every cart line BEFORE persisting so
        # we can validate the (intent × cart × actor) tuple and stamp
        # snapshots in one pass.
        per_line_classification = [
            classify_line(
                service=line.get("service"),
                customer=customer,
                requested_date=line["requested_date"],
                custom_description=(line.get("custom_description") or ""),
                # Sprint 137 item 6 — a custom-price line. Still
                # classifies AD_HOC; see classify_line's docstring.
                custom_price=line.get("snapshot_customer_custom_price"),
            )
            for line in line_items_data
        ]
        cart_classification = classify_cart(per_line_classification)

        actor_kind = self._actor_kind(user, customer, building)
        if supplied_intent:
            try:
                validate_intent_for_cart(
                    intent=supplied_intent,
                    cart=cart_classification,
                    actor_kind=actor_kind,
                )
            except IntentValidationError as exc:
                raise serializers.ValidationError(
                    {
                        "request_intent": [
                            serializers.ErrorDetail(exc.message, code=exc.code)
                        ]
                    }
                )
            effective_intent = supplied_intent
        else:
            # Backward compatibility for Batch 6/7/8 clients that
            # never sent an intent. Derive a safe default (never
            # AUTO_START — that would skip customer approval).
            effective_intent = derive_default_intent(cart_classification)

        validated_data["request_intent"] = effective_intent

        # Sprint 28 Batch 6 — parent + line items + routing decision
        # all land inside a single transaction so a half-created cart
        # (parent saved, no lines) is never observable.
        with transaction.atomic():
            request = super().create(validated_data)

            all_lines_have_contract = True
            for line, classification in zip(
                line_items_data, per_line_classification
            ):
                service = line.get("service")
                # Sprint 2A — ad-hoc lines have no Service FK; unit
                # type defaults to OTHER (legacy placeholder mirroring
                # migration 0003 backfill). Catalog lines denormalise
                # from Service.unit_type to pin pricing semantics.
                #
                # Sprint 137 item 6 — a custom-price line denormalises
                # from the CustomerCustomPrice row instead, for the same
                # reason: a later edit to the price row must not rewrite
                # the historical line's pricing semantics.
                if service is None:
                    unit_type = (
                        classification.custom_unit_type
                        or ExtraWorkPricingUnitType.OTHER
                    )
                else:
                    unit_type = service.unit_type
                ExtraWorkRequestItem.objects.create(
                    extra_work_request=request,
                    service=service,
                    # A custom-price line carries the price row's name
                    # as its description, so every existing renderer
                    # (detail page, proposal builder, exports) shows the
                    # work's real name with no change of its own.
                    custom_description=(
                        classification.custom_description
                        or line.get("custom_description")
                        or ""
                    ),
                    snapshot_customer_custom_price=(
                        classification.custom_price
                    ),
                    quantity=line["quantity"],
                    unit_type=unit_type,
                    requested_date=line["requested_date"],
                    customer_note=line.get("customer_note", ""),
                    # Sprint 2A — snapshot stamping. Source label is
                    # always set; snapshot price columns only when the
                    # line resolved to a contract row (AGREED case).
                    line_price_source=classification.source,
                    snapshot_unit_price=classification.snapshot_unit_price,
                    snapshot_vat_pct=classification.snapshot_vat_pct,
                    snapshot_service_name=classification.snapshot_service_name,
                    snapshot_service_category_name=(
                        classification.snapshot_service_category_name
                    ),
                    snapshot_customer_service_price=classification.contract,
                )
                # Routing decision uses the same AGREED-vs-not split
                # the classifier already computed — keep both in sync.
                if (
                    classification.source
                    != ExtraWorkLinePriceSource.AGREED_CUSTOMER_PRICE
                ):
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
            #
            # Sprint 2A note: the instant-spawn path here is gated on
            # `routing_decision == INSTANT` AND implicitly on the
            # derived/explicit intent being DIRECT_AGREED_PRICE_ORDER
            # — validate_intent_for_cart guarantees that any other
            # intent on an all-agreed cart is rejected, and an
            # all-agreed cart with no explicit intent derives to
            # DIRECT.
            #
            # Sprint 180 §5 — this comment used to end "this spawn
            # still emits one Ticket per ExtraWorkRequestItem for now".
            # That has been false since Sprint 6A: the refactor it calls
            # deferred was DONE, and `instant_tickets.spawn_tickets_for
            # _request` creates exactly ONE Ticket per request (see the
            # request-level idempotency guard there and
            # `test_sprint6_one_ticket_per_request`). One ticket per
            # request is now the assumption the whole Extra Work billing
            # chain rests on, so a comment saying otherwise is worse
            # than no comment.
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
# Extra Work — cart preview / classification (Sprint 5)
# ---------------------------------------------------------------------------
class ExtraWorkPreviewLineSerializer(serializers.Serializer):
    """Lightweight per-line input for the non-mutating preview
    endpoint. Mirrors the cart-line contract of
    `ExtraWorkRequestItemSerializer` (service XOR custom_description,
    quantity > 0, inactive service rejected) WITHOUT pulling in any
    model-bound write path — preview never persists a row.
    """

    service = serializers.PrimaryKeyRelatedField(
        queryset=Service.objects.all(),
        required=False,
        allow_null=True,
        default=None,
    )
    custom_description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=255,
    )
    # Sprint 137 item 6 — mirror of the cart line's custom-price input.
    # Model-free serializer, so it keeps the wire name with no `source`.
    custom_price = serializers.PrimaryKeyRelatedField(
        queryset=CustomerCustomPrice.objects.all(),
        required=False,
        allow_null=True,
        default=None,
    )
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    requested_date = serializers.DateField()
    customer_note = serializers.CharField(
        required=False, allow_blank=True, default=""
    )

    def validate_quantity(self, value):
        if value <= Decimal("0"):
            raise serializers.ValidationError(
                "Quantity must be greater than zero."
            )
        return value

    def validate_service(self, value):
        if value is not None and not value.is_active:
            raise serializers.ValidationError(
                "Cannot order an inactive service."
            )
        return value

    def validate(self, attrs):
        # Sprint 137 item 6 — identical rule to the cart line; shared
        # helper so preview and create cannot drift.
        _validate_line_source_exclusivity(
            service=attrs.get("service"),
            custom_price=attrs.get("custom_price"),
            custom_description=attrs.get("custom_description"),
        )
        return attrs


class ExtraWorkPreviewSerializer(serializers.Serializer):
    """Input validation for `POST /api/extra-work/preview/`.

    Subset of the create cart — no title/description/category. Reuses
    the SAME customer/building scope + permission gate as
    `ExtraWorkRequestCreateSerializer.validate` and the SAME
    cross-company service check. STRICTLY NON-MUTATING: this serializer
    has no `create()`/`save()`; the view reads `validated_data` and
    runs the classifier.
    """

    building = serializers.PrimaryKeyRelatedField(
        queryset=Building.objects.filter(is_active=True)
    )
    customer = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.filter(is_active=True)
    )
    request_intent = serializers.ChoiceField(
        choices=ExtraWorkRequest._meta.get_field("request_intent").choices,
        required=False,
        allow_null=True,
        default=None,
    )
    line_items = ExtraWorkPreviewLineSerializer(many=True)

    def validate_line_items(self, value):
        if not value:
            raise serializers.ValidationError(
                "At least one line item is required."
            )
        return value

    def validate(self, attrs):
        request = self.context["request"]
        user = request.user

        building = attrs["building"]
        customer = attrs["customer"]

        if customer.company_id != building.company_id:
            raise serializers.ValidationError(
                "Building and customer must belong to the same company."
            )

        if not CustomerBuildingMembership.objects.filter(
            customer=customer, building=building
        ).exists():
            raise serializers.ValidationError(
                "Customer is not linked to the selected building."
            )

        # Cross-company service guard — same stable code as create.
        for index, line in enumerate(attrs.get("line_items", []) or []):
            line_service = line.get("service")
            if line_service is None:
                continue
            if line_service.company_id != customer.company_id:
                raise serializers.ValidationError(
                    {
                        "line_items": [
                            {
                                "service": [
                                    serializers.ErrorDetail(
                                        "Service belongs to a "
                                        "different provider company "
                                        "than the customer.",
                                        code=(
                                            "line_service_company_mismatch"
                                        ),
                                    )
                                ]
                            }
                            if i == index
                            else {}
                            for i, _ in enumerate(
                                attrs.get("line_items", []) or []
                            )
                        ]
                    }
                )

        # Sprint 137 item 6 — same custom-price tenant + orderability
        # guard as create (the preview would otherwise leak another
        # tenant's custom-price amount back to the caller).
        for line in attrs.get("line_items", []) or []:
            line_custom_price = line.get("custom_price")
            if line_custom_price is None:
                continue
            _validate_custom_price_orderable(
                line_custom_price, customer, line["requested_date"]
            )

        # Same scope + permission gate as create.
        if user.role == UserRole.CUSTOMER_USER:
            if not user_can(
                user,
                customer.id,
                building.id,
                "customer.extra_work.create",
            ):
                raise serializers.ValidationError(
                    "You do not have permission to preview Extra Work "
                    "for this customer/building."
                )
        elif user.role in {
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        }:
            from accounts.permissions_v2 import user_has_osius_permission

            if user.role != UserRole.SUPER_ADMIN and not user_has_osius_permission(
                user,
                "osius.ticket.view_building",
                building_id=building.id,
            ):
                raise serializers.ValidationError(
                    "You do not have provider-side scope to preview "
                    "Extra Work in this building."
                )
        else:
            raise serializers.ValidationError(
                "This role cannot preview Extra Work."
            )

        return attrs


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
# Sprint 127.1 — relabel payload (provider classification after create)
# ---------------------------------------------------------------------------
class ExtraWorkLabelsSerializer(serializers.Serializer):
    """The NARROW relabel surface for `PATCH /api/extra-work/<id>/labels/`:
    `department` + `work_type` ONLY. Deliberately a standalone Serializer,
    not a general EW update serializer — the EW ViewSet has no update mixin
    by design, and a full serializer would expose every model field.

    Both fields are optional so a client may set either, both, or send an
    explicit `null` to clear one. The view distinguishes "absent" (leave as
    is) from "sent as null" (clear) via key presence in `validated_data`;
    the same-customer invariant is applied in the view against the resolved
    EW's customer (see `label_validation.validate_labels_for_customer`).
    """

    department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(), required=False, allow_null=True
    )
    work_type = serializers.PrimaryKeyRelatedField(
        queryset=WorkType.objects.all(), required=False, allow_null=True
    )


class ExtraWorkDatesSerializer(serializers.Serializer):
    """Sprint 176 §3 — the NARROW date surface for
    `PATCH /api/extra-work/<id>/dates/`: `deadline` + `planned_end_date`
    only.

    Same shape and same reasoning as `ExtraWorkLabelsSerializer` above: the
    EW ViewSet has no update mixin by design, so a date agreed AFTER
    creation had no way in at all — both fields were write-once on the
    create form. A general update serializer would expose every model
    field; this exposes two.

    Both optional, both `allow_null`, so the view can tell "absent" (leave
    unchanged) from "sent as null" (clear) by key presence — the same
    convention the relabel action uses, and the same one the bulk dialog's
    "leave unchanged" default needs.

    `preferred_date` is deliberately NOT here. It is the CUSTOMER's wish,
    recorded at request time; the provider answers it with a `deadline`
    rather than editing it. Letting the provider rewrite what the customer
    asked for would erase the very thing the deadline is judged against.
    """

    deadline = serializers.DateField(required=False, allow_null=True)
    planned_end_date = serializers.DateField(required=False, allow_null=True)
    provider_planned_date = serializers.DateField(required=False, allow_null=True)


# ---------------------------------------------------------------------------
# Sprint 8B — actual-hours entry payload
# ---------------------------------------------------------------------------
class ActualHoursLineSerializer(serializers.Serializer):
    """One `{line_id, actual_hours}` entry in the actual-hours payload.

    `actual_hours` must parse as a Decimal and be strictly > 0 (the
    view raises stable code `actual_hours_invalid` for <= 0; the field
    here only guarantees it is a well-formed Decimal). The view does
    the cross-checks (line belongs to the active set, line is hourly,
    EW not locked) because those need the resolved EW context.
    """

    line_id = serializers.IntegerField()
    actual_hours = serializers.DecimalField(max_digits=12, decimal_places=2)


class ActualHoursEntrySerializer(serializers.Serializer):
    lines = ActualHoursLineSerializer(many=True)

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError(
                serializers.ErrorDetail(
                    "At least one line is required.",
                    code="actual_hours_required",
                )
            )
        return value


# ---------------------------------------------------------------------------
# Sprint 28 Batch 8 — proposal serializers
# ---------------------------------------------------------------------------
def _classify_proposal_line_source(obj: "ProposalLine"):
    """Shared snapshot-vs-live classifier for ProposalLine rows.

    Returns ``(price_source, contract_unit_price, contract_vat_pct)``
    where the last two are Decimals (or None) ready for
    `_decimal_str()` rendering.

    Snapshot rule (matches the module-level docblock):

    * Ad-hoc lines (no `service` FK) are ALWAYS CUSTOM. They were
      operator-typed and have no catalog row to anchor against.
    * Catalog-linked lines call `resolve_price(line.service,
      parent.customer, on=parent.requested_at.date())` to find the
      contract row that WOULD apply right now. If a row is returned
      AND its `unit_price` + `vat_pct` match the line's persisted
      values exactly, the line is CONTRACT and the `contract_*` fields
      mirror the line's snapshot. If the contract row exists but the
      prices diverge (operator typed a different number on the
      proposal), the line is CUSTOM. If no contract row exists, the
      line is CUSTOM. In every CUSTOM case the `contract_*` fields are
      None.

    The resolver is intentionally consulted on a date from the parent
    EW, not the current date, so a contract row that has changed since
    the proposal was built does not silently change the source label
    for a historical render. The snapshot-mirror policy on the
    `contract_*` fields means a downstream contract edit never rewrites
    the amounts in a stored response either.
    """
    if obj.service_id is None:
        return PRICE_SOURCE_CUSTOM, None, None
    parent = obj.proposal.extra_work_request
    contract = resolve_price(
        obj.service,
        parent.customer,
        on=parent.requested_at.date(),
    )
    if contract is None:
        return PRICE_SOURCE_CUSTOM, None, None
    if (
        contract.unit_price == obj.unit_price
        and contract.vat_pct == obj.vat_pct
    ):
        # Mirror the line's persisted snapshot (which equals the
        # contract row's values by construction). We intentionally do
        # NOT return `contract.unit_price` directly — a later edit to
        # the contract row must never rewrite the persisted amount
        # surfaced through this read path.
        return PRICE_SOURCE_CONTRACT, obj.unit_price, obj.vat_pct
    return PRICE_SOURCE_CUSTOM, None, None


class ProposalLineAdminSerializer(serializers.ModelSerializer):
    """
    Full provider-side proposal-line serializer. Carries both
    `customer_explanation` (customer-visible) and `internal_note`
    (provider-only). Used for write paths and admin reads.
    """

    service_name = serializers.CharField(
        source="service.name", read_only=True, default=None
    )
    # #108 Part B — declared explicitly with trim_whitespace=False so
    # the RF-2 mirror in validate() owns the stripping: a supplied
    # whitespace-only label must reach the validator intact to be
    # rejected with the stable `custom_unit_label_required` code
    # (DRF's default trimming would silently collapse it to a legal
    # blank first).
    custom_unit_label = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
    )
    # See module-level "Per-line pricing source" docblock for the
    # contract. Proposal lines have their own persisted `unit_price` +
    # `vat_pct` snapshot; the classifier compares against an active
    # contract row but NEVER mutates the snapshot.
    price_source = serializers.SerializerMethodField()
    contract_unit_price = serializers.SerializerMethodField()
    contract_vat_pct = serializers.SerializerMethodField()

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
            "custom_unit_label",
            "unit_price",
            "vat_pct",
            "customer_explanation",
            "internal_note",
            "is_approved_for_spawn",
            "line_subtotal",
            "line_vat",
            "line_total",
            # Sprint 8B — actual hours (read-only on this read/write
            # serializer; written only via the actual-hours endpoint).
            "actual_hours",
            "price_source",
            "contract_unit_price",
            "contract_vat_pct",
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
            "actual_hours",
            "price_source",
            "contract_unit_price",
            "contract_vat_pct",
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

        # #108 Part B — mirror the RF-2 custom-unit rule from
        # `serializers_catalog.CustomerCustomPriceSerializer` (same
        # stable code `custom_unit_label_required`) with ONE
        # owner-decided difference: a plain OTHER line with a BLANK
        # label stays legal — the composer offers both "Other" and
        # "Custom…", and only the Custom path demands a name (the
        # backend sees that path as a supplied, non-empty label). A
        # concrete unit type forces the label blank so a stale label
        # can never contradict its unit; for OTHER the label is
        # stripped, and a supplied whitespace-only label (an attempted
        # custom name that collapses to nothing) is rejected.
        unit_type = attrs.get(
            "unit_type", getattr(instance, "unit_type", None)
        )
        if unit_type != ExtraWorkPricingUnitType.OTHER:
            if "custom_unit_label" in attrs or instance is not None:
                attrs["custom_unit_label"] = ""
        else:
            raw = attrs.get(
                "custom_unit_label",
                getattr(instance, "custom_unit_label", ""),
            )
            label = (raw or "").strip()
            if raw and not label:
                raise serializers.ValidationError(
                    {
                        "custom_unit_label": [
                            serializers.ErrorDetail(
                                "A unit name is required when the unit "
                                "is entered as Custom.",
                                code="custom_unit_label_required",
                            )
                        ]
                    }
                )
            attrs["custom_unit_label"] = label
        return attrs

    def _classified(self, obj):
        cache = getattr(self, "_classify_cache", None)
        if cache is None:
            cache = {}
            self._classify_cache = cache
        if obj.id not in cache:
            cache[obj.id] = _classify_proposal_line_source(obj)
        return cache[obj.id]

    def get_price_source(self, obj):
        return self._classified(obj)[0]

    def get_contract_unit_price(self, obj):
        return _decimal_str(self._classified(obj)[1])

    def get_contract_vat_pct(self, obj):
        return _decimal_str(self._classified(obj)[2])


class ProposalLineCustomerSerializer(serializers.ModelSerializer):
    """
    Customer-facing proposal-line serializer — DROPS `internal_note`.
    Used for any read path where the requesting user is a
    CUSTOMER_USER.
    """

    service_name = serializers.CharField(
        source="service.name", read_only=True, default=None
    )
    # See module-level "Per-line pricing source" docblock for the
    # contract. Customer-safe by construction — describes the same
    # numbers the customer already sees in `unit_price` / `vat_pct`.
    price_source = serializers.SerializerMethodField()
    contract_unit_price = serializers.SerializerMethodField()
    contract_vat_pct = serializers.SerializerMethodField()

    class Meta:
        model = ProposalLine
        fields = [
            "id",
            "service",
            "service_name",
            "description",
            "quantity",
            "unit_type",
            "custom_unit_label",
            "unit_price",
            "vat_pct",
            "customer_explanation",
            "line_subtotal",
            "line_vat",
            "line_total",
            # Sprint 8B — actual hours; customer-visible per SoT §5.12.
            "actual_hours",
            "price_source",
            "contract_unit_price",
            "contract_vat_pct",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def _classified(self, obj):
        cache = getattr(self, "_classify_cache", None)
        if cache is None:
            cache = {}
            self._classify_cache = cache
        if obj.id not in cache:
            cache[obj.id] = _classify_proposal_line_source(obj)
        return cache[obj.id]

    def get_price_source(self, obj):
        return self._classified(obj)[0]

    def get_contract_unit_price(self, obj):
        return _decimal_str(self._classified(obj)[1])

    def get_contract_vat_pct(self, obj):
        return _decimal_str(self._classified(obj)[2])


def _advance_parent_to_under_review(
    extra_work_request: ExtraWorkRequest, actor
) -> None:
    """Sprint 187 §2a — move a REQUESTED parent to UNDER_REVIEW when a
    proposal is created against it.

    ## The trap this closes

    The detail page offers "Prepare proposal" on a REQUESTED **or**
    UNDER_REVIEW parent, and `ProposalCreateSerializer.validate`
    deliberately admits both. But `can_send` requires UNDER_REVIEW, so an
    operator who reached the builder from REQUESTED could build a
    complete quote and then find the Send button simply absent — and,
    because `can_direct_publish` is derived from `can_send`, the escape
    hatch was hidden too. Both terminal actions on the builder were dead,
    with nothing on screen saying why. The page even contradicted itself:
    the REQUESTED step hint says "Start the review, then prepare a
    pricing proposal" while the CTA below let you do it in the other
    order.

    Creating a proposal IS starting the review, so the order the hint
    describes is now simply true whichever way the operator arrives.

    ## Why `apply_transition` and not the `_advance_parent_on_send`
    ## bypass

    `_advance_parent_on_send` bypasses `apply_transition` for one
    specific reason, stated in its own docstring: that path enforces
    `pricing_line_items_required`, which counts LEGACY
    `ExtraWorkPricingLineItem` rows the proposal flow never writes.

    That precondition is scoped to `to_status == PRICING_PROPOSED`
    (`state_machine.py`), and this transition is
    `REQUESTED -> UNDER_REVIEW`. It cannot trip. So the reason for the
    bypass does not exist here, and the normal path is correct — which
    also means we inherit the role gate, the concurrency lock, the
    history row and the timestamp bookkeeping instead of hand-rolling
    a third copy of them.

    `is_override=False` and no reason: this is an ordinary
    provider-driven transition, present in `ALLOWED_TRANSITIONS` and not
    system-only.

    ## When the actor may not drive it

    A provider operator who lacks `osius.ticket.view_building` at this
    building cannot advance the parent. The proposal creation still
    succeeds — refusing it would take away a capability the operator
    already had — but the failure is NOT swallowed: the reason is
    attached to the returned proposal as `parent_advance_blocked`, and
    the builder renders a disabled Send button carrying it. Silence is
    the actual defect being fixed here; a second silent skip would just
    move it.
    """
    if extra_work_request.status != ExtraWorkStatus.REQUESTED:
        # Idempotent: already UNDER_REVIEW (the normal arrival), or
        # somewhere `validate` would have rejected.
        return
    from .state_machine import TransitionError as EwTransitionError
    from .state_machine import apply_transition as ew_apply_transition

    try:
        ew_apply_transition(
            extra_work_request,
            actor,
            ExtraWorkStatus.UNDER_REVIEW,
            note=(
                "Review started by preparing a pricing proposal "
                "(Sprint 187 §2a)."
            ),
        )
    except EwTransitionError as exc:
        logger.warning(
            "Proposal created on EW #%s but the parent could not be "
            "advanced to UNDER_REVIEW (%s: %s). Send will be blocked "
            "until the parent moves.",
            extra_work_request.pk,
            getattr(exc, "code", "transition_error"),
            exc,
        )
        raise _ParentAdvanceBlocked(str(exc)) from exc


class _ParentAdvanceBlocked(Exception):
    """Carries the human-readable reason the parent could not advance,
    from `_advance_parent_to_under_review` up to `create()`. Never
    reaches the wire as an exception — `create()` turns it into the
    `parent_advance_blocked` field."""


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
    array (or sends `lines=[]`), the serializer auto-seeds
    `ProposalLine` rows from the parent EW's cart. For each cart
    item, the contract resolver
    (`extra_work.pricing.resolve_price`) is consulted with the cart
    item's own `requested_date`. ONLY agreed-priced cart lines (a
    contract row is returned) are auto-seeded, pre-filling
    `unit_price` and `vat_pct` from the contract row. Non-contract
    (custom / needs-proposal) cart lines are NOT auto-seeded; the
    operator adds them deliberately via the composer (they would
    otherwise seed at 0.00 and, since saved proposal lines are
    read-only in the UI, force the operator to remove + re-add
    them). An all-custom cart therefore auto-seeds zero lines and
    yields an empty DRAFT proposal; the existing SEND gate
    (`proposal_lines_required`) blocks sending an empty proposal.
    No metadata marker is written on a seeded line (per the B2
    spec — `customer_explanation` is customer-visible business
    text, not an internal flag; "is this line contract-priced" is
    derived by re-calling `resolve_price` at validation / read
    time).

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
                    # Only auto-seed agreed-priced cart lines. A
                    # non-contract (custom / needs-proposal) line is
                    # skipped: the operator adds it deliberately (and
                    # already priced) via the composer. Auto-seeding it
                    # at 0.00 would force a remove + re-add because saved
                    # proposal lines are read-only in the UI.
                    if contract is None:
                        continue
                    ProposalLine.objects.create(
                        proposal=proposal,
                        service=item.service,
                        description="",
                        quantity=item.quantity,
                        unit_type=item.unit_type,
                        unit_price=contract.unit_price,
                        vat_pct=contract.vat_pct,
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
                        custom_unit_label=line.get("custom_unit_label", ""),
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
            # Sprint 187 §2a — creating a proposal IS starting the
            # review. Inside the same atomic block, so the parent's
            # status write and its history row commit with the proposal
            # or not at all.
            try:
                _advance_parent_to_under_review(extra_work_request, actor)
                proposal._parent_advance_blocked = ""
            except _ParentAdvanceBlocked as blocked:
                # The proposal still gets created — see the helper's
                # docstring. The reason rides back on the response so
                # the builder can say it rather than hide the button.
                proposal._parent_advance_blocked = str(blocked)
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
        from accounts.permissions_v2 import (
            user_has_osius_permission,
            user_has_provider_dangerous_permission,
        )

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
        #
        # Sprint 187 §3 — this flag used to mirror TWO of the endpoint's
        # gates and the endpoint applies FOUR. The consequence was not an
        # edge case: the dedicated dangerous grant below is OFF BY
        # DEFAULT, so in a default deployment an in-scope COMPANY_ADMIN
        # was shown "Publish directly" on a perfectly ordinary DRAFT and
        # it failed 403 every single time.
        #
        # The class docstring's precedent does not cover these. It
        # excuses exactly one kind of gate — the expensive cart-coverage
        # / contract-price validations — and then states the governing
        # rule for everything else: a gate that is cheap and accurate
        # belongs in the action flag. That is why the parent-status guard
        # is already inside `can_send`. Both of these are one attribute
        # read and one cached permission resolve.
        #
        # H-11: reflecting a permission gate in an action flag is
        # REPORTING authority, not granting it. The endpoint's own checks
        # in `views_proposals.py` are untouched and remain the authority;
        # this only stops the UI offering a button that authority will
        # refuse.
        if is_super or is_ca_in:
            can_direct_publish = can_send
        elif is_bm_in:
            can_direct_publish = can_send and bm_has_override
        else:
            can_direct_publish = False

        if can_direct_publish:
            # Gate 3 — the DEDICATED dangerous quote-bypass grant
            # (`views_proposals.py`). Holding the generic B6 override key
            # is explicitly NOT sufficient (SoT §5.5, matrix H-11 —
            # separate concepts). SA resolves True; CA / BM only when
            # their provider company carries the Super-Admin grant.
            can_direct_publish = user_has_provider_dangerous_permission(
                user,
                "provider.extra_work.quote_override_start",
                company_id=extra_work.company_id,
            )

        if can_direct_publish:
            # Gate 4 — the bypass is only meaningful for a
            # Request-a-Quote request. DIRECT_AGREED_PRICE_ORDER spawns
            # immediately and AUTO_START_AFTER_PRICING auto-approves on
            # SEND, so neither has a customer decision to override.
            can_direct_publish = (
                extra_work.request_intent
                == ExtraWorkRequestIntent.REQUEST_QUOTE
            )

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
