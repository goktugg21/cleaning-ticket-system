"""
FE-3 (Addendum D §D.4 / §D.11) — the two facts the ticket detail's fact
block needs and no serializer carried: WHAT KIND of work this is, and
HOW IT STANDS against its due date.

Presentation only, like `display_phase`: computed, never stored (zero
migrations), never writable, never read by backend logic. Both are
derived from rows the detail serializer already loads.

  kind          MELDING   a customer's own report
                MEERWERK  the execution of an extra work (has a parent)
                TICKET    any other provider-created work
                The §D.4 enum — "Chargeable work" is not a noun here, it
                is the same meerwerk in its execution phase.

  due           The date that decides late, exactly as the Werkplanning
                places cards (`tickets/job_dates.py::job_due`): the extra
                work's real deadline when one exists, otherwise the last
                planned day. `due_kind` says which of the two it is, so a
                planned day is never captioned "deadline" (§D.11 G3).
                `days_until_due` is signed and whole — days left when
                positive, days over when negative, today at zero — and
                None once the work is over (a finished job is not late).
"""
from __future__ import annotations

import datetime

from accounts.models import UserRole

from .job_dates import job_deadline, job_due
from .lateness_index import LATE_LIVE_TICKET_STATUSES

KIND_MELDING = "MELDING"
KIND_MEERWERK = "MEERWERK"
KIND_TICKET = "TICKET"
TICKET_KINDS = frozenset({KIND_MELDING, KIND_MEERWERK, KIND_TICKET})

DUE_KIND_DEADLINE = "DEADLINE"
DUE_KIND_PLANNED_DAY = "PLANNED_DAY"


def ticket_kind(ticket) -> str:
    """The kind, from the parent link and the author's role.

    The three spawn paths `resolve_extra_work_origin_core` walks all set
    one of these FKs, and the ids are on the row, so this costs no query.
    """
    if (
        ticket.extra_work_request_id is not None
        or ticket.proposal_line_id is not None
        or ticket.extra_work_request_item_id is not None
    ):
        return KIND_MEERWERK
    author = getattr(ticket, "created_by", None)
    if author is not None and author.role == UserRole.CUSTOMER_USER:
        return KIND_MELDING
    return KIND_TICKET


def ticket_due(ticket, today: datetime.date) -> dict:
    """`{due_date, due_kind, days_until_due}` for the fact block.

    `due_date` / `due_kind` are stated whatever the status — a finished
    job still had a deadline. Only the countdown stops: `days_until_due`
    is None unless the ticket is live (the same set the lateness ladder
    calls live) and unarchived.
    """
    due = job_due(ticket)
    if due is None:
        return {"due_date": None, "due_kind": None, "days_until_due": None}
    due_kind = (
        DUE_KIND_DEADLINE
        if job_deadline(ticket) is not None
        else DUE_KIND_PLANNED_DAY
    )
    live = (
        ticket.status in LATE_LIVE_TICKET_STATUSES
        and ticket.archived_at is None
    )
    return {
        "due_date": due.isoformat(),
        "due_kind": due_kind,
        "days_until_due": (due - today).days if live else None,
    }
