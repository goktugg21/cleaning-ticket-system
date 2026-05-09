from django.urls import reverse
from django.utils import timezone
from pathlib import Path as FilePath

from rest_framework import serializers

from accounts.models import User, UserRole
from accounts.permissions import is_staff_role
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
        fields = [
            "id",
            "old_status",
            "new_status",
            "changed_by",
            "changed_by_email",
            "note",
            "created_at",
        ]
        read_only_fields = fields


class TicketListSerializer(serializers.ModelSerializer):
    building_name = serializers.CharField(source="building.name", read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
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
    created_by_email = serializers.CharField(source="created_by.email", read_only=True)
    assigned_to_email = serializers.CharField(source="assigned_to.email", read_only=True, default=None)
    status_history = TicketStatusHistorySerializer(many=True, read_only=True)
    allowed_next_statuses = serializers.SerializerMethodField()
    sla_is_paused = serializers.SerializerMethodField()
    sla_remaining_business_seconds = serializers.SerializerMethodField()
    sla_display_state = serializers.SerializerMethodField()

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
            "building",
            "building_name",
            "customer",
            "customer_name",
            "created_by",
            "created_by_email",
            "assigned_to",
            "assigned_to_email",
            "created_at",
            "updated_at",
            "first_response_at",
            "sent_for_approval_at",
            "approved_at",
            "rejected_at",
            "resolved_at",
            "closed_at",
            "status_history",
            "allowed_next_statuses",
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
        ]
        read_only_fields = fields

    def get_allowed_next_statuses(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return []
        return allowed_next_statuses(request.user, obj)

    def get_sla_is_paused(self, obj):
        return obj.sla_paused_at is not None

    def get_sla_remaining_business_seconds(self, obj):
        return _sla_remaining_business_seconds(obj)

    def get_sla_display_state(self, obj):
        return _sla_display_state(obj)


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
            if not CustomerUserBuildingAccess.objects.filter(
                membership=membership, building_id=building.id
            ).exists():
                raise serializers.ValidationError(
                    {"building": "You do not have access to this building under this customer."}
                )
            return attrs

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
        if value == TicketMessageType.INTERNAL_NOTE and not is_staff_role(user):
            raise serializers.ValidationError("Customer users cannot post internal notes.")
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

        if value and not is_staff_role(user):
            raise serializers.ValidationError(
                "Customer users cannot upload hidden/internal attachments."
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

        if (
            message
            and not is_staff_role(user)
            and (message.is_hidden or message.message_type == TicketMessageType.INTERNAL_NOTE)
        ):
            raise serializers.ValidationError(
                {"message": "Customer users cannot attach files to hidden/internal messages."}
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

        return attrs

    to_status = serializers.ChoiceField(choices=TicketStatus.choices)
    note = serializers.CharField(required=False, allow_blank=True, default="")

    def save(self, **kwargs):
        ticket = self.context["ticket"]
        user = self.context["request"].user
        try:
            return apply_transition(
                ticket=ticket,
                user=user,
                to_status=self.validated_data["to_status"],
                note=self.validated_data.get("note", ""),
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

        if not is_staff_role(user):
            raise serializers.ValidationError(
                {"detail": "Customer users cannot assign tickets."}
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
