"""W7 — the planned-vs-worked panel's endpoint.

    GET /api/reports/extra-work/<id>/planned-vs-actual/

Its own module beside `views_extra_work_hours.py` for the reason
CLAUDE.md gives: `reports/views.py` is already 50KB and app-scoped files
are the convention here.

## Two doors into one job, because STAFF have only one of them

Resolving "may this caller read this job" cannot go through
`extra_work.scoping.scope_extra_work_for` alone. That helper returns
NOTHING for STAFF, deliberately — the P0 staff-privacy decision keeps a
worker away from the parent Extra Work record, where the commercial
side of the job lives. A worker's operational view of the same work is
the TICKET it spawned, and `accounts.scoping.scope_tickets_for` is the
existing authority on which tickets that is.

So the job resolves through either door, and neither door widens the
other:

  * provider management reach it as an Extra Work, as they always have;
  * anybody else reaches it only if a ticket they may already see
    points at it.

A caller with neither gets 404 — the same answer a fictional id gives,
which is H-1's rule about never confirming a record exists across a
tenant boundary.

**The door decides admission; the rows decide content.** Getting in
through a ticket buys nothing but the panel: `planned_vs_actual_report`
narrows a non-manager to their own line, so a STAFF user with
building-wide read on a job they never worked gets an empty panel
rather than the crew's hours.

## No money passes through here

`planned_vs_actual_report` computes none, and this view adds none.
That absence is what lets STAFF through
`reports.permissions.IsPlannedHoursConsumer` at all — see that class.
"""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import IsPlannedHoursConsumer


class ExtraWorkPlannedVsActualView(APIView):
    """GET /api/reports/extra-work/<id>/planned-vs-actual/."""

    permission_classes = [IsAuthenticated, IsPlannedHoursConsumer]

    def get(self, request, extra_work_id: int):
        # Imported inside the method for the reason the other
        # cross-module reports views give: `reports` loads early, and a
        # module-level import of `extra_work` / `tickets` pulls their
        # whole model graphs into every request path touching this app.
        from accounts.scoping import scope_tickets_for
        from extra_work.models import ExtraWorkRequest
        from extra_work.scoping import scope_extra_work_for

        from .planned_vs_actual import planned_vs_actual_report

        extra_work = (
            scope_extra_work_for(request.user)
            .only("id", "company_id")
            .filter(pk=extra_work_id)
            .first()
        )
        if extra_work is None:
            # The worker's door. `scope_tickets_for` has already decided
            # which tickets this caller may see; if one of them IS this
            # job's operational ticket, the panel opens.
            reachable = (
                scope_tickets_for(request.user)
                .filter(extra_work_request_id=extra_work_id)
                .exists()
            )
            if reachable:
                extra_work = (
                    ExtraWorkRequest.objects.filter(
                        pk=extra_work_id, deleted_at__isnull=True
                    )
                    .only("id", "company_id")
                    .first()
                )
        if extra_work is None:
            from rest_framework import status

            return Response(
                {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(planned_vs_actual_report(request.user, extra_work))
