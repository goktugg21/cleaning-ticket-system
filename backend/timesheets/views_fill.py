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

W12 — and it is now reachable by the person whose week it is.

Until this sprint the endpoint was `IsTimesheetManager`, and the only
caller was the admin week wizard. So W10's promise — "the weekly sheet
is never blank" — held for an admin opening a crew's week and for
nobody else: a STAFF member opening **My hours** got the raw table,
because the fill for their week had never run and they were 403'd from
running it. The tier that fills is now the tier that owns the row:
a manager fills the company's week, everybody else fills their own and
only their own.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .fill import fill_week
from .permissions import IsTimesheetUser
from .scope import is_timesheet_manager
from .views_common import parse_int_param, resolve_view_company
from .views_weeks import _parse_week


class TimeEntryFillWeekView(APIView):
    """POST /api/timesheets/entries/fill-week/.

    Two tiers, the module's usual pair:

      * SA / CA — the whole company's week, or one employee's with
        `employee`, which is the crew fill the wizard has always done.
      * STAFF / BUILDING_MANAGER — their OWN week. A supplied
        `employee` is not rejected, it is IGNORED: the actor is the
        only employee this can be about, so there is nothing a caller
        could say here that would change the answer, and a 403 for
        naming yourself would be a puzzle rather than a guard.
    """

    permission_classes = [IsTimesheetUser]

    def post(self, request, *args, **kwargs):
        iso_year, iso_week = _parse_week(request.data)
        company = resolve_view_company(
            request.user, parse_int_param(request.data.get("company"))
        )
        if is_timesheet_manager(request.user):
            employee_id = parse_int_param(request.data.get("employee"))
        else:
            employee_id = request.user.id
        result = fill_week(
            company.id, iso_year, iso_week, actor=request.user,
            employee_id=employee_id,
        )
        return Response(
            {
                "company": company.id,
                "iso_year": iso_year,
                "iso_week": iso_week,
                "employee": employee_id,
                **result.as_dict(),
            },
            status=status.HTTP_200_OK,
        )
