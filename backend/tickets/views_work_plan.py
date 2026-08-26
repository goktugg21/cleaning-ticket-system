"""
Sprint 179A — the Work Plan endpoint.

    GET /api/tickets/work-plan/?week=2026-W33&scope=company

One week of operational work, from BOTH sources, with the §12B
week-placement rule applied server-side and every count computed over
the whole scope rather than over whatever the caller happened to fetch.

**Why a new endpoint rather than more query params on `my-slots/`.**
`my-slots/` is a plain `ListAPIView` over `TicketStaffAssignment` and
every existing caller reads it as a paginated list of slot rows. The
Work Plan is not a list of slots: it is a composite — two sources, a
placement decision per card, three bounded lists and a count block — and
bolting that onto a paginated model list would change the response shape
under a contract other callers already speak (the Sprint 134 lesson, in
CLAUDE.md's own words: a list endpoint's pagination shape is a contract
with EVERY caller). `my-slots/` is therefore untouched.

**Why it lives in `tickets/`.** It reads both `tickets` and
`extra_work`, and the two apps already import from each other in both
directions. It is mounted next to `my-slots/`, which is the surface it
supersedes for this page, and the rule it applies lives in
`tickets/work_plan.py` — free of Django entirely, so it is testable
without a request.

**Scoping — nothing new is invented here.**

* Ticket slots, team view: `scope_tickets_for`, the SAME helper the
  ticket list and `my-slots/?scope=company` use. Sprint 170 §1 already
  established that path and it is reused verbatim, not re-derived.
* Ticket slots, personal view: the caller's own assignment rows.
  Inherently caller-scoped.
* Extra work, team view: `scope_extra_work_for`, narrowed to requests
  somebody has actually been assigned to.
* Extra work, personal view: the caller's own `ExtraWorkAssignment`
  rows, and ONLY those.

That last one is the one that needed a decision, so it is written down.
`scope_extra_work_for` returns `.none()` for STAFF on purpose — the
post-2026-05-20 privacy fix, because every extra-work serializer gated
only on "is this a customer" and would therefore have leaked
`internal_cost_note`, `manager_note`, `override_*` and proposal pricing
to field staff. That decision is NOT reopened here. What this endpoint
adds is the same shape `Ticket.extra_work_origin` already uses: a
worker who has been deliberately put on a job by an authorised operator
sees a narrow OPERATIONAL subset of it — title, building, customer name,
planned window, deadline, urgency, status — and no commercial field
exists on this serializer to leak. `_entry_from_extra_work` below is the
whole surface; `test_sprint179a_work_plan` pins its key set exactly, so
adding a field is a deliberate act with a failing test attached.

Being assigned is not something a caller can arrange for themselves: a
WORKER must hold `BuildingStaffVisibility` on the request's building and
the assignment is written by a provider operator through
`extra_work.views_assignments` (Sprint 157/158). A cross-tenant
assignment row cannot be created, so a caller-scoped read of those rows
cannot cross a tenant (H-1).
"""
from __future__ import annotations

import datetime

from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import (
    IsAuthenticatedAndActive,
    is_customer_side,
    is_provider_management_role,
)
from accounts.scoping import scope_tickets_for
from extra_work.models import (
    ExtraWorkAssignment,
    ExtraWorkRequest,
    ExtraWorkStatus,
)
from extra_work.scoping import scope_extra_work_for

from . import lateness as late_rules
from .lateness_index import LATE_LIVE_TICKET_STATUSES, LatenessIndex
from .models import (
    StaffAssignmentSlotStatus,
    Ticket,
    TicketStaffAssignment,
    TicketStatus,
)
from .work_plan import (
    CLOSED_STATES,
    PLACEMENT_OVERDUE,
    PLACEMENT_PLANNED,
    STATE_BLOCKED,
    STATE_DONE,
    STATE_IN_PROGRESS,
    STATE_OPEN,
    Job,
    day_for,
    is_overdue,
    iso_week_bounds,
    overdue_days,
    placement_for,
)


KIND_TICKET_SLOT = "TICKET_SLOT"
KIND_EXTRA_WORK = "EXTRA_WORK"

#: How many cards the week may return. A week view looks fine on seed
#: data and breaks on a real tenant, so the list is bounded here AND
#: rendered inside a `BoundedList` on the page. `truncated` says so out
#: loud rather than letting the reader assume they see everything —
#: which is the same defect as a count that describes one page.
ENTRY_LIMIT = 300
#: The two "elsewhere" lists behind their own buttons.
OVERDUE_LIMIT = 100
UPCOMING_LIMIT = 100
#: Sprint 181 §8 — the undated lane. Same bound as its two siblings:
#: this list is potentially the LARGEST of the three (on crmtest it is
#: 43 of 70 live tickets), which is precisely why it needs one.
UNDATED_LIMIT = 100
#: W-LATE §1a — the late strip. Wider than its siblings because the
#: strip is the one list that must never hide its worst row: the page
#: renders the first few and offers "+N more", and only past THIS bound
#: does the server say it stopped counting rows (it never stops counting
#: the total — `counts.late` is the whole set).
LATE_LIMIT = 200

#: How many names a card carries before it just says how many more.
ASSIGNEE_NAMES_SHOWN = 5


# ---------------------------------------------------------------------
# The same rule, expressed in SQL.
#
# `work_plan.py` holds the rule as Python over a `Job`. The COUNTS have
# to be answered over the whole scope without loading it, so they are
# expressed here as querysets — two expressions of one rule, which is
# exactly the drift the product docs warn about. So
# `WorkPlanRuleParityTests` asserts, over a fixture built to hit every
# branch, that each SQL count equals the count the Python rule produces
# over the same rows. Change one without the other and that test fails.
# ---------------------------------------------------------------------


