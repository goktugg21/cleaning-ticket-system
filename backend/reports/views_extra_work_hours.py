"""W3-H — the hours panel's endpoint.

    GET /api/reports/extra-work/<id>/hours/

Its own module rather than another class in `reports/views.py`, which is
already 50KB: CLAUDE.md's naming rule asks for app-scoped files and asks
not to collapse them into mega-files.

## Why this lives in `reports/` and not in `timesheets/`

Two reasons, and both are rules rather than taste.

**Cost.** `timesheets` records hours and weighted hours and never
computes money (its module docstring says so in as many words). This
response carries a labour cost, so it cannot be served from there.

**Scope.** Deciding whether the caller may read THIS extra work means
resolving the extra work, and `timesheets` imports nothing from
`extra_work` — deliberately, so a provider who uses only the hours
module keeps working. `reports/` is the app that may read across, which
is the same argument `hour_sources.py` and `hours_comparison.py` already
make.

## Who gets what

`IsRevenueReportConsumer` at the door — SA / CA / BM in, STAFF and every
customer-side role 403'd — reused rather than re-derived, and reused
specifically because that class's docstring already settled the shape
this endpoint needs: "admission is to the SURFACE, not to the rows." A
BUILDING_MANAGER is admitted here and then sees their own rows and no
cost, exactly as they do in the Worker Hour Report.

Then the extra work itself is resolved through
`extra_work.scoping.scope_extra_work_for`, so a request for another
tenant's job answers 404 — the same answer a fictional id gives (H-1).
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import IsRevenueReportConsumer


class ExtraWorkHoursView(APIView):
    """GET /api/reports/extra-work/<id>/hours/ — see the module docstring."""

    permission_classes = [IsAuthenticated, IsRevenueReportConsumer]

    def get(self, request, extra_work_id: int):
        # Imported inside the method for the same reason the other
        # cross-module reports views do it: `reports` is loaded early and
        # a module-level import of `extra_work` pulls its whole model
        # graph into every request path that touches this app.
        from extra_work.scoping import scope_extra_work_for

        from .extra_work_hours import extra_work_hours_report

        extra_work = get_object_or_404(
            scope_extra_work_for(request.user).only(
                "id", "company_id", "budget_hours"
            ),
            pk=extra_work_id,
        )
        return Response(extra_work_hours_report(request.user, extra_work))
