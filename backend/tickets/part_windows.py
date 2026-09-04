"""W-LATE §3a — a part's window must sit inside its ticket's window.

THE TICKET'S OWN WINDOW, in one place. A ticket carries several dates
and none of them is called "the window", so this module says which:

    start  the ticket's `scheduled_start_at` (local date), else the
           earliest non-cancelled slot's start.
    end    the LATEST of the ticket's `scheduled_end_at`, the extra
           work's deadline (the promise), and the last non-cancelled
           slot's day — never before `start`.

A ticket with no `start` has no window, and a part on it may carry any
window at all: there is nothing for it to be outside of.

TWO REFUSALS, both a STABLE 400 that names the field, so the parts
modal can put the sentence under the input that caused it instead of
in a toast over a closed dialog:

    part_window_end_before_start   {"field": "planned_end_date"}
    part_window_outside_ticket     {"field": "planned_start_date" |
                                             "planned_end_date"}
"""
from __future__ import annotations

import datetime

from rest_framework import status
from rest_framework.response import Response

from .lateness_index import local_date
from .models import StaffAssignmentSlotStatus

ERR_END_BEFORE_START = "part_window_end_before_start"
ERR_OUTSIDE_TICKET = "part_window_outside_ticket"


def ticket_window(ticket) -> tuple[datetime.date | None, datetime.date | None]:
    slots = [
        s
        for s in ticket.staff_assignments.all()
        if s.slot_status != StaffAssignmentSlotStatus.CANCELLED
    ]
    slot_starts = [
        local_date(s.scheduled_start_at) for s in slots if s.scheduled_start_at
    ]
    slot_ends = [
        local_date(s.scheduled_end_at or s.scheduled_start_at)
        for s in slots
        if s.scheduled_end_at or s.scheduled_start_at
    ]
    start = local_date(ticket.scheduled_start_at)
    if start is None and slot_starts:
        start = min(slot_starts)
    if start is None:
        return None, None
    deadline = getattr(getattr(ticket, "extra_work_request", None), "deadline", None)
    ends = [
        d
        for d in (
            local_date(ticket.scheduled_end_at),
            deadline,
            max(slot_ends) if slot_ends else None,
        )
        if d is not None
    ]
    end = max(ends) if ends else start
    return start, max(start, end)


def refusal(ticket, sub_task, data: dict):
    """The 400 to answer, or None when the window is fine.

    `data` is the validated write payload; on a PATCH the instance's
    current values fill what the payload leaves out, so a part whose
    end is patched alone is still checked against its existing start.
    """
    start = data.get(
        "planned_start_date", getattr(sub_task, "planned_start_date", None)
    )
    end = data.get("planned_end_date", getattr(sub_task, "planned_end_date", None))
    if start is None and end is None:
        return None
    if start is not None and end is not None and end < start:
        return _refuse(
            ERR_END_BEFORE_START,
            "planned_end_date",
            "The part's last day is before its first day.",
        )
    window_start, window_end = ticket_window(ticket)
    if window_start is None:
        return None
    first = start if start is not None else end
    last = end if end is not None else start
    if first < window_start:
        return _refuse(
            ERR_OUTSIDE_TICKET,
            "planned_start_date",
            f"The part starts before the job's own window "
            f"({window_start.isoformat()} - {window_end.isoformat()}).",
        )
    if last > window_end:
        return _refuse(
            ERR_OUTSIDE_TICKET,
            "planned_end_date" if end is not None else "planned_start_date",
            f"The part ends after the job's own window "
            f"({window_start.isoformat()} - {window_end.isoformat()}).",
        )
    return None


def _refuse(code: str, field: str, message: str) -> Response:
    return Response(
        {"detail": message, "code": code, "field": field, field: [message]},
        status=status.HTTP_400_BAD_REQUEST,
    )


__all__ = ["ERR_END_BEFORE_START", "ERR_OUTSIDE_TICKET", "refusal", "ticket_window"]