def _slot_window_end_q(lookup: str, value: datetime.date) -> Q:
    """`window_end <lookup> value` for a slot.

    A slot's window end is `scheduled_end_at`, or `scheduled_start_at`
    when no end was set — the single-planned-day reading `Job.window_end`
    uses. Expressed as a two-branch OR rather than a `Coalesce`
    annotation so the same predicate composes into a `Count(filter=...)`
    without dragging an annotation through every aggregate.
    """
    return Q(**{f"scheduled_end_at__date__{lookup}": value}) | Q(
        scheduled_end_at__isnull=True,
        **{f"scheduled_start_at__date__{lookup}": value},
    )


#: Not finished and not cancelled. For a slot this is exactly
#: `slot_status == ASSIGNED`: the other three slot statuses are the two
#: closed states.
_SLOT_LIVE_Q = Q(slot_status=StaffAssignmentSlotStatus.ASSIGNED)

_SLOT_STATE_Q = {
    STATE_DONE: Q(slot_status=StaffAssignmentSlotStatus.COMPLETED),
    STATE_BLOCKED: Q(
        slot_status__in=[
            StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE,
            StaffAssignmentSlotStatus.CANCELLED,
        ]
    ),
    STATE_IN_PROGRESS: _SLOT_LIVE_Q & Q(ticket__status=TicketStatus.IN_PROGRESS),
    STATE_OPEN: _SLOT_LIVE_Q & ~Q(ticket__status=TicketStatus.IN_PROGRESS),
}

#: Extra work has no separate slot lifecycle — its own status carries
#: both the commercial and the operational segment, and only the
#: operational half matters here.
_EW_STATE_Q = {
    STATE_DONE: Q(status=ExtraWorkStatus.COMPLETED),
    STATE_BLOCKED: Q(
        status__in=[
            ExtraWorkStatus.CANCELLED,
            ExtraWorkStatus.CUSTOMER_REJECTED,
        ]
    ),
    STATE_IN_PROGRESS: Q(status=ExtraWorkStatus.IN_PROGRESS),
    STATE_OPEN: Q(
        status__in=[
            ExtraWorkStatus.REQUESTED,
            ExtraWorkStatus.UNDER_REVIEW,
            ExtraWorkStatus.PRICING_PROPOSED,
            ExtraWorkStatus.CUSTOMER_APPROVED,
        ]
    ),
}

_EW_LIVE_Q = ~Q(
    status__in=[
        ExtraWorkStatus.COMPLETED,
        ExtraWorkStatus.CANCELLED,
        ExtraWorkStatus.CUSTOMER_REJECTED,
    ]
)


#: Sprint 184 §2 — the slot's DUE date in SQL, mirroring `_slot_job`.
#:
#: The Python rule and this predicate must select the same rows; the
#: module header says so and a test enforces it. So the branch is the
#: same branch: a real extra-work deadline where one exists, the last
#: planned day where none does.
_SLOT_EW_DEADLINE = "ticket__extra_work_request__deadline"


def _slot_due_q(lookup: str, value: datetime.date) -> Q:
    """`due <lookup> value` for a slot.

    Written as two POSITIVE branches rather than one negated branch on
    purpose. `deadline__isnull=True` over a nullable FK chain is true
    both when the ticket has no extra work at all and when it has one
    with no deadline — which is exactly the set that should fall back to
    the planned window. A `~Q(...isnull=False)` would mean the same
    thing here but reads as a double negative over a LEFT JOIN, and this
    predicate has to be obviously right to anybody checking it against
    `_slot_job`.
    """
    return (
        Q(**{f"{_SLOT_EW_DEADLINE}__isnull": False})
        & Q(**{f"{_SLOT_EW_DEADLINE}__{lookup}": value})
    ) | (
        Q(**{f"{_SLOT_EW_DEADLINE}__isnull": True})
        & _slot_window_end_q(lookup, value)
    )


def _slot_overdue_q(today: datetime.date) -> Q:
    return _SLOT_LIVE_Q & _slot_due_q("lt", today)


def _ew_overdue_q(today: datetime.date) -> Q:
    return _EW_LIVE_Q & Q(deadline__isnull=False, deadline__lt=today)


def _slot_week_q(
    week_start: datetime.date, week_end: datetime.date, today: datetime.date
) -> Q:
    """SQL twin of `work_plan.placement_for`: planned placement, and
    nothing else. W-FIX1 E2 dropped the `| started | overdue` branches
    that used to copy live and late work onto today's column; those
    rows are the overdue strip's and the undated lane's. `today` is
    kept in the signature so the parity test can call both twins the
    same way."""
    del today
    return Q(scheduled_start_at__date__lte=week_end) & _slot_window_end_q(
        "gte", week_start
    )


def _ew_week_q(
    week_start: datetime.date, week_end: datetime.date, today: datetime.date
) -> Q:
    del today
    return Q(preferred_date__lte=week_end) & (
        Q(planned_end_date__gte=week_start)
        | Q(planned_end_date__isnull=True, preferred_date__gte=week_start)
    )


def _slot_upcoming_q(week_end: datetime.date) -> Q:
    # No `is_overdue` guard, unlike the Python rule: a job planned to
    # START after this week cannot also be past a due date that is on or
    # before today, because today is inside or before this week. The
    # parity test pins that reasoning rather than trusting it.
    return Q(scheduled_start_at__date__gt=week_end) & _SLOT_STATE_Q[STATE_OPEN]


