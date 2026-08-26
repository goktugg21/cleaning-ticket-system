"""
Sprint 158 §1 — the same bulk assign/unassign surface tickets' extra-work
sibling got in Sprint 157.

    POST /api/tickets/bulk-assign/
    Body: {"tickets": [id,...], "users": [id,...],
           "role": "WORKER"|"MANAGER", "mode": "assign"|"unassign"}
      or: {"tickets": [id,...], "workers": [id,...],
           "managers": [id,...], "mode": "assign"|"unassign"}
    Response: {"created": N, "removed": N,
               "already_assigned": N, "not_assigned": N}

Sprint 159 §2 — the second shape puts BOTH roles in one request, so
staffing a job is one confirm and one transaction rather than two of
each with a half-crew state in between.

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

from . import crew_sync
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
    """Sprint 159 §2 — managers AND workers in ONE request.

    Same two accepted shapes as the extra-work sibling, for the same
    reason: the owner wants one dialog and one confirm to staff a job,
    and the Sprint 158 shape stays working so nothing that already
    speaks it breaks.
    """

    tickets = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False
    )
    users = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False
    )
    role = serializers.ChoiceField(
        choices=[ROLE_WORKER, ROLE_MANAGER], required=False
    )
    workers = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False
    )
    managers = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False
    )
    mode = serializers.ChoiceField(
        choices=["assign", "unassign"], default="assign"
    )

    def validate(self, attrs):
        groups: dict[str, list[int]] = {}

        def add(role: str, ids) -> None:
            if not ids:
                return
            merged = groups.setdefault(role, [])
            merged.extend(i for i in ids if i not in merged)

        add(attrs.get("role") or ROLE_WORKER, attrs.get("users"))
        add(ROLE_WORKER, attrs.get("workers"))
        add(ROLE_MANAGER, attrs.get("managers"))

        if not groups:
            raise serializers.ValidationError(
                {"users": ["Name at least one person to assign."]}
            )
        attrs["groups"] = groups
        return attrs


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
        groups: dict[str, list[int]] = payload.validated_data["groups"]
        mode = payload.validated_data["mode"]

        tickets = {
            t.id: t
            for t in scope_tickets_for(request.user).filter(id__in=ticket_ids)
        }
        if len(tickets) != len(ticket_ids):
            _reject()

        # Eligibility is a property of each TICKET's building and differs
        # per role, so it is resolved per (ticket, role) rather than once
        # for the batch. Assigning one person across two buildings
        # therefore requires them to be authorised at both.
        #
        # Sprint 159 §2 — every group resolves BEFORE any write, so a
        # body naming both roles is still all-or-nothing.
        pairs = []
        for ticket in tickets.values():
            for role, user_ids in groups.items():
                eligible = resolve_assignable_users(
                    ticket.building, role, user_ids, request.user
                )
                if len(eligible) != len(user_ids):
                    _reject()
                for user in eligible.values():
                    pairs.append((ticket, user, role))

        try:
            audit_context.set_current_reason(
                f"ticket_bulk_{mode}_"
                + "_".join(sorted(role.lower() for role in groups))
            )
        except Exception:  # pragma: no cover - defensive
            pass

        created = removed = already = not_assigned = 0
        with transaction.atomic():
            for ticket, user, role in pairs:
                model = (
                    TicketManagerAssignment
                    if role == ROLE_MANAGER
                    else TicketStaffAssignment
                )
                existing = model.objects.filter(
                    ticket=ticket, user=user
                ).first()
                if mode == "assign":
                    # W26.3 — for STAFF the blocking question is "does
                    # this person hold a BASE slot here", the same level
                    # `staff_already_assigned` now asks, because this
                    # path creates base slots. Asking it of ANY row (as
                    # W26 did) would count someone who holds only a part
                    # slot as already-assigned and leave them filed under
                    # a part of a job they are not on — the state rule
                    # (c) exists to prevent. Managers have no parts, so
                    # for them any row is the answer.
                    if model is TicketStaffAssignment:
                        blocked = model.objects.filter(
                            ticket=ticket, user=user, sub_task__isnull=True
                        ).exists()
                    else:
                        blocked = existing is not None
                    if blocked:
                        # It stays a COUNTER here rather than a 400: this
                        # endpoint's contract is a per-pair tally over a
                        # batch of tickets (`already_assigned` is a
                        # documented response field every caller reads),
                        # and it creates no duplicate either way.
                        already += 1
                        continue
                    model.objects.create(
                        ticket=ticket, user=user, assigned_by=request.user
                    )
                    created += 1
                    # W-FIX1 C1 (audit F25) — the bulk door mirrors to
                    # the extra work like the per-slot door does, so a
                    # person put on a spawned ticket here can be planned.
                    if model is TicketStaffAssignment:
                        crew_sync.worker_added(ticket, user, actor=request.user)
                    else:
                        crew_sync.manager_added(ticket, user, actor=request.user)
                else:
                    if existing is None:
                        not_assigned += 1
                        continue
                    # Every matching row, because a staff member may hold
                    # several slots on one ticket and "unassign this
                    # person" means all of them, not the oldest. W26.3:
                    # that is already the base-slot cascade the per-slot
                    # DELETE performs — base row and its part rows go
                    # together — so this branch needed no change.
                    for row in model.objects.filter(ticket=ticket, user=user):
                        row.delete()
                        removed += 1
                    # W-FIX1 C1 — and the mirror on the way out: the
                    # person's open plan goes with their last slot.
                    if model is TicketStaffAssignment:
                        crew_sync.worker_removed(ticket, user.id)
                    else:
                        crew_sync.manager_removed(ticket, user.id)

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
