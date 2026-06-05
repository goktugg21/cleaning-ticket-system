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
from collections import defaultdict

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from tickets.models import Ticket

from .constants import DEFAULT_GENERATION_DAYS_AHEAD, MAX_GENERATION_DAYS_AHEAD
from .errors import PlannedWorkError
from .generation import (
    _occurrence_pricing_snapshot,
    ensure_job_windows,
    generate_occurrences,
)
from .lifecycle import apply_occurrence_status, cancel_occurrence, skip_occurrence
from .models import (
    PlannedOccurrence,
    PlannedOccurrenceStatus,
    PlannedOccurrenceStatusHistory,
    RecurringJob,
)
from .permissions import CanManagePlannedOccurrence, CanManageRecurringJob
from .recurrence import iter_occurrence_dates
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


# Sprint 6 — calendar projection horizon (default + hard cap, in days).
_CALENDAR_DEFAULT_DAYS = 90
_CALENDAR_MAX_DAYS = 366


def _require_calendar_date(request) -> datetime.date:
    """Parse the REQUIRED POST-body `date` (YYYY-MM-DD) for the explicit-date
    actions (skip-date / add-date / clear-date)."""
    raw = request.data.get("date")
    if not raw:
        raise ValidationError(
            {
                "detail": "A 'date' (YYYY-MM-DD) is required.",
                "code": "date_required",
            }
        )
    return _parse_rollup_date(raw, "date")


def _occurrence_calendar_entry(occ, ticket_id):
    """One window cell for a PERSISTED occurrence (its real state)."""
    return {
        "window_id": occ.source_window_id,
        "window_label": occ.time_window_label
        or (occ.source_window.label if occ.source_window_id else ""),
        "status": occ.status,
        "is_ad_hoc": occ.is_ad_hoc,
        "occurrence_id": occ.id,
        "ticket_id": ticket_id,
    }


def _projected_calendar_entry(window):
    """One window cell for an UNMATERIALIZED rule date (no DB row yet)."""
    return {
        "window_id": window.id,
        "window_label": window.label,
        "status": PlannedOccurrenceStatus.PLANNED.value,
        "is_ad_hoc": False,
        "occurrence_id": None,
        "ticket_id": None,
    }


def _build_job_calendar(job, range_start, range_end):
    """Read-only merged occurrence projection for ONE recurring job over
    [range_start, range_end]: the UNION of (i) the rule's projected dates
    (unmaterialized -> PLANNED, occurrence_id null) and (ii) the persisted
    PlannedOccurrence rows in range (their real status / is_ad_hoc /
    occurrence_id / ticket_id). NO persistence; scoped strictly to `job`.
    """
    if range_start > range_end:
        return []
    active_windows = list(
        job.windows.filter(is_active=True).order_by("ordering", "id")
    )
    persisted = list(
        PlannedOccurrence.objects.filter(
            recurring_job=job,
            planned_date__gte=range_start,
            planned_date__lte=range_end,
        ).select_related("source_window")
    )
    ticket_map = dict(
        Ticket.objects.filter(planned_occurrence__in=persisted).values_list(
            "planned_occurrence_id", "id"
        )
    )
    persisted_by_date = defaultdict(list)
    for occ in persisted:
        persisted_by_date[occ.planned_date].append(occ)
    rule_dates = set(
        iter_occurrence_dates(
            job.frequency,
            job.start_date,
            range_start,
            range_end,
            job.end_date,
            weekdays=job.weekdays,
        )
    )
    out = []
    for d in sorted(rule_dates | set(persisted_by_date.keys())):
        occs = persisted_by_date.get(d, [])
        seen_window_ids = {o.source_window_id for o in occs}
        # (sort_key, entry) so persisted + rule-projected windows interleave by
        # the window's display order for a stable per-date ordering.
        cells = []
        for occ in occs:
            order = occ.source_window.ordering if occ.source_window_id else 0
            cells.append(
                (
                    (order, occ.source_window_id or 0),
                    _occurrence_calendar_entry(occ, ticket_map.get(occ.id)),
                )
            )
        if d in rule_dates:
            for w in active_windows:
                if w.id not in seen_window_ids:
                    cells.append(((w.ordering, w.id), _projected_calendar_entry(w)))
        cells.sort(key=lambda c: c[0])
        out.append({"date": d.isoformat(), "windows": [c[1] for c in cells]})
    return out


