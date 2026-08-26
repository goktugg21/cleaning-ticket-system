"""
Sprint 4 — SubTask CRUD nested under a ticket.

Mirrors the staff-assignment endpoints' shape (explicit `generics` views +
the SAME `_resolve_ticket` / `_gate_actor` gate, reused verbatim): the
roles/scope that may already assign staff to a ticket are exactly the roles
that may CRUD its sub-tasks (SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER
holding `osius.ticket.assign_staff` for the ticket's building; STAFF +
customer roles -> 403). Cross-tenant / cross-building tickets resolve to 404
through `scope_tickets_for` (H-1/H-2), never a 403 leak.

  GET    /api/tickets/<id>/sub-tasks/            list
  POST   /api/tickets/<id>/sub-tasks/            {title, description?, ordering?}
  GET    /api/tickets/<id>/sub-tasks/<sid>/      retrieve
  PATCH  /api/tickets/<id>/sub-tasks/<sid>/      update (title / description / ordering)
  DELETE /api/tickets/<id>/sub-tasks/<sid>/      delete (SET_NULLs its slots)

Mutations (create / patch / delete) are blocked on a TERMINAL ticket,
mirroring the schedule control's terminal-guard set.
"""
from __future__ import annotations

from django.db import transaction

from rest_framework import generics, status
from rest_framework.response import Response

from accounts.permissions import IsAuthenticatedAndActive

from . import part_windows
from .models import SubTask, TERMINAL_TICKET_STATUSES, TicketStaffAssignment
from .serializers import SubTaskSerializer, SubTaskWriteSerializer
from .views_staff_assignments import _gate_actor, _resolve_ticket


def _terminal_guard(ticket):
    """Block sub-task mutation on a terminal ticket (mirrors the schedule
    control's `_SCHEDULE_TERMINAL_STATUSES` guard). Returns a 400 Response
    or None."""
    if ticket.status in TERMINAL_TICKET_STATUSES:
        return Response(
            {
                "detail": (
                    "This ticket is in a terminal status; its sub-tasks "
                    "cannot be changed."
                ),
                "code": "sub_task_not_allowed_terminal",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    return None


def _subtask_queryset(ticket):
    return (
        SubTask.objects.filter(ticket=ticket)
        .select_related("created_by")
        .prefetch_related("staff_assignments", "staff_assignments__user")
        .order_by("ordering", "id")
    )


class TicketSubTaskListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/tickets/<id>/sub-tasks/
    POST /api/tickets/<id>/sub-tasks/
    """

    permission_classes = [IsAuthenticatedAndActive]
    serializer_class = SubTaskSerializer

    def _resolve(self):
        ticket = _resolve_ticket(self.request, self.kwargs["ticket_id"])
        gate = _gate_actor(self.request, ticket)
        if gate is not None:
            return gate, None
        return None, ticket

    def get_queryset(self):
        ticket = _resolve_ticket(self.request, self.kwargs["ticket_id"])
        return _subtask_queryset(ticket)

    def list(self, request, *args, **kwargs):
        early, _ = self._resolve()
        if early is not None:
            return early
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        early, ticket = self._resolve()
        if early is not None:
            return early
        terminal = _terminal_guard(ticket)
        if terminal is not None:
            return terminal
        write = SubTaskWriteSerializer(data=request.data)
        write.is_valid(raise_exception=True)
        # W-LATE §3a — the window rules, answered at the field.
        refused = part_windows.refusal(ticket, None, write.validated_data)
        if refused is not None:
            return refused
        sub_task = SubTask.objects.create(
            ticket=ticket,
            created_by=request.user,
            **write.validated_data,
        )
        return Response(
            SubTaskSerializer(sub_task).data,
            status=status.HTTP_201_CREATED,
        )


class TicketSubTaskDetailView(generics.GenericAPIView):
    """
    GET    /api/tickets/<id>/sub-tasks/<sid>/
    PATCH  /api/tickets/<id>/sub-tasks/<sid>/
    DELETE /api/tickets/<id>/sub-tasks/<sid>/

    Keyed by the SubTask's OWN id, scoped to the ticket
    (`filter(ticket=ticket, pk=sub_task_id)`), so a sub-task id from another
    ticket resolves to 404.
    """

    permission_classes = [IsAuthenticatedAndActive]

    def _resolve(self, ticket_id, sub_task_id):
        ticket = _resolve_ticket(self.request, ticket_id)
        gate = _gate_actor(self.request, ticket)
        if gate is not None:
            return gate, None, None
        sub_task = (
            _subtask_queryset(ticket).filter(pk=sub_task_id).first()
        )
        if sub_task is None:
            return (
                Response(
                    {"detail": "Not found."},
                    status=status.HTTP_404_NOT_FOUND,
                ),
                None,
                None,
            )
        return None, ticket, sub_task

    def get(self, request, ticket_id, sub_task_id):
        early, _, sub_task = self._resolve(ticket_id, sub_task_id)
        if early is not None:
            return early
        return Response(SubTaskSerializer(sub_task).data)

    def patch(self, request, ticket_id, sub_task_id):
        early, ticket, sub_task = self._resolve(ticket_id, sub_task_id)
        if early is not None:
            return early
        terminal = _terminal_guard(ticket)
        if terminal is not None:
            return terminal
        write = SubTaskWriteSerializer(sub_task, data=request.data, partial=True)
        write.is_valid(raise_exception=True)
        refused = part_windows.refusal(ticket, sub_task, write.validated_data)
        if refused is not None:
            return refused
        write.save()
        sub_task.refresh_from_db()
        return Response(SubTaskSerializer(sub_task).data)

    @transaction.atomic
    def delete(self, request, ticket_id, sub_task_id):
        early, ticket, sub_task = self._resolve(ticket_id, sub_task_id)
        if early is not None:
            return early
        terminal = _terminal_guard(ticket)
        if terminal is not None:
            return terminal
        # W26.3 — the FK is `on_delete=SET_NULL`, and under the new model
        # that alone would MINT DUPLICATE BASE SLOTS rather than tidy up.
        #
        # A NULL sub_task is not "the loose pool" any more, it is the
        # person's one base slot on the job. Rule (c) says every part
        # slot sits alongside a base slot for the same person, so under
        # W26.3 the SET_NULL is not an edge case: for every current part
        # slot it turns that row into a SECOND base slot for someone who
        # already has one — the "Ahmet twice" state, arriving through a
        # path that never passes the chokepoint.
        #
        # So the part's slots are removed HERE, for the people who hold a
        # base slot — they stay on the job through that base slot, the
        # part they were filed under is simply gone. Slots whose owner
        # has NO base slot (legacy rows predating W26.3) are left to the
        # FK and still fall back to the loose pool exactly as before, so
        # old data keeps its old behaviour and cannot gain a duplicate.
        base_holder_ids = list(
            TicketStaffAssignment.objects.filter(
                ticket=ticket, sub_task__isnull=True
            ).values_list("user_id", flat=True)
        )
        TicketStaffAssignment.objects.filter(
            ticket=ticket, sub_task=sub_task, user_id__in=base_holder_ids
        ).delete()
        sub_task.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
