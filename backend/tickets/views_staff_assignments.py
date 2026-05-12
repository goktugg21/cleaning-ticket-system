"""
Sprint 25A — admin/manager direct staff assignment for tickets.

The Sprint 23A `StaffAssignmentRequest` flow is one way to attach a
STAFF user to a ticket: the staff member submits a request and a
manager approves it, which creates the `TicketStaffAssignment` row.

For pilot operations the MAIN path is the inverse: the admin or
manager directly assigns a STAFF member to a ticket without
requiring the staff to file a self-request. Sprint 23B's existing
`TicketViewSet.assign` action and `assignable_managers` action only
deal with `ticket.assigned_to` (a single BUILDING_MANAGER pointer),
so there was no admin-driven path to populate
`TicketStaffAssignment` (the M:N field-staff list shown on the
ticket detail card) until Sprint 25A.

This module ships the minimum surface the pilot audit identified:

  GET    /api/tickets/<id>/staff-assignments/            list current rows
  POST   /api/tickets/<id>/staff-assignments/            {user_id} → add
  DELETE /api/tickets/<id>/staff-assignments/<user_id>/  remove

Permission rules (preserved from Sprint 23B's approve flow):
  - Caller must be SUPER_ADMIN, COMPANY_ADMIN, or BUILDING_MANAGER
    AND hold `osius.ticket.assign_staff` permission for the ticket's
    building. Staff and customer roles → 403.
  - Cross-company / cross-building actors are filtered by
    `scope_tickets_for` at the ticket lookup → 404.
  - Target STAFF user must:
      - hold role=STAFF,
      - have an active `StaffProfile` (Sprint 24A),
      - have `BuildingStaffVisibility` on the ticket's building
        (Sprint 23A). This mirrors the existing
        `osius.staff.request_assignment` resolver, which is the only
        existing gate that already encodes "may operate at this
        building".
  - Duplicates are idempotent: re-POSTing an existing row returns
    `200` with the same payload.
  - Audit logs are emitted by the existing
    `audit/signals.py::_on_membership_post_save` /
    `_on_membership_post_delete` handlers, which already track
    `TicketStaffAssignment` rows for create/delete since Sprint 23A.

Sprint 23B's `staff-assignment-requests/<id>/approve/` is unchanged
— the two paths converge on the same `TicketStaffAssignment` row.
"""
from __future__ import annotations

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.response import Response

from accounts.models import StaffProfile, User, UserRole
from accounts.permissions import IsAuthenticatedAndActive, is_staff_role
from accounts.permissions_v2 import user_has_osius_permission
from accounts.scoping import scope_tickets_for
from buildings.models import BuildingStaffVisibility

from .models import Ticket, TicketStaffAssignment


class _TicketStaffAssignmentSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    user_full_name = serializers.CharField(
        source="user.full_name", read_only=True
    )
    assigned_by_id = serializers.IntegerField(
        source="assigned_by.id", read_only=True, default=None
    )
    assigned_by_email = serializers.CharField(
        source="assigned_by.email", read_only=True, default=None
    )

    class Meta:
        model = TicketStaffAssignment
        fields = [
            "id",
            "ticket",
            "user_id",
            "user_email",
            "user_full_name",
            "assigned_by_id",
            "assigned_by_email",
            "assigned_at",
        ]
        read_only_fields = fields


def _resolve_ticket(request, ticket_id: int) -> Ticket:
    """
    Fetch the ticket via the role-scoped queryset so cross-company /
    cross-building actors see a 404 instead of a 403 leak.
    """
    ticket = get_object_or_404(Ticket, pk=ticket_id, deleted_at__isnull=True)
    if not scope_tickets_for(request.user).filter(pk=ticket.pk).exists():
        raise Http404("Ticket not found.")
    return ticket