def _single_date_windows(job, d):
    """The calendar `windows` array for a SINGLE date — reused as the
    explicit-date actions' response so the client can render the new state
    without a separate fetch."""
    cal = _build_job_calendar(job, d, d)
    return cal[0]["windows"] if cal else []


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

    # ------------------------------------------------------------------
    # Sprint 6 — explicit per-date occurrence control (calendar tick).
    #
    # Each action applies a SINGLE date across the job's ACTIVE windows and
    # is idempotent. They never change rule-based generation: a pre-created
    # SKIPPED row blocks a future date because get_or_create's `defaults`
    # apply only on CREATE and the spawn step only spawns a PLANNED
    # occurrence with no ticket. The skip/clear actions never touch an
    # occurrence that already spawned a ticket.
    # ------------------------------------------------------------------

    @action(detail=True, methods=["post"], url_path="skip-date")
    def skip_date(self, request, pk=None):
        """Skip a whole DATE (the calendar "untick a rule date"). For each
        active window, materialize (if absent) the occurrence and flip it to
        SKIPPED so the generator never spawns it. Refused when the date
        already has a live generated ticket (cancel that occurrence instead).
        """
        job = self.get_object()
        d = _require_calendar_date(request)
        if Ticket.objects.filter(
            planned_occurrence__recurring_job=job,
            planned_occurrence__planned_date=d,
            deleted_at__isnull=True,
        ).exists():
            return Response(
                {
                    "detail": "This date already has a generated ticket; "
                    "cancel that occurrence instead of skipping the date.",
                    "code": "skip_date_has_ticket",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            for window in ensure_job_windows(job):
                pricing_mode, fixed_price, vat_pct = _occurrence_pricing_snapshot(
                    job, window
                )
                occ, _created = PlannedOccurrence.objects.get_or_create(
                    recurring_job=job,
                    planned_date=d,
                    source_window=window,
                    defaults={
                        "company": job.company,
                        "building": job.building,
                        "customer": job.customer,
                        "status": PlannedOccurrenceStatus.PLANNED,
                        "pricing_mode": pricing_mode,
                        "fixed_price": fixed_price,
                        "vat_pct": vat_pct,
                        "preferred_start_time": window.start_time,
                        "time_window_label": window.label,
                    },
                )
                # Only a PLANNED row flips to SKIPPED — an already-SKIPPED row
                # is an idempotent no-op; anything materialized was excluded by
                # the live-ticket guard above.
                if occ.status == PlannedOccurrenceStatus.PLANNED:
                    apply_occurrence_status(
                        occ,
                        PlannedOccurrenceStatus.SKIPPED,
                        actor=request.user,
                        reason="Skipped from the recurring-job calendar.",
                    )
        return Response(
            {"date": d.isoformat(), "windows": _single_date_windows(job, d)},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="add-date")
    def add_date(self, request, pk=None):
        """Add an ad-hoc PLANNED occurrence on a DATE (the calendar "tick an
        off-rule date"), for each active window, snapshotting pricing exactly
        like the generator. The per-occurrence spawn picks it up when due.
        Idempotent.
        """
        job = self.get_object()
        d = _require_calendar_date(request)
        # Bound the ad-hoc date to the job's own [start_date, end_date] window
        # (end_date null = open-ended, no upper bound). Adding a date outside
        # the job's lifetime would create an occurrence the rule could never
        # have produced — and one past end_date would never spawn anyway.
        if d < job.start_date:
            return Response(
                {
                    "detail": "This date is before the recurring job's start "
                    "date.",
                    "code": "add_date_before_start_date",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if job.end_date is not None and d > job.end_date:
            return Response(
                {
                    "detail": "This date is after the recurring job's end "
                    "date.",
                    "code": "add_date_after_end_date",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            for window in ensure_job_windows(job):
                pricing_mode, fixed_price, vat_pct = _occurrence_pricing_snapshot(
                    job, window
                )
                occ, created = PlannedOccurrence.objects.get_or_create(
                    recurring_job=job,
                    planned_date=d,
                    source_window=window,
                    defaults={
                        "company": job.company,
                        "building": job.building,
                        "customer": job.customer,
                        "status": PlannedOccurrenceStatus.PLANNED,
                        "is_ad_hoc": True,
                        "pricing_mode": pricing_mode,
                        "fixed_price": fixed_price,
                        "vat_pct": vat_pct,
                        "preferred_start_time": window.start_time,
                        "time_window_label": window.label,
                    },
                )
                if created:
                    # Record the ad-hoc add as a status-history row (the H-11
                    # planned-work audit trail — PlannedOccurrence is NOT in
                    # the generic AuditLog).
                    PlannedOccurrenceStatusHistory.objects.create(
                        occurrence=occ,
                        old_status="",
                        new_status=PlannedOccurrenceStatus.PLANNED,
                        changed_by=request.user,
                        note="Ad-hoc date added from the recurring-job calendar.",
                    )
        return Response(
            {"date": d.isoformat(), "windows": _single_date_windows(job, d)},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="clear-date")
    def clear_date(self, request, pk=None):
        """Clear a DATE: delete its still-PLANNED-or-SKIPPED, not-yet-spawned
        occurrences. A skipped RULE date reverts to rule-generated (the next
        run recreates it PLANNED); an ad-hoc date disappears. Never deletes an
        occurrence that already spawned a ticket. Idempotent.
        """
        job = self.get_object()
        d = _require_calendar_date(request)
        with transaction.atomic():
            occs = PlannedOccurrence.objects.filter(
                recurring_job=job,
                planned_date=d,
                status__in=[
                    PlannedOccurrenceStatus.PLANNED,
                    PlannedOccurrenceStatus.SKIPPED,
                ],
            )
            for occ in occs:
                # Defensive: a PLANNED/SKIPPED row should never carry a ticket
                # (a spawn flips it to TICKET_CREATED), but never delete one.
                if Ticket.objects.filter(planned_occurrence=occ).exists():
                    continue
                occ.delete()
        return Response(
            {"date": d.isoformat(), "windows": _single_date_windows(job, d)},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"], url_path="calendar")
    def calendar(self, request, pk=None):
        """Read-only merged occurrence projection for THIS job over a horizon
        (default today..+90d; capped at the job's end_date and a hard 366-day
        max). The union of rule-projected dates and persisted occurrences. No
        persistence; strictly job-scoped.
        """
        job = self.get_object()
        today = timezone.localdate()

        raw_from = request.query_params.get("from")
        range_start = _parse_rollup_date(raw_from, "from") if raw_from else today

        raw_to = request.query_params.get("to")
        range_end = (
            _parse_rollup_date(raw_to, "to")
            if raw_to
            else today + datetime.timedelta(days=_CALENDAR_DEFAULT_DAYS)
        )

        hard_max = today + datetime.timedelta(days=_CALENDAR_MAX_DAYS)
        if range_end > hard_max:
            range_end = hard_max
        if job.end_date and range_end > job.end_date:
            range_end = job.end_date

        return Response(
            {
                "from": range_start.isoformat(),
                "to": range_end.isoformat(),
                "dates": _build_job_calendar(job, range_start, range_end),
            },
            status=status.HTTP_200_OK,
        )


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
