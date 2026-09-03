"""W-VIEWER §1 — THE JOB'S OWN PLANNED WINDOW, resolved once.

The owner's ruling of 2026-08-27 replaces W-PLANTRUTH §1a. That wave
decided "one fact places the board: the planned day of the WORK, which
is the slot's (or a part's)" and applied it to every reader. Measured on
crmtest the same day, that is what put TCK-2026-000361 — a job the
ticket schedules for 7 September — on 29 August, because one of Ahmet's
four slots carried 29 August; and TCK-2026-000342, scheduled for
30 August, on today's column stamped "Planned 26 Aug — 1 day late",
because Ahmet's slot window ended on the 26th.

The ruling: THOSE ARE TWO DIFFERENT FACTS AND BOTH ARE TRUE.

    the job's scheduled date        when the ticket itself is to happen
    a staff member's working date   when THAT person is to work on it

So there is no single universal placement rule. There are two, chosen by
who is reading:

    SA / PA / MANAGER   the JOB — one card per ticket, on the ticket's
                        own scheduled date. Five people on it is still
                        one card.
    STAFF (own week)    their OWN slots and their OWN parts, each on the
                        date they were given.

This module owns the first half: given a ticket, WHICH DATE IS THE
JOB'S. `views_work_plan.py` places the board with it and
`lateness_index.py` judges lateness with it, so the board and the ladder
cannot disagree about which day a job belongs to — the exact drift the
ruling closes.

THE FALLBACK CHAIN, and why each link is the field it is
--------------------------------------------------------
`Ticket.scheduled_start_at` is the answer. Its own docstring
(`models.py`) calls it "the planned start of the on-site work", and
`TicketStatus.ACKNOWLEDGED` says out loud that WHEN the work is due "is
already owned by `scheduled_start_at`". It is THE field.

It is nullable, and on crmtest 9 of the 54 extra-work-born tickets carry
no value in it, so a fallback is needed and the ruling asks for the
field's business meaning to be reconfirmed before one is picked. In
`extra_work/models.py` §"the six dates":

    preferred_date          the customer's WISH (Sprint 176 §3)
    planned_end_date        the last day of the asked-for window
    provider_planned_date   the provider's COMMITMENT to a day (W2-D)
    provider_planned_end_date   the last day of the committed window
    deadline                what was promised — never a placement date

`provider_planned_date` is therefore the right second link: it is the
same KIND of fact as `scheduled_start_at` — the provider saying when it
will do the work — and `extra_work/dates.py` records that a write to it
pushes the spawned tickets' schedules (Sprint 184 §1), so the two are
the same commitment seen from either end.

`preferred_date` — the customer's WISH — is NOT a link any more.
P-15 §0.4 extends the P-14 A5 ruling (a wish is not a plan) from the
extra-work rows to the tickets they spawn: one placement law, no
exceptions. A ticket whose only date is the wish has NO window, sits in
the Not-planned strip, and the strip states the wish as a FACT
("Wished for {date}" — `job_wish_day` carries it). Before P-15 the wish
was the third link "so a request and its spawned ticket sit on the same
day" — both now sit in the strip, which still satisfies that reason.

Past the provider's plan: NOTHING. A job with no date is undated, and
the undated lane is where it goes. An unrelated staff slot is never
promoted into the job's date — "if there is no valid placement date, do
not invent one", verbatim.

The one deliberate exception is LATENESS: the ladder keeps the wish
(`lateness_index.py`) — a wished day passing unplanned is exactly its
business. That is why `job_wish_window` exists as a named accessor
rather than the wish silently vanishing from every reader.

THE DUE DATE is the extra work's `deadline` where one exists and the
window's last day otherwise. Unchanged from Sprint 184 §2, restated here
so one module answers every date question about a job.

TWO EXPRESSIONS, ONE RULE. `job_window` is the Python; `with_job_dates`
annotates the identical chain onto a queryset so the counts can be
answered in SQL without loading the rows. `WorkPlanRuleParityTests`
asserts the two agree, the same way it already does for the slot rule.
"""
from __future__ import annotations

import datetime

