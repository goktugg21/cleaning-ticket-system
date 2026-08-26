"""W-LATE §1b — JOB-level lateness for a set of tickets and extra work,
built once and asked per row.

The RULE is `tickets/lateness.py` — pure, five facts in, a rung out.
This module is the fact-gathering in front of it: which planned window,
which deadline, whether the work is still pending, and how many hours
have been booked. Two callers ask the same questions — the Work Plan
endpoint for every card it renders, and the phase-2 escalation sweep for
every ticket it might have to speak about — so the gathering lives in
one place rather than as two copies that would drift.

JOB-level, not slot-level, on purpose. A slot is one person's dated
piece of a ticket; "the planned date has passed" is a fact about the
ticket, and the strip shows one card per job. So the planned window is
the WIDEST one the ticket carries — its own `scheduled_*` plus every
non-cancelled slot's window — and the deadline is the extra work's, read
through the canonical link exactly as `views_work_plan._slot_deadline`
reads it.

Hours are the timesheets module's `TimeEntry` rows filed against the
job (`HourSource.TICKET` for the ticket, `HourSource.EXTRA_WORK` for the
request it came from — a booking on either side is an hour worked on
this job). Imported inside the constructor, the way
`extra_work/planning.py` already does: `timesheets` imports nothing from
`tickets`, and `tickets` keeps the reverse import off the module path so
the hours module stays usable on its own.
"""
from __future__ import annotations

import datetime

from django.db.models import Max, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from extra_work.models import ExtraWorkStatus

from . import lateness as late_rules
from .models import (
    StaffAssignmentSlotStatus,
    Ticket,
    TicketEscalation,
    TicketStatus,
)

#: W-LATE — the ticket statuses in which the WORK is still pending. A
#: job is late only while somebody still has to do it: a ticket sitting
#: in review, waiting on the customer, approved, rejected, closed or
#: converted has nothing left to be late with, whatever its dates say.
#: ON_HOLD stays: parked work is still undone work, and the plan date
#: it was parked past is still a broken plan.
LATE_LIVE_TICKET_STATUSES = frozenset(
    {
        TicketStatus.OPEN,
        TicketStatus.ACKNOWLEDGED,
        TicketStatus.IN_PROGRESS,
        TicketStatus.ON_HOLD,
        TicketStatus.REOPENED_BY_ADMIN,
    }
)

#: An extra work that is finished or will not happen — the same set
#: `ExtraWorkRequest.is_overdue` treats as never late.
_EW_DONE_STATUSES = frozenset(
    {
        ExtraWorkStatus.COMPLETED,
        ExtraWorkStatus.CANCELLED,
        ExtraWorkStatus.CUSTOMER_REJECTED,
    }
)


def local_date(value) -> datetime.date | None:
    """The LOCAL calendar date of an aware datetime — `timezone.localtime`
    rather than `.date()` on the stored UTC value, so a 00:30 Amsterdam
    slot is not filed under the previous day."""
    if value is None:
        return None
    return timezone.localtime(value).date()