def _ew_upcoming_q(week_end: datetime.date) -> Q:
    return Q(preferred_date__gt=week_end) & _EW_STATE_Q[STATE_OPEN]


def _slot_undated_q() -> Q:
    """No planned window at all, and still live. Belongs to no week, so
    it is counted and named rather than dropped — a job nobody has
    scheduled is exactly the one that most needs seeing.

    W-FIX1 A1 (audit F1) — "undated" is a fact about the JOB, not about
    one person's slot. The lane's one action writes the TICKET's
    schedule, so a slot whose ticket is already scheduled, or whose
    colleague's slot on the same ticket already has a day, is not work
    nobody has planned: the job sits in its week and must not ALSO sit
    here. Measured on crmtest: TCK-2026-000352 was on Wednesday's column
    through one slot and in the undated lane through another."""
    dated_sibling = TicketStaffAssignment.objects.filter(
        ticket_id=OuterRef("ticket_id"),
        scheduled_start_at__isnull=False,
    ).exclude(slot_status=StaffAssignmentSlotStatus.CANCELLED)
    return (
        _SLOT_LIVE_Q
        & Q(scheduled_start_at__isnull=True)
        & Q(ticket__scheduled_start_at__isnull=True)
        & ~Exists(dated_sibling)
    )


def _ew_undated_q() -> Q:
    return _EW_LIVE_Q & Q(preferred_date__isnull=True)


# ---------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------


def _slot_source(user, team: bool):
    queryset = TicketStaffAssignment.objects.filter(
        ticket__deleted_at__isnull=True
    )
    if team:
        # Sprint 170 §1's path, unchanged: the widening is expressed
        # through `scope_tickets_for`, so it cannot show a ticket the
        # actor could not open. Not a second scoping path.
        queryset = queryset.filter(ticket__in=scope_tickets_for(user))
    else:
        queryset = queryset.filter(user=user)
    return queryset.select_related(
        "ticket",
        "ticket__building",
        "ticket__customer",
        # Sprint 184 §2 — the slot's due date is the parent extra work's
        # deadline where one exists. Joined here so `_slot_deadline`
        # reads an already-loaded row: without it every slot in the week
        # would fetch its own extra work, which is the N+1 the §1 read
        # design exists to avoid.
        "ticket__extra_work_request",
        # W-N1 §3 — the slot's own part. Joined for the same reason the
        # extra work above is: without it every slot in the week fetches
        # its own sub-task.
        "sub_task",
        "user",
    )


def _extra_work_source(user, team: bool):
    """Extra work SOMEBODY IS ASSIGNED TO.

    The Work Plan answers "who is doing what, when". An extra work with
    nobody on it is not yet anybody's work, and putting every request in
    the company on an operator's week would bury the jobs that are.
    Filtering through an `id__in` subquery rather than a join keeps one
    row per request when a person holds both roles on it.
    """
    assigned_ids = ExtraWorkAssignment.objects.values("extra_work_request_id")
    if team:
        queryset = scope_extra_work_for(user).filter(id__in=assigned_ids)
    else:
        queryset = ExtraWorkRequest.objects.filter(
            deleted_at__isnull=True,
            id__in=assigned_ids.filter(user=user),
        )

    # W-FIX1 A1 (audit F1) — ONE JOB, ONE ROW. Once an extra work has
    # spawned a ticket and somebody holds a live slot on it, that slot
    # row IS the job's row on this board: it carries the day, the slot
    # status, the parts and the completion action, which the extra-work
    # row cannot. Offering both put "yy" and "TCK-2026-000352 · yy" side
    # by side in the undated lane with two "Plan for today" doors that
    # wrote two different records. The richer row wins; the extra-work
    # row is kept only while no slot exists to speak for the job (a
    # spawned ticket nobody has been put on yet still needs seeing).
    covered = TicketStaffAssignment.objects.filter(
        ticket__deleted_at__isnull=True,
        ticket__extra_work_request__isnull=False,
    ).exclude(slot_status=StaffAssignmentSlotStatus.CANCELLED)
    if team:
        covered = covered.filter(ticket__in=scope_tickets_for(user))
    else:
        covered = covered.filter(user=user)
    queryset = queryset.exclude(
        id__in=covered.values("ticket__extra_work_request_id")
    )
    return queryset.select_related("building", "customer")


# ---------------------------------------------------------------------
# Normalisation — model row -> `Job` -> response entry
# ---------------------------------------------------------------------


def _local_date(value) -> datetime.date | None:
    """The LOCAL calendar date of an aware datetime.

    `timezone.localtime` rather than `.date()` on the stored UTC value:
    a 00:30 Amsterdam slot is stored as 22:30 the previous day in UTC,
    and reading `.date()` off that files it under the wrong day — and,
    on a Monday, under the wrong week.
    """
    if value is None:
        return None
    return timezone.localtime(value).date()


def _slot_state(slot) -> str:
    if slot.slot_status == StaffAssignmentSlotStatus.COMPLETED:
        return STATE_DONE
    if slot.slot_status in {
        StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE,
        StaffAssignmentSlotStatus.CANCELLED,
    }:
        return STATE_BLOCKED
    if slot.ticket.status == TicketStatus.IN_PROGRESS:
        return STATE_IN_PROGRESS
    return STATE_OPEN


