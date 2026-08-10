"""
Sprint 158 §1 — the same bulk assign/unassign surface tickets' extra-work
sibling got in Sprint 157.

    POST /api/tickets/bulk-assign/
    Body: {"tickets": [id,...], "users": [id,...],
           "role": "WORKER"|"MANAGER", "mode": "assign"|"unassign"}
    Response: {"created": N, "removed": N,
               "already_assigned": N, "not_assigned": N}

    GET  /api/tickets/<id>/assignments/candidates/?role=WORKER|MANAGER

Same SHAPE as `extra_work.views_assignments`, same eligibility rule from
`buildings.assignment_eligibility`, and nothing imported from
`extra_work` — the shared part is the building rule, which is why it
lives in `buildings/` and not in either consumer.

The models are the ones that already existed:

  WORKER  -> `TicketStaffAssignment`
  MANAGER -> `TicketManagerAssignment`

**`TicketStaffAssignment` is not a plain link and that matters here.**
Since Sprint 14E each row is a dated operational SLOT — it carries
`scheduled_start_at`, `time_window_label`, a slot status and completion
evidence, and the SAME staff member may hold several slots on one ticket
(which is why its `unique_together` was dropped). A bulk assign therefore
creates ONE unscheduled slot per (ticket, user) pair and refuses to make
a second, because "assign these six people to these three tickets" means
one slot each, not an extra slot every time the button is pressed. The
detail page's own slot editor stays the way to add a second, scheduled
slot; this endpoint deliberately does not.

Everything else is the Sprint 154/157 discipline, unchanged: every id
resolved before any write, one `transaction.atomic()`, real
`objects.create()` / instance `.delete()` so the audit rows are written
(H-10), and one constant rejection body so an ineligible id and a
fictional one are indistinguishable (H-1).
"""
from __future__ import annotations

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRole
from accounts.permissions import IsAuthenticatedAndActive
from accounts.scoping import scope_tickets_for
from audit import context as audit_context
from buildings.assignment_eligibility import (
    ROLE_MANAGER,
    ROLE_WORKER,
    eligible_users_for_building,
    resolve_assignable_users,
)

from .models import TicketManagerAssignment, TicketStaffAssignment


ERR_TICKET_BULK_ASSIGN_INVALID = "ticket_bulk_assign_invalid"

_INVALID_MESSAGE = (
    "One or more of the selected tickets or people could not be "
    "resolved, or cannot be assigned to each other. Nothing was changed."
)

_ASSIGNER_ROLES = {
    UserRole.SUPER_ADMIN,
    UserRole.COMPANY_ADMIN,
    UserRole.BUILDING_MANAGER,
}


def _reject():
    raise serializers.ValidationError(
        {
            "detail": [
                serializers.ErrorDetail(
                    _INVALID_MESSAGE, code=ERR_TICKET_BULK_ASSIGN_INVALID
                )
            ]
        }
    )


class _TicketBulkAssignInputSerializer(serializers.Serializer):
    tickets = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False
    )
    users = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False
    )
    role = serializers.ChoiceField(choices=[ROLE_WORKER, ROLE_MANAGER])
    mode = serializers.ChoiceField(
        choices=["assign", "unassign"], default="assign"
    )


class TicketBulkAssignView(APIView):
    """POST /api/tickets/bulk-assign/ — see the module docstring."""

    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request, *args, **kwargs):
        if request.user.role not in _ASSIGNER_ROLES:
            return Response(
                {"detail": "You may not assign people to tickets."},
                status=status.HTTP_403_FORBIDDEN,
            )

        payload = _TicketBulkAssignInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        ticket_ids = list(dict.fromkeys(payload.validated_data["tickets"]))
        user_ids = list(dict.fromkeys(payload.validated_data["users"]))
        role = payload.validated_data["role"]
        mode = payload.validated_data["mode"]

        tickets = {
            t.id: t
            for t in scope_tickets_for(request.user).filter(id__in=ticket_ids)
        }
        if len(tickets) != len(ticket_ids):
            _reject()

        # Eligibility is a property of each TICKET's building, so it is
        # resolved per ticket rather than once for the batch. Assigning
        # one person across two buildings therefore requires them to be
        # authorised at both.
        pairs = []
        for ticket in tickets.values():
            eligible = resolve_assignable_users(
                ticket.building, role, user_ids, request.user
            )
            if len(eligible) != len(user_ids):
                _reject()
            for user in eligible.values():
                pairs.append((ticket, user))

        try:
            audit_context.set_current_reason(
                f"ticket_bulk_{mode}_{role.lower()}"
            )
        except Exception:  # pragma: no cover - defensive
            pass

        model = (
            TicketManagerAssignment
            if role == ROLE_MANAGER
            else TicketStaffAssignment
        )

        created = removed = already = not_assigned = 0
        with transaction.atomic():
            for ticket, user in pairs:
                existing = model.objects.filter(
                    ticket=ticket, user=user
                ).first()
                if mode == "assign":
                    if existing is not None:
                        # For staff this means "already has a slot here".
                        # See the module docstring: this endpoint makes
                        # one slot per pair, never a second.
                        already += 1
                        continue
                    model.objects.create(
                        ticket=ticket, user=user, assigned_by=request.user
                    )
                    created += 1
                else:
                    if existing is None:
                        not_assigned += 1
                        continue
                    # Every matching row, because a staff member may hold
                    # several slots on one ticket and "unassign this
                    # person" means all of them, not the oldest.
                    for row in model.objects.filter(ticket=ticket, user=user):
                        row.delete()
                        removed += 1

        return Response(
            {
                "created": created,
                "removed": removed,
                "already_assigned": already,
                "not_assigned": not_assigned,
            },
            status=status.HTTP_200_OK,
        )


class TicketAssignableUsersView(APIView):
    """GET /api/tickets/<id>/assignments/candidates/?role=…

    The picker's source and the write validator's source are the same
    helper, so "offerable" and "acceptable" cannot disagree.
    """

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, pk: int, *args, **kwargs):
        if request.user.role not in _ASSIGNER_ROLES:
            return Response(
                {"detail": "You may not assign people to tickets."},
                status=status.HTTP_403_FORBIDDEN,
            )
        role = request.query_params.get("role", ROLE_WORKER)
        if role not in (ROLE_WORKER, ROLE_MANAGER):
            raise serializers.ValidationError(
                {"role": ["Unknown assignment role."]}
            )
        ticket = get_object_or_404(scope_tickets_for(request.user), pk=pk)
        users = eligible_users_for_building(ticket.building, role, request.user)
        return Response(
            [
                {
                    "id": user.id,
                    "email": user.email,
                    "full_name": user.full_name,
                    "role": user.role,
                }
                for user in users
            ],
            status=status.HTTP_200_OK,
        )
