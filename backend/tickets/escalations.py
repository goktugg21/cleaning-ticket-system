"""W-LATE §2 — the ladder speaks.

ANCHORED TO THE PROMISE, NOT TO ARBITRARY CLOCKS
------------------------------------------------
Three steps, each about a date somebody committed to:

  L2_MANAGERS    the deadline has passed and the work is not done. The
                 ticket's ASSIGNED MANAGERS are told, once.
  L2_ESCALATED   still not done a deadline-proportional step later. The
                 building managers AND the company admins are told, once.
                 "Proportional": half the span of the promise itself
                 (planned start -> deadline, or creation -> deadline when
                 nothing was planned), never less than a day. A job that
                 was promised in ten days gets five days of grace past
                 its deadline before the ring above hears; a job promised
                 for tomorrow gets one.
  L3_NEVER_DONE  thirty days past the anchor (the deadline, else the
                 planned date) with not one hour booked. The PROVIDER
                 ADMINS are told, once.

L1 — the plan passed — says nothing. It is the strip's orange rung and
a strip is where it belongs; a mail for every slipped day is the kind of
warning that gets a warning system switched off.

WHO IS TOLD, AND HOW THEY ARE FOUND
-----------------------------------
By ROLE, inside the ticket's own provider company, through the rosters
`notifications.services` already resolves for the SLA warnings:

  managers         `ticket_responsible_manager_recipients` — the explicit
                   per-ticket responsible managers, else the legacy
                   primary pointer, else the building's managers.
  BM + CA          `_ticket_staff_users` — the building's managers and
                   the company's admins.
  provider admins  `company_admin_recipients` — the company's admins.

No user id, name or address appears here or in any setting. The names
the never-done modal prints are resolved at render time from the ids the
step actually reached, which this module records on the escalation row.

ONCE, EVER — AND WHAT RE-PLANNING DOES
--------------------------------------
The SLA sweep dedupes on a cooldown; the deadline reminder dedupes on
"ever". This dedupes on a ROW: `TicketEscalation(ticket, step, anchor)`,
written in the same transaction as the notifications, so a step cannot
fire twice for one promise. The two L2 steps are keyed by the deadline
they measured against, so a genuinely re-planned job — a new deadline —
restarts L1/L2 from the new dates and can speak again. L3 is keyed by
the ticket alone: its never-worked clock resets only when hours land,
and once they have, the rung itself is gone.

BOTH CHANNELS, WITH THE SEVERITY ON THEM
----------------------------------------
Every step writes a bell row (`emit_escalation_inapp`, severity L2 or
L3) AND sends a mail (`send_logged_email`, the pipeline every SLA
warning uses — MailHog shows it on crmtest). The text states the fact
and the promise broken, in the recipient's own language:

    "Zonwering — TCK-2026-000344: deadline 20 aug is 6 dagen overschreden"

NEVER FATAL
-----------
One bad ticket must not silence the sweep for every other ticket; each
is tried on its own and a failure is logged and counted.
"""
from __future__ import annotations

import datetime
import logging
import math

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import lateness as late_rules
from .lateness_index import LATE_LIVE_TICKET_STATUSES, LatenessIndex, local_date
from .models import Ticket, TicketEscalation, TicketEscalationStep

logger = logging.getLogger(__name__)

#: The share of the promise's own span that a job may persist past its
#: deadline before the ring above the managers hears.
L2_PERSIST_FRACTION = 0.5
#: ...but never less than a day past the deadline.
L2_PERSIST_MIN_DAYS = 1


def l2_persist_days(
    *,
    planned_start: datetime.date | None,
    deadline: datetime.date,
    created_on: datetime.date,
) -> int:
    """How many days past the deadline the L2_ESCALATED step waits.

    Half the promise's span, measured from the planned start when there
    was one before the deadline, otherwise from the day the ticket was
    raised. Rounded up; never below `L2_PERSIST_MIN_DAYS`.
    """
    start = planned_start if planned_start and planned_start < deadline else created_on
    span = (deadline - start).days
    if span <= 0:
        return L2_PERSIST_MIN_DAYS
    return max(L2_PERSIST_MIN_DAYS, math.ceil(span * L2_PERSIST_FRACTION))


