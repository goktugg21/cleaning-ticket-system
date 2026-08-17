"""
Sprint 185 E §2 — the cost-share endpoints.

    GET /api/buildings/<building_id>/cost-shares/
    PUT /api/buildings/<building_id>/cost-shares/     {"shares": [...]}

`IsSuperAdminOrCompanyAdminForCompany`, the same gate every other
building sub-resource uses. These percentages decide what each tenant is
billed, so the write is a provider-admin act — a building manager may
read the division (they are asked about it) and may not change it.

PUT and not PATCH: this replaces the whole division, which is the only
shape in which the sum-to-100 rule can hold. See
`serializers_cost_shares` for why a per-row endpoint could not.
"""
from __future__ import annotations

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRole
from accounts.permissions import (
    IsProviderRosterReader,
    IsSuperAdminOrCompanyAdminForCompany,
)
from audit import context as audit_context

from .models import Building, BuildingCostShare
from .serializers_cost_shares import (
    BuildingCostShareSerializer,
    BuildingCostSharesWriteSerializer,
)


class BuildingCostSharesView(APIView):
    """Read or replace one building's cost division."""

    def get_permissions(self):
        if self.request.method == "GET":
            # PROVIDER-SIDE ONLY, and this is a tenancy decision rather
            # than a convenience.
            #
            # The first version of this gate was `IsAuthenticatedAndActive`
            # plus the building's own scope, on the reasoning that a
            # building manager is the person asked "who pays for this".
            # A test written for the customer side caught what that
            # missed: a CUSTOMER_USER can reach their own building, so
            # they could read the whole division — including what the
            # OTHER tenants of their building pay. That is exactly the
            # cross-customer leak H-1/H-2 exist to prevent, and the
            # commercial terms of one tenant are none of another's
            # business.
            #
            # `IsProviderRosterReader` is the existing three-role
            # provider gate (SUPER_ADMIN / COMPANY_ADMIN /
            # BUILDING_MANAGER, customer roles and STAFF refused), and it
            # is exactly the set that should read this.
            return [IsProviderRosterReader()]
        return [IsSuperAdminOrCompanyAdminForCompany()]

    def _get_building(self, request, building_id):
        from accounts.scoping import scope_buildings_for

        building = get_object_or_404(
            scope_buildings_for(request.user), pk=building_id
        )
        if request.method != "GET":
            self.check_object_permissions(request, building)
        return building

    def get(self, request, building_id):
        building = self._get_building(request, building_id)
        rows = (
            BuildingCostShare.objects.filter(building=building)
            .select_related("customer")
            .order_by("-share_pct", "customer_id")
        )
        return Response(
            {"results": BuildingCostShareSerializer(rows, many=True).data}
        )

    def put(self, request, building_id):
        building = self._get_building(request, building_id)
        serializer = BuildingCostSharesWriteSerializer(
            data=request.data, building=building
        )
        serializer.is_valid(raise_exception=True)
        rows = serializer.validated_data["shares"]

        try:
            audit_context.set_current_reason("building_cost_shares_replace")
        except Exception:  # pragma: no cover - defensive
            pass

        with transaction.atomic():
            # Replace, in one transaction: a building is never left with
            # half a division, which would be a state the sum rule says
            # cannot exist.
            BuildingCostShare.objects.filter(building=building).delete()
            BuildingCostShare.objects.bulk_create(
                [
                    BuildingCostShare(
                        building=building,
                        customer=row["customer"],
                        share_pct=row["share_pct"],
                    )
                    for row in rows
                ]
            )

        saved = (
            BuildingCostShare.objects.filter(building=building)
            .select_related("customer")
            .order_by("-share_pct", "customer_id")
        )
        return Response(
            {"results": BuildingCostShareSerializer(saved, many=True).data},
            status=status.HTTP_200_OK,
        )
