from rest_framework import viewsets

from accounts.permissions import IsAuthenticatedAndActive
from accounts.scoping import scope_companies_for

from .filters import CompanyFilter
from .serializers import CompanySerializer


class CompanyViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CompanySerializer
    permission_classes = [IsAuthenticatedAndActive]
    filterset_class = CompanyFilter
    search_fields = ["name", "slug"]
    ordering_fields = ["name", "created_at"]

    def get_queryset(self):
        return scope_companies_for(self.request.user)
