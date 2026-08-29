"""P-1 (Addendum D §D.12 item 2, second report) — A DATE IS A PLAN ONLY
IF A PERSON MADE IT.

The owner reported the "Planned" bug twice. FE-4 fixed the WORDS on
clean fixtures; on crmtest, TCK-2026-000209 ("ggtg", created 3 June)
still read "Planned 3 Jun — 87 days late" on 29 August, though nobody
had ever planned it. The date on its `scheduled_start_at` was the
Sprint 9B spawn seed: the cart line's `requested_date`, which the
create serializer had defaulted to THE DAY OF ENTRY because the customer
stated no wish. A creation date, copied into the schedule column and
read back as a commitment.

This module answers one question for a ticket: does its own schedule
carry a person's plan, and if so whose? It reads history that already
exists — nothing new is stored, zero migrations:

    the schedule annotation row   `tickets/schedule.py::set_schedule`
                                  writes "Schedule set: ..." /
                                  "Schedule rescheduled: ..." with
                                  `changed_by`, on every human door
                                  (the schedule endpoint, the transition
                                  modal, the board's plan action)
    the recurring occurrence      `planned_work/generation.py` spawns
                                  the ticket ON the occurrence's
                                  `planned_date`; the person is whoever
                                  set the recurring job up
    the provider's commitment     `extra_work/planning.py::apply_plan`
                                  writes a "Plan changed: ... committed
                                  window ..." row on the extra work AND
                                  on each spawned ticket; the bulk dates
                                  endpoint writes the column alone

A `scheduled_start_at` with none of those behind it is a PHANTOM: the
column is set, no person set it. `tickets/job_dates.py` reads this
before it reads the column, so the board, the ladder, the counts and
the detail all stop at the same fact. The phantom rows stay in the
database untouched; presentation decides the words (Aangemaakt op ...
door ... — nog niet ingepland), never "te laat" against a plan nobody
made.
"""
from __future__ import annotations

import dataclasses
import datetime

from django.db.models import Exists, OuterRef, Q

from .schedule_history import SCHEDULE_NOTE_PREFIX

#: The two annotation notes that SET a schedule. "Schedule cleared" is
#: the third note `compose_schedule_note` writes and is deliberately not
#: a plan.
SCHEDULE_SET_PREFIXES = (
    f"{SCHEDULE_NOTE_PREFIX}set",
    f"{SCHEDULE_NOTE_PREFIX}rescheduled",
)

#: `extra_work/planning.py::apply_plan` — the note fragment that marks
#: a provider's committed window, on the extra work's own history and
#: mirrored onto each spawned ticket.
COMMITTED_WINDOW_MARK = "committed window"

PLAN_KIND_SCHEDULE = "SCHEDULE"
PLAN_KIND_RECURRING = "RECURRING"
PLAN_KIND_PROVIDER_PLAN = "PROVIDER_PLAN"

#: The annotation `with_own_plan` adds. Named so `job_dates` cannot typo
#: it into a silent `None`.
OWN_PLAN = "job_own_plan"


def _is_schedule_set_note(note: str | None) -> bool:
    text = note or ""
    return any(text.startswith(prefix) for prefix in SCHEDULE_SET_PREFIXES)


def _person_label(user) -> str | None:
    if user is None:
        return None
    return (getattr(user, "full_name", "") or "").strip() or user.email


def latest_schedule_set_row(ticket):
    """The newest "Schedule set / rescheduled" row, or None.

    Iterates the prefetched relation like `latest_schedule_change`
    does, so the detail view pays no query for it.
    """
    newest = None
    for row in ticket.status_history.all():
        if not _is_schedule_set_note(row.note):
            continue
        if newest is None or row.created_at > newest.created_at:
            newest = row
    return newest


def ticket_has_own_plan(ticket) -> bool:
    """Does the ticket's OWN `scheduled_start_at` carry a person's plan?

    True when a person scheduled it (a set / rescheduled row) or when
    the ticket is a recurring occurrence's (its plan-of-record is the
    occurrence's `planned_date`). Reads the `job_own_plan` annotation
    when the queryset carried one, else the prefetched history.
    """
    if ticket.scheduled_start_at is None:
        return False
    if ticket.planned_occurrence_id is not None:
        return True
    annotated = ticket.__dict__.get(OWN_PLAN)
    if annotated is not None:
        return bool(annotated)
    return latest_schedule_set_row(ticket) is not None


