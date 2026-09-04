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
the WIDEST one the WORK carries — every non-cancelled slot's window and
every part's window — and the deadline is the extra work's, read
through the canonical link exactly as `views_work_plan._slot_deadline`
reads it.

W-VIEWER (owner ruling, 2026-08-27) — supersedes W-PLANTRUTH §1a, which
had removed the ticket's own date from this window and left the widest
slot window in its place. That is what made TCK-2026-000342 — a job the
ticket schedules for 30 August — read "Planned 26 Aug — 1 day late" on
27 August, off the back of one of Ahmet's three slots. A staff member's
assigned working date is not the job's date, and it must not be able to
call the whole job late.

So the JOB's window is the JOB's: `tickets/job_dates.py`, which is the
same resolver the board places manager cards with, so the ladder and the
board cannot disagree about which day a job belongs to.

The widest slot / part window survives as a FALLBACK and only that: a
ticket that carries no schedule of its own, and no extra work to inherit
one from, has no other stated date, and going silent about it would take
a real late signal away from the escalation sweep. A ticket that DOES
state a date is judged on that date and on nothing else.

A viewer's OWN standing is a different question again, and
`for_window` answers it — the same ladder over the window that viewer
was actually given (their slot, widened by their own parts). Staff read
their own week; they should not be shouted at by a rung measured on
somebody else's day.

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

from django.db.models import Max, Min, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from extra_work.models import ExtraWorkStatus

