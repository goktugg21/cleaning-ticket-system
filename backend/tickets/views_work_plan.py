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

from django.db.models import Count, Q
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

from .models import (
    StaffAssignmentSlotStatus,
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
    planned = Q(scheduled_start_at__date__lte=week_end) & _slot_window_end_q(
        "gte", week_start
    )
    if not (week_start <= today <= week_end):
        return planned
    return (
        planned
        | _SLOT_STATE_Q[STATE_IN_PROGRESS]
        | _slot_overdue_q(today)
    )


def _ew_week_q(
    week_start: datetime.date, week_end: datetime.date, today: datetime.date
) -> Q:
    planned = Q(preferred_date__lte=week_end) & (
        Q(planned_end_date__gte=week_start)
        | Q(planned_end_date__isnull=True, preferred_date__gte=week_start)
    )
    if not (week_start <= today <= week_end):
        return planned
    return planned | _EW_STATE_Q[STATE_IN_PROGRESS] | _ew_overdue_q(today)


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
    scheduled is exactly the one that most needs seeing."""
    return _SLOT_LIVE_Q & Q(scheduled_start_at__isnull=True)


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


def _entry_from_slot(slot, job, placement, day, today, *, viewer) -> dict:
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
    extra_work, job, placement, day, today, *, assignees
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
                "counts": self._counts(
                    slots, extra_work, week_start, week_end, today
                ),
                "entries": entries,
                "overdue_entries": overdue_entries,
                "upcoming_entries": upcoming_entries,
                # Sprint 181 §8 — the undated lane's rows.
                "undated_entries": undated_entries,
                "limits": {
                    "entries": ENTRY_LIMIT,
                    "overdue_entries": OVERDUE_LIMIT,
                    "upcoming_entries": UPCOMING_LIMIT,
                    "undated_entries": UNDATED_LIMIT,
                },
                "truncated": {
                    "entries": truncated,
                    "overdue_entries": overdue_truncated,
                    "upcoming_entries": upcoming_truncated,
                    "undated_entries": undated_truncated,
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
                _entry_from_slot(slot, job, placement, day, today, viewer=viewer)
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
    "OVERDUE_LIMIT",
    "UNDATED_LIMIT",
    "UPCOMING_LIMIT",
    "WorkPlanView",
]
