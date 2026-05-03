from rest_framework import serializers

from accounts.models import UserRole
from accounts.permissions import is_staff_role
from buildings.models import Building
from customers.models import Customer

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
        ]
        read_only_fields = fields


class TicketDetailSerializer(serializers.ModelSerializer):
    building_name = serializers.CharField(source="building.name", read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True)
    assigned_to_email = serializers.CharField(source="assigned_to.email", read_only=True, default=None)
    status_history = TicketStatusHistorySerializer(many=True, read_only=True)
    allowed_next_statuses = serializers.SerializerMethodField()

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
        ]
        read_only_fields = fields

    def get_allowed_next_statuses(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return []
        return allowed_next_statuses(request.user, obj)


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

        if customer.building_id != building.id:
            raise serializers.ValidationError(
                {"customer": "Customer does not belong to the selected building."}
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

            if not CustomerUserMembership.objects.filter(
                user=user, customer_id=customer.id
            ).exists():
                raise serializers.ValidationError(
                    {"customer": "You are not linked to this customer."}
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
        if not obj.file:
            return ""
        request = self.context.get("request")
        url = obj.file.url
        if request:
            return request.build_absolute_uri(url)
        return url

    def validate_file(self, value):
        max_size = 10 * 1024 * 1024
        allowed_mime_types = {
            "image/jpeg",
            "image/png",
            "image/webp",
            "application/pdf",
        }

        mime_type = getattr(value, "content_type", "") or "application/octet-stream"
        file_size = getattr(value, "size", 0)

        if file_size > max_size:
            raise serializers.ValidationError("Attachment file size cannot exceed 10 MB.")

        if mime_type not in allowed_mime_types:
            raise serializers.ValidationError(
                "Only JPG, PNG, WEBP, and PDF attachments are allowed."
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

        return attrs


class TicketStatusChangeSerializer(serializers.Serializer):
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
