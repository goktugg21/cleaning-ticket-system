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

    class Meta:
        model = Ticket
        fields = {
            "status": ["exact", "in"],
            "priority": ["exact", "in"],
            "type": ["exact", "in"],
            "company": ["exact"],
            "building": ["exact"],
            "customer": ["exact"],
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
