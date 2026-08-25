"""W-N1 §1 — the deadline reminder.

One sweep, mirroring `sla/warnings.py` in shape and in its throttle, but
living here because the subject is a ticket and the roster is the ticket's
own people.

WHAT "DEADLINE" MEANS FOR A TICKET
----------------------------------
A ticket has NO deadline column. `tickets/work_plan.py` says so in as
many words, and `views_work_plan.py::_slot_job` already settled what
stands in for one, so this module reuses that answer rather than
inventing a second:

    the extra-work deadline the ticket was spawned from, when it has
    one; otherwise the last day anybody planned for it.

Re-deriving it differently here would mean a ticket could be "overdue" on
the Work Plan and "not yet approaching" in the mail, which is the kind of
disagreement nobody ever debugs.

WHY IT DOES NOT REPEAT
----------------------
`sla/warnings.py` throttles on a COOLDOWN: "have I told this person about
this problem in the last N hours?", asked of the email log and the in-app
feed together so a hit on either suppresses both. That is right for a
condition that keeps being true and keeps deserving a nudge.

A deadline is not that condition. It arrives once, and a reminder that
re-fires every night until the deadline passes is the thing operators
mute. So this asks the same two tables the same way, with NO time bound:
"has this person EVER been told about THIS ticket's deadline?" Once per
ticket per person, which is what the brief asks for.

The consequence is deliberate and worth stating: moving a deadline does
NOT re-arm the reminder. Re-arming on change would need a marker of which
deadline was warned about — a column, and this wave's migration budget is
spent on the enum. A manager who moves a deadline is looking at the
ticket while they do it.
"""
import datetime
import logging

from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

#: How far ahead counts as "approaching". Fixed, not configurable: the
#: brief asks for a sane default and no settings surface, and a window
#: nobody can mis-set is a window nobody can mis-set to zero.
DEADLINE_WARNING_HOURS = 48

#: Statuses at which a deadline stops mattering. Mirrors the SLA sweep's
#: own terminal set, including CONVERTED_TO_EXTRA_WORK (Sprint 7B).
def _terminal_statuses():
    from .models import TicketStatus

    return (
        TicketStatus.APPROVED,
        TicketStatus.REJECTED,
        TicketStatus.CLOSED,
        TicketStatus.CONVERTED_TO_EXTRA_WORK,
    )


def _local_date(value):
    """The DATE a timestamp falls on in the project's timezone. Same
    conversion `views_work_plan._local_date` uses — a bare `.date()` on a
    UTC datetime prints the previous day anywhere east of Greenwich."""
    if value is None:
        return None
    if timezone.is_aware(value):
        return timezone.localtime(value).date()
    return value.date()


def ticket_deadline(ticket):
    """The date this ticket was supposed to be finished by, or None.

    Precedence is `_slot_job`'s, lifted to the ticket: a real deadline
    beats a planned day, and across several slots the LAST planned day is
    the one the ticket as a whole is due by — a ticket is not finished
    while any of its slots is still ahead of it.
    """
    deadline = getattr(
        getattr(ticket, "extra_work_request", None), "deadline", None
    )
    if deadline is not None:
        return deadline

    days = []
    for slot in ticket.staff_assignments.all():
        day = _local_date(slot.scheduled_end_at) or _local_date(
            slot.scheduled_start_at
        )
        if day is not None:
            days.append(day)
    return max(days) if days else None


def _already_reminded_user_ids(*, ticket_id, user_ids):
    """Who has ALREADY been told about this ticket's deadline, on either
    channel, ever.

    Two queries, not one per recipient, and no time bound — see the module
    docstring. Keyed on the same `event_type` string in both tables, which
    is why the two enums spell it identically.
    """
    from notifications.models import (
        Notification,
        NotificationEventType,
        NotificationLog,
    )

    if not user_ids:
        return set()
    ids = list(user_ids)
    event = NotificationEventType.TICKET_DEADLINE_APPROACHING
    told = set(
        NotificationLog.objects.filter(
            ticket_id=ticket_id,
            event_type=event,
            recipient_user_id__in=ids,
        ).values_list("recipient_user_id", flat=True)
    )
    told |= set(
        Notification.objects.filter(
            ticket_id=ticket_id,
            event_type=event,
            recipient_id__in=ids,
        ).values_list("recipient_id", flat=True)
    )
    return told


