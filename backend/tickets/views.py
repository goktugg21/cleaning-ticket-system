from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from accounts.models import UserRole
from accounts.permissions import IsAuthenticatedAndActive, is_staff_role
from accounts.scoping import scope_tickets_for

from .filters import TicketFilter
from .models import Ticket, TicketAttachment, TicketMessage, TicketMessageType
from buildings.models import BuildingManagerAssignment
from .permissions import CanPostMessage, CanViewTicket, user_has_scope_for_ticket
from .serializers import (
    TicketAssignableManagerSerializer,
    TicketAssignSerializer,
    TicketAttachmentSerializer,
    TicketCreateSerializer,
    TicketDetailSerializer,
    TicketListSerializer,
    TicketMessageSerializer,
    TicketStatusChangeSerializer,
)


class TicketViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticatedAndActive, CanViewTicket]
    filterset_class = TicketFilter
    search_fields = ["ticket_no", "title", "description", "room_label"]
    ordering_fields = ["created_at", "updated_at", "priority", "status"]

    def get_queryset(self):
        qs = scope_tickets_for(self.request.user).select_related(
            "company", "building", "customer", "created_by", "assigned_to"
        )
        if self.action == "retrieve":
            qs = qs.prefetch_related("status_history", "status_history__changed_by")
        return qs

    def get_serializer_class(self):
        if self.action == "create":
            return TicketCreateSerializer
        if self.action == "retrieve":
            return TicketDetailSerializer
        return TicketListSerializer

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticatedAndActive()]
        return super().get_permissions()

    @action(detail=True, methods=["post"], url_path="status")
    def change_status(self, request, pk=None):
        ticket = self.get_object()
        serializer = TicketStatusChangeSerializer(
            data=request.data,
            context={"request": request, "ticket": ticket},
        )
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return Response(
            TicketDetailSerializer(updated, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


    @action(detail=True, methods=["post"], url_path="assign")
    def assign(self, request, pk=None):
        ticket = self.get_object()
        serializer = TicketAssignSerializer(
            data=request.data,
            context={"request": request, "ticket": ticket},
        )
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return Response(
            TicketDetailSerializer(updated, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


    @action(detail=True, methods=["get"], url_path="assignable-managers")
    def assignable_managers(self, request, pk=None):
        ticket = self.get_object()

        if not is_staff_role(request.user):
            self.permission_denied(
                request,
                message="Customer users cannot view assignable managers.",
            )

        managers = [
            assignment.user
            for assignment in BuildingManagerAssignment.objects.filter(
                building_id=ticket.building_id,
                user__is_active=True,
                user__deleted_at__isnull=True,
                user__role=UserRole.BUILDING_MANAGER,
            )
            .select_related("user")
            .order_by("user__email")
        ]

        return Response(
            TicketAssignableManagerSerializer(managers, many=True).data,
            status=status.HTTP_200_OK,
        )


class TicketMessageListCreateView(generics.ListCreateAPIView):
    serializer_class = TicketMessageSerializer
    permission_classes = [IsAuthenticatedAndActive, CanPostMessage]

    def _get_ticket(self):
        ticket_id = self.kwargs["ticket_id"]
        ticket = get_object_or_404(Ticket, pk=ticket_id)
        if not scope_tickets_for(self.request.user).filter(pk=ticket.pk).exists():
            self.permission_denied(self.request, message="Ticket not found in your scope.")
        self.check_object_permissions(self.request, ticket)
        return ticket

    def get_queryset(self):
        ticket = self._get_ticket()
        qs = TicketMessage.objects.filter(ticket=ticket).select_related("author")
        user = self.request.user
        if not is_staff_role(user):
            qs = qs.filter(is_hidden=False)
            qs = qs.exclude(message_type=TicketMessageType.INTERNAL_NOTE)
        return qs.order_by("created_at")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["ticket"] = self._get_ticket()
        return context

    def perform_create(self, serializer):
        ticket = self._get_ticket()
        user = self.request.user

        message_type = serializer.validated_data.get(
            "message_type", TicketMessageType.PUBLIC_REPLY
        )
        if not is_staff_role(user):
            message_type = TicketMessageType.PUBLIC_REPLY

        message = serializer.save(
            ticket=ticket,
            author=user,
            message_type=message_type,
            is_hidden=(message_type == TicketMessageType.INTERNAL_NOTE),
        )

        # First staff response stamps first_response_at on the ticket.
        if is_staff_role(user):
            ticket.mark_first_response_if_needed()

        return message



class TicketAttachmentListCreateView(generics.ListCreateAPIView):
    serializer_class = TicketAttachmentSerializer
    permission_classes = [IsAuthenticatedAndActive, CanViewTicket]
    parser_classes = [MultiPartParser, FormParser]

    def _get_ticket(self):
        ticket_id = self.kwargs["ticket_id"]
        ticket = get_object_or_404(Ticket, pk=ticket_id)

        if not scope_tickets_for(self.request.user).filter(pk=ticket.pk).exists():
            self.permission_denied(self.request, message="Ticket not found in your scope.")

        self.check_object_permissions(self.request, ticket)
        return ticket

    def get_queryset(self):
        ticket = self._get_ticket()
        qs = TicketAttachment.objects.filter(ticket=ticket).select_related(
            "uploaded_by",
            "message",
        )

        user = self.request.user
        if not is_staff_role(user):
            qs = qs.filter(is_hidden=False)
            qs = qs.exclude(message__is_hidden=True)
            qs = qs.exclude(message__message_type=TicketMessageType.INTERNAL_NOTE)

        return qs.order_by("-created_at")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["ticket"] = self._get_ticket()
        return context

    def perform_create(self, serializer):
        ticket = self._get_ticket()
        user = self.request.user
        uploaded_file = serializer.validated_data["file"]

        is_hidden = serializer.validated_data.get("is_hidden", False)
        if not is_staff_role(user):
            is_hidden = False

        serializer.save(
            ticket=ticket,
            uploaded_by=user,
            original_filename=uploaded_file.name,
            mime_type=getattr(uploaded_file, "content_type", "") or "application/octet-stream",
            file_size=getattr(uploaded_file, "size", 0),
            is_hidden=is_hidden,
        )


class TicketAttachmentDownloadView(generics.GenericAPIView):
    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, ticket_id, attachment_id):
        ticket = get_object_or_404(Ticket, pk=ticket_id)

        if not scope_tickets_for(request.user).filter(pk=ticket.pk).exists():
            self.permission_denied(request, message="Ticket not found in your scope.")

        attachment = get_object_or_404(
            TicketAttachment,
            pk=attachment_id,
            ticket=ticket,
        )

        if attachment.is_hidden and not is_staff_role(request.user):
            self.permission_denied(request, message="Attachment not found in your scope.")

        if not attachment.file:
            raise Http404("File not found.")

        return FileResponse(
            attachment.file.open("rb"),
            as_attachment=True,
            filename=attachment.original_filename,
        )