from django.db.models import Case, DateField, F, Q, When
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from .plan_provenance import OWN_PLAN, ticket_has_own_plan, with_own_plan


def local_date(value) -> datetime.date | None:
    """The LOCAL calendar date of an aware datetime.

    `timezone.localtime` rather than `.date()` on the stored UTC value: a
    ticket scheduled for 00:00 Amsterdam is stored as 22:00 the previous
    day in UTC, and reading `.date()` off that files it under the wrong
    day — and, on a Monday, under the wrong week. TCK-2026-000364 is
    exactly that row (`2026-08-30 22:00Z` = 31 August local), so the
    distinction is not hypothetical here.
    """
    if value is None:
        return None
    return timezone.localtime(value).date()


def job_window(ticket) -> tuple[datetime.date | None, datetime.date | None]:
    """`(start, end)` — the job's own planned window, or `(None, None)`.

    The pair is taken from ONE source, never mixed: a ticket that carries
    a start but no end has no end, rather than borrowing the extra work's.
    Mixing them would print a window neither record ever stated.
    """
    # P-1 — the column counts only when a person (or the recurring plan)
    # stands behind it. A seeded `scheduled_start_at` with no schedule
    # row and no occurrence is a PHANTOM and is read as absent, so the
    # chain falls through to what the extra work actually states (see
    # `plan_provenance.py`).
    if ticket_has_own_plan(ticket):
        start = local_date(ticket.scheduled_start_at)
        if start is not None:
            return start, local_date(ticket.scheduled_end_at)
    extra_work = getattr(ticket, "extra_work_request", None)
    if extra_work is None:
        return None, None
    if extra_work.provider_planned_date is not None:
        return (
            extra_work.provider_planned_date,
            extra_work.provider_planned_end_date,
        )
    # P-15 §0.4 — the customer's wish is NOT a window. See the module
    # docstring; the ladder reads it through `job_wish_window` instead.
    return None, None


def job_wish_window(
    ticket,
) -> tuple[datetime.date | None, datetime.date | None]:
    """The customer's WISH as a (start, end) pair, or `(None, None)`.

    Named and separate from `job_window` on purpose (P-15 §0.4): the
    wish never places a board, but two readers still state it — the
    Not-planned strip's "Wished for {date}" fact and the lateness
    ladder, whose business a passed unplanned wish exactly is. Answers
    only when the wish is the job's ONLY date: a provider plan or an
    own schedule outranks and silences it.
    """
    if ticket_has_own_plan(ticket) and ticket.scheduled_start_at is not None:
        return None, None
    extra_work = getattr(ticket, "extra_work_request", None)
    if extra_work is None or extra_work.provider_planned_date is not None:
        return None, None
    return extra_work.preferred_date, extra_work.planned_end_date


def job_wish_day(ticket) -> datetime.date | None:
    """The strip's fact: the wished day, when the wish is all there is."""
    return job_wish_window(ticket)[0]


#: FE-4 (Addendum D SS D.12 item 2) -- WHERE a job's window came from, so
#: a card can say "Gepland" only when somebody planned it. The three
#: branches of `job_window`, named: the ticket's own schedule, the extra
#: work's provider commitment, or the customer's WISH -- which is a wish,
#: never a plan, and is captioned as one.
PLAN_SOURCE_TICKET = "TICKET"
PLAN_SOURCE_PROVIDER_PLAN = "PROVIDER_PLAN"
PLAN_SOURCE_CUSTOMER_WISH = "CUSTOMER_WISH"


def job_plan_source(ticket) -> str | None:
    """WHERE the job's dates come from, or None when it has none at all.

    P-15 §0.4 — deliberately WIDER than `job_window` now: the
    `CUSTOMER_WISH` branch survives as the CAPTION source (the strip's
    "Wished for {date}" fact) even though the wish no longer yields a
    window. The first two branches still mirror `job_window`."""
    if ticket_has_own_plan(ticket):
        return PLAN_SOURCE_TICKET
    extra_work = getattr(ticket, "extra_work_request", None)
    if extra_work is None:
        return None
    if extra_work.provider_planned_date is not None:
        return PLAN_SOURCE_PROVIDER_PLAN
    if extra_work.preferred_date is not None:
        return PLAN_SOURCE_CUSTOMER_WISH
    return None


