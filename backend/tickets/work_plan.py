"""
Sprint 179A — the week-placement rule, written ONCE.

`docs/product/system-business-logic-and-workflows.md` §12B recorded this
rule as DECIDED and not implemented, and it stayed that way for five
sprints. This module is the rule; `views_work_plan.py` is the HTTP
surface over it, and nothing else is allowed to re-derive it.

**The question it answers.** Given a job with a planned window, a due
date and a state, which week(s) does it appear in — and, when it appears
somewhere other than its planned week, WHY?

    1. Planned placement.  A job appears in the week(s) its planned
       window covers. That is its home and it stays there whatever its
       status, so September shows September's work.
    2. Overdue work lives in the OVERDUE strip ("Overdue, any week"),
       marked with how late it is. It is NOT copied onto today's column.
    3. Undated work lives in the UNDATED lane ("Not planned yet"). It is
       NOT copied onto today's column either.
    4. Untouched future work does NOT clutter today. It appears only in
       its planned week, plus the separate "upcoming" list.

W-FIX1 E2 (audit F20) — before this, a STARTED job and an OVERDUE job
were ALSO placed on today's column of the current week ("active" and
"overdue" placements). Measured on crmtest: today's column read "20
jobs" and held work planned for June, August 5th, August 14th and next
week, plus undated extra work — a catch-all nobody could read. The day
column now holds work PLANNED FOR that day and nothing else; the two
strips that already existed carry the rest. `PLACEMENT_OVERDUE` and the
STARTED placements survive as the reason stamped on a strip's rows.

W-PLANTRUTH §1b (owner ruling, 2026-08-27) — THE DISPLAY ROLLS, THE
DATE DOES NOT. A card whose planned day has passed and whose work is
still PENDING (rule 5 below) is no longer shown in that past column: it
is shown in TODAY's column, stamped `PLACEMENT_ROLLED`, carrying the day
it was planned for and how many days late it is. It stays there every
day until the work is done. A PAST day column therefore shows only work
that is finished (done, or otherwise closed) — undone work never lingers
in yesterday. Nothing is written: the planned date on the record is the
same date it always was, which is what the badge prints.

    5. Pending work planned for a day that has passed rolls forward to
       today's column (current week only), marked with its planned day.
       Past columns show finished work only.

W-VIEWER (owner ruling, 2026-08-27) — TWO READERS, TWO PLACEMENT FACTS.
The job's scheduled date and one staff member's assigned working date
are DIFFERENT facts, and the previous wave's "one fact places the board"
collapsed them: a job the ticket scheduled for 7 September was filed
under 29 August because one of its four slots carried that day. So the
CALLER now decides which fact it hands in — `views_work_plan.py` builds
a `Job` from the ticket's own schedule for a manager's board and from
the viewer's own slot for their own week (`tickets/job_dates.py` owns
the first resolution). This module is unchanged in what it decides; it
simply no longer assumes there is only one date to decide it from.

    6. A planned window that CONTAINS today hangs on today's column,
       so a job planned across a fortnight is on the day it is being
       worked rather than on the day the fortnight opened.

WP-1 G0 (Addendum D §D.11.2) — THE SAME-WEEK HALF OF CARRY-FORWARD.
Rule 5 rolls a job whose planned window has CLOSED onto today. What it
could not catch is a job whose window still covers the current week but
whose DUE DATE has already passed — planned Monday-to-Friday, deadline
Tuesday, read on Thursday. Planned placement used to win outright, so
the card sat at home with nothing but a flag on it. In the CURRENT week
only, an overdue-and-open job is now stamped OVERDUE even when its
planned window covers this week, and `day_for` hangs it on today's
column like every other non-planned placement. Past and future weeks
keep planned placement: September still shows September's work, and a
job that was late in its own week is shown there as history, at home.

    7. In the current week, overdue-and-open beats planned: the card is
       marked OVERDUE on today's column, carrying its planned day and
       how late it is. Any other week keeps rule 1 unchanged.

P-1 §3 (2026-08-29) — WORK WAITING FOR A MANAGER DOES NOT ROT IN THE
PAST. A ticket in WAITING_MANAGER_REVIEW is not pending (the worker is
done) and not over (nobody confirmed), and the board read "not pending"
as "settled": the card sat calm on the day the worker finished and
slid into last week while the billing chain stayed broken at the
manager. `awaits_review` names that state; a manager's board hangs such
a job on today's column, marked REVIEW with its waiting age, until it
is confirmed. A worker's own completed slot is unchanged.

    8. In the current week, a job waiting for review hangs on today's
       column for readers who can review it, marked with how long it
       has waited. Past and future weeks keep rule 1.

P-3 §A.1 (2026-08-29) — WORK WAITING ON THE CUSTOMER IS NOT IN A DAY
COLUMN. A ticket in WAITING_CUSTOMER_APPROVAL is over for the provider
side and not over for the record, and the board read it as settled:
the calm card sat in the column of its planned day. On the CURRENT
week that is a finished-looking card in a past column with nothing
left to do on it, and the owner — the system's own designer — needed
three days to understand why it was there. `views_work_plan.py` owns
the predicate (`_ticket_waiting_customer_q` and its slot twin) because
it is a ticket-status fact, not a date fact this module can express.

    9. In the current week, a job waiting on the customer is in no
       column: it is one row behind the "Wacht op klant" chip, whole
       scope, like the undated lane. Past and future weeks keep rule 1
       as history.

**Why a normalised `Job` instead of two copies of the rule.** The two
sources are a dated ticket slot (`TicketStaffAssignment`) and an extra
work request (`ExtraWorkRequest`). They share no model, no state machine
and no date field NAMES — but they answer the same four questions, so
they are flattened onto the same four attributes here and the rule is
written against those. The alternative is the same date arithmetic in
two modules, which is precisely how a screen ends up marking a row late
that another screen calls on time.

Pure functions over `datetime.date`. No Django, no DRF, no querysets —
so the rule can be tested directly, without a request.
"""
from __future__ import annotations

