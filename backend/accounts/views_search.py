"""
P-6 V4 — `GET /api/search/?q=<text>` — the global search box's endpoint.

One read-only view, five groups of at most five rows each:

    tickets, extra_work, customers, buildings, people

Every group is scoped by the SAME helper its list endpoint already uses
(`accounts.scoping.scope_*_for`, `extra_work.scoping.scope_extra_work_for`,
`accounts.scoping.manageable_user_ids_for`). Nothing here re-derives a
scope rule: an out-of-scope record is simply absent from the answer
(H-1/H-2), a STAFF viewer's extra-work group is always empty (the
scoper returns `.none()` for STAFF by design), and only SUPER_ADMIN /
COMPANY_ADMIN ever see a person — the exact rule `/api/users/` applies.

Matching is `icontains` only, nothing fuzzy. Each group fetches one row
past the limit so `truncated[group]` can say "there is more" without a
count query. `display_phase` is the same server-computed value the list
serializers expose, so the search row and the list row never disagree.
"""
from __future__ import annotations

from django.db.models import Q
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.scoping import (
    manageable_user_ids_for,
    scope_buildings_for,
    scope_customers_for,
    scope_tickets_for,
)
from extra_work.scoping import scope_extra_work_for
from extra_work.serializers import ExtraWorkRequestListSerializer
from tickets.display_phase import ticket_display_phase

from .models import User, UserRole
from .permissions import IsAuthenticatedAndActive

LIMIT = 5
MIN_QUERY_LENGTH = 2
GROUPS = ("tickets", "extra_work", "customers", "buildings", "people")

# The widest id Postgres accepts for a BigAutoField; an all-digit query
# past it is "no such row", not a DataError.
_MAX_ID = 2**63 - 1


def _take(queryset):
    """Fetch LIMIT + 1 rows; return (the first LIMIT, whether more matched)."""
    rows = list(queryset[: LIMIT + 1])
    return rows[:LIMIT], len(rows) > LIMIT


def _exact_id(q: str):
    """The integer an all-digit query names, or None."""
    if not q.isdigit():
        return None
    value = int(q)
    return value if value <= _MAX_ID else None


def _people_queryset(user):
    """Mirror `UserViewSet.get_queryset`'s default branch: active,
    not soft-deleted, cut down to the viewer's manageable set."""
    manageable = manageable_user_ids_for(user)
    if manageable is not None and not manageable:
        return User.objects.none()
    qs = User.objects.filter(is_active=True, deleted_at__isnull=True)
    if manageable is not None:
        qs = qs.filter(id__in=manageable)
    return qs


class GlobalSearchView(APIView):
    """GET /api/search/?q=<text> — see the module docstring."""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, *args, **kwargs):
        q = (request.query_params.get("q") or "").strip()
        if len(q) < MIN_QUERY_LENGTH:
            return Response(
                {
                    "detail": "Type at least two characters to search.",
                    "code": "query_too_short",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        viewer_is_customer = user.role == UserRole.CUSTOMER_USER

        tickets, tickets_truncated = _take(
            scope_tickets_for(user)
            .filter(Q(ticket_no__icontains=q) | Q(title__icontains=q))
            .select_related("customer", "building")
            .order_by("-id")
        )

        extra_work_match = Q(title__icontains=q)
        extra_work_id = _exact_id(q)
        if extra_work_id is not None:
            extra_work_match |= Q(id=extra_work_id)
        extra_work, extra_work_truncated = _take(
            scope_extra_work_for(user)
            .filter(extra_work_match)
            .select_related("customer", "building")
            .order_by("-id")
        )

        customers, customers_truncated = _take(
            scope_customers_for(user)
            .filter(name__icontains=q)
            .select_related("company")
            .order_by("name", "id")
        )

        buildings, buildings_truncated = _take(
            scope_buildings_for(user)
            .filter(Q(name__icontains=q) | Q(city__icontains=q))
            .select_related("company")
            .order_by("name", "id")
        )

        people, people_truncated = _take(
            _people_queryset(user)
            .filter(Q(full_name__icontains=q) | Q(email__icontains=q))
            .order_by("full_name", "id")
        )

        # The list serializer's own method, on an instance that carries
        # the request: the search row's phase is the list row's phase.
        extra_work_phases = ExtraWorkRequestListSerializer(
            context={"request": request}
        )

        return Response(
            {
                "q": q,
                "limit": LIMIT,
                "groups": {
                    "tickets": [
                        {
                            "id": ticket.id,
                            "ticket_no": ticket.ticket_no,
                            "title": ticket.title,
                            "status": ticket.status,
                            "display_phase": ticket_display_phase(
                                status=ticket.status,
                                viewer_is_customer=viewer_is_customer,
                            ),
                            "customer_name": ticket.customer.name,
                            "building_name": ticket.building.name,
                        }
                        for ticket in tickets
                    ],
                    "extra_work": [
                        {
                            "id": row.id,
                            "title": row.title,
                            "status": row.status,
                            "display_phase": extra_work_phases.get_display_phase(row),
                            "customer_name": row.customer.name,
                            "building_name": row.building.name,
                        }
                        for row in extra_work
                    ],
                    "customers": [
                        {
                            "id": customer.id,
                            "name": customer.name,
                            "company_name": customer.company.name,
                        }
                        for customer in customers
                    ],
                    "buildings": [
                        {
                            "id": building.id,
                            "name": building.name,
                            "city": building.city,
                            "company_name": building.company.name,
                        }
                        for building in buildings
                    ],
                    "people": [
                        {
                            "id": person.id,
                            "full_name": person.full_name,
                            "email": person.email,
                            "role": person.role,
                        }
                        for person in people
                    ],
                },
                "truncated": {
                    "tickets": tickets_truncated,
                    "extra_work": extra_work_truncated,
                    "customers": customers_truncated,
                    "buildings": buildings_truncated,
                    "people": people_truncated,
                },
            }
        )