# ---------------------------------------------------------------------
# The sentence, in the recipient's language — P-16 Part D: the words
# live in the notification copy catalogue (`notifications/copy.py`,
# the `ticket_late_*` keys); this module packs the FACTS.
# ---------------------------------------------------------------------


def _lang(user) -> str:
    return "en" if getattr(user, "language", "nl") == "en" else "nl"


def _label(ticket) -> str:
    return ticket.ticket_no or f"#{ticket.pk}"


_TEMPLATE_KEY = {
    TicketEscalationStep.L2_MANAGERS: "ticket_late_l2_managers",
    TicketEscalationStep.L2_ESCALATED: "ticket_late_l2_escalated",
    TicketEscalationStep.L3_NEVER_DONE: "ticket_late_l3_never_done",
}


def _step_params(step: str, ticket, lateness: late_rules.Lateness) -> dict:
    """Names, numbers and ISO dates — never ids. The catalogue formats
    the dates per language at render time, so one params payload serves
    a Dutch inbox and an English bell alike."""
    from notifications.copy import ticket_facts_params

    params = ticket_facts_params(ticket)
    params.update(
        {
            "label": _label(ticket),
            "deadline_days_late": lateness.deadline_days_late,
            "deadline_iso": (
                lateness.deadline.isoformat() if lateness.deadline else ""
            ),
            "anchor_days": lateness.anchor_days,
            "anchor_iso": (
                lateness.anchor.isoformat() if lateness.anchor else ""
            ),
            "anchored_on_deadline": lateness.deadline is not None,
        }
    )
    return params


def summary_for(step: str, ticket, lateness: late_rules.Lateness, lang: str) -> str:
    """The fact and the promise broken, as one line (via the catalogue)."""
    from notifications import copy as notification_copy

    return (
        notification_copy.render_summary(
            _TEMPLATE_KEY[step], _step_params(step, ticket, lateness), lang
        )
        or ""
    )


# ---------------------------------------------------------------------
# The steps
# ---------------------------------------------------------------------

_EVENT = {
    TicketEscalationStep.L2_MANAGERS: "TICKET_LATE_L2_MANAGERS",
    TicketEscalationStep.L2_ESCALATED: "TICKET_LATE_L2_ESCALATED",
    TicketEscalationStep.L3_NEVER_DONE: "TICKET_LATE_L3_QUARANTINE",
}


def _recipients(step: str, ticket):
    from notifications.services import (
        _dedupe_users,
        _ticket_staff_users,
        company_admin_recipients,
        ticket_responsible_manager_recipients,
    )

    if step == TicketEscalationStep.L2_MANAGERS:
        return ticket_responsible_manager_recipients(ticket)
    if step == TicketEscalationStep.L2_ESCALATED:
        return _dedupe_users(list(_ticket_staff_users(ticket)))
    return company_admin_recipients(ticket.company_id)


def _already_fired(ticket, step: str, anchor: datetime.date | None) -> bool:
    rows = TicketEscalation.objects.filter(ticket=ticket, step=step)
    if step != TicketEscalationStep.L3_NEVER_DONE:
        rows = rows.filter(anchor_date=anchor)
    return rows.exists()


def _severity(step: str):
    from notifications.models import NotificationSeverity

    return (
        NotificationSeverity.L3
        if step == TicketEscalationStep.L3_NEVER_DONE
        else NotificationSeverity.L2
    )


def fire_step(ticket, step: str, lateness: late_rules.Lateness, *, now) -> int:
    """Speak one step for one ticket, on both channels, and record it.
    Returns how many people were told (0 when the step had already
    fired, or there was nobody to tell)."""
    from notifications.services import emit_escalation_inapp, send_logged_email

    anchor = None if step == TicketEscalationStep.L3_NEVER_DONE else lateness.deadline
    if _already_fired(ticket, step, anchor):
        return 0
    people = _recipients(step, ticket)
    if not people:
        # Nobody holds the role this step speaks to. Recorded anyway, so
        # the row says "fired, reached nobody" rather than the sweep
        # asking the same question every day — and so the bar can say
        # exactly that.
        TicketEscalation.objects.create(
            ticket=ticket,
            step=step,
            anchor_date=anchor,
            notified_at=now,
            recipient_ids=[],
            recipient_count=0,
        )
        return 0

    event = _EVENT[step]
    template_key = _TEMPLATE_KEY[step]
    params = _step_params(step, ticket, lateness)
    with transaction.atomic():
        emit_escalation_inapp(
            event_type=event,
            recipients=people,
            template_key=template_key,
            params=params,
            severity=_severity(step),
            ticket=ticket,
        )
        from notifications import copy as notification_copy

        for user in people:
            if not getattr(user, "email", ""):
                continue
            subject, body = notification_copy.render_email(
                template_key, params, _lang(user)
            )
            send_logged_email(
                recipient_email=user.email,
                recipient_user=user,
                subject=subject,
                body=body,
                event_type=event,
                ticket=ticket,
                template_key=template_key,
                params=params,
            )
        TicketEscalation.objects.create(
            ticket=ticket,
            step=step,
            anchor_date=anchor,
            notified_at=now,
            recipient_ids=[user.id for user in people],
            recipient_count=len(people),
        )
    return len(people)


