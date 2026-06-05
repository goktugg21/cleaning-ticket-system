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

  GET    /api/tickets/<id>/staff-assignments/                 list current rows
  POST   /api/tickets/<id>/staff-assignments/                 {user_id} → add slot
  PATCH  /api/tickets/<id>/staff-assignments/<assignment_id>/ update one slot
  DELETE /api/tickets/<id>/staff-assignments/<assignment_id>/ remove one slot

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
  - Multi-slot per staff: each POST creates a NEW slot row (`201`).
    The same staff member may hold several dated slots on one ticket
    (e.g. a 09:00-11:00 slot AND a 15:00-17:00 slot), so a re-POST is
    no longer deduplicated by user — it adds another slot.
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
from django.utils import timezone
from rest_framework import generics, serializers, status
from rest_framework.response import Response

from accounts.models import StaffProfile, User, UserRole
from accounts.permissions import IsAuthenticatedAndActive, is_staff_role
from accounts.permissions_v2 import user_has_osius_permission
from accounts.scoping import scope_tickets_for
from buildings.models import BuildingStaffVisibility
from notifications.services import send_slot_unable_to_complete_email

from .models import (
    StaffAssignmentSlotStatus,
    SubTask,
    TERMINAL_TICKET_STATUSES,
    Ticket,
    TicketStaffAssignment,
)
from .serializers import is_photo_attachment
from .sub_task_rollup import maybe_auto_complete_ticket_on_subtasks


# Sprint 14E — writable slot fields, split by who may write them.
#  * On CREATE / manager PATCH: schedule + window + note + status +
#    completion evidence.
#  * On STAFF self-PATCH: only the slot's own status + completion
#    evidence (a staff member reports their own work; they cannot
#    reschedule themselves or edit the manager's assignment note).
_MANAGER_SLOT_WRITE_FIELDS = (
    "scheduled_start_at",
    "scheduled_end_at",
    "time_window_label",
    "assignment_note",
    "slot_status",
    "completion_note",
    "unable_to_complete_reason",
    # Sprint 4 — place this slot into / out of a named SubTask on the same
    # ticket. Manager-only: a STAFF self-PATCH (status/completion only)
    # cannot retarget the slot's sub_task.
    "sub_task",
)
_STAFF_SELF_SLOT_WRITE_FIELDS = (
    "slot_status",
    "completion_note",
    "unable_to_complete_reason",
)


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

    completed_by_id = serializers.IntegerField(
        source="completed_by.id", read_only=True, default=None
    )

    class Meta:
        model = TicketStaffAssignment
        fields = [
            "id",
            "ticket",
            # Sprint 4 — the SubTask this slot is placed in (null = loose).
            "sub_task",
            "user_id",
            "user_email",
            "user_full_name",
            "assigned_by_id",
            "assigned_by_email",
            "assigned_at",
            # Sprint 14E — dated slot metadata.
            "scheduled_start_at",
            "scheduled_end_at",
            "time_window_label",
            "assignment_note",
            "slot_status",
            "completion_note",
            "completed_at",
            "completed_by_id",
            "unable_to_complete_reason",
        ]
        read_only_fields = fields


