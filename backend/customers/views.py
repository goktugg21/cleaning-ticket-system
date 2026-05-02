from rest_framework import viewsets

from accounts.permissions import IsAuthenticatedAndActive
from accounts.scoping import scope_customers_for

from .filters import CustomerFilter
from .serializers import CustomerSerializer


class CustomerViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticatedAndActive]
    filterset_class = CustomerFilter
    search_fields = ["name", "contact_email", "phone"]
    ordering_fields = ["name", "created_at"]

    def get_queryset(self):
        return scope_customers_for(self.request.user).select_related("company", "building")
