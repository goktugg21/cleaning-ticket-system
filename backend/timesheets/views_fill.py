"""W10 — materialise one company-week from its standing agreements.

    POST /api/timesheets/entries/fill-week/
    {"iso_year": 2026, "iso_week": 34, "company": 3}

A POST rather than a side effect on the week grid's GET: reading a
sheet must not write to it, or two people opening the same week race
each other and neither can tell what happened.

Idempotent, so the client may call it every time a week is opened —
which is what makes the sheet arrive filled without anybody pressing
anything. The rules live in `timesheets.fill`; this view resolves the
company and the actor and nothing else.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .fill import fill_week
from .permissions import IsTimesheetManager
from .views_common import parse_int_param, resolve_view_company
from .views_weeks import _parse_week


class TimeEntryFillWeekView(APIView):
    """POST /api/timesheets/entries/fill-week/.

    Manager-only, matching every other write that acts on somebody
    else's hours: a fill writes rows for a whole crew.
    """

    permission_classes = [IsTimesheetManager]

    def post(self, request, *args, **kwargs):
        iso_year, iso_week = _parse_week(request.data)
        company = resolve_view_company(
            request.user, parse_int_param(request.data.get("company"))
        )
        result = fill_week(
            company.id, iso_year, iso_week, actor=request.user
        )
        return Response(
            {
                "company": company.id,
                "iso_year": iso_year,
                "iso_week": iso_week,
                **result.as_dict(),
            },
            status=status.HTTP_200_OK,
        )
