"""
Sprint 13C — provider/BM-scoped STAFF roster (Employees page backend).

`GET /api/staff/` is the read-only roster the provider-side Employees
page renders. Unlike `UserViewSet` (the SUPER_ADMIN / COMPANY_ADMIN
admin write surface, which 403s BUILDING_MANAGER and returns `none()`
for it), this endpoint deliberately ADMITS BUILDING_MANAGER with a
narrower, building-scoped queryset.

Scope:
  - SUPER_ADMIN: every STAFF-role user (including profile-only ones
    that hold no visibility row yet).
  - COMPANY_ADMIN / BUILDING_MANAGER: STAFF users that hold a
    `BuildingStaffVisibility` row on a building the viewer can see
    (resolved by `building_ids_for`).

Privacy floor: the response is rendered through `StaffRosterSerializer`
which exposes the employment category + viewer-scoped building
visibility ONLY — never `internal_note`, `phone`, customer linkage, or
pricing.

Optional `?employment_type=<INTERNAL_STAFF|ZZP|INHUUR>` filters on
`staff_profile__employment_type`; an out-of-enum value returns a 400
with the stable code `employment_type_invalid`.
"""
from __future__ import annotations

from rest_framework import generics, status
from rest_framework.response import Response

from buildings.models import BuildingStaffVisibility
from config.pagination import UnboundedPagination

from .models import StaffProfile, User, UserRole
from .permissions import IsProviderRosterReader
from .scoping import building_ids_for
from .serializers_staff import StaffRosterSerializer


class StaffRosterView(generics.ListAPIView):
    """GET /api/staff/ — read-only provider/BM STAFF roster."""

    permission_classes = [IsProviderRosterReader]
    serializer_class = StaffRosterSerializer
    pagination_class = UnboundedPagination

    def _viewer_building_ids(self):
        # SUPER_ADMIN is unscoped — return the sentinel `None` so the
        # serializer shows every visibility row without a containment
        # check, and so the queryset below skips the BSV narrowing.
        viewer = self.request.user
        if viewer.role == UserRole.SUPER_ADMIN:
            return None
        return set(building_ids_for(viewer))

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["viewer_building_ids"] = self._viewer_building_ids()
        return context

    def _employment_type_filter(self):
        """Return the validated ?employment_type value or None.

        Raises a ValueError-shaped 400 via the caller when the value is
        out of enum.
        """
        raw = self.request.query_params.get("employment_type")
        if raw in (None, ""):
            return None, None
        if raw not in StaffProfile.EmploymentType.values:
            return None, Response(
                {
                    "detail": "Unknown employment_type.",
                    "code": "employment_type_invalid",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return raw, None

    def get_queryset(self):
        viewer = self.request.user
        base = User.objects.filter(
            role=UserRole.STAFF, deleted_at__isnull=True
        )

        if viewer.role != UserRole.SUPER_ADMIN:
            viewer_building_ids = list(building_ids_for(viewer))
            visible_user_ids = (
                BuildingStaffVisibility.objects.filter(
                    building_id__in=viewer_building_ids
                )
                .values_list("user_id", flat=True)
                .distinct()
            )
            base = base.filter(id__in=visible_user_ids)

        employment_type, _early = self._employment_type_filter()
        if employment_type is not None:
            base = base.filter(
                staff_profile__employment_type=employment_type
            )

        return (
            base.select_related("staff_profile")
            .prefetch_related("building_visibility__building")
            .order_by("email")
            .distinct()
        )

    def list(self, request, *args, **kwargs):
        # Validate the optional filter before touching the queryset so an
        # out-of-enum value returns the stable 400 code rather than an
        # empty 200.
        _employment_type, early = self._employment_type_filter()
        if early is not None:
            return early
        return super().list(request, *args, **kwargs)
