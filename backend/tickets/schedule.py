"""W-FIX1 B2 (audit F24) — ONE writer for a ticket's schedule.

`POST /api/tickets/<id>/schedule/` wrote the whole fact: the start, the
end, the window label, `schedule_status`, `rescheduled_from`, the
reschedule reason and the `TicketStatusHistory` annotation row that IS
the audit trail of the change (Sprint 9B). The transition modal's
convenience path (`TicketStatusChangeSerializer._apply_transition_
answers`) wrote `scheduled_start_at` and nothing else — so a ticket
scheduled from "Mark as seen and planned" carried a date, read
UNSCHEDULED, and had no row saying who set it or when. Measured on
crmtest: ticket 373 was SCHEDULED with `schedule_planned_by_name:
null`.

Both doors now call `set_schedule`. The view keeps its role and scope
gates and its input serializer; the side door keeps the same gates it
already ran. What they share is the write, which is the part that must
not have two shapes.
"""
from __future__ import annotations

from django.db import transaction

from .models import TicketScheduleStatus, TicketStatusHistory
from .schedule_history import compose_schedule_note


class ScheduleError(Exception):
    """A schedule write the rule refuses. `code` is the stable API code
    the two doors already publish; `detail` is the sentence."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def set_schedule(
    ticket,
    *,
    actor,
    scheduled_start_at,
    scheduled_end_at=None,
    time_window_label: str = "",
    reschedule_reason: str = "",
) -> str:
    """Set or move the ticket's schedule. Returns the history action
    written: `"set"` on first scheduling, `"rescheduled"` after.

    Raises `ScheduleError("reschedule_reason_required")` when the ticket
    already has a schedule and no reason was given — the rule the
    schedule endpoint has enforced since Sprint 9B, now enforced for
    every door.
    """
    old_start = ticket.scheduled_start_at
    is_reschedule = ticket.schedule_status != TicketScheduleStatus.UNSCHEDULED
    reason = (reschedule_reason or "").strip()

    if is_reschedule and not reason:
        raise ScheduleError(
            "reschedule_reason_required",
            "A reschedule reason is required when changing an existing "
            "schedule.",
        )

    with transaction.atomic():
        ticket.scheduled_start_at = scheduled_start_at
        ticket.scheduled_end_at = scheduled_end_at
        ticket.time_window_label = time_window_label or ""
        if is_reschedule:
            ticket.schedule_status = TicketScheduleStatus.RESCHEDULED
            ticket.rescheduled_from = old_start
            ticket.reschedule_reason = reason
            history_action = "rescheduled"
        else:
            ticket.schedule_status = TicketScheduleStatus.SCHEDULED
            # First scheduling leaves rescheduled_from /
            # reschedule_reason empty.
            ticket.rescheduled_from = None
            ticket.reschedule_reason = ""
            history_action = "set"

        # Explicit update_fields EXCLUDES `status` so the SLA
        # post_save signal sees no status change.
        ticket.save(
            update_fields=[
                "scheduled_start_at",
                "scheduled_end_at",
                "time_window_label",
                "schedule_status",
                "rescheduled_from",
                "reschedule_reason",
                "updated_at",
            ]
        )

        # Sprint 8B annotation-row pattern: old_status == new_status
        # == ticket.status; is_override=False. This IS the audit
        # trail for the schedule change (no generic AuditLog row).
        TicketStatusHistory.objects.create(
            ticket=ticket,
            old_status=ticket.status,
            new_status=ticket.status,
            changed_by=actor,
            note=compose_schedule_note(
                action=history_action,
                old_start=old_start,
                new_start=ticket.scheduled_start_at,
                window_label=ticket.time_window_label,
                reason=reason,
            ),
            is_override=False,
            override_reason="",
        )
    return history_action
