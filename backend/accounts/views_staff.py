"""
Sprint 24A — admin endpoints for StaffProfile + BuildingStaffVisibility.

Mounted at `/api/users/<user_id>/staff-profile/` and
`/api/users/<user_id>/staff-visibility/[/<building_id>/]`. Every
endpoint resolves the target user, runs `CanManageStaffMember` for
the actor↔target check (SUPER_ADMIN passes; COMPANY_ADMIN passes
only inside their own company), and only then performs the read /
write. Cross-company COMPANY_ADMIN attempts hit the object-level
check and return 403 to match the Sprint 23C convention.

Write coverage:
  - StaffProfileView (GET / PATCH)
      Edits phone / internal_note / can_request_assignment /
      is_active on an existing profile. Auto-creates the profile on
      first GET so the admin UI does not need a separate "create
      profile" call (rows are created with model defaults; the same
      shape the seed produces).

  - BuildingStaffVisibilityListCreateView (GET / POST)
      Lists / adds visibility rows. POST {building_id} grants
      visibility on a building. If the actor is a COMPANY_ADMIN the
      target building must belong to one of the actor's companies —
      otherwise we'd let a company admin grant their own STAFF a
      building from another tenant.

  - BuildingStaffVisibilityDetailView (PATCH / DELETE)
      PATCH toggles can_request_assignment; DELETE revokes the row.

Audit:
  - StaffProfile already has full CRUD audit via audit/signals.py.
  - BuildingStaffVisibility already has membership-shape CREATE /
    DELETE audit via the same module.
  Neither view writes AuditLog rows directly.
"""
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response

from buildings.models import Building, BuildingStaffVisibility
from companies.models import CompanyUserMembership
from config.pagination import UnboundedPagination

from .models import StaffProfile, User, UserRole
from .permissions import CanManageStaffMember
from .serializers_staff import (
    BuildingStaffVisibilitySerializer,
    BuildingStaffVisibilityUpdateSerializer,
    StaffProfileSerializer,
    StaffProfileUpdateSerializer,
)


