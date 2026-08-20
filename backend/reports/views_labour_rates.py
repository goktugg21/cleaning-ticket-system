"""W4-R — the per-person hourly rate endpoints.

    GET  /api/reports/employee-hourly-rates/            list
    POST /api/reports/employee-hourly-rates/            record a new rate
    GET/PATCH/DELETE
         /api/reports/employee-hourly-rates/<id>/       one row

Its own module rather than another class in `reports/views.py`, which is
already 50KB: CLAUDE.md's naming rule asks for app-scoped files and asks
not to collapse them into mega-files.

## The permission is HERE, not on the screen

A wage is personal data. Hiding a field in the frontend while the
endpoint still returns it is not a permission, it is a decoration — so
the rule lives at the door (`IsLabourRateManager`: SA and CA only) and
again in the queryset (`filter_hourly_rates_for`), and both are tested
by calling this URL as each of the five roles.

## Editing a historical row is allowed, deliberately

PATCH and DELETE re-price the period the edited row covered, and that is
the intended behaviour: an operator who typed 24.50 for 25.40 has to be
able to fix it. What the model prevents is a rate change re-pricing the
past SILENTLY, as a side effect of an ordinary raise — a raise writes a
NEW row from a NEW date and touches nothing before it. The difference
between the two is the difference between a correction somebody made and
a number that moved on its own. Every write here lands on the
`AuditLog` with a before/after diff (H-10's shape), so a corrected wage
is attributable.

## Pagination

`UnboundedPagination` is NOT used and no `pagination_class` is set here:
this is a new endpoint with no other callers, so it takes the project
default and the list page gets real prev/next. CLAUDE.md's rule about
loosening a shared endpoint's pagination is about endpoints that already
have callers; the lesson it draws — fix the caller that has no
pagination UI — is why the frontend pages this exhaustively (the Sprint
120 pattern) instead.
"""
from __future__ import annotations

from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .labour_rate_scope import filter_hourly_rates_for
from .models import EmployeeHourlyRate
from .permissions import IsLabourRateManager
from .serializers_labour_rates import EmployeeHourlyRateSerializer


class _LabourRateBase:
    """The scoped queryset and the serializer context, in one place.

    Both views need the identical pair, and a second copy of the scope
    call is the copy somebody later edits only one of.
    """

    permission_classes = [IsAuthenticated, IsLabourRateManager]
    serializer_class = EmployeeHourlyRateSerializer

    def get_queryset(self):
        return filter_hourly_rates_for(
            self.request.user,
            EmployeeHourlyRate.objects.select_related(
                "company", "employee", "created_by"
            ),
        )


class EmployeeHourlyRateListCreateView(_LabourRateBase, ListCreateAPIView):
    """List the rates in scope, or record a new one.

    `?employee=<id>` and `?company=<id>` narrow the list — the rate
    HISTORY of one person is what the editor reads, and it is the list
    filtered to them rather than a second endpoint. Both filters are
    applied ON TOP of the scope, never instead of it: an out-of-scope
    `?company=` yields nothing rather than another tenant's wages.
    """

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params

        employee = params.get("employee")
        if employee:
            try:
                queryset = queryset.filter(employee_id=int(employee))
            except (TypeError, ValueError):
                raise ValidationError({"employee": "Must be an integer."})

        company = params.get("company")
        if company:
            try:
                queryset = queryset.filter(company_id=int(company))
            except (TypeError, ValueError):
                raise ValidationError({"company": "Must be an integer."})

        return queryset

    def perform_create(self, serializer):
        # `created_by` is the ACTOR, never a client-supplied field —
        # it is read-only on the serializer for exactly that reason.
        serializer.save(created_by=self.request.user)


class EmployeeHourlyRateDetailView(_LabourRateBase, RetrieveUpdateDestroyAPIView):
    """Read, correct or remove one dated rate row.

    A row out of the actor's scope 404s through `get_queryset`, which is
    the same answer a fictional id gives (H-1) — out of scope must be
    indistinguishable from nonexistent.
    """

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:  # pragma: no cover - nothing FKs to a rate yet
            # Defensive. Nothing references a rate row today; the day
            # something does, this answers with a sentence instead of a
            # 500. Cheaper to write now than to find in production.
            return Response(
                {
                    "detail": (
                        "This rate is referenced elsewhere and cannot be "
                        "removed. Supersede it with a new rate from a later "
                        "date instead."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
