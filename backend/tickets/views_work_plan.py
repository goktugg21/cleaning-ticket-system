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

**W-VIEWER (owner ruling, 2026-08-27) — TWO READERS, TWO SOURCES.**

The previous wave placed every card on the day of the WORK — a staff
slot's day, or a part's — for every reader alike. That is right for the
person holding the slot and wrong for everybody else: measured on
crmtest the same day, TCK-2026-000361 (the ticket schedules it for
7 September) sat on 29 August because one of Ahmet's four slots did, and
TCK-2026-000342 (scheduled 30 August) sat on today's column stamped
"Planned 26 Aug — 1 day late" off the back of Ahmet's slot window.

The job's scheduled date and one person's assigned working date are two
different facts. Both are true. So this endpoint reads from two
different sources depending on who is asking:

    scope=company, provider-management role
        the JOB. One row per TICKET, from `_ticket_source`, placed on
        the ticket's own scheduled date (`tickets/job_dates.py`). Five
        people on it is still ONE card. No slot date and no part date
        can move it.

    every other caller (this is the only shape STAFF can get)
        the SLOT. One row per assignment the CALLER holds, from
        `_slot_source`, placed on the day THEY were given, with THEIR
        parts on it. Unchanged from Sprint 179A.

A staff member therefore sees a job on their own working day and a
manager sees the same job on its scheduled day, and neither is lying.
The ticket's Scheduling card still shows every staff window to anybody
who opens it — the general board just stops re-publishing them.

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

