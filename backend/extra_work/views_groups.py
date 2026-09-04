"""W5-B — the three group endpoints.

    POST  /api/extra-work/batch/                 one form, many works
    GET   /api/extra-work/groups/<id>/           members + the spread
    PATCH /api/extra-work/groups/<id>/members/   title / time / condition

WHAT IS NOT HERE, AND WHY
-------------------------
**No group status endpoint.** The reference system has
`PUT /groups/{id}/status`, a query-builder mass update whose target
status "is not validated against `t_ticket_status` at all" and which
"bypasses Eloquent events entirely: no `*_by` stamp, no `*_at` stamp, no
system comment, no broadcast, no FCM, no activity row, no draft
publication" (A7 §2.1). Its one caller never sends `source_status_id`,
so the whole group is moved to one status regardless of where each
member was — and live group 17 shows the result: eight members at the
invoicing status with `approved_at` null, having skipped the approval
step entirely. A status change here is a workflow transition, goes
through `state_machine.apply_transition`, and writes its history row.
One work at a time, as it always has.

**No group delete endpoint.** Theirs soft-deletes every member "with no
status check at all -- a group containing invoiced works can be deleted
this way", then hard-deletes the group row so the nullOnDelete FK
orphans the members it just removed (A7 §2.1). Cancelling one work is a
per-work action and stays one.

**No group planning endpoint.** Planning already has exactly two doors,
`POST /extra-work/<id>/plan/` and `POST /extra-work/bulk-plan/`, and
since W4-O the bulk one takes per-work values in one atomic call. The
group editor calls THAT. A third planning path would be a third place
for the completion flags to be silently dropped, which is the defect
that family of endpoints exists to prevent.

So what is left here is what genuinely has no home: creating N works
from one form, reading a group back, and editing the two scheduling
columns plus the title.

JSON ONLY, on both writes. DRF reads a boolean that is ABSENT from form
input as `False`, so a form-encoded write could silently clear a
completion flag across a whole group. Pinned at the door, exactly as on
the plan endpoints, and pinned by a test.
"""
from __future__ import annotations

import datetime
import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from notifications.services import emit_extra_work_requested_notifications
from rest_framework import serializers, status
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRole
from accounts.permissions import IsAuthenticatedAndActive
from accounts.permissions_v2 import user_has_osius_permission
from audit import context as audit_context

from .groups import (
    BatchRejected,
    MAX_BATCH_SLOTS,
    compose_member_title,
    create_batch,
    group_status_counts,
)
from .models import ExtraWorkCondition, ExtraWorkGroup
from .scoping import scope_extra_work_for
from .serializers import (
    ExtraWorkRequestCreateSerializer,
    ExtraWorkRequestDetailSerializer,
    redact_for_customer,
)

logger = logging.getLogger(__name__)


ERR_GROUP_PROVIDER_ONLY = "extra_work_group_provider_only"
ERR_GROUP_MEMBER_INVALID = "extra_work_group_member_invalid"

#: ONE constant message for every way a member reference can fail —
#: not in this group, not visible to this caller, or not a real id.
#: A distinguishable answer would let a caller enumerate which extra
#: work exists in other tenants (H-1).
_MEMBER_INVALID_MESSAGE = (
    "One or more of the works could not be resolved. Nothing was changed."
)


def _reject_member():
    raise serializers.ValidationError(
        {
            "detail": [
                serializers.ErrorDetail(
                    _MEMBER_INVALID_MESSAGE, code=ERR_GROUP_MEMBER_INVALID
                )
            ],
            "code": ERR_GROUP_MEMBER_INVALID,
        }
    )


class _SlotSerializer(serializers.Serializer):
    """One picked day/time/condition.

    `time` and `condition` are optional and NULL is a real answer for
    both: a slot with no time is not midnight, and a slot with no
    condition is not "at handover". See `ExtraWorkCondition`.
    """

    date = serializers.DateField()
    time = serializers.TimeField(required=False, allow_null=True)
    condition = serializers.ChoiceField(
        choices=ExtraWorkCondition.choices, required=False, allow_null=True
    )


class _BatchInputSerializer(serializers.Serializer):
    """Only the slots are validated here.

    Everything else on the body is the SHARED payload and is passed to
    `ExtraWorkRequestCreateSerializer` untouched, so this endpoint
    cannot develop its own opinion about what a valid Extra Work is.
    That is the whole reason the reference system's batch path drifted
    from its single path — two writers, two field sets, two
    product-unit conventions on one table.
    """

    slots = _SlotSerializer(many=True, allow_empty=False)


