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

from django.db import transaction
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
    # Sprint 24D — narrow filterable fields. The default
    # DjangoFilterBackend in settings.REST_FRAMEWORK picks these up so
    # callers can target a single (ticket, staff, status) tuple without
    # having to walk every page of their own request list. This is the
    # frontend pending-discovery contract: the TicketDetailPage queries
    # `?ticket=<id>&status=PENDING` and gets at most ONE row back per
    # staff user (the duplicate guard in `create()` allows one PENDING
    # per (staff, ticket)).
    filterset_fields = ["status", "ticket", "staff"]

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
        """
        Sprint 24D — approve/reject path is now wrapped in a single
        `transaction.atomic()` block with `select_for_update()` on the
        StaffAssignmentRequest row. The row-level lock serialises
        concurrent acts (e.g. one COMPANY_ADMIN clicks Approve while
        another clicks Reject, or while STAFF clicks Cancel) so the
        loser sees the fresh status and 400s out instead of silently
        overwriting the winner. select_for_update is a no-op on the
        SQLite test backend but works as expected against PostgreSQL,
        which is the canonical deployment.

        Permission + 404 checks stay OUTSIDE the lock so a denied
        caller does not hold a row lock while the response is built.
        """
        try:
            # Scope-resolve the pk against the role-scoped queryset
            # WITHOUT the lock — this is a read-only check that the
            # caller can see this row at all (cross-company / cross-
            # building actors transparently 404 here).
            req = self.get_queryset().get(pk=pk)
        except StaffAssignmentRequest.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not user_has_osius_permission(
            request.user, perm_key, building_id=req.ticket.building_id
        ):
            return Response(
                {"detail": "Not allowed."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Re-fetch under SELECT FOR UPDATE so the status check + write
        # form one atomic critical section.
        with transaction.atomic():
            locked = (
                StaffAssignmentRequest.objects
                .select_for_update()
                .get(pk=req.pk)
            )
            if locked.status != AssignmentRequestStatus.PENDING:
                return Response(
                    {"detail": "Request is not pending."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            locked.status = target_status
            locked.reviewed_by = request.user
            locked.reviewed_at = timezone.now()
            locked.reviewer_note = request.data.get("reviewer_note", "") or ""
            locked.save(
                update_fields=[
                    "status",
                    "reviewed_by",
                    "reviewed_at",
                    "reviewer_note",
                ]
            )
            # Approving an assignment request CREATES the assignment
            # row. We do this inside the same transaction so the
            # caller gets one atomic "approve and assign" round-trip.
            if target_status == AssignmentRequestStatus.APPROVED:
                TicketStaffAssignment.objects.get_or_create(
                    ticket=locked.ticket,
                    user=locked.staff,
                    defaults={"assigned_by": request.user},
                )
        return Response(self.get_serializer(locked).data)

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

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """
        Sprint 24C — STAFF self-cancellation.

        A STAFF user may cancel their OWN PENDING request before a
        reviewer acts on it. Sprint 23A reserved the `CANCELLED`
        status in `AssignmentRequestStatus.choices` for exactly this
        purpose, so no migration is needed.

        Permission rules (preserved from Sprint 23A scoping):
          - STAFF only. Other roles get 403 from the role gate.
          - The viewset's `get_queryset` already narrows STAFF rows
            to `staff=request.user`, so trying to cancel another
            staff member's request transparently 404s — the row is
            invisible to the actor.
          - Status MUST be PENDING. Any other status (APPROVED /
            REJECTED / CANCELLED) returns 400 so an already-acted
            row is not silently overwritten.

        After the row is CANCELLED, the existing duplicate-prevention
        in `create()` (filters on `status=PENDING`) lets the staff
        user submit a fresh request for the same ticket if they
        change their mind.
        """
        if request.user.role != UserRole.STAFF:
            return Response(
                {"detail": "Only STAFF users can cancel their own request."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            # Scope-resolve under the role-scoped queryset so a STAFF
            # actor cannot cancel another staff member's row even if
            # they guess the pk (the queryset filters to
            # `staff=request.user`).
            req = self.get_queryset().get(pk=pk)
        except StaffAssignmentRequest.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        # Defence in depth — the queryset already enforces this,
        # but a hand-rolled raw query at some future point should
        # still reject cancels against other staff's rows.
        if req.staff_id != request.user.id:
            return Response(status=status.HTTP_404_NOT_FOUND)
        # Sprint 24D — atomic transition. Re-fetch under
        # SELECT FOR UPDATE so a near-simultaneous admin approve /
        # reject sees this cancel's status flip (or vice versa) and
        # the loser 400s instead of silently overwriting state.
        with transaction.atomic():
            locked = (
                StaffAssignmentRequest.objects
                .select_for_update()
                .get(pk=req.pk)
            )
            if locked.status != AssignmentRequestStatus.PENDING:
                return Response(
                    {"detail": "Request is not pending."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            locked.status = AssignmentRequestStatus.CANCELLED
            # `reviewed_*` deliberately stays blank — a cancellation
            # is staff-initiated, not a reviewer action. Stamping it
            # would conflate two different audit shapes.
            locked.save(update_fields=["status"])
        return Response(self.get_serializer(locked).data)