class _SlotWriteSerializer(serializers.ModelSerializer):
    """Sprint 14E — validates writable slot fields. The view chooses
    the field allow-list (manager vs staff-self) via `fields` kwarg so
    a STAFF member can only touch their own status/completion, never
    reschedule themselves or edit the manager's assignment note."""

    class Meta:
        model = TicketStaffAssignment
        fields = list(_MANAGER_SLOT_WRITE_FIELDS)

    def __init__(self, *args, allowed_fields=None, **kwargs):
        super().__init__(*args, **kwargs)
        if allowed_fields is not None:
            for name in set(self.fields) - set(allowed_fields):
                self.fields.pop(name)

    def validate(self, attrs):
        # Sprint 4 — placing a slot into a SubTask: the sub-task must belong
        # to THIS ticket, and a terminal ticket cannot accept new sub-task
        # placement. Only fires when sub_task is EXPLICITLY supplied with a
        # non-null value (a STAFF self-completion never touches it; a detach
        # to NULL is always allowed). The ticket comes from the VIEW via
        # serializer context, never from caller input.
        if attrs.get("sub_task") is not None and "sub_task" in attrs:
            ticket = self.context.get("ticket")
            sub_task = attrs["sub_task"]
            if ticket is not None:
                if sub_task.ticket_id != ticket.id:
                    raise serializers.ValidationError(
                        {"sub_task": "Sub-task does not belong to this ticket."},
                        code="sub_task_ticket_mismatch",
                    )
                if ticket.status in TERMINAL_TICKET_STATUSES:
                    raise serializers.ValidationError(
                        {
                            "sub_task": (
                                "This ticket is in a terminal status; "
                                "assignments cannot be placed into a sub-task."
                            )
                        },
                        code="sub_task_ticket_terminal",
                    )
        # Resolve the post-write status to validate completion evidence.
        new_status = attrs.get(
            "slot_status",
            getattr(self.instance, "slot_status", None),
        )
        if new_status == StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE:
            reason = attrs.get(
                "unable_to_complete_reason",
                getattr(self.instance, "unable_to_complete_reason", ""),
            )
            if not (reason or "").strip():
                raise serializers.ValidationError(
                    {
                        "unable_to_complete_reason": (
                            "A reason is required when marking a slot "
                            "unable to complete."
                        )
                    },
                    code="slot_unable_reason_required",
                )
        if new_status == StaffAssignmentSlotStatus.COMPLETED:
            # Sprint 12 — completing a slot requires evidence: a non-empty
            # completion_note OR at least one non-hidden linked PHOTO (image
            # only — a PDF does not count). The photo is linked via the
            # two-step flow: upload an attachment with staff_assignment_id,
            # then PATCH slot_status=COMPLETED. Mirrors the ticket-level
            # STAFF completion-evidence rule (state_machine.py) but on the
            # per-staff dated-slot surface, which does NOT drive the ticket
            # state machine.
            note = attrs.get(
                "completion_note",
                getattr(self.instance, "completion_note", "") or "",
            )
            has_note = bool((note or "").strip())
            # A linked photo must be a GENUINE image: both an image MIME type
            # AND an image extension (is_photo_attachment). A MIME-only check
            # would let historical bad data (proof.pdf stored as image/jpeg)
            # satisfy the gate, so verify each non-hidden linked attachment in
            # Python rather than with a mime_type__in queryset filter.
            has_photo = bool(
                self.instance is not None
                and any(
                    is_photo_attachment(att)
                    for att in self.instance.attachments.filter(is_hidden=False)
                )
            )
            if not (has_note or has_photo):
                raise serializers.ValidationError(
                    {
                        "completion_note": (
                            "Completing a slot requires a note or a photo."
                        )
                    },
                    code="completion_evidence_required",
                )
        start = attrs.get(
            "scheduled_start_at",
            getattr(self.instance, "scheduled_start_at", None),
        )
        end = attrs.get(
            "scheduled_end_at",
            getattr(self.instance, "scheduled_end_at", None),
        )
        if start and end and end < start:
            raise serializers.ValidationError(
                {
                    "scheduled_end_at": (
                        "scheduled_end_at cannot be before scheduled_start_at."
                    )
                },
                code="slot_window_invalid",
            )
        return attrs


