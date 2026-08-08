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
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRole
from accounts.permissions import (
    IsAuthenticatedAndActive,
    IsSuperAdminOrCompanyAdminForCompany,
)
from accounts.scoping import scope_buildings_for, scope_tickets_for
from customers.models import CustomerBuildingMembership
from customers.serializers_memberships import CustomerBuildingMembershipSerializer
from config.pagination import UnboundedPagination

from .models import Building


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
