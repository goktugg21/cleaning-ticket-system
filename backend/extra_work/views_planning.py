"""W2-D — plan many Extra Works in one call.

    POST /api/extra-work/bulk-plan/

A crew agreed for the same week is the normal case, not an edge one: an
operator staffs six jobs off one phone call, and typing the same budget
and the same window six times is how one of them ends up different by
accident.

THE ONE THING THIS ENDPOINT EXISTS TO GET RIGHT
-----------------------------------------------
**Bulk plan carries the completion flags, and carries them by PRESENCE.**

In the reference system neither flag survives a plan write at all: the
plan modal sends `upload_is_required` and `notes_is_required`, the
config-driven update persists only the fields in its own allow-list,
neither is in it, and both are silently discarded — 0 of 78 live records
has either set to true
(`docs/reference/osius-reference-system/01-extra-work.md` §1.6, §3.6).
The gap-closing brief states the same failure from the operator's side,
as "bulk plan writes both to false on every selected work". The
mechanism differs; the consequence is the same, and it is the one to
avoid: a plan path that accepts a flag, does not carry it, and says
nothing.

We cannot have that bug, because there is only one plan payload
(`ExtraWorkPlanSerializer`) and one writer (`planning.apply_plan`), and
both read every field — the booleans included — by KEY PRESENCE:

    absent   -> left exactly as it was on each selected work
    present  -> written to every selected work

So a bulk edit of the dates cannot touch the flags, and a bulk edit of
the flags is something somebody asked for. `test_w2d_bulk_plan.py` pins
it with the flags set differently on two works in one selection.

THE THREE PROPERTIES BORROWED FROM THE BULK FAMILY NEXT DOOR
------------------------------------------------------------
Deliberately the same as `views_dates.py` / `views_assignments.py`,
because a caller should not have to learn a third dialect:

1. **All-or-nothing.** Every id is resolved through the caller's own
   `scope_extra_work_for` BEFORE any write, and one unresolvable id
   rejects the whole batch with zero writes. A partial bulk plan is
   worse than a failed one — the operator cannot see which half landed.
2. **An out-of-scope id is refused with the SAME body as one that does
   not exist**, and so is a person who is not assigned to one of the
   selected works. A distinguishable answer would let a caller
   enumerate which extra work exists in other tenants and who works
   where (H-1).
3. **Provider-only, at the door.** `scope_extra_work_for` would already
   narrow what a customer-side user can see, but planning is a provider
   action end to end and the refusal belongs at the door rather than
   emerging from an empty resolution.

WHAT IS REPORTED BACK
---------------------
Per work: whether it started, and if not, why not. A bulk plan over
twelve works where four already have a ticket driving their status is a
normal outcome, not a failure — but an operator who is not told which
four learns nothing from a bare "12 updated".

Nothing here imports from `tickets`.
"""
from __future__ import annotations

from django.db import transaction
from rest_framework import serializers, status
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRole
from accounts.permissions import IsAuthenticatedAndActive
from accounts.permissions_v2 import user_has_osius_permission
from audit import context as audit_context

from .planning import PlanRejected, apply_plan
from .scoping import scope_extra_work_for
from .serializers import ExtraWorkPlanSerializer


ERR_BULK_PLAN_INVALID = "extra_work_bulk_plan_invalid"
ERR_BULK_PLAN_PROVIDER_ONLY = "plan_provider_only"

# ONE constant message for every rejection reason — see property (2).
_BULK_PLAN_INVALID_MESSAGE = (
    "One or more of the selected works could not be resolved. Nothing "
    "was changed."
)


def _reject():
    raise serializers.ValidationError(
        {
            "detail": [
                serializers.ErrorDetail(
                    _BULK_PLAN_INVALID_MESSAGE, code=ERR_BULK_PLAN_INVALID
                )
            ],
            "code": ERR_BULK_PLAN_INVALID,
        }
    )


class _BulkPlanInputSerializer(ExtraWorkPlanSerializer):
    """The plan payload, plus the works to write it to.

    SUBCLASSED, not re-declared. Every field the single plan action
    accepts is a field this one accepts, BY CONSTRUCTION rather than by
    two lists being kept in step. A second declaration here is all it
    would take for the bulk table to quietly stop carrying a field the
    single form offers, and nothing would fail — the payload would
    validate, the write would land, and the field would be gone.
    """

    requests = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )


class ExtraWorkBulkPlanView(APIView):
    """POST /api/extra-work/bulk-plan/ — see the module docstring."""

    permission_classes = [IsAuthenticatedAndActive]
    # JSON ONLY. DRF's `BooleanField.get_value` reads a boolean that is
    # ABSENT from HTML form input as `False` (an unchecked checkbox
    # sends nothing), so with the default parser set a form-encoded bulk
    # plan that never mentioned the completion flags would write both to
    # False on every selected work — the reference system's defect,
    # rebuilt here by a framework default. Pinned at the door, on both
    # plan endpoints, and pinned by a test.
    parser_classes = [JSONParser]

    def post(self, request, *args, **kwargs):
        if request.user.role not in {
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        }:
            return Response(
                {
                    "detail": "This role cannot plan Extra Work. Planning "
                    "is a provider action.",
                    "code": ERR_BULK_PLAN_PROVIDER_ONLY,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        payload = _BulkPlanInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        request_ids = list(dict.fromkeys(data.pop("requests")))

        # Resolve through the actor's OWN scope before touching anything.
        requests = {
            row.id: row
            for row in scope_extra_work_for(request.user).filter(
                id__in=request_ids
            )
        }
        if len(requests) != len(request_ids):
            _reject()

        # Provider-side BUILDING scope, per row and BEFORE any write —
        # the same check the single plan action makes. `scope_extra_work_for`
        # already answered "may this actor SEE it"; this answers "may
        # this actor ACT on it", which for a COMPANY_ADMIN or a
        # BUILDING_MANAGER is a narrower question. A row that fails is
        # refused with the same body as one that does not exist.
        if request.user.role != UserRole.SUPER_ADMIN:
            for extra_work in requests.values():
                if not user_has_osius_permission(
                    request.user,
                    "osius.ticket.view_building",
                    building_id=extra_work.building_id,
                ):
                    _reject()

        try:
            audit_context.set_current_reason("extra_work_bulk_plan")
        except Exception:  # pragma: no cover - defensive
            pass

        results: list[dict] = []
        moved: list[int] = []
        kept_own_date: list[int] = []

        # One transaction for the batch, and `PlanRejected` propagates
        # out of it so a refusal on the ninth row rolls back the eight
        # before it — property (1). Ordered by id so the batch is
        # deterministic and a test can read the results positionally.
        try:
            with transaction.atomic():
                for extra_work_id in sorted(requests):
                    extra_work = requests[extra_work_id]
                    result = apply_plan(
                        extra_work, dict(data), actor=request.user
                    )
                    moved.extend(result["tickets_moved"])
                    kept_own_date.extend(result["tickets_kept_own_date"])
                    results.append(
                        {
                            "extra_work": extra_work.id,
                            "warnings": result["warnings"],
                            "started": result["started"],
                            "start_skipped": result["start_skipped"],
                        }
                    )
        except PlanRejected as exc:
            return Response(exc.body, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "updated": len(results),
                "results": results,
                "tickets_moved": moved,
                "tickets_kept_own_date": kept_own_date,
            },
            status=status.HTTP_200_OK,
        )
