"""
Sprint 152 — hour-type catalog endpoints.

    GET  / POST            /api/timesheets/hour-types/
    GET  / PATCH / DELETE  /api/timesheets/hour-types/<int:hour_type_id>/
    POST                   /api/timesheets/hour-types/standard-set/

Reads are open to every provider-side role — STAFF needs the ACTIVE
types to fill in the entry form, and the list is already scoped to their
own company. Writes are SA / CA only (`IsTimesheetManager`) and run
`_enforce_timesheet_management` against the row's owning company.

CUSTOMER_USER is 403'd on every method by `IsTimesheetUser`.
"""
from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import Count, ProtectedError
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from audit import context as audit_context
from companies.models import Company, CompanyUserMembership
from config.pagination import UnboundedPagination

from .models import HourType, TimeEntry, WeekLock
from .permissions import (
    IsTimesheetManager,
    IsTimesheetUser,
    _enforce_timesheet_management,
)
from .scope import filter_hour_types_for, scope_company_ids_for_timesheets
from .serializers import (
    ERR_HOUR_TYPE_NAME_NOT_UNIQUE,
    HourTypeSerializer,
    HourTypeStandardSetSerializer,
    snapshot_multiplier,
)
from .standard_set import STANDARD_HOUR_TYPES
from .views_common import parse_bool_param, resolve_target_company


ERR_HOUR_TYPE_PROTECTED = "hour_type_protected"


def _annotate_entry_counts(queryset):
    """One aggregate for the whole page — the number the UI reads to
    decide whether Delete is offerable at all (`TimeEntry.hour_type` is
    PROTECT, so a type with any entry is permanently undeletable).
    """
    return queryset.annotate(
        annotated_entry_count=Count("time_entries", distinct=True)
    )


class HourTypeListCreateView(generics.ListCreateAPIView):
    """GET (list) + POST (create) at /api/timesheets/hour-types/.

    Filters `?company=<id>` and `?is_active=true|false`. Both NARROW
    only: they are applied BEFORE `filter_hour_types_for`, which then
    intersects with the actor's own scope, so no query param can widen
    what an actor sees. `?company=` is how a SUPER_ADMIN picks the one
    company they are working in (Sprint 149/150).
    """

    serializer_class = HourTypeSerializer
    pagination_class = UnboundedPagination

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsTimesheetUser()]
        return [IsTimesheetManager()]

    def get_queryset(self):
        qs = _annotate_entry_counts(
            HourType.objects.select_related("company").all()
        )
        company_param = self.request.query_params.get("company")
        if company_param:
            try:
                qs = qs.filter(company_id=int(company_param))
            except (TypeError, ValueError):
                # Bad input -> empty result rather than a 500.
                qs = qs.none()
        flag = parse_bool_param(self.request.query_params.get("is_active"))
        if flag is not None:
            qs = qs.filter(is_active=flag)
        qs = filter_hour_types_for(self.request.user, qs)
        return qs.order_by("sort_order", "name", "id")

    def perform_create(self, serializer):
        target_company = resolve_target_company(
            self.request.user, serializer.validated_data.get("company")
        )
        _enforce_timesheet_management(self.request.user, target_company)
        try:
            # The inner atomic() is load-bearing, not decorative: without
            # a savepoint boundary Postgres refuses every further command
            # in the surrounding transaction after an IntegrityError,
            # even though Python catches it. Same rationale as
            # `ManagedUnitListCreateView.perform_create`.
            with transaction.atomic():
                serializer.save(company=target_company)
        except IntegrityError:
            # Backstop for the case the serializer's pre-check cannot
            # cover — a CA who omitted `company`, so the target was not
            # known at validate() time — and for a genuine race.
            raise serializers.ValidationError(
                {
                    "name": [
                        serializers.ErrorDetail(
                            "An hour type with this name already exists "
                            "for this company.",
                            code=ERR_HOUR_TYPE_NAME_NOT_UNIQUE,
                        )
                    ]
                }
            )


class HourTypeDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET / PATCH / DELETE at /api/timesheets/hour-types/<id>/.

    The queryset is scoped on EVERY method, so an out-of-scope id is a
    404 before any handler runs.
    """

    serializer_class = HourTypeSerializer
    lookup_url_kwarg = "hour_type_id"

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsTimesheetUser()]
        return [IsTimesheetManager()]

    def get_queryset(self):
        return filter_hour_types_for(
            self.request.user,
            _annotate_entry_counts(
                HourType.objects.select_related("company").all()
            ),
        )

    def perform_update(self, serializer):
        """Save the type, and — when the MULTIPLIER changed — refresh
        `multiplier_snapshot` on this type's entries in OPEN weeks of
        this company, in the SAME transaction.

        This is the immutability core of the module. A closed week's
        weighted totals must be byte-identical before and after a
        multiplier edit, because a closed week is a number somebody has
        already acted on; an open week must follow the current
        multiplier, because it has not been agreed yet. Both halves are
        one transaction so there is no window in which a report would
        read a half-refreshed set.

        Per-row `save()` rather than a queryset `.update()`: `TimeEntry`
        is registered for full-CRUD generic audit and a queryset update
        fires no `post_save`, so it would silently write nothing to
        `AuditLog` (RBAC H-10). Same precedent as
        `ServiceCategoryArchiveView`.
        """
        instance = serializer.instance
        _enforce_timesheet_management(self.request.user, instance.company)
        old_multiplier = instance.multiplier
        try:
            with transaction.atomic():
                hour_type = serializer.save()
                if hour_type.multiplier != old_multiplier:
                    self._refresh_open_week_snapshots(hour_type)
        except IntegrityError:
            raise serializers.ValidationError(
                {
                    "name": [
                        serializers.ErrorDetail(
                            "An hour type with this name already exists "
                            "for this company.",
                            code=ERR_HOUR_TYPE_NAME_NOT_UNIQUE,
                        )
                    ]
                }
            )

    @staticmethod
    def _refresh_open_week_snapshots(hour_type):
        """Rewrite `multiplier_snapshot` on this type's entries whose
        week is OPEN. Closed weeks are never touched.

        The closed set is read ONCE for the company (`WeekLock` rows are
        few — only weeks somebody deliberately closed) and the entries
        are filtered against it in Python, rather than issuing a lock
        lookup per entry.
        """
        closed = {
            (row[0], row[1])
            for row in WeekLock.objects.filter(
                company_id=hour_type.company_id
            ).values_list("iso_year", "iso_week")
        }
        audit_context.set_current_reason("hour_type_multiplier_refresh")
        new_snapshot = snapshot_multiplier(hour_type)
        entries = TimeEntry.objects.filter(
            hour_type=hour_type, company_id=hour_type.company_id
        ).exclude(multiplier_snapshot=new_snapshot)
        for entry in entries:
            if (entry.iso_year, entry.iso_week) in closed:
                continue
            entry.multiplier_snapshot = new_snapshot
            entry.save(update_fields=["multiplier_snapshot", "updated_at"])

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        _enforce_timesheet_management(request.user, instance.company)
        try:
            instance.delete()
        except ProtectedError:
            return Response(
                {
                    # BACKSTOP only: the UI offers Delete exactly when
                    # `entry_count` is 0 and offers Archive otherwise.
                    "detail": (
                        "Cannot delete an hour type that is still used by "
                        "time entries. Archive it (is_active=false) "
                        "instead — archiving keeps every existing entry "
                        "intact and only removes the type from the "
                        "pickers for new ones."
                    ),
                    "code": ERR_HOUR_TYPE_PROTECTED,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class HourTypeStandardSetView(APIView):
    """POST /api/timesheets/hour-types/standard-set/ — create the
    standard Dutch six for a company, skipping names it already has.

    Idempotent by construction: the skip test is the SAME
    case/whitespace-insensitive comparison the uniqueness constraint
    uses, so pressing the button twice creates nothing the second time
    rather than 400-ing on the first collision and leaving a partial
    set behind. One transaction.

    The response reports `created` and `skipped` by name, because "6
    added" and "6 already there" are the two outcomes an operator needs
    told apart and a bare count cannot tell them.
    """

    permission_classes = [IsTimesheetManager]

    def post(self, request, *args, **kwargs):
        payload = HourTypeStandardSetSerializer(
            data=request.data, context={"request": request}
        )
        payload.is_valid(raise_exception=True)
        target_company = resolve_target_company(
            request.user, payload.validated_data.get("company")
        )
        _enforce_timesheet_management(request.user, target_company)

        existing = {
            name.strip().lower()
            for name in HourType.objects.filter(
                company=target_company
            ).values_list("name", flat=True)
        }

        created, skipped = [], []
        audit_context.set_current_reason("hour_type_standard_set")
        with transaction.atomic():
            for name, multiplier, sort_order in STANDARD_HOUR_TYPES:
                if name.strip().lower() in existing:
                    skipped.append(name)
                    continue
                HourType.objects.create(
                    company=target_company,
                    name=name,
                    multiplier=multiplier,
                    sort_order=sort_order,
                )
                created.append(name)

        return Response(
            {
                "company": target_company.id,
                "created": created,
                "skipped": skipped,
                "created_count": len(created),
                "skipped_count": len(skipped),
            },
            status=status.HTTP_201_CREATED
            if created
            else status.HTTP_200_OK,
        )
