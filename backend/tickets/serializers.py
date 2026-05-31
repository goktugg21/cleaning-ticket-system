from django.urls import reverse
from django.utils import timezone
from pathlib import Path as FilePath

from rest_framework import serializers

from accounts.models import User, UserRole
from accounts.permissions import (
    is_provider_management_role,
    is_staff_role,
)
from accounts.permissions_v2 import user_has_osius_permission
from buildings.models import Building, BuildingManagerAssignment
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
)
from sla import business_hours

from .models import (
    Ticket,
    TicketAttachment,
    TicketMessage,
    TicketMessageType,
    TicketStatus,
    TicketStatusHistory,
)
from .permissions import user_has_scope_for_ticket
from .state_machine import TransitionError, allowed_next_statuses, apply_transition


def _sla_display_state(obj):
    """Mirror of frontend getSLADisplayState — paused overrides underlying state."""
    if obj.sla_status == "HISTORICAL":
        return "HISTORICAL"
    if obj.sla_status == "COMPLETED":
        return "COMPLETED"
    if obj.sla_paused_at is not None:
        return "PAUSED"
    if obj.sla_status == "BREACHED":
        return "BREACHED"
    if obj.sla_status == "AT_RISK":
        return "AT_RISK"
    return "ON_TRACK"


def _sla_remaining_business_seconds(obj):
    """
    Positive when remaining, negative when overdue, None when not applicable
    (paused / HISTORICAL / COMPLETED / no due date).
    """
    if obj.sla_paused_at is not None:
        return None
    if obj.sla_status in ("HISTORICAL", "COMPLETED"):
        return None
    if obj.sla_due_at is None:
        return None
    now = timezone.now()
    if now <= obj.sla_due_at:
        return business_hours.business_seconds_between(now, obj.sla_due_at)
    return -business_hours.business_seconds_between(obj.sla_due_at, now)


ALLOWED_ATTACHMENT_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".pdf",
    ".heic",
    ".heif",
}

ALLOWED_ATTACHMENT_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
    "image/heic",
    "image/heif",
}

ALLOWED_ATTACHMENT_MESSAGE = (
    "Only JPG, JPEG, PNG, WEBP, PDF, HEIC, and HEIF attachments are allowed."
)


class TicketStatusHistorySerializer(serializers.ModelSerializer):
    changed_by_email = serializers.CharField(source="changed_by.email", read_only=True)

    class Meta:
        model = TicketStatusHistory
        # Sprint 27F-B1 — expose the new workflow-override columns so
        # the UI timeline can render the override badge alongside the
        # operator's reason. Both fields default to safe values (False
        # / empty string) on legacy rows post-migration.
        fields = [
            "id",
            "old_status",
            "new_status",
            "changed_by",
            "changed_by_email",
            "note",
            "created_at",
            "is_override",
            "override_reason",
        ]
        read_only_fields = fields

    def to_representation(self, instance):
        # B1 (system-business-logic-and-workflows.md §7 + §13) — when a
        # CUSTOMER_USER reads the timeline, redact `note` and
        # `override_reason` on rows authored by a provider-side actor.
        # The free-text `note` field is shared by provider operators and
        # customers; a provider operator can write provider-internal
        # context there (cost notes, internal coordination, override
        # reasoning beyond the structured `override_reason`). Customers
        # must never see it. Rows whose `changed_by` is None (system
        # transitions) or a CUSTOMER_USER (the customer themself, e.g.
        # their own reject reason) keep `note` visible.
        #
        # B7 — the same `note` and `override_reason` redaction also
        # applies to STAFF when the row is a provider-management
        # customer-decision override (`is_override=True` with the
        # author being a provider management role). Per §9.2 of the
        # canonical doc, STAFF must not see PROVIDER_INTERNAL notes;
        # override-row commentary on a customer-decision transition is
        # PROVIDER_INTERNAL by purpose (commercial reasoning, manager
        # rationale). STAFF still sees the non-override `note` field
        # (operational handoff context) and any STAFF-authored
        # completion notes — those are STAFF_COMPLETION /
        # STAFF_OPERATIONAL by purpose.
        data = super().to_representation(instance)
        request = self.context.get("request")
        viewer = getattr(request, "user", None) if request else None
        viewer_role = getattr(viewer, "role", None)
        changed_by = getattr(instance, "changed_by", None)
        author_role = getattr(changed_by, "role", None)

        if viewer_role == UserRole.CUSTOMER_USER:
            if author_role is not None and author_role != UserRole.CUSTOMER_USER:
                data["note"] = ""
                data["override_reason"] = ""

        elif viewer_role == UserRole.STAFF:
            # Redact PROVIDER_INTERNAL override commentary for STAFF.
            # The structured `override_reason` is always PROVIDER_INTERNAL
            # by purpose (only populated on provider-driven overrides);
            # the free-text `note` on an override row carries the same
            # provider-internal context and must be redacted alongside.
            is_provider_override = (
                getattr(instance, "is_override", False)
                and author_role in {
                    UserRole.SUPER_ADMIN,
                    UserRole.COMPANY_ADMIN,
                    UserRole.BUILDING_MANAGER,
                }
            )
            if is_provider_override:
                data["note"] = ""
                data["override_reason"] = ""
        return data