class ExtraWorkBatchCreateView(APIView):
    """POST /api/extra-work/batch/ — see the module docstring."""

    permission_classes = [IsAuthenticatedAndActive]
    parser_classes = [JSONParser]

    def post(self, request, *args, **kwargs):
        payload = _BatchInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        slots = payload.validated_data["slots"]

        # Everything that is not `slots` is the shared payload, verbatim.
        shared = {
            key: value
            for key, value in request.data.items()
            if key not in ("slots", "idempotency_key")
        }

        # W-FIX1 D3 (audit F28) — a resend is not a second series. The
        # client stamps each batch with an `idempotency_key`; a resend
        # carrying one is answered with the series it already made, when
        # this actor made a series with the same title, customer,
        # building and slot dates in the last quarter hour. The key
        # itself is not persisted — `ExtraWorkGroup` has no column for
        # it and adding one is a migration, reported rather than written
        # — so the match is on the batch's own natural key, and only for
        # callers that sent a key (an old client keeps its old contract).
        idempotency_key = str(request.data.get("idempotency_key") or "").strip()
        if idempotency_key:
            duplicate = _recent_duplicate_group(request.user, shared, slots)
            if duplicate is not None:
                members = list(duplicate.members.order_by("group_sequence", "id"))
                return Response(
                    {
                        "group": _group_block(duplicate),
                        "created": 0,
                        "members": [member.id for member in members],
                        "deduplicated": True,
                    },
                    status=status.HTTP_200_OK,
                )

        try:
            audit_context.set_current_reason("extra_work_batch_create")
        except Exception:  # pragma: no cover - defensive
            pass

        try:
            group, members = create_batch(
                shared=shared,
                slots=slots,
                serializer_class=ExtraWorkRequestCreateSerializer,
                context={"request": request},
            )
        except BatchRejected as exc:
            return Response(exc.body, status=status.HTTP_400_BAD_REQUEST)

        # W-FIX1 D3 — the single create path emits the "new extra-work
        # request" notification to provider management; the batch path
        # bypassed `ExtraWorkRequestViewSet.create` and never did. Same
        # helper, same best-effort contract (logged, never fatal).
        for member in members:
            try:
                emit_extra_work_requested_notifications(
                    member, actor=member.created_by
                )
            except Exception:  # noqa: BLE001 — best-effort fan-out, logged
                logger.exception(
                    "Failed to emit extra-work requested notification for EW %s",
                    member.pk,
                )

        return Response(
            {
                "group": _group_block(group),
                "created": len(members),
                "members": [member.id for member in members],
                "deduplicated": False,
            },
            status=status.HTTP_201_CREATED,
        )


#: How long a resend still counts as the same batch.
_DEDUPE_WINDOW = datetime.timedelta(minutes=15)


def _recent_duplicate_group(user, shared: dict, slots: list[dict]):
    """The series this actor just made with this exact batch, or None.

    Natural key: title, customer, building, and the SET of slot dates.
    Everything else on the payload is shared by construction, so two
    batches that agree on these four within the window are one batch
    sent twice.
    """
    def _int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    customer_id = _int(shared.get("customer"))
    building_id = _int(shared.get("building"))
    if customer_id is None or building_id is None:
        return None
    wanted_dates = sorted({slot["date"] for slot in slots})
    since = timezone.now() - _DEDUPE_WINDOW
    candidates = (
        ExtraWorkGroup.objects.filter(
            created_by=user,
            customer_id=customer_id,
            building_id=building_id,
            standard_title=str(shared.get("title", "") or ""),
            created_at__gte=since,
        )
        .prefetch_related("members")
        .order_by("-id")
    )
    for group in candidates:
        dates = sorted(
            {
                member.preferred_date
                for member in group.members.all()
                if member.preferred_date is not None
            }
        )
        if dates == wanted_dates:
            return group
    return None


def _group_block(group) -> dict:
    return {
        "id": group.id,
        "standard_title": group.standard_title,
        "customer": group.customer_id,
        "building": group.building_id,
        "member_count": group.members.count(),
        "status_counts": group_status_counts(group),
    }


def _resolve_group(request, pk: int):
    """A group the caller may see, or a 404 that says nothing else.

    Resolved THROUGH THE MEMBERS' OWN SCOPE rather than by reading the
    group's company id, so group visibility can never be broader than
    the visibility of the work inside it. A group whose members are all
    invisible to this caller is a group that does not exist as far as
    this caller is concerned.

    None of the reference system's three group endpoints applies its
    scope filter at all — "each starts from `ExtraWorkGroup::findOrFail`
    / a bare `ExtraWork::where(...)`, exactly like the other unscoped
    endpoints tier-1 A1 listed" (A7 §2.1).
    """
    group = get_object_or_404(ExtraWorkGroup, pk=pk)
    visible = scope_extra_work_for(request.user).filter(group=group)
    if not visible.exists():
        # Same answer as a group id that was never issued.
        get_object_or_404(ExtraWorkGroup, pk=0)
    return group


