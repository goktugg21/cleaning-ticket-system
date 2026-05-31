from django.db.models import Q
from django_filters import rest_framework as df

from .models import Ticket


class TicketFilter(df.FilterSet):
    # Sprint 30 Batch 30.1 / Sprint 6A — filter the ticket list by
    # parent EW id. Anchors on the canonical `extra_work_request` FK
    # and keeps both legacy chains in the union for historical rows:
    #   * canonical: extra_work_request_id
    #   * cart route: extra_work_request_item__extra_work_request_id
    #   * proposal route: proposal_line__proposal__extra_work_request_id
    extra_work_request = df.NumberFilter(method="filter_extra_work_request")

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