def job_window_end(ticket) -> datetime.date | None:
    """The last planned day: the end, or the start when there is none —
    `work_plan.Job.window_end`'s single-planned-day reading."""
    start, end = job_window(ticket)
    return end or start


def job_deadline(ticket) -> datetime.date | None:
    """The REAL deadline behind this job, or None.

    Read through the canonical FK exactly as Sprint 184 §2 established,
    never copied onto the ticket, so editing the deadline on the extra
    work moves this in the same instant.
    """
    return getattr(
        getattr(ticket, "extra_work_request", None), "deadline", None
    )


def job_due(ticket) -> datetime.date | None:
    """What decides late for this job: the deadline, else the last
    planned day. A job with neither is never late — nobody said when it
    was due, and inventing a due date to call something late is worse
    than not marking it."""
    deadline = job_deadline(ticket)
    if deadline is not None:
        return deadline
    return job_window_end(ticket)


# --- the same chain, in SQL ------------------------------------------

#: The annotation names `with_job_dates` adds. Named here so a predicate
#: cannot typo one into a silent `None`.
JOB_START = "job_start"
JOB_END = "job_end"
JOB_WINDOW_END = "job_window_end"

_EW = "extra_work_request"


def with_job_dates(queryset):
    """Annotate `job_start` / `job_end` / `job_window_end` onto a TICKET
    queryset — the SQL twin of `job_window`.

    `job_end` is a `Case` rather than a third `Coalesce` on purpose: the
    branch that supplies the start must supply the end, which is what
    keeps a ticket's start from being paired with an extra work's end.
    `TruncDate` takes the current timezone, which is the same conversion
    `local_date` does.

    P-15 §0.4 — the wish legs (`preferred_date` / `planned_end_date`)
    are GONE, mirroring `job_window`: a wish-only ticket has NULL
    `job_start` and falls to the Not-planned strip.
    """
    # P-1 — the SQL twin of `ticket_has_own_plan`: the ticket's own
    # column is read only behind a schedule row or an occurrence.
    own = Q(scheduled_start_at__isnull=False) & (
        Q(planned_occurrence__isnull=False) | Q(**{OWN_PLAN: True})
    )
    return with_own_plan(queryset).annotate(
        **{
            JOB_START: Coalesce(
                Case(
                    When(own, then=TruncDate("scheduled_start_at")),
                    output_field=DateField(),
                ),
                F(f"{_EW}__provider_planned_date"),
                output_field=DateField(),
            ),
            JOB_END: Case(
                When(own, then=TruncDate("scheduled_end_at")),
                When(
                    **{f"{_EW}__provider_planned_date__isnull": False},
                    then=F(f"{_EW}__provider_planned_end_date"),
                ),
                output_field=DateField(),
            ),
        }
    ).annotate(
        **{
            JOB_WINDOW_END: Coalesce(
                F(JOB_END), F(JOB_START), output_field=DateField()
            )
        }
    )


def job_due_q(lookup: str, value: datetime.date) -> Q:
    """`due <lookup> value` — the SQL twin of `job_due`.

    Two POSITIVE branches rather than one negated branch, for the reason
    `_slot_due_q` gives next door: `deadline__isnull=True` over a
    nullable FK chain is true both when the ticket has no extra work at
    all and when it has one with no deadline, which is exactly the set
    that should fall back to the planned window.
    """
    return (
        Q(**{f"{_EW}__deadline__isnull": False})
        & Q(**{f"{_EW}__deadline__{lookup}": value})
    ) | (
        Q(**{f"{_EW}__deadline__isnull": True})
        & Q(**{f"{JOB_WINDOW_END}__{lookup}": value})
    )


__all__ = [
    "JOB_END",
    "JOB_START",
    "JOB_WINDOW_END",
    "job_deadline",
    "job_due",
    "job_due_q",
    "job_window",
    "job_window_end",
    "job_wish_day",
    "job_wish_window",
    "local_date",
    "with_job_dates",
]
