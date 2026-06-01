"""Planned-work viewsets (Sprint 11B Batch 3).

Provider-only API. `RecurringJobViewSet` is a full ModelViewSet over the
recurring-job template; `PlannedOccurrenceViewSet` is read-only with
skip / cancel lifecycle actions. Both gate on the provider-management
permission classes and scope their querysets through the planned-work
scope helpers (STAFF / CUSTOMER_USER see nothing). Lifecycle actions
surface `PlannedWorkError` as a stable `{detail, code}` 400, mirroring
the ticket viewset's action shape.
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .constants import DEFAULT_GENERATION_DAYS_AHEAD, MAX_GENERATION_DAYS_AHEAD
from .errors import PlannedWorkError
from .generation import generate_occurrences
from .lifecycle import cancel_occurrence, skip_occurrence
from .models import RecurringJob
from .permissions import CanManagePlannedOccurrence, CanManageRecurringJob
from .scoping import scope_planned_occurrences_for, scope_recurring_jobs_for
from .serializers import (
    OccurrenceActionSerializer,
    PlannedOccurrenceSerializer,
    RecurringJobReadSerializer,
    RecurringJobWriteSerializer,
)


class RecurringJobViewSet(viewsets.ModelViewSet):
    permission_classes = [CanManageRecurringJob]

    def get_queryset(self):
        return (
            scope_recurring_jobs_for(self.request.user)
            .select_related("company", "building", "customer", "created_by")
            .prefetch_related("default_staff", "default_managers")
        )

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return RecurringJobWriteSerializer
        return RecurringJobReadSerializer

    def destroy(self, request, *args, **kwargs):
        # Soft-archive instead of hard delete. PlannedOccurrence PROTECTs
        # this job, so a hard delete would fail once occurrences exist;
        # archiving preserves occurrences for reporting.
        job = self.get_object()
        job.is_active = False
        job.archived_at = timezone.now()
        job.save(update_fields=["is_active", "archived_at", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request, pk=None):
        job = self.get_object()
        job.is_active = False
        job.archived_at = timezone.now()
        job.save(update_fields=["is_active", "archived_at", "updated_at"])
        return Response(
            RecurringJobReadSerializer(
                job, context={"request": request}
            ).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="unarchive")
    def unarchive(self, request, pk=None):
        job = self.get_object()
        job.is_active = True
        job.archived_at = None
        job.save(update_fields=["is_active", "archived_at", "updated_at"])
        return Response(
            RecurringJobReadSerializer(
                job, context={"request": request}
            ).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="generate")
    def generate(self, request, pk=None):
        """Materialize occurrences for THIS job within the horizon and
        spawn their operational tickets. Idempotent. Returns counts.
        """
        job = self.get_object()
        # Coerce + bound days_ahead: an uncast value reaches
        # `today + timedelta(days=...)` and a string would 500; an
        # unbounded huge int would mass-materialize occurrences + tickets.
        raw = request.data.get("days_ahead", DEFAULT_GENERATION_DAYS_AHEAD)
        try:
            days_ahead = int(raw)
        except (TypeError, ValueError):
            return Response(
                {
                    "detail": "days_ahead must be an integer.",
                    "code": "invalid_days_ahead",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if days_ahead < 1 or days_ahead > MAX_GENERATION_DAYS_AHEAD:
            return Response(
                {
                    "detail": "days_ahead must be between 1 and %d."
                    % MAX_GENERATION_DAYS_AHEAD,
                    "code": "invalid_days_ahead",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        counts = generate_occurrences(
            days_ahead=days_ahead,
            actor=request.user,
            jobs=RecurringJob.objects.filter(pk=job.pk),
        )
        return Response(counts, status=status.HTTP_200_OK)


class PlannedOccurrenceViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [CanManagePlannedOccurrence]
    serializer_class = PlannedOccurrenceSerializer

    def get_queryset(self):
        qs = scope_planned_occurrences_for(self.request.user).select_related(
            "recurring_job", "company", "building", "customer"
        )
        params = self.request.query_params

        status_value = params.get("status")
        if status_value:
            qs = qs.filter(status=status_value)

        building = params.get("building")
        if building:
            qs = qs.filter(building_id=building)

        customer = params.get("customer")
        if customer:
            qs = qs.filter(customer_id=customer)

        recurring_job = params.get("recurring_job")
        if recurring_job:
            qs = qs.filter(recurring_job_id=recurring_job)

        date_from = params.get("date_from")
        if date_from:
            qs = qs.filter(planned_date__gte=date_from)

        date_to = params.get("date_to")
        if date_to:
            qs = qs.filter(planned_date__lte=date_to)

        return qs

    @action(detail=True, methods=["post"], url_path="skip")
    def skip(self, request, pk=None):
        occurrence = self.get_object()
        serializer = OccurrenceActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            skip_occurrence(
                occurrence,
                actor=request.user,
                reason=serializer.validated_data["reason"],
            )
        except PlannedWorkError as exc:
            return Response(
                {"detail": str(exc), "code": exc.code},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            PlannedOccurrenceSerializer(
                occurrence, context={"request": request}
            ).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        occurrence = self.get_object()
        serializer = OccurrenceActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            cancel_occurrence(
                occurrence,
                actor=request.user,
                reason=serializer.validated_data["reason"],
            )
        except PlannedWorkError as exc:
            return Response(
                {"detail": str(exc), "code": exc.code},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            PlannedOccurrenceSerializer(
                occurrence, context={"request": request}
            ).data,
            status=status.HTTP_200_OK,
        )