class TicketListSerializer(serializers.ModelSerializer):
    building_name = serializers.CharField(source="building.name", read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True)
    assigned_to_email = serializers.CharField(source="assigned_to.email", read_only=True, default=None)
    sla_is_paused = serializers.SerializerMethodField()
    sla_remaining_business_seconds = serializers.SerializerMethodField()
    sla_display_state = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id",
            "ticket_no",
            "title",
            "type",
            "priority",
            "status",
            "company",
            "company_name",
            "building",
            "building_name",
            "customer",
            "customer_name",
            "assigned_to",
            "assigned_to_email",
            "created_at",
            "updated_at",
            "sla_is_paused",
            "sla_remaining_business_seconds",
            "sla_display_state",
        ]
        read_only_fields = fields

    def get_sla_is_paused(self, obj):
        return obj.sla_paused_at is not None

    def get_sla_remaining_business_seconds(self, obj):
        return _sla_remaining_business_seconds(obj)

    def get_sla_display_state(self, obj):
        return _sla_display_state(obj)


class TicketDetailSerializer(serializers.ModelSerializer):
    building_name = serializers.CharField(source="building.name", read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True)
    assigned_to_email = serializers.CharField(source="assigned_to.email", read_only=True, default=None)
    status_history = TicketStatusHistorySerializer(many=True, read_only=True)
    allowed_next_statuses = serializers.SerializerMethodField()
    # Per-record per-current-user actions block. Lets BM / STAFF /
    # CUSTOMER_USER (who cannot self-introspect via the admin-only
    # `/api/users/<id>/effective-permissions/` endpoint) learn what they
    # can do on THIS specific ticket. Composed from the live resolvers
    # so the frontend never re-implements gates and cannot drift. See
    # `get_actions` below for the field-by-field rationale.
    actions = serializers.SerializerMethodField()
    sla_is_paused = serializers.SerializerMethodField()
    sla_remaining_business_seconds = serializers.SerializerMethodField()
    sla_display_state = serializers.SerializerMethodField()
    # Sprint 23A — list of staff currently assigned to the ticket
    # via TicketStaffAssignment. For a CUSTOMER_USER caller, the
    # output is gated through Customer.show_assigned_staff_*
    # flags so the customer never sees fields the policy hides.
    # See _assigned_staff_payload() below.
    assigned_staff = serializers.SerializerMethodField()
    # Sprint 28 Batch 11 — per-current-user "is this caller listed
    # on TicketStaffAssignment for this ticket?" flag. The frontend
    # completion-modal logic uses this to decide whether to render the
    # "Complete work" button without making a separate API call.
    is_assigned_staff = serializers.SerializerMethodField()
    # Sprint 28 Batch 15.4 — surface the parent Extra Work request when
    # the ticket was spawned through either the INSTANT-route auto-
    # approval (`extra_work_request_item` set) or the PROPOSAL-route
    # approval (`proposal_line` set). The payload is metadata-only:
    # parent id + title + status + origin tag + the line's
    # `service_name`. Provider-only EW fields (`internal_cost_note`,
    # `manager_note`, override_*) are intentionally NOT surfaced — the
    # caller must hit `/api/extra-work/<id>/` for that, where the
    # role-aware serializer enforces visibility.
    extra_work_origin = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id",
            "ticket_no",
            "title",
            "description",
            "room_label",
            "type",
            "priority",
            "status",
            "company",
            "company_name",
            "building",
            "building_name",
            "customer",
            "customer_name",
            "created_by",
            "created_by_email",
            "assigned_to",
            "assigned_to_email",
            "assigned_staff",
            "is_assigned_staff",
            "created_at",
            "updated_at",
            "first_response_at",
            "sent_for_approval_at",
            "manager_review_at",
            "approved_at",
            "rejected_at",
            "resolved_at",
            "closed_at",
            "status_history",
            "allowed_next_statuses",
            "actions",
            "sla_status",
            "sla_due_at",
            "sla_started_at",
            "sla_completed_at",
            "sla_paused_at",
            "sla_paused_seconds",
            "sla_first_breached_at",
            "sla_is_paused",
            "sla_remaining_business_seconds",
            "sla_display_state",
            "extra_work_origin",
        ]
        read_only_fields = fields

    def _resolve_allowed_next_statuses(self, obj):
        """Single computation shared by the top-level
        `allowed_next_statuses` field and the `actions` block. We cache
        on the serializer instance keyed by the ticket id so the two
        callers cannot drift; the same call inside one render also
        avoids a redundant queryset scan in `_user_passes_scope`.
        """
        cache = getattr(self, "_allowed_next_cache", None)
        if cache is not None and cache[0] == obj.id:
            return cache[1]
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            result = []
        else:
            result = allowed_next_statuses(request.user, obj)
        self._allowed_next_cache = (obj.id, result)
        return result

    def get_allowed_next_statuses(self, obj):
        return self._resolve_allowed_next_statuses(obj)

    def get_actions(self, obj):
        """Per-current-user, per-ticket capability block.

        Every boolean mirrors a live backend gate (state machine, write
        validator, attachment gate) so the frontend never re-derives a
        rule and the answer cannot drift from what the user actually
        gets when they POST. See the brief for the field contract.

        Anonymous (or any non-authenticated) callers get an empty
        statuses list + every boolean False — the serializer is
        normally only reached behind the authenticated TicketViewSet
        gate, but defence in depth here covers any future read path
        that drops the `request` context.
        """
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if user is None or not user.is_authenticated:
            allowed = []
            blank: dict = {
                "allowed_next_statuses": [],
                "can_override_customer_decision": False,
                "can_post_provider_internal_note": False,
                "can_post_staff_operational_note": False,
                "can_post_staff_completion_note": False,
                "can_upload_hidden_attachment": False,
                "status_transitions": {
                    str(status): False for status, _label in TicketStatus.choices
                },
            }
            return blank

        allowed = self._resolve_allowed_next_statuses(obj)
        # `status_transitions` is the same data as `allowed_next_statuses`
        # reshaped as an O(1) lookup dict. The frontend renders one
        # button per status and reads `actions.status_transitions[s]`
        # to decide enabled/disabled.
        allowed_set = {str(s) for s in allowed}
        status_transitions = {
            str(status): (str(status) in allowed_set)
            for status, _label in TicketStatus.choices
        }

        role = getattr(user, "role", None)
        # `can_override_customer_decision` mirrors the
        # `provider_driven_customer_decision` coercion block in
        # `tickets.state_machine.apply_transition`: SA / CA in scope /
        # BM in assigned building (gated by the B6 revocable key) —
        # the per-record answer is precise to THIS ticket's building.
        has_override_authority = False
        if role == UserRole.SUPER_ADMIN:
            has_override_authority = True
        elif role == UserRole.COMPANY_ADMIN:
            from companies.models import CompanyUserMembership
            has_override_authority = CompanyUserMembership.objects.filter(
                user=user, company_id=obj.company_id
            ).exists()
        elif role == UserRole.BUILDING_MANAGER:
            assigned = BuildingManagerAssignment.objects.filter(
                user=user, building_id=obj.building_id
            ).exists()
            has_override_authority = assigned and user_has_osius_permission(
                user,
                "osius.building_manager.override_customer_decision",
                building_id=obj.building_id,
            )
        # Tightened so the answer reflects CURRENT record state, not
        # just authority: the override is only meaningful at the
        # customer-decision step (WAITING_CUSTOMER_APPROVAL with
        # APPROVED or REJECTED reachable in the live state machine).
        in_decision_phase = (
            str(obj.status) == str(TicketStatus.WAITING_CUSTOMER_APPROVAL)
            and (
                str(TicketStatus.APPROVED) in allowed_set
                or str(TicketStatus.REJECTED) in allowed_set
            )
        )
        can_override_customer_decision = (
            has_override_authority and in_decision_phase
        )

        # Note booleans mirror `TicketMessageSerializer.validate_message_type`
        # exactly (which the view's `perform_create` defers to). The
        # four-tier taxonomy lives in `TicketMessageType` (B7); each
        # boolean below corresponds to a non-trivial tier:
        #
        #   * INTERNAL_NOTE (PROVIDER_INTERNAL) — provider mgmt only.
        #   * STAFF_OPERATIONAL — any provider-side actor (incl. STAFF).
        #   * STAFF_COMPLETION — any provider-side actor (incl. STAFF).
        #
        # `PUBLIC_REPLY` is omitted because every authenticated viewer
        # in scope on the ticket can author it; the frontend doesn't
        # need a boolean for "always-allowed" tiers.
        can_post_provider_internal_note = is_provider_management_role(user)
        can_post_staff_operational_note = is_staff_role(user)
        can_post_staff_completion_note = is_staff_role(user)
        # Mirrors `TicketAttachmentSerializer.validate_is_hidden`. Only
        # provider management may upload an `is_hidden=True` attachment
        # (the moderation flag that strips visibility from STAFF and
        # customer-side queries).
        can_upload_hidden_attachment = is_provider_management_role(user)

        return {
            "allowed_next_statuses": list(allowed),
            "can_override_customer_decision": can_override_customer_decision,
            "can_post_provider_internal_note": can_post_provider_internal_note,
            "can_post_staff_operational_note": can_post_staff_operational_note,
            "can_post_staff_completion_note": can_post_staff_completion_note,
            "can_upload_hidden_attachment": can_upload_hidden_attachment,
            "status_transitions": status_transitions,
        }

    def get_sla_is_paused(self, obj):
        return obj.sla_paused_at is not None

    def get_sla_remaining_business_seconds(self, obj):
        return _sla_remaining_business_seconds(obj)

    def get_sla_display_state(self, obj):
        return _sla_display_state(obj)

    def get_assigned_staff(self, obj):
        request = self.context.get("request")
        viewer = getattr(request, "user", None) if request else None
        return _assigned_staff_payload(obj, viewer)

    def get_is_assigned_staff(self, obj):
        """
        Sprint 28 Batch 11 — True iff the requesting user is listed on
        a `TicketStaffAssignment` row for this ticket. Used by the
        frontend completion modal to decide whether to render the
        "Complete work" button without a separate API call.
        """
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if user is None or not user.is_authenticated:
            return False
        from .models import TicketStaffAssignment

        return TicketStaffAssignment.objects.filter(
            ticket=obj, user=user
        ).exists()

    def get_extra_work_origin(self, obj):
        """
        Sprint 28 Batch 15.4 — surface parent Extra Work metadata when
        the ticket was spawned from a cart line. Returns None when the
        ticket was created via the legacy direct-API path. Same payload
        for every role (the parent EW detail endpoint enforces the
        provider-only-field stripping; this serializer never carries
        those fields in the first place).

        Sprint 6A — origin resolution:
          * Resolve the parent EW via the CANONICAL
            `obj.extra_work_request` FK first; fall back to the legacy
            `proposal_line` / `extra_work_request_item` chains only
            when the canonical FK is null (historical rows).
          * Classify `origin` from the resolved EW's
            `routing_decision`: INSTANT -> "INSTANT", else "PROPOSAL".
          * `extra_work_request_item_id` + `service_name` come from the
            representative linked line (the FIRST line the spawn helper
            stamped on the back-compat FK).
          * Return None only when NO EW can be resolved by any path.
        """
        from extra_work.models import ExtraWorkRoutingDecision

        item = obj.extra_work_request_item
        proposal_line = obj.proposal_line

        # Canonical resolution.
        ew_request = obj.extra_work_request
        if ew_request is None:
            # Legacy fallback: proposal chain, then cart-item chain.
            if proposal_line is not None:
                ew_request = proposal_line.proposal.extra_work_request
            elif item is not None:
                ew_request = item.extra_work_request

        if ew_request is None:
            return None

        # Representative line for the back-compat payload keys. The
        # proposal helper stamps `proposal_line`; the instant / legacy
        # helpers stamp `extra_work_request_item`.
        if proposal_line is not None:
            service = proposal_line.service
            item_id = item.id if item is not None else None
        elif item is not None:
            service = item.service
            item_id = item.id
        else:
            service = None
            item_id = None

        origin = (
            "INSTANT"
            if ew_request.routing_decision == ExtraWorkRoutingDecision.INSTANT
            else "PROPOSAL"
        )

        return {
            "extra_work_request_id": ew_request.id,
            "extra_work_request_title": ew_request.title,
            "extra_work_request_status": ew_request.status,
            "extra_work_request_item_id": item_id,
            "service_name": service.name if service is not None else None,
            "origin": origin,
        }


