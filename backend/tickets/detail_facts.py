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

from django.utils import timezone

from accounts.models import UserRole

from .job_dates import job_deadline, job_due, job_plan_source, job_window
from .lateness_index import LATE_LIVE_TICKET_STATUSES
from .models import TicketStatus
from .plan_provenance import ticket_plan_provenance

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


def _planned_after_deadline(ticket, has_real_plan: bool) -> bool:
    if not has_real_plan:
        return False
    start, end = job_window(ticket)
    window_end = end or start
    deadline = job_deadline(ticket)
    if window_end is None or deadline is None:
        return False
    return window_end > deadline


#: P-9 §A.2b — reported done, not yet settled for this reader. Such a
#: ticket carries `reported_done_at` (P-8R E) and NO `settled_at`: FE-4
#: pinned "work waiting on the customer is settled without a finish".
_REPORTED_DONE_STATUSES = frozenset(
    {TicketStatus.WAITING_MANAGER_REVIEW, TicketStatus.WAITING_CUSTOMER_APPROVAL}
)

#: The endings that are not a finish: the work did not get done.
_BLOCKED_STATUSES = frozenset(
    {TicketStatus.REJECTED, TicketStatus.CONVERTED_TO_EXTRA_WORK}
)


def ticket_is_live(ticket) -> bool:
    """Somebody on the provider side still has to work this: the
    ladder's live set, and not archived. The one reading `ticket_due`,
    the board (`views_work_plan._ticket_live`) and the finish stamp
    below all share."""
    return (
        ticket.status in LATE_LIVE_TICKET_STATUSES
        and ticket.archived_at is None
    )


def ticket_finished_at(ticket):
    """P-9 §A.2b — the moment the WORK was finished, on a ticket that is
    over. None while it is live.

    The worker's report is the finish: `manager_review_at` (the leg into
    the manager's check) or `sent_for_approval_at` (the leg to the
    customer) — both stamped by the state machine on entry, both
    overwritten when the work is sent back and reported again, so the
    LAST report is the one that counts. A row that carries neither
    (approved straight from work, closed by hand, a legacy row) answers
    with the approval, the close, or the old `resolved_at`. A blocked
    ending (rejected, converted) answers with the moment it ended: it
    is not a finish, but it is when the job left the board.

    This is the day a finished card hangs on (`work_plan` rule 10) AND
    the day it prints, so the card can never sit in one column and
    name another.
    """
    if ticket_is_live(ticket):
        return None
    if ticket.status in _BLOCKED_STATUSES:
        return (
            ticket.rejected_at
            or ticket.closed_at
            or ticket.approved_at
            or ticket.resolved_at
        )
    return (
        ticket.manager_review_at
        or ticket.sent_for_approval_at
        or ticket.approved_at
        or ticket.closed_at
        or ticket.resolved_at
    )


def ticket_settled_at(ticket):
    """FE-4's past-tense stamp: when the work was over, on a job that IS
    over. None while live, and None while reported done but waiting on
    a check — `reported_done_at` carries that moment, and a card that
    said "finished" about work the customer has not accepted would be
    telling the reader the chain is complete when it is not."""
    if ticket.status in _REPORTED_DONE_STATUSES:
        return None
    return ticket_finished_at(ticket)


def ticket_due(ticket, today: datetime.date) -> dict:
    """The due facts for the fact block: `due_date`, `due_kind`,
    `days_until_due`, `unplanned_age_days`, `settled_at`,
    `settled_days_after_due`.

    `due_date` / `due_kind` are stated whatever the status — a finished
    job still had a deadline. Only the countdown stops: `days_until_due`
    is None unless the ticket is live (the same set the lateness ladder
    calls live) and unarchived.
    """
    live = ticket_is_live(ticket)
    # FE-4 (Addendum D SS D.12 item 4) -- when the work was over, and how
    # far after its due date that came: past tense, quiet history.
    # P-9 §A.2b -- the FINISH moment (the worker's report), the same
    # stamp the board places the card by, so card and detail agree.
    settled_at = ticket_settled_at(ticket)
    due = job_due(ticket)
    # P-1 — WHO planned the window and WHEN, or that nobody did. The
    # words on the detail and on the card both key off `has_real_plan`;
    # a phantom (a seeded date with no person behind it) reads as no
    # plan here AND has already been read as no window by `job_window`,
    # so the two cannot disagree.
    provenance = ticket_plan_provenance(ticket)
    facts = {
        **provenance.as_dict(),
        "plan_source": job_plan_source(ticket),
        "due_date": None,
        "due_kind": None,
        "days_until_due": None,
        # FE-4 (SS D.12 item 2) -- the SAME age the Werkplanning's "Nog
        # niet gepland" row prints: whole days since creation, only on a
        # live job with no window at all. The card and the detail agree.
        "unplanned_age_days": None,
        "settled_at": settled_at.isoformat() if settled_at else None,
        "settled_days_after_due": None,
        # P-3 §A.5 — a REAL plan whose last day is past the deadline.
        # The same rule the card reads (`views_work_plan.planned_after_
        # deadline`), so card and detail cannot disagree.
        "planned_after_deadline": _planned_after_deadline(
            ticket, provenance.has_real_plan
        ),
    }
    if due is None:
        if live and job_window(ticket)[0] is None:
            created = timezone.localtime(ticket.created_at).date()
            facts["unplanned_age_days"] = max((today - created).days, 0)
        return facts
    facts["due_date"] = due.isoformat()
    facts["due_kind"] = (
        DUE_KIND_DEADLINE
        if job_deadline(ticket) is not None
        else DUE_KIND_PLANNED_DAY
    )
    if live:
        facts["days_until_due"] = (due - today).days
    elif settled_at is not None:
        late_by = (timezone.localtime(settled_at).date() - due).days
        facts["settled_days_after_due"] = late_by if late_by > 0 else None
    return facts
