from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from django_filters import rest_framework as df

from accounts.models import UserRole

from .models import Ticket, TicketStatus


# Sprint 9B — agenda "overdue" view-state excludes terminal tickets.
# This is an AGENDA VIEW STATE (a scheduled start in the past on a
# still-active ticket), NOT an SLA breach and NOT a TicketStatus.
_AGENDA_TERMINAL_STATUSES = [
    TicketStatus.APPROVED,
    TicketStatus.REJECTED,
    TicketStatus.CLOSED,
    TicketStatus.CONVERTED_TO_EXTRA_WORK,
]


# Sprint 180 §2 — "completed extra works should not clutter the ticket
# list". FINISHED is read off the TICKET's own status, never off the
# parent Extra Work's.
#
# Keying on `ExtraWorkStatus.COMPLETED` was the obvious reading and it
# is the wrong one: a provider operator can drive an Extra Work
# IN_PROGRESS -> COMPLETED by hand while one of its spawned tickets is
# still OPEN, and that ticket would vanish from the list that is
# supposed to be showing it. The ticket's own status is the authority
# on whether the ticket's work is finished, and it cannot be set from
# the Extra Work side.
#
# REJECTED is deliberately absent: rejected work loops back through
# IN_PROGRESS for rework, so it is live work despite being listed in
# `models.TERMINAL_TICKET_STATUSES`. CONVERTED_TO_EXTRA_WORK is absent
# too — such a ticket is the SOURCE of an Extra Work, not a row spawned
# by one, and its pointer to the successor is the reason to keep it
# visible.
_FINISHED_TICKET_STATUSES = [
    TicketStatus.APPROVED,
    TicketStatus.CLOSED,
]


def _extra_work_origin_q() -> Q:
    """
    Rows that were SPAWNED BY an Extra Work request, across all three
    parentage paths, exactly as `TicketFilter.filter_extra_work_request`
    and `serializers.resolve_extra_work_origin_core` resolve them:
    the canonical FK first, then the two legacy chains historical rows
    may still be anchored on.

    All three are forward FKs on Ticket, so `isnull` compiles to the
    local column and no join fan-out (and therefore no `.distinct()`)
    is involved.
    """
    return (
        Q(extra_work_request__isnull=False)
        | Q(extra_work_request_item__isnull=False)
        | Q(proposal_line__isnull=False)
    )


def apply_archived(queryset, value):
    """The archive gate, in ONE place.

    `None` (the param was not sent) and `False` both mean the working
    list; only an explicit `True` opens the archive. The list filter and
    the stats chips both call this, for the reason
    `apply_is_extra_work` records: a chip counting a different set from
    the list under it is worse than no chip at all.
    """
    if value is True:
        return queryset.filter(archived_at__isnull=False)
    return queryset.filter(archived_at__isnull=True)


def apply_is_extra_work(queryset, value):
    """Narrow to chargeable work (`True`) or to ordinary tickets
    (`False`); `None` leaves the queryset alone.

    Sprint 183 §2 — shared by `TicketFilter.filter_is_extra_work` (the
    rows) and `TicketViewSet.stats` (the chips above them), for exactly
    the reason `exclude_finished_extra_work` below is shared: a chip
    counting a different set from the list it sits on is worse than no
    chip at all.

    The two branches are exact COMPLEMENTS by construction — one `Q`,
    filtered and excluded — which is what makes "the chips sum to the
    All tile" a property rather than a coincidence. All three parentage
    paths are forward FKs on Ticket (`extra_work_request`,
    `extra_work_request_item`, `proposal_line`), so `isnull` compiles to
    a local column, there is no join fan-out, and neither side needs
    `.distinct()`. Adding one to only the `True` branch — which is what
    this code used to do — is how the complement breaks quietly.
    """
    if value is None:
        return queryset
    origin = _extra_work_origin_q()
    return queryset.filter(origin) if value else queryset.exclude(origin)


def parse_is_extra_work(raw):
    """`?is_extra_work=` as a tri-state.

    `None` when absent OR unrecognised: an unparseable value must mean
    "no opinion", never "ordinary tickets only", or one typo in a URL
    would silently hide every chargeable row and the page would look
    like it had lost data.
    """
    if raw in {"true", "True", "1"}:
        return True
    if raw in {"false", "False", "0"}:
        return False
    return None


