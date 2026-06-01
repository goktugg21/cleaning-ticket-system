"""
Sprint 10B — admin/manager direct manager assignment for tickets.

The single `Ticket.assigned_to` FK has always been the legacy "primary
manager" pointer, written by the Sprint 23B `TicketViewSet.assign`
action. SoT §4.2 needs the inverse of `TicketStaffAssignment`: an
EXPLICIT per-ticket responsible-manager M:N so a ticket can carry more
than one responsible BUILDING_MANAGER at once. That is
`TicketManagerAssignment`, and this module is its write/read surface —
modelled 1:1 on `views_staff_assignments.py`:

  GET    /api/tickets/<id>/manager-assignments/            list rows
  POST   /api/tickets/<id>/manager-assignments/            {user_id} OR
                                                           {user_ids:[...]} -> add
  DELETE /api/tickets/<id>/manager-assignments/<user_id>/  remove

Permission rules (mirror the staff-assignment gate):
  - Caller must be SUPER_ADMIN, COMPANY_ADMIN, or BUILDING_MANAGER AND
    hold `osius.ticket.assign_staff` for the ticket's building (that key
    already means "may manage this building's ticket assignments" — it
    is reused verbatim, no new key is minted). STAFF and CUSTOMER_USER
    roles -> 403 `manager_assignment_forbidden`.
  - Cross-company / cross-building actors are filtered by
    `scope_tickets_for` at the ticket lookup -> 404.
  - Target user must hold role=BUILDING_MANAGER (400
    `manager_assignment_target_invalid`) AND have a
    `BuildingManagerAssignment` for the ticket's building (400
    `manager_not_eligible`). Cross-company targets are caught by the
    building-eligibility check because a BuildingManagerAssignment is
    building-scoped and the building belongs to exactly one company; an
    explicit cross-company guard (400 `manager_assignment_scope_forbidden`)
    is also applied defence-in-depth when the target's BM assignment
    building belongs to a different company than the ticket.
  - Terminal / converted tickets cannot become newly assignable:
    a ticket in {APPROVED, REJECTED, CLOSED, CONVERTED_TO_EXTRA_WORK}
    -> 400 `manager_assignment_terminal`.
  - All-or-nothing: when a bulk `user_ids` list is posted, EVERY target
    is validated before any row is written; a single invalid target
    400s the whole request and writes nothing.
  - Duplicates are idempotent: a row that already existed is left as-is.
    The response is 201 if any row was created, else 200.

Stable error codes emitted by this module:
  - manager_assignment_forbidden        actor role / osius gate failure
  - manager_assignment_terminal         ticket in a terminal status
  - manager_assignment_target_invalid   target is not a BUILDING_MANAGER
  - manager_not_eligible                target has no BM assignment on building
  - manager_assignment_scope_forbidden  target's BM assignment is cross-company
"""
from __future__ import annotations

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.response import Response

from accounts.models import User, UserRole
from accounts.permissions import IsAuthenticatedAndActive, is_staff_role
from accounts.permissions_v2 import user_has_osius_permission
from accounts.scoping import scope_tickets_for
from buildings.models import BuildingManagerAssignment

from .models import Ticket, TicketManagerAssignment, TicketStatus


# Sprint 10B — terminal / decided / converted tickets have left every
# operational queue and must not be made newly assignable. Mirrors the
# `_SCHEDULE_TERMINAL_STATUSES` guard in `views.py`.
_TERMINAL_STATUSES = {
    TicketStatus.APPROVED,
    TicketStatus.REJECTED,
    TicketStatus.CLOSED,
    TicketStatus.CONVERTED_TO_EXTRA_WORK,
}


