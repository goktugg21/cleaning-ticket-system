from django.db.models import Count
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
    # Sprint 154 §I.5 — the buildings list table sorts by header click,
    # mirroring what Sprint 153 gave the customers list. `OrderingFilter`
    # is already in DEFAULT_FILTER_BACKENDS, so extending this tuple is
    # the whole change; every entry is a concrete column on Building.
    ordering_fields = [
        "name",
        "created_at",
        "city",
        "postal_code",
        "is_active",
    ]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticatedAndActive()]
        if self.action == "reactivate":
            return [IsSuperAdmin()]
        return [IsSuperAdminOrCompanyAdminForCompany()]

    def get_queryset(self):
        # Sprint 154 §I.5 — the four list counts are ANNOTATED, and the
        # customer names for the list column are PREFETCHED. Computing
        # either per row would cost 5 extra queries x page_size (125 on a
        # 25-row page); the `assertNumQueries` guard in
        # `buildings/tests/test_sprint154_buildings_area.py` pins that a
        # 10-row page costs exactly what a 2-row page costs.
        #
        # `distinct=True` is mandatory: four joined Counts in one query
        # multiply each other's row sets otherwise.
        return (
            scope_buildings_for(self.request.user)
            .select_related("company", "building_type")
            .prefetch_related("customer_memberships__customer")
            .annotate(
                _customer_count=Count("customer_memberships", distinct=True),
                _manager_count=Count("manager_assignments", distinct=True),
                _staff_count=Count("staff_visibility", distinct=True),
                _contact_count=Count("contact_links", distinct=True),
            )
        )

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
