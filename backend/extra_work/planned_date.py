"""
Sprint 184 §1 (write half) — planning an extra work moves its work.

THE READ/WRITE SPLIT, IN ONE LINE
---------------------------------
`preferred_date`, `planned_end_date` and `deadline` are READ through the
link (`tickets.serializers.resolve_extra_work_origin_core` exposes them
on `extra_work_origin`); `provider_planned_date` is the one that WRITES,
because when the provider commits to a day the WORK moves and the
spawned ticket's own `scheduled_start_at` has to move with it.

Why the others are not copied: a copy is one fact stored twice, and the
second copy is silently wrong the moment somebody edits the first. The
extra work owns those dates. But `scheduled_start_at` is not a copy of
`provider_planned_date` — it is the ticket's OWN schedule, which the
agenda, the SLA pause rules and the staff slots all read. Setting it is
an action taken on the ticket, the same action an operator would take by
hand, and it is recorded as such.

WHAT HAPPENS TO A TICKET SOMEBODY ALREADY RESCHEDULED BY HAND
--------------------------------------------------------------
**The explicit reschedule wins, and the write says so.**

A ticket in `RESCHEDULED` carries `rescheduled_from` and a mandatory
`reschedule_reason` — somebody looked at this job, moved it, and wrote
down why. Overwriting that from a date field on the parent would throw
away a human decision and its stated reason, and the operator who made
it would get no signal at all; they would simply find their ticket on a
different day next time they looked.

So a RESCHEDULED ticket is left alone and reported back as skipped. The
caller surfaces that rather than swallowing it — "planned, but two
tickets keep their own date" is a sentence an operator can act on;
silence is not.

An UNSCHEDULED or SCHEDULED ticket moves. SCHEDULED is included on
purpose: that is the state the spawn helper leaves a ticket in when it
seeded a start from the cart line's requested date, which is a machine's
guess, not a person's decision.
"""
from __future__ import annotations

import datetime

from django.utils import timezone

from tickets.models import Ticket, TicketScheduleStatus


#: Statuses whose schedule this may move. RESCHEDULED is deliberately
#: absent — see the module docstring.
_MOVABLE_SCHEDULE_STATUSES = frozenset(
    {
        TicketScheduleStatus.UNSCHEDULED,
        TicketScheduleStatus.SCHEDULED,
    }
)


def _local_midnight(value: datetime.date):
    """The planned DAY as an aware datetime at local 00:00.

    Mirrors `instant_tickets.earliest_requested_start` exactly, so a
    ticket scheduled by the spawn helper and one moved by this module
    land on the same instant for the same day — otherwise the agenda
    would sort two identically-planned jobs differently.
    """
    return timezone.make_aware(
        datetime.datetime.combine(value, datetime.time.min)
    )


def spawned_tickets_for(extra_work):
    """The LIVE operational tickets this extra work spawned.

    Anchored on the canonical `extra_work_request` FK, with the two
    legacy chains kept in the union for historical rows whose canonical
    FK is null — the same three paths
    `tickets.filters.TicketFilter.filter_extra_work_request` and
    `resolve_extra_work_origin_core` resolve, so "which tickets belong to
    this extra work" cannot mean one thing here and another there.
    """
    from django.db.models import Q

    return (
        Ticket.objects.filter(
            Q(extra_work_request_id=extra_work.id)
            | Q(extra_work_request_item__extra_work_request_id=extra_work.id)
            | Q(proposal_line__proposal__extra_work_request_id=extra_work.id),
            deleted_at__isnull=True,
        )
        .distinct()
    )


def apply_planned_date_to_tickets(extra_work) -> dict:
    """Move this extra work's spawned tickets onto its planned day.

    Returns `{"moved": [ticket_id, ...], "kept_own_date": [ticket_id, ...]}`
    so the caller can tell the operator what actually happened. Never
    raises: a schedule that could not be moved is reported, not fatal —
    the date write on the extra work itself has already succeeded and
    must not be rolled back because a ticket held its own plan.

    A NULL `provider_planned_date` (the provider cleared the plan) does
    NOT clear the tickets' schedules. Un-planning an extra work is not a
    statement that the work should become undated — the ticket may be
    scheduled for reasons of its own, and wiping schedules as a side
    effect of clearing one field is exactly the kind of silent action
    this module exists to avoid.
    """
    planned = extra_work.provider_planned_date
    result: dict[str, list[int]] = {"moved": [], "kept_own_date": []}
    if planned is None:
        return result

    when = _local_midnight(planned)
    for ticket in spawned_tickets_for(extra_work):
        if str(ticket.schedule_status) not in {
            str(s) for s in _MOVABLE_SCHEDULE_STATUSES
        }:
            result["kept_own_date"].append(ticket.id)
            continue
        if ticket.scheduled_start_at == when:
            # Already there. Not reported as moved — an operator reading
            # "3 tickets moved" when nothing changed learns nothing.
            continue
        ticket.scheduled_start_at = when
        ticket.schedule_status = TicketScheduleStatus.SCHEDULED
        ticket.save(
            update_fields=[
                "scheduled_start_at",
                "schedule_status",
                "updated_at",
            ]
        )
        result["moved"].append(ticket.id)
    return result
