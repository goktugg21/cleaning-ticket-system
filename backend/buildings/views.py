from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from accounts.models import UserRole
from accounts.permissions import (
    IsAuthenticatedAndActive,
    IsSuperAdmin,
    IsSuperAdminOrCompanyAdminForCompany,
)
from accounts.scoping import scope_buildings_for
from companies.models import Company, CompanyUserMembership

from .filters import BuildingFilter
from .models import Building
from .serializers import BuildingSerializer


class BuildingViewSet(viewsets.ModelViewSet):
    serializer_class = BuildingSerializer
    filterset_class = BuildingFilter
    search_fields = ["name", "address", "city", "postal_code"]
    ordering_fields = ["name", "created_at"]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticatedAndActive()]
        if self.action == "reactivate":
            return [IsSuperAdmin()]
        return [IsSuperAdminOrCompanyAdminForCompany()]

    def get_queryset(self):
        return scope_buildings_for(self.request.user).select_related("company")

    def perform_create(self, serializer):
        company: Company = serializer.validated_data["company"]
        actor = self.request.user
        if actor.role == UserRole.COMPANY_ADMIN and not CompanyUserMembership.objects.filter(
            user=actor, company_id=company.id
        ).exists():
            raise PermissionDenied("You can only create buildings within your own company.")
        serializer.save()

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=["is_active"])

    @action(detail=True, methods=["post"], permission_classes=[IsSuperAdmin])
    def reactivate(self, request, pk=None):
        building = Building.objects.filter(pk=pk).first()
        if building is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        building.is_active = True
        building.save(update_fields=["is_active"])
        return Response(BuildingSerializer(building).data, status=status.HTTP_200_OK)
