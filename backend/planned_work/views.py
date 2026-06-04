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

import datetime

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .constants import DEFAULT_GENERATION_DAYS_AHEAD, MAX_GENERATION_DAYS_AHEAD
from .errors import PlannedWorkError
from .generation import generate_occurrences
from .lifecycle import cancel_occurrence, skip_occurrence
from .models import PlannedOccurrenceStatus, RecurringJob
from .permissions import CanManagePlannedOccurrence, CanManageRecurringJob
from .scoping import scope_planned_occurrences_for, scope_recurring_jobs_for
from .serializers import (
    OccurrenceActionSerializer,
    PlannedOccurrenceOverrideSerializer,
    PlannedOccurrenceSerializer,
    RecurringJobReadSerializer,
    RecurringJobWriteSerializer,
)


# All seven PlannedOccurrenceStatus values, in enum order. The rollup pads
# its histogram with these keys so the response shape is stable even when a
# status has zero rows in scope.
_ALL_OCCURRENCE_STATUSES = [s.value for s in PlannedOccurrenceStatus]


def _parse_rollup_date(raw: str, field_name: str) -> datetime.date:
    try:
        return datetime.datetime.strptime(raw, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ValidationError(
            {
                "detail": "Invalid date for '%s'. Expected YYYY-MM-DD."
                % field_name,
                "code": "invalid_date",
            }
        )


def _parse_rollup_id(raw: str, field_name: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValidationError(
            {
                "detail": "'%s' must be an integer." % field_name,
                "code": "invalid_id",
            }
        )


class RecurringJobViewSet(viewsets.ModelViewSet):
    permission_classes = [CanManageRecurringJob]

    def get_queryset(self):
        return (
            scope_recurring_jobs_for(self.request.user)
            .select_related("company", "building", "customer", "created_by")
            .prefetch_related("default_staff", "default_managers", "windows")
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
        # Refuse generation on an archived job. This per-job action passes
        # an explicit `jobs=` queryset to generate_occurrences, which
        # BYPASSES the is_active / archived_at filter that the daily
        # generator applies only when `jobs is None` — so without this
        # guard a generate on an archived job would spawn occurrences +
        # tickets for archived work. The frontend hides the trigger for
        # archived jobs; this is the authoritative server-side guard.
        if not job.is_active or job.archived_at is not None:
            return Response(
                {
                    "detail": "Cannot generate occurrences for an archived "
                    "recurring job.",
                    "code": "recurring_job_archived",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
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
            "recurring_job", "company", "building", "customer", "source_window"
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

    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        """Sprint 14A — planned-occurrence status rollup.

        Aggregates the scoped occurrence set by status over an optional
        `planned_date` window (date_from / date_to, inclusive), with
        optional building_id / customer_id narrowing. The window and the
        id filters are applied INSIDE `scope_planned_occurrences_for`, so a
        foreign / out-of-scope id can only ever yield zero rows — it can
        never 403 or leak another tenant's data (H-1 / H-2).

        `by_status` always carries all seven PlannedOccurrenceStatus keys
        (zero-padded). STAFF / CUSTOMER_USER never reach this code — the
        IsProviderManager permission 403s them before dispatch (the
        planned-work surface is provider-only).

        Answers "this month, how many planned jobs completed / missed /
        rescheduled?" via date_from / date_to on the immutable
        planned_date + by_status.
        """
        params = request.query_params

        date_from = None
        raw_from = params.get("date_from")
        if raw_from:
            date_from = _parse_rollup_date(raw_from, "date_from")

        date_to = None
        raw_to = params.get("date_to")
        if raw_to:
            date_to = _parse_rollup_date(raw_to, "date_to")

        if date_from is not None and date_to is not None and date_from > date_to:
            raise ValidationError(
                {
                    "detail": "date_from must not be after date_to.",
                    "code": "invalid_date_range",
                }
            )

        building_id = None
        raw_building = params.get("building_id")
        if raw_building:
            building_id = _parse_rollup_id(raw_building, "building_id")

        customer_id = None
        raw_customer = params.get("customer_id")
        if raw_customer:
            customer_id = _parse_rollup_id(raw_customer, "customer_id")

        # Anchor on the scoped queryset — never on a caller-supplied id —
        # so the filters narrow WITHIN the actor's visibility envelope.
        qs = scope_planned_occurrences_for(request.user)
        if date_from is not None:
            qs = qs.filter(planned_date__gte=date_from)
        if date_to is not None:
            qs = qs.filter(planned_date__lte=date_to)
        if building_id is not None:
            qs = qs.filter(building_id=building_id)
        if customer_id is not None:
            qs = qs.filter(customer_id=customer_id)

        by_status = {s: 0 for s in _ALL_OCCURRENCE_STATUSES}
        for row in qs.values("status").annotate(c=Count("id")):
            by_status[row["status"]] = row["c"]
        total = sum(by_status.values())

        # Per-building breakdown: one GROUP BY with conditional counts per
        # status. Buildings with no rows in scope are skipped naturally
        # (no padding rows), but every row that DOES appear carries all
        # seven status keys for a stable per-row shape.
        status_aggregates = {
            "count_%s" % s: Count("id", filter=Q(status=s))
            for s in _ALL_OCCURRENCE_STATUSES
        }
        by_building = [
            {
                "building_id": row["building_id"],
                "building_name": row["building__name"],
                "total": row["row_total"],
                "by_status": {
                    s: row["count_%s" % s] for s in _ALL_OCCURRENCE_STATUSES
                },
            }
            for row in qs.values("building_id", "building__name")
            .annotate(row_total=Count("id"), **status_aggregates)
            .order_by("building__name", "building_id")
        ]

        return Response(
            {
                "from": date_from.isoformat() if date_from else None,
                "to": date_to.isoformat() if date_to else None,
                "filters": {
                    "building_id": building_id,
                    "customer_id": customer_id,
                },
                "by_status": by_status,
                "total": total,
                "by_building": by_building,
                "generated_at": timezone.now().isoformat(),
            },
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

    @action(detail=True, methods=["patch"], url_path="override")
    def override(self, request, pk=None):
        """Sprint 12 — provider-manager per-occurrence override of the
        snapshotted pricing + schedule window (e.g. "this date after
        09:00", or a one-off custom price).

        Provider-only: `CanManagePlannedOccurrence` already 403s STAFF /
        CUSTOMER_USER (has_permission) and object-scopes to the actor's
        visibility (`get_object` -> scoped queryset -> 404 out-of-scope).
        Only the five pricing/window fields are writable; status / date /
        identity fields are not. A CANCELLED occurrence is frozen. The
        price/window diff lands as a targeted AuditLog UPDATE row via the
        dedicated `_PO_TRACKED_FIELDS` audit handler — NOT a status-history
        row (H-11: status changes belong to PlannedOccurrenceStatusHistory;
        this is a price/window edit, a separate fact).
        """
        occurrence = self.get_object()
        if occurrence.status == PlannedOccurrenceStatus.CANCELLED:
            return Response(
                {
                    "detail": "A cancelled occurrence cannot be edited.",
                    "code": "occurrence_override_forbidden_state",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = PlannedOccurrenceOverrideSerializer(
            occurrence, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            PlannedOccurrenceSerializer(
                occurrence, context={"request": request}
            ).data,
            status=status.HTTP_200_OK,
        )