from django.db.models import (
    Case,
    Count,
    DateField,
    DateTimeField,
    Exists,
    F,
    Max,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import (
    IsAuthenticatedAndActive,
    is_customer_side,
    is_provider_management_role,
)
from accounts.models import UserRole
from accounts.scoping import scope_tickets_for
from buildings.models import BuildingManagerAssignment
from extra_work.models import (
    ExtraWorkAssignment,
    ExtraWorkPlannedHours,
    ExtraWorkRequest,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
)
from extra_work.display_phase import display_phase as ew_display_phase
from extra_work.scoping import scope_extra_work_for

from . import lateness as late_rules
from .detail_facts import ticket_finished_at, ticket_is_live, ticket_settled_at
from .job_dates import (
    PLAN_SOURCE_CUSTOMER_WISH,
    PLAN_SOURCE_PROVIDER_PLAN,
    PLAN_SOURCE_TICKET,
    job_plan_source,
    JOB_START,
    JOB_WINDOW_END,
    job_deadline,
    job_due_q,
    job_window,
    job_wish_day,
    with_job_dates,
)
from .lateness_index import LATE_LIVE_TICKET_STATUSES, LatenessIndex
from .models import (
    StaffAssignmentSlotStatus,
    SubTask,
    Ticket,
    TicketManagerAssignment,
    TicketStaffAssignment,
    TicketStatus,
)
from .plan_provenance import (
    NO_PLAN,
    PLAN_KIND_SCHEDULE,
    PlanProvenance,
    extra_work_plan_provenance,
    ticket_plan_provenance,
)
from .work_plan import (
    CLOSED_STATES,
    PLACEMENT_OVERDUE,
    PLACEMENT_PLANNED,
    PLACEMENT_REVIEW,
    PLACEMENT_ROLLED,
    STATE_BLOCKED,
    STATE_DONE,
    STATE_IN_PROGRESS,
    STATE_OPEN,
    Job,
    day_for,
    days_to_due,
    is_overdue,
    iso_week_bounds,
    overdue_days,
    placement_for,
    review_days,
    rolled_days,
    rolls_forward,
    settled_days_after_plan,
)


#: One person's dated piece of a ticket. The shape a caller reading
#: THEIR OWN week gets.
KIND_TICKET_SLOT = "TICKET_SLOT"
#: W-VIEWER — the JOB. One row per ticket, on the ticket's own scheduled
#: date, whatever its people's days say. The shape a provider-management
#: caller reading the company's week gets. A separate kind rather than a
#: flag on `TICKET_SLOT` because the two carry different `status` values
#: — a ticket status here, a slot status there — and the browser picks a
#: badge off `kind`. One kind meaning two status vocabularies is how a
#: badge ends up rendering a raw enum.
KIND_TICKET = "TICKET"
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
#: WP-1 G1 (Addendum D §D.11.2) — the "Vastgelopen — actie nodig" list.
#: Same bound as its flat-list siblings, for the same reason.
STUCK_LIMIT = 100
#: P-3 §A.1 — the "Wacht op klant" list: work sent to the customer and
#: waiting on their answer. In the current week those rows leave the
#: seven columns (a finished job sitting calm in Tuesday's column read
#: as "something is wrong with Tuesday" — the owner needed three days
#: to see why) and live behind ONE chip, like the undated lane.
WAITING_LIMIT = 100

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

#: W-PLANTRUTH §1b — the TICKET's work is still open: the ladder's own
#: set (`LATE_LIVE_TICKET_STATUSES`), and not archived. An ASSIGNED slot
#: on a ticket that is in review, approved or closed is a slot nobody is
#: expected to work any more; before this wave it read OPEN on the
#: board, which is how a closed ticket's stale slot rendered as an open
#: card in a past column (measured on crmtest: TCK-2026-000226 and
#: -000343, both CLOSED, each with an ASSIGNED slot).
_TICKET_LIVE_Q = Q(
    ticket__status__in=LATE_LIVE_TICKET_STATUSES,
    ticket__archived_at__isnull=True,
)
#: PENDING — somebody is still expected to do this: an ASSIGNED slot on
#: a ticket whose work is still open. The predicate rule 5 rolls on.
_SLOT_PENDING_Q = _SLOT_LIVE_Q & _TICKET_LIVE_Q

#: P-11 A10 — ACTIVE: pending AND not on hold. An on-hold job is off
#: the board entirely: it lives ONLY in the On hold fold until someone
#: takes it off hold (the owner, over ticket 460 rolling onto today as
#: late; reverses the P-3 matrix's "a parked job WITH a day keeps its
#: place"). Pending still means "the work is undone" — the escalation
#: sweep and the lateness INDEX keep reading it — but every board and
#: strip surface reads ACTIVE.
_SLOT_ACTIVE_Q = _SLOT_PENDING_Q & ~Q(ticket__status=TicketStatus.ON_HOLD)

#: A ticket that ended without the work being done: the slot on it is
#: BLOCKED rather than DONE.
_TICKET_BLOCKED_STATUSES = frozenset(
    {TicketStatus.REJECTED, TicketStatus.CONVERTED_TO_EXTRA_WORK}
)

_SLOT_STATE_Q = {
    STATE_DONE: Q(slot_status=StaffAssignmentSlotStatus.COMPLETED)
    | (
        _SLOT_LIVE_Q
        & ~_TICKET_LIVE_Q
        & ~Q(ticket__status__in=list(_TICKET_BLOCKED_STATUSES))
    ),
    STATE_BLOCKED: Q(
        slot_status__in=[
            StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE,
            StaffAssignmentSlotStatus.CANCELLED,
        ]
    )
    | (_SLOT_LIVE_Q & Q(ticket__status__in=list(_TICKET_BLOCKED_STATUSES))),
    STATE_IN_PROGRESS: _SLOT_PENDING_Q & Q(ticket__status=TicketStatus.IN_PROGRESS),
    STATE_OPEN: _SLOT_PENDING_Q & ~Q(ticket__status=TicketStatus.IN_PROGRESS),
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


# ---------------------------------------------------------------------
# P-9 §A.2b — rule 10 in SQL: the day a finished job was finished.
#
# `work_plan.Job.settled_day` is the local date of the finish moment,
# set only on a job in the DONE state. Each source annotates the same
# date onto its rows (`settled_day`) so the week predicates below can
# say "in the week of its settled day" and compose into
# `Count(filter=...)` like every other predicate here. The chains are
# the Python twins' chains, in the same order:
#
#   ticket   manager_review_at, sent_for_approval_at, approved_at,
#            closed_at, resolved_at         (`detail_facts.ticket_finished_at`)
#   slot     completed_at, then the ticket's chain — but ONLY the slot's
#            own stamp while its ticket is live (a colleague may still be
#            working; a stale stamp from an earlier report must not
#            place this person's finished slot)
#   extra    the latest history leg into COMPLETED
#   work
#
# `TruncDate` converts in the current timezone, which is what
# `_local_date` does for the Python side.
# ---------------------------------------------------------------------

SETTLED_DAY = "settled_day"

_TICKET_FINISH_CHAIN = (
    "manager_review_at",
    "sent_for_approval_at",
    "approved_at",
    "closed_at",
    "resolved_at",
)

#: The blocked endings' chain — not a finish, but the moment the job
#: left the board (`detail_facts.ticket_finished_at`'s other branch).
_TICKET_BLOCKED_FINISH_CHAIN = (
    "rejected_at",
    "closed_at",
    "approved_at",
    "resolved_at",
)

#: P-10 A1 — reported done, waiting for somebody's check: NOT finished.
#: A ticket in one of these carries a report stamp and no finish; it is
#: in no past column (the review strip / the responsible manager's today
#: card, or the customer zone, carry it), and it settles on its report
#: day only once the chain is over.
_REPORTED_DONE_STATUS_LIST = [
    TicketStatus.WAITING_MANAGER_REVIEW,
    TicketStatus.WAITING_CUSTOMER_APPROVAL,
]


def _ticket_finish_expr(prefix: str = ""):
    """SQL twin of `detail_facts.ticket_finished_at`, branch for branch:
    NULL while reported done (P-10 A1), the blocked chain for a blocked
    ending, else the finish chain. `prefix` walks it from a slot
    (`ticket__`)."""

    def chain(fields):
        return Coalesce(
            *[F(f"{prefix}{field}") for field in fields],
            output_field=DateTimeField(),
        )

    return Case(
        When(
            Q(**{f"{prefix}status__in": _REPORTED_DONE_STATUS_LIST}),
            then=Value(None, output_field=DateTimeField()),
        ),
        When(
            Q(**{f"{prefix}status__in": list(_TICKET_BLOCKED_STATUSES)}),
            then=chain(_TICKET_BLOCKED_FINISH_CHAIN),
        ),
        default=chain(_TICKET_FINISH_CHAIN),
        output_field=DateTimeField(),
    )


def _with_ticket_settled_day(queryset):
    return queryset.annotate(
        **{SETTLED_DAY: TruncDate(_ticket_finish_expr(), output_field=DateField())}
    )


def _with_slot_settled_day(queryset):
    # The person's own completion stamp, else the ticket's finish. While
    # the ticket is live — or reported done and unchecked (P-10 A1) —
    # ONLY the slot's own stamp: a colleague may still be working, and a
    # report stamp is not a finish.
    return queryset.annotate(
        **{
            SETTLED_DAY: TruncDate(
                Case(
                    When(_TICKET_LIVE_Q, then=F("completed_at")),
                    When(
                        Q(ticket__status__in=_REPORTED_DONE_STATUS_LIST),
                        then=F("completed_at"),
                    ),
                    default=Coalesce(
                        "completed_at",
                        _ticket_finish_expr("ticket__"),
                        output_field=DateTimeField(),
                    ),
                    output_field=DateTimeField(),
                ),
                output_field=DateField(),
            )
        }
    )


def _with_ew_settled_day(queryset):
    completed_leg = (
        ExtraWorkStatusHistory.objects.filter(
            extra_work_id=OuterRef("pk"), new_status=ExtraWorkStatus.COMPLETED
        )
        .order_by("-created_at", "-id")
        .values("created_at")[:1]
    )
    return queryset.annotate(
        **{
            SETTLED_DAY: TruncDate(
                Subquery(completed_leg, output_field=DateTimeField()),
                output_field=DateField(),
            )
        }
    )


def _settled_in_week_q(week_start: datetime.date, week_end: datetime.date) -> Q:
    return Q(**{f"{SETTLED_DAY}__gte": week_start, f"{SETTLED_DAY}__lte": week_end})


def _home_or_settled_q(
    home: Q, over_q: Q, week_start: datetime.date, week_end: datetime.date
) -> Q:
    """Rule 1 for a job that is not over (or over at an unknown moment),
    rule 10 for a job that is over: SQL twin of the first branch of
    `work_plan.placement_for`. `over_q` is the closed set — finished OR
    blocked (P-10 A1: a rejected / converted job hangs on the day it
    left the board when that moment is known, like a finished one)."""
    return (home & (~over_q | Q(**{f"{SETTLED_DAY}__isnull": True}))) | (
        over_q & _settled_in_week_q(week_start, week_end)
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
    # `_SLOT_ACTIVE_Q`, not `_SLOT_LIVE_Q`: the Python twin `is_overdue`
    # reads "state not closed", and a slot on a finished ticket is DONE.
    # P-11 A10 — and not on hold: a paused job does not nag.
    return _SLOT_ACTIVE_Q & _slot_due_q("lt", today)


# ---------------------------------------------------------------------
# P-10 A6 / P-14 A5 — THE EXTRA WORK'S WINDOW IS THE PROVIDER'S PLAN,
# FULL STOP.
#
# The "Not planned yet" row's one button writes `provider_planned_date`
# (`POST /extra-work/bulk-dates/`, Sprint 182 §3), which is what
# `tickets/job_dates.py` reads as the job's window for a spawned
# ticket. P-10 A6 made that plan win over the request's `preferred_date`
# (the customer's WISH) but kept the wish as a fallback — and a wish is
# not a plan: a request with only a wished day sat in today's column
# with the badge "Not planned yet" beside it (web-Claude's P-14 pass;
# the P-1 defect reopened). P-14 A5 undoes the fallback for PLACEMENT:
# no provider plan means NO window — the row belongs to the "Not
# planned yet" strip, in no column of any week. The wish may seed a
# card's details, never its column. Every EW predicate and the Python
# twin `_extra_work_job` read these and nothing else. (The lateness
# ladder in `lateness_index.py` still reads the wish deliberately: a
# wished day that passes unplanned is exactly what it must surface.)
# ---------------------------------------------------------------------
EW_START = "ew_start"
EW_END = "ew_end"


def _with_ew_dates(queryset):
    # `ew_end` is NEVER NULL when `ew_start` is set: the end, else the
    # start (`Job.window_end`'s one-day reading). An annotation Django
    # cannot know to be nullable would otherwise turn every `~Q(ew_end
    # < today)` into SQL NULL and drop the row from the board — the
    # three-valued trap a real nullable column is guarded against.
    return queryset.annotate(
        **{
            EW_START: F("provider_planned_date"),
            EW_END: Coalesce(
                "provider_planned_end_date",
                "provider_planned_date",
                output_field=DateField(),
            ),
        }
    )


def _ew_planned_window(extra_work):
    """Python twin of `_with_ew_dates`: `(start, end)` — the provider's
    committed window, or nothing (P-14 A5: the wish is not a plan)."""
    if extra_work.provider_planned_date is not None:
        return extra_work.provider_planned_date, extra_work.provider_planned_end_date
    return None, None


def _ew_window_end_q(lookup: str, value: datetime.date) -> Q:
    """`window_end <lookup> value` for an extra work — `Job.window_end`'s
    reading, over the P-10 A6 annotation (already the end-or-start)."""
    return Q(**{f"{EW_END}__{lookup}": value})


def _slot_rolled_q(today: datetime.date) -> Q:
    """W-PLANTRUTH §1b — SQL twin of `work_plan.rolls_forward` for a
    slot: active, and its last planned day has passed (P-11 A10 —
    ACTIVE: an on-hold job never rolls)."""
    return _SLOT_ACTIVE_Q & _slot_window_end_q("lt", today)


def _ew_rolled_q(today: datetime.date) -> Q:
    return _EW_LIVE_Q & _ew_window_end_q("lt", today)


def _slot_waiting_customer_q() -> Q:
    """P-3 §A.1 — SQL twin of rule 9 for a slot: the job it is on has been
    sent to the customer and waits on their answer."""
    return Q(ticket__status=TicketStatus.WAITING_CUSTOMER_APPROVAL)


def _slot_review_q() -> Q:
    """P-10 A2 — the job this slot is on was reported done and waits for
    a manager's check. For the worker it is a strip ("Reported done,
    waiting for the check"), never a column: not their day any more,
    not finished either."""
    return Q(ticket__status=TicketStatus.WAITING_MANAGER_REVIEW)


def _slot_board_q(
    week_start: datetime.date, week_end: datetime.date, today: datetime.date
) -> Q:
    """What the seven columns of THIS week hold, in SQL.

    Rule 1 (planned in this week) MINUS rule 5's rolled rows (a pending
    row whose planned day has passed is not in its past column any
    more), PLUS — when today is inside this week — every rolled row in
    scope, whichever week it was planned in, because it sits on today.
    The Python twin is the roll branch of `WorkPlanView._build`; the
    parity test asserts the two agree over the same rows.

    P-3 rule 9 / P-9 §A.2a — a row waiting on the customer is not in
    any column of ANY week: it is behind the "Wacht op klant" chip
    (the owner: "when it goes to customer approval it leaves the
    dates"). Until P-9 only the current week subtracted it.
    """
    board = _slot_week_q(week_start, week_end, today) & ~_slot_rolled_q(today)
    if week_start <= today <= week_end:
        board = board | _slot_rolled_q(today)
    # Rule 9 (customer) and P-10 A2 (manager's check): both waits are
    # outside the dates for the worker — strips, never columns.
    # P-11 A10 — and an on-hold job is in the fold, never a column
    # (its dated window would otherwise still overlap rule 1's week).
    return (
        board
        & ~_slot_waiting_customer_q()
        & ~_slot_review_q()
        & ~Q(ticket__status=TicketStatus.ON_HOLD)
    )


def _ew_board_q(
    week_start: datetime.date, week_end: datetime.date, today: datetime.date
) -> Q:
    board = _ew_week_q(week_start, week_end, today) & ~_ew_rolled_q(today)
    if week_start <= today <= week_end:
        board = board | _ew_rolled_q(today)
    return board


def _ew_overdue_q(today: datetime.date) -> Q:
    return _EW_LIVE_Q & Q(deadline__isnull=False, deadline__lt=today)


def _part_window_q(week_start: datetime.date, week_end: datetime.date) -> Q:
    """W-LATE §3b — a PART this slot's person holds, windowed into this
    week. An `Exists` rather than a join, so the predicate composes into
    `Count(filter=...)` without multiplying slot rows by their parts."""
    parts = SubTask.objects.filter(
        ticket_id=OuterRef("ticket_id"),
        staff_assignments__user_id=OuterRef("user_id"),
        planned_start_date__lte=week_end,
    ).filter(
        Q(planned_end_date__gte=week_start)
        | Q(planned_end_date__isnull=True, planned_start_date__gte=week_start)
    )
    return Exists(parts)


def _slot_week_q(
    week_start: datetime.date, week_end: datetime.date, today: datetime.date
) -> Q:
    """SQL twin of `work_plan.placement_for`: planned placement, and
    nothing else. W-FIX1 E2 dropped the `| started | overdue` branches
    that used to copy live and late work onto today's column; those
    rows are the overdue strip's and the undated lane's. `today` is
    kept in the signature so the parity test can call both twins the
    same way.

    W-LATE §3b — OR a part window: a slot whose person holds a part
    windowed into this week is in this week too, on the part's day,
    under its ticket (`_part_day_in_week` is the Python twin)."""
    del today
    home = (
        Q(scheduled_start_at__date__lte=week_end)
        & _slot_window_end_q("gte", week_start)
    ) | _part_window_q(week_start, week_end)
    # P-9 §A.2b — a finished slot is in the week it was finished in.
    # P-10 A1 — so is a blocked one whose ending moment is known.
    return _home_or_settled_q(
        home,
        _SLOT_STATE_Q[STATE_DONE] | _SLOT_STATE_Q[STATE_BLOCKED],
        week_start,
        week_end,
    )


def _part_day_in_week(
    parts, week_start: datetime.date, week_end: datetime.date
) -> datetime.date | None:
    """The first day inside the week that one of `parts` is windowed on,
    or None. The Python twin of `_part_window_q`."""
    days = []
    for part in parts or []:
        start = part.get("planned_start")
        if not start:
            continue
        start_d = datetime.date.fromisoformat(start)
        end_d = (
            datetime.date.fromisoformat(part["planned_end"])
            if part.get("planned_end")
            else start_d
        )
        if start_d <= week_end and end_d >= week_start:
            days.append(max(start_d, week_start))
    return min(days) if days else None


def _viewer_window(job, parts):
    """W-VIEWER §5 — the window ONE PERSON was actually given.

    Their slot's window widened by their own parts' windows, which is the
    whole of what they were asked to do on this job. Returned as a plain
    `(start, end)` pair for `LatenessIndex.for_window`; `(None, None)`
    when they were given no date at all, which that method reads as
    "fall back to the job's own rung".
    """
    starts = [job.planned_start]
    ends = [job.window_end]
    for part in parts or []:
        start = part.get("planned_start")
        if not start:
            continue
        start_d = datetime.date.fromisoformat(start)
        end_d = (
            datetime.date.fromisoformat(part["planned_end"])
            if part.get("planned_end")
            else start_d
        )
        starts.append(start_d)
        ends.append(end_d)
    starts = [d for d in starts if d is not None]
    ends = [d for d in ends if d is not None]
    if not starts and not ends:
        return None, None
    return (min(starts) if starts else None), (max(ends) if ends else None)


def _ew_week_q(
    week_start: datetime.date, week_end: datetime.date, today: datetime.date
) -> Q:
    del today
    home = Q(**{f"{EW_START}__lte": week_end}) & _ew_window_end_q("gte", week_start)
    # P-9 §A.2b — a completed extra work is in the week it was completed.
    return _home_or_settled_q(home, _EW_STATE_Q[STATE_DONE], week_start, week_end)


def _slot_upcoming_q(week_end: datetime.date) -> Q:
    # No `is_overdue` guard, unlike the Python rule: a job planned to
    # START after this week cannot also be past a due date that is on or
    # before today, because today is inside or before this week. The
    # parity test pins that reasoning rather than trusting it.
    # P-11 A10 — an on-hold job is not "coming up" either.
    return (
        Q(scheduled_start_at__date__gt=week_end)
        & _SLOT_STATE_Q[STATE_OPEN]
        & ~Q(ticket__status=TicketStatus.ON_HOLD)
    )


def _ew_upcoming_q(week_end: datetime.date) -> Q:
    return Q(**{f"{EW_START}__gt": week_end}) & _EW_STATE_Q[STATE_OPEN]


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
    # W-PLANTRUTH §1a (owner ruling) — ONE FACT PLACES THE BOARD: the
    # planned day of the work, which is the slot's (or a part's). The
    # ticket-level schedule is a different fact and creates no
    # placement, so it cannot take a job out of this lane either: a job
    # whose ticket carries a date but whose people have no day is work
    # nobody has planned, and it sits here until somebody does. The
    # clause `ticket__scheduled_start_at__isnull=True` that W-FIX1 A1
    # added is gone for that reason. Measured on crmtest before the
    # change: six live tickets carried a ticket date, ASSIGNED slots and
    # no slot day — on no column, in no lane, late by a date the board
    # never used.
    #
    # `_SLOT_PENDING_Q` rather than `_SLOT_LIVE_Q`: an ASSIGNED slot on a
    # closed ticket is not "not planned yet", it is over.
    return (
        _SLOT_PENDING_Q
        & Q(scheduled_start_at__isnull=True)
        & ~Exists(dated_sibling)
        # P-7 S8 — a worker's slot on a parked job is in the parked
        # list, not the nag (the job-side rule, mirrored).
        & ~Q(ticket__status=TicketStatus.ON_HOLD)
    )


def _slot_parked_q() -> Q:
    """P-7 S8 — the slot twin of `_ticket_parked_q`. P-11 A10 — dated
    or not; the fold is the on-hold job's only place."""
    return _SLOT_PENDING_Q & Q(ticket__status=TicketStatus.ON_HOLD)


def _ew_undated_q() -> Q:
    # P-14 A5 — no provider plan. The customer's wish alone is not a
    # window (a wish is not a plan), so a wished-but-unplanned request
    # sits HERE, not in a column.
    return _EW_LIVE_Q & Q(**{f"{EW_START}__isnull": True})


# ---------------------------------------------------------------------
# WP-1 G1 — the "unable to complete" leak, in SQL.
#
# A slot marked UNABLE_TO_COMPLETE maps to BLOCKED, which counts as
# closed: it stops carrying forward and silently leaves the system's
# attention. These predicates name the jobs that stopped WITHOUT a human
# decision, so the view can put them in a follow-up list that only a
# human action empties. Blocked is not done.
#
# The job-level reading: a live ticket where somebody said "I could not
# do this" and NOBODY is expected to work it any more (no ASSIGNED slot
# left). While a colleague still holds an ASSIGNED slot the job is not
# silently gone — their slot still rolls forward — so it is not stuck.
# Rescheduling (the unable slot back to ASSIGNED with a new day),
# reassigning (a fresh ASSIGNED slot for somebody else) and cancelling
# (the slot to CANCELLED, or the ticket out of its live statuses) are
# exactly the three existing actions that make these predicates false —
# the list mutates nothing.
# ---------------------------------------------------------------------


def _unable_slots(ticket_ref: str):
    return TicketStaffAssignment.objects.filter(
        ticket_id=OuterRef(ticket_ref),
        slot_status=StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE,
    )


def _assigned_slots(ticket_ref: str):
    return TicketStaffAssignment.objects.filter(
        ticket_id=OuterRef(ticket_ref),
        slot_status=StaffAssignmentSlotStatus.ASSIGNED,
    )


def _ticket_stuck_q() -> Q:
    """A stuck JOB: live, at least one unable slot, nobody assigned."""
    return (
        _TICKET_ACTIVE_Q
        & Exists(_unable_slots("id"))
        & ~Exists(_assigned_slots("id"))
    )


def _slot_stuck_q() -> Q:
    """The caller's own stuck piece: their UNABLE_TO_COMPLETE slot on a
    live ticket that nobody is assigned to any more. The same job-level
    condition as `_ticket_stuck_q`, read from the slot side, so a worker
    and their manager agree on what is stuck."""
    return (
        Q(slot_status=StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE)
        & _TICKET_LIVE_Q
        # P-11 A10 — a paused job is not stuck; it is in the fold.
        & ~Q(ticket__status=TicketStatus.ON_HOLD)
        & ~Exists(_assigned_slots("ticket_id"))
    )


def _ew_stuck_q() -> Q:
    """A stuck EXTRA WORK: still live commercially, but its operational
    ticket ended in a blocked status (rejected / converted) — the work
    stopped without being done and without anybody deciding about the
    request itself."""
    blocked_ticket = Ticket.objects.filter(
        extra_work_request_id=OuterRef("id"),
        deleted_at__isnull=True,
        status__in=list(_TICKET_BLOCKED_STATUSES),
    )
    return _EW_LIVE_Q & Exists(blocked_ticket)


# ---------------------------------------------------------------------
# W-VIEWER — the JOB's rule, in SQL.
#
# The same five questions the slot predicates above answer, asked of a
# TICKET and answered from the ticket's own dates. Every one of them
# reads the `job_start` / `job_window_end` annotations `with_job_dates`
# adds, so the fallback chain is stated once (`tickets/job_dates.py`)
# and no predicate here can drift off it.
#
# `WorkPlanRuleParityTests` covers these the same way it covers the slot
# twins: each SQL count is asserted equal to the count the Python rule
# produces over the same rows.
# ---------------------------------------------------------------------

#: Somebody on the provider side still has to do this. Same set the
#: ladder uses, so "on the board as work" and "can be late" agree.
_TICKET_PENDING_Q = Q(
    status__in=LATE_LIVE_TICKET_STATUSES, archived_at__isnull=True
)

#: P-11 A10 — the job twin of `_SLOT_ACTIVE_Q`: pending AND not on
#: hold. See that constant for the ruling.
_TICKET_ACTIVE_Q = _TICKET_PENDING_Q & ~Q(status=TicketStatus.ON_HOLD)

_TICKET_STATE_Q = {
    STATE_DONE: ~_TICKET_PENDING_Q
    & ~Q(status__in=list(_TICKET_BLOCKED_STATUSES)),
    STATE_BLOCKED: ~_TICKET_PENDING_Q
    & Q(status__in=list(_TICKET_BLOCKED_STATUSES)),
    STATE_IN_PROGRESS: _TICKET_PENDING_Q & Q(status=TicketStatus.IN_PROGRESS),
    STATE_OPEN: _TICKET_PENDING_Q & ~Q(status=TicketStatus.IN_PROGRESS),
}


def _ticket_week_q(week_start: datetime.date, week_end: datetime.date) -> Q:
    """Rule 1 for a job — does its planned window overlap this week?

    No part-window branch, unlike `_slot_week_q`. A part is one person's
    named half of the work and its window is a staffing fact; the ruling
    is explicit that no such date may move the job card off the day the
    ticket states.
    """
    home = Q(
        **{f"{JOB_START}__lte": week_end, f"{JOB_WINDOW_END}__gte": week_start}
    )
    # P-9 §A.2b (rule 10) — a finished job is in the week of its finish.
    # P-10 A1 — a blocked job in the week it left the board.
    return _home_or_settled_q(
        home,
        _TICKET_STATE_Q[STATE_DONE] | _TICKET_STATE_Q[STATE_BLOCKED],
        week_start,
        week_end,
    )


def _ticket_rolled_q(today: datetime.date) -> Q:
    """Rule 5 for a job: active, and its last planned day has passed.
    P-11 A10 — ACTIVE, not PENDING: an on-hold job never rolls."""
    return _TICKET_ACTIVE_Q & Q(**{f"{JOB_WINDOW_END}__lt": today})


def _ticket_review_q() -> Q:
    """Rule 8 (P-1 §3) — SQL twin of `work_plan.awaits_review` for a
    job: the worker finished, a manager has not confirmed. The status
    alone (like the customer wait): archive is housekeeping, and an
    archived job still waiting for a check is still waiting."""
    return Q(status=TicketStatus.WAITING_MANAGER_REVIEW)


def _ticket_responsible_q(user) -> Q:
    """P-10 A2 — is THIS viewer a manager responsible for the job?

    The owner's ruling: "everyone's schedule is their own; the manager
    sees it on their day, the owner sees it in a section." Responsible
    is `notifications.services.ticket_responsible_manager_recipients`'s
    three tiers, first non-empty wins, asked about one person:

      1. named on the ticket (`TicketManagerAssignment`);
      2. else the legacy primary manager (`Ticket.assigned_to`);
      3. else — for a BUILDING_MANAGER — the building's authority ring
         (`BuildingManagerAssignment`).

    `Exists` throughout, so the predicate composes into `Count` without
    multiplying rows. A SUPER_ADMIN or provider admin is responsible for
    nothing by role: they read the strip.
    """
    named_any = TicketManagerAssignment.objects.filter(ticket_id=OuterRef("id"))
    named_me = named_any.filter(user_id=user.id)
    tier1 = Exists(named_me)
    tier2 = ~Exists(named_any) & Q(assigned_to_id=user.id)
    q = Q(tier1) | Q(tier2)
    if user.role == UserRole.BUILDING_MANAGER:
        ring = BuildingManagerAssignment.objects.filter(
            building_id=OuterRef("building_id"), user_id=user.id
        )
        q = q | (~Exists(named_any) & Q(assigned_to__isnull=True) & Exists(ring))
    return q


def _ticket_waiting_customer_q() -> Q:
    """P-3 §A.1 — rule 9: sent to the customer, waiting on their answer.

    Neither pending (the provider side is done) nor over (the customer
    has not answered). Before this the board read it as settled and
    left the calm card in the column of its planned day; on the
    CURRENT week that is a finished-looking card in a past column, and
    the owner — the system's own designer — needed three days to work
    out why it sat there. In the current week such a job is in no
    column: it is one row behind the "Wacht op klant" chip, next to
    "Nog niet gepland". Past and future weeks keep rule 1: browsed as
    history, the week shows what it held.
    """
    # The status alone: an archived ticket still waiting on the customer
    # is still waiting on the customer (archive is housekeeping).
    return Q(status=TicketStatus.WAITING_CUSTOMER_APPROVAL)


def _ticket_board_q(
    week_start: datetime.date,
    week_end: datetime.date,
    today: datetime.date,
    user=None,
) -> Q:
    # P-10 A1/A2 — a job waiting for a manager's check is in NO column
    # of any week (its report is not a finish); the ONE exception is
    # the responsible manager's today, where it hangs as their card to
    # check (rule 8, made personal). Everybody else reads it in the
    # "Waiting for a manager's check" strip.
    board = (
        _ticket_week_q(week_start, week_end)
        & ~_ticket_rolled_q(today)
        & ~_ticket_review_q()
    )
    if week_start <= today <= week_end:
        # Rule 5's rolled rows sit on today, whichever week they were
        # planned in; so do the review rows this viewer must check.
        board = board | _ticket_rolled_q(today)
        if user is not None:
            board = board | (_ticket_review_q() & _ticket_responsible_q(user))
    # Rule 9 (P-9 §A.2a: in EVERY week) — waiting rows sit nowhere on
    # the board; they are zone 2, outside the dates.
    # P-11 A10 — and an on-hold job is in the fold, never a column.
    return (
        board
        & ~_ticket_waiting_customer_q()
        & ~Q(status=TicketStatus.ON_HOLD)
    )


def _ticket_overdue_q(today: datetime.date) -> Q:
    return _TICKET_ACTIVE_Q & job_due_q("lt", today)


def _ticket_upcoming_q(week_end: datetime.date) -> Q:
    # P-11 A10 — an on-hold job is not "coming up" either.
    return (
        Q(**{f"{JOB_START}__gt": week_end})
        & _TICKET_STATE_Q[STATE_OPEN]
        & ~Q(status=TicketStatus.ON_HOLD)
    )


def _ticket_parked_q() -> Q:
    """P-7 S8 — parked (ON_HOLD through triage) and without a day.

    The owner's ruling: parked work leaves the "Not planned yet" nag.
    It is its own quiet list ("Geparkeerd (N)") behind the same drawer,
    with the reason it was parked for.

    P-11 A10 — dated or not: an on-hold job lives ONLY here until
    someone takes it off hold (reverses the P-3 matrix's "a parked job
    WITH a day keeps its place" — ticket 460 rolled onto the owner's
    today as late while deliberately paused)."""
    return _TICKET_PENDING_Q & Q(status=TicketStatus.ON_HOLD)


def _ticket_undated_q() -> Q:
    """Nobody has said when this job happens.

    W-VIEWER — a JOB-level question now, and only that: the ticket
    states no date and inherits none. Under W-PLANTRUTH §1a this lane
    asked whether the PEOPLE had days, which put a ticket scheduled for
    next Tuesday in "not planned yet" because nobody had been given a
    slot time. The manager's board answers "when does this job happen",
    and it happens on Tuesday.
    """
    # P-7 S8 — parked work is not "not planned yet": it was decided
    # about, with a reason. It has its own list (`_ticket_parked_q`).
    return (
        _TICKET_PENDING_Q
        & Q(**{f"{JOB_START}__isnull": True})
        & ~Q(status=TicketStatus.ON_HOLD)
    )


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
    queryset = queryset.select_related(
        "ticket",
        "ticket__building",
        "ticket__customer",
        # P-1 — who created the ticket and who gave the slot its day.
        "ticket__created_by",
        "assigned_by",
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
    ).prefetch_related(
        # P-9 §A.3 — the reported-done leg (its moment and who reported)
        # is read off the prefetched history, never one query per card.
        "ticket__status_history__changed_by",
    )
    return _with_slot_settled_day(queryset)


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
    # P-1 — the plan's provenance (`extra_work_plan_provenance`) reads
    # the "committed window" history row; one prefetch for the board.
    return _with_ew_dates(
        _with_ew_settled_day(
            queryset.select_related("building", "customer", "created_by")
            # P-11 A1 — `_ew_phase` reads the spawned ticket's status.
            .prefetch_related("status_history__changed_by", "operational_tickets")
        )
    )


def _stuck_extra_work_source(user, team: bool):
    """WP-1 G1 — the stuck EXTRA WORK rows.

    Mirrors `_extra_work_source`'s scoping exactly, WITHOUT the
    covered-by-a-slot exclusion, deliberately: the slot on a blocked
    ticket is not pending and places no card anywhere, so leaving the
    exclusion in would hide precisely the rows this list exists for.
    """
    assigned_ids = ExtraWorkAssignment.objects.values("extra_work_request_id")
    if team:
        queryset = scope_extra_work_for(user).filter(id__in=assigned_ids)
    else:
        queryset = ExtraWorkRequest.objects.filter(
            deleted_at__isnull=True,
            id__in=assigned_ids.filter(user=user),
        )
    return _with_ew_dates(
        queryset.filter(_ew_stuck_q())
        .select_related("building", "customer")
        # P-11 A1 — `_ew_phase` reads the spawned ticket's status.
        .prefetch_related("operational_tickets")
    )


def _ticket_source(user):
    """W-VIEWER — the JOB rows for a provider-management caller.

    ONE ROW PER TICKET. `scope_tickets_for` is the same helper the ticket
    list and the slot path already use, so this cannot show a ticket the
    actor could not open — it is not a second scoping path.

    MEMBERSHIP IS DELIBERATELY UNCHANGED: a ticket reaches this board
    when at least one person is on it and not cancelled, which is exactly
    the set the slot-driven board carried. The ruling is about WHERE a
    card is placed, not about which jobs are on the board, and quietly
    widening this to every scheduled ticket in scope would put a
    different complaint on the owner's screen than the one being fixed.

    An `Exists` rather than a join: a join would return one row per slot,
    which is the duplication this whole change exists to end, and it
    would also make `Count("id")` count slots.
    """
    staffed = TicketStaffAssignment.objects.filter(
        ticket_id=OuterRef("id")
    ).exclude(slot_status=StaffAssignmentSlotStatus.CANCELLED)
    queryset = (
        scope_tickets_for(user)
        .filter(deleted_at__isnull=True)
        .filter(Exists(staffed))
        .select_related(
            "building",
            "customer",
            "extra_work_request",
            # P-1 — provenance: who created it, who planned it. The
            # schedule rows and the extra work's "committed window" row
            # are prefetched once for the board rather than per card.
            "created_by",
            "planned_occurrence__recurring_job__created_by",
        )
        .prefetch_related(
            "status_history__changed_by",
            "extra_work_request__status_history__changed_by",
        )
    )
    return _with_ticket_settled_day(with_job_dates(queryset))


def _ticket_parked_source(user):
    """P-15 (P-14's S3 finding) — the PARKED list admits unstaffed jobs.

    `_ticket_source` gates the whole board on `Exists(non-cancelled
    slot)` — membership the ruling deliberately kept. But an ON_HOLD
    ticket with NOBODY on it then reached no lane at all, including
    "Geparkeerd": the undated lane excludes ON_HOLD by design, so the
    job vanished from the entire planning surface (ticket 309 live).
    Parking a job and pulling its crew is a normal one-two; the parked
    lane is exactly where such a job must wait.

    Same scoping helper, same annotations, NO staffing gate, narrowed to
    the parked predicate — used only for the parked list and its count,
    so the columns and every other chip keep the staffed membership."""
    queryset = (
        scope_tickets_for(user)
        .filter(deleted_at__isnull=True)
        .filter(_ticket_parked_q())
        .select_related(
            "building",
            "customer",
            "extra_work_request",
            "created_by",
            "planned_occurrence__recurring_job__created_by",
        )
        .prefetch_related(
            "status_history__changed_by",
            "extra_work_request__status_history__changed_by",
        )
    )
    return _with_ticket_settled_day(with_job_dates(queryset))


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


def _clock(value) -> str | None:
    """P-3 §A.3 — the clock time of a planned moment, in the SERVER's
    zone, or None when the plan is a DAY and not a time.

    The convention every writer already follows: a date-only plan is
    stored as local midnight (`TicketScheduleCard` sends the day with
    `00:00`; `set_schedule` stores it as given), and the schedule card
    reads midnight back as "no time". The board printed the raw instant
    instead — `2026-08-26 22:00Z` (27 August, 00:00 Amsterdam) rendered
    as "01:00 AM" in a browser three hours east of Greenwich, the
    owner's. So the SERVER says whether a time exists, in ITS zone, and
    a card prints a clock only when this is not None.
    """
    if value is None:
        return None
    local = timezone.localtime(value)
    if local.hour == 0 and local.minute == 0:
        return None
    return local.strftime("%H:%M")



def _stamp_parked_reasons(entries) -> None:
    """P-7 S8 — the reason a job was parked: the note on its latest
    history row INTO ON_HOLD (the triage dialog's one reason, written
    by `apply_transition` on that leg). One query for the whole list,
    never one per row; the list is bounded by UNDATED_LIMIT."""
    from .models import TicketStatusHistory

    ticket_ids = [
        e["ticket_id"] for e in entries if e.get("ticket_id") is not None
    ]
    if not ticket_ids:
        return
    reasons = {}
    rows = (
        TicketStatusHistory.objects.filter(
            ticket_id__in=ticket_ids, new_status=TicketStatus.ON_HOLD
        )
        .order_by("ticket_id", "-created_at", "-id")
        .values_list("ticket_id", "note")
    )
    for ticket_id, note in rows:
        reasons.setdefault(ticket_id, (note or "").strip() or None)
    for entry in entries:
        entry["parked_reason"] = reasons.get(entry.get("ticket_id"))


def _stamp_manager_names(entries) -> None:
    """P-10 A2 — WHO is answerable for each job on the manager's-check
    strip: `ticket_responsible_manager_recipients`'s three tiers, asked
    per ticket, in three queries for the whole (bounded) list. The
    strip's summary names them ("Gökhan 2 · Sophie 1 · oldest 6 days")
    and the worker's row says whose check it waits on."""
    ticket_ids = {e["ticket_id"] for e in entries if e.get("ticket_id")}
    if not ticket_ids:
        return
    named: dict[int, list[str]] = {}
    rows = (
        TicketManagerAssignment.objects.filter(ticket_id__in=list(ticket_ids))
        .select_related("user")
        .order_by("user__full_name", "user__email", "id")
    )
    for row in rows:
        names = named.setdefault(row.ticket_id, [])
        label = _person_label(row.user)
        if label and label not in names:
            names.append(label)
    tickets = {
        t.id: t
        for t in Ticket.objects.filter(id__in=list(ticket_ids)).select_related(
            "assigned_to"
        )
    }
    ring_buildings = {
        t.building_id
        for t in tickets.values()
        if t.building_id and t.id not in named and t.assigned_to_id is None
    }
    ring: dict[int, list[str]] = {}
    if ring_buildings:
        members = (
            BuildingManagerAssignment.objects.filter(
                building_id__in=list(ring_buildings),
                user__role=UserRole.BUILDING_MANAGER,
                user__is_active=True,
            )
            .select_related("user")
            .order_by("user__full_name", "user__email", "id")
        )
        for row in members:
            names = ring.setdefault(row.building_id, [])
            label = _person_label(row.user)
            if label and label not in names:
                names.append(label)
    for entry in entries:
        ticket = tickets.get(entry.get("ticket_id"))
        if ticket is None:
            continue
        if ticket.id in named:
            entry["manager_names"] = list(named[ticket.id])
        elif ticket.assigned_to_id:
            entry["manager_names"] = [_person_label(ticket.assigned_to)]
        else:
            entry["manager_names"] = list(ring.get(ticket.building_id, []))


def _stamp_override_authority(entries, user) -> None:
    """P-4 (Part E) -- `can_override_customer_decision` on the waiting rows.

    The SAME question the ticket detail answers, asked with the same
    function (`override_authority.can_override_customer_decision`), so
    the drawer's amber button renders exactly where the detail page's
    Advanced fold would offer the override. Bounded by `WAITING_LIMIT`:
    one ticket fetch for the page, one machine read per row.
    """
    from .override_authority import can_override_customer_decision
    from .state_machine import allowed_next_statuses

    ticket_ids = {e["ticket_id"] for e in entries if e.get("ticket_id")}
    if not ticket_ids:
        return
    tickets = Ticket.objects.in_bulk(list(ticket_ids))
    for entry in entries:
        ticket = tickets.get(entry.get("ticket_id"))
        if ticket is None:
            continue
        entry["can_override_customer_decision"] = can_override_customer_decision(
            user, ticket, allowed_next_statuses(user, ticket)
        )


def _ticket_waiting_customer(ticket) -> bool:
    """Python twin of `_ticket_waiting_customer_q`."""
    return ticket.status == TicketStatus.WAITING_CUSTOMER_APPROVAL


def _ticket_live(ticket) -> bool:
    """Python twin of `_TICKET_LIVE_Q` (`detail_facts.ticket_is_live`)."""
    return ticket_is_live(ticket)


def _slot_pending(slot) -> bool:
    """Python twin of `_SLOT_PENDING_Q`."""
    return (
        slot.slot_status == StaffAssignmentSlotStatus.ASSIGNED
        and _ticket_live(slot.ticket)
    )


def _slot_state(slot) -> str:
    if slot.slot_status == StaffAssignmentSlotStatus.COMPLETED:
        return STATE_DONE
    if slot.slot_status in {
        StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE,
        StaffAssignmentSlotStatus.CANCELLED,
    }:
        return STATE_BLOCKED
    # W-PLANTRUTH §1b — an ASSIGNED slot on a ticket whose work is over
    # is over too: DONE when the ticket finished (review, approval,
    # closed), BLOCKED when it ended without the work (rejected,
    # converted). Twin of `_SLOT_STATE_Q`.
    if not _ticket_live(slot.ticket):
        if slot.ticket.status in _TICKET_BLOCKED_STATUSES:
            return STATE_BLOCKED
        return STATE_DONE
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
    state = _slot_state(slot)
    # P-9 §A.2b — the day THIS person finished: their own completion
    # stamp, else the ticket's finish (twin of `_with_slot_settled_day`).
    # P-10 A1 — the closed set (finished or blocked); `ticket_finished_at`
    # answers None while the ticket is live or reported done, so only
    # the slot's own stamp can place it then.
    settled_day = None
    if state in CLOSED_STATES:
        settled_day = _local_date(
            slot.completed_at or ticket_finished_at(slot.ticket)
        )
    return Job(
        planned_start=start,
        planned_end=end,
        due=deadline if deadline is not None else (end or start),
        state=state,
        pending=_slot_pending(slot),
        settled_day=settled_day,
    )


def _ticket_state(ticket) -> str:
    """The JOB's normalised state. The same reading `_slot_state` applies
    to the ticket half of a slot's verdict, so a job card and its
    people's cards cannot disagree about whether the work is over."""
    if not _ticket_live(ticket):
        if ticket.status in _TICKET_BLOCKED_STATUSES:
            return STATE_BLOCKED
        return STATE_DONE
    if ticket.status == TicketStatus.IN_PROGRESS:
        return STATE_IN_PROGRESS
    return STATE_OPEN


def _ticket_job(ticket) -> Job:
    """W-VIEWER — the `Job` a manager's card is placed by.

    Every date comes from `tickets/job_dates.py`: the ticket's own
    schedule, the extra work's provider commitment, the day it was asked
    for, in that order and no further. No slot date and no part date is
    consulted, which is the whole point.
    """
    start, end = job_window(ticket)
    deadline = job_deadline(ticket)
    # Rule 8 (P-1 §3) — waiting for a manager. The day it was handed
    # over is `manager_review_at` (stamped on entry to the status);
    # `updated_at` stands in for rows older than that stamp.
    review_since = None
    if ticket.status == TicketStatus.WAITING_MANAGER_REVIEW:
        review_since = _local_date(
            ticket.manager_review_at or ticket.updated_at
        )
    state = _ticket_state(ticket)
    # P-9 §A.2b — rule 10: a finished job is placed by the day it was
    # finished (twin of `_with_ticket_settled_day`). P-10 A1 — the closed
    # set, and never while reported done (`ticket_finished_at` is None).
    settled_day = (
        _local_date(ticket_finished_at(ticket)) if state in CLOSED_STATES else None
    )
    return Job(
        planned_start=start,
        planned_end=end,
        due=deadline if deadline is not None else (end or start),
        state=state,
        pending=_ticket_live(ticket),
        review_since=review_since,
        settled_day=settled_day,
    )


def _ticket_settled(ticket) -> bool:
    """W-VIEWER §5 — is there nothing this reader must do right now?

    A card the provider side is not currently holding renders CALM: the
    ruling's own example is work sent to the customer and waiting on
    their answer, where the manager may still withdraw it or react to a
    rejection but is not being asked for anything today. That is exactly
    the complement of `LATE_LIVE_TICKET_STATUSES` — the set the ladder
    already treats as "nothing left to be late with" — so this adds no
    second opinion about when a job is over, it only says so on the card.
    """
    return not _ticket_live(ticket)


def _slot_settled(slot, parts) -> bool:
    """W-VIEWER §5 — the same question for the person holding a slot.

    Their own slot is off their hands AND every part of theirs is done.
    A completed slot with an open part is NOT settled: the part is work
    they still hold, and a calm card would be telling them otherwise.
    """
    if not _ticket_live(slot.ticket):
        return True
    if slot.slot_status == StaffAssignmentSlotStatus.ASSIGNED:
        return False
    return all(part["is_done"] for part in (parts or []))


def _ew_finished_at(extra_work):
    """P-9 §A.2b — the moment the request was completed: its latest
    history leg into COMPLETED, read off the prefetched rows (twin of
    `_with_ew_settled_day`). None when no such leg exists."""
    latest = None
    for row in extra_work.status_history.all():
        if row.new_status != ExtraWorkStatus.COMPLETED:
            continue
        if latest is None or (row.created_at, row.id) > (latest.created_at, latest.id):
            latest = row
    return latest.created_at if latest is not None else None


def _extra_work_job(extra_work) -> Job:
    state = _extra_work_state(extra_work)
    settled_day = (
        _local_date(_ew_finished_at(extra_work)) if state == STATE_DONE else None
    )
    start, end = _ew_planned_window(extra_work)
    return Job(
        planned_start=start,
        planned_end=end,
        due=extra_work.deadline,
        state=state,
        settled_day=settled_day,
    )


def _ew_phase(extra_work, provenance) -> str:
    """P-11 A1 — the extra-work row's status word, server-decided.

    The board's extra-work rows carry the same `display_phase` the
    Extra work list reads (`extra_work/display_phase.py`), so the badge
    on a schedule card and the badge on the list row can never
    disagree. `viewer_is_customer` is False by construction: the board
    403s customer-side callers at the door. The spawned-ticket
    resolution mirrors `serializers._display_phase_for` (lowest id,
    deleted excluded); the sources prefetch `operational_tickets`, so a
    board is one query, not one per row.
    """
    tickets = [
        t for t in extra_work.operational_tickets.all() if t.deleted_at is None
    ]
    ticket_status = min(tickets, key=lambda t: t.id).status if tickets else None
    return ew_display_phase(
        status=extra_work.status,
        routing_decision=extra_work.routing_decision,
        request_intent=extra_work.request_intent,
        ticket_status=ticket_status,
        is_invoiced=bool(extra_work.is_invoiced),
        viewer_is_customer=False,
        has_real_plan=provenance.has_real_plan,
    )


def _iso(value: datetime.date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _person_label(user) -> str:
    return (user.full_name or user.email) if user is not None else ""


def _parts_map(slot_rows, today):
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
        # W-LATE §3b — `is_done` walks the part's slots; prefetched so a
        # week of parts is one query, not one per chip.
        .prefetch_related("sub_task__staff_assignments")
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
        bucket.append(_part_payload(row.sub_task, today))
    return out


def _part_payload(part, today) -> dict:
    """W-LATE §3b — the chip's whole surface: the name, the window, and
    the STATE the server decided (`lateness.part_state`)."""
    return {
        "id": part.id,
        "title": part.title,
        "planned_start": _iso(part.planned_start_date),
        "planned_end": _iso(part.planned_end_date),
        "time_window_label": part.time_window_label or "",
        "is_done": part.is_done(),
        "state": part.window_state(today),
    }


def _empty_lateness() -> dict:
    data = late_rules.NOT_LATE.as_dict()
    data["escalation_steps"] = []
    return data


def _unplanned_age(job, created, today) -> int | None:
    """WP-1 G2 — how long a dateless job has been waiting for a plan.

    A job with no planned date can never become overdue by design
    (inventing dates would be worse), so nothing ever nags about it.
    This is the nag: whole days since the record was created, only on a
    job with no planned window at all. The "Nog niet gepland" lane
    prints it past a threshold; every dated entry answers None.
    """
    if job.planned_start is not None or created is None:
        return None
    created_date = _local_date(created)
    if created_date is None:
        return None
    return max((today - created_date).days, 0)


#: FE-4 (Addendum D SS D.12) -- the same two words the detail uses
#: (`tickets/detail_facts.py`), so the card and the detail cannot caption
#: one date two ways.
DUE_KIND_DEADLINE = "DEADLINE"
DUE_KIND_PLANNED_DAY = "PLANNED_DAY"


def _fe4_facts(
    job,
    *,
    created,
    deadline,
    plan_source,
    settled_at,
    provenance: PlanProvenance = NO_PLAN,
    created_by=None,
    reported_done_at=None,
    reported_done_by=None,
    approved_at=None,
    sent_to=None,
    planned_hours=None,
    today=None,
    manager_checked=(None, None),
    approved_by=None,
    approved_on_behalf=False,
    wished_day=None,
) -> dict:
    """FE-4 (Addendum D SS D.12 items 2-4) -- the honest-date facts every
    entry carries, whatever its source:

      created_at              when the record was created (never a plan)
      plan_source             TICKET / PROVIDER_PLAN / CUSTOMER_WISH / None
                              -- "Gepland" only for the first two
      due_kind                DEADLINE / PLANNED_DAY / None -- what the
                              headline lateness counts against
      settled_at              when the work was finished, on a card that
                              is over; None while it is live
      settled_days_after_due  whole days the finish came after the due
                              date (quiet history), None otherwise

    P-1 adds the provenance (`tickets/plan_provenance.py`):

      has_real_plan           a PERSON (or the recurring plan) made the
                              window -- "Gepland" is allowed only then
      planned_by_name / planned_at   who, and when they did
      created_by_name         who opened the record; the plain fact
                              every card and detail states

    P-3 §A.5 adds:

      planned_after_deadline  a REAL plan whose last day falls after the
                              deadline. Nothing is blocked (the operator
                              may well know better); the card and the
                              detail simply say so, and the plan dialog
                              warns before the save.

    P-15 §0.4 adds:

      wished_day              the customer's WISH as a bare fact
                              ("Wished for {date}"), carried ONLY when
                              the wish is the record's sole date — a
                              provider plan or an own schedule silences
                              it. It places nothing; the Not-planned
                              strip prints it.

    P-9 §A.3 adds the facts the one card standard needs, on every kind:

      reported_done_by_name   who reported the work done (waiting rows)
      waiting_days            whole days since it was reported done
      approved_at             when the customer approved (finished rows)
      sent_to_name            who the finished work was sent to
      planned_hours           the plan's hours ("4.00"), or null
      settled_days_after_plan whole days the finish came after the last
                              planned day (0 = on the day), or null
    """
    due_kind = None
    if job.due is not None:
        due_kind = (
            DUE_KIND_DEADLINE if deadline is not None else DUE_KIND_PLANNED_DAY
        )
    settled_after = None
    settled_day = _local_date(settled_at) if settled_at is not None else None
    if settled_day is not None and job.due is not None:
        late_by = (settled_day - job.due).days
        settled_after = late_by if late_by > 0 else None
    waiting_days = None
    if reported_done_at is not None and today is not None:
        waiting_days = max((today - _local_date(reported_done_at)).days, 0)
    return {
        "created_at": created,
        # P-10 A4 — the creation DAY as the server states it (P-3 §A.3:
        # the card prints this, never a slice of the instant).
        "created_day": _iso(_local_date(created)),
        "created_by_name": _person_label(created_by) if created_by else None,
        "plan_source": plan_source,
        "wished_day": _iso(wished_day),
        "has_real_plan": provenance.has_real_plan,
        "planned_by_name": provenance.planned_by_name,
        "planned_at": provenance.planned_at,
        "due_kind": due_kind,
        "settled_at": settled_at,
        "reported_done_at": reported_done_at,
        "reported_done_by_name": reported_done_by,
        "waiting_days": waiting_days,
        "approved_at": approved_at,
        "sent_to_name": sent_to,
        # P-3 §A.3 — the DAYS as the server states them, in its own zone:
        # the card prints these, never a `.slice(0, 10)` of a UTC instant
        # (an evening finish in Amsterdam is the previous day in UTC).
        "settled_day": _iso(_local_date(settled_at)),
        "reported_done_day": _iso(_local_date(reported_done_at)),
        "approved_day": _iso(_local_date(approved_at)),
        # P-10 A4 — the finished card's Details: the manager's check and
        # the customer's approval, each a server DAY and a name.
        "manager_checked_day": _iso(_local_date(manager_checked[0])),
        "manager_checked_by_name": manager_checked[1],
        "approved_by_name": approved_by,
        # P-15 §0.3 — True when the approval leg was an on-behalf
        # override: the card words the check as the sign-off.
        "approved_on_behalf": approved_on_behalf,
        # P-3 §A.3 twin for the report: the clock of the report moment in
        # the server's zone, or null at midnight / when unknown.
        "reported_done_time": _clock(reported_done_at),
        "planned_hours": _hours_text(planned_hours),
        "settled_days_after_due": settled_after,
        "settled_days_after_plan": settled_days_after_plan(job),
        "planned_after_deadline": planned_after_deadline(
            job.window_end, deadline, provenance.has_real_plan
        ),
    }


def planned_after_deadline(window_end, deadline, has_real_plan) -> bool:
    """P-3 §A.5 — is the plan's last day past the deadline? Only a REAL
    plan can be (a phantom is no plan), and only against a real
    deadline (a planned day is never its own deadline)."""
    if not has_real_plan or window_end is None or deadline is None:
        return False
    return window_end > deadline


#: P-8R E — the statuses in which a job is waiting on somebody's check
#: of finished work. The "reported done" moment is the latest history
#: leg INTO one of them.
_REPORTED_DONE_STATUSES = (
    TicketStatus.WAITING_CUSTOMER_APPROVAL,
    TicketStatus.WAITING_MANAGER_REVIEW,
)


#: P-10 A4 — the finished card's Details name the whole chain, so the
#: report legs are read for a job that is OVER too (approved, closed),
#: not only while it waits.
_OVER_STATUSES = (TicketStatus.APPROVED, TicketStatus.CLOSED)


def _latest_leg(ticket, *, into=None, out_of=None):
    """The latest history row whose `new_status` is in `into` and/or
    whose `old_status` is in `out_of`, off the prefetched rows."""
    latest = None
    for row in ticket.status_history.all():
        if into is not None and row.new_status not in into:
            continue
        if out_of is not None and row.old_status not in out_of:
            continue
        if latest is None or (row.created_at, row.id) > (latest.created_at, latest.id):
            latest = row
    return latest


def _leg_facts(leg):
    if leg is None:
        return None, None
    who = _person_label(leg.changed_by) if leg.changed_by_id else None
    return leg.created_at, who


def _ticket_reported_done(ticket):
    """When the work was reported done — the moment it went to the
    customer (or the manager) for a check — and WHO reported it.
    Server-computed from the status history so the card and the waiting
    row cannot print the planned day for it (P-8R E). `(None, None)`
    unless the ticket is waiting on that check right now or is over
    (P-10 A4: the finished card's Details say who reported it and
    when). Read off the prefetched history rows (both sources prefetch
    them), so this costs no query per card."""
    if ticket.status not in _REPORTED_DONE_STATUSES + _OVER_STATUSES:
        return None, None
    return _leg_facts(_latest_leg(ticket, into=_REPORTED_DONE_STATUSES))


def _ticket_check_facts(ticket):
    """P-10 A4 — the manager's check (the leg OUT of
    WAITING_MANAGER_REVIEW into the customer wait or straight to
    approved) and the customer's approval (the leg INTO APPROVED), each
    as (moment, who). None where the leg never happened.

    P-15 §0.3 — the third element says whether that approval leg was an
    ON-BEHALF override (`is_override`), so the card words the check as
    the sign-off instead of presenting a provider's hand as the
    customer's."""
    checked = _latest_leg(
        ticket,
        out_of=(TicketStatus.WAITING_MANAGER_REVIEW,),
        into=(TicketStatus.WAITING_CUSTOMER_APPROVAL, TicketStatus.APPROVED),
    )
    approved = _latest_leg(ticket, into=(TicketStatus.APPROVED,))
    on_behalf = bool(approved is not None and approved.is_override)
    return _leg_facts(checked), _leg_facts(approved), on_behalf


def _ticket_settled_at(ticket):
    """The moment the ticket's work was over, for the past-tense card:
    P-9 §A.2b, the FINISH (`detail_facts.ticket_settled_at`), the same
    stamp the card is placed by. Null while live, null while reported
    done but unchecked."""
    return ticket_settled_at(ticket)


def _sent_to_name(ticket) -> str | None:
    """P-9 §A.3 — who the finished work was sent to: the customer's
    person who opened the melding, else the customer organisation.
    Only on a job waiting for the customer."""
    if ticket.status != TicketStatus.WAITING_CUSTOMER_APPROVAL:
        return None
    author = getattr(ticket, "created_by", None)
    if author is not None and author.role == UserRole.CUSTOMER_USER:
        return _person_label(author)
    return ticket.customer.name if ticket.customer_id else None


def _hours_text(value) -> str | None:
    return None if value is None else str(value)


def _planned_hours_map(ew_ids) -> dict:
    """P-9 §A.3 — the planned hours behind the cards on one page, in ONE
    query: `{(extra_work_id, user_id): hours}` per person and
    `{(extra_work_id, None): hours}` for the job — the request's
    `budget_hours` when set, else the sum of its per-person rows."""
    ids = {ew_id for ew_id in ew_ids if ew_id is not None}
    if not ids:
        return {}
    out = {}
    totals = {}
    rows = (
        ExtraWorkPlannedHours.objects.filter(extra_work_request_id__in=ids)
        .values("extra_work_request_id", "user_id")
        .annotate(total=Sum("hours"))
    )
    for row in rows:
        out[(row["extra_work_request_id"], row["user_id"])] = row["total"]
        totals[row["extra_work_request_id"]] = (
            totals.get(row["extra_work_request_id"], 0) + row["total"]
        )
    budgets = dict(
        ExtraWorkRequest.objects.filter(id__in=ids, budget_hours__isnull=False)
        .values_list("id", "budget_hours")
    )
    for ew_id in ids:
        total = budgets.get(ew_id) or totals.get(ew_id)
        if total is not None:
            out[(ew_id, None)] = total
    return out


def _entry_from_slot(
    slot,
    job,
    placement,
    day,
    today,
    *,
    viewer,
    parts=None,
    lateness=None,
    rolled_from=None,
    rolled=None,
    settled=None,
    planned_hours=None,
) -> dict:
    reported_done_at, reported_done_by = _ticket_reported_done(slot.ticket)
    manager_checked, approved_by, approved_on_behalf = _ticket_check_facts(
        slot.ticket
    )
    return {
        **_fe4_facts(
            job,
            created=slot.ticket.created_at,
            deadline=_slot_deadline(slot),
            manager_checked=manager_checked,
            approved_by=approved_by[1],
            approved_on_behalf=approved_on_behalf,
            # A slot IS a dated piece of a ticket: its own day is a plan,
            # given by whoever put this person on it.
            plan_source=(
                PLAN_SOURCE_TICKET if job.planned_start is not None else None
            ),
            # P-15 §0.4 — the worker's strip states the wish too
            # (`ticket__extra_work_request` is select_related above).
            wished_day=job_wish_day(slot.ticket),
            provenance=(
                PlanProvenance(
                    kind=PLAN_KIND_SCHEDULE,
                    planned_by_name=_person_label(slot.assigned_by),
                    planned_at=slot.assigned_at,
                )
                if job.planned_start is not None
                else NO_PLAN
            ),
            created_by=slot.ticket.created_by,
            reported_done_at=reported_done_at,
            reported_done_by=reported_done_by,
            approved_at=slot.ticket.approved_at,
            sent_to=_sent_to_name(slot.ticket),
            planned_hours=planned_hours,
            today=today,
            settled_at=(
                slot.completed_at or _ticket_settled_at(slot.ticket)
                if (
                    slot.slot_status != StaffAssignmentSlotStatus.ASSIGNED
                    or not _ticket_live(slot.ticket)
                )
                else None
            ),
        ),
        "kind": KIND_TICKET_SLOT,
        # Stable across the two kinds so React can key one merged list
        # without inventing an index.
        "key": f"slot-{slot.id}",
        # P-4 (Part E) -- stamped True on "Wacht op klant" rows for a reader who
        # may answer on the customer's behalf (`_stamp_override_authority`).
        "can_override_customer_decision": False,
        "source_id": slot.id,
        "ticket_id": slot.ticket_id,
        "ticket_no": slot.ticket.ticket_no,
        "extra_work_id": None,
        "title": slot.ticket.title,
        "status": slot.slot_status,
        "state": job.state,
        "ticket_status": slot.ticket.status,
        # P-11 A1 — extra-work rows carry the phase word instead.
        "display_phase": None,
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
        # WP-1 G2 — days this job has sat with no plan; null on a dated
        # entry. G1 — days this job has been stuck (set by the stuck
        # list, null everywhere else). Both on every kind: one shape.
        "unplanned_age_days": _unplanned_age(job, slot.assigned_at, today),
        "stuck_age_days": None,
        "scheduled_start_at": slot.scheduled_start_at,
        "scheduled_end_at": slot.scheduled_end_at,
        # P-3 §A.3 — the clock, decided by the server in its own zone;
        # null when the plan is a day and not a time.
        "start_time": _clock(slot.scheduled_start_at),
        "end_time": _clock(slot.scheduled_end_at),
        "time_window_label": slot.time_window_label,
        "assignment_note": slot.assignment_note,
        "completion_note": slot.completion_note,
        "unable_to_complete_reason": slot.unable_to_complete_reason,
        # P-14 — the ONE key the slot shape lacked (red in
        # `test_both_kinds_answer_the_same_key_set` since P-7 added it
        # to the other two builders only). Filled by
        # `_stamp_parked_reasons` on the parked list, keyed on
        # `ticket_id`, so a worker's parked row now says why too.
        "parked_reason": None,
        "day": _iso(day),
        "placement": placement,
        # W-PLANTRUTH §1b — set only on a ROLLED card: the day this card
        # was planned for (the date that placed it, which the badge
        # prints) and how many whole days past it today is.
        "rolled_from": _iso(rolled_from),
        "rolled_days": rolled,
        "is_overdue": is_overdue(job, today),
        "overdue_days": overdue_days(job, today),
        # W-VIEWER §5 — the reader's standing against the promise, signed:
        # 3 is three days left, 0 is today, -2 is two days past. Null when
        # nothing was promised.
        "days_until_due": days_to_due(job, today),
        # W-VIEWER §5 — nothing left for THIS reader to do, so the card
        # renders calm rather than urgent.
        "viewer_settled": (
            _slot_settled(slot, parts) if settled is None else settled
        ),
        "assignee_names": [_person_label(slot.user)],
        "assignee_count": 1,
        # P-10 A2 — the managers answerable for the job; filled on the
        # manager's-check strip (`_stamp_manager_names`), empty elsewhere.
        "manager_names": [],
        # W-N1 §3 — the parts this person holds on this ticket, so the
        # Work Plan can say WHICH half of the job is theirs. Empty list,
        # never null: a card that renders `parts.map` should not have to
        # ask whether the key exists.
        "parts": parts or [],
        # W-LATE §1b — the rung this JOB stands on, from the one helper,
        # and (§2) the steps that have spoken about it. Always present,
        # `level: null` when it is not late, so the client reads one
        # shape for every card.
        "lateness": lateness if lateness is not None else _empty_lateness(),
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
    extra_work,
    job,
    placement,
    day,
    today,
    *,
    assignees,
    lateness=None,
    rolled_from=None,
    rolled=None,
    planned_hours=None,
) -> dict:
    """The extra-work card's WHOLE surface.

    Operational fields only. There is deliberately no description, no
    pricing, no note of any kind and no proposal reference — see the
    module docstring. `test_sprint179a_work_plan` asserts this key set
    exactly, in both scopes, so a field cannot be added here by
    accident.
    """
    names = [_person_label(user) for user in assignees]
    # Hoisted so the phase and the facts read ONE provenance answer.
    provenance = extra_work_plan_provenance(extra_work)
    return {
        **_fe4_facts(
            job,
            created=extra_work.requested_at,
            deadline=extra_work.deadline,
            # P-14 A5 — placed by the PROVIDER's plan or not at all
            # (the wish no longer places; `_ew_planned_window`). P-15
            # §0.4 revives the CUSTOMER_WISH caption as a bare FACT:
            # `wished_day` carries the wish into the strip's "Wished
            # for {date}" line, and the source names it, while the
            # window stays provider-only.
            plan_source=(
                PLAN_SOURCE_PROVIDER_PLAN
                if extra_work.provider_planned_date is not None
                else PLAN_SOURCE_CUSTOMER_WISH
                if extra_work.preferred_date is not None
                else None
            ),
            wished_day=(
                extra_work.preferred_date
                if extra_work.provider_planned_date is None
                else None
            ),
            provenance=provenance,
            created_by=extra_work.created_by,
            planned_hours=planned_hours,
            today=today,
            # P-9 §A.2b — the completion leg of its own timeline, the
            # same moment the card is placed by. Never live once closed,
            # so no countdown.
            settled_at=_ew_finished_at(extra_work) if job.state == STATE_DONE else None,
        ),
        "kind": KIND_EXTRA_WORK,
        "key": f"ew-{extra_work.id}",
        # P-4 (Part E) -- stamped True on "Wacht op klant" rows for a reader who
        # may answer on the customer's behalf (`_stamp_override_authority`).
        "can_override_customer_decision": False,
        "source_id": extra_work.id,
        "ticket_id": None,
        "ticket_no": None,
        "extra_work_id": extra_work.id,
        "title": extra_work.title,
        "status": extra_work.status,
        "state": job.state,
        "ticket_status": None,
        # P-11 A1 — the badge word: the same phase the Extra work list
        # shows for this row. Ticket rows carry `ticket_status` instead.
        "display_phase": _ew_phase(extra_work, provenance),
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
        "unplanned_age_days": _unplanned_age(
            job, extra_work.requested_at, today
        ),
        "stuck_age_days": None,
        # Extra work has no dated slot — Sprint 157 §2 declined to build
        # one and nothing since has changed that. The card shows a
        # planned WINDOW in days, so the three time fields are null
        # rather than absent: one entry shape, whatever the source.
        "scheduled_start_at": None,
        "scheduled_end_at": None,
        "start_time": None,
        "end_time": None,
        "time_window_label": None,
        "assignment_note": None,
        "completion_note": None,
        "unable_to_complete_reason": None,
        # P-7 S8 — why it was parked (the ON_HOLD leg's history note);
        # filled by `_stamp_parked_reasons` on the parked list only.
        "parked_reason": None,
        "day": _iso(day),
        "placement": placement,
        "rolled_from": _iso(rolled_from),
        "rolled_days": rolled,
        "is_overdue": is_overdue(job, today),
        "overdue_days": overdue_days(job, today),
        "days_until_due": days_to_due(job, today),
        "viewer_settled": job.state in CLOSED_STATES,
        # W-N1 §3 — extra work has no parts; the key is present and
        # empty so both kinds answer `entry.parts` the same way and the
        # frontend needs no `kind` check to read it.
        "parts": [],
        "lateness": lateness if lateness is not None else _empty_lateness(),
        "assignee_names": names[:ASSIGNEE_NAMES_SHOWN],
        "assignee_count": len(names),
        "manager_names": [],
        "can_complete": False,
    }


def _entry_from_ticket(
    ticket,
    job,
    placement,
    day,
    today,
    *,
    names,
    parts=None,
    lateness=None,
    rolled_from=None,
    rolled=None,
    planned_hours=None,
) -> dict:
    """W-VIEWER — THE JOB CARD. One per ticket, whatever its headcount.

    Same key set as the other two kinds, so the browser reads one shape:
    what differs is where the values come from. `status` is the TICKET's
    status (the `kind` is `TICKET`, and the badge is picked off `kind`),
    and the three time fields are the TICKET's schedule — never a slot's.

    NO SLOT TIMES, deliberately. §3 of the ruling: the general board does
    not re-publish every staff member's working hours; the ticket's own
    Scheduling section does, to anybody who opens it. What the card says
    instead is how many people are on it.
    """
    reported_done_at, reported_done_by = _ticket_reported_done(ticket)
    manager_checked, approved_by, approved_on_behalf = _ticket_check_facts(
        ticket
    )
    return {
        **_fe4_facts(
            job,
            created=ticket.created_at,
            deadline=job_deadline(ticket),
            manager_checked=manager_checked,
            approved_by=approved_by[1],
            approved_on_behalf=approved_on_behalf,
            plan_source=job_plan_source(ticket),
            # P-15 §0.4 — the wish is a fact on the card, never a column.
            wished_day=job_wish_day(ticket),
            settled_at=_ticket_settled_at(ticket),
            reported_done_at=reported_done_at,
            reported_done_by=reported_done_by,
            approved_at=ticket.approved_at,
            sent_to=_sent_to_name(ticket),
            planned_hours=planned_hours,
            today=today,
            provenance=ticket_plan_provenance(ticket),
            created_by=ticket.created_by,
        ),
        "kind": KIND_TICKET,
        "key": f"ticket-{ticket.id}",
        # P-4 (Part E) -- stamped True on "Wacht op klant" rows for a reader who
        # may answer on the customer's behalf (`_stamp_override_authority`).
        "can_override_customer_decision": False,
        "source_id": ticket.id,
        "ticket_id": ticket.id,
        "ticket_no": ticket.ticket_no,
        "extra_work_id": ticket.extra_work_request_id,
        "title": ticket.title,
        "status": ticket.status,
        "state": job.state,
        "ticket_status": ticket.status,
        # P-11 A1 — extra-work rows carry the phase word instead.
        "display_phase": None,
        "ticket_type": ticket.type,
        "urgency": None,
        "customer_name": (
            ticket.customer.name if ticket.customer_id else None
        ),
        "building_id": ticket.building_id,
        "building_name": (
            ticket.building.name if ticket.building_id else None
        ),
        "planned_start": _iso(job.planned_start),
        "planned_end": _iso(job.planned_end),
        "due_date": _iso(job.due),
        "unplanned_age_days": _unplanned_age(job, ticket.created_at, today),
        # Rule 8 — how long the job has waited for a manager; the
        # number the REVIEW marker prints. None on any other placement.
        "stuck_age_days": (
            review_days(job, today) if placement == PLACEMENT_REVIEW else None
        ),
        "scheduled_start_at": ticket.scheduled_start_at,
        "scheduled_end_at": ticket.scheduled_end_at,
        "start_time": _clock(ticket.scheduled_start_at),
        "end_time": _clock(ticket.scheduled_end_at),
        "time_window_label": None,
        "assignment_note": None,
        "completion_note": None,
        "unable_to_complete_reason": None,
        # P-7 S8 — why it was parked (the ON_HOLD leg's history note);
        # filled by `_stamp_parked_reasons` on the parked list only.
        "parked_reason": None,
        "day": _iso(day),
        "placement": placement,
        "rolled_from": _iso(rolled_from),
        "rolled_days": rolled,
        "is_overdue": is_overdue(job, today),
        "overdue_days": overdue_days(job, today),
        "days_until_due": days_to_due(job, today),
        # Rule 8 — a job on today's column waiting for THIS reader's
        # confirmation is not settled for them, whatever its status set
        # says; the card must ask, not soothe.
        "viewer_settled": (
            False if placement == PLACEMENT_REVIEW else _ticket_settled(ticket)
        ),
        "parts": parts or [],
        "lateness": lateness if lateness is not None else _empty_lateness(),
        "assignee_names": names[:ASSIGNEE_NAMES_SHOWN],
        "assignee_count": len(names),
        "manager_names": [],
        # A job card is a READ. Completing a slot belongs to the person
        # holding it, on their own week.
        "can_complete": False,
    }


def _job_people_map(ticket_ids):
    """`{ticket_id: [display name, ...]}` — everybody on the job.

    One query for the whole board, not one per card. Cancelled slots are
    left out: somebody taken off the job is not on it.
    """
    if not ticket_ids:
        return {}
    out: dict[int, list[str]] = {}
    rows = (
        TicketStaffAssignment.objects.filter(ticket_id__in=list(ticket_ids))
        .exclude(slot_status=StaffAssignmentSlotStatus.CANCELLED)
        .select_related("user")
        .order_by("user__full_name", "user__email", "id")
    )
    for row in rows:
        names = out.setdefault(row.ticket_id, [])
        label = _person_label(row.user)
        if label and label not in names:
            names.append(label)
    return out


def _job_parts_map(ticket_ids, today):
    """`{ticket_id: [part payload, ...]}` — every part of the job.

    The manager's half of `_parts_map`, which is keyed by (ticket,
    person) because a worker sees only their own. A job card shows the
    whole checklist: it is a job-level fact, and it is the one place the
    ruling asks the general board to keep saying something about parts.
    """
    if not ticket_ids:
        return {}
    out: dict[int, list] = {}
    rows = (
        SubTask.objects.filter(ticket_id__in=list(ticket_ids))
        .prefetch_related("staff_assignments")
        .order_by("ordering", "id")
    )
    for part in rows:
        out.setdefault(part.ticket_id, []).append(_part_payload(part, today))
    return out


def _stuck_ages(entries, today) -> None:
    """WP-1 G1 — stamp each stuck row with how long it has been stuck.

    The moment a slot was marked unable is not a column on the slot, so
    the age is read from the best witness available, in order:

    1. The `NotificationLog` row the unable transition always writes
       (`TICKET_SLOT_UNABLE` — the log row is created BEFORE the mail is
       queued, so it exists even when the mail later fails).
    2. The slot's own last planned day — a job that failed has been
       stuck at least since the day it was supposed to happen.
    3. The day the slot was assigned.

    A stuck extra work is dated by the moment its operational ticket
    entered the blocked status: `rejected_at` where the stamp exists,
    else the status-history row that recorded the transition.
    """
    from notifications.models import NotificationEventType, NotificationLog

    ticket_ids = {
        e["ticket_id"]
        for e in entries
        if e["kind"] != KIND_EXTRA_WORK and e["ticket_id"] is not None
    }
    ew_ids = {
        e["extra_work_id"] for e in entries if e["kind"] == KIND_EXTRA_WORK
    }

    def _day(stamp) -> datetime.date | None:
        if stamp is None:
            return None
        return timezone.localtime(stamp).date()

    since: dict[int, datetime.date] = {}
    if ticket_ids:
        rows = (
            NotificationLog.objects.filter(
                ticket_id__in=list(ticket_ids),
                event_type=NotificationEventType.TICKET_SLOT_UNABLE,
            )
            .values("ticket_id")
            .annotate(latest=Max("created_at"))
        )
        for row in rows:
            since[row["ticket_id"]] = _day(row["latest"])
        missing = ticket_ids - set(since)
        if missing:
            slots = TicketStaffAssignment.objects.filter(
                ticket_id__in=list(missing),
                slot_status=StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE,
            ).values(
                "ticket_id",
                "scheduled_end_at",
                "scheduled_start_at",
                "assigned_at",
            )
            for slot in slots:
                day = (
                    _day(slot["scheduled_end_at"])
                    or _day(slot["scheduled_start_at"])
                    or _day(slot["assigned_at"])
                    or today
                )
                prev = since.get(slot["ticket_id"])
                if prev is None or day > prev:
                    since[slot["ticket_id"]] = day

    ew_since: dict[int, datetime.date] = {}
    if ew_ids:
        from .models import TicketStatusHistory

        blocked = Ticket.objects.filter(
            extra_work_request_id__in=list(ew_ids),
            deleted_at__isnull=True,
            status__in=list(_TICKET_BLOCKED_STATUSES),
        ).values("id", "extra_work_request_id", "rejected_at")
        history_needed: dict[int, int] = {}
        for row in blocked:
            day = _day(row["rejected_at"])
            if day is None:
                history_needed[row["id"]] = row["extra_work_request_id"]
                continue
            prev = ew_since.get(row["extra_work_request_id"])
            if prev is None or day > prev:
                ew_since[row["extra_work_request_id"]] = day
        if history_needed:
            history = (
                TicketStatusHistory.objects.filter(
                    ticket_id__in=list(history_needed),
                    new_status__in=list(_TICKET_BLOCKED_STATUSES),
                )
                .values("ticket_id")
                .annotate(latest=Max("created_at"))
            )
            for row in history:
                ew_id = history_needed[row["ticket_id"]]
                day = _day(row["latest"])
                prev = ew_since.get(ew_id)
                if day is not None and (prev is None or day > prev):
                    ew_since[ew_id] = day

    for entry in entries:
        if entry["kind"] == KIND_EXTRA_WORK:
            day = ew_since.get(entry["extra_work_id"], today)
        else:
            day = since.get(entry["ticket_id"], today)
        entry["stuck_age_days"] = max((today - day).days, 0)


#: Sorts a merged list where one source has a clock time and the other
#: has only a day. A far-future sentinel puts the day-only cards after
#: the timed ones inside the same column, which is where an operator
#: expects "sometime today" to sit relative to "09:00".
_NO_TIME = datetime.datetime.max.replace(tzinfo=datetime.timezone.utc)


def _week_sort_key(entry: dict) -> tuple:
    # W-PLANTRUTH §1b — inside a column the day's own work comes first,
    # then the rolled cards, oldest planned day first: the backlog reads
    # from the longest-overdue down.
    # FE-4 (Addendum D SS D.12 item 5) -- the reading order of a column:
    # the day's own open work, then the carried late work, then whatever
    # is settled (done, or waiting on somebody else) at the end.
    return (
        entry["day"] or "",
        1 if entry["viewer_settled"] else 0,
        1 if entry["placement"] in (PLACEMENT_ROLLED, PLACEMENT_REVIEW) else 0,
        entry["rolled_from"] or "",
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
        # W-VIEWER — THE ONE BRANCH THE RULING IS ABOUT. A manager
        # reading the company's week reads JOBS, placed on the ticket's
        # own scheduled date; everybody else — and this is the only shape
        # a STAFF caller can get — reads their OWN slots, on the days
        # they were given. Two sources, two predicate families, one
        # placement rule applied to both.
        if team:
            jobs = _ticket_source(user)
            board_q = _ticket_board_q(week_start, week_end, today, user)
            overdue_q = _ticket_overdue_q(today)
            upcoming_q = _ticket_upcoming_q(week_end)
            undated_q = _ticket_undated_q()
            parked_q = _ticket_parked_q()
        else:
            # `team=False` always, and it can be nothing else: the team
            # widening now belongs to `_ticket_source`. The parameter
            # stays on `_slot_source` because the tests reach the SLOT
            # shape through it in both scopes, which is the shape a
            # worker gets whatever their role.
            jobs = _slot_source(user, False)
            board_q = _slot_board_q(week_start, week_end, today)
            overdue_q = _slot_overdue_q(today)
            upcoming_q = _slot_upcoming_q(week_end)
            undated_q = _slot_undated_q()
            parked_q = _slot_parked_q()
        extra_work = _extra_work_source(user, team)

        entries, truncated = self._week_entries(
            jobs.filter(board_q), extra_work, week_start, week_end, today,
            team=team, viewer=user,
        )
        overdue_entries, overdue_truncated = self._flat_entries(
            jobs.filter(overdue_q),
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
            jobs.filter(upcoming_q),
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
            jobs.filter(undated_q),
            extra_work.filter(_ew_undated_q()),
            week_start,
            week_end,
            today,
            limit=UNDATED_LIMIT,
            team=team,
            viewer=user,
            fallback_placement=PLACEMENT_PLANNED,
        )

        # P-7 S8 — the parked list: undated work somebody decided to park,
        # with its reason. Out of the nag, behind the same drawer. A
        # meerwerk has no parked state (§D.18 item 6), so no extra-work
        # half. P-15 — on the team board the parked list reads its OWN
        # source, staffed or not (`_ticket_parked_source`): an unstaffed
        # ON_HOLD job must not vanish from the whole planning surface.
        parked_entries, parked_truncated = self._flat_entries(
            _ticket_parked_source(user) if team else jobs.filter(parked_q),
            extra_work.none(),
            week_start,
            week_end,
            today,
            limit=UNDATED_LIMIT,
            team=team,
            viewer=user,
            fallback_placement=PLACEMENT_PLANNED,
        )
        _stamp_parked_reasons(parked_entries)

        # W-LATE §1a — the late strip's rows, one per job, and its total.
        late_entries, late_truncated, late_total = self._late_entries(
            jobs, extra_work, today, team=team, viewer=user
        )
        # WP-1 G1 — the "Vastgelopen — actie nodig" follow-up list:
        # work that stopped without being done and without a human
        # deciding about it. Reads only; a row leaves when a human
        # reschedules, reassigns or cancels through the existing actions.
        stuck_entries, stuck_truncated, stuck_total = self._stuck_entries(
            jobs.filter(_ticket_stuck_q() if team else _slot_stuck_q()),
            _stuck_extra_work_source(user, team),
            week_start,
            week_end,
            today,
            team=team,
            viewer=user,
        )
        # P-3 §A.1 — the "Wacht op klant" rows: whole scope, like the
        # undated lane, because a job sent to the customer in July is
        # still waiting in August. Tickets only — no extra-work state
        # means "the customer is checking finished work" (a price
        # awaiting the customer's decision is a commercial wait, and
        # such a request has nobody assigned to it; by design).
        waiting_q = (
            _ticket_waiting_customer_q() if team else _slot_waiting_customer_q()
        )
        waiting_entries, waiting_truncated = self._flat_entries(
            jobs.filter(waiting_q),
            extra_work.none(),
            week_start,
            week_end,
            today,
            limit=WAITING_LIMIT,
            team=team,
            viewer=user,
            fallback_placement=PLACEMENT_PLANNED,
        )
        # P-4 (Part E) -- the drawer acts. Same rule, same answer as the ticket
        # detail's `actions.can_override_customer_decision`; nothing new is
        # permitted to anyone.
        _stamp_override_authority(waiting_entries, user)
        # P-10 A2 — the manager's-check strip: reported done, not yet
        # checked, and NOT this viewer's to check (those hang on their
        # today, `_ticket_board_q`). A worker's own strip is every slot
        # of theirs on a job waiting for the check. Whole scope, like
        # the customer zone: a job reported done in July still waits in
        # September.
        if team:
            review_source = jobs.filter(_ticket_review_q()).exclude(
                _ticket_review_q() & _ticket_responsible_q(user)
            )
        else:
            review_source = jobs.filter(_slot_review_q())
        review_entries, review_truncated = self._flat_entries(
            review_source,
            extra_work.none(),
            week_start,
            week_end,
            today,
            limit=WAITING_LIMIT,
            team=team,
            viewer=user,
            fallback_placement=PLACEMENT_PLANNED,
        )
        _stamp_manager_names(review_entries)
        counts = self._counts(
            jobs, extra_work, week_start, week_end, today, team=team, user=user
        )
        # Counted over the deduped JOB set in Python rather than as a SQL
        # aggregate, because the ladder needs the widest window across a
        # ticket's slots — see `_late_entries`. It is the whole set,
        # never the page.
        counts["late"] = late_total
        # WP-1 G1 — the whole stuck set, never the page.
        counts["stuck"] = stuck_total

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
                # FE-5 step 0 — whether THIS viewer may put undated work
                # on a day. The two write endpoints the lane's one action
                # uses (`POST /tickets/<id>/schedule/` and
                # `POST /extra-work/bulk-dates/`) both admit exactly the
                # provider-management roles and refuse everyone else with
                # a 403, so the lane reads the same answer here and shows
                # the button only when pressing it can work. Read-only,
                # additive; no migration.
                "can_plan": is_provider_management_role(user),
                "counts": counts,
                "entries": entries,
                "overdue_entries": overdue_entries,
                "upcoming_entries": upcoming_entries,
                # Sprint 181 §8 — the undated lane's rows.
                "undated_entries": undated_entries,
                # P-7 S8 — the parked sub-view's rows, with reasons.
                "parked_entries": parked_entries,
                # W-LATE §1a — the late strip's rows.
                "late_entries": late_entries,
                # WP-1 G1 — the follow-up list's rows.
                "stuck_entries": stuck_entries,
                # P-3 §A.1 — the "Wacht op klant" chip's rows.
                "waiting_customer_entries": waiting_entries,
                # P-10 A2 — the manager's-check strip's rows.
                "review_entries": review_entries,
                "limits": {
                    "entries": ENTRY_LIMIT,
                    "overdue_entries": OVERDUE_LIMIT,
                    "upcoming_entries": UPCOMING_LIMIT,
                    "undated_entries": UNDATED_LIMIT,
                    "parked_entries": UNDATED_LIMIT,
                    "late_entries": LATE_LIMIT,
                    "stuck_entries": STUCK_LIMIT,
                    "waiting_customer_entries": WAITING_LIMIT,
                    "review_entries": WAITING_LIMIT,
                },
                "truncated": {
                    "entries": truncated,
                    "overdue_entries": overdue_truncated,
                    "upcoming_entries": upcoming_truncated,
                    "undated_entries": undated_truncated,
                    "parked_entries": parked_truncated,
                    "late_entries": late_truncated,
                    "stuck_entries": stuck_truncated,
                    "waiting_customer_entries": waiting_truncated,
                    "review_entries": review_truncated,
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
        rows_source,
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

        W-VIEWER — `rows_source` is a TICKET queryset in team scope and a
        SLOT queryset otherwise. The placement rule below is the same
        either way; what changes is the `Job` it is asked about, which is
        the whole shape of the ruling: one rule, two facts, chosen by who
        is reading.

        `fallback_placement=None` is the week view: a row the rule does
        not place in this week is dropped. The flat lists (overdue,
        upcoming) are tables rather than columns and every row in them
        is there for a known reason, so they pass that reason in instead
        of asking the week rule a question it cannot answer about a week
        the row is not in.
        """
        if team:
            rows = list(rows_source.order_by(JOB_START, "id")[: limit + 1])
        else:
            rows = list(
                rows_source.order_by("scheduled_start_at", "id")[: limit + 1]
            )
        ew_rows = list(extra_work.order_by(EW_START, "id")[: limit + 1])
        assignees = cls._assignee_map(
            [row.id for row in ew_rows], team=team, viewer=viewer
        )
        ticket_ids = [
            row.id if team else row.ticket_id for row in rows
        ]
        # P-9 §A.3 — the plan's hours behind every card on this page,
        # one query for the job totals and the per-person rows.
        planned_hours = _planned_hours_map(
            [
                (row.extra_work_request_id if team else row.ticket.extra_work_request_id)
                for row in rows
            ]
            + [row.id for row in ew_rows]
        )
        if team:
            parts_by_ticket = _job_parts_map(ticket_ids, today)
            names_by_ticket = _job_people_map(ticket_ids)
            parts_by_pair = {}
        else:
            parts_by_pair = _parts_map(rows, today)
            parts_by_ticket = names_by_ticket = {}
        # W-LATE §1b — one index for every card in this list, so a card
        # on Tuesday's column and the same job's card in the strip say
        # the same thing.
        lateness = LatenessIndex(ticket_ids, ew_rows, today)

        today_in_week = week_start <= today <= week_end
        entries = []
        for row in rows:
            if team:
                entries.extend(
                    cls._job_entry(
                        row,
                        week_start,
                        week_end,
                        today,
                        today_in_week=today_in_week,
                        fallback_placement=fallback_placement,
                        lateness=lateness,
                        parts=parts_by_ticket.get(row.id, []),
                        names=names_by_ticket.get(row.id, []),
                        planned_hours=planned_hours.get(
                            (row.extra_work_request_id, None)
                        ),
                    )
                )
            else:
                entries.extend(
                    cls._slot_entry(
                        row,
                        week_start,
                        week_end,
                        today,
                        today_in_week=today_in_week,
                        fallback_placement=fallback_placement,
                        lateness=lateness,
                        viewer=viewer,
                        parts=parts_by_pair.get((row.ticket_id, row.user_id)),
                        # The person's own planned hours on the job, else
                        # the job's total.
                        planned_hours=(
                            planned_hours.get(
                                (row.ticket.extra_work_request_id, row.user_id)
                            )
                            or planned_hours.get(
                                (row.ticket.extra_work_request_id, None)
                            )
                        ),
                    )
                )
        for row in ew_rows:
            job = _extra_work_job(row)
            placement = placement_for(job, week_start, week_end, today)
            day = None
            rolled_from = rolled = None
            if fallback_placement is None and rolls_forward(job, today):
                if not today_in_week:
                    continue
                placement, day = PLACEMENT_ROLLED, today
                rolled_from, rolled = job.window_end, rolled_days(job, today)
            elif placement is None:
                if fallback_placement is None:
                    continue
                placement = fallback_placement
            if day is None:
                day = day_for(job, placement, week_start, week_end, today)
            entries.append(
                _entry_from_extra_work(
                    row,
                    job,
                    placement,
                    day,
                    today,
                    assignees=assignees.get(row.id, []),
                    lateness=lateness.lateness_dict(extra_work=row),
                    rolled_from=rolled_from,
                    rolled=rolled,
                    planned_hours=planned_hours.get((row.id, None)),
                )
            )

        entries.sort(key=sort_key)
        truncated = len(entries) > limit
        return entries[:limit], truncated

    @staticmethod
    def _job_entry(
        ticket,
        week_start,
        week_end,
        today,
        *,
        today_in_week,
        fallback_placement,
        lateness,
        parts,
        names,
        planned_hours=None,
    ):
        """W-VIEWER — one JOB card, or none. Returns a list so the caller
        treats both sources the same way."""
        job = _ticket_job(ticket)
        placement = placement_for(job, week_start, week_end, today)
        day = None
        rolled_from = rolled = None
        # Rule 9 (P-3 §A.1, P-9 §A.2a: EVERY week) — waiting on the
        # customer: in NO column. The Python twin of `_ticket_board_q`'s
        # exclusion; the chip's own list is built with a fallback
        # placement and is not affected.
        if fallback_placement is None and _ticket_waiting_customer(ticket):
            return []
        # Rule 8 (P-1 §3), personal since P-10 A2 — waiting for a
        # manager: on today's column of the current week for the
        # responsible viewer (the SQL board narrows to exactly those
        # rows, `_ticket_responsible_q`), marked. In any other week, and
        # for every other reader, such a job is in NO column: its report
        # is not a finish (A1), so it never hangs in the past.
        if fallback_placement is None and ticket.status == TicketStatus.WAITING_MANAGER_REVIEW:
            if not today_in_week or job.review_since is None:
                return []
            placement, day = PLACEMENT_REVIEW, today
        # Rule 5, unchanged in what it decides: a pending job whose last
        # planned day has passed is not left in that past column, it is
        # on today until it is done. The date on the record never moved,
        # and `rolled_from` is that date.
        elif fallback_placement is None and rolls_forward(job, today):
            if not today_in_week:
                return []
            placement, day = PLACEMENT_ROLLED, today
            rolled_from, rolled = job.window_end, rolled_days(job, today)
        elif placement is None:
            if fallback_placement is None:
                return []
            placement = fallback_placement
        if day is None:
            day = day_for(job, placement, week_start, week_end, today)
        return [
            _entry_from_ticket(
                ticket,
                job,
                placement,
                day,
                today,
                names=names,
                parts=parts,
                lateness=lateness.lateness_dict(ticket_id=ticket.id),
                rolled_from=rolled_from,
                rolled=rolled,
                planned_hours=planned_hours,
            )
        ]

    @staticmethod
    def _slot_entry(
        slot,
        week_start,
        week_end,
        today,
        *,
        today_in_week,
        fallback_placement,
        lateness,
        viewer,
        parts,
        planned_hours=None,
    ):
        """One SLOT card — the caller's own dated piece of a job.

        W-VIEWER §5 — the ladder is asked about THIS PERSON'S window
        (their slot, widened by their own parts), not the job's. A
        colleague working next Friday does not make this person late, and
        a person who has finished their own half is not shouted at for a
        job that is still running.
        """
        job = _slot_job(slot)
        placement = placement_for(job, week_start, week_end, today)
        day = None
        rolled_from = rolled = None
        # Rule 9 (P-3 §A.1, P-9 §A.2a: EVERY week) — the slot's job waits
        # on the customer: it is in no column (twin of `_slot_board_q`).
        if fallback_placement is None and _ticket_waiting_customer(slot.ticket):
            return []
        # P-10 A2 — the worker's slot on a job waiting for the manager's
        # check: a strip row, never a column (twin of `_slot_board_q`).
        if (
            fallback_placement is None
            and slot.ticket.status == TicketStatus.WAITING_MANAGER_REVIEW
        ):
            return []
        if fallback_placement is None and rolls_forward(job, today):
            if not today_in_week:
                return []
            placement, day = PLACEMENT_ROLLED, today
            rolled_from, rolled = job.window_end, rolled_days(job, today)
        elif placement is None:
            # W-LATE §3b — a part windowed into this week places its
            # ticket here, on the part's day. The Python twin of the
            # `_part_window_q` branch in the SQL.
            # P-9 §A.2b — a finished slot is placed by its finish day
            # alone; a part's window no longer pulls it into a week.
            part_day = (
                _part_day_in_week(parts, week_start, week_end)
                if fallback_placement is None and job.settled_day is None
                else None
            )
            if part_day is not None:
                placement = PLACEMENT_PLANNED
                day = part_day
            elif fallback_placement is None:
                return []
            else:
                placement = fallback_placement
        if day is None:
            day = day_for(job, placement, week_start, week_end, today)
        settled = _slot_settled(slot, parts)
        mine_start, mine_end = _viewer_window(job, parts)
        return [
            _entry_from_slot(
                slot,
                job,
                placement,
                day,
                today,
                viewer=viewer,
                parts=parts,
                lateness=lateness.window_dict(
                    slot.ticket_id, mine_start, mine_end, done=settled
                ),
                rolled_from=rolled_from,
                rolled=rolled,
                settled=settled,
                planned_hours=planned_hours,
            )
        ]

    @classmethod
    def _week_entries(
        cls, jobs, extra_work, week_start, week_end, today, *, team, viewer
    ):
        # `jobs` arrives already narrowed to the board — the caller picks
        # the predicate family, because which one is right depends on who
        # is reading (W-VIEWER).
        return cls._build(
            jobs,
            extra_work.filter(_ew_board_q(week_start, week_end, today)),
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
        jobs,
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
            jobs,
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
    def _stuck_entries(
        cls, jobs, extra_work, week_start, week_end, today, *, team, viewer
    ):
        """WP-1 G1 — the follow-up list. Returns `(entries, truncated,
        total)` like the late strip, on the same builders as every other
        list, plus a `stuck_age_days` per row (oldest first).

        `fallback_placement=PLACEMENT_PLANNED` because these rows are a
        table, not a column: placement answers "why is this card in the
        week on screen", which is not a question a follow-up row is
        asked. The frontend renders no marker off it here.
        """
        entries, truncated = cls._flat_entries(
            jobs,
            extra_work,
            week_start,
            week_end,
            today,
            limit=STUCK_LIMIT,
            team=team,
            viewer=viewer,
            fallback_placement=PLACEMENT_PLANNED,
        )
        total = jobs.count() + extra_work.count()
        _stuck_ages(entries, today)
        entries.sort(key=lambda e: (-(e["stuck_age_days"] or 0), e["key"]))
        return entries, truncated, total

    @classmethod
    def _late_entries(cls, jobs, extra_work, today, *, team, viewer):
        """W-LATE §1a — the late strip: ONE ROW PER LATE JOB, ordered by
        the ladder. Returns `(entries, truncated, total)`.

        Fed from "planned-date-passed-and-not-done" (L1) and its two
        worse rungs, which is NOT the overdue list's question: that list
        asks "past its due date", where the due date is the extra work's
        deadline when one exists. A job planned for Monday with a
        deadline on Friday is not overdue on Tuesday, but its plan IS
        broken, and the strip is where that shows. Both lists stay:
        they answer different questions and are labelled as such.

        W-VIEWER — the strip is viewer-aware like the board. A manager
        reads the JOB's rung, measured on the ticket's own date; a person
        reading their own week reads THEIR rung, measured on the days
        they were given. Neither is shouted at over somebody else's
        calendar, which is the defect the ruling names.
        """
        if team:
            return cls._late_jobs(jobs, extra_work, today, viewer=viewer)
        return cls._late_own(jobs, extra_work, today, viewer=viewer)

    @classmethod
    def _late_jobs(cls, tickets, extra_work, today, *, viewer):
        """The manager's strip: one row per late TICKET.

        The SQL narrows to a SUPERSET (a job whose window or deadline has
        passed); the ladder itself is asked of every candidate in Python,
        because a rung also depends on hours booked, which is one
        aggregate too many for a predicate that has to compose into a
        count.
        """
        # The SUPERSET the ladder is then asked about, one row per
        # ticket. The job's own window and its deadline are the first two
        # branches; the slot and part branches are here because
        # `LatenessIndex` falls back to the widest slot / part window for
        # a job that states no date of its own, and a candidate filter
        # narrower than the rule it feeds would silence exactly those
        # jobs (W-LATE §3b's part-window case, measured as the one test
        # this ruling's first pass broke). `.distinct()` because those
        # two branches are multi-valued joins.
        candidates = list(
            # P-11 A10 — ACTIVE: an on-hold job is not on the late
            # strip; the fold is its only place on this page.
            tickets.filter(_TICKET_ACTIVE_Q)
            .filter(
                Q(**{f"{JOB_WINDOW_END}__lt": today})
                | Q(extra_work_request__deadline__lt=today)
                | (
                    Q(**{f"{JOB_START}__isnull": True})
                    & (
                        Q(staff_assignments__scheduled_start_at__date__lt=today)
                        | Q(staff_assignments__scheduled_end_at__date__lt=today)
                        | Q(sub_tasks__planned_start_date__lt=today)
                        | Q(sub_tasks__planned_end_date__lt=today)
                    )
                )
            )
            .distinct()
        )
        ew_rows = list(
            extra_work.filter(_EW_LIVE_Q)
            .filter(
                # P-11 A11 — the provider's plan can be late too; the
                # ladder (`LatenessIndex`) reads it first, so the
                # candidate set must not hide a provider-planned row
                # behind a future wish. Over-selection is harmless: the
                # `is_late` re-check below drops what the ladder clears.
                Q(preferred_date__lt=today)
                | Q(planned_end_date__lt=today)
                | Q(provider_planned_date__lt=today)
                | Q(provider_planned_end_date__lt=today)
                | Q(deadline__lt=today)
            )
            .order_by("id")
        )
        index = LatenessIndex([t.id for t in candidates], ew_rows, today)
        late_tickets = [
            t for t in candidates if index.for_ticket(t.id).is_late
        ]
        late_ew = [row for row in ew_rows if index.for_extra_work(row).is_late]

        ticket_ids = [t.id for t in late_tickets]
        parts_by_ticket = _job_parts_map(ticket_ids, today)
        names_by_ticket = _job_people_map(ticket_ids)
        assignees = cls._assignee_map(
            [row.id for row in late_ew], team=True, viewer=viewer
        )

        keyed = []
        for ticket in late_tickets:
            lateness = index.for_ticket(ticket.id)
            entry = _entry_from_ticket(
                ticket,
                _ticket_job(ticket),
                PLACEMENT_OVERDUE,
                today,
                today,
                names=names_by_ticket.get(ticket.id, []),
                parts=parts_by_ticket.get(ticket.id, []),
                lateness=index.lateness_dict(ticket_id=ticket.id),
            )
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
                lateness=index.lateness_dict(extra_work=row),
            )
            keyed.append((late_rules.sort_key(lateness, entry["title"]), entry))

        keyed.sort(key=lambda pair: (pair[0], pair[1]["key"]))
        entries = [entry for _, entry in keyed]
        total = len(entries)
        return entries[:LATE_LIMIT], total > LATE_LIMIT, total

    @classmethod
    def _late_own(cls, slots, extra_work, today, *, viewer):
        """The worker's strip: one row per job THEY are late on.

        A person can hold several slots on one ticket (a base slot and
        one per part), so the rows are collapsed onto the ticket and the
        window is the widest of THEIRS — never a colleague's. A job whose
        own plan is broken by somebody else's day is not this reader's
        problem and does not appear here.
        """
        live = slots.filter(_SLOT_LIVE_Q)
        candidate_ids = list(
            Ticket.objects.filter(
                id__in=live.values("ticket_id"),
                status__in=LATE_LIVE_TICKET_STATUSES,
                archived_at__isnull=True,
                deleted_at__isnull=True,
            )
            # P-11 A10 — an on-hold job is off this strip too.
            .exclude(status=TicketStatus.ON_HOLD)
            .values_list("id", flat=True)
            .distinct()
        )
        ew_rows = list(
            extra_work.filter(_EW_LIVE_Q)
            .filter(
                # P-11 A11 — the provider's plan can be late too; the
                # ladder (`LatenessIndex`) reads it first, so the
                # candidate set must not hide a provider-planned row
                # behind a future wish. Over-selection is harmless: the
                # `is_late` re-check below drops what the ladder clears.
                Q(preferred_date__lt=today)
                | Q(planned_end_date__lt=today)
                | Q(provider_planned_date__lt=today)
                | Q(provider_planned_end_date__lt=today)
                | Q(deadline__lt=today)
            )
            .order_by("id")
        )
        index = LatenessIndex(candidate_ids, ew_rows, today)
        late_ew = [row for row in ew_rows if index.for_extra_work(row).is_late]

        slot_rows = list(
            live.filter(ticket_id__in=candidate_ids).order_by(
                "ticket_id", "scheduled_start_at", "id"
            )
        )
        parts_by_pair = _parts_map(slot_rows, today)
        assignees = cls._assignee_map(
            [row.id for row in late_ew], team=False, viewer=viewer
        )

        by_ticket: dict[int, list] = {}
        for slot in slot_rows:
            by_ticket.setdefault(slot.ticket_id, []).append(slot)

        keyed = []
        for ticket_id, bucket in by_ticket.items():
            first = bucket[0]
            names: list[str] = []
            parts: list[dict] = []
            starts: list[datetime.date] = []
            ends: list[datetime.date] = []
            settled = True
            for slot in bucket:
                label = _person_label(slot.user)
                if label and label not in names:
                    names.append(label)
                slot_parts = parts_by_pair.get(
                    (slot.ticket_id, slot.user_id), []
                )
                for part in slot_parts:
                    if all(p["id"] != part["id"] for p in parts):
                        parts.append(part)
                if not _slot_settled(slot, slot_parts):
                    settled = False
                start, end = _viewer_window(_slot_job(slot), slot_parts)
                if start is not None:
                    starts.append(start)
                if end is not None:
                    ends.append(end)
            lateness = index.for_window(
                ticket_id,
                min(starts) if starts else None,
                max(ends) if ends else None,
                done=settled,
            )
            if not lateness.is_late:
                continue
            entry = _entry_from_slot(
                first,
                _slot_job(first),
                PLACEMENT_OVERDUE,
                today,
                today,
                viewer=viewer,
                lateness=index.window_dict(
                    ticket_id,
                    min(starts) if starts else None,
                    max(ends) if ends else None,
                    done=settled,
                ),
                settled=settled,
            )
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
                lateness=index.lateness_dict(extra_work=row),
            )
            keyed.append((late_rules.sort_key(lateness, entry["title"]), entry))

        keyed.sort(key=lambda pair: (pair[0], pair[1]["key"]))
        entries = [entry for _, entry in keyed]
        total = len(entries)
        return entries[:LATE_LIMIT], total > LATE_LIMIT, total

    @staticmethod
    def _counts(
        jobs, extra_work, week_start, week_end, today, *, team, user=None
    ) -> dict:
        """Every number on the screen, over the WHOLE scope.

        This is the point of the endpoint. The chips used to be counted
        in the browser over whatever the page had fetched, so a chip
        could report a number that described one page and looked
        authoritative doing it. These are `COUNT(*)` over the scoped
        queryset and stay right when `entries` is truncated.

        W-VIEWER — and they count what the reader is looking at. A
        manager's chips count JOBS; a worker's count their own slots.
        Counting slots under a board that shows one card per job is how a
        chip reading "12" sits over eight cards.
        """
        if team:
            board_q = _ticket_board_q(week_start, week_end, today, user)
            state_q = _TICKET_STATE_Q
            overdue_q = _ticket_overdue_q(today)
            upcoming_q = _ticket_upcoming_q(week_end)
            undated_q = _ticket_undated_q()
            parked_q = _ticket_parked_q()
            waiting_q = _ticket_waiting_customer_q()
        else:
            board_q = _slot_board_q(week_start, week_end, today)
            state_q = _SLOT_STATE_Q
            overdue_q = _slot_overdue_q(today)
            upcoming_q = _slot_upcoming_q(week_end)
            undated_q = _slot_undated_q()
            parked_q = _slot_parked_q()
            waiting_q = _slot_waiting_customer_q()

        # W-PLANTRUTH §1b — the chips describe THE BOARD: what the seven
        # columns hold, rolled rows included, past-and-pending excluded.
        job_week = jobs.filter(board_q)
        ew_week = extra_work.filter(_ew_board_q(week_start, week_end, today))

        # Conditional aggregation: FOUR queries for nine numbers rather
        # than eighteen `COUNT(*)` round trips. Neither source is joined
        # to a multi-row relation here — the team widening goes through
        # an `IN (subquery)` or an `Exists`, not a join — so a filtered
        # `Count("id")` cannot double-count.
        job_week_counts = job_week.aggregate(
            total=Count("id"),
            overdue=Count("id", filter=overdue_q),
            open=Count("id", filter=state_q[STATE_OPEN]),
            in_progress=Count("id", filter=state_q[STATE_IN_PROGRESS]),
            done=Count("id", filter=state_q[STATE_DONE]),
            blocked=Count("id", filter=state_q[STATE_BLOCKED]),
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
        job_other = jobs.aggregate(
            overdue_all=Count("id", filter=overdue_q),
            upcoming=Count("id", filter=upcoming_q),
            undated=Count("id", filter=undated_q),
            # P-7 S8 — the parked sub-view's number, whole scope.
            parked=Count("id", filter=parked_q),
            # P-3 §A.1 — the "Wacht op klant" chip's number, whole scope.
            waiting_customer=Count("id", filter=waiting_q),
        )
        ew_other = extra_work.aggregate(
            overdue_all=Count("id", filter=_ew_overdue_q(today)),
            upcoming=Count("id", filter=_ew_upcoming_q(week_end)),
            undated=Count("id", filter=_ew_undated_q()),
        )

        counts = {
            key: job_week_counts[key] + ew_week_counts[key]
            for key in job_week_counts
        }
        # No extra-work state is "the customer checks finished work", so
        # `waiting_customer` has no extra-work half to add.
        counts.update(
            {
                key: job_other[key] + ew_other.get(key, 0) for key in job_other
            }
        )
        if team and user is not None:
            # P-15 — the parked chip counts what the parked list shows:
            # its own staffed-or-not source, not the gated board set.
            counts["parked"] = _ticket_parked_source(user).count()
        # P-10 A2 — the manager's-check numbers, whole scope: `review` is
        # the strip (not this viewer's to check), `review_mine` the cards
        # on their today. Two plain counts rather than a conditional
        # aggregate: the responsible predicate is three `Exists`, and it
        # has to read the same here as on the board.
        if team:
            review_total = jobs.filter(_ticket_review_q()).count()
            review_mine = (
                jobs.filter(_ticket_review_q() & _ticket_responsible_q(user)).count()
                if user is not None
                else 0
            )
        else:
            review_total = jobs.filter(_slot_review_q()).count()
            review_mine = 0
        counts["review"] = review_total - review_mine
        counts["review_mine"] = review_mine
        return counts


__all__ = [
    "CLOSED_STATES",
    "ENTRY_LIMIT",
    "KIND_EXTRA_WORK",
    "KIND_TICKET",
    "KIND_TICKET_SLOT",
    "LATE_LIMIT",
    "LATE_LIVE_TICKET_STATUSES",
    "OVERDUE_LIMIT",
    "STUCK_LIMIT",
    "UNDATED_LIMIT",
    "UPCOMING_LIMIT",
    "WAITING_LIMIT",
    "WorkPlanView",
]
