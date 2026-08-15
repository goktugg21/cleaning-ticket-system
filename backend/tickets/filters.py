from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from django_filters import rest_framework as df

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

    class Meta:
        model = Ticket
        fields = {
            "status": ["exact", "in"],
            "priority": ["exact", "in"],
            "type": ["exact", "in"],
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
