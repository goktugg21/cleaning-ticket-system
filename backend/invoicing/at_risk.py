"""
WP-1 G4 (Addendum D §D.11.2) — the billing-month guard.

The business problem, in the addendum's words: completion is a chain —
slot done -> ticket completed (staff completion + manager confirm) ->
extra work earned -> billing month resolved -> unbilled pool ->
invoice. A break anywhere (typically: the manager never confirms)
silently drops the job out of that month's invoice, and the invoice
comes out wrong until somebody edits data by hand.

This module NAMES the breaks. It is a read and nothing else: no status
changes, no billing-month writes, no claims. The existing manual
surfaces (the billing-month override on the extra work, the workflow
override with reason) remain the only mutation paths — Addendum B is
untouched.

WHAT COUNTS AS AT RISK
----------------------
An extra work that is still live commercially (not cancelled, not
customer-rejected), NOT yet earned (`extra_work.billing.is_earned` —
once earned it is the due panel's job, not this one), whose planned day
or deadline falls in the OPEN billing month **or any earlier month**
(the Addendum B §B.10 lesson: a break in July is still a broken July
invoice in August; anchoring to the exact current month is how work
silently drops off a panel), and whose chain is visibly broken in one
of four ways:

    WAITING_REVIEW  the spawned ticket has sat in manager review for
                    REVIEW_STALL_DAYS or longer. The typical break.
    SLOT_DONE       every staff slot on the ticket is completed but the
                    ticket itself never moved — the work happened and
                    nobody reported it done.
    BLOCKED         the work stopped without being done: the ticket
                    ended blocked (rejected / converted), or everybody
                    on it said "unable" and nobody is assigned any more
                    (the same reading as the work plan's stuck list).
    PAST_DEADLINE   the extra work is in execution and its deadline has
                    passed.

A ticket in manager review for LESS than the threshold is deliberately
not listed: review is the chain working, not the chain broken.

The stage values are machine keys; the frontend translates them. The
"open billing month" is the current Amsterdam-local month — the same
anchor the /due/ panel reports (`period_year` / `period_month`).
"""
from __future__ import annotations

import datetime

from django.utils import timezone

from extra_work.billing import NON_BILLABLE_STATUSES, is_earned
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from tickets.models import (
    StaffAssignmentSlotStatus,
    Ticket,
    TicketStaffAssignment,
    TicketStatus,
)

#: Days in manager review before the chain counts as stalled.
REVIEW_STALL_DAYS = 7

#: One bound across all groups. The panel renders inside a bounded list
#: and the digest prints the same rows; `truncated` says when the cap
#: was hit. The TOTAL is always the whole set.
ROW_LIMIT = 200

STAGE_WAITING_REVIEW = "WAITING_REVIEW"
STAGE_SLOT_DONE = "SLOT_DONE"
STAGE_BLOCKED = "BLOCKED"
STAGE_PAST_DEADLINE = "PAST_DEADLINE"

#: The ticket ended without the work being done.
_BLOCKED_TICKET_STATUSES = frozenset(
    {TicketStatus.REJECTED, TicketStatus.CONVERTED_TO_EXTRA_WORK}
)

#: The ticket is still on the provider's plate, before any completion
#: report: the statuses where "all slots done" means "somebody forgot
#: to move the ticket".
_ACTIVE_TICKET_STATUSES = frozenset(
    {
        TicketStatus.OPEN,
        TicketStatus.ACKNOWLEDGED,
        TicketStatus.IN_PROGRESS,
        TicketStatus.ON_HOLD,
        TicketStatus.REOPENED_BY_ADMIN,
    }
)


def _local_date(value) -> datetime.date | None:
    if value is None:
        return None
    return timezone.localtime(value).date()


