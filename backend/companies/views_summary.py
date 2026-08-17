"""
Sprint 156 §1 — the SUPER_ADMIN's read of one provider company.

    GET /api/companies/<company_id>/summary/       counts for the tiles
    GET /api/companies/<company_id>/admins-detail/ COMPANY_ADMINs + phone
    GET /api/companies/<company_id>/employees/     staff + BMs + buildings
    GET /api/companies/<company_id>/buildings/     the company's buildings
    GET /api/companies/<company_id>/customers/     the company's customers

`CompanyDetailPage` answered "what IS this provider company?" with a name,
a slug, a language and a list of admin e-mails. These five reads are what
it needed to answer it properly, and they follow the shape Sprint 153
(`customers/views_summary.py`) and Sprint 154 (`buildings/views_summary.py`)
established, for the same three reasons:

1. **Scoped resolution, 404 and never 403.** Every view resolves the
   company through `scope_companies_for(request.user)`, so a company the
   actor may not see is indistinguishable from one that does not exist.
   A 403 would confirm the id names a real company, which is the
   existence oracle H-1 forbids (the Sprint 142.1 class).

2. **Each block is wrapped, so one unreadable module degrades to `null`
   rather than 500.** The tiles read across four apps; a company whose
   extra-work module cannot be read should still show its building count.
   `null` and `0` are deliberately different answers — `null` means "not
   answerable for you", `0` means "none", and the UI renders an em dash
   for the first.

3. **Counts are ANNOTATED, never counted per row.** The employee list
   carries each person's buildings, which is the one place an N+1 would
   hide; `test_sprint156_company_area.py` pins a 10-row page at the same
   query count as a 2-row page.

Phone is `User.phone` throughout (Sprint 154 §I.1). **Never
`StaffProfile.phone`** — that field is staff-only and gated by the
customer's `show_assigned_staff_phone` policy, and Sprint 154 §K already
established that putting it on a provider read surface breaches
`ProviderEmployeeSerializer`'s documented privacy floor.
"""
from __future__ import annotations

from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User, UserRole
from accounts.permissions import IsAuthenticatedAndActive
from accounts.scoping import (
    scope_buildings_for,
    scope_companies_for,
    scope_customers_for,
    scope_tickets_for,
)
from buildings.models import Building, BuildingManagerAssignment, BuildingStaffVisibility
from config.pagination import UnboundedPagination
from customers.models import Customer

from .models import Company, CompanyUserMembership


def _resolve_company(request, company_id: int) -> Company:
    """The one resolution path. Scoped, so out-of-scope is a 404."""
    return get_object_or_404(scope_companies_for(request.user), pk=company_id)


# ---------------------------------------------------------------------------
# Summary — the stat tiles
# ---------------------------------------------------------------------------


