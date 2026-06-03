from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.response import Response

from accounts.models import User, UserRole
from accounts.permissions import (
    IsProviderRosterReader,
    IsSuperAdminOrCompanyAdminForCompany,
)
from accounts.scoping import scope_buildings_for
from config.pagination import UnboundedPagination

from .models import Building, BuildingManagerAssignment
from .serializers_memberships import (
    BuildingManagerAssignmentSerializer,
    BuildingManagerAssignmentUpdateSerializer,
)


class BuildingManagerListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]
    serializer_class = BuildingManagerAssignmentSerializer
    pagination_class = UnboundedPagination

    def _get_building(self):
        building = get_object_or_404(Building, pk=self.kwargs["building_id"])
        self.check_object_permissions(self.request, building)
        return building

    def get_queryset(self):
        building = self._get_building()
        return (
            BuildingManagerAssignment.objects.filter(building=building)
            .select_related("user")
            .order_by("-assigned_at")
        )

    def create(self, request, *args, **kwargs):
        building = self._get_building()
        user_id = request.data.get("user_id")
        if not user_id:
            return Response(
                {"user_id": "This field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = get_object_or_404(
            User, pk=user_id, is_active=True, deleted_at__isnull=True
        )
        if user.role != UserRole.BUILDING_MANAGER:
            return Response(
                {"user_id": "User must have role BUILDING_MANAGER."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        membership, created = BuildingManagerAssignment.objects.get_or_create(
            building=building, user=user
        )
        return Response(
            BuildingManagerAssignmentSerializer(membership).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class BuildingManagerDeleteView(generics.GenericAPIView):
    """
    DELETE /api/buildings/<building_id>/managers/<user_id>/
    PATCH  /api/buildings/<building_id>/managers/<user_id>/

    Sprint 14 — DELETE removes the BM↔building assignment.
    B6 — PATCH accepts `{"permission_overrides": { ... }}` so SA /
    Provider Company Admin can revoke specific BM defaults
    (`osius.building_manager.override_customer_decision`,
    `osius.building_manager.prepare_extra_work_proposal`) per-(BM,
    building) without removing the assignment itself. The
    `BuildingManagerAssignmentUpdateSerializer` validates the
    allow-list + boolean shape; only the two B6 keys are accepted.

    Audit coverage: the new `permission_overrides` field is tracked
    by the dedicated UPDATE-diff handler in `audit/signals.py`, so
    each PATCH writes one AuditLog row with the before/after diff.
    """

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]

    def delete(self, request, building_id, user_id):
        building = get_object_or_404(Building, pk=building_id)
        self.check_object_permissions(request, building)
        deleted, _ = BuildingManagerAssignment.objects.filter(
            building=building, user_id=user_id
        ).delete()
        if deleted == 0:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def patch(self, request, building_id, user_id):
        building = get_object_or_404(Building, pk=building_id)
        self.check_object_permissions(request, building)
        assignment = BuildingManagerAssignment.objects.filter(
            building=building, user_id=user_id
        ).first()
        if assignment is None:
            return Response(
                {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND
            )
        serializer = BuildingManagerAssignmentUpdateSerializer(
            assignment, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        assignment.refresh_from_db()
        return Response(
            BuildingManagerAssignmentSerializer(assignment).data,
            status=status.HTTP_200_OK,
        )


class EligibleCrewUserSerializer(serializers.ModelSerializer):
    """Compact crew row: id + display name + email. Used only by the
    eligible-crew endpoint below; no customer-side fields are exposed."""

    class Meta:
        model = User
        fields = ["id", "full_name", "email"]
        read_only_fields = fields


class BuildingEligibleCrewView(generics.GenericAPIView):
    """
    GET /api/buildings/<building_id>/eligible-crew/

    Read-only. Returns the STAFF + BUILDING_MANAGER users eligible to be
    a recurring job's default crew for this building, BEFORE any ticket
    exists. The frontend planned-work form needs this to populate its
    default_staff_ids / default_manager_ids pickers; the per-ticket
    `assignable-staff` / `assignable-managers` endpoints require an
    existing ticket and so cannot serve the template-authoring screen.

    Eligibility mirrors the recurring-job write validation in
    `planned_work.serializers.RecurringJobWriteSerializer.validate`
    exactly, so every user offered here passes the write:
      * staff    = role=STAFF users with a BuildingStaffVisibility row
                   for this building (else staff_not_eligible on write).
      * managers = role=BUILDING_MANAGER users with a
                   BuildingManagerAssignment for this building (else
                   manager_not_eligible on write).

    Permissions: provider-management only. `IsProviderRosterReader`
    403s STAFF and CUSTOMER_USER (same admit set as the staff roster).
    The building is resolved through `scope_buildings_for`, so a provider
    actor out of scope for the building (a BUILDING_MANAGER not assigned
    to it, or a COMPANY_ADMIN of another company) gets a 404 — the
    anti-enumeration shape used by the ticket staff-assignment endpoints
    (`_resolve_ticket`) — rather than a 403 that would confirm the
    building exists. Customer users are never exposed.
    """

    permission_classes = [IsProviderRosterReader]
    serializer_class = EligibleCrewUserSerializer

    def get(self, request, building_id):
        building = (
            scope_buildings_for(request.user).filter(pk=building_id).first()
        )
        if building is None:
            raise Http404("Building not found.")

        staff = (
            User.objects.filter(
                role=UserRole.STAFF,
                is_active=True,
                deleted_at__isnull=True,
                building_visibility__building_id=building.id,
            )
            .order_by("email")
            .distinct()
        )
        managers = (
            User.objects.filter(
                role=UserRole.BUILDING_MANAGER,
                is_active=True,
                deleted_at__isnull=True,
                building_assignments__building_id=building.id,
            )
            .order_by("email")
            .distinct()
        )

        return Response(
            {
                "staff": EligibleCrewUserSerializer(staff, many=True).data,
                "managers": EligibleCrewUserSerializer(managers, many=True).data,
            },
            status=status.HTTP_200_OK,
        )