# P-9 D2 -- WHERE A ROW CAME FROM, as ONE server-side axis.
#
# The Tickets queue lists every operational ticket whatever its origin
# and prints the origin on the row (`TicketListSerializer.kind` plus
# `occurrence_origin`). A filter on that column has to partition the
# rows EXACTLY the way the column labels them, or the reader picks
# "Melding" and gets rows the column calls "Extra work". `?type=REPORT`
# cannot be that filter: on crmtest every one of the 91 extra-work
# tickets is typed REPORT too (the spawn copies the request's type), so
# a type-based "Melding" narrowing returned the whole meerwerk pile.
#
# The four values restate `detail_facts.ticket_kind` (the column's
# rule) in ORM terms, in the same precedence:
#
#   meerwerk   has an extra-work parent (any of the three spawn paths)
#   melding    no parent, and the author is a customer-side user
#   recurring  no parent, provider author, a planned occurrence behind it
#   ticket     no parent, provider author, no occurrence
#
# Exact partition by construction -- every row lands in exactly one --
# so the four chips sum to the total, the property Sprint 183's
# `apply_is_extra_work` established for its two branches. `exclude()`
# rather than `~Q` for the author test, so a NULL join (a ticket whose
# author row is gone) counts as provider work here exactly as
# `ticket_kind` counts an absent author.
ORIGIN_MELDING = "melding"
ORIGIN_MEERWERK = "meerwerk"
ORIGIN_RECURRING = "recurring"
ORIGIN_TICKET = "ticket"
ORIGIN_VALUES = frozenset(
    {ORIGIN_MELDING, ORIGIN_MEERWERK, ORIGIN_RECURRING, ORIGIN_TICKET}
)


def parse_origin(raw):
    """`?origin=` as an optional enum. `None` when absent OR unrecognised,
    for the reason `parse_is_extra_work` gives: a typo in a URL must
    mean "no opinion", never an empty page that looks like lost data."""
    if raw is None:
        return None
    value = str(raw).strip().lower()
    return value if value in ORIGIN_VALUES else None


def apply_origin(queryset, value):
    """Narrow to one origin; `None` leaves the queryset alone. Shared by
    `TicketFilter.filter_origin` (the rows) and `TicketViewSet.stats`
    (the tab counts above them), so the two cannot disagree."""
    if value is None:
        return queryset
    parent = _extra_work_origin_q()
    if value == ORIGIN_MEERWERK:
        return queryset.filter(parent)
    customer_author = Q(created_by__role=UserRole.CUSTOMER_USER)
    if value == ORIGIN_MELDING:
        return queryset.exclude(parent).filter(customer_author)
    provider_work = queryset.exclude(parent).exclude(customer_author)
    if value == ORIGIN_RECURRING:
        return provider_work.filter(planned_occurrence__isnull=False)
    return provider_work.filter(planned_occurrence__isnull=True)


def exclude_finished_extra_work(queryset):
    """
    Drop EW-spawned tickets whose OWN work is finished.

    Shared by `TicketFilter.hide_finished_extra_work` (the list) and
    `TicketViewSet.stats` (the count chips above it) so the chips and
    the rows can never disagree about what is on screen.
    """
    return queryset.exclude(
        Q(status__in=_FINISHED_TICKET_STATUSES) & _extra_work_origin_q()
    )