from . import lateness as late_rules
from .job_dates import job_wish_window
from .job_dates import job_window as resolve_job_window
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
        # W-PLANTRUTH §1a — the FIRST planned day of the work (the
        # earliest slot or part start), for the escalation sweep's
        # persist rule, which used to read the ticket's own date.
        self._planned_start: dict[int, datetime.date | None] = {}
        # W-VIEWER §5 — kept so `for_window` can re-run the SAME ladder
        # over a viewer's OWN window without a second round of queries.
        self._hours: dict[int, object] = {}
        self._done: dict[int, bool] = {}
        self._deadline: dict[int, datetime.date | None] = {}
        # W-LATE §2 — the steps the ladder has spoken for each ticket,
        # with the display names of the people each step reached.
        self._steps: dict[int, list[dict]] = {}

        ticket_ids = {tid for tid in ticket_ids if tid is not None}
        ew_rows = list(extra_work_rows)
        ew_ids = {row.id for row in ew_rows}

        tickets = []
        if ticket_ids:
            not_cancelled = ~Q(
                staff_assignments__slot_status=StaffAssignmentSlotStatus.CANCELLED
            )
            # Two multi-valued joins (slots, parts) in one annotate: the
            # row set is a cross product, which is harmless for Max/Min
            # (it would not be for Sum or Count).
            tickets = list(
                Ticket.objects.filter(id__in=ticket_ids)
                .select_related("extra_work_request")
                .annotate(
                    slot_window_end=Max(
                        Coalesce(
                            "staff_assignments__scheduled_end_at",
                            "staff_assignments__scheduled_start_at",
                        ),
                        filter=not_cancelled,
                    ),
                    slot_window_start=Min(
                        "staff_assignments__scheduled_start_at",
                        filter=not_cancelled,
                    ),
                    part_window_end=Max(
                        Coalesce(
                            "sub_tasks__planned_end_date",
                            "sub_tasks__planned_start_date",
                        )
                    ),
                    part_window_start=Min("sub_tasks__planned_start_date"),
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
            # W-VIEWER — the JOB's own window first. Only when the job
            # states no date anywhere does the widest slot / part window
            # stand in for it (see the module docstring).
            planned_start, planned_end = resolve_job_window(ticket)
            if planned_start is None:
                # P-15 §0.4 — the ladder KEEPS the wish (the A5 ruling's
                # own carve-out: a wished day passing unplanned is
                # exactly the ladder's business), even though the wish
                # no longer places the board. Same branch the EW rows
                # below have always had.
                planned_start, planned_end = job_wish_window(ticket)
            if planned_start is None:
                ends = [
                    d
                    for d in (
                        local_date(ticket.slot_window_end),
                        ticket.part_window_end,
                    )
                    if d is not None
                ]
                starts = [
                    d
                    for d in (
                        local_date(ticket.slot_window_start),
                        ticket.part_window_start,
                    )
                    if d is not None
                ]
                planned_start = min(starts) if starts else None
                planned_end = max(ends) if ends else None
            self._planned_start[ticket.id] = planned_start
            booked = hours_for(HourSource.TICKET, ticket.id)
            if ticket.extra_work_request_id is not None:
                booked = booked + hours_for(
                    HourSource.EXTRA_WORK, ticket.extra_work_request_id
                )
            self._hours[ticket.id] = booked
            self._done[ticket.id] = (
                ticket.status not in LATE_LIVE_TICKET_STATUSES
                or ticket.archived_at is not None
                or ticket.deleted_at is not None
            )
            self._deadline[ticket.id] = getattr(
                ticket.extra_work_request, "deadline", None
            )
            self._tickets[ticket.id] = late_rules.assess(
                planned_start=planned_start,
                planned_end=planned_end,
                deadline=self._deadline[ticket.id],
                done=self._done[ticket.id],
                hours_booked=booked,
                today=today,
            )
        for row in ew_rows:
            # P-11 A11 — the ladder reads the PROVIDER's plan when one
            # exists (the row's Plan-it button writes it; P-10 A6 moved
            # every board predicate onto it and left this one on the
            # customer's wish), else the wish — the same branch
            # `views_work_plan._ew_planned_window` takes.
            if row.provider_planned_date is not None:
                ew_start = row.provider_planned_date
                ew_end = row.provider_planned_end_date
            else:
                ew_start = row.preferred_date
                ew_end = row.planned_end_date
            self._extra_work[row.id] = late_rules.assess(
                planned_start=ew_start,
                planned_end=ew_end,
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

    def for_window(
        self,
        ticket_id,
        planned_start,
        planned_end,
        *,
        done: bool | None = None,
    ) -> late_rules.Lateness:
        """W-VIEWER §5 — the same ladder over ONE VIEWER'S OWN window.

        The deadline, the hours and "is the work over" are the job's and
        are reused as loaded; only the planned window differs, because
        that is the only thing that differs between a manager reading the
        job and the person who was given a day on it. `done` overrides
        the job's verdict for a viewer who has finished THEIR part of a
        job that is still running — the case the ruling calls "the card
        can remain visible, but it should look calm".

        A viewer with no window of their own falls back to the job's
        rung: they are still standing on a job, and saying nothing about
        it would be quieter than the truth.
        """
        if ticket_id not in self._tickets:
            return late_rules.NOT_LATE
        if planned_start is None and planned_end is None:
            job = self.for_ticket(ticket_id)
            if done and job.level is not None:
                return late_rules.NOT_LATE
            return job
        return late_rules.assess(
            planned_start=planned_start,
            planned_end=planned_end,
            deadline=self._deadline.get(ticket_id),
            done=self._done.get(ticket_id, False) if done is None else done,
            hours_booked=self._hours.get(ticket_id, late_rules.ZERO_HOURS),
            today=self.today,
        )

    def window_dict(self, ticket_id, planned_start, planned_end, *, done=None) -> dict:
        """`for_window`, on the wire, carrying the job's escalation steps
        — the ladder spoke about the JOB, whoever is reading it."""
        data = self.for_window(
            ticket_id, planned_start, planned_end, done=done
        ).as_dict()
        data["escalation_steps"] = self.steps_for_ticket(ticket_id)
        return data

    def planned_start_for(self, ticket_id) -> datetime.date | None:
        """The first planned day of the work (earliest slot or part
        start), or None when nothing is dated."""
        return self._planned_start.get(ticket_id)

    def for_extra_work(self, extra_work) -> late_rules.Lateness:
        return self._extra_work.get(extra_work.id, late_rules.NOT_LATE)

    def for_entry(self, entry: dict) -> late_rules.Lateness:
        if entry["ticket_id"] is not None:
            return self.for_ticket(entry["ticket_id"])
        return self._extra_work.get(entry["extra_work_id"], late_rules.NOT_LATE)


__all__ = ["LATE_LIVE_TICKET_STATUSES", "LatenessIndex", "local_date"]