def _recipients(ticket):
    """The ticket's own people: the staff working it, plus the managers
    responsible for it. Both rosters come from `notifications.services`
    already tenant-scoped — this module never assembles a roster itself,
    for the same reason `sla/warnings.py` does not.
    """
    from notifications.services import (
        _dedupe_users,
        _ticket_assigned_staff_users,
        _ticket_staff_users,
    )

    return _dedupe_users(
        list(_ticket_assigned_staff_users(ticket)) + list(_ticket_staff_users(ticket))
    )


def _subject_and_body(ticket, deadline):
    from notifications.services import _ticket_summary

    label = ticket.ticket_no or f"#{ticket.pk}"
    subject = f"Deadline approaching: {label}"
    body = (
        f"{label} — {ticket.title}\n"
        f"Deadline: {deadline.isoformat()}\n\n"
        f"{_ticket_summary(ticket)}"
    )
    return subject, body


def remind_one(ticket, *, now=None):
    """Warn this ticket's people, once each. Returns how many were told."""
    from notifications.models import NotificationEventType
    from notifications.services import emit_sla_warning_inapp, send_logged_email

    now = now or timezone.now()
    deadline = ticket_deadline(ticket)
    if deadline is None:
        return 0
    today = _local_date(now)
    horizon = today + datetime.timedelta(hours=DEADLINE_WARNING_HOURS)
    # Inside the window means "due between now and the horizon". A
    # deadline already PAST is not "approaching" — it is overdue, which
    # the Work Plan already says loudly and which this reminder would only
    # repeat late.
    if deadline < today or deadline > horizon:
        return 0

    people = _recipients(ticket)
    if not people:
        return 0
    suppressed = _already_reminded_user_ids(
        ticket_id=ticket.id, user_ids=[u.id for u in people]
    )
    told = [u for u in people if u.id not in suppressed]
    if not told:
        return 0

    event = NotificationEventType.TICKET_DEADLINE_APPROACHING
    label = ticket.ticket_no or f"#{ticket.pk}"
    emit_sla_warning_inapp(
        event_type=event,
        recipients=told,
        summary=f"{label} is due {deadline.isoformat()}",
        ticket=ticket,
    )
    subject, body = _subject_and_body(ticket, deadline)
    for user in told:
        if not getattr(user, "email", ""):
            continue
        send_logged_email(
            recipient_email=user.email,
            recipient_user=user,
            subject=subject,
            body=body,
            event_type=event,
            ticket=ticket,
        )
    return len(told)


def sweep(now=None):
    """Every live ticket whose deadline is inside the window.

    Never raises per ticket: one bad row must not stop the reminder for
    every other row — the same argument `sweep_sla_warnings` makes, and
    the same reason it is worth repeating here.
    """
    from .models import Ticket

    now = now or timezone.now()
    told = failed = 0
    base = (
        Ticket.objects.exclude(status__in=_terminal_statuses())
        .select_related("extra_work_request", "customer", "building")
        .prefetch_related("staff_assignments")
    )
    # `chunk_size` is REQUIRED once a queryset prefetches — Django
    # refuses the combination without it rather than silently dropping
    # the prefetch, which is how the slots would have become an N+1.
    for ticket in base.iterator(chunk_size=500):
        try:
            told += remind_one(ticket, now=now)
        except Exception:  # noqa: BLE001 — one bad row, not the whole sweep
            failed += 1
            logger.exception(
                "deadline reminder failed for ticket %s", ticket.pk
            )
    return {"told": told, "failed": failed}
