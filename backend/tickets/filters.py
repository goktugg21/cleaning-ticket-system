from django_filters import rest_framework as df

from .models import Ticket


class TicketFilter(df.FilterSet):
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
