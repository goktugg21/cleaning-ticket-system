from rest_framework import viewsets

from accounts.permissions import IsAuthenticatedAndActive
from accounts.scoping import scope_buildings_for

from .filters import BuildingFilter
from .serializers import BuildingSerializer


class BuildingViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = BuildingSerializer
    permission_classes = [IsAuthenticatedAndActive]
    filterset_class = BuildingFilter
    search_fields = ["name", "address", "city", "postal_code"]
    ordering_fields = ["name", "created_at"]

    def get_queryset(self):
        return scope_buildings_for(self.request.user).select_related("company")
