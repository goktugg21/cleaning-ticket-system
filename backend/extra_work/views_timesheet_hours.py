"""P-11 B3 — the timesheet's answer for one extra work's job hours.

Two hour concepts, said once, linked once: TIMESHEET hours (who worked
when — `timesheets.TimeEntry`) and BILLABLE hours (what the customer
pays — the quote line's `actual_hours`) stay two things — payroll is
not invoicing — but the Money tab's "Hours worked, to bill" panel
pre-fills from the timesheet instead of asking the operator to restate
what the crew already reported.

The query lives HERE because the import may only run this way:
`timesheets` imports nothing from `tickets` or `extra_work` (its
models module says so at length); the other direction is fine.

The rows are the JOB lines on this request and its spawned tickets:

    source_type=EXTRA_WORK, source_id=<this request>
    source_type=TICKET,     source_id in <spawned ticket ids>

with `planned_date.spawned_tickets_for` as the canonical spawned-ticket
resolution — the same one the money definition uses, so "this job's
hours" cannot mean one thing here and another on the ticket page.

Provider-only, like every money surface: the panel this feeds is
behind the Money tab's own provider gate, and the hour type's
multiplier is a payroll fact a customer has no business reading.
"""
from __future__ import annotations

from decimal import Decimal

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAuthenticatedAndActive

from .planned_date import spawned_tickets_for
from .scoping import scope_extra_work_for
from .views import PROVIDER_ROLES


class ExtraWorkTimesheetHoursView(APIView):
    """GET /api/extra-work/<id>/timesheet-hours/ — the job's timesheet."""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, pk: int, *args, **kwargs):
        if request.user.role not in PROVIDER_ROLES:
            return Response(
                {"detail": "Timesheet hours are a provider-side read."},
                status=status.HTTP_403_FORBIDDEN,
            )
        # Scoped resolution: a request the actor may not see is a 404,
        # never a 403.
        extra_work = get_object_or_404(
            scope_extra_work_for(request.user), pk=pk
        )

        from timesheets.models import HourSource, TimeEntry
        from django.db.models import Q

        ticket_ids = list(
            spawned_tickets_for(extra_work).values_list("id", flat=True)
        )
        rows = (
            TimeEntry.objects.filter(
                Q(
                    source_type=HourSource.EXTRA_WORK,
                    source_id=extra_work.id,
                )
                | Q(source_type=HourSource.TICKET, source_id__in=ticket_ids)
            )
            .select_related("employee", "hour_type")
            .order_by("date", "employee_id", "id")
        )

        entries = []
        total = Decimal("0")
        for row in rows:
            total += row.hours
            entries.append(
                {
                    "employee": row.employee_id,
                    "employee_name": (
                        row.employee.full_name or row.employee.email
                    ),
                    "date": row.date.isoformat(),
                    "hours": f"{row.hours:.2f}",
                    "hour_type": row.hour_type_id,
                    "hour_type_name": row.hour_type.name,
                    "hour_type_multiplier": f"{row.multiplier_snapshot:.2f}",
                    "source_type": row.source_type,
                    "source_id": row.source_id,
                }
            )
        return Response(
            {"entries": entries, "total_hours": f"{total:.2f}"},
            status=status.HTTP_200_OK,
        )