class CompanySummaryView(APIView):
    """GET /api/companies/<company_id>/summary/"""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, company_id: int, *args, **kwargs):
        company = _resolve_company(request, company_id)

        data = {}
        data.update(self._structure_counts(request.user, company))
        data.update(self._people_counts(company))
        data.update(self._ticket_counts(request.user, company))
        data.update(self._extra_work_counts(request.user, company))
        return Response(data, status=status.HTTP_200_OK)

    @staticmethod
    def _structure_counts(user, company: Company) -> dict:
        """Buildings and customers, both through the ACTOR's scope.

        Scoped rather than counted off the company directly: a
        COMPANY_ADMIN of this company sees all of them, but the count must
        not become a way to learn about rows the actor cannot list.
        """
        try:
            return {
                "building_count": scope_buildings_for(user)
                .filter(company=company)
                .count(),
                "customer_count": scope_customers_for(user)
                .filter(company=company)
                .count(),
            }
        except Exception:  # pragma: no cover - defensive
            return {"building_count": None, "customer_count": None}

    @staticmethod
    def _people_counts(company: Company) -> dict:
        """Admins and employees.

        `admin_count` is COMPANY_ADMIN membership rows. `employee_count`
        is provider-side STAFF and BUILDING_MANAGERs reachable from this
        company — see `_company_employee_queryset` for why membership
        alone is the wrong question.
        """
        try:
            return {
                "admin_count": CompanyUserMembership.objects.filter(
                    company=company, user__role=UserRole.COMPANY_ADMIN
                )
                .values("user_id")
                .distinct()
                .count(),
                "employee_count": _company_employee_queryset(company).count(),
            }
        except Exception:  # pragma: no cover - defensive
            return {"admin_count": None, "employee_count": None}

    @staticmethod
    def _ticket_counts(user, company: Company) -> dict:
        """Open tickets across the company's buildings, in the actor's scope.

        `TERMINAL_TICKET_STATUSES` is the exported frozenset in
        `tickets.models` — the same authority Sprint 153 and 154 used, and
        deliberately not `state_machine`.
        """
        try:
            from tickets.models import TERMINAL_TICKET_STATUSES

            scoped = scope_tickets_for(user).filter(building__company=company)
            terminal = [str(s) for s in TERMINAL_TICKET_STATUSES]
            return {
                "ticket_count": scoped.count(),
                "open_ticket_count": scoped.exclude(status__in=terminal).count(),
            }
        except Exception:  # pragma: no cover - defensive
            return {"ticket_count": None, "open_ticket_count": None}

    @staticmethod
    def _extra_work_counts(user, company: Company) -> dict:
        """STAFF gets `null`, not `0`.

        `scope_extra_work_for` returns `.none()` for STAFF by deliberate
        privacy design; reporting `0` would misrepresent that as "there is
        no extra work here". Same rule as the building summary.
        """
        if user.role == UserRole.STAFF:
            return {"extra_work_count": None, "open_extra_work_count": None}
        try:
            from extra_work.scoping import scope_extra_work_for
            from extra_work.views import EXTRA_WORK_TERMINAL_STATUSES

            scoped = scope_extra_work_for(user).filter(
                building__company=company
            )
            return {
                "extra_work_count": scoped.count(),
                "open_extra_work_count": scoped.exclude(
                    status__in=list(EXTRA_WORK_TERMINAL_STATUSES)
                ).count(),
            }
        except Exception:  # pragma: no cover - defensive
            return {"extra_work_count": None, "open_extra_work_count": None}


# ---------------------------------------------------------------------------
# Who is in this company
# ---------------------------------------------------------------------------


def _company_employee_queryset(company: Company):
    """Provider-side STAFF and BUILDING_MANAGERs belonging to this company.

    **Membership alone is the wrong question**, and this is the trap
    Sprint 152.1 already documented for the timesheets employee picker:
    `CompanyUserMembership` is how COMPANY_ADMINs are attached, but a
    STAFF member belongs to a company through
    `BuildingStaffVisibility` and a BUILDING_MANAGER through
    `BuildingManagerAssignment`. Asking only the membership table reports
    zero employees for exactly the roles this card exists to show.

    So the answer is the union of all three routes, de-duplicated by the
    queryset itself.
    """
    attached = (
        Q(building_visibility__building__company=company)
        | Q(building_assignments__building__company=company)
        | Q(company_memberships__company=company)
    )
    return (
        User.objects.filter(
            role__in=[UserRole.STAFF, UserRole.BUILDING_MANAGER]
        )
        # `distinct()` is load-bearing, not tidiness: a manager of three
        # buildings matches the OR three times and would appear three
        # times in the list AND be counted three times on the tile.
        .filter(attached)
        .distinct()
    )


class _CompanyAdminRowSerializer(serializers.ModelSerializer):
    """One COMPANY_ADMIN of this company.

    E-mail and phone are both `User` fields the provider side already
    exposes elsewhere; `phone` is `User.phone` (ungated), never
    `StaffProfile.phone`.
    """

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "phone", "is_active"]
        read_only_fields = fields


class _CompanyEmployeeRowSerializer(serializers.ModelSerializer):
    """One provider-side employee, with the buildings they are on.

    "Which buildings is this person on" is the whole point of the card —
    it is the "who can do what, where" question — so the buildings come
    down ON the row rather than as a second request per person. The view
    prefetches both link tables, so `get_buildings` touches no query.
    """

    buildings = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "phone", "role", "is_active", "buildings"]
        read_only_fields = fields

    def get_buildings(self, obj: User) -> list:
        seen = {}
        # A STAFF member is attached through visibility, a BUILDING_MANAGER
        # through assignment. Reading BOTH on every row rather than
        # branching on role: a role can change without the old link rows
        # being cleaned up, and a person who still has both should show
        # both rather than have half of them silently dropped.
        for link in obj.building_visibility.all():
            seen[link.building_id] = link.building.name
        for link in obj.building_assignments.all():
            seen[link.building_id] = link.building.name
        return [
            {"id": building_id, "name": name}
            for building_id, name in sorted(seen.items(), key=lambda kv: kv[1])
        ]


