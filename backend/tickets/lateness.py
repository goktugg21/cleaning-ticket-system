"""W-LATE §1b — the late ladder, written ONCE.

THE LAW OF THE WAVE
-------------------
Planned dates never change by themselves. A job that is not done keeps
its planned date; it reappears in TODAY's late strip every day because
it is unfinished, not because anything moved. Nothing in this module
writes; it only reads dates and says how bad things are.

THE LADDER
----------
    L1  the planned date has passed          (the plan is broken)
    L2  the customer deadline has passed     (the promise is broken)
    L3  quarantine: thirty days past the ANCHOR with ZERO worked hours
        booked — anchor = the deadline, else the planned date.

Each rung is a pure predicate over five facts: the planned window, the
deadline, whether the work is done, how many hours have been booked, and
today. The rung a job stands on is the HIGHEST predicate that holds.

ONE HELPER, ONE OWNER. `views_work_plan.py` asks this for every card,
the late strip and the quarantine bar read the same answer, the day
modal splits "today" from "late" with it, and the phase-2 escalation
sweep fires off the same rungs. A second date comparison anywhere else
is how one screen ends up calling a job late that another calls on time
(`tickets/work_plan.py` says the same about §12B, and for the same
reason).

Pure functions over `datetime.date` and `Decimal`. No Django, no
querysets — testable without a request.
"""
from __future__ import annotations

import dataclasses
import datetime
from decimal import Decimal

#: The three rungs. `None` is "not late at all".
LEVEL_PLANNED_PASSED = 1
LEVEL_DEADLINE_PASSED = 2
LEVEL_QUARANTINE = 3

#: How long a job may sit past its anchor with no hour booked before it
#: is quarantined. Thirty days is the brief's number, verbatim; it is
#: not a setting because a threshold nobody can mis-set is a threshold
#: nobody can mis-set to zero (the deadline reminder makes the same
#: argument about its 48 hours).
QUARANTINE_DAYS = 30

ZERO_HOURS = Decimal("0")


@dataclasses.dataclass(frozen=True)
class Lateness:
    """The facts the ladder produced for one job.

    `planned_date` is the last planned day — the window END, or the
    start when there is no end (the single-planned-day reading
    `work_plan.Job.window_end` uses). It is the date L1 compares
    against, and the date the strip's badge prints: "Gepland <date> — N
    dagen te laat".

    `anchor` is what L3 counts from: the deadline when there is one,
    otherwise the planned date. `anchor_days` is how many days past it
    we are (None when it has not passed, or there is none).
    """

    level: int | None
    planned_date: datetime.date | None
    planned_days_late: int | None
    deadline: datetime.date | None
    deadline_days_late: int | None
    anchor: datetime.date | None
    anchor_days: int | None
    hours_booked: Decimal

    @property
    def is_late(self) -> bool:
        return self.level is not None

    @property
    def days_late(self) -> int | None:
        """The one number a card prints: how late against the PLAN,
        falling back to how late against the deadline for a job that
        has a deadline and no planned date."""
        if self.planned_days_late is not None:
            return self.planned_days_late
        return self.deadline_days_late

    def as_dict(self) -> dict:
        return {
            "level": self.level,
            "planned_date": _iso(self.planned_date),
            "planned_days_late": self.planned_days_late,
            "deadline": _iso(self.deadline),
            "deadline_days_late": self.deadline_days_late,
            "anchor": _iso(self.anchor),
            "anchor_days": self.anchor_days,
            "days_late": self.days_late,
            # Serialised as a string, the way every money/hours amount in
            # this API travels, so the client never rounds it.
            "hours_booked": str(self.hours_booked),
        }


NOT_LATE = Lateness(
    level=None,
    planned_date=None,
    planned_days_late=None,
    deadline=None,
    deadline_days_late=None,
    anchor=None,
    anchor_days=None,
    hours_booked=ZERO_HOURS,
)