def _month_end(today: datetime.date) -> datetime.date:
    first_of_next = datetime.date(
        today.year + (today.month // 12), (today.month % 12) + 1, 1
    )
    return first_of_next - datetime.timedelta(days=1)


def _relevant_date(ew, ticket) -> datetime.date | None:
    """The planned day / deadline that ties this work to a month.

    The extra work's own dates win (deadline is the promise, then the
    planned window); a ticket-only schedule is the fallback. None means
    the work is tied to no month at all — that is the work plan's
    "not planned yet" lane's problem (G2), not this guard's.
    """
    if ew.deadline is not None:
        return ew.deadline
    if ew.planned_end_date is not None:
        return ew.planned_end_date
    if ew.preferred_date is not None:
        return ew.preferred_date
    if ticket is not None:
        return _local_date(ticket.scheduled_end_at) or _local_date(
            ticket.scheduled_start_at
        )
    return None


def _spawned_tickets(ew_ids) -> dict:
    """ew_id -> spawned operational ticket, lowest id per extra work —
    the same election `extra_work.billing.build_ticket_map` makes, but
    loading the full row because the stage decision reads far more
    fields than the billing pool does."""
    out: dict = {}
    if not ew_ids:
        return out
    rows = (
        Ticket.objects.filter(
            extra_work_request_id__in=list(ew_ids), deleted_at__isnull=True
        )
        .order_by("id")
    )
    for ticket in rows:
        out.setdefault(ticket.extra_work_request_id, ticket)
    return out


def _slot_facts(ticket_ids) -> dict:
    """ticket_id -> (has_assigned, has_unable, all_done, latest_done_at).

    `all_done` is over the non-cancelled slots and requires at least one
    of them — a ticket with no slots at all has nobody who finished.
    """
    facts: dict[int, dict] = {}
    if not ticket_ids:
        return {}
    rows = TicketStaffAssignment.objects.filter(
        ticket_id__in=list(ticket_ids)
    ).values("ticket_id", "slot_status", "completed_at")
    for row in rows:
        fact = facts.setdefault(
            row["ticket_id"],
            {
                "assigned": False,
                "unable": False,
                "completed": 0,
                "live": 0,
                "latest_done": None,
            },
        )
        slot_status = row["slot_status"]
        if slot_status == StaffAssignmentSlotStatus.CANCELLED:
            continue
        fact["live"] += 1
        if slot_status == StaffAssignmentSlotStatus.ASSIGNED:
            fact["assigned"] = True
        elif slot_status == StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE:
            fact["unable"] = True
        elif slot_status == StaffAssignmentSlotStatus.COMPLETED:
            fact["completed"] += 1
            done = row["completed_at"]
            if done is not None and (
                fact["latest_done"] is None or done > fact["latest_done"]
            ):
                fact["latest_done"] = done
    return {
        ticket_id: {
            "assigned": fact["assigned"],
            "unable": fact["unable"],
            "all_done": fact["live"] > 0
            and fact["completed"] == fact["live"],
            "latest_done": fact["latest_done"],
        }
        for ticket_id, fact in facts.items()
    }


def _blocked_since(ticket, today: datetime.date) -> datetime.date:
    """When the work stopped. `rejected_at` where the state machine
    stamped it; else the unable notification the transition always
    logs; else today (age 0 — present, honestly unknown)."""
    day = _local_date(getattr(ticket, "rejected_at", None))
    if day is not None:
        return day
    from notifications.models import NotificationEventType, NotificationLog

    stamp = (
        NotificationLog.objects.filter(
            ticket_id=ticket.id,
            event_type=NotificationEventType.TICKET_SLOT_UNABLE,
        )
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    return _local_date(stamp) or today


def _stage_for(ew, ticket, slots, today, now):
    """`(stage, age_days)` or None when the chain is not visibly broken."""
    if ticket is not None:
        if ticket.status == TicketStatus.WAITING_MANAGER_REVIEW:
            if ticket.manager_review_at is None:
                return None
            days = (now - ticket.manager_review_at).days
            if days >= REVIEW_STALL_DAYS:
                return STAGE_WAITING_REVIEW, days
            return None
        if ticket.status in _BLOCKED_TICKET_STATUSES:
            return (
                STAGE_BLOCKED,
                max((today - _blocked_since(ticket, today)).days, 0),
            )
        facts = slots.get(ticket.id)
        if facts is not None and ticket.status in _ACTIVE_TICKET_STATUSES:
            if facts["unable"] and not facts["assigned"]:
                return (
                    STAGE_BLOCKED,
                    max((today - _blocked_since(ticket, today)).days, 0),
                )
            if facts["all_done"]:
                since = _local_date(facts["latest_done"]) or today
                return STAGE_SLOT_DONE, max((today - since).days, 0)
    if (
        ew.status == ExtraWorkStatus.IN_PROGRESS
        and ew.deadline is not None
        and ew.deadline < today
    ):
        return STAGE_PAST_DEADLINE, (today - ew.deadline).days
    return None


def at_risk_groups(customers, *, today=None, now=None) -> dict:
    """The guard's whole answer, grouped per customer.

    `customers` is an already-scoped queryset — scoping belongs to the
    caller (the view scopes by actor, the digest by company) and this
    function never widens it.
    """
    now = now or timezone.now()
    today = today or timezone.localdate(now)
    month_end = _month_end(today)

    ews = list(
        ExtraWorkRequest.objects.filter(
            customer__in=customers, deleted_at__isnull=True
        )
        .exclude(status__in=list(NON_BILLABLE_STATUSES))
        .select_related("customer", "building")
        .order_by("id")
    )
    tickets = _spawned_tickets([ew.id for ew in ews])
    slots = _slot_facts([t.id for t in tickets.values()])

    by_customer: dict[int, dict] = {}
    total = 0
    for ew in ews:
        ticket = tickets.get(ew.id)
        if is_earned(ticket):
            continue
        relevant = _relevant_date(ew, ticket)
        if relevant is None or relevant > month_end:
            continue
        staged = _stage_for(ew, ticket, slots, today, now)
        if staged is None:
            continue
        stage, age = staged
        group = by_customer.setdefault(
            ew.customer_id,
            {
                "customer": ew.customer_id,
                "customer_name": ew.customer.name if ew.customer_id else "",
                "company": ew.company_id,
                "count": 0,
                "rows": [],
            },
        )
        group["count"] += 1
        total += 1
        group["rows"].append(
            {
                "kind": "EXTRA_WORK",
                "extra_work_id": ew.id,
                "ticket_id": ticket.id if ticket is not None else None,
                "ticket_no": (
                    ticket.ticket_no if ticket is not None else None
                ),
                "title": ew.title,
                "building_id": ew.building_id,
                "building_name": (
                    ew.building.name if ew.building_id else None
                ),
                "stage": stage,
                "age_days": age,
                "date": relevant.isoformat(),
            }
        )

    groups = sorted(
        by_customer.values(), key=lambda g: (g["customer_name"], g["customer"])
    )
    shown = 0
    truncated = False
    for group in groups:
        group["rows"].sort(
            key=lambda r: (-r["age_days"], r["extra_work_id"])
        )
        keep = max(ROW_LIMIT - shown, 0)
        if len(group["rows"]) > keep:
            group["rows"] = group["rows"][:keep]
            truncated = True
        shown += len(group["rows"])
    groups = [g for g in groups if g["rows"]]

    return {
        "period_year": today.year,
        "period_month": today.month,
        "total": total,
        "limit": ROW_LIMIT,
        "truncated": truncated,
        "groups": groups,
    }