def _gate_actor(request, ticket: Ticket):
    """
    Sprint 23A permission gate. The actor must be on the service-
    provider side AND hold `osius.ticket.assign_staff` for the
    ticket's building. STAFF and CUSTOMER_USER never pass.
    """
    if not is_staff_role(request.user):
        return Response(
            {"detail": "Only admins or managers can assign staff to tickets."},
            status=status.HTTP_403_FORBIDDEN,
        )
    if request.user.role == UserRole.STAFF:
        # is_staff_role() includes STAFF (Sprint 23A) for internal-note /
        # first-response purposes. Direct staff assignment is an
        # admin/manager action — not a STAFF action. The osius gate
        # also blocks STAFF, but checking here gives a cleaner error
        # message than a generic 403.
        return Response(
            {"detail": "Staff cannot assign other staff to tickets."},
            status=status.HTTP_403_FORBIDDEN,
        )
    if not user_has_osius_permission(
        request.user,
        "osius.ticket.assign_staff",
        building_id=ticket.building_id,
    ):
        return Response(
            {"detail": "Not allowed to assign staff for this building."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


def _validate_target_staff(target: User, ticket: Ticket):
    """
    The user being assigned must hold role=STAFF, have an active
    StaffProfile, and have BuildingStaffVisibility on the ticket's
    building. Returns an error Response on failure, otherwise None.
    """
    if target.role != UserRole.STAFF:
        return Response(
            {"user_id": "Target user is not a STAFF user."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    profile = getattr(target, "staff_profile", None)
    if profile is None or not profile.is_active:
        return Response(
            {"user_id": "Target staff has no active staff profile."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not BuildingStaffVisibility.objects.filter(
        user=target, building_id=ticket.building_id
    ).exists():
        return Response(
            {"user_id": "Target staff has no visibility on this building."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return None


class TicketStaffAssignmentListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/tickets/<id>/staff-assignments/
    POST /api/tickets/<id>/staff-assignments/   {user_id}
    """

    permission_classes = [IsAuthenticatedAndActive]
    serializer_class = _TicketStaffAssignmentSerializer

    def _resolve(self):
        ticket = _resolve_ticket(self.request, self.kwargs["ticket_id"])
        gate = _gate_actor(self.request, ticket)
        if gate is not None:
            return gate, None
        return None, ticket

    def get_queryset(self):
        ticket = _resolve_ticket(self.request, self.kwargs["ticket_id"])
        return (
            TicketStaffAssignment.objects.filter(ticket=ticket)
            .select_related("user", "assigned_by")
            .order_by("user__email")
        )

    def list(self, request, *args, **kwargs):
        early, _ = self._resolve()
        if early is not None:
            return early
        return super().list(request, *args, **kwargs)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        early, ticket = self._resolve()
        if early is not None:
            return early
        user_id = request.data.get("user_id")
        if not user_id:
            return Response(
                {"user_id": "This field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        target = get_object_or_404(
            User, pk=user_id, is_active=True, deleted_at__isnull=True
        )
        target_check = _validate_target_staff(target, ticket)
        if target_check is not None:
            return target_check

        # Idempotent: re-POSTing an existing pairing returns 200 with
        # the existing row, mirroring Sprint 23B's approve-path
        # `get_or_create`.
        assignment, created = TicketStaffAssignment.objects.get_or_create(
            ticket=ticket,
            user=target,
            defaults={"assigned_by": request.user},
        )
        return Response(
            self.get_serializer(assignment).data,
            status=(
                status.HTTP_201_CREATED if created else status.HTTP_200_OK
            ),
        )


class TicketStaffAssignmentDeleteView(generics.GenericAPIView):
    """
    DELETE /api/tickets/<id>/staff-assignments/<user_id>/
    """

    permission_classes = [IsAuthenticatedAndActive]

    @transaction.atomic
    def delete(self, request, ticket_id, user_id):
        ticket = _resolve_ticket(request, ticket_id)
        gate = _gate_actor(request, ticket)
        if gate is not None:
            return gate
        deleted, _ = TicketStaffAssignment.objects.filter(
            ticket=ticket, user_id=user_id
        ).delete()
        if deleted == 0:
            return Response(
                {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


def assignable_staff_view(request, ticket: Ticket):
    """
    GET-helper for `TicketViewSet.assignable_staff` action — returns
    the STAFF users eligible to be added to the ticket. Eligibility:
      - role=STAFF
      - active StaffProfile
      - BuildingStaffVisibility on the ticket's building
    """
    gate = _gate_actor(request, ticket)
    if gate is not None:
        return gate

    eligible_qs = (
        User.objects.filter(
            role=UserRole.STAFF,
            is_active=True,
            deleted_at__isnull=True,
        )
        .filter(
            staff_profile__is_active=True,
            building_visibility__building_id=ticket.building_id,
        )
        .select_related("staff_profile")
        .order_by("email")
        .distinct()
    )

    return Response(
        [
            {
                "id": u.id,
                "email": u.email,
                "full_name": u.full_name,
                "role": u.role,
            }
            for u in eligible_qs
        ],
        status=status.HTTP_200_OK,
    )