import dataclasses
import datetime


# --- The normalised state of a job -----------------------------------
#
# Deliberately NOT the slot's `slot_status` nor the extra work's
# `status`: those two enums disagree about almost everything. What the
# week view needs is the four buckets below, and each source maps its
# own enum onto them once (see `views_work_plan.py`).

STATE_OPEN = "OPEN"
STATE_IN_PROGRESS = "IN_PROGRESS"
STATE_DONE = "DONE"
STATE_BLOCKED = "BLOCKED"

#: Work that is finished or will not happen. Never late, never dragged
#: into the current week by rules 2 and 3.
CLOSED_STATES = frozenset({STATE_DONE, STATE_BLOCKED})


# --- Why a card is in the week it is in -------------------------------

#: Its planned window covers this week. Its home; no marker needed.
PLACEMENT_PLANNED = "PLANNED"
#: Started, and its planned window opens AFTER this week. The father's
#: example: entered today, started today, planned for September.
PLACEMENT_STARTED_EARLY = "STARTED_EARLY"
#: Started, and its planned window already opened. Carried into now.
PLACEMENT_STARTED = "STARTED"
#: Past its due date and unfinished.
PLACEMENT_OVERDUE = "OVERDUE"
#: W-PLANTRUTH §1b — planned for a day that has passed, still pending,
#: shown on TODAY's column instead. The card carries the day it was
#: planned for (`rolled_from`) and how far past it we are (`rolled_days`).
PLACEMENT_ROLLED = "ROLLED"

#: P-1 §3 — the staff finished, a manager has not confirmed. The job is
#: not pending (nobody is expected to WORK it) and it is not over (the
#: chain slot done -> ticket confirmed -> billing month is broken at
#: the manager). It used to sit settled on its planned day and slide
#: into the past; for the reader who CAN confirm it, it is on today's
#: column until they do, carrying how long it has waited
#: (`stuck_age_days`). A worker's own completed slot is unchanged: it
#: stays settled on its own day.
PLACEMENT_REVIEW = "REVIEW"

#: Every placement that is NOT the job's planned week. §12B: "A card
#: shown outside its planned week must say why." The frontend keys its
#: marker off exactly this set, so adding a placement without adding a
#: marker for it is a one-line, visible mistake rather than a silent one.
PLACEMENTS_NEEDING_A_REASON = frozenset(
    {
        PLACEMENT_STARTED_EARLY,
        PLACEMENT_STARTED,
        PLACEMENT_OVERDUE,
        PLACEMENT_ROLLED,
        PLACEMENT_REVIEW,
    }
)