class _TicketManagerAssignmentSerializer(serializers.ModelSerializer):
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
        model = TicketManagerAssignment
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
    Sprint 10B permission gate (mirror of the staff-assignment gate).
    The actor must be on the service-provider management side AND hold
    `osius.ticket.assign_staff` for the ticket's building. STAFF and
    CUSTOMER_USER never pass. Returns an error Response on failure,
    otherwise None.
    """
    if not is_staff_role(request.user):
        return Response(
            {
                "detail": "Only admins or managers can assign managers to tickets.",
                "code": "manager_assignment_forbidden",
            },
            status=status.HTTP_403_FORBIDDEN,
        )
    if request.user.role == UserRole.STAFF:
        # is_staff_role() includes STAFF (Sprint 23A) for internal-note
        # purposes. Manager assignment is an admin/manager action — not
        # a STAFF action. Checking here gives a cleaner error than a
        # generic osius-gate 403.
        return Response(
            {
                "detail": "Staff cannot assign managers to tickets.",
                "code": "manager_assignment_forbidden",
            },
            status=status.HTTP_403_FORBIDDEN,
        )
    if not user_has_osius_permission(
        request.user,
        "osius.ticket.assign_staff",
        building_id=ticket.building_id,
    ):
        return Response(
            {
                "detail": "Not allowed to assign managers for this building.",
                "code": "manager_assignment_forbidden",
            },
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


def _gate_terminal(ticket: Ticket):
    """
    A terminal / converted ticket cannot be made newly assignable.
    Returns an error Response on failure, otherwise None.
    """
    if ticket.status in {str(s) for s in _TERMINAL_STATUSES}:
        return Response(
            {
                "detail": (
                    "This ticket is in a terminal status and cannot be "
                    "assigned a manager."
                ),
                "code": "manager_assignment_terminal",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    return None


def _validate_target_manager(target: User, ticket: Ticket):
    """
    The user being assigned must hold role=BUILDING_MANAGER and have a
    `BuildingManagerAssignment` for the ticket's building. Returns an
    error Response on failure, otherwise None.
    """
    if target.role != UserRole.BUILDING_MANAGER:
        return Response(
            {
                "user_id": "Target user is not a building manager.",
                "code": "manager_assignment_target_invalid",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    if BuildingManagerAssignment.objects.filter(
        user=target, building_id=ticket.building_id
    ).exists():
        return None

    # Not eligible for THIS building. Defence-in-depth: distinguish a BM
    # whose only assignments are in ANOTHER company (cross-company —
    # `manager_assignment_scope_forbidden`) from a BM who simply is not
    # assigned to this specific building of the ticket's own company
    # (`manager_not_eligible`). The actor's own scope already limits
    # which tickets they can reach; this split is purely so an operator
    # can tell the two reject reasons apart in logs.
    has_any_assignment = BuildingManagerAssignment.objects.filter(
        user=target
    ).exists()
    has_same_company_assignment = BuildingManagerAssignment.objects.filter(
        user=target, building__company_id=ticket.company_id
    ).exists()
    if has_any_assignment and not has_same_company_assignment:
        return Response(
            {
                "user_id": (
                    "Target manager is assigned to a different "
                    "company's buildings."
                ),
                "code": "manager_assignment_scope_forbidden",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    return Response(
        {
            "user_id": (
                "Target manager is not assigned to this ticket's building."
            ),
            "code": "manager_not_eligible",
        },
        status=status.HTTP_400_BAD_REQUEST,
    )


def _requested_user_ids(request):
    """
    Accept EITHER `{"user_id": <id>}` OR `{"user_ids": [<id>, ...]}`.
    Returns (ids, error_response). `ids` is a de-duplicated list that
    preserves first-seen order.
    """
    raw_ids = request.data.get("user_ids")
    if raw_ids is None:
        single = request.data.get("user_id")
        if single is None:
            return None, Response(
                {"user_id": "This field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        raw_ids = [single]
    if not isinstance(raw_ids, (list, tuple)):
        return None, Response(
            {"user_ids": "Expected a list of user ids."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not raw_ids:
        return None, Response(
            {"user_ids": "At least one user id is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    seen = []
    for value in raw_ids:
        if value not in seen:
            seen.append(value)
    return seen, None


class TicketManagerAssignmentListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/tickets/<id>/manager-assignments/
    POST /api/tickets/<id>/manager-assignments/   {user_id} | {user_ids:[...]}
    """

    permission_classes = [IsAuthenticatedAndActive]
    serializer_class = _TicketManagerAssignmentSerializer

    def _resolve(self):
        ticket = _resolve_ticket(self.request, self.kwargs["ticket_id"])
        gate = _gate_actor(self.request, ticket)
        if gate is not None:
            return gate, None
        return None, ticket

    def get_queryset(self):
        ticket = _resolve_ticket(self.request, self.kwargs["ticket_id"])
        return (
            TicketManagerAssignment.objects.filter(ticket=ticket)
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

        terminal = _gate_terminal(ticket)
        if terminal is not None:
            return terminal

        ids, error = _requested_user_ids(request)
        if error is not None:
            return error

        # All-or-nothing validation BEFORE any write: resolve + validate
        # every target first; a single failure 400s the whole request
        # and (because we are inside @transaction.atomic and write
        # nothing before this loop completes) writes no rows.
        targets = []
        for user_id in ids:
            target = get_object_or_404(
                User, pk=user_id, is_active=True, deleted_at__isnull=True
            )
            check = _validate_target_manager(target, ticket)
            if check is not None:
                return check
            targets.append(target)

        created_rows = []
        any_created = False
        for target in targets:
            assignment, created = (
                TicketManagerAssignment.objects.get_or_create(
                    ticket=ticket,
                    user=target,
                    defaults={"assigned_by": request.user},
                )
            )
            any_created = any_created or created
            created_rows.append(assignment)

        return Response(
            self.get_serializer(created_rows, many=True).data,
            status=(
                status.HTTP_201_CREATED if any_created else status.HTTP_200_OK
            ),
        )


class TicketManagerAssignmentDeleteView(generics.GenericAPIView):
    """
    DELETE /api/tickets/<id>/manager-assignments/<user_id>/
    """

    permission_classes = [IsAuthenticatedAndActive]

    @transaction.atomic
    def delete(self, request, ticket_id, user_id):
        ticket = _resolve_ticket(request, ticket_id)
        gate = _gate_actor(request, ticket)
        if gate is not None:
            return gate
        deleted, _ = TicketManagerAssignment.objects.filter(
            ticket=ticket, user_id=user_id
        ).delete()
        if deleted == 0:
            return Response(
                {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
