"""
Sprint 154 §I.5/§I.6 — the building detail page's reads.

  GET /api/buildings/<id>/customers/   the inverse of
                                       /api/customers/<id>/buildings/
  GET /api/buildings/<id>/summary/     the dashboard counts

Same rules as `customers/views_summary.py`, deliberately: scope through
`scope_buildings_for`, **404 and never 403** for a building outside that
scope (a 403 confirms the row exists — H-1), each block individually
wrapped so one module raising cannot take the page down, and `null` for
"this module is not yours to read" versus `0` for "readable and empty".
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRole
from accounts.permissions import (
    IsAuthenticatedAndActive,
    IsSuperAdminOrCompanyAdminForCompany,
)
from accounts.scoping import scope_buildings_for, scope_tickets_for
from customers.models import ContactBuildingLink, CustomerBuildingMembership
from customers.serializers_memberships import CustomerBuildingMembershipSerializer
from config.pagination import UnboundedPagination

from .models import Building, BuildingStaffVisibility


class BuildingCustomerListView(generics.ListAPIView):
    """GET /api/buildings/<building_id>/customers/

    The inverse read of `CustomerBuildingListCreateView`. Without it the
    building page would have to fetch EVERY customer and filter
    client-side, which is both a bigger payload and a scope decision made
    in the browser.

    Reuses `CustomerBuildingMembershipSerializer` so the row shape is
    identical from both directions — one serializer, two anchors.
    Writes go through the shared `/api/buildings/bulk-link/` endpoint.
    """

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]
    serializer_class = CustomerBuildingMembershipSerializer
    pagination_class = UnboundedPagination

    def _get_building(self):
        # Scoped lookup, so an out-of-scope building 404s here rather
        # than reaching check_object_permissions and 403ing.
        building = get_object_or_404(
            scope_buildings_for(self.request.user), pk=self.kwargs["building_id"]
        )
        self.check_object_permissions(self.request, building)
        return building

    def get_queryset(self):
        building = self._get_building()
        return (
            CustomerBuildingMembership.objects.filter(building=building)
            .select_related("customer", "building")
            .order_by("customer__name")
        )


class _BuildingStaffRowSerializer(serializers.ModelSerializer):
    """Sprint 154 §G.2 — one staff member linked to this building.

    Deliberately NOT `accounts.serializers_staff
    .BuildingStaffVisibilitySerializer`: that one is anchored on the USER
    (it repeats the building on every row, because it answers "which
    buildings does this person see"). This answers the mirror question
    and so repeats the person, not the building.
    """

    user_id = serializers.IntegerField(source="user.id", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    user_full_name = serializers.CharField(
        source="user.full_name", read_only=True
    )
    # Sprint 154 §I.1 — the user's own number. `StaffProfile.phone` is a
    # DIFFERENT field (staff-only, customer-visibility-gated) and is
    # deliberately not mixed in here.
    user_phone = serializers.CharField(source="user.phone", read_only=True)

    class Meta:
        model = BuildingStaffVisibility
        fields = [
            "id",
            "user_id",
            "user_email",
            "user_full_name",
            "user_phone",
            "visibility_level",
            "can_request_assignment",
            "created_at",
        ]
        read_only_fields = fields


class _BuildingContactRowSerializer(serializers.ModelSerializer):
    """Sprint 154 §G.2 — one contact person linked to this building.

    A `Contact` may or may not have a login (`user` is nullable), which
    is exactly why contacts are a separate concept from users; the
    building page shows both lists side by side.
    """

    contact_id = serializers.IntegerField(source="contact.id", read_only=True)
    full_name = serializers.CharField(source="contact.full_name", read_only=True)
    email = serializers.CharField(source="contact.email", read_only=True)
    phone = serializers.CharField(source="contact.phone", read_only=True)
    role_label = serializers.CharField(
        source="contact.role_label", read_only=True
    )
    customer_id = serializers.IntegerField(
        source="contact.customer_id", read_only=True
    )
    customer_name = serializers.CharField(
        source="contact.customer.name", read_only=True
    )
    has_login = serializers.SerializerMethodField()

    class Meta:
        model = ContactBuildingLink
        fields = [
            "id",
            "contact_id",
            "full_name",
            "email",
            "phone",
            "role_label",
            "customer_id",
            "customer_name",
            "has_login",
            "created_at",
        ]
        read_only_fields = fields

    def get_has_login(self, obj) -> bool:
        return obj.contact.user_id is not None


class BuildingStaffListView(generics.ListAPIView):
    """GET /api/buildings/<building_id>/staff/

    The per-BUILDING read of `BuildingStaffVisibility`. The relation has
    always been editable — from the USER's page — but has never been
    readable from the building, which is what §G.2 needs. Writes go
    through the shared `/api/buildings/bulk-link/` endpoint.
    """

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]
    serializer_class = _BuildingStaffRowSerializer
    pagination_class = UnboundedPagination

    def get_queryset(self):
        building = get_object_or_404(
            scope_buildings_for(self.request.user), pk=self.kwargs["building_id"]
        )
        self.check_object_permissions(self.request, building)
        return (
            BuildingStaffVisibility.objects.filter(building=building)
            .select_related("user")
            .order_by("user__full_name", "user__email")
        )


class BuildingContactListView(generics.ListAPIView):
    """GET /api/buildings/<building_id>/contacts/

    The per-BUILDING read of `ContactBuildingLink`. Same story as staff:
    the M:N has existed since Sprint 12B and is managed from the
    customer's contacts page; this is the missing view from the
    building's side.
    """

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]
    serializer_class = _BuildingContactRowSerializer
    pagination_class = UnboundedPagination

    def get_queryset(self):
        building = get_object_or_404(
            scope_buildings_for(self.request.user), pk=self.kwargs["building_id"]
        )
        self.check_object_permissions(self.request, building)
        return (
            ContactBuildingLink.objects.filter(building=building)
            .select_related("contact", "contact__customer", "contact__user")
            .order_by("contact__full_name")
        )


class BuildingSummaryView(APIView):
    """GET /api/buildings/<building_id>/summary/

    Read-only operational counts for one building. Permission is the same
    gate as `GET /api/buildings/<id>/` — `IsAuthenticatedAndActive` plus
    the `scope_buildings_for` queryset.
    """

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, building_id: int, *args, **kwargs):
        building = get_object_or_404(
            scope_buildings_for(request.user), pk=building_id
        )

        data = {}
        data.update(self._link_counts(building))
        data.update(self._room_count(building))
        data.update(self._ticket_counts(request.user, building))
        data.update(self._extra_work_counts(request.user, building))
        return Response(data, status=status.HTTP_200_OK)

    @staticmethod
    def _link_counts(building: Building) -> dict:
        """The four link counts. These are properties of the building row
        itself: reaching the building at all is the only gate they need."""
        try:
            return {
                "customer_count": building.customer_memberships.count(),
                "manager_count": building.manager_assignments.count(),
                "staff_count": building.staff_visibility.count(),
                "contact_count": building.contact_links.count(),
            }
        except Exception:  # pragma: no cover - defensive
            return {
                "customer_count": None,
                "manager_count": None,
                "staff_count": None,
                "contact_count": None,
            }

    @staticmethod
    def _room_count(building: Building) -> dict:
        """ALWAYS `null` — and that is a factual answer, not a stub.

        Sprint 154 §I.6 asked for a room count. **This system has no room
        concept at all**: there is no `Room` model, no rooms app, and no
        field on `Building` that subdivides it. A building is an
        indivisible location everywhere in the codebase — tickets, extra
        work, planned work and staff visibility all anchor on
        `building_id` with nothing below it.

        The key is present and `null` so the contract is stable and the
        frontend renders an em dash rather than a misleading `0`. Adding
        real rooms is a new model, a new migration, and a product
        decision about what a room means for ticketing — not something to
        infer. Recorded in the checklist's NEXT queue.
        """
        return {"room_count": None}

    @staticmethod
    def _ticket_counts(user, building: Building) -> dict:
        """Total + open tickets at this building, in the ACTOR's scope.

        `TERMINAL_TICKET_STATUSES` is imported from `tickets.models` — the
        exported frozenset that `views_sub_tasks` and
        `views_staff_assignments` already share. See Sprint 153's
        `customers/views_summary.py` for why that module, and not
        `state_machine`, is the authority.
        """
        try:
            from tickets.models import TERMINAL_TICKET_STATUSES

            scoped = scope_tickets_for(user).filter(building=building)
            terminal = [str(s) for s in TERMINAL_TICKET_STATUSES]
            return {
                "ticket_count": scoped.count(),
                "open_ticket_count": scoped.exclude(status__in=terminal).count(),
            }
        except Exception:  # pragma: no cover - defensive
            return {"ticket_count": None, "open_ticket_count": None}

    @staticmethod
    def _extra_work_counts(user, building: Building) -> dict:
        """STAFF gets `null`: `scope_extra_work_for` returns `.none()` for
        STAFF by deliberate privacy design, and reporting `0` would
        misrepresent that as 'there is no extra work here'."""
        if user.role == UserRole.STAFF:
            return {"extra_work_count": None, "open_extra_work_count": None}
        try:
            from extra_work.scoping import scope_extra_work_for
            from extra_work.views import EXTRA_WORK_TERMINAL_STATUSES

            scoped = scope_extra_work_for(user).filter(building=building)
            return {
                "extra_work_count": scoped.count(),
                "open_extra_work_count": scoped.exclude(
                    status__in=list(EXTRA_WORK_TERMINAL_STATUSES)
                ).count(),
            }
        except Exception:  # pragma: no cover - defensive
            return {"extra_work_count": None, "open_extra_work_count": None}
