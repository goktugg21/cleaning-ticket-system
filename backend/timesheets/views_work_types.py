"""
Sprint 168 §3 — work-type catalog endpoints.

    GET  / POST            /api/timesheets/work-types/
    GET  / PATCH / DELETE  /api/timesheets/work-types/<int:work_type_id>/
    POST                   /api/timesheets/work-types/standard-set/

Deliberately the `views_hour_types` shape, method for method: reads open
to every provider-side role (a picker needs the active list), writes SA /
CA only through `IsTimesheetManager` plus
`_enforce_timesheet_management` against the row's OWNING company — not
the actor's, which is the check that stops a two-company admin writing
into the wrong one.

CUSTOMER_* is 403'd on every method by `IsTimesheetUser`.
"""
from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import Count, ProtectedError
from django.db.models.functions import Lower, Trim
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from audit import context as audit_context
from config.pagination import UnboundedPagination

from .models import WorkType
from .permissions import (
    IsTimesheetManager,
    IsTimesheetUser,
    _enforce_timesheet_management,
)
from .scope import filter_work_types_for
from .serializers_work_types import (
    ERR_WORK_TYPE_NAME_NOT_UNIQUE,
    STANDARD_WORK_TYPES,
    WorkTypeSerializer,
    WorkTypeStandardSetSerializer,
    normalise_work_type_name,
)
from .views_common import parse_bool_param, resolve_target_company


ERR_WORK_TYPE_PROTECTED = "work_type_protected"


def _annotate_usage(queryset):
    """One aggregate for the whole page: how many contract-hours rows
    use this type. `ContractHours.work_type` is PROTECT, so a type in
    use is permanently undeletable and the UI needs the number to know
    whether to offer Delete at all.
    """
    return queryset.annotate(
        annotated_usage_count=Count("contract_hours", distinct=True)
    )


class WorkTypeListCreateView(generics.ListCreateAPIView):
    """GET (list) + POST (create) at /api/timesheets/work-types/.

    `?company=<id>` and `?is_active=true|false` both NARROW an already
    scoped queryset — neither can widen it, which is the H-1 shape every
    filter in this app follows.

    Unpaginated: this is a picker source, and a catalog of work kinds is
    a handful of rows per company. It is NOT a shared list endpoint with
    its own pagination UI, so `UnboundedPagination` here costs no other
    caller anything (the Sprint 134/135 lesson, applied by choosing the
    right endpoint rather than loosening a shared one).
    """

    serializer_class = WorkTypeSerializer
    permission_classes = [IsTimesheetUser]
    pagination_class = UnboundedPagination

    def get_queryset(self):
        queryset = filter_work_types_for(
            self.request.user, WorkType.objects.select_related("company")
        )
        company = self.request.query_params.get("company")
        if company:
            queryset = queryset.filter(company_id=company)
        is_active = parse_bool_param(self.request.query_params.get("is_active"))
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        return _annotate_usage(queryset)

    def create(self, request, *args, **kwargs):
        if not IsTimesheetManager().has_permission(request, self):
            return Response(
                {"detail": "forbidden"}, status=status.HTTP_403_FORBIDDEN
            )
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        company = serializer.validated_data.get("company")
        _enforce_timesheet_management(self.request.user, company)
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError as exc:
            # Narrow: only OUR uniqueness constraint is turned into a
            # field error. Anything else is a real fault and must not be
            # reported to the operator as "that name is taken".
            if "uniq_work_type_name_per_company_ci" not in str(exc):
                raise
            raise generics.ValidationError(
                {"name": [ERR_WORK_TYPE_NAME_NOT_UNIQUE]}
            ) from exc


class WorkTypeDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET / PATCH / DELETE one work type.

    DELETE is offered but usually refused: `ContractHours.work_type` is
    PROTECT, so a type any agreement references cannot be removed. The
    refusal is a 409 with `work_type_protected` rather than a 500, and
    the operator's route is to ARCHIVE it — which keeps every existing
    agreement reading exactly as it did.
    """

    serializer_class = WorkTypeSerializer
    permission_classes = [IsTimesheetManager]
    lookup_url_kwarg = "work_type_id"

    def get_queryset(self):
        return _annotate_usage(
            filter_work_types_for(
                self.request.user, WorkType.objects.select_related("company")
            )
        )

    def perform_update(self, serializer):
        _enforce_timesheet_management(
            self.request.user, serializer.instance.company
        )
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError as exc:
            if "uniq_work_type_name_per_company_ci" not in str(exc):
                raise
            raise generics.ValidationError(
                {"name": [ERR_WORK_TYPE_NAME_NOT_UNIQUE]}
            ) from exc

    def perform_destroy(self, instance):
        _enforce_timesheet_management(self.request.user, instance.company)
        try:
            with transaction.atomic():
                instance.delete()
        except ProtectedError as exc:
            raise generics.ValidationError(
                {"detail": ERR_WORK_TYPE_PROTECTED}
            ) from exc


class WorkTypeStandardSetView(APIView):
    """POST /api/timesheets/work-types/standard-set/ — offer the four
    reference kinds to a company that has none.

    The `hour-types/standard-set/` shape, and idempotent for the same
    reason: the skip test is the same `Lower(Trim(...))` comparison the
    uniqueness constraint uses, so "already there" means the same thing
    to this view and to the database. Pressing the button twice creates
    nothing the second time.

    One transaction, so a partial set can never be left behind, and the
    response reports `created` and `skipped` BY NAME — "4 added" and "4
    already there" are the two outcomes an operator needs told apart,
    and a bare count cannot tell them.

    These four are OFFERED, not imposed: a company is free to delete
    them and name its own. The button exists because a company with an
    empty catalog cannot create anything at all, which is the state
    every new tenant starts in.
    """

    permission_classes = [IsTimesheetManager]

    def post(self, request, *args, **kwargs):
        payload = WorkTypeStandardSetSerializer(
            data=request.data, context={"request": request}
        )
        payload.is_valid(raise_exception=True)
        target_company = resolve_target_company(
            request.user, payload.validated_data.get("company")
        )
        _enforce_timesheet_management(request.user, target_company)

        existing = set(
            WorkType.objects.filter(company=target_company)
            .annotate(normalised=Lower(Trim("name")))
            .values_list("normalised", flat=True)
        )

        created, skipped = [], []
        audit_context.set_current_reason("work_type_standard_set")
        try:
            with transaction.atomic():
                for name, sort_order in STANDARD_WORK_TYPES:
                    if normalise_work_type_name(name) in existing:
                        skipped.append(name)
                        continue
                    # save() per row, not bulk_create: the audit
                    # receivers are post_save, and bulk_create does not
                    # fire them (H-10).
                    WorkType.objects.create(
                        company=target_company,
                        name=name,
                        sort_order=sort_order,
                    )
                    created.append(name)
        finally:
            audit_context.set_current_reason(None)

        return Response(
            {"created": created, "skipped": skipped},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
