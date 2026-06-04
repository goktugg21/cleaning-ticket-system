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

from buildings.models import BuildingManagerAssignment, BuildingStaffVisibility
from companies.models import CompanyUserMembership
from config.pagination import UnboundedPagination

from .models import StaffProfile, User, UserRole
from .permissions import IsProviderRosterReader
from .scoping import building_ids_for, company_ids_for
from .serializers_staff import ProviderEmployeeSerializer, StaffRosterSerializer


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


# Multi-role provider workforce directory (the Employees page). Lists
# COMPANY_ADMIN / BUILDING_MANAGER / STAFF — the three provider-employee
# roles. EXCLUDES SUPER_ADMIN (a platform admin, not a provider employee)
# and every customer-side user.
_PROVIDER_EMPLOYEE_ROLES = (
    UserRole.COMPANY_ADMIN,
    UserRole.BUILDING_MANAGER,
    UserRole.STAFF,
)


class ProviderEmployeesView(generics.ListAPIView):
    """GET /api/employees/ — provider workforce directory.

    Distinct from /api/staff/ (the STAFF-only roster): this directory lists
    the provider company's COMPANY_ADMIN / BUILDING_MANAGER / STAFF users,
    scoped per the Employees RBAC matrix:

      - SUPER_ADMIN: every provider employee across all companies.
      - COMPANY_ADMIN / BUILDING_MANAGER: employees tied to the viewer's
        provider company(ies) via `company_ids_for` — a COMPANY_ADMIN's
        CompanyUserMembership companies, a BUILDING_MANAGER's
        assigned-building companies. A user is "in" a company through
        CompanyUserMembership (PA), BuildingManagerAssignment.building
        (BM), or BuildingStaffVisibility.building (STAFF). BUILDING_MANAGER
        is admitted READ-ONLY: no edit affordance is ever exposed here, and
        the employment_type edit lives on the SA/CA-only staff-profile
        PATCH (CanManageStaffMember), so a BM cannot mutate anything.

    Cross-tenant isolation: a COMPANY_ADMIN / BUILDING_MANAGER only ever
    sees their own company's employees (the id-set is built from THEIR
    company ids); another provider's people never appear.

    Optional filters (out-of-enum -> stable 400, mirroring the roster):
      - ?role=<COMPANY_ADMIN|BUILDING_MANAGER|STAFF>  (code role_invalid)
      - ?employment_type=<INTERNAL_STAFF|ZZP|INHUUR>  (code employment_type_invalid)

    Privacy floor via ProviderEmployeeSerializer (no internal_note / phone /
    customer linkage / pricing).
    """

    permission_classes = [IsProviderRosterReader]
    serializer_class = ProviderEmployeeSerializer
    pagination_class = UnboundedPagination

    def _role_filter(self):
        raw = self.request.query_params.get("role")
        if raw in (None, ""):
            return None, None
        if raw not in {r.value for r in _PROVIDER_EMPLOYEE_ROLES}:
            return None, Response(
                {"detail": "Unknown role.", "code": "role_invalid"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return raw, None

    def _employment_type_filter(self):
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
            role__in=_PROVIDER_EMPLOYEE_ROLES, deleted_at__isnull=True
        )

        if viewer.role != UserRole.SUPER_ADMIN:
            # Scope to the viewer's provider company(ies). company_ids_for
            # resolves a COMPANY_ADMIN via CompanyUserMembership and a
            # BUILDING_MANAGER via their assigned buildings' companies.
            company_ids = list(company_ids_for(viewer))
            ca_ids = CompanyUserMembership.objects.filter(
                company_id__in=company_ids
            ).values_list("user_id", flat=True)
            bm_ids = BuildingManagerAssignment.objects.filter(
                building__company_id__in=company_ids
            ).values_list("user_id", flat=True)
            staff_ids = BuildingStaffVisibility.objects.filter(
                building__company_id__in=company_ids
            ).values_list("user_id", flat=True)
            employee_ids = set(ca_ids) | set(bm_ids) | set(staff_ids)
            base = base.filter(id__in=employee_ids)

        role, _early = self._role_filter()
        if role is not None:
            base = base.filter(role=role)
        employment_type, _early2 = self._employment_type_filter()
        if employment_type is not None:
            base = base.filter(staff_profile__employment_type=employment_type)

        return base.select_related("staff_profile").order_by("email").distinct()

    def list(self, request, *args, **kwargs):
        # Validate both optional filters before touching the queryset so an
        # out-of-enum value returns the stable 400 code rather than an
        # empty 200.
        _role, early = self._role_filter()
        if early is not None:
            return early
        _employment_type, early2 = self._employment_type_filter()
        if early2 is not None:
            return early2
        return super().list(request, *args, **kwargs)
