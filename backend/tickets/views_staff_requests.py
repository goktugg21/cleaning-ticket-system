"""
Sprint 23A — minimal API for the staff-initiated
"I want to do this work" assignment-request flow.

Scope of this view is intentionally narrow:
  - STAFF user with osius.staff.request_assignment can POST to
    create a PENDING request for a ticket they have building
    visibility for.
  - BUILDING_MANAGER / COMPANY_ADMIN / SUPER_ADMIN can list
    PENDING requests for their scope and approve / reject them.
  - CUSTOMER_USER calls always get an empty list — the resource
    is invisible to the customer side.

The UI for this endpoint is deferred to Sprint 23B; only the
backend contract + tests ship in 23A.
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import UserRole
from accounts.permissions_v2 import user_has_osius_permission
from buildings.models import BuildingManagerAssignment

from .models import (
    AssignmentRequestStatus,
    StaffAssignmentRequest,
    Ticket,
    TicketStaffAssignment,
)


class _RequestSerializer(serializers.ModelSerializer):
    staff_email = serializers.CharField(source="staff.email", read_only=True)
    ticket_no = serializers.CharField(source="ticket.ticket_no", read_only=True)
    ticket_title = serializers.CharField(source="ticket.title", read_only=True)
    reviewer_email = serializers.CharField(
        source="reviewed_by.email", read_only=True, default=None
    )

    class Meta:
        model = StaffAssignmentRequest
        fields = [
            "id",
            "staff",
            "staff_email",
            "ticket",
            "ticket_no",
            "ticket_title",
            "status",
            "requested_at",
            "reviewed_by",
            "reviewer_email",
            "reviewed_at",
            "reviewer_note",
        ]
        read_only_fields = [
            "id",
            "staff",
            "staff_email",
            "ticket_no",
            "ticket_title",
            "status",
            "requested_at",
            "reviewed_by",
            "reviewer_email",
            "reviewed_at",
            "reviewer_note",
        ]


class StaffAssignmentRequestViewSet(viewsets.ModelViewSet):
    """
    Endpoints (relative to `/api/staff-assignment-requests/`):

      GET  /              — list visible requests
      POST /              — staff creates a request for a ticket
      POST /{id}/approve/ — manager approves a request
      POST /{id}/reject/  — manager rejects a request

    DELETE / PATCH are not supported in 23A. A staff user who
    wants to cancel their own pending request can do so via a
    Sprint 23B endpoint; for now an admin can reject it.
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = _RequestSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        # CUSTOMER_USER never sees this resource. Returning none()
        # at the queryset layer means list / detail / actions all
        # 404 for customers — no information leak.
        if user.role == UserRole.CUSTOMER_USER:
            return StaffAssignmentRequest.objects.none()
        if user.role == UserRole.SUPER_ADMIN:
            return StaffAssignmentRequest.objects.all()
        if user.role == UserRole.COMPANY_ADMIN:
            # A COMPANY_ADMIN sees every request whose ticket
            # belongs to a company they administer.
            from companies.models import CompanyUserMembership

            company_ids = CompanyUserMembership.objects.filter(
                user=user
            ).values_list("company_id", flat=True)
            return StaffAssignmentRequest.objects.filter(
                ticket__company_id__in=company_ids
            )
        if user.role == UserRole.BUILDING_MANAGER:
            building_ids = BuildingManagerAssignment.objects.filter(
                user=user
            ).values_list("building_id", flat=True)
            return StaffAssignmentRequest.objects.filter(
                ticket__building_id__in=building_ids
            )
        if user.role == UserRole.STAFF:
            # STAFF only see their own requests.
            return StaffAssignmentRequest.objects.filter(staff=user)
        return StaffAssignmentRequest.objects.none()

    def create(self, request, *args, **kwargs):
        user = request.user
        if user.role != UserRole.STAFF:
            return Response(
                {"detail": "Only STAFF users can request assignment."},
                status=status.HTTP_403_FORBIDDEN,
            )
        ticket_id = request.data.get("ticket")
        if not ticket_id:
            return Response(
                {"ticket": "This field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            ticket = Ticket.objects.get(pk=ticket_id, deleted_at__isnull=True)
        except Ticket.DoesNotExist:
            return Response(
                {"detail": "Ticket not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # The user must have request_assignment permission FOR THE
        # ticket's building.
        if not user_has_osius_permission(
            user,
            "osius.staff.request_assignment",
            building_id=ticket.building_id,
        ):
            return Response(
                {"detail": "Not allowed to request assignment for this ticket."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Already assigned? Nothing to request.
        if TicketStaffAssignment.objects.filter(
            ticket=ticket, user=user
        ).exists():
            return Response(
                {"detail": "Already assigned to this ticket."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Duplicate pending request? Reject silently.
        if StaffAssignmentRequest.objects.filter(
            ticket=ticket, staff=user, status=AssignmentRequestStatus.PENDING
        ).exists():
            return Response(
                {"detail": "A pending request already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        req = StaffAssignmentRequest.objects.create(
            staff=user,
            ticket=ticket,
            status=AssignmentRequestStatus.PENDING,
        )
        return Response(
            self.get_serializer(req).data, status=status.HTTP_201_CREATED
        )

    def _review(self, request, pk, target_status, perm_key):
        try:
            req = self.get_queryset().get(pk=pk)
        except StaffAssignmentRequest.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if req.status != AssignmentRequestStatus.PENDING:
            return Response(
                {"detail": "Request is not pending."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not user_has_osius_permission(
            request.user, perm_key, building_id=req.ticket.building_id
        ):
            return Response(
                {"detail": "Not allowed."},
                status=status.HTTP_403_FORBIDDEN,
            )
        req.status = target_status
        req.reviewed_by = request.user
        req.reviewed_at = timezone.now()
        req.reviewer_note = request.data.get("reviewer_note", "") or ""
        req.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewed_at",
                "reviewer_note",
            ]
        )
        # Approving an assignment request CREATES the assignment
        # row. We do this in the same view so the caller gets one
        # atomic "approve and assign" round-trip.
        if target_status == AssignmentRequestStatus.APPROVED:
            TicketStaffAssignment.objects.get_or_create(
                ticket=req.ticket,
                user=req.staff,
                defaults={"assigned_by": request.user},
            )
        return Response(self.get_serializer(req).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._review(
            request,
            pk,
            AssignmentRequestStatus.APPROVED,
            "osius.assignment_request.approve",
        )

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._review(
            request,
            pk,
            AssignmentRequestStatus.REJECTED,
            "osius.assignment_request.reject",
        )