def _get_target_staff(request, user_id):
    """
    Resolve the target user and run the staff-management gate.

    Returns the user instance. 404 on unknown user; 403 from the
    permission class when the actor is out of scope; 400 when the
    target is not a STAFF user (the editor only supports STAFF).
    """
    target = get_object_or_404(User, pk=user_id, deleted_at__isnull=True)
    if target.role != UserRole.STAFF:
        # 400 here is deliberate — a non-STAFF user is a domain mismatch,
        # not a permission failure. The permission class would also
        # return 403 because has_object_permission filters on role.
        # We pre-check so the API caller gets a clearer error and so
        # `get_or_create` below never auto-creates a profile against a
        # COMPANY_ADMIN row by mistake.
        return Response(
            {"detail": "User is not a STAFF user."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return target


class StaffProfileView(generics.GenericAPIView):
    """
    GET   /api/users/<user_id>/staff-profile/
    PATCH /api/users/<user_id>/staff-profile/
    """

    permission_classes = [CanManageStaffMember]

    def _resolve(self, request, user_id):
        target = _get_target_staff(request, user_id)
        if isinstance(target, Response):
            return target, None
        self.check_object_permissions(request, target)
        # Auto-create with model defaults so the admin UI works
        # against any STAFF user that pre-dates Sprint 23A. The seed
        # always creates a profile, but a manually invited STAFF row
        # might not have one yet.
        profile, _ = StaffProfile.objects.get_or_create(user=target)
        return None, profile

    def get(self, request, user_id):
        early_response, profile = self._resolve(request, user_id)
        if early_response is not None:
            return early_response
        return Response(StaffProfileSerializer(profile).data, status=status.HTTP_200_OK)

    def patch(self, request, user_id):
        early_response, profile = self._resolve(request, user_id)
        if early_response is not None:
            return early_response
        serializer = StaffProfileUpdateSerializer(
            profile, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        profile.refresh_from_db()
        return Response(
            StaffProfileSerializer(profile).data, status=status.HTTP_200_OK
        )


class BuildingStaffVisibilityListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/users/<user_id>/staff-visibility/
    POST /api/users/<user_id>/staff-visibility/   {building_id, [can_request_assignment]}
    """

    permission_classes = [CanManageStaffMember]
    serializer_class = BuildingStaffVisibilitySerializer
    pagination_class = UnboundedPagination

    def _resolve_target(self, request):
        target = _get_target_staff(request, self.kwargs["user_id"])
        if isinstance(target, Response):
            return target
        self.check_object_permissions(request, target)
        return target

    def get_queryset(self):
        target = self._resolve_target(self.request)
        if isinstance(target, Response):
            # ListCreateAPIView's list() calls get_queryset before
            # rendering; signal "no rows" via empty qs and rely on
            # the create()/list() overrides for the actual 400 shape.
            return BuildingStaffVisibility.objects.none()
        return (
            BuildingStaffVisibility.objects.filter(user=target)
            .select_related("building", "building__company", "user")
            .order_by("building__name")
        )

    def list(self, request, *args, **kwargs):
        target = self._resolve_target(request)
        if isinstance(target, Response):
            return target
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        target = self._resolve_target(request)
        if isinstance(target, Response):
            return target
        building_id = request.data.get("building_id")
        if not building_id:
            return Response(
                {"building_id": "This field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        building = get_object_or_404(Building, pk=building_id)

        # Cross-company guard: a COMPANY_ADMIN can only grant
        # visibility on buildings in their own company. SUPER_ADMIN
        # passes any building. Without this check, a company admin
        # could attach their own STAFF persona to another tenant's
        # building and bypass the Sprint 23A scope.
        actor = request.user
        if actor.role == UserRole.COMPANY_ADMIN:
            if not CompanyUserMembership.objects.filter(
                user=actor, company_id=building.company_id
            ).exists():
                return Response(
                    {"building_id": "Building is not in your company."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if not building.is_active:
            return Response(
                {"building_id": "Building is inactive."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        can_request_raw = request.data.get("can_request_assignment", True)
        # JSON booleans pass through directly; strings like "true"/"false"
        # are coerced so a curl caller can use either shape.
        if isinstance(can_request_raw, str):
            can_request = can_request_raw.strip().lower() in ("true", "1", "yes")
        else:
            can_request = bool(can_request_raw)

        visibility, created = BuildingStaffVisibility.objects.get_or_create(
            user=target,
            building=building,
            defaults={"can_request_assignment": can_request},
        )
        return Response(
            BuildingStaffVisibilitySerializer(visibility).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class BuildingStaffVisibilityDetailView(generics.GenericAPIView):
    """
    PATCH  /api/users/<user_id>/staff-visibility/<building_id>/
    DELETE /api/users/<user_id>/staff-visibility/<building_id>/
    """

    permission_classes = [CanManageStaffMember]

    def _resolve(self, request, user_id, building_id):
        target = _get_target_staff(request, user_id)
        if isinstance(target, Response):
            return target, None
        self.check_object_permissions(request, target)
        visibility = BuildingStaffVisibility.objects.filter(
            user=target, building_id=building_id
        ).first()
        if visibility is None:
            return Response(
                {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND
            ), None
        return None, visibility

    def patch(self, request, user_id, building_id):
        early_response, visibility = self._resolve(request, user_id, building_id)
        if early_response is not None:
            return early_response
        serializer = BuildingStaffVisibilityUpdateSerializer(
            visibility, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        visibility.refresh_from_db()
        return Response(
            BuildingStaffVisibilitySerializer(visibility).data,
            status=status.HTTP_200_OK,
        )

    @transaction.atomic
    def delete(self, request, user_id, building_id):
        early_response, visibility = self._resolve(request, user_id, building_id)
        if early_response is not None:
            return early_response
        visibility.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