class CompanyAdminDetailListView(generics.ListAPIView):
    """GET /api/companies/<company_id>/admins-detail/

    Deliberately NOT the existing `/admins/` endpoint: that one is
    anchored on `CompanyUserMembership` and is the write surface for
    adding and removing admins. This is a read of the PEOPLE, with the
    fields the detail card renders. Widening the membership serializer
    instead would change the shape for its existing write callers.
    """

    permission_classes = [IsAuthenticatedAndActive]
    serializer_class = _CompanyAdminRowSerializer
    pagination_class = UnboundedPagination

    def get_queryset(self):
        company = _resolve_company(self.request, self.kwargs["company_id"])
        return (
            User.objects.filter(
                role=UserRole.COMPANY_ADMIN,
                company_memberships__company=company,
            )
            .distinct()
            .order_by("full_name", "email")
        )


class CompanyEmployeeListView(generics.ListAPIView):
    """GET /api/companies/<company_id>/employees/"""

    permission_classes = [IsAuthenticatedAndActive]
    serializer_class = _CompanyEmployeeRowSerializer
    pagination_class = UnboundedPagination

    def get_queryset(self):
        company = _resolve_company(self.request, self.kwargs["company_id"])
        # Both link tables prefetched WITH their building, so the row
        # serializer's `get_buildings` costs nothing per row. Without
        # this the employees card is a textbook N+1 — two extra queries
        # per person — which is what the assertNumQueries test guards.
        return (
            _company_employee_queryset(company)
            .prefetch_related(
                Prefetch(
                    "building_visibility",
                    queryset=BuildingStaffVisibility.objects.select_related(
                        "building"
                    ).filter(building__company=company),
                ),
                Prefetch(
                    "building_assignments",
                    queryset=BuildingManagerAssignment.objects.select_related(
                        "building"
                    ).filter(building__company=company),
                ),
            )
            .order_by("full_name", "email")
        )


class _CompanyBuildingRowSerializer(serializers.ModelSerializer):
    customer_count = serializers.SerializerMethodField()

    class Meta:
        model = Building
        fields = [
            "id",
            "name",
            "address",
            "city",
            "postal_code",
            "is_active",
            "customer_count",
        ]
        read_only_fields = fields

    def get_customer_count(self, obj: Building) -> int:
        # `is not None`, never truthiness — an annotated 0 is a real
        # answer and must not fall through to a per-row query.
        annotated = getattr(obj, "_customer_count", None)
        if annotated is not None:
            return annotated
        return obj.customer_memberships.count()


class CompanyBuildingListView(generics.ListAPIView):
    """GET /api/companies/<company_id>/buildings/"""

    permission_classes = [IsAuthenticatedAndActive]
    serializer_class = _CompanyBuildingRowSerializer
    pagination_class = UnboundedPagination

    def get_queryset(self):
        company = _resolve_company(self.request, self.kwargs["company_id"])
        return (
            scope_buildings_for(self.request.user)
            .filter(company=company)
            .annotate(_customer_count=Count("customer_memberships", distinct=True))
            .order_by("name")
        )


class _CompanyCustomerRowSerializer(serializers.ModelSerializer):
    building_count = serializers.SerializerMethodField()
    user_count = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            "id",
            "name",
            "is_active",
            "building_count",
            "user_count",
        ]
        read_only_fields = fields

    @staticmethod
    def _annotated(obj, attr, related):
        annotated = getattr(obj, attr, None)
        if annotated is not None:
            return annotated
        return getattr(obj, related).count()

    def get_building_count(self, obj: Customer) -> int:
        return self._annotated(obj, "_building_count", "building_memberships")

    def get_user_count(self, obj: Customer) -> int:
        return self._annotated(obj, "_user_count", "user_memberships")


class CompanyCustomerListView(generics.ListAPIView):
    """GET /api/companies/<company_id>/customers/

    Each row becomes a link to `/admin/customers/<id>` in the UI — the
    owner asked for that click-through explicitly.
    """

    permission_classes = [IsAuthenticatedAndActive]
    serializer_class = _CompanyCustomerRowSerializer
    pagination_class = UnboundedPagination

    def get_queryset(self):
        company = _resolve_company(self.request, self.kwargs["company_id"])
        return (
            scope_customers_for(self.request.user)
            .filter(company=company)
            .annotate(
                # `distinct=True` is mandatory: two joined Counts in one
                # query multiply each other's rows otherwise.
                _building_count=Count("building_memberships", distinct=True),
                _user_count=Count("user_memberships", distinct=True),
            )
            .order_by("name")
        )