def _iso(value: datetime.date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _days_past(value: datetime.date | None, today: datetime.date) -> int | None:
    """Whole days by which `today` is past `value`; None when it is not."""
    if value is None or value >= today:
        return None
    return (today - value).days


def window_end(
    planned_start: datetime.date | None, planned_end: datetime.date | None
) -> datetime.date | None:
    """The last planned day: the end, or the start when there is no
    end. `None` only when the job has no planned window at all."""
    return planned_end or planned_start


def assess(
    *,
    planned_start: datetime.date | None,
    planned_end: datetime.date | None,
    deadline: datetime.date | None,
    done: bool,
    hours_booked: Decimal | None,
    today: datetime.date,
) -> Lateness:
    """Which rung, and the facts behind it.

    `done` is the caller's word for "no work is pending": finished,
    cancelled, sitting in review, or terminal. Done work is never late,
    whatever its dates say — the same rule `work_plan.is_overdue` and
    `ExtraWorkRequest.is_overdue` apply.

    A job with NO planned date and NO deadline cannot be late: nobody
    said when, and inventing a date to call something late is worse
    than not marking it. It lives in the undated lane, which is its own
    kind of warning.
    """
    hours = hours_booked if hours_booked is not None else ZERO_HOURS
    planned_date = window_end(planned_start, planned_end)
    anchor = deadline if deadline is not None else planned_date
    if done:
        return dataclasses.replace(
            NOT_LATE,
            planned_date=planned_date,
            deadline=deadline,
            anchor=anchor,
            hours_booked=hours,
        )

    planned_days_late = _days_past(planned_date, today)
    deadline_days_late = _days_past(deadline, today)
    anchor_days = _days_past(anchor, today)

    level: int | None = None
    if planned_days_late is not None:
        level = LEVEL_PLANNED_PASSED
    if deadline_days_late is not None:
        level = LEVEL_DEADLINE_PASSED
    if (
        anchor_days is not None
        and anchor_days >= QUARANTINE_DAYS
        and hours <= ZERO_HOURS
    ):
        level = LEVEL_QUARANTINE

    return Lateness(
        level=level,
        planned_date=planned_date,
        planned_days_late=planned_days_late,
        deadline=deadline,
        deadline_days_late=deadline_days_late,
        anchor=anchor,
        anchor_days=anchor_days,
        hours_booked=hours,
    )


def sort_key(lateness: Lateness, title: str = "") -> tuple:
    """Left to right, ascending severity: the rung first, then how many
    days late within the rung, then the title so two equal cards keep a
    stable order. Orange leftmost, bordeaux rightmost — the strip reads
    monotonically worse as the eye travels right."""
    return (
        lateness.level or 0,
        lateness.days_late if lateness.days_late is not None else 0,
        title or "",
    )


# ---------------------------------------------------------------------
# W-LATE §3b — a PART's own window, and the four states it can be in.
#
# Kept here rather than in a parts module because it is the same
# vocabulary applied one level down: "the day I was planned for has
# passed and I am not done" is L1 for a job and MISSED for a part.
# ---------------------------------------------------------------------

#: No window on this part: it has nothing to be late against.
PART_STATE_NONE = "NONE"
#: A window that has not closed yet, and today is not its last day.
PART_STATE_OPEN = "OPEN"
#: Today is the LAST day of the window and the part is not done.
PART_STATE_LAST_DAY = "LAST_DAY"
#: The window has closed and the part is not done. Renders red,
#: "niet gedaan op <window end>", and keeps rendering forward until it
#: is done or deleted — it never escalates on its own (§2b).
PART_STATE_MISSED = "MISSED"
#: Done, whatever its window said.
PART_STATE_DONE = "DONE"


def part_state(
    *,
    planned_start: datetime.date | None,
    planned_end: datetime.date | None,
    is_done: bool,
    today: datetime.date,
) -> str:
    if is_done:
        return PART_STATE_DONE
    end = window_end(planned_start, planned_end)
    if end is None:
        return PART_STATE_NONE
    if end < today:
        return PART_STATE_MISSED
    if end == today:
        return PART_STATE_LAST_DAY
    return PART_STATE_OPEN


__all__ = [
    "LEVEL_DEADLINE_PASSED",
    "LEVEL_PLANNED_PASSED",
    "LEVEL_QUARANTINE",
    "Lateness",
    "NOT_LATE",
    "PART_STATE_DONE",
    "PART_STATE_LAST_DAY",
    "PART_STATE_MISSED",
    "PART_STATE_NONE",
    "PART_STATE_OPEN",
    "QUARANTINE_DAYS",
    "assess",
    "part_state",
    "sort_key",
    "window_end",
]
