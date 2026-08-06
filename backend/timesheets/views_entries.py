"""
Sprint 152 — time-entry endpoints.

    GET / POST             /api/timesheets/entries/
    GET / PATCH / DELETE   /api/timesheets/entries/<int:entry_id>/

Every queryset resolves through TWO helpers, always in this order:
`filter_time_entries_for` (the tenant floor, H-1) and then
`restrict_entries_to_self` (the privacy floor for non-managers). An
out-of-scope OR someone-else's id is therefore a 404 before any handler
runs — a STAFF member cannot read, edit, delete or even confirm the
existence of a colleague's row.
"""
from __future__ import annotations

from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from config.pagination import StandardResultsSetPagination

from .models import TimeEntry
from .permissions import (
    ERR_TIMESHEET_EMPLOYEE_FORBIDDEN,
    IsTimesheetUser,
    _enforce_timesheet_management,
)
from .scope import (
    filter_time_entries_for,
    is_timesheet_manager,
    restrict_entries_to_self,
)
from .periods import parse_period
from .serializers import TimeEntrySerializer, snapshot_multiplier
from .views_common import parse_int_param
from .weeks import enforce_week_open


def _base_entry_queryset(user):
    qs = TimeEntry.objects.select_related(
        "company", "employee", "hour_type", "building", "created_by"
    )
    return restrict_entries_to_self(user, filter_time_entries_for(user, qs))


def _apply_entry_filters(qs, query_params):
    """Shared `?employee=&date_from=&date_to=&hour_type=&building=
    &company=&iso_year=&iso_week=` filtering.

    Shared with the summary + export views so the table an operator
    reads and the totals underneath it can never be computed over
    different sets. Every filter NARROWS — they are applied to an
    already-scoped queryset, so none of them can widen it.
    """
    employee = parse_int_param(query_params.get("employee"))
    if employee is not None:
        qs = qs.filter(employee_id=employee)
    hour_type = parse_int_param(query_params.get("hour_type"))
    if hour_type is not None:
        qs = qs.filter(hour_type_id=hour_type)
    building = parse_int_param(query_params.get("building"))
    if building is not None:
        qs = qs.filter(building_id=building)
    company = parse_int_param(query_params.get("company"))
    if company is not None:
        qs = qs.filter(company_id=company)
    iso_year = parse_int_param(query_params.get("iso_year"))
    if iso_year is not None:
        qs = qs.filter(iso_year=iso_year)
    iso_week = parse_int_param(query_params.get("iso_week"))
    if iso_week is not None:
        qs = qs.filter(iso_week=iso_week)

    # Sprint 152.2 — PARSED, not passed through. These two used to go
    # straight into `.filter(date__gte=...)`, where an unparseable value
    # raises Django's own `ValidationError` — which DRF does not
    # translate, so it was an unhandled 500 on all three endpoints that
    # share this helper. `parse_period` raises a DRF ValidationError
    # instead (HTTP 400, stable code) and also rejects a reversed range,
    # which previously returned an empty set that reads as "nobody
    # worked" rather than "your dates are the wrong way round".
    #
    # `None` on either side means UNBOUNDED there — absent stays "no
    # filter". No default window is imposed: these endpoints legitimately
    # answer "everything".
    date_from, date_to = parse_period(query_params)
    if date_from is not None:
        qs = qs.filter(date__gte=date_from)
    if date_to is not None:
        qs = qs.filter(date__lte=date_to)
    return qs


def _resolve_write_employee(request, serializer_data_employee):
    """Decide whose entry this is.

    Managers (SA / CA) may name anyone their scope reaches. Everyone
    else is forced to themselves, and naming someone else is a 403 with
    a stable code rather than a silent substitution — writing an entry
    under a different name than the one the client asked for would be
    the kind of "helpful" behaviour that hides a bug for months.

    The 403 leaks nothing: it says "not you", never whether the id names
    a real user.
    """
    user = request.user
    if is_timesheet_manager(user):
        return serializer_data_employee or user
    if (
        serializer_data_employee is not None
        and serializer_data_employee.pk != user.pk
    ):
        raise PermissionDenied(
            detail={
                "detail": "You may only record your own hours.",
                "code": ERR_TIMESHEET_EMPLOYEE_FORBIDDEN,
            }
        )
    return user


class TimeEntryListCreateView(generics.ListCreateAPIView):
    """GET (list) + POST (create) at /api/timesheets/entries/.

    Paginated with the STANDARD page size, not `UnboundedPagination`: a
    year of one company's hours is tens of thousands of rows, and this
    is the endpoint the admin table and the week view both read.
    """

    serializer_class = TimeEntrySerializer
    permission_classes = [IsTimesheetUser]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = _apply_entry_filters(
            _base_entry_queryset(self.request.user), self.request.query_params
        )
        return qs.order_by("-date", "-id")

    def initial(self, request, *args, **kwargs):
        """Force `employee` to self for non-managers BEFORE validation.

        Done here rather than in `perform_create` because the serializer
        needs the final employee to resolve the company, the hour type's
        ownership and the week lock. Running the substitution afterwards
        would validate one employee's request and save another's.
        """
        super().initial(request, *args, **kwargs)
        if request.method == "POST" and not is_timesheet_manager(request.user):
            supplied = request.data.get("employee")
            if supplied not in (None, "") and str(supplied) != str(
                request.user.pk
            ):
                raise PermissionDenied(
                    detail={
                        "detail": "You may only record your own hours.",
                        "code": ERR_TIMESHEET_EMPLOYEE_FORBIDDEN,
                    }
                )

    def perform_create(self, serializer):
        employee = _resolve_write_employee(
            self.request, serializer.validated_data.get("employee")
        )
        company = serializer.validated_data["company"]
        if is_timesheet_manager(self.request.user):
            # A manager writing into a company must be entitled to
            # manage it. A non-manager needs no such check: their own
            # entry is in their own company by construction (the
            # serializer resolved it from THEIR memberships).
            _enforce_timesheet_management(self.request.user, company)
        hour_type = serializer.validated_data["hour_type"]
        serializer.save(
            employee=employee,
            company=company,
            created_by=self.request.user,
            multiplier_snapshot=snapshot_multiplier(hour_type),
        )


class TimeEntryDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET / PATCH / DELETE at /api/timesheets/entries/<id>/."""

    serializer_class = TimeEntrySerializer
    permission_classes = [IsTimesheetUser]
    lookup_url_kwarg = "entry_id"

    def get_queryset(self):
        return _base_entry_queryset(self.request.user)

    def perform_update(self, serializer):
        instance = serializer.instance
        if is_timesheet_manager(self.request.user):
            _enforce_timesheet_management(self.request.user, instance.company)
        employee = _resolve_write_employee(
            self.request,
            serializer.validated_data.get("employee") or instance.employee,
        )
        # Re-snapshot on EVERY update, not only when `hour_type` changes:
        # the rule is "the snapshot reflects the type at write time", and
        # a rule with an exception in it is one somebody eventually
        # forgets. An unchanged type simply writes the same value back.
        hour_type = (
            serializer.validated_data.get("hour_type") or instance.hour_type
        )
        serializer.save(
            employee=employee,
            multiplier_snapshot=snapshot_multiplier(hour_type),
        )

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        if is_timesheet_manager(request.user):
            _enforce_timesheet_management(request.user, instance.company)
        # A closed week refuses deletions exactly as it refuses edits —
        # removing an entry changes the week's totals as much as
        # changing one does.
        enforce_week_open(instance.company_id, instance.date)
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
