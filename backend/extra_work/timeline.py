"""
FE-2 (Addendum D §D.4) — the requester's folded timeline.

One meerwerk, one story: the request's own status history and its
spawned ticket's history merged into a single chronological list of
PHASE EVENTS. The requester never meets a second object called
"ticket" — the ticket's milestones appear inside the meerwerk's story.

Design rules, all deliberate:

  * EVENTS, NOT NOTES. Every entry is a machine key the frontend
    translates (§D.2 vocabulary lives in i18n, both locales). No free
    text from history rows is ever copied in — which is also how the
    note-privacy floor (test_b1/test_b7) is satisfied by construction:
    there is nothing here to redact, for any viewer.
  * INTERNAL STEPS ARE NOT EVENTS. The manager's double-check, an
    on-hold shuffle, the auto-close bookkeeping row — none of these is
    a phase of the requester's story, for ANY viewer of this endpoint.
    Provider surfaces keep their own full histories elsewhere.
  * The actor is the display name the existing history serializers
    already show to every viewer (`changed_by_email` has never been
    redacted); system rows show no actor.
  * Read-only by construction: this module only reads.
"""
from __future__ import annotations

from tickets.models import TicketStatus

from .models import ExtraWorkStatus

SOURCE_MEERWERK = "MEERWERK"
SOURCE_TICKET = "TICKET"

#: Extra-work status-history rows -> the event the requester reads.
#: A status absent here produces no entry (REQUESTED's entry is the
#: synthetic "requested" row from `requested_at`, so a reprice loop
#: back through UNDER_REVIEW simply says the price is being prepared
#: again).
_EW_EVENTS = {
    ExtraWorkStatus.UNDER_REVIEW: "price_in_preparation",
    ExtraWorkStatus.PRICING_PROPOSED: "quote_sent",
    ExtraWorkStatus.CUSTOMER_APPROVED: "approved",
    ExtraWorkStatus.IN_PROGRESS: "work_started",
    ExtraWorkStatus.COMPLETED: "work_done",
    ExtraWorkStatus.CUSTOMER_REJECTED: "quote_rejected",
    ExtraWorkStatus.CANCELLED: "cancelled",
}

#: Spawned-ticket history rows -> events. Only the milestones that are
#: the REQUESTER's: the work being created, the finished work reaching
#: them, their answer, and a reopen. IN_PROGRESS is deliberately absent
#: — the parent's own auto-advance row already says "work_started" and
#: two identical entries a second apart is noise, not information.
_TICKET_EVENTS = {
    TicketStatus.OPEN: "work_created",
    TicketStatus.WAITING_CUSTOMER_APPROVAL: "completion_submitted",
    TicketStatus.APPROVED: "completion_approved",
    TicketStatus.REJECTED: "completion_rejected",
    TicketStatus.REOPENED_BY_ADMIN: "work_reopened",
}


def _actor(user) -> str:
    if user is None:
        return ""
    return (user.full_name or "").strip() or user.email


def _entry(at, event, actor, source) -> dict:
    return {
        "at": at.isoformat() if at is not None else None,
        "event": event,
        "actor": actor,
        "source": source,
    }


def build_timeline(extra_work, spawned_tickets) -> list[dict]:
    """The folded list, oldest first.

    `spawned_tickets` are the request's operational tickets (already
    resolved by the caller so prefetches are honoured). History rows
    must carry `changed_by` loaded — the caller select_relates it.
    """
    entries: list[dict] = [
        _entry(
            extra_work.requested_at,
            "requested",
            _actor(extra_work.created_by),
            SOURCE_MEERWERK,
        )
    ]

    for row in extra_work.status_history.all():
        event = _EW_EVENTS.get(row.new_status)
        if event is None:
            continue
        entries.append(
            _entry(row.created_at, event, _actor(row.changed_by), SOURCE_MEERWERK)
        )

    for ticket in spawned_tickets:
        for row in ticket.status_history.all():
            event = _TICKET_EVENTS.get(row.new_status)
            if event is None:
                continue
            entries.append(
                _entry(row.created_at, event, _actor(row.changed_by), SOURCE_TICKET)
            )

    if extra_work.is_invoiced and extra_work.invoiced_at is not None:
        entries.append(_entry(extra_work.invoiced_at, "invoiced", "", SOURCE_MEERWERK))

    entries.sort(key=lambda item: (item["at"] is None, item["at"]))
    return entries