def _assigned_staff_payload(ticket, viewer):
    """
    Sprint 23A — render the list of staff assigned to a ticket
    through the customer's contact-visibility policy.

    For OSIUS-side viewers (SUPER_ADMIN / COMPANY_ADMIN /
    BUILDING_MANAGER / STAFF) the full record is always returned —
    those roles need name/email/phone to coordinate work.

    For CUSTOMER_USER viewers the Customer.show_assigned_staff_*
    flags act as filters. If all three flags are False the payload
    collapses to a single anonymous label key the frontend renders
    as "Assigned to the OSIUS team" (locale: en) /
    "Toegewezen aan het OSIUS-team" (locale: nl).
    """
    assignments = list(
        ticket.staff_assignments.select_related("user", "user__staff_profile")
        .order_by("assigned_at")
    )
    if not assignments:
        return []

    is_customer = getattr(viewer, "role", None) == UserRole.CUSTOMER_USER
    customer = ticket.customer
    if is_customer:
        show_name = bool(customer.show_assigned_staff_name)
        show_email = bool(customer.show_assigned_staff_email)
        show_phone = bool(customer.show_assigned_staff_phone)
        if not (show_name or show_email or show_phone):
            return [{"anonymous": True, "label_key": "tickets.assigned_team_anonymous"}]
    else:
        show_name = show_email = show_phone = True

    out = []
    for a in assignments:
        user = a.user
        entry = {"id": user.id}
        if show_name:
            entry["full_name"] = user.full_name or user.email.split("@")[0]
        if show_email:
            entry["email"] = user.email
        if show_phone:
            profile = getattr(user, "staff_profile", None)
            entry["phone"] = profile.phone if profile else ""
        out.append(entry)
    return out


class TicketCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = [
            "id",
            "ticket_no",
            "title",
            "description",
            "room_label",
            "type",
            "priority",
            "building",
            "customer",
            "status",
            "created_at",
        ]
        read_only_fields = ["id", "ticket_no", "status", "created_at"]

    def validate(self, attrs):
        request = self.context["request"]
        user = request.user
        building: Building = attrs["building"]
        customer: Customer = attrs["customer"]

        # Sprint 14: customer/building pair must be linked via the M:N
        # CustomerBuildingMembership. We deliberately accept the legacy
        # `customer.building == building` shape for already-existing
        # customers (the migration backfill creates a matching
        # CustomerBuildingMembership row, so the new check below also
        # passes for legacy data — no special case needed).
        if not CustomerBuildingMembership.objects.filter(
            customer_id=customer.id, building_id=building.id
        ).exists():
            raise serializers.ValidationError(
                {"customer": "Customer is not linked to the selected building."}
            )

        if not building.is_active:
            raise serializers.ValidationError(
                {"building": "This building is inactive and cannot receive new tickets."}
            )
        if not customer.is_active:
            raise serializers.ValidationError(
                {"customer": "This customer is inactive and cannot receive new tickets."}
            )

        if user.role == UserRole.SUPER_ADMIN:
            return attrs

        if user.role == UserRole.COMPANY_ADMIN:
            from companies.models import CompanyUserMembership

            if not CompanyUserMembership.objects.filter(
                user=user, company_id=building.company_id
            ).exists():
                raise serializers.ValidationError(
                    {"building": "You are not a member of the company that owns this building."}
                )
            return attrs

        if user.role == UserRole.BUILDING_MANAGER:
            from buildings.models import BuildingManagerAssignment

            if not BuildingManagerAssignment.objects.filter(
                user=user, building_id=building.id
            ).exists():
                raise serializers.ValidationError(
                    {"building": "You are not assigned to this building."}
                )
            return attrs

        if user.role == UserRole.CUSTOMER_USER:
            from customers.models import CustomerUserMembership
            from customers.permissions import access_has_permission

            membership = CustomerUserMembership.objects.filter(
                user=user, customer_id=customer.id
            ).first()
            if membership is None:
                raise serializers.ValidationError(
                    {"customer": "You are not linked to this customer."}
                )

            # Sprint 14: customer-users must additionally have building
            # access for the (customer, building) pair. A user with
            # access to B3 only cannot create a ticket for B1, even if
            # the customer is linked to both.
            #
            # Sprint 23A (corrected before PR #50): the access row
            # must be ACTIVE, and the resolved permission for the
            # `customer.ticket.create` key must be True. An inactive
            # row resolves every key to False (handled inside
            # access_has_permission), so a single `if not allowed`
            # test below is enough.
            #
            # CUSTOMER_COMPANY_ADMIN spans buildings: an admin holding
            # an active access row at ANY building of the customer
            # whose role/override grants `customer.ticket.create`
            # may create at any other building of the same customer.
            pair_access = CustomerUserBuildingAccess.objects.filter(
                membership=membership, building_id=building.id
            ).first()
            if pair_access is not None and access_has_permission(
                pair_access, "customer.ticket.create"
            ):
                return attrs

            company_admin_access = CustomerUserBuildingAccess.objects.filter(
                membership=membership,
                is_active=True,
                access_role=(
                    CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
                ),
            ).first()
            if company_admin_access is not None and access_has_permission(
                company_admin_access, "customer.ticket.create"
            ):
                return attrs

            # No active pair-access row, OR override revokes create,
            # OR access role doesn't grant create — block.
            raise serializers.ValidationError(
                {
                    "building": (
                        "You do not have permission to create a ticket at "
                        "this location."
                    )
                }
            )

        raise serializers.ValidationError("You do not have permission to create tickets.")

    def create(self, validated_data):
        request = self.context["request"]
        building: Building = validated_data["building"]
        validated_data["company"] = building.company
        validated_data["created_by"] = request.user
        validated_data["status"] = TicketStatus.OPEN
        return super().create(validated_data)


