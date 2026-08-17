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
      - ?company=<id>                                 (code company_invalid)

    Sprint 187B §2 — `?company=` follows the same convention as the two
    above: a non-integer value is a stable 400 with a named code, never a
    500 and never a silent empty 200.

    It NARROWS; it never widens (H-1/H-2). The scoping block below builds
    the caller's own company-id set first, and that set remains the outer
    bound: `?company=` is applied INSIDE it. A COMPANY_ADMIN who passes
    another provider's id has their own scope intersected with a company
    they hold nothing in, and receives zero rows — not that company's
    employees, and no error that would confirm the id exists. A
    SUPER_ADMIN has no outer bound, so the parameter simply selects one
    company for them.

    Privacy floor via ProviderEmployeeSerializer: no internal_note, no
    StaffProfile.phone, no customer linkage, no pricing. Sprint 187B adds
    the PROVIDER company name, which is not customer linkage — see that
    serializer's docstring for the reasoning.
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

    def _company_filter(self):
        """Sprint 187B §2 — ?company=<id>, validated like its two siblings.

        A non-integer is a stable 400 with a named code. An id that does
        not exist is NOT an error: it is treated as "a company with no
        employees here" and yields an empty 200, because a 400 or 404 on
        an unknown id would tell a COMPANY_ADMIN which ids are real —
        the cross-tenant leak this filter exists to avoid.
        """
        raw = self.request.query_params.get("company")
        if raw in (None, ""):
            return None, None
        try:
            return int(raw), None
        except (TypeError, ValueError):
            return None, Response(
                {"detail": "Unknown company.", "code": "company_invalid"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def get_queryset(self):
        viewer = self.request.user
        base = User.objects.filter(
            role__in=_PROVIDER_EMPLOYEE_ROLES, deleted_at__isnull=True
        )

        company_filter, _early3 = self._company_filter()

        if viewer.role != UserRole.SUPER_ADMIN:
            # Scope to the viewer's provider company(ies). company_ids_for
            # resolves a COMPANY_ADMIN via CompanyUserMembership and a
            # BUILDING_MANAGER via their assigned buildings' companies.
            company_ids = list(company_ids_for(viewer))
            # Sprint 187B §2 — ?company= narrows INSIDE the caller's own
            # set; it never replaces it. Intersecting here rather than
            # further down is what makes widening impossible: an id the
            # caller does not hold leaves an EMPTY set, and every id-set
            # below is then built from nothing. A COMPANY_ADMIN passing
            # another provider's id gets zero rows by construction, not by
            # a filter that could later be reordered away.
            if company_filter is not None:
                company_ids = [c for c in company_ids if c == company_filter]
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
        elif company_filter is not None:
            # SUPER_ADMIN has no outer bound, so the parameter selects one
            # company directly — the same three membership axes as above.
            ca_ids = CompanyUserMembership.objects.filter(
                company_id=company_filter
            ).values_list("user_id", flat=True)
            bm_ids = BuildingManagerAssignment.objects.filter(
                building__company_id=company_filter
            ).values_list("user_id", flat=True)
            staff_ids = BuildingStaffVisibility.objects.filter(
                building__company_id=company_filter
            ).values_list("user_id", flat=True)
            base = base.filter(
                id__in=set(ca_ids) | set(bm_ids) | set(staff_ids)
            )

        role, _early = self._role_filter()
        if role is not None:
            base = base.filter(role=role)
        employment_type, _early2 = self._employment_type_filter()
        if employment_type is not None:
            base = base.filter(staff_profile__employment_type=employment_type)

        return base.select_related("staff_profile").order_by("email").distinct()

    def paginate_queryset(self, queryset):
        """Sprint 187B §2 — attach each row's provider company names.

        `paginate_queryset` is the precise hook: DRF calls it with the
        filtered queryset and hands whatever it returns straight to the
        serializer, so this sees exactly the rows that will be rendered
        and nothing else.

        The names are resolved for the WHOLE page in three queries (one
        per membership axis) and attached in Python, rather than looked
        up per row in the serializer. This endpoint uses
        `UnboundedPagination`, so a per-row lookup would be three SELECTs
        times the entire provider workforce; this is three regardless of
        how many people there are.
        """
        page = super().paginate_queryset(queryset)
        if page is None:
            # Pagination disabled. Returning a list here would break DRF's
            # contract (it reads None as "unpaginated"), so hand back None
            # and let the serializer resolve each row on its own. That path
            # is an N+1, which is why the serializer's fallback exists and
            # why an assertNumQueries test pins this one.
            return None
        rows = list(page)
        self._attach_company_names(rows)
        return rows

    @staticmethod
    def _attach_company_names(rows):
        user_ids = [u.pk for u in rows]
        if not user_ids:
            return
        names_by_user = {uid: set() for uid in user_ids}

        def _collect(pairs):
            for user_id, name in pairs:
                if user_id in names_by_user:
                    names_by_user[user_id].add(name)

        _collect(
            CompanyUserMembership.objects.filter(
                user_id__in=user_ids
            ).values_list("user_id", "company__name")
        )
        _collect(
            BuildingManagerAssignment.objects.filter(
                user_id__in=user_ids
            ).values_list("user_id", "building__company__name")
        )
        _collect(
            BuildingStaffVisibility.objects.filter(
                user_id__in=user_ids
            ).values_list("user_id", "building__company__name")
        )
        for row in rows:
            row._company_names = sorted(names_by_user.get(row.pk, set()))

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
        # Sprint 187B §2 — same treatment for ?company=: a junk value is a
        # named 400 here, before the queryset runs, rather than an empty
        # 200 that would read as "this company has no employees".
        _company, early3 = self._company_filter()
        if early3 is not None:
            return early3
        return super().list(request, *args, **kwargs)