def _extra_work_state(extra_work) -> str:
    if extra_work.status == ExtraWorkStatus.COMPLETED:
        return STATE_DONE
    if extra_work.status in {
        ExtraWorkStatus.CANCELLED,
        ExtraWorkStatus.CUSTOMER_REJECTED,
    }:
        return STATE_BLOCKED
    if extra_work.status == ExtraWorkStatus.IN_PROGRESS:
        return STATE_IN_PROGRESS
    return STATE_OPEN


def _slot_deadline(slot) -> datetime.date | None:
    """The REAL deadline behind this slot, when there is one.

    Sprint 184 §2. A slot is one person's dated piece of work on a
    ticket, and a ticket born from an extra work inherits that request's
    `deadline` — the provider's commitment for when the job must be
    finished. Read through the link (Sprint 184 §1), never copied onto
    the ticket, so editing the deadline on the extra work moves this in
    the same instant.

    Returns None for an ordinary ticket's slot: those genuinely have no
    deadline, and inventing one is what the old rule effectively did.

    FOLLOWS THE CANONICAL FK ONLY, deliberately. `resolve_extra_work_
    origin_core` also walks the two legacy chains (`proposal_line` and
    `extra_work_request_item`) for historical rows whose canonical FK is
    null; this does not, because the SQL twin `_slot_due_q` has to
    select exactly the same rows and three OR'd join paths in a
    predicate that also composes into `Count(filter=...)` is a great
    deal of machinery for rows that no longer occur — every spawn path
    has set the canonical FK since Sprint 6A. Measured on crmtest: all
    four live slots on extra-work tickets resolve through the canonical
    FK. A legacy-linked row keeps the old last-planned-day rule, which
    is its pre-Sprint-184 behaviour, so nothing regresses.
    """
    return getattr(
        getattr(slot.ticket, "extra_work_request", None), "deadline", None
    )


def _slot_job(slot) -> Job:
    start = _local_date(slot.scheduled_start_at)
    end = _local_date(slot.scheduled_end_at)
    # Sprint 184 §2 — "overdue" on a slot now means what it says.
    #
    # It used to mean "past its last planned day", because a slot has no
    # deadline column and the rule needed SOMETHING. That quietly
    # redefined late in both directions: a job planned for Monday but
    # genuinely due Friday was marked overdue on Tuesday, and a job that
    # had blown a real deadline stopped being marked the moment somebody
    # moved its planned window forward.
    #
    # Where a real deadline exists — a ticket spawned by an extra work
    # carrying one — it is the answer. Where none exists the old
    # definition stands unchanged, because for an ordinary ticket the
    # last planned day is still the only date anybody stated. §12B's
    # placement rule ("a job past its deadline and unfinished also
    # appears in the current week, marked overdue") is what this makes
    # literally true rather than approximately true.
    deadline = _slot_deadline(slot)
    return Job(
        planned_start=start,
        planned_end=end,
        due=deadline if deadline is not None else (end or start),
        state=_slot_state(slot),
    )


def _extra_work_job(extra_work) -> Job:
    return Job(
        planned_start=extra_work.preferred_date,
        planned_end=extra_work.planned_end_date,
        due=extra_work.deadline,
        state=_extra_work_state(extra_work),
    )