class _MySlotSerializer(serializers.ModelSerializer):
    """Sprint 14E — STAFF agenda row: the slot plus a compact ticket
    summary so the frontend can render a card without a detail fetch."""

    ticket_id = serializers.IntegerField(source="ticket.id", read_only=True)
    ticket_no = serializers.CharField(source="ticket.ticket_no", read_only=True)
    ticket_title = serializers.CharField(source="ticket.title", read_only=True)
    ticket_status = serializers.CharField(source="ticket.status", read_only=True)
    building_id = serializers.IntegerField(
        source="ticket.building_id", read_only=True
    )
    building_name = serializers.CharField(
        source="ticket.building.name", read_only=True
    )

    class Meta:
        model = TicketStaffAssignment
        fields = [
            "id",
            "ticket_id",
            "ticket_no",
            "ticket_title",
            "ticket_status",
            "building_id",
            "building_name",
            "scheduled_start_at",
            "scheduled_end_at",
            "time_window_label",
            "assignment_note",
            "slot_status",
            "completion_note",
            "completed_at",
            "unable_to_complete_reason",
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

        # Sprint 14E — optional dated slot metadata on create. The
        # completion fields are PATCH-only (a slot is created ASSIGNED,
        # then completed later); create accepts only schedule + window
        # + note. Validated (window order) before the row is written.
        slot_ser = _SlotWriteSerializer(
            data=request.data,
            allowed_fields=(
                "scheduled_start_at",
                "scheduled_end_at",
                "time_window_label",
                "assignment_note",
                # Sprint 4 — a slot may be created directly inside a SubTask.
                "sub_task",
            ),
            context={"ticket": ticket},
        )
        slot_ser.is_valid(raise_exception=True)

        # Multi-slot per staff — every POST creates a NEW slot row, so the
        # same staff member can be added again as another dated slot
        # (Ahmet 09:00-11:00 AND Ahmet 15:00-17:00). There is no longer a
        # (ticket, user) uniqueness constraint to dedupe against, so this
        # always returns 201. A flat (no-schedule) add stays valid.
        assignment = TicketStaffAssignment.objects.create(
            ticket=ticket,
            user=target,
            assigned_by=request.user,
            **slot_ser.validated_data,
        )
        return Response(
            self.get_serializer(assignment).data,
            status=status.HTTP_201_CREATED,
        )


class TicketStaffAssignmentDetailView(generics.GenericAPIView):
    """
    PATCH  /api/tickets/<id>/staff-assignments/<assignment_id>/  update slot
    DELETE /api/tickets/<id>/staff-assignments/<assignment_id>/  remove slot

    Multi-slot per staff — the slot is addressed by its OWN id
    (`assignment_id`), not by user_id, because one staff member may hold
    several slots on the same ticket. The lookup is scoped to the ticket
    (`filter(ticket=ticket, pk=assignment_id)`), so a slot id belonging to
    another ticket resolves to 404.

    Sprint 14E — PATCH supports two actors:
      * Manager / admin (the existing `_gate_actor` gate): may edit the
        full slot (schedule, window, note, status, completion).
      * The assigned STAFF member themselves: may update only THEIR OWN
        slot's status + completion evidence (report done / unable). They
        cannot reschedule themselves, edit the manager's note, or touch
        another staff member's slot — a STAFF actor PATCHing a slot they
        do not own falls through to the manager gate and gets 403.
    DELETE stays manager/admin-only. Deleting one slot never touches a
    sibling slot on the same ticket (separate rows).
    """

    permission_classes = [IsAuthenticatedAndActive]

    @transaction.atomic
    def patch(self, request, ticket_id, assignment_id):
        ticket = _resolve_ticket(request, ticket_id)
        assignment = TicketStaffAssignment.objects.filter(
            ticket=ticket, pk=assignment_id
        ).first()
        if assignment is None:
            return Response(
                {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND
            )

        # Multi-slot per staff — the self-gate keys off the RESOLVED slot's
        # owner, not the URL. A STAFF actor may self-update only a slot they
        # own; a STAFF actor targeting another staff's slot id does NOT match
        # here, falls through to `_gate_actor`, and is rejected 403 (STAFF
        # never passes the manager gate).
        is_self_staff = (
            request.user.role == UserRole.STAFF
            and request.user.id == assignment.user_id
        )
        if is_self_staff:
            allowed = _STAFF_SELF_SLOT_WRITE_FIELDS
        else:
            gate = _gate_actor(request, ticket)
            if gate is not None:
                return gate
            allowed = _MANAGER_SLOT_WRITE_FIELDS

        ser = _SlotWriteSerializer(
            assignment,
            data=request.data,
            partial=True,
            allowed_fields=allowed,
            context={"ticket": ticket},
        )
        ser.is_valid(raise_exception=True)

        # Completion side-effects (assignment-level only — the ticket
        # state machine is NOT touched; the manager double-check flow
        # still owns ticket completion). Applied as save() kwargs so the
        # whole PATCH is ONE row write -> exactly ONE audit UPDATE row
        # (Sprint 14E audit-coverage contract), not a status row + a
        # follow-up completed_at row.
        prev_status = assignment.slot_status
        save_extra = {}
        new_status = ser.validated_data.get("slot_status", prev_status)
        if (
            new_status == StaffAssignmentSlotStatus.COMPLETED
            and assignment.completed_at is None
        ):
            save_extra = {
                "completed_at": timezone.now(),
                "completed_by": request.user,
            }
        updated = ser.save(**save_extra)

        # Sprint 12 — notify the provider/manager side when a slot is newly
        # reported unable-to-complete so a manager can reschedule / reassign.
        # The slot does NOT change ticket status, so the status-change email
        # never fires; this is the only manager signal. Only on the
        # transition INTO unable (not a re-PATCH of an already-unable slot).
        if (
            new_status == StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE
            and prev_status != StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE
        ):
            send_slot_unable_to_complete_email(
                ticket, updated, actor=request.user
            )

        # Sprint 4 — sub-task auto-complete roll-up. Fires ONLY on a genuine
        # transition INTO COMPLETED (the prev != COMPLETED edge), so a
        # re-PATCH of an already-COMPLETED slot does not re-trigger it. The
        # helper no-ops unless the ticket opted in and every sub-task (plus
        # all loose work) is done; a failed transition is logged inside the
        # helper and never blocks this slot completion (best-effort).
        if (
            new_status == StaffAssignmentSlotStatus.COMPLETED
            and prev_status != StaffAssignmentSlotStatus.COMPLETED
        ):
            maybe_auto_complete_ticket_on_subtasks(ticket, request.user)

        return Response(_TicketStaffAssignmentSerializer(updated).data)

    @transaction.atomic
    def delete(self, request, ticket_id, assignment_id):
        ticket = _resolve_ticket(request, ticket_id)
        gate = _gate_actor(request, ticket)
        if gate is not None:
            return gate
        # Multi-slot per staff — delete ONLY the addressed slot (by id,
        # scoped to the ticket). Sibling slots for the same staff survive.
        deleted, _ = TicketStaffAssignment.objects.filter(
            ticket=ticket, pk=assignment_id
        ).delete()
        if deleted == 0:
            return Response(
                {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class StaffAssignmentSlotAgendaView(generics.ListAPIView):
    """
    GET /api/tickets/my-slots/

    Sprint 14E — the caller's OWN dated assignment slots (the staff
    agenda the transcript asks for: "each staff sees their own assigned
    dated job"). Returns one row per `TicketStaffAssignment` the caller
    holds, ordered by scheduled start, with a compact ticket summary so
    the frontend renders cards without a per-ticket detail fetch.

    Inherently caller-scoped: a user only ever has assignment rows on
    tickets they were assigned to, so there is no cross-tenant surface.
    Soft-deleted tickets are filtered out. A manager/admin who wants to
    see ALL slots on a ticket uses
    `GET /api/tickets/<id>/staff-assignments/`.
    """

    permission_classes = [IsAuthenticatedAndActive]
    serializer_class = _MySlotSerializer

    def get_queryset(self):
        return (
            TicketStaffAssignment.objects.filter(
                user=self.request.user,
                ticket__deleted_at__isnull=True,
            )
            .select_related("ticket", "ticket__building")
            .order_by("scheduled_start_at", "id")
        )


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