class TicketMessageSerializer(serializers.ModelSerializer):
    author_email = serializers.CharField(source="author.email", read_only=True)

    class Meta:
        model = TicketMessage
        fields = [
            "id",
            "ticket",
            "author",
            "author_email",
            "message",
            "message_type",
            "is_hidden",
            "created_at",
        ]
        read_only_fields = ["id", "ticket", "author", "author_email", "is_hidden", "created_at"]

    def validate_message_type(self, value):
        request = self.context.get("request")
        user = request.user if request else None
        # B7 — INTERNAL_NOTE (PROVIDER_INTERNAL) is provider-management
        # only. STAFF cannot author it. Customer-side users cannot
        # author it. The two staff-facing tiers (STAFF_OPERATIONAL,
        # STAFF_COMPLETION) require any provider-side actor; the
        # view's perform_create forces non-provider-side authors to
        # PUBLIC_REPLY before this validator fires so a customer
        # cannot smuggle a STAFF_* tier through the wire.
        if value == TicketMessageType.INTERNAL_NOTE and not (
            is_provider_management_role(user)
        ):
            raise serializers.ValidationError(
                "Only provider management roles "
                "(Super Admin / Provider Company Admin / Building "
                "Manager) may post internal (provider-internal) notes."
            )
        if value in {
            TicketMessageType.STAFF_OPERATIONAL,
            TicketMessageType.STAFF_COMPLETION,
        } and not is_staff_role(user):
            raise serializers.ValidationError(
                "Only provider-side actors may post staff "
                "operational / completion notes."
            )
        return value

    def validate(self, attrs):
        ticket = self.context["ticket"]
        user = self.context["request"].user
        if not user_has_scope_for_ticket(user, ticket):
            raise serializers.ValidationError("You do not have access to this ticket.")
        return attrs


class TicketAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by_email = serializers.CharField(source="uploaded_by.email", read_only=True)
    file = serializers.FileField(write_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = TicketAttachment
        fields = [
            "id",
            "ticket",
            "message",
            "uploaded_by",
            "uploaded_by_email",
            "file",
            "file_url",
            "original_filename",
            "mime_type",
            "file_size",
            "is_hidden",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "ticket",
            "message",
            "uploaded_by",
            "uploaded_by_email",
            "file_url",
            "original_filename",
            "mime_type",
            "file_size",
            "created_at",
        ]

    def get_file_url(self, obj):
        request = self.context.get("request")
        path = reverse(
            "ticket-attachment-download",
            kwargs={"ticket_id": obj.ticket_id, "attachment_id": obj.id},
        )
        if request:
            return request.build_absolute_uri(path)
        return path

    def validate_file(self, value):
        max_size = 10 * 1024 * 1024
        allowed_mime_types = ALLOWED_ATTACHMENT_MIME_TYPES

        mime_type = getattr(value, "content_type", "") or "application/octet-stream"
        file_size = getattr(value, "size", 0)
        extension = FilePath(getattr(value, "name", "")).suffix.lower()

        if file_size > max_size:
            raise serializers.ValidationError("Attachment file size cannot exceed 10 MB.")

        if extension not in ALLOWED_ATTACHMENT_EXTENSIONS:
            raise serializers.ValidationError(ALLOWED_ATTACHMENT_MESSAGE)

        if mime_type not in allowed_mime_types:
            raise serializers.ValidationError(
                ALLOWED_ATTACHMENT_MESSAGE
            )

        return value

    def validate_is_hidden(self, value):
        request = self.context.get("request")
        user = request.user if request else None

        # B7 — `is_hidden=True` is the PROVIDER_INTERNAL moderation
        # flag; only provider management roles may set it. STAFF must
        # not be able to hide an attachment because hidden attachments
        # are filtered out of STAFF's own queryset (see
        # `TicketAttachmentListCreateView.get_queryset`).
        if value and not is_provider_management_role(user):
            raise serializers.ValidationError(
                "Only provider management roles may upload "
                "hidden/internal attachments."
            )

        return value

    def validate(self, attrs):
        ticket = self.context["ticket"]
        user = self.context["request"].user

        if not user_has_scope_for_ticket(user, ticket):
            raise serializers.ValidationError("You do not have access to this ticket.")

        message = attrs.get("message")
        if message and message.ticket_id != ticket.id:
            raise serializers.ValidationError(
                {"message": "Attachment message must belong to this ticket."}
            )

        # B7 — disallow attaching to hidden / PROVIDER_INTERNAL
        # messages unless the actor is provider management. STAFF was
        # previously admitted by `is_staff_role`; the four-tier model
        # narrows that to provider management roles only, mirroring
        # the visibility queryset above.
        if (
            message
            and not is_provider_management_role(user)
            and (
                message.is_hidden
                or message.message_type == TicketMessageType.INTERNAL_NOTE
            )
        ):
            raise serializers.ValidationError(
                {
                    "message": (
                        "Only provider management roles may attach "
                        "files to hidden / provider-internal messages."
                    )
                }
            )
        # B7 — disallow customer-side actors from attaching to a
        # STAFF_OPERATIONAL message (those are not customer-visible).
        if (
            message
            and not is_staff_role(user)
            and message.message_type == TicketMessageType.STAFF_OPERATIONAL
        ):
            raise serializers.ValidationError(
                {
                    "message": (
                        "Customer users cannot attach files to "
                        "staff-operational messages."
                    )
                }
            )

        return attrs


class TicketStatusChangeSerializer(serializers.Serializer):
    def validate(self, attrs):
        attrs = super().validate(attrs)

        # CUSTOMER_REJECT_REQUIRES_NOTE
        request = self.context.get("request")
        current_user = getattr(request, "user", None)
        note = (attrs.get("note") or "").strip()
        attrs["note"] = note
        to_status = attrs.get("to_status")

        if (
            getattr(current_user, "role", None) == "CUSTOMER_USER"
            and str(to_status) == "REJECTED"
            and not note
        ):
            raise serializers.ValidationError(
                {"note": "Please explain why this ticket is rejected."}
            )

        # Sprint 28 Batch 11 — BM rejection of a staff-completed ticket
        # (WAITING_MANAGER_REVIEW -> IN_PROGRESS) requires a note. Defence in
        # depth at the view+serializer layer; state machine also enforces.
        ticket = self.context.get("ticket")
        if (
            ticket is not None
            and str(ticket.status) == "WAITING_MANAGER_REVIEW"
            and str(to_status) == "IN_PROGRESS"
            and not note
        ):
            raise serializers.ValidationError(
                {"note": "Please explain why you are sending this back to in-progress."}
            )

        return attrs

    to_status = serializers.ChoiceField(choices=TicketStatus.choices)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    # Sprint 27F-B1 — workflow override surface. Mirrors the Extra Work
    # transition endpoint: clients send `is_override + override_reason`
    # when a provider operator is driving a customer-decision
    # transition. The state-machine layer coerces `is_override=True`
    # for SUPER_ADMIN / COMPANY_ADMIN driving WAITING_CUSTOMER_APPROVAL
    # -> APPROVED/REJECTED even if the client forgot the flag, and
    # rejects with `override_reason_required` when the reason is
    # missing.
    is_override = serializers.BooleanField(required=False, default=False)
    override_reason = serializers.CharField(
        required=False, allow_blank=True, default=""
    )

    def save(self, **kwargs):
        ticket = self.context["ticket"]
        user = self.context["request"].user
        try:
            return apply_transition(
                ticket=ticket,
                user=user,
                to_status=self.validated_data["to_status"],
                note=self.validated_data.get("note", ""),
                is_override=self.validated_data.get("is_override", False),
                override_reason=self.validated_data.get("override_reason", ""),
            )
        except TransitionError as exc:
            raise serializers.ValidationError({"detail": str(exc), "code": exc.code})


class TicketAssignableManagerSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "full_name", "role"]
        read_only_fields = fields