def _iso(value: datetime.date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _person_label(user) -> str:
    return (user.full_name or user.email) if user is not None else ""


def _parts_map(slot_rows):
    """(ticket_id, user_id) -> the parts that person holds on that ticket.

    W-N1 §3. ONE query for the whole week, not one per card — the same
    shape `_assignee_map` uses next door and for the same reason.

    SCOPING IS INHERITED, NOT RE-DERIVED. The pairs come from
    `slot_rows`, which `_slot_source` has already scoped: `user=user` for
    a STAFF viewer, `ticket__in=scope_tickets_for(user)` for a manager.
    So this asks only "what parts does this same person hold on this same
    ticket", about a person and a ticket the viewer has already been
    admitted to. It never widens, and it deliberately does NOT call a
    scoping helper of its own — a second scoping path is how a
    cross-tenant leak gets written.

    That inheritance is also what makes the brief's two cases fall out
    for free: a STAFF viewer's rows are their own slots, so they see
    their own parts; a manager's rows are everyone's, so they see all of
    them.
    """
    pairs = {(row.ticket_id, row.user_id) for row in slot_rows}
    if not pairs:
        return {}
    ticket_ids = {t for t, _ in pairs}
    user_ids = {u for _, u in pairs}
    out: dict[tuple[int, int], list] = {}
    rows = (
        TicketStaffAssignment.objects.filter(
            ticket_id__in=ticket_ids,
            user_id__in=user_ids,
            sub_task__isnull=False,
            ticket__deleted_at__isnull=True,
        )
        .select_related("sub_task")
        .order_by("sub_task__ordering", "sub_task_id")
    )
    for row in rows:
        key = (row.ticket_id, row.user_id)
        # The id__in pair above is a cross product, so a row for a
        # (ticket, user) combination that is not actually in `pairs` can
        # come back. Dropped here rather than widening what is shown.
        if key not in pairs:
            continue
        bucket = out.setdefault(key, [])
        if any(p["id"] == row.sub_task_id for p in bucket):
            continue
        bucket.append({"id": row.sub_task_id, "title": row.sub_task.title})
    return out


def _entry_from_slot(
    slot, job, placement, day, today, *, viewer, parts=None, lateness=None
) -> dict:
    return {
        "kind": KIND_TICKET_SLOT,
        # Stable across the two kinds so React can key one merged list
        # without inventing an index.
        "key": f"slot-{slot.id}",
        "source_id": slot.id,
        "ticket_id": slot.ticket_id,
        "ticket_no": slot.ticket.ticket_no,
        "extra_work_id": None,
        "title": slot.ticket.title,
        "status": slot.slot_status,
        "state": job.state,
        "ticket_status": slot.ticket.status,
        "ticket_type": slot.ticket.type,
        "urgency": None,
        "customer_name": (
            slot.ticket.customer.name if slot.ticket.customer_id else None
        ),
        "building_id": slot.ticket.building_id,
        "building_name": (
            slot.ticket.building.name if slot.ticket.building_id else None
        ),
        "planned_start": _iso(job.planned_start),
        "planned_end": _iso(job.planned_end),
        "due_date": _iso(job.due),
        "scheduled_start_at": slot.scheduled_start_at,
        "scheduled_end_at": slot.scheduled_end_at,
        "time_window_label": slot.time_window_label,
        "assignment_note": slot.assignment_note,
        "completion_note": slot.completion_note,
        "unable_to_complete_reason": slot.unable_to_complete_reason,
        "day": _iso(day),
        "placement": placement,
        "is_overdue": is_overdue(job, today),
        "overdue_days": overdue_days(job, today),
        "assignee_names": [_person_label(slot.user)],
        "assignee_count": 1,
        # W-N1 §3 — the parts this person holds on this ticket, so the
        # Work Plan can say WHICH half of the job is theirs. Empty list,
        # never null: a card that renders `parts.map` should not have to
        # ask whether the key exists.
        "parts": parts or [],
        # W-LATE §1b — the rung this JOB stands on, from the one helper.
        # Always present, `level: null` when it is not late, so the
        # client reads one shape for every card.
        "lateness": (lateness or late_rules.NOT_LATE).as_dict(),
        # The completion actions belong to the person holding the slot.
        # An admin looking at the team's week is reading it, not working
        # it, and a "Mark done" button on somebody else's card is one
        # mis-click away from a false completion record.
        "can_complete": (
            slot.user_id == viewer.id
            and slot.slot_status == StaffAssignmentSlotStatus.ASSIGNED
        ),
    }


def _entry_from_extra_work(
    extra_work, job, placement, day, today, *, assignees, lateness=None
) -> dict:
    """The extra-work card's WHOLE surface.

    Operational fields only. There is deliberately no description, no
    pricing, no note of any kind and no proposal reference — see the
    module docstring. `test_sprint179a_work_plan` asserts this key set
    exactly, in both scopes, so a field cannot be added here by
    accident.
    """
    names = [_person_label(user) for user in assignees]
    return {
        "kind": KIND_EXTRA_WORK,
        "key": f"ew-{extra_work.id}",
        "source_id": extra_work.id,
        "ticket_id": None,
        "ticket_no": None,
        "extra_work_id": extra_work.id,
        "title": extra_work.title,
        "status": extra_work.status,
        "state": job.state,
        "ticket_status": None,
        "ticket_type": None,
        "urgency": extra_work.urgency,
        "customer_name": (
            extra_work.customer.name if extra_work.customer_id else None
        ),
        "building_id": extra_work.building_id,
        "building_name": (
            extra_work.building.name if extra_work.building_id else None
        ),
        "planned_start": _iso(job.planned_start),
        "planned_end": _iso(job.planned_end),
        "due_date": _iso(job.due),
        # Extra work has no dated slot — Sprint 157 §2 declined to build
        # one and nothing since has changed that. The card shows a
        # planned WINDOW in days, so the three time fields are null
        # rather than absent: one entry shape, whatever the source.
        "scheduled_start_at": None,
        "scheduled_end_at": None,
        "time_window_label": None,
        "assignment_note": None,
        "completion_note": None,
        "unable_to_complete_reason": None,
        "day": _iso(day),
        "placement": placement,
        "is_overdue": is_overdue(job, today),
        "overdue_days": overdue_days(job, today),
        # W-N1 §3 — extra work has no parts; the key is present and
        # empty so both kinds answer `entry.parts` the same way and the
        # frontend needs no `kind` check to read it.
        "parts": [],
        "lateness": (lateness or late_rules.NOT_LATE).as_dict(),
        "assignee_names": names[:ASSIGNEE_NAMES_SHOWN],
        "assignee_count": len(names),
        "can_complete": False,
    }


#: Sorts a merged list where one source has a clock time and the other
#: has only a day. A far-future sentinel puts the day-only cards after
#: the timed ones inside the same column, which is where an operator
#: expects "sometime today" to sit relative to "09:00".
_NO_TIME = datetime.datetime.max.replace(tzinfo=datetime.timezone.utc)


def _week_sort_key(entry: dict) -> tuple:
    return (
        entry["day"] or "",
        entry["scheduled_start_at"] or _NO_TIME,
        entry["title"] or "",
        entry["key"],
    )


def _due_sort_key(entry: dict) -> tuple:
    """Most overdue first / soonest planned first, whichever list it is.

    The week's own ordering is meaningless in a flat table where every
    row hangs on the same day.
    """
    return (
        entry["due_date"] or entry["planned_start"] or "9999-12-31",
        entry["title"] or "",
        entry["key"],
    )


# ---------------------------------------------------------------------
# The view
# ---------------------------------------------------------------------


class WorkPlanView(APIView):
    """GET /api/tickets/work-plan/ — see the module docstring."""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, *args, **kwargs):
        user = request.user

        # A customer-side user has no operational week: they hold no
        # assignment rows and are never assignable to one. Refusing at
        # the door says so, rather than handing back a permanently empty
        # plan that looks like a bug.
        if is_customer_side(user):
            return Response(
                {"detail": "The work plan is a provider-side surface."},
                status=status.HTTP_403_FORBIDDEN,
            )

        today = timezone.localdate()
        week = self._resolve_week(request, today)
        if week is None:
            return Response(
                {"detail": "week must look like 2026-W33."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        iso_year, iso_week = week
        week_start, week_end = iso_week_bounds(iso_year, iso_week)

        team = request.query_params.get(
            "scope"
        ) == "company" and is_provider_management_role(user)
        slots = _slot_source(user, team)
        extra_work = _extra_work_source(user, team)

        entries, truncated = self._week_entries(
            slots, extra_work, week_start, week_end, today, team=team,
            viewer=user,
        )
        overdue_entries, overdue_truncated = self._flat_entries(
            slots.filter(_slot_overdue_q(today)),
            extra_work.filter(_ew_overdue_q(today)),
            week_start,
            week_end,
            today,
            limit=OVERDUE_LIMIT,
            team=team,
            viewer=user,
            fallback_placement=PLACEMENT_OVERDUE,
        )
        upcoming_entries, upcoming_truncated = self._flat_entries(
            slots.filter(_slot_upcoming_q(week_end)),
            extra_work.filter(_ew_upcoming_q(week_end)),
            week_start,
            week_end,
            today,
            limit=UPCOMING_LIMIT,
            team=team,
            viewer=user,
            fallback_placement=PLACEMENT_PLANNED,
        )
        # Sprint 181 §8 — the undated work, as ENTRIES rather than as a
        # number.
        #
        # `counts.undated` has always been here and the page rendered it
        # as one muted sentence: "N items have no date". On crmtest that
        # sentence currently stands for 43 of 70 live tickets — two
        # thirds of the work admitted to and not shown, while six of the
        # seven week columns read "Nothing planned". A count is not a
        # place to put something; a list is.
        #
        # Same shape as the two flat lists above, deliberately: same
        # builder, same limit-plus-one truncation, same placement
        # fallback. Nothing new to learn, nothing new to keep in step.
        undated_entries, undated_truncated = self._flat_entries(
            slots.filter(_slot_undated_q()),
            extra_work.filter(_ew_undated_q()),
            week_start,
            week_end,
            today,
            limit=UNDATED_LIMIT,
            team=team,
            viewer=user,
            fallback_placement=PLACEMENT_PLANNED,
        )

        # W-LATE §1a — the late strip's rows, one per job, and its total.
        late_entries, late_truncated, late_total = self._late_entries(
            slots, extra_work, today, team=team, viewer=user
        )
        counts = self._counts(slots, extra_work, week_start, week_end, today)
        # Counted over the deduped JOB set in Python rather than as a SQL
        # aggregate, because the ladder needs the widest window across a
        # ticket's slots — see `_late_entries`. It is the whole set,
        # never the page.
        counts["late"] = late_total

        return Response(
            {
                "week": {
                    "iso_year": iso_year,
                    "iso_week": iso_week,
                    "label": f"{iso_year}-W{iso_week:02d}",
                    "start": _iso(week_start),
                    "end": _iso(week_end),
                    "is_current": week_start <= today <= week_end,
                },
                "today": _iso(today),
                "scope": "company" if team else "own",
                "counts": counts,
                "entries": entries,
                "overdue_entries": overdue_entries,
                "upcoming_entries": upcoming_entries,
                # Sprint 181 §8 — the undated lane's rows.
                "undated_entries": undated_entries,
                # W-LATE §1a — the late strip's rows.
                "late_entries": late_entries,
                "limits": {
                    "entries": ENTRY_LIMIT,
                    "overdue_entries": OVERDUE_LIMIT,
                    "upcoming_entries": UPCOMING_LIMIT,
                    "undated_entries": UNDATED_LIMIT,
                    "late_entries": LATE_LIMIT,
                },
                "truncated": {
                    "entries": truncated,
                    "overdue_entries": overdue_truncated,
                    "upcoming_entries": upcoming_truncated,
                    "undated_entries": undated_truncated,
                    "late_entries": late_truncated,
                },
            },
            status=status.HTTP_200_OK,
        )

    # -- helpers ------------------------------------------------------

    @staticmethod
    def _resolve_week(request, today: datetime.date):
        """`?week=2026-W33`, defaulting to the week containing today."""
        raw = (request.query_params.get("week") or "").strip()
        if not raw:
            iso = today.isocalendar()
            return iso[0], iso[1]
        head, _, tail = raw.partition("-W")
        if not tail or not head.isdigit() or not tail.isdigit():
            return None
        iso_year, iso_week = int(head), int(tail)
        if not (1 <= iso_week <= 53) or not (1900 <= iso_year <= 2999):
            return None
        try:
            iso_week_bounds(iso_year, iso_week)
        except ValueError:
            # Week 53 of a 52-week year. A real input mistake, and a
            # 400 says so instead of silently showing week 1.
            return None
        return iso_year, iso_week

    @staticmethod
    def _assignee_map(extra_work_ids, *, team: bool, viewer):
        """`{extra_work_id: [user, ...]}` for the cards.

        Personal scope answers with the VIEWER alone. Who else is on a
        job is a management read, and widening a worker's own week into
        a roster of colleagues is not something this endpoint was asked
        for.
        """
        if not extra_work_ids:
            return {}
        if not team:
            return {ew_id: [viewer] for ew_id in extra_work_ids}
        rows = (
            ExtraWorkAssignment.objects.filter(
                extra_work_request_id__in=list(extra_work_ids)
            )
            .select_related("user")
            .order_by("role", "user__full_name", "user__email")
        )
        out: dict[int, list] = {}
        for row in rows:
            people = out.setdefault(row.extra_work_request_id, [])
            if all(person.id != row.user_id for person in people):
                people.append(row.user)
        return out

    @classmethod
    def _build(
        cls,
        slots,
        extra_work,
        week_start,
        week_end,
        today,
        *,
        limit,
        team,
        viewer,
        fallback_placement,
        sort_key,
    ):
        """Materialise both sources into merged entries.

        `fallback_placement=None` is the week view: a row the rule does
        not place in this week is dropped. The flat lists (overdue,
        upcoming) are tables rather than columns and every row in them
        is there for a known reason, so they pass that reason in instead
        of asking the week rule a question it cannot answer about a week
        the row is not in.
        """
        rows = list(
            slots.order_by("scheduled_start_at", "id")[: limit + 1]
        )
        ew_rows = list(
            extra_work.order_by("preferred_date", "id")[: limit + 1]
        )
        assignees = cls._assignee_map(
            [row.id for row in ew_rows], team=team, viewer=viewer
        )
        parts_by_pair = _parts_map(rows)
        # W-LATE §1b — one index for every card in this list, so a card
        # on Tuesday's column and the same job's card in the strip say
        # the same thing.
        lateness = LatenessIndex(
            [row.ticket_id for row in rows], ew_rows, today
        )

        entries = []
        for slot in rows:
            job = _slot_job(slot)
            placement = placement_for(job, week_start, week_end, today)
            if placement is None:
                if fallback_placement is None:
                    continue
                placement = fallback_placement
            day = day_for(job, placement, week_start, week_end, today)
            entries.append(
                _entry_from_slot(
                    slot,
                    job,
                    placement,
                    day,
                    today,
                    viewer=viewer,
                    parts=parts_by_pair.get((slot.ticket_id, slot.user_id)),
                    lateness=lateness.for_ticket(slot.ticket_id),
                )
            )
        for row in ew_rows:
            job = _extra_work_job(row)
            placement = placement_for(job, week_start, week_end, today)
            if placement is None:
                if fallback_placement is None:
                    continue
                placement = fallback_placement
            day = day_for(job, placement, week_start, week_end, today)
            entries.append(
                _entry_from_extra_work(
                    row,
                    job,
                    placement,
                    day,
                    today,
                    assignees=assignees.get(row.id, []),
                    lateness=lateness.for_extra_work(row),
                )
            )

        entries.sort(key=sort_key)
        truncated = len(entries) > limit
        return entries[:limit], truncated

    @classmethod
    def _week_entries(
        cls, slots, extra_work, week_start, week_end, today, *, team, viewer
    ):
        return cls._build(
            slots.filter(_slot_week_q(week_start, week_end, today)),
            extra_work.filter(_ew_week_q(week_start, week_end, today)),
            week_start,
            week_end,
            today,
            limit=ENTRY_LIMIT,
            team=team,
            viewer=viewer,
            fallback_placement=None,
            sort_key=_week_sort_key,
        )

    @classmethod
    def _flat_entries(
        cls,
        slots,
        extra_work,
        week_start,
        week_end,
        today,
        *,
        limit,
        team,
        viewer,
        fallback_placement,
    ):
        return cls._build(
            slots,
            extra_work,
            week_start,
            week_end,
            today,
            limit=limit,
            team=team,
            viewer=viewer,
            fallback_placement=fallback_placement,
            sort_key=_due_sort_key,
        )

    @classmethod
    def _late_entries(cls, slots, extra_work, today, *, team, viewer):
        """W-LATE §1a — the late strip: ONE ROW PER LATE JOB, ordered by
        the ladder. Returns `(entries, truncated, total)`.

        Fed from "planned-date-passed-and-not-done" (L1) and its two
        worse rungs, which is NOT the overdue list's question: that list
        asks "past its due date", where a slot's due date is the extra
        work's deadline when one exists. A job planned for Monday with a
        deadline on Friday is not overdue on Tuesday, but its plan IS
        broken, and the strip is where that shows. Both lists stay:
        they answer different questions and are labelled as such.

        Job-level, so a two-person ticket is one card carrying both
        names — the merge `dedupeByJob` does in the browser for the
        undated lane, done here because the strip's whole vocabulary
        (one rung per job, one anchor, one hour total) is per job.

        The SQL narrows to a SUPERSET (anything with a past start, a
        past deadline or a past slot start); the ladder itself is asked
        of every candidate in Python, because it needs the widest window
        across the ticket and its slots, which is one aggregate too many
        for a predicate that also has to compose into a count.
        """
        live = slots.filter(_SLOT_LIVE_Q)
        candidate_ids = list(
            Ticket.objects.filter(
                id__in=live.values("ticket_id"),
                status__in=LATE_LIVE_TICKET_STATUSES,
                archived_at__isnull=True,
                deleted_at__isnull=True,
            )
            .filter(
                Q(scheduled_start_at__date__lt=today)
                | Q(scheduled_end_at__date__lt=today)
                | Q(extra_work_request__deadline__lt=today)
                | Q(staff_assignments__scheduled_start_at__date__lt=today)
                | Q(staff_assignments__scheduled_end_at__date__lt=today)
            )
            .values_list("id", flat=True)
            .distinct()
        )
        ew_rows = list(
            extra_work.filter(_EW_LIVE_Q)
            .filter(
                Q(preferred_date__lt=today)
                | Q(planned_end_date__lt=today)
                | Q(deadline__lt=today)
            )
            .order_by("id")
        )
        index = LatenessIndex(candidate_ids, ew_rows, today)
        late_ticket_ids = [
            tid for tid in candidate_ids if index.for_ticket(tid).is_late
        ]
        late_ew = [row for row in ew_rows if index.for_extra_work(row).is_late]

        slot_rows = list(
            live.filter(ticket_id__in=late_ticket_ids).order_by(
                "ticket_id", "scheduled_start_at", "id"
            )
        )
        parts_by_pair = _parts_map(slot_rows)
        assignees = cls._assignee_map(
            [row.id for row in late_ew], team=team, viewer=viewer
        )

        by_ticket: dict[int, list] = {}
        for slot in slot_rows:
            by_ticket.setdefault(slot.ticket_id, []).append(slot)

        keyed = []
        for ticket_id, bucket in by_ticket.items():
            first = bucket[0]
            lateness = index.for_ticket(ticket_id)
            entry = _entry_from_slot(
                first,
                _slot_job(first),
                PLACEMENT_OVERDUE,
                today,
                today,
                viewer=viewer,
                lateness=lateness,
            )
            names: list[str] = []
            parts: list[dict] = []
            for slot in bucket:
                label = _person_label(slot.user)
                if label and label not in names:
                    names.append(label)
                for part in parts_by_pair.get((slot.ticket_id, slot.user_id), []):
                    if all(p["id"] != part["id"] for p in parts):
                        parts.append(part)
            entry["assignee_names"] = names[:ASSIGNEE_NAMES_SHOWN]
            entry["assignee_count"] = len(names)
            entry["parts"] = parts
            # The strip is a READ. Completing a slot stays on the week
            # card that belongs to the person holding it.
            entry["can_complete"] = False
            keyed.append((late_rules.sort_key(lateness, entry["title"]), entry))
        for row in late_ew:
            lateness = index.for_extra_work(row)
            entry = _entry_from_extra_work(
                row,
                _extra_work_job(row),
                PLACEMENT_OVERDUE,
                today,
                today,
                assignees=assignees.get(row.id, []),
                lateness=lateness,
            )
            keyed.append((late_rules.sort_key(lateness, entry["title"]), entry))

        keyed.sort(key=lambda pair: (pair[0], pair[1]["key"]))
        entries = [entry for _, entry in keyed]
        total = len(entries)
        return entries[:LATE_LIMIT], total > LATE_LIMIT, total

    @staticmethod
    def _counts(slots, extra_work, week_start, week_end, today) -> dict:
        """Every number on the screen, over the WHOLE scope.

        This is the point of the endpoint. The chips used to be counted
        in the browser over whatever the page had fetched, so a chip
        could report a number that described one page and looked
        authoritative doing it. These are `COUNT(*)` over the scoped
        queryset and stay right when `entries` is truncated.
        """
        slot_week = slots.filter(_slot_week_q(week_start, week_end, today))
        ew_week = extra_work.filter(_ew_week_q(week_start, week_end, today))

        # Conditional aggregation: FOUR queries for nine numbers rather
        # than eighteen `COUNT(*)` round trips. Neither source is joined
        # to a multi-row relation here — the team widening goes through
        # an `IN (subquery)`, not a join — so a filtered `Count("id")`
        # cannot double-count.
        slot_week_counts = slot_week.aggregate(
            total=Count("id"),
            overdue=Count("id", filter=_slot_overdue_q(today)),
            open=Count("id", filter=_SLOT_STATE_Q[STATE_OPEN]),
            in_progress=Count("id", filter=_SLOT_STATE_Q[STATE_IN_PROGRESS]),
            done=Count("id", filter=_SLOT_STATE_Q[STATE_DONE]),
            blocked=Count("id", filter=_SLOT_STATE_Q[STATE_BLOCKED]),
        )
        ew_week_counts = ew_week.aggregate(
            total=Count("id"),
            overdue=Count("id", filter=_ew_overdue_q(today)),
            open=Count("id", filter=_EW_STATE_Q[STATE_OPEN]),
            in_progress=Count("id", filter=_EW_STATE_Q[STATE_IN_PROGRESS]),
            done=Count("id", filter=_EW_STATE_Q[STATE_DONE]),
            blocked=Count("id", filter=_EW_STATE_Q[STATE_BLOCKED]),
        )
        # The three "elsewhere" numbers answer questions about work that
        # is NOT in this week, so they are counted over the whole scope.
        slot_other = slots.aggregate(
            overdue_all=Count("id", filter=_slot_overdue_q(today)),
            upcoming=Count("id", filter=_slot_upcoming_q(week_end)),
            undated=Count("id", filter=_slot_undated_q()),
        )
        ew_other = extra_work.aggregate(
            overdue_all=Count("id", filter=_ew_overdue_q(today)),
            upcoming=Count("id", filter=_ew_upcoming_q(week_end)),
            undated=Count("id", filter=_ew_undated_q()),
        )

        counts = {
            key: slot_week_counts[key] + ew_week_counts[key]
            for key in slot_week_counts
        }
        counts.update(
            {
                key: slot_other[key] + ew_other[key] for key in slot_other
            }
        )
        return counts


__all__ = [
    "CLOSED_STATES",
    "ENTRY_LIMIT",
    "KIND_EXTRA_WORK",
    "KIND_TICKET_SLOT",
    "LATE_LIMIT",
    "LATE_LIVE_TICKET_STATUSES",
    "OVERDUE_LIMIT",
    "UNDATED_LIMIT",
    "UPCOMING_LIMIT",
    "WorkPlanView",
]