@dataclasses.dataclass(frozen=True)
class Job:
    """The four things the rule needs, and nothing else.

    `planned_start` / `planned_end` — the planned WINDOW. A one-day job
    has `planned_end is None`; the rule reads that as "ends the day it
    starts" rather than "no end", because a window with a start and no
    end is a single planned day (Sprint 177 §1 settled the same reading
    for the label).

    `due` — the date that decides late. For extra work that is the
    `deadline`; for a ticket slot there is no deadline column, so it is
    the last planned day. Both are "the date this was supposed to be
    finished by", which is the only property the rule uses.

    `state` — one of the four buckets above.
    """

    planned_start: datetime.date | None
    planned_end: datetime.date | None
    due: datetime.date | None
    state: str
    #: W-PLANTRUTH §1b — is somebody still expected to do this work? For
    #: a slot: ASSIGNED on a ticket whose work is still open (the ladder's
    #: `LATE_LIVE_TICKET_STATUSES`); for an extra work: not finished,
    #: cancelled or rejected. Distinct from `state`: a slot can read OPEN
    #: on a ticket that is already in review, and that slot is not
    #: pending — nobody is expected to work it any more. Defaults from
    #: `state` so the rule tests that build a bare `Job` keep reading.
    pending: bool | None = None
    #: P-1 §3 — the day the work was handed to a manager for review, on
    #: a job that is still waiting for that review. Only the JOB builder
    #: sets it (a manager's board); a worker's slot never carries it.
    review_since: datetime.date | None = None

    @property
    def window_end(self) -> datetime.date | None:
        """The last planned day: the end, or the start when there is no
        end. `None` only when the job has no planned window at all."""
        return self.planned_end or self.planned_start

    @property
    def is_pending(self) -> bool:
        if self.pending is not None:
            return self.pending
        return self.state not in CLOSED_STATES


def is_overdue(job: Job, today: datetime.date) -> bool:
    """Past its due date and unfinished.

    Mirrors `ExtraWorkRequest.is_overdue` exactly — a record with no due
    date is never overdue (nobody said when it was due, and inventing a
    due date to call something late is worse than not marking it), and
    finished or cancelled work is never late whatever its date says.
    """
    if job.due is None:
        return False
    if job.state in CLOSED_STATES:
        return False
    return job.due < today


def is_started(job: Job) -> bool:
    """Work has begun and has not finished.

    DONE is deliberately not "started" for placement purposes: rule 2
    exists so live work is visible today, and finished work is not live.
    It still shows in its planned week through rule 1.
    """
    return job.state == STATE_IN_PROGRESS


def covers_week(
    job: Job, week_start: datetime.date, week_end: datetime.date
) -> bool:
    """Rule 1 — does the planned window overlap this week?"""
    if job.planned_start is None:
        return False
    end = job.window_end or job.planned_start
    return job.planned_start <= week_end and end >= week_start


def placement_for(
    job: Job,
    week_start: datetime.date,
    week_end: datetime.date,
    today: datetime.date,
) -> str | None:
    """Which placement puts `job` in this week, or `None` for "it does
    not belong here".

    Order matters and is the rule's, not an implementation detail:

    * WP-1 G0 (rule 7) — in the CURRENT week, overdue-and-open beats
      planned. A late job's card must not sit quietly at home while the
      deadline recedes; it is a visitor on today's column, marked, until
      someone finishes, reschedules or cancels it.
    * In any OTHER week, planned placement wins outright. A job in its
      own past or future week is at home and needs no marker, even when
      it is also late — the `is_overdue` flag still marks the card, but
      the card is not a visitor. September shows September's work.
    """
    if covers_week(job, week_start, week_end):
        if week_start <= today <= week_end and is_overdue(job, today):
            return PLACEMENT_OVERDUE
        return PLACEMENT_PLANNED

    # W-FIX1 E2 — that is the whole rule for a week. A started or late
    # job that is not planned in this week is NOT a visitor on today's
    # column: the overdue strip and the undated lane carry it, and the
    # strip stamps the reason (`fallback_placement` in the view).
    return None


def day_for(
    job: Job,
    placement: str,
    week_start: datetime.date,
    week_end: datetime.date,
    today: datetime.date,
) -> datetime.date:
    """Which of the seven day columns the card hangs on.

    Planned placement uses the first planned day that falls INSIDE the
    week, so a job spanning Friday to Tuesday appears on Friday in one
    week and on Monday in the next rather than vanishing from the
    second. Every other placement is about now, so it hangs on today.

    W-VIEWER §4 — A LIVE WINDOW HANGS ON TODAY. Rule 6: when the planned
    window CONTAINS today and today is in this week, the card is on
    today's column, not on the window's first day. A job planned
    1 September to 10 September is work somebody is expected to be doing
    on the 4th; parking its only card on the 1st for the whole run puts
    live work in a column the reader has already walked past, which is
    the same complaint rule 5 answers for a window that has closed.
    Rule 5 (rolled) and this one are the two halves of one sentence: the
    card is where the work is, which is today, until it is done.
    """
    if placement != PLACEMENT_PLANNED or job.planned_start is None:
        return today if week_start <= today <= week_end else week_start
    if week_start <= today <= week_end and covers_today(job, today):
        return today
    return max(job.planned_start, week_start)