class TicketAssignSerializer(serializers.Serializer):
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True, deleted_at__isnull=True),
        allow_null=True,
    )

    def validate(self, attrs):
        ticket = self.context["ticket"]
        request = self.context["request"]
        user = request.user
        assigned_to = attrs.get("assigned_to")

        # Sprint 28 Batch 2: STAFF must not reassign tickets via this
        # serializer either. The view-level gate at `tickets/views.py`
        # is the primary gate (returns 403); this check is defense in
        # depth so a future call-site that bypasses the view still
        # rejects with a clear ValidationError. `is_staff_role` returns
        # True for STAFF and is therefore the wrong gate here — gate
        # explicitly on the allowed role set.
        #
        # Sprint 28 Batch 10: STAFF passes this serializer-level gate
        # only when the actor holds a `BuildingStaffVisibility` row at
        # level `BUILDING_READ_AND_ASSIGN` for the ticket's building.
        # The view layer already enforces the same shape; the
        # serializer mirror keeps defence-in-depth at the same shape.
        # PM Q5: the multi-staff endpoint stays admin-only; that's
        # enforced by `views_staff_assignments.py::_gate_actor` — not
        # by this serializer.
        if user.role == UserRole.STAFF:
            from buildings.models import BuildingStaffVisibility

            if not BuildingStaffVisibility.objects.filter(
                user=user,
                building_id=ticket.building_id,
                visibility_level=BuildingStaffVisibility.VisibilityLevel.BUILDING_READ_AND_ASSIGN,
            ).exists():
                raise serializers.ValidationError(
                    {"detail": "This role cannot assign tickets."}
                )
        elif user.role not in (
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        ):
            raise serializers.ValidationError(
                {"detail": "This role cannot assign tickets."}
            )

        if assigned_to is None:
            return attrs

        if assigned_to.role != UserRole.BUILDING_MANAGER:
            raise serializers.ValidationError(
                {"assigned_to": "Ticket can only be assigned to a building manager."}
            )

        if not BuildingManagerAssignment.objects.filter(
            user=assigned_to,
            building_id=ticket.building_id,
        ).exists():
            raise serializers.ValidationError(
                {"assigned_to": "Manager is not assigned to this ticket building."}
            )

        return attrs

    def save(self, **kwargs):
        ticket = self.context["ticket"]
        ticket.assigned_to = self.validated_data["assigned_to"]
        ticket.save(update_fields=["assigned_to", "updated_at"])
        return ticket
