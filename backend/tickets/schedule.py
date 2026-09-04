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

import datetime

from django.db import transaction

from .models import (
    StaffAssignmentSlotStatus,
    TicketScheduleStatus,
    TicketStaffAssignment,
    TicketStatusHistory,
)
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
    apply_to_slots: bool = True,
) -> str:
    """Set or move the ticket's schedule. Returns the history action
    written: `"set"` on first scheduling, `"rescheduled"` after.

    Raises `ScheduleError("reschedule_reason_required")` when the ticket
    already has a schedule and no reason was given — the rule the
    schedule endpoint has enforced since Sprint 9B, now enforced for
    every door.

    P-9 ruling 12(e) — `apply_to_slots` defaults to TRUE on every door:
    one plan, one date. A caller that wants the job's date moved without
    its people's days passes False explicitly.

    W-PLANTRUTH §1a — `apply_to_slots`. The owner's ruling is that the
    ticket-level schedule is a different fact from the planned day of
    the WORK (the slots' days), and only the latter places a card on the
    Work Plan. So a door that means "move the job to this day" — the
    board's "Plan for today" and "Reschedule", the schedule card when
    the operator ticks it — passes `apply_to_slots=True`, and every
    PENDING slot on the ticket (ASSIGNED, base or part) is moved onto the
    same window: the two facts are written together by the one door,
    rather than one being read as if it were the other. Completed,
    unable and cancelled slots are history and are not touched. The
    slot writes go through `save()` so the audit receivers fire per row.
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

        moved = 0
        if apply_to_slots:
            moved = move_pending_slots(
                ticket,
                scheduled_start_at=scheduled_start_at,
                scheduled_end_at=scheduled_end_at,
                time_window_label=time_window_label or "",
            )
        mirror_window_onto_extra_work(
            ticket,
            scheduled_start_at=scheduled_start_at,
            scheduled_end_at=scheduled_end_at,
        )

        note = compose_schedule_note(
            action=history_action,
            old_start=old_start,
            new_start=ticket.scheduled_start_at,
            window_label=ticket.time_window_label,
            reason=reason,
        )
        if moved:
            note = f"{note} {moved} planned slot(s) moved with it."

        # Sprint 8B annotation-row pattern: old_status == new_status
        # == ticket.status; is_override=False. This IS the audit
        # trail for the schedule change (no generic AuditLog row).
        TicketStatusHistory.objects.create(
            ticket=ticket,
            old_status=ticket.status,
            new_status=ticket.status,
            changed_by=actor,
            note=note,
            is_override=False,
            override_reason="",
        )
    return history_action


def mirror_window_onto_extra_work(
    ticket,
    *,
    scheduled_start_at: datetime.datetime,
    scheduled_end_at: datetime.datetime | None,
) -> bool:
    """P-5 S1 — ONE PLAN, ONE DATE: the ticket's window IS the
    meerwerk's committed window, seen from the other end.

    `extra_work/dates.py` already pushes `provider_planned_date` onto
    the spawned tickets (Sprint 184 §1). This is the missing half: a
    start set on the TICKET — the transition modal's "When does it
    start?", the schedule card, the board's reschedule — lands on the
    meerwerk too, so the plan tab never shows a ticket start beside a
    different "committed" window (TCK-2026-000385: 10 Sep on the ticket,
    11–25 Oct on the meerwerk, one job).

    The days are the LOCAL calendar days of the instants. The end: the
    ticket's end when it has one; else the meerwerk's own end when it
    still lies after the new start (the plan modal keeps a last work
    day the operator chose — P-4 (2)); else none. Only the two window
    fields are written, straight onto the row: the ticket's own history
    row already records who moved what, and the meerwerk's tracked
    fields are audited by `audit.signals`. Never pushed back onto the
    other spawned tickets — this door moves ONE job.

    Returns True when the meerwerk changed.
    """
    extra_work = getattr(ticket, "extra_work_request", None)
    if extra_work is None:
        return False
    from django.utils import timezone

    start_day = timezone.localtime(scheduled_start_at).date()
    if scheduled_end_at is not None:
        end_day = timezone.localtime(scheduled_end_at).date()
    else:
        kept = extra_work.provider_planned_end_date
        end_day = kept if kept is not None and kept > start_day else None
    if end_day is not None and end_day <= start_day:
        end_day = None
    if (
        extra_work.provider_planned_date == start_day
        and extra_work.provider_planned_end_date == end_day
    ):
        return False
    extra_work.provider_planned_date = start_day
    extra_work.provider_planned_end_date = end_day
    extra_work.save(
        update_fields=[
            "provider_planned_date",
            "provider_planned_end_date",
            "updated_at",
        ]
    )
    return True


def move_pending_slots(
    ticket,
    *,
    scheduled_start_at: datetime.datetime,
    scheduled_end_at: datetime.datetime | None,
    time_window_label: str = "",
) -> int:
    """Put every PENDING slot of `ticket` on the given window. Returns
    how many rows changed. See `set_schedule` for why this exists."""
    moved = 0
    for slot in TicketStaffAssignment.objects.filter(
        ticket=ticket, slot_status=StaffAssignmentSlotStatus.ASSIGNED
    ).order_by("id"):
        if (
            slot.scheduled_start_at == scheduled_start_at
            and slot.scheduled_end_at == scheduled_end_at
            and (slot.time_window_label or "") == (time_window_label or "")
        ):
            continue
        slot.scheduled_start_at = scheduled_start_at
        slot.scheduled_end_at = scheduled_end_at
        slot.time_window_label = time_window_label or ""
        slot.save(
            update_fields=[
                "scheduled_start_at",
                "scheduled_end_at",
                "time_window_label",
            ]
        )
        moved += 1
    return moved