class ExtraWorkGroupDetailView(APIView):
    """GET /api/extra-work/groups/<id>/ — the members and their spread."""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, pk: int, *args, **kwargs):
        group = _resolve_group(request, pk)
        members = (
            scope_extra_work_for(request.user)
            .filter(group=group)
            .select_related("building")
            .order_by("group_sequence", "id")
        )
        return Response(
            {
                "group": _group_block(group),
                "members": [
                    redact_for_customer(
                        {
                        "extra_work": member.id,
                        "title": member.title,
                        "status": member.status,
                        "building_name": member.building.name,
                        "preferred_date": member.preferred_date,
                        "scheduled_time": member.scheduled_time,
                        "condition": member.condition,
                        "group_sequence": member.group_sequence,
                        "provider_planned_date": member.provider_planned_date,
                        "budget_hours": (
                            None
                            if member.budget_hours is None
                            else f"{member.budget_hours:.2f}"
                        ),
                        },
                        request.user,
                        # W-FIX1 D4 — the DETAIL serializer's own list, so
                        # what a customer cannot read there they cannot
                        # read here either.
                        ExtraWorkRequestDetailSerializer._PROVIDER_ONLY_FIELDS,
                    )
                    for member in members
                ],
            },
            status=status.HTTP_200_OK,
        )


class _MemberEditSerializer(serializers.Serializer):
    """One member's editable scheduling columns.

    READ BY KEY PRESENCE, the same convention the plan payload uses:
    absent leaves the value alone, present-and-null clears it, present
    sets it. `condition: null` is therefore how an operator says "we
    were wrong to record one", which a truthiness check could not
    express.
    """

    extra_work = serializers.IntegerField(min_value=1)
    title = serializers.CharField(max_length=255, required=False)
    scheduled_time = serializers.TimeField(required=False, allow_null=True)
    condition = serializers.ChoiceField(
        choices=ExtraWorkCondition.choices, required=False, allow_null=True
    )
    #: Recompose the title from this member's columns AFTER the edits
    #: above land. One direction only — it reads `preferred_date`,
    #: `scheduled_time` and `condition`, never the old title.
    regenerate_title = serializers.BooleanField(required=False)


class _MembersEditInputSerializer(serializers.Serializer):
    members = _MemberEditSerializer(many=True, allow_empty=False)


class ExtraWorkGroupMembersView(APIView):
    """PATCH /api/extra-work/groups/<id>/members/ — title, time, condition.

    The three things about a member that are neither a workflow
    transition nor a planning value, and therefore have no existing
    endpoint. Date, budget hours and assigned people are NOT here: they
    go through `bulk-plan` and `bulk-assign`, which already take
    per-work values.

    All-or-nothing, like every other bulk write in this app: one
    unresolvable member rejects the batch with zero writes.
    """

    permission_classes = [IsAuthenticatedAndActive]
    # JSON ONLY — see the module docstring.
    parser_classes = [JSONParser]

    _PROVIDER_ROLES = frozenset(
        {
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        }
    )

    def patch(self, request, pk: int, *args, **kwargs):
        if request.user.role not in self._PROVIDER_ROLES:
            return Response(
                {
                    "detail": "This role cannot edit a work series.",
                    "code": ERR_GROUP_PROVIDER_ONLY,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        group = _resolve_group(request, pk)
        payload = _MembersEditInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        rows = payload.validated_data["members"]

        wanted = [row["extra_work"] for row in rows]
        if len(set(wanted)) != len(wanted):
            _reject_member()

        # Resolved through the caller's own scope AND pinned to this
        # group, before anything is written.
        members = {
            member.id: member
            for member in scope_extra_work_for(request.user)
            .filter(group=group, id__in=wanted)
        }
        if len(members) != len(wanted):
            _reject_member()

        if request.user.role != UserRole.SUPER_ADMIN:
            for member in members.values():
                if not user_has_osius_permission(
                    request.user,
                    "osius.ticket.view_building",
                    building_id=member.building_id,
                ):
                    _reject_member()

        try:
            audit_context.set_current_reason("extra_work_group_member_edit")
        except Exception:  # pragma: no cover - defensive
            pass

        with transaction.atomic():
            for row in rows:
                member = members[row["extra_work"]]
                fields = []
                if "scheduled_time" in row:
                    member.scheduled_time = row["scheduled_time"]
                    fields.append("scheduled_time")
                if "condition" in row:
                    member.condition = row["condition"]
                    fields.append("condition")
                if "title" in row:
                    member.title = row["title"]
                    fields.append("title")
                # AFTER the column edits, and derived from the columns
                # only. Never from the previous title.
                if row.get("regenerate_title"):
                    member.title = compose_member_title(
                        group.standard_title,
                        member.preferred_date,
                        member.scheduled_time,
                        member.condition,
                    )
                    if "title" not in fields:
                        fields.append("title")
                if fields:
                    fields.append("updated_at")
                    member.save(update_fields=fields)

        return Response(
            {"group": _group_block(group), "updated": len(rows)},
            status=status.HTTP_200_OK,
        )
