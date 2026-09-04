"""P-6 V4 — stale-work triage: park or close MANY tickets with ONE reason.

The "Not planned yet" drawer on My schedule is where junk collects —
test tickets, duplicates, work a customer called off by phone. This
endpoint lets provider management clear several at once, and it does
so ONLY through the transitions that already exist:

* ``park``  — the ticket ends ON_HOLD by walking the machine's own
  legs: OPEN -> ACKNOWLEDGED -> ON_HOLD, ACKNOWLEDGED -> ON_HOLD, or
  IN_PROGRESS -> ON_HOLD. Every leg is ``apply_transition`` with the
  reason as its note, so each writes its own history row.
* ``close`` — APPROVED -> CLOSED is the machine's own leg. Any other
  source status is an out-of-machine jump, which ``can_transition``
  allows to a SUPER_ADMIN only and ``apply_transition`` records as an
  override (``is_override`` + ``override_reason``) — the same audit
  trail the ticket detail's "Geavanceerd" fold leaves.

PER-ITEM semantics, like ``bulk_status``: an out-of-scope id is
``not_found``, a ticket with no legal path is ``no_path``, and one
refusal never aborts the batch. Always HTTP 200 with a breakdown.
"""
from __future__ import annotations

from django.db import transaction
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAuthenticatedAndActive, is_provider_management_role
from accounts.scoping import scope_tickets_for
from notifications.services import send_ticket_status_changed_email

from .models import TicketStatus
from .state_machine import TransitionError, apply_transition, can_transition

# The machine's own way to ON_HOLD from each status that has one.
PARK_PATHS = {
    str(TicketStatus.OPEN): [TicketStatus.ACKNOWLEDGED, TicketStatus.ON_HOLD],
    str(TicketStatus.ACKNOWLEDGED): [TicketStatus.ON_HOLD],
    str(TicketStatus.IN_PROGRESS): [TicketStatus.ON_HOLD],
}

ACTION_PARK = "park"
ACTION_CLOSE = "close"


class TicketBulkTriageSerializer(serializers.Serializer):
    ticket_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        max_length=200,
    )
    action = serializers.ChoiceField(choices=[ACTION_PARK, ACTION_CLOSE])
    reason = serializers.CharField(allow_blank=False, max_length=2000)

    def validate_ticket_ids(self, value):
        seen = set()
        ordered = []
        for ticket_id in value:
            if ticket_id not in seen:
                seen.add(ticket_id)
                ordered.append(ticket_id)
        return ordered

    def validate_reason(self, value):
        stripped = value.strip()
        if not stripped:
            raise serializers.ValidationError("A reason is required.")
        return stripped


def _park(ticket, user, reason):
    path = PARK_PATHS.get(str(ticket.status))
    if str(ticket.status) == str(TicketStatus.ON_HOLD):
        raise TransitionError("Already parked.", code="already_parked")
    if path is None:
        raise TransitionError("No path to ON_HOLD from this status.", code="no_path")
    updated = ticket
    with transaction.atomic():
        for step in path:
            updated = apply_transition(updated, user, step, note=reason)
    return updated


def _close(ticket, user, reason):
    if str(ticket.status) == str(TicketStatus.CLOSED):
        raise TransitionError("Already closed.", code="already_closed")
    with transaction.atomic():
        if str(ticket.status) == str(TicketStatus.APPROVED):
            return apply_transition(ticket, user, TicketStatus.CLOSED, note=reason)
        if not can_transition(user, ticket, TicketStatus.CLOSED):
            raise TransitionError("No path to CLOSED from this status.", code="no_path")
        return apply_transition(
            ticket,
            user,
            TicketStatus.CLOSED,
            note=reason,
            is_override=True,
            override_reason=reason,
        )


class TicketBulkTriageView(APIView):
    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request, *args, **kwargs):
        if not is_provider_management_role(request.user):
            return Response(
                {"detail": "Only provider management can triage tickets in bulk."},
                status=status.HTTP_403_FORBIDDEN,
            )
        payload = TicketBulkTriageSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        ticket_ids = payload.validated_data["ticket_ids"]
        action = payload.validated_data["action"]
        reason = payload.validated_data["reason"]

        scoped = {
            ticket.id: ticket
            for ticket in scope_tickets_for(request.user).filter(pk__in=ticket_ids)
        }
        results = []
        succeeded = 0
        failed = 0
        for ticket_id in ticket_ids:
            ticket = scoped.get(ticket_id)
            if ticket is None:
                results.append({"id": ticket_id, "ok": False, "error": "not_found"})
                failed += 1
                continue
            old_status = ticket.status
            try:
                updated = (_park if action == ACTION_PARK else _close)(
                    ticket, request.user, reason
                )
            except TransitionError as exc:
                results.append({"id": ticket_id, "ok": False, "error": exc.code})
                failed += 1
                continue
            send_ticket_status_changed_email(
                updated,
                old_status=old_status,
                new_status=updated.status,
                actor=request.user,
                is_admin_override=action == ACTION_CLOSE
                and str(old_status) != str(TicketStatus.APPROVED),
            )
            results.append({"id": ticket_id, "ok": True, "status": str(updated.status)})
            succeeded += 1
        return Response(
            {"succeeded": succeeded, "failed": failed, "results": results},
            status=status.HTTP_200_OK,
        )