def own_plan_q() -> Q:
    """SQL twin of `ticket_has_own_plan` for a TICKET queryset."""
    from .models import TicketStatusHistory

    set_rows = TicketStatusHistory.objects.filter(
        ticket_id=OuterRef("pk")
    ).filter(
        Q(note__startswith=SCHEDULE_SET_PREFIXES[0])
        | Q(note__startswith=SCHEDULE_SET_PREFIXES[1])
    )
    return Q(scheduled_start_at__isnull=False) & (
        Q(planned_occurrence__isnull=False) | Exists(set_rows)
    )


def with_own_plan(queryset):
    """Annotate `job_own_plan` onto a TICKET queryset."""
    from .models import TicketStatusHistory

    set_rows = TicketStatusHistory.objects.filter(
        ticket_id=OuterRef("pk")
    ).filter(
        Q(note__startswith=SCHEDULE_SET_PREFIXES[0])
        | Q(note__startswith=SCHEDULE_SET_PREFIXES[1])
    )
    return queryset.annotate(**{OWN_PLAN: Exists(set_rows)})


@dataclasses.dataclass(frozen=True)
class PlanProvenance:
    """WHO planned the job's window and WHEN — or nothing."""

    kind: str | None
    planned_by_name: str | None
    planned_at: datetime.datetime | None

    @property
    def has_real_plan(self) -> bool:
        return self.kind is not None

    def as_dict(self) -> dict:
        return {
            "has_real_plan": self.has_real_plan,
            "plan_kind": self.kind,
            "planned_by_name": self.planned_by_name,
            "planned_at": (
                self.planned_at.isoformat() if self.planned_at else None
            ),
        }


NO_PLAN = PlanProvenance(kind=None, planned_by_name=None, planned_at=None)


def _committed_window_row(rows):
    newest = None
    for row in rows:
        if COMMITTED_WINDOW_MARK not in (row.note or ""):
            continue
        if newest is None or row.created_at > newest.created_at:
            newest = row
    return newest


def extra_work_plan_provenance(extra_work) -> PlanProvenance:
    """The provider's commitment on an extra work, and who made it.

    `provider_planned_date` IS the plan (W2-D: the provider saying when
    it will do the work). The person comes from the "committed window"
    history row `apply_plan` writes; the bulk dates endpoint writes the
    column without one, so the plan can be real with nobody named.
    """
    if extra_work is None or extra_work.provider_planned_date is None:
        return NO_PLAN
    row = _committed_window_row(extra_work.status_history.all())
    return PlanProvenance(
        kind=PLAN_KIND_PROVIDER_PLAN,
        planned_by_name=_person_label(getattr(row, "changed_by", None)),
        planned_at=getattr(row, "created_at", None),
    )


def ticket_plan_provenance(ticket) -> PlanProvenance:
    """Who planned this ticket's window, mirroring `job_dates.job_window`
    branch for branch: the ticket's own schedule when a person (or the
    recurring plan) stands behind it, else the extra work's commitment,
    else nothing. A customer's wish is not a plan and answers NO_PLAN.
    """
    if ticket.scheduled_start_at is not None:
        row = latest_schedule_set_row(ticket)
        if row is not None:
            return PlanProvenance(
                kind=PLAN_KIND_SCHEDULE,
                planned_by_name=_person_label(row.changed_by),
                planned_at=row.created_at,
            )
        occurrence = (
            ticket.planned_occurrence
            if ticket.planned_occurrence_id is not None
            else None
        )
        if occurrence is not None:
            job = occurrence.recurring_job
            return PlanProvenance(
                kind=PLAN_KIND_RECURRING,
                planned_by_name=_person_label(
                    getattr(job, "created_by", None)
                ),
                planned_at=getattr(job, "created_at", None),
            )
        # No row, no occurrence: the column was seeded, not planned.
        # Fall through to the extra work's own commitment, exactly as
        # `job_window` does.
    extra_work = getattr(ticket, "extra_work_request", None)
    if extra_work is None:
        return NO_PLAN
    return extra_work_plan_provenance(extra_work)


__all__ = [
    "COMMITTED_WINDOW_MARK",
    "NO_PLAN",
    "OWN_PLAN",
    "PLAN_KIND_PROVIDER_PLAN",
    "PLAN_KIND_RECURRING",
    "PLAN_KIND_SCHEDULE",
    "PlanProvenance",
    "SCHEDULE_SET_PREFIXES",
    "extra_work_plan_provenance",
    "latest_schedule_set_row",
    "own_plan_q",
    "ticket_has_own_plan",
    "ticket_plan_provenance",
    "with_own_plan",
]
