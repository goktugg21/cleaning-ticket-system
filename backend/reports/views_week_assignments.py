"""hours2 Part 3 — the week-assignments endpoint.

    GET /api/reports/week-assignments/?iso_year=2026&iso_week=35
        &company=<id>&employee=<id>&employee=<id>

The admin week grid's row proposal: per selected person, the buildings
they may enter and the jobs they are on this week (`week_assignments`
has the whole argument). Its own module beside `views_extra_work_hours`
and `views_planned_vs_actual` — `reports/views.py` is 50KB and CLAUDE.md
asks for app-scoped files.

## Who gets in

`timesheets.permissions.IsTimesheetManager` — SUPER_ADMIN and
COMPANY_ADMIN, the two roles that write other people's weeks. That is
the gate on the grid this feeds (`/admin/hours`), so the endpoint and
the screen agree. A BUILDING_MANAGER or STAFF member fills their OWN
week on **My hours**, which never needs to ask who else is assigned
where; customers are refused everywhere in the hours module.

## Tenant scope

`resolve_view_company` (the module's own reader) turns `?company=` into
one company the caller may read, 404ing an out-of-scope id rather than
confirming it exists. Requested employee ids are intersected with the
company's eligible employees; an id outside that set is absent from the
answer, indistinguishable from an id that never existed (H-1).

## Why not more params on `hour-sources/`

That endpoint answers "what may hours be logged against at all" for the
CALLER, is read by STAFF for their own week, and returns a flat list.
This one answers per OTHER person, per week, for managers only, and
returns a structure. Different question, different gate, different
shape — bolting it on would change a contract every My-hours caller
already speaks.
"""
from __future__ import annotations

from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from timesheets.permissions import IsTimesheetManager
from timesheets.scope import employees_of_company_queryset
from timesheets.views_common import parse_int_param, resolve_view_company


ERR_WEEK_REQUIRED = "week_required"


class WeekAssignmentsView(APIView):
    """GET /api/reports/week-assignments/ — see the module docstring."""

    permission_classes = [IsTimesheetManager]

    def get(self, request, *args, **kwargs):
        # Imported inside the method for the reason the other
        # cross-module reports views give: `reports` loads early, and a
        # module-level import of `tickets` / `extra_work` pulls their
        # whole model graphs into every request path touching this app.
        from .week_assignments import week_assignments

        iso_year = parse_int_param(request.query_params.get("iso_year"))
        iso_week = parse_int_param(request.query_params.get("iso_week"))
        if iso_year is None or iso_week is None or not (1 <= iso_week <= 53):
            raise serializers.ValidationError(
                {
                    "iso_week": [
                        serializers.ErrorDetail(
                            "`iso_year` and `iso_week` are required.",
                            code=ERR_WEEK_REQUIRED,
                        )
                    ]
                }
            )
        try:
            # Validated here so week 53 of a 52-week year is a 400 with a
            # field, not a 500 out of the date library — the same guard
            # `views_week_grid` keeps.
            from timesheets.weeks import week_bounds

            week_bounds(iso_year, iso_week)
        except ValueError:
            raise serializers.ValidationError(
                {
                    "iso_week": [
                        serializers.ErrorDetail(
                            "That ISO week does not exist in that year.",
                            code=ERR_WEEK_REQUIRED,
                        )
                    ]
                }
            )

        company = resolve_view_company(
            request.user, parse_int_param(request.query_params.get("company"))
        )

        requested = {
            parsed
            for parsed in (
                parse_int_param(value)
                for value in request.query_params.getlist("employee")
            )
            if parsed is not None
        }
        employees = (
            employees_of_company_queryset(company.id)
            .filter(pk__in=requested)
            .order_by("full_name", "email", "id")
            if requested
            else []
        )

        return Response(
            week_assignments(request.user, company, employees, iso_year, iso_week)
        )