def steps_due(
    ticket,
    lateness: late_rules.Lateness,
    *,
    today: datetime.date,
    planned_start: datetime.date | None = None,
) -> list[str]:
    """Which steps the ladder says should have spoken by today.

    `planned_start` is the first planned day of the WORK (the index's
    `planned_start_for`) — W-PLANTRUTH §1a: the ticket's own date is a
    different fact and is not read here any more. None falls back to
    the day the ticket was raised, as `l2_persist_days` already does.
    """
    if not lateness.is_late:
        return []
    due: list[str] = []
    if lateness.deadline_days_late is not None and lateness.deadline is not None:
        due.append(TicketEscalationStep.L2_MANAGERS)
        persist = l2_persist_days(
            planned_start=planned_start,
            deadline=lateness.deadline,
            created_on=local_date(ticket.created_at) or today,
        )
        if lateness.deadline_days_late >= persist:
            due.append(TicketEscalationStep.L2_ESCALATED)
    if lateness.level == late_rules.LEVEL_NEVER_DONE:
        due.append(TicketEscalationStep.L3_NEVER_DONE)
    return due


def escalate_one(ticket, index: LatenessIndex, *, now) -> int:
    lateness = index.for_ticket(ticket.id)
    told = 0
    for step in steps_due(
        ticket,
        lateness,
        today=index.today,
        planned_start=index.planned_start_for(ticket.id),
    ):
        told += fire_step(ticket, step, lateness, now=now)
    return told


def sweep(now=None) -> dict:
    """Every pending ticket that might be on rung two or three."""
    now = now or timezone.now()
    today = timezone.localdate(now)
    never_done_horizon = today - datetime.timedelta(days=late_rules.NEVER_DONE_DAYS - 1)
    # A SUPERSET: past deadline (L2/L3 with a deadline), or any planned
    # date old enough to be thirty days past (L3 without one). The
    # ladder itself is asked of every candidate.
    candidates = (
        Ticket.objects.filter(
            status__in=LATE_LIVE_TICKET_STATUSES,
            archived_at__isnull=True,
            deleted_at__isnull=True,
        )
        # W-PLANTRUTH §1a — the planned days are the slots' and the
        # parts'; the ticket's own date is not one of them.
        .filter(
            Q(extra_work_request__deadline__lt=today)
            | Q(staff_assignments__scheduled_start_at__date__lt=never_done_horizon)
            | Q(staff_assignments__scheduled_end_at__date__lt=never_done_horizon)
            | Q(sub_tasks__planned_start_date__lt=never_done_horizon)
            | Q(sub_tasks__planned_end_date__lt=never_done_horizon)
        )
        .distinct()
        .select_related("extra_work_request", "customer", "building", "assigned_to")
        .order_by("id")
    )
    rows = list(candidates)
    index = LatenessIndex([t.id for t in rows], [], today)
    told = failed = 0
    for ticket in rows:
        try:
            told += escalate_one(ticket, index, now=now)
        except Exception:  # noqa: BLE001 — one bad row, not the whole sweep
            failed += 1
            logger.exception("late escalation failed for ticket %s", ticket.pk)
    return {"told": told, "failed": failed, "checked": len(rows)}


__all__ = [
    "L2_PERSIST_FRACTION",
    "L2_PERSIST_MIN_DAYS",
    "escalate_one",
    "fire_step",
    "l2_persist_days",
    "steps_due",
    "summary_for",
    "sweep",
]
