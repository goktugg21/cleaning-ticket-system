from django.db.models import Count
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from accounts.models import UserRole
from accounts.permissions import IsAuthenticatedAndActive, is_staff_role
from accounts.scoping import scope_tickets_for
from notifications.services import (
    send_ticket_assigned_email,
    send_ticket_created_email,
    send_ticket_status_changed_email,
    send_ticket_unassigned_email,
)

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
    ordering_fields = ["created_at", "updated_at", "priority", "status"]

    @property
    def search_fields(self):
        # Only staff can substring-search across descriptions; for customer
        # users descriptions can carry context that should stay scoped to the
        # one ticket they were typed into. Implemented as a property because
        # DRF's SearchFilter reads view.search_fields directly via getattr.
        if is_staff_role(self.request.user):
            return ["ticket_no", "title", "room_label", "description"]
        return ["ticket_no", "title", "room_label"]

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

    def perform_create(self, serializer):
        ticket = serializer.save()
        send_ticket_created_email(ticket, actor=self.request.user)

    @action(detail=True, methods=["post"], url_path="status")
    def change_status(self, request, pk=None):
        ticket = self.get_object()
        old_status = ticket.status
        to_status = request.data.get("to_status")
        if not is_staff_role(request.user) and to_status not in {
            "APPROVED",
            "REJECTED",
        }:
            self.permission_denied(
                request,
                message="Customer users cannot perform staff-only status transitions.",
            )
        serializer = TicketStatusChangeSerializer(
            data=request.data,
            context={"request": request, "ticket": ticket},
        )
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        is_admin_override = (
            is_staff_role(request.user)
            and old_status == "WAITING_CUSTOMER_APPROVAL"
            and updated.status in {"APPROVED", "REJECTED"}
        )
        send_ticket_status_changed_email(
            updated,
            old_status=old_status,
            new_status=updated.status,
            actor=request.user,
            is_admin_override=is_admin_override,
        )
        return Response(
            TicketDetailSerializer(updated, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


    @action(detail=True, methods=["post"], url_path="assign")
    def assign(self, request, pk=None):
        ticket = self.get_object()
        if not is_staff_role(request.user):
            self.permission_denied(
                request,
                message="Customer users cannot assign tickets.",
            )
        old_assigned_to = ticket.assigned_to
        serializer = TicketAssignSerializer(
            data=request.data,
            context={"request": request, "ticket": ticket},
        )
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()

        old_assigned_to_id = old_assigned_to.id if old_assigned_to else None
        if old_assigned_to_id != updated.assigned_to_id:
            send_ticket_assigned_email(
                updated,
                old_assigned_to=old_assigned_to,
                actor=request.user,
            )
            if old_assigned_to is not None:
                send_ticket_unassigned_email(
                    updated,
                    recipient_user=old_assigned_to,
                    actor=request.user,
                )

        return Response(
            TicketDetailSerializer(updated, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        scoped = scope_tickets_for(request.user)

        status_counts = {row["status"]: row["c"] for row in scoped.values("status").annotate(c=Count("id"))}
        priority_counts = {row["priority"]: row["c"] for row in scoped.values("priority").annotate(c=Count("id"))}

        closed_states = {"CLOSED", "APPROVED", "REJECTED"}
        my_open = sum(c for s, c in status_counts.items() if s not in closed_states)
        waiting_customer_approval = status_counts.get("WAITING_CUSTOMER_APPROVAL", 0)
        urgent = scoped.exclude(status__in=closed_states).filter(priority="URGENT").count()
        total = sum(status_counts.values())

        return Response(
            {
                "total": total,
                "by_status": status_counts,
                "by_priority": priority_counts,
                "my_open": my_open,
                "waiting_customer_approval": waiting_customer_approval,
                "urgent": urgent,
            },
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
            raise Http404("Ticket not found.")
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
            raise Http404("Ticket not found.")

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
            raise Http404("Ticket not found.")

        attachment = get_object_or_404(
            TicketAttachment,
            pk=attachment_id,
            ticket=ticket,
        )

        hidden_by_message = (
            attachment.message_id
            and (
                attachment.message.is_hidden
                or attachment.message.message_type == TicketMessageType.INTERNAL_NOTE
            )
        )
        if (attachment.is_hidden or hidden_by_message) and not is_staff_role(request.user):
            self.permission_denied(request, message="Attachment not found in your scope.")

        if not attachment.file:
            raise Http404("File not found.")

        return FileResponse(
            attachment.file.open("rb"),
            as_attachment=True,
            filename=attachment.original_filename,
        )