class TicketFilter(df.FilterSet):
    # Sprint 30 Batch 30.1 / Sprint 6A — filter the ticket list by
    # parent EW id. Anchors on the canonical `extra_work_request` FK
    # and keeps both legacy chains in the union for historical rows:
    #   * canonical: extra_work_request_id
    #   * cart route: extra_work_request_item__extra_work_request_id
    #   * proposal route: proposal_line__proposal__extra_work_request_id
    extra_work_request = df.NumberFilter(method="filter_extra_work_request")

    # Sprint 9B — agenda / scheduling filters (all OPT-IN; the default
    # ticket list with no scheduling params is unchanged). They run on
    # top of `scope_tickets_for` (already applied in get_queryset), so
    # every role only ever filters within its own scope.
    scheduled_from = df.IsoDateTimeFilter(
        field_name="scheduled_start_at", lookup_expr="gte"
    )
    scheduled_to = df.IsoDateTimeFilter(
        field_name="scheduled_start_at", lookup_expr="lte"
    )
    scheduled_on = df.DateFilter(
        field_name="scheduled_start_at", lookup_expr="date"
    )
    agenda = df.ChoiceFilter(
        method="filter_agenda",
        choices=[
            ("today", "today"),
            ("upcoming", "upcoming"),
            ("overdue", "overdue"),
            ("unscheduled", "unscheduled"),
        ],
    )

    # Sprint 13C — staff "My Jobs" filter. OPT-IN; runs on top of the
    # already-`scope_tickets_for`-narrowed queryset, so it composes
    # naturally with the scheduled_*/agenda filters.
    my_jobs = df.BooleanFilter(method="filter_my_jobs")

    # Sprint 111 — building-manager "My tickets" filter. OPT-IN; runs on
    # top of the already-`scope_tickets_for`-narrowed queryset, so (like
    # `my_jobs`) it can only ever narrow within the caller's own scope —
    # no cross-tenant surface. Narrows to tickets the caller MANAGES: the
    # UNION of the legacy single primary-manager FK (`Ticket.assigned_to`)
    # and the responsible-manager M:N (`TicketManagerAssignment`, reverse
    # relation `manager_assignments`).
    my_managed = df.BooleanFilter(method="filter_my_managed")

    # M6.1 — customer-detail sub-tabs. The tickets tab is the inverse of
    # the meldingen tab: drop every ticket whose type is in the given CSV
    # (the tickets tab passes exclude_type=REPORT so it stays disjoint
    # from the meldingen tab's type=REPORT). Opt-in; runs on top of
    # scope_tickets_for like the other filters here.
    exclude_type = df.CharFilter(method="filter_exclude_type")

    # Sprint 169 §8 — `customer` as a NUMBER, not a model choice.
    #
    # The generated ModelChoiceFilter validated the id against EVERY
    # customer, so an id that does not exist produced a 400 while an id
    # that exists but is out of the actor's scope produced a 200 with no
    # rows. That difference is an existence oracle: it answers "is there
    # a customer 812?" to anyone who can reach the list.
    #
    # It matters more from this sprint on, because the customer-scoped
    # Tickets page now supplies the id from the URL — it is a
    # client-controlled value on a page where it used to be implicit.
    #
    # As a plain number both cases behave identically: filter, no match,
    # empty list, 200. The filter still only NARROWS what
    # `scope_tickets_for` already allowed.
    customer = df.NumberFilter(field_name="customer_id")

    # Sprint 180 §2 — hide finished Extra Work rows from the ticket
    # list. OPT-IN at the API layer (absent param == today's behaviour,
    # every existing caller unaffected); the Tickets page turns it ON by
    # default and shows a clearable chip, because "default to hiding
    # finished work" is what was asked and "never hide things with no
    # way back" is the house rule.
    hide_finished_extra_work = df.BooleanFilter(
        method="filter_hide_finished_extra_work"
    )

    # Sprint 180 §1 — age the customer-approval queue. Narrows to
    # tickets that have been sitting in WAITING_CUSTOMER_APPROVAL for at
    # least N days, i.e. finished work the customer has not answered on
    # and which therefore cannot become invoiceable. OPT-IN.
    awaiting_customer_approval_days = df.NumberFilter(
        method="filter_awaiting_customer_approval_days"
    )

    # Sprint 181 §5 — every chargeable-work ticket, as a group.
    #
    # `?extra_work_request=<id>` has always answered "which tickets came
    # from THAT extra work"; nothing answered "which came from an extra
    # work at all", so the sub-page that lists them had no query to
    # make. Reuses `_extra_work_origin_q()` — the same three parentage
    # paths `filter_extra_work_request` and
    # `resolve_extra_work_origin_core` walk — rather than restating
    # them, so the sub-page cannot disagree with the pill on the row.
    #
    # `?is_extra_work=false` is the inverse (ordinary tickets only), and
    # an absent param leaves the queryset alone, so no existing caller
    # changes behaviour.
    is_extra_work = df.BooleanFilter(method="filter_is_extra_work")

    # P-9 D2 -- `?origin=melding|meerwerk|recurring|ticket`, the queue's
    # Origin column as a filter. See `apply_origin` for the partition.
    # A CharFilter rather than a ChoiceFilter so an unrecognised value
    # is "no opinion" (200, unfiltered) instead of a 400 -- the same
    # tolerance `is_extra_work` extends to a mistyped URL.
    origin = df.CharFilter(method="filter_origin")

    # W-H §2 — THE ARCHIVE IS NOT LOADED UNLESS YOU ASK FOR IT.
    #
    # "You don't load the archive all the time." Absent means live work,
    # which is the opposite default from every other filter on this
    # class and is deliberate: an archive that still turns up in the
    # working list is a flag, not an archive.
    #
    #   absent  -> archived rows are EXCLUDED (the working list)
    #   true    -> archived rows ONLY (the archive)
    #   false   -> archived rows are EXCLUDED (an explicit way to say
    #              the default out loud, so a saved link can pin it)
    #
    # NOT a declared `BooleanFilter`, and NOT handled in this class at
    # all. Two reasons, and the second one cost a test:
    #
    #  1. django-filter only runs a filter whose parameter is PRESENT,
    #     so a declared one can express "true means X" and "false means
    #     Y" but never "absent means Y". Declaring it read correctly and
    #     did nothing.
    #  2. A FilterSet-level override then hides archived rows from
    #     `get_object` too, because DRF resolves a detail route through
    #     `filter_queryset`. That made an archived ticket 404 on its own
    #     page -- so it could never be unarchived, which is the one
    #     thing an archive must never do.
    #
    # It lives on the VIEWSET (`TicketViewSet.filter_queryset`, list
    # action only) for exactly that reason.
    #
    # No existing caller changes behaviour on the day this ships,
    # because no ticket is archived yet.

    # W-H §3 — THE PERIOD, on the ticket's own date.
    #
    # `created_at` and not `scheduled_start_at`: the second is null on
    # every unscheduled ticket, so a period filter over it would
    # silently drop exactly the rows an operator is looking for, and
    # "the tickets from five years ago" is an age, which is what
    # `created_at` measures. `scheduled_from` / `scheduled_to` above
    # already answer the scheduling question and are untouched.
    #
    # Inclusive at both ends. `date_to` is a DATE and the column is a
    # DATETIME, so `lte` on the raw value would drop everything after
    # 00:00 on the last day; `__date` compares calendar days, which is
    # what the person picking "31 March" means.
    date_from = df.DateFilter(field_name="created_at", lookup_expr="date__gte")
    date_to = df.DateFilter(field_name="created_at", lookup_expr="date__lte")

    class Meta:
        model = Ticket
        fields = {
            "status": ["exact", "in"],
            "priority": ["exact", "in"],
            "type": ["exact", "in"],
            # Sprint 185 E §1 — WHICH KIND OF WORK, and this is the whole
            # point of the catalog: a taxonomy whose values do not reach
            # the filters is a dropdown, not a taxonomy. `isnull` is
            # offered beside `exact` so "not yet categorised" is a state
            # an operator can list and work through, rather than a gap
            # they can only find by reading every row.
            "category": ["exact", "in", "isnull"],
            "company": ["exact"],
            "building": ["exact"],
            "assigned_to": ["exact", "isnull"],
            "created_by": ["exact"],
        }

    def filter_extra_work_request(self, queryset, name, value):
        if value in (None, ""):
            return queryset
        return queryset.filter(
            Q(extra_work_request_id=value)
            | Q(extra_work_request_item__extra_work_request_id=value)
            | Q(proposal_line__proposal__extra_work_request_id=value)
        ).distinct()

    def filter_is_extra_work(self, queryset, name, value):
        # Sprint 181 §5, moved to the shared helper in Sprint 183 §2 so
        # the stats endpoint counts the same rows this lists. The old
        # body called `.distinct()` on the True branch only, citing a
        # to-many join that `_extra_work_origin_q`'s own docstring says
        # does not exist — all three paths are forward FKs. Dropping it
        # makes the two branches exact complements, which is what the
        # chip-sum test rests on.
        return apply_is_extra_work(queryset, value)

    def filter_origin(self, queryset, name, value):
        # P-9 D2 -- the shared helper, so `stats` counts what this lists.
        return apply_origin(queryset, parse_origin(value))

    def filter_hide_finished_extra_work(self, queryset, name, value):
        # Sprint 180 §2. A falsy value leaves the queryset untouched, so
        # "show all" is genuinely all — the escape hatch is a real one.
        if not value:
            return queryset
        return exclude_finished_extra_work(queryset)

    def filter_awaiting_customer_approval_days(self, queryset, name, value):
        # Sprint 180 §1. `value` is a number of days; 0 means "every
        # ticket currently awaiting approval".
        #
        # Rows with a NULL `sent_for_approval_at` are excluded rather
        # than treated as infinitely old: the column is stamped by
        # `TIMESTAMP_ON_ENTER[WAITING_CUSTOMER_APPROVAL]`, so a NULL is
        # a row that never went through the transition (a hand-set
        # fixture, or a legacy row) and has no age to measure. Ageing
        # them from `created_at` instead would put rows in the "customer
        # is sitting on this" queue that the customer was never asked
        # about.
        if value in (None, ""):
            return queryset
        cutoff = timezone.now() - timedelta(days=float(value))
        return queryset.filter(
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            sent_for_approval_at__isnull=False,
            sent_for_approval_at__lte=cutoff,
        )

    def filter_agenda(self, queryset, name, value):
        # Sprint 9B — agenda view-state filter. Opt-in only.
        if value in (None, ""):
            return queryset
        if value == "today":
            return queryset.filter(
                scheduled_start_at__date=timezone.localdate()
            )
        if value == "upcoming":
            return queryset.filter(
                scheduled_start_at__isnull=False,
                scheduled_start_at__gt=timezone.now(),
            )
        if value == "overdue":
            # Past scheduled start on a still-active ticket. NOT SLA,
            # NOT a TicketStatus — purely an agenda view state.
            return queryset.filter(
                scheduled_start_at__isnull=False,
                scheduled_start_at__lt=timezone.now(),
            ).exclude(status__in=_AGENDA_TERMINAL_STATUSES)
        if value == "unscheduled":
            return queryset.filter(scheduled_start_at__isnull=True)
        return queryset

    def filter_exclude_type(self, queryset, name, value):
        # M6.1 — drop the listed ticket types (CSV). A falsy value leaves
        # the queryset untouched.
        if value in (None, ""):
            return queryset
        values = [v.strip() for v in value.split(",") if v.strip()]
        if not values:
            return queryset
        return queryset.exclude(type__in=values)

    def filter_my_jobs(self, queryset, name, value):
        # Sprint 13C — narrow to tickets where the current user holds a
        # TicketStaffAssignment. This uses the M:N TicketStaffAssignment
        # (reverse relation `staff_assignments`), NOT the legacy
        # `assigned_to` FK. For a BUILDING_READ staff it narrows the
        # building-wide agenda down to only-assigned-to-me; for an
        # ASSIGNED_ONLY staff it is consistent with their already-narrow
        # scope. Opt-in only — a falsy value leaves the queryset untouched.
        if not value:
            return queryset
        if getattr(self, "request", None) is None:
            return queryset
        return queryset.filter(
            staff_assignments__user=self.request.user
        ).distinct()

    def filter_my_managed(self, queryset, name, value):
        # Sprint 111 — narrow to tickets the current user MANAGES: the
        # UNION of the legacy single primary-manager FK (`assigned_to`)
        # and the responsible-manager M:N (`TicketManagerAssignment`,
        # reverse relation `manager_assignments`). Mirrors
        # `filter_my_jobs`: OPT-IN only (a falsy value leaves the queryset
        # untouched), request-scoped (guard when there is no request), and
        # `.distinct()` to collapse the M:N-join fan-out. It does NOT alter
        # `assigned_to`/`my_jobs`; it composes with `scope_tickets_for`
        # (already applied in the view), so it can only narrow within the
        # caller's own scope.
        if not value:
            return queryset
        if getattr(self, "request", None) is None:
            return queryset
        return queryset.filter(
            Q(assigned_to=self.request.user)
            | Q(manager_assignments__user=self.request.user)
        ).distinct()