class LatenessIndex:
    """See the module docstring. Three queries for any number of rows:
    the tickets with their widest slot window, the hour sums, and the
    escalation rows (phase 2)."""

    def __init__(self, ticket_ids, extra_work_rows, today):
        from timesheets.models import HourSource, TimeEntry

        self.today = today
        self._tickets: dict[int, late_rules.Lateness] = {}
        self._extra_work: dict[int, late_rules.Lateness] = {}
        # W-LATE §2 — the steps the ladder has spoken for each ticket,
        # with the display names of the people each step reached.
        self._steps: dict[int, list[dict]] = {}

        ticket_ids = {tid for tid in ticket_ids if tid is not None}
        ew_rows = list(extra_work_rows)
        ew_ids = {row.id for row in ew_rows}

        tickets = []
        if ticket_ids:
            tickets = list(
                Ticket.objects.filter(id__in=ticket_ids)
                .select_related("extra_work_request")
                .annotate(
                    slot_window_end=Max(
                        Coalesce(
                            "staff_assignments__scheduled_end_at",
                            "staff_assignments__scheduled_start_at",
                        ),
                        filter=~Q(
                            staff_assignments__slot_status=(
                                StaffAssignmentSlotStatus.CANCELLED
                            )
                        ),
                    )
                )
            )
        ticket_ew_ids = {
            t.extra_work_request_id
            for t in tickets
            if t.extra_work_request_id is not None
        }

        hours: dict[tuple[str, int], object] = {}
        source_q = Q()
        if ticket_ids:
            source_q |= Q(
                source_type=HourSource.TICKET, source_id__in=list(ticket_ids)
            )
        wanted_ew = ew_ids | ticket_ew_ids
        if wanted_ew:
            source_q |= Q(
                source_type=HourSource.EXTRA_WORK, source_id__in=list(wanted_ew)
            )
        if source_q:
            for row in (
                TimeEntry.objects.filter(source_q)
                .values("source_type", "source_id")
                .annotate(total=Sum("hours"))
            ):
                hours[(row["source_type"], row["source_id"])] = row["total"]

        def hours_for(kind, key):
            value = hours.get((kind, key))
            return value if value is not None else late_rules.ZERO_HOURS

        for ticket in tickets:
            own_end = local_date(
                ticket.scheduled_end_at or ticket.scheduled_start_at
            )
            slot_end = local_date(ticket.slot_window_end)
            ends = [d for d in (own_end, slot_end) if d is not None]
            booked = hours_for(HourSource.TICKET, ticket.id)
            if ticket.extra_work_request_id is not None:
                booked = booked + hours_for(
                    HourSource.EXTRA_WORK, ticket.extra_work_request_id
                )
            self._tickets[ticket.id] = late_rules.assess(
                planned_start=local_date(ticket.scheduled_start_at),
                planned_end=max(ends) if ends else None,
                deadline=getattr(ticket.extra_work_request, "deadline", None),
                done=(
                    ticket.status not in LATE_LIVE_TICKET_STATUSES
                    or ticket.archived_at is not None
                    or ticket.deleted_at is not None
                ),
                hours_booked=booked,
                today=today,
            )
        for row in ew_rows:
            self._extra_work[row.id] = late_rules.assess(
                planned_start=row.preferred_date,
                planned_end=row.planned_end_date,
                deadline=row.deadline,
                done=row.status in _EW_DONE_STATUSES,
                hours_booked=hours_for(HourSource.EXTRA_WORK, row.id),
                today=today,
            )
        # W-LATE follow-up — an extra-work row speaks for a job whose
        # spawned ticket nobody holds a live slot on (W-FIX1 A1), and
        # the ladder spoke about THAT ticket. So the row carries the
        # ticket's steps: the promise is one, whichever record fronts
        # it on the board.
        self._spawned: dict[int, list[int]] = {}
        if ew_ids:
            for ticket_id, ew_id in Ticket.objects.filter(
                extra_work_request_id__in=list(ew_ids), deleted_at__isnull=True
            ).values_list("id", "extra_work_request_id"):
                self._spawned.setdefault(ew_id, []).append(ticket_id)
        step_ticket_ids = set(ticket_ids)
        for spawned in self._spawned.values():
            step_ticket_ids.update(spawned)
        if step_ticket_ids:
            self._load_steps(step_ticket_ids)

    def _load_steps(self, ticket_ids):
        """One query for the rows, one for the names. The names are
        DISPLAY names resolved now, from the ids the step reached — the
        addendum's rule: recipients by role in code, people by name on
        the screen."""
        from accounts.models import User

        rows = list(
            TicketEscalation.objects.filter(ticket_id__in=list(ticket_ids))
            .order_by("notified_at", "id")
        )
        if not rows:
            return
        wanted: set[int] = set()
        for row in rows:
            wanted.update(int(uid) for uid in (row.recipient_ids or []))
        names = {}
        if wanted:
            for user in User.objects.filter(id__in=list(wanted)).only(
                "id", "full_name", "email"
            ):
                names[user.id] = (user.full_name or "").strip() or user.email
        for row in rows:
            self._steps.setdefault(row.ticket_id, []).append(
                {
                    "step": row.step,
                    "notified_at": row.notified_at.isoformat(),
                    "names": [
                        names[int(uid)]
                        for uid in (row.recipient_ids or [])
                        if int(uid) in names
                    ],
                }
            )

    def steps_for_ticket(self, ticket_id) -> list[dict]:
        return list(self._steps.get(ticket_id, []))

    def lateness_dict(self, *, ticket_id=None, extra_work=None) -> dict:
        """The wire shape: the ladder's facts plus the steps that spoke."""
        if ticket_id is not None:
            data = self.for_ticket(ticket_id).as_dict()
            data["escalation_steps"] = self.steps_for_ticket(ticket_id)
            return data
        data = (
            self.for_extra_work(extra_work) if extra_work is not None
            else late_rules.NOT_LATE
        ).as_dict()
        steps: list[dict] = []
        if extra_work is not None:
            for ticket_id in self._spawned.get(extra_work.id, []):
                steps.extend(self.steps_for_ticket(ticket_id))
        steps.sort(key=lambda s: s["notified_at"])
        data["escalation_steps"] = steps
        return data

    def for_ticket(self, ticket_id) -> late_rules.Lateness:
        return self._tickets.get(ticket_id, late_rules.NOT_LATE)

    def for_extra_work(self, extra_work) -> late_rules.Lateness:
        return self._extra_work.get(extra_work.id, late_rules.NOT_LATE)

    def for_entry(self, entry: dict) -> late_rules.Lateness:
        if entry["ticket_id"] is not None:
            return self.for_ticket(entry["ticket_id"])
        return self._extra_work.get(entry["extra_work_id"], late_rules.NOT_LATE)


__all__ = ["LATE_LIVE_TICKET_STATUSES", "LatenessIndex", "local_date"]
