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

#: Every placement that is NOT the job's planned week. §12B: "A card
#: shown outside its planned week must say why." The frontend keys its
#: marker off exactly this set, so adding a placement without adding a
#: marker for it is a one-line, visible mistake rather than a silent one.
PLACEMENTS_NEEDING_A_REASON = frozenset(
    {PLACEMENT_STARTED_EARLY, PLACEMENT_STARTED, PLACEMENT_OVERDUE}
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

    @property
    def window_end(self) -> datetime.date | None:
        """The last planned day: the end, or the start when there is no
        end. `None` only when the job has no planned window at all."""
        return self.planned_end or self.planned_start


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

    * Planned placement wins outright. A job in its own week is at home
      and needs no marker, even when it is also late — the `is_overdue`
      flag still marks the card, but the card is not a visitor.
    * Overdue beats started. A job that is both is more usefully
      described as late than as running.
    """
    if covers_week(job, week_start, week_end):
        return PLACEMENT_PLANNED

    # W-FIX1 E2 — that is the whole rule for a week. A started or late
    # job that is not planned in this week is NOT a visitor on today's
    # column: the overdue strip and the undated lane carry it, and the
    # strip stamps the reason (`fallback_placement` in the view). `today`
    # stays in the signature so the two SQL twins in `views_work_plan`
    # keep taking the same arguments as this function.
    del today
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
    """
    if placement != PLACEMENT_PLANNED or job.planned_start is None:
        return today if week_start <= today <= week_end else week_start
    return max(job.planned_start, week_start)


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
