"""
Sprint 167 §3 / §4 — the standing hours agreement's endpoints.

    GET  / POST            /api/timesheets/contract-hours/
    GET  / PATCH / DELETE  /api/timesheets/contract-hours/<int:pk>/
    POST                   /api/timesheets/contract-hours/bulk/
    POST                   /api/timesheets/contract-hours/<int:pk>/status/

Reads admit every provider-side role (`IsTimesheetUser`); writes are
SA / CA (`IsTimesheetManager`), the same split the hour-type catalog
uses. CUSTOMER_* is 403'd on every method.

**An APPROVED row is not editable.** PATCH on one is a 400, and the way
to change an approved agreement is a NEW row from a new `valid_from` —
the discipline `CustomerServicePrice` and `ContractRevision` already
use. The only thing that may move on an approved row is its status,
through the dedicated status endpoint, which is how a reopen happens.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.pagination import UnboundedPagination

from .contract_hours import in_force_between, in_force_on
from .models import ContractHours, ContractHoursStatus
from .permissions import IsTimesheetManager, IsTimesheetUser
from .scope import filter_contract_hours_for, restrict_contract_hours_to_self
from .serializers_contract_hours import (
    ContractHoursBulkSerializer,
    ContractHoursSerializer,
)
from .views_common import parse_int_param


ERR_APPROVED_IMMUTABLE = "contract_hours_approved_immutable"
ERR_BAD_TRANSITION = "contract_hours_bad_transition"


def _base_queryset(user):
    """The two scoping helpers, applied as the PAIR they are.

    W12 — `restrict_contract_hours_to_self` was missing here.
    `filter_contract_hours_for` answers the tenant question (H-1) and
    nothing else, so with only that applied, GET was
    `IsTimesheetUser` — every provider-side role — over the whole
    company's standing agreements: a STAFF member could read every
    colleague's contracted weekly pattern, building and hour type
    through this endpoint. That is precisely the defect Sprint 182 §1
    found in `reports`, which is why the self-restriction helper
    already existed and was already documented as one half of a pair.
    It had a second caller and now has its third.
    """
    return restrict_contract_hours_to_self(
        user,
        filter_contract_hours_for(
            user,
            ContractHours.objects.select_related(
                "employee", "building", "hour_type", "company"
            ),
        ),
    )


class ContractHoursListCreateView(generics.ListCreateAPIView):
    """GET (list) + POST (create).

    `UnboundedPagination` because a company's standing agreements are
    bounded by domain reality — one row per (employee, building, hour
    type) window, not a growing event log — and the screen shows them
    as one editable table. The Sprint 134/135 rule still applies: this
    is a NEW endpoint choosing its own shape, not a loosening of one
    other callers depend on.
    """

    serializer_class = ContractHoursSerializer
    pagination_class = UnboundedPagination

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsTimesheetUser()]
        return [IsTimesheetManager()]

    def get_queryset(self):
        qs = _base_queryset(self.request.user)
        params = self.request.query_params

        company = parse_int_param(params.get("company"))
        if company is not None:
            qs = qs.filter(company_id=company)
        building = parse_int_param(params.get("building"))
        if building is not None:
            qs = qs.filter(building_id=building)
        employee = parse_int_param(params.get("employee"))
        if employee is not None:
            qs = qs.filter(employee_id=employee)
        hour_type = parse_int_param(params.get("hour_type"))
        if hour_type is not None:
            qs = qs.filter(hour_type_id=hour_type)
        state = (params.get("status") or "").strip().upper()
        if state:
            if state not in ContractHoursStatus.values:
                # An unrecognised state yields nothing rather than being
                # ignored: silently returning everything reads as "the
                # filter is off" when the operator believes it is on.
                return qs.none()
            qs = qs.filter(status=state)

        valid_on = params.get("valid_on")
        if valid_on:
            from datetime import date

            try:
                qs = in_force_on(qs, date.fromisoformat(valid_on))
            except ValueError:
                return qs.none()

        # Sprint 168 §2 — a WINDOW, not a point. The approval screen
        # reviews a week, and an agreement starting on the Tuesday
        # belongs to that week; `valid_on=<monday>` dropped it.
        window_start = params.get("valid_between_start")
        window_end = params.get("valid_between_end")
        if window_start and window_end:
            from datetime import date

            try:
                qs = in_force_between(
                    qs,
                    date.fromisoformat(window_start),
                    date.fromisoformat(window_end),
                )
            except ValueError:
                return qs.none()
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ContractHoursDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ContractHoursSerializer

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsTimesheetUser()]
        return [IsTimesheetManager()]

    def get_queryset(self):
        return _base_queryset(self.request.user)

    def perform_update(self, serializer):
        if serializer.instance.is_locked:
            raise serializers.ValidationError(
                {
                    "status": [
                        serializers.ErrorDetail(
                            "An approved agreement cannot be edited. Create "
                            "a new one from a new valid-from date instead.",
                            code=ERR_APPROVED_IMMUTABLE,
                        )
                    ]
                }
            )
        serializer.save()

    def perform_destroy(self, instance):
        if instance.is_locked:
            raise serializers.ValidationError(
                {
                    "status": [
                        serializers.ErrorDetail(
                            "An approved agreement cannot be deleted.",
                            code=ERR_APPROVED_IMMUTABLE,
                        )
                    ]
                }
            )
        instance.delete()


class ContractHoursStatusView(APIView):
    """POST a `status` to move one row between DRAFT / SAVED / APPROVED.

    A dedicated endpoint rather than a PATCH field, so the transition
    rules live in one place and an approved row can still be REOPENED
    while remaining immutable in every other respect.
    """

    permission_classes = [IsTimesheetManager]

    ALLOWED = {
        ContractHoursStatus.DRAFT: {ContractHoursStatus.SAVED},
        ContractHoursStatus.SAVED: {
            ContractHoursStatus.APPROVED,
            ContractHoursStatus.DRAFT,
        },
        # Reopening is deliberate: the alternative is that one wrong
        # approval is permanent and the only escape is a superseding row
        # whose date lies about when the agreement changed.
        ContractHoursStatus.APPROVED: {ContractHoursStatus.SAVED},
    }

    def post(self, request, pk):
        row = _base_queryset(request.user).filter(pk=pk).first()
        if row is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        target = (request.data.get("status") or "").strip().upper()
        if target not in ContractHoursStatus.values:
            return Response(
                {"status": [ERR_BAD_TRANSITION]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if target not in self.ALLOWED[row.status]:
            return Response(
                {
                    "status": [
                        f"{row.status} -> {target} is not a permitted "
                        f"transition."
                    ],
                    "code": ERR_BAD_TRANSITION,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        row.status = target
        if target == ContractHoursStatus.APPROVED:
            row.approved_by = request.user
            row.approved_at = timezone.now()
        else:
            # Reopening clears the approval, so the row never claims to
            # have been approved by someone who has since had it undone.
            row.approved_by = None
            row.approved_at = None
        # `save()` not `update()`: the audit trail for every transition
        # comes from the post_save receiver, and a queryset update fires
        # none of them (H-10).
        row.save(
            update_fields=["status", "approved_by", "approved_at", "updated_at"]
        )
        return Response(ContractHoursSerializer(row).data)


class ContractHoursBulkView(APIView):
    """POST several (employee, building) pairs at once — the Bulk
    assignment dialog.

    One transaction: a bulk assignment that half-applied would leave the
    operator guessing which pairs took.
    """

    permission_classes = [IsTimesheetManager]

    def post(self, request):
        serializer = ContractHoursBulkSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            created = serializer.save(created_by=request.user)
        # W10 — the answer takes effect immediately, on the week the
        # operator is standing in. Every OTHER week fills when it is
        # opened (`entries/fill-week/`), which is what keeps this
        # bounded: a `valid_from` two years back must not turn one
        # assignment into a hundred weeks of writes.
        _fill_current_week(created, request.user)
        return Response(
            ContractHoursSerializer(created, many=True).data,
            status=status.HTTP_201_CREATED,
        )


def _fill_current_week(rows, actor) -> None:
    """Fill this week for every company an auto-fill row just landed in.

    Per COMPANY, not per row: `fill_week` already walks that company's
    agreements, so calling it once per created row would do the same
    work N times for the same answer.
    """
    from datetime import date as _date

    from .fill import fill_week

    companies = {r.company_id for r in rows if r.auto_fill}
    if not companies:
        return
    iso_year, iso_week, _ = _date.today().isocalendar()
    for company_id in companies:
        fill_week(company_id, iso_year, iso_week, actor=actor)
