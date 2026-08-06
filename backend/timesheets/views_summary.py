"""
Sprint 152 — the timesheets summary + its CSV export.

    GET /api/timesheets/summary/
    GET /api/timesheets/summary/export.csv

Same filters as the entries list, computed over the SAME queryset
helper (`_apply_entry_filters`), so the totals under a table always
describe that table.

Access:
  * SA / CA — company-wide.
  * STAFF / BUILDING_MANAGER — allowed, but force-scoped to themselves
    by `restrict_entries_to_self`, exactly as the entries list is. An
    employee reading their own weekly total is the ordinary case; there
    is no version of this endpoint in which they see a colleague's.
  * CSV export — SA / CA only. Not a privacy judgement about the
    numbers (a STAFF member may read their own on screen) but about the
    artefact: a downloaded file is the shape that gets forwarded, and
    the export exists for the payroll hand-off, which is an admin task.
  * CUSTOMER_USER — 403 on both.
"""
from __future__ import annotations

from django.http import HttpResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .exports import build_timesheet_summary_csv
from .permissions import IsTimesheetManager, IsTimesheetUser
from .views_common import parse_int_param, resolve_view_company
from .views_entries import _apply_entry_filters, _base_entry_queryset
from .summary import build_summary


def _summary_payload(request):
    """Resolve the company, apply the filters, aggregate.

    The company is pinned to exactly ONE (Sprint 149's model, and the
    `?company=` param a SUPER_ADMIN sends). That is what keeps the
    per-week breakdown unambiguous: two companies could both have a
    2026-W32, and one of them could have it closed while the other did
    not, so a payload spanning both would carry two rows that look
    identical and disagree.
    """
    company = resolve_view_company(
        request.user, parse_int_param(request.query_params.get("company"))
    )
    queryset = _apply_entry_filters(
        _base_entry_queryset(request.user).filter(company=company),
        request.query_params,
    )
    payload = build_summary(queryset)
    payload["company"] = company.id
    payload["company_name"] = company.name
    # Echo the period back so the CSV can label its rows and the UI can
    # caption the panel without re-deriving what it asked for.
    payload["date_from"] = request.query_params.get("date_from") or None
    payload["date_to"] = request.query_params.get("date_to") or None
    return payload


class TimesheetSummaryView(APIView):
    """GET /api/timesheets/summary/ — totals, per hour type, per week."""

    permission_classes = [IsTimesheetUser]

    def get(self, request, *args, **kwargs):
        return Response(_summary_payload(request), status=status.HTTP_200_OK)


class TimesheetSummaryCSVView(APIView):
    """GET /api/timesheets/summary/export.csv — the same payload, CSV."""

    permission_classes = [IsTimesheetManager]

    def get(self, request, *args, **kwargs):
        payload = _summary_payload(request)
        body = build_timesheet_summary_csv(payload)
        period = ""
        if payload["date_from"] or payload["date_to"]:
            period = f"_{payload['date_from'] or ''}_{payload['date_to'] or ''}"
        response = HttpResponse(body, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="employee-hours{period}.csv"'
        )
        return response
