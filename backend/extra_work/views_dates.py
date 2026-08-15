"""Sprint 176 §3 — set deadline / planned end on many Extra Work rows at once.

    POST /api/extra-work/bulk-dates/

A batch of jobs agreed for the same week is the normal case, not an edge
one: an operator gets off the phone having promised Friday for six
requests, and typing the same date six times is how one of them gets a
different date by accident.

Three properties, all borrowed deliberately from the Sprint 157 bulk-assign
family next door rather than invented here:

1. **All-or-nothing.** Every id is resolved through the caller's own
   `scope_extra_work_for` BEFORE any write, and one unresolvable id rejects
   the whole batch with zero writes. A partial bulk edit is worse than a
   failed one — the operator cannot see which half landed.

2. **An out-of-scope id is refused with the SAME body as one that does not
   exist.** Not a nicety: a distinguishable answer here would let a caller
   enumerate which extra work exists in other tenants (H-1).

3. **"Leave unchanged" is key PRESENCE**, resolved by the shared writer in
   `dates.py`. A field the dialog did not touch is absent from the payload
   and is not written; a field explicitly cleared arrives as null. This is
   the property the dialog's defaults rest on — without it a bulk edit of
   ten rows would wipe the date nobody touched on the other nine.

Provider-only, for the reason recorded in the §3 decision: the deadline is
what turns a row red and what an operator is measured against, so it is a
provider commitment. The customer's wish is `preferred_date`, which this
endpoint does not touch.

Nothing here imports from `tickets`.
"""
from __future__ import annotations

from django.db import transaction
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRole
from accounts.permissions import IsAuthenticatedAndActive
from audit import context as audit_context

from .dates import apply_extra_work_dates
from .scoping import scope_extra_work_for

ERR_BULK_DATES_INVALID = "extra_work_bulk_dates_invalid"


def _reject():
    """One rejection body for every failure mode — see property (2)."""
    raise serializers.ValidationError(
        {
            "detail": "One or more extra work requests could not be found.",
            "code": ERR_BULK_DATES_INVALID,
        }
    )


class _BulkDatesInputSerializer(serializers.Serializer):
    """`{requests: [id, ...], deadline?: date|null, planned_end_date?: ...}`.

    Both date fields are optional and nullable so the three states of the
    dialog survive the wire intact: absent (leave unchanged), null (clear),
    a date (set). `validate` refuses a body that names neither, because a
    bulk edit that changes nothing is far more likely to be a bug in the
    caller than a deliberate no-op over a selection of rows.
    """

    requests = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )
    deadline = serializers.DateField(required=False, allow_null=True)
    planned_end_date = serializers.DateField(required=False, allow_null=True)
    provider_planned_date = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        if (
            "deadline" not in attrs
            and "planned_end_date" not in attrs
            and "provider_planned_date" not in attrs
        ):
            raise serializers.ValidationError(
                {
                    "detail": "Provide deadline, planned_end_date and/or "
                    "provider_planned_date to set or clear.",
                    "code": "no_dates_provided",
                }
            )
        return attrs


class ExtraWorkBulkDatesView(APIView):
    """POST /api/extra-work/bulk-dates/ — see the module docstring."""

    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request, *args, **kwargs):
        # Refusal at the door, not emerging from an empty resolution.
        # `scope_extra_work_for` would already narrow what a customer-side
        # user can see, but a deadline is a provider commitment end to end
        # and the 403 should say so.
        if request.user.role not in {
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        }:
            return Response(
                {
                    "detail": "This role cannot set Extra Work dates. A "
                    "deadline is a provider commitment.",
                    "code": "deadline_provider_only",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        payload = _BulkDatesInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        request_ids = list(dict.fromkeys(data["requests"]))

        # Resolve through the actor's OWN scope before touching anything.
        requests = {
            row.id: row
            for row in scope_extra_work_for(request.user).filter(
                id__in=request_ids
            )
        }
        if len(requests) != len(request_ids):
            _reject()

        # Only the date keys that were actually sent — `apply_extra_work_dates`
        # reads presence, so rebuilding the dict here would turn "absent"
        # into "clear" for every row in the batch.
        fields = {
            key: data[key]
            for key in ("deadline", "planned_end_date", "provider_planned_date")
            if key in data
        }

        try:
            audit_context.set_current_reason("extra_work_bulk_dates")
        except Exception:  # pragma: no cover - defensive
            pass

        # One transaction for the batch. `apply_extra_work_dates` can still
        # refuse a row (a planned end before its planned start), and when it
        # does the whole batch rolls back rather than leaving the rows
        # before it written — property (1).
        with transaction.atomic():
            updated = 0
            for extra_work in requests.values():
                error = apply_extra_work_dates(extra_work, fields)
                if error is not None:
                    # Name the row. Unlike the scope rejection above there
                    # is nothing to leak here: the caller already proved it
                    # can see this request by resolving it.
                    error = dict(error)
                    error["extra_work_id"] = extra_work.id
                    return Response(
                        error, status=status.HTTP_400_BAD_REQUEST
                    )
                updated += 1

        return Response({"updated": updated}, status=status.HTTP_200_OK)
