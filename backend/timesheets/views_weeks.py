"""
Sprint 152 — week close / reopen.

    GET  /api/timesheets/weeks/          list the CLOSED weeks
    GET  /api/timesheets/weeks/status/   is ONE week open or closed?
    POST /api/timesheets/weeks/close/
    POST /api/timesheets/weeks/reopen/

`status/` exists because the list cannot answer the question the "Mijn
uren" page actually asks. Absence of a row means OPEN (see
`models.WeekLock`), so an EMPTY week — no entries, no lock — has nothing
in either collection to hang a lock notice off. `status/` names a week
and gets a definite answer, which is what a week picker needs on every
navigation.

Close / reopen are SA / CA only. Reopen DELETES the lock row; the
AuditLog DELETE entry is the reopen trail.
"""
from __future__ import annotations

from django.db import IntegrityError, transaction
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from audit import context as audit_context
from config.pagination import UnboundedPagination

from .models import WeekLock
from .periods import iso_week_exists
from .permissions import (
    IsTimesheetManager,
    IsTimesheetUser,
    _enforce_timesheet_management,
)
from .scope import filter_week_locks_for
from .serializers import WeekLockSerializer
from .views_common import (
    parse_int_param,
    resolve_target_company,
    resolve_view_company,
)


ERR_WEEK_INVALID = "week_invalid"
ERR_WEEK_ALREADY_CLOSED = "week_already_closed"
ERR_WEEK_NOT_CLOSED = "week_not_closed"


def _parse_week(data):
    """Read and validate `iso_year` / `iso_week` from a payload.

    ISO weeks run 1..53, and a year bound is applied too — not because a
    wider one would break anything, but because a typo'd `iso_year` of
    20260 would silently create a lock nobody can ever find again.

    Sprint 152.2 — the range check alone was NOT enough. Most years have
    52 ISO weeks and only some have 53 (2025 has 52; 2026 has 53), so
    `1 <= iso_week <= 53` accepted `2025-W53` — a week that does not
    exist. Closing it created a `WeekLock` no `TimeEntry` could ever
    belong to: invisible in the entries list, permanently listed as a
    closed week, and locking nothing. `iso_week_exists` asks
    `date.fromisocalendar` instead of guessing, so week 53 is accepted
    exactly in the years that have one.
    """
    iso_year = parse_int_param(data.get("iso_year"))
    iso_week = parse_int_param(data.get("iso_week"))
    if (
        iso_year is None
        or iso_week is None
        or not (1970 <= iso_year <= 2200)
        or not (1 <= iso_week <= 53)
        or not iso_week_exists(iso_year, iso_week)
    ):
        raise serializers.ValidationError(
            {
                "iso_week": [
                    serializers.ErrorDetail(
                        "iso_year and iso_week must together name a real "
                        "ISO week (note not every year has a week 53).",
                        code=ERR_WEEK_INVALID,
                    )
                ]
            }
        )
    return iso_year, iso_week


class WeekLockListView(generics.ListAPIView):
    """GET /api/timesheets/weeks/ — the CLOSED weeks in scope.

    Open to every provider-side role: a STAFF member is entitled to know
    which of their own weeks are shut. The rows carry no personal data —
    a company, a week number, and who closed it.

    `?company=<id>` and `?iso_year=<y>` NARROW only; the scope filter
    runs last.
    """

    serializer_class = WeekLockSerializer
    permission_classes = [IsTimesheetUser]
    pagination_class = UnboundedPagination

    def get_queryset(self):
        qs = WeekLock.objects.select_related("company", "closed_by").all()
        company = parse_int_param(self.request.query_params.get("company"))
        if company is not None:
            qs = qs.filter(company_id=company)
        iso_year = parse_int_param(self.request.query_params.get("iso_year"))
        if iso_year is not None:
            qs = qs.filter(iso_year=iso_year)
        qs = filter_week_locks_for(self.request.user, qs)
        return qs.order_by("-iso_year", "-iso_week", "id")


class WeekStatusView(APIView):
    """GET /api/timesheets/weeks/status/?iso_year=&iso_week=&company=

    Returns `is_closed` for one company-week, plus the lock's details
    when there is one. Open to every provider-side role.
    """

    permission_classes = [IsTimesheetUser]

    def get(self, request, *args, **kwargs):
        iso_year, iso_week = _parse_week(request.query_params)
        company = resolve_view_company(
            request.user,
            parse_int_param(request.query_params.get("company")),
        )
        lock = (
            WeekLock.objects.select_related("company", "closed_by")
            .filter(company=company, iso_year=iso_year, iso_week=iso_week)
            .first()
        )
        return Response(
            {
                "company": company.id,
                "company_name": company.name,
                "iso_year": iso_year,
                "iso_week": iso_week,
                "is_closed": lock is not None,
                "lock": WeekLockSerializer(lock).data if lock else None,
            },
            status=status.HTTP_200_OK,
        )


class WeekCloseView(APIView):
    """POST /api/timesheets/weeks/close/ — close one company-week.

    Closing an EMPTY week is allowed and is not a no-op: it is how a
    company states "nobody worked that week and we are done with it",
    and it blocks a later back-dated entry from appearing in a period
    already reported on.
    """

    permission_classes = [IsTimesheetManager]

    def post(self, request, *args, **kwargs):
        iso_year, iso_week = _parse_week(request.data)
        company = resolve_target_company(
            request.user, self._supplied_company(request)
        )
        _enforce_timesheet_management(request.user, company)

        audit_context.set_current_reason("timesheet_week_close")
        try:
            with transaction.atomic():
                lock = WeekLock.objects.create(
                    company=company,
                    iso_year=iso_year,
                    iso_week=iso_week,
                    closed_by=request.user,
                )
        except IntegrityError:
            # Already closed. A 400 rather than a silent 200: the
            # operator's mental model ("I am closing this now") is wrong
            # and the response should say so.
            return Response(
                {
                    "detail": "This week is already closed.",
                    "code": ERR_WEEK_ALREADY_CLOSED,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            WeekLockSerializer(lock).data, status=status.HTTP_201_CREATED
        )

    @staticmethod
    def _supplied_company(request):
        from companies.models import Company

        company_id = parse_int_param(request.data.get("company"))
        if company_id is None:
            return None
        return Company.objects.filter(id=company_id).first()


class WeekReopenView(APIView):
    """POST /api/timesheets/weeks/reopen/ — DELETE the lock row.

    Deliberate and owner-approved: mistakes and late sick-leave entries
    are routine, so a close has to be reversible, and the invariant
    "absence of a row = open" leaves no other way to express it. The
    AuditLog DELETE row — actor, timestamp, the company-week in its
    payload — is the reopen trail.
    """

    permission_classes = [IsTimesheetManager]

    def post(self, request, *args, **kwargs):
        iso_year, iso_week = _parse_week(request.data)
        company = resolve_target_company(
            request.user, WeekCloseView._supplied_company(request)
        )
        _enforce_timesheet_management(request.user, company)

        lock = WeekLock.objects.filter(
            company=company, iso_year=iso_year, iso_week=iso_week
        ).first()
        if lock is None:
            return Response(
                {
                    "detail": "This week is not closed.",
                    "code": ERR_WEEK_NOT_CLOSED,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        audit_context.set_current_reason("timesheet_week_reopen")
        with transaction.atomic():
            lock.delete()
        return Response(
            {
                "company": company.id,
                "iso_year": iso_year,
                "iso_week": iso_week,
                "is_closed": False,
            },
            status=status.HTTP_200_OK,
        )