def covers_today(job: Job, today: datetime.date) -> bool:
    """Rule 6 — is today inside the planned window, with the work still
    pending? Finished work stays in the column it was finished in."""
    if job.planned_start is None:
        return False
    if not job.is_pending:
        return False
    end = job.window_end or job.planned_start
    return job.planned_start <= today <= end


def rolls_forward(job: Job, today: datetime.date) -> bool:
    """Rule 5 — planned for a day that has passed, and still pending.

    A job with no planned window cannot roll: it belongs to the undated
    lane. Finished work never rolls: its past column is where it was
    done. The comparison is against the window END — a job planned
    Monday-to-Wednesday is not late on Tuesday.
    """
    end = job.window_end
    if end is None:
        return False
    if not job.is_pending:
        return False
    return end < today


def rolled_days(job: Job, today: datetime.date) -> int | None:
    """How many whole days past its planned day a rolled card is, or
    None when it does not roll. The number the card prints beside the
    planned day: "Planned 25 Aug — 2 days late"."""
    if not rolls_forward(job, today):
        return None
    return (today - job.window_end).days


def awaits_review(job: Job) -> bool:
    """Rule 8 (P-1 §3) — finished by the worker, not yet confirmed by a
    manager. Such a job is neither pending nor over, so neither rule 5
    nor the settled look fits it; in the current week it hangs on
    today's column for the reader who can confirm it."""
    return job.review_since is not None


def review_days(job: Job, today: datetime.date) -> int | None:
    """How many whole days the job has waited for review, or None when
    it is not waiting. The number the card prints: "Wacht op controle —
    al 5 dagen"."""
    if not awaits_review(job):
        return None
    return max((today - job.review_since).days, 0)


def is_upcoming(
    job: Job, week_end: datetime.date, today: datetime.date
) -> bool:
    """Rule 4's other half — the "planned / upcoming" list.

    Untouched work planned AFTER the week on screen. Not started, not
    late, not finished: a job that is any of those is already on the
    week itself and listing it again as "upcoming" would double-count
    it in a number the operator is meant to trust.
    """
    if job.planned_start is None:
        return False
    if job.planned_start <= week_end:
        return False
    if job.state != STATE_OPEN:
        return False
    return not is_overdue(job, today)


def overdue_days(job: Job, today: datetime.date) -> int | None:
    """How many whole days late, or `None` when it is not late.

    "Late" without "how late" does not rank, and the overdue list is
    ordered by it.
    """
    if not is_overdue(job, today) or job.due is None:
        return None
    return (today - job.due).days


def days_to_due(job: Job, today: datetime.date) -> int | None:
    """W-VIEWER §5 — how the reader stands against the promise.

    Signed and whole: `3` is three days left, `0` is today, `-2` is two
    days past. `None` when nothing was promised.

    "Late or not" was the only thing a card said before this, and it says
    it one day too late to act on. A number that counts DOWN as well as
    up is what lets somebody read their own standing without opening the
    ticket, which is what the ruling asks the card to do.
    """
    if job.due is None:
        return None
    # FE-4 (Addendum D SS D.12 item 4) -- finished or settled work stops
    # counting. A closed job "3 days over its deadline" is history, not
    # pressure, and the detail's own countdown (`detail_facts.ticket_due`)
    # already answered None for it: the card and the detail must agree.
    if not job.is_pending:
        return None
    return (job.due - today).days


def iso_week_bounds(iso_year: int, iso_week: int) -> tuple[
    datetime.date, datetime.date
]:
    """Monday and Sunday of an ISO week.

    `date.fromisocalendar` is the stdlib's own inverse of
    `date.isocalendar()`, which is what the frontend's `isoWeek.ts`
    reimplements in TypeScript — so both sides agree on the weeks that
    make a naive "day-of-year / 7" wrong (2027-01-01 is week 53 of
    2026).
    """
    monday = datetime.date.fromisocalendar(iso_year, iso_week, 1)
    return monday, monday + datetime.timedelta(days=6)
