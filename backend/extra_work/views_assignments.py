"""
Sprint 157 §2 — assign workers and managers to Extra Work, in bulk.

    POST /api/extra-work/bulk-assign/
    Body: {"requests": [id,...], "users": [id,...],
           "role": "WORKER"|"MANAGER", "mode": "assign"|"unassign"}
      or: {"requests": [id,...], "workers": [id,...],
           "managers": [id,...], "mode": "assign"|"unassign"}
    Response: {"created": N, "removed": N,
               "already_assigned": N, "not_assigned": N}

Sprint 159 §2 — the second shape puts BOTH roles in one request. The
owner's complaint was that the UI took one role per operation, so
staffing a job meant two confirms and, if the second failed, half a
crew. One body, one transaction, one all-or-nothing answer.

Same discipline as the Sprint 154 building bulk-link family, for the
same reasons, and stated here rather than assumed because this is a NEW
write surface:

1. **Every id is resolved before any write.** Requests through
   `scope_extra_work_for`, users through the provider-employee query
   below. One unresolvable id rejects the WHOLE batch with a 400 and
   zero writes — a partial bulk assign is worse than none, because the
   operator then has to work out which half landed.

2. **A foreign id and a fictional id are the same answer.** Both fall
   out of the same "did every id resolve" check and produce one constant
   body, so the endpoint cannot be used to discover whether an id names
   a real request or a real person (H-1, the Sprint 142.1 oracle class).
   Pinned by comparing two response bodies for equality in the tests.

3. **Real `objects.create()` / instance `.delete()`, never a queryset
   `.update()`.** The audit rows are written by post_save / post_delete
   receivers; a bulk `.update()` fires neither and the assignment would
   happen with no trace (H-10).

4. **One `transaction.atomic()`** around every pair.

Sprint 158 §1 — WHO may be assigned is now derived from the request's
BUILDING, not its company, and differs per role:

    GET /api/extra-work/<id>/assignable/?role=WORKER|MANAGER

Sprint 157 used one set `{STAFF, BUILDING_MANAGER, COMPANY_ADMIN}` for
both roles, so a field worker could be made the MANAGER of a request.
The rule now lives in `buildings.assignment_eligibility`, and the picker
READ and the write VALIDATOR both go through it — so "who is offerable"
equals "who is acceptable" by construction rather than by two lists
being kept in step (Sprint 152.1 §1a).

Nothing here imports from `tickets`. `TicketStaffAssignment` is the
model this one is shaped after, but extra work and tickets are separate
modules and coupling them would make an extra-work change depend on the
ticket state machine. The shared eligibility helper lives in
`buildings/` for the same reason — it is a BUILDING rule, and both
modules already depend on that app.
"""
from __future__ import annotations

from django.db import transaction
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from django.shortcuts import get_object_or_404

from accounts.models import UserRole
from accounts.permissions import IsAuthenticatedAndActive
from audit import context as audit_context
from buildings.assignment_eligibility import (
    eligible_users_for_building,
    resolve_assignable_users,
)

from .models import ExtraWorkAssignment, ExtraWorkAssignmentRole
from .scoping import scope_extra_work_for


ERR_BULK_ASSIGN_INVALID = "extra_work_bulk_assign_invalid"

# ONE constant message for every rejection reason. A message that named
# WHICH id failed, or why, would be the oracle this is written to avoid.
_BULK_ASSIGN_INVALID_MESSAGE = (
    "One or more of the selected requests or people could not be "
    "resolved, or cannot be assigned to each other. Nothing was changed."
)

def _reject():
    raise serializers.ValidationError(
        {
            "detail": [
                serializers.ErrorDetail(
                    _BULK_ASSIGN_INVALID_MESSAGE, code=ERR_BULK_ASSIGN_INVALID
                )
            ]
        }
    )


class _BulkAssignInputSerializer(serializers.Serializer):
    """Sprint 159 §2 — managers AND workers in ONE request.

    Two shapes are accepted and both resolve to the same thing, a map of
    role -> user ids:

      {"users": [...], "role": "WORKER"}          the Sprint 157 shape
      {"workers": [...], "managers": [...]}       both roles at once

    The old shape is kept working rather than migrated, because the
    detail page's remove path and the tests already speak it, and a
    write endpoint that changes shape under its existing callers is a
    worse problem than one that accepts two.

    They compose: a body carrying `users` AND `workers` merges them,
    de-duplicated, so no caller has to know which field the other half
    of the UI used.
    """

    requests = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False
    )
    users = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False
    )
    role = serializers.ChoiceField(
        choices=ExtraWorkAssignmentRole.values, required=False
    )
    workers = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False
    )
    managers = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False
    )
    mode = serializers.ChoiceField(
        choices=["assign", "unassign"], default="assign"
    )

    def validate(self, attrs):
        groups: dict[str, list[int]] = {}

        def add(role: str, ids) -> None:
            if not ids:
                return
            merged = groups.setdefault(role, [])
            merged.extend(i for i in ids if i not in merged)

        add(attrs.get("role") or ExtraWorkAssignmentRole.WORKER, attrs.get("users"))
        add(ExtraWorkAssignmentRole.WORKER, attrs.get("workers"))
        add(ExtraWorkAssignmentRole.MANAGER, attrs.get("managers"))

        if not groups:
            # About an EMPTY body, not about any id — so it says what is
            # missing without becoming an existence oracle.
            raise serializers.ValidationError(
                {"users": ["Name at least one person to assign."]}
            )
        attrs["groups"] = groups
        return attrs


class ExtraWorkBulkAssignView(APIView):
    """POST /api/extra-work/bulk-assign/ — see the module docstring.

    Re-assigning an existing pair is NOT an error: it counts as
    `already_assigned`, so pressing the button twice is safe. Same
    property the Sprint 154 bulk-link family has.
    """

    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request, *args, **kwargs):
        # A customer-side user cannot call this at all. `scope_extra_work_for`
        # would already narrow what they can see, but assignment is a
        # provider-side operation end to end and the refusal belongs at
        # the door rather than emerging from an empty resolution.
        if request.user.role not in {
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        }:
            return Response(
                {"detail": "You may not assign people to extra work."},
                status=status.HTTP_403_FORBIDDEN,
            )

        payload = _BulkAssignInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        request_ids = list(dict.fromkeys(payload.validated_data["requests"]))
        groups: dict[str, list[int]] = payload.validated_data["groups"]
        mode = payload.validated_data["mode"]

        # (1) Requests, through the actor's own extra-work scope.
        requests = {
            r.id: r
            for r in scope_extra_work_for(request.user).filter(id__in=request_ids)
        }
        if len(requests) != len(request_ids):
            _reject()

        # (2) People, per REQUEST and per ROLE, because eligibility is a
        # property of the request's BUILDING and differs between the two
        # roles. Assigning the same person to two requests at different
        # buildings therefore requires them to be eligible at BOTH —
        # which is the correct reading of "the authorised people at that
        # building", and the reason this loop is not hoisted out.
        #
        # An id that is not eligible is rejected with the SAME body as an
        # id that does not exist. That is not a nicety: a distinguishable
        # answer here would let a caller enumerate who works where (H-1).
        #
        # Sprint 159 §2 — every group is resolved BEFORE any write, so a
        # body naming both roles is still all-or-nothing: an ineligible
        # manager rejects the workers with it rather than leaving half a
        # crew on the job.
        pairs = []
        for extra_work in requests.values():
            for role, user_ids in groups.items():
                eligible = resolve_assignable_users(
                    extra_work.building, role, user_ids, request.user
                )
                if len(eligible) != len(user_ids):
                    _reject()
                for user in eligible.values():
                    pairs.append((extra_work, user, role))

        try:
            audit_context.set_current_reason(
                f"extra_work_bulk_{mode}_"
                + "_".join(sorted(role.lower() for role in groups))
            )
        except Exception:  # pragma: no cover - defensive
            pass

        created = removed = already = not_assigned = 0
        with transaction.atomic():
            for extra_work, user, role in pairs:
                existing = ExtraWorkAssignment.objects.filter(
                    extra_work_request=extra_work, user=user, role=role
                ).first()
                if mode == "assign":
                    if existing is not None:
                        already += 1
                        continue
                    # objects.create() fires post_save, so the audit row
                    # is written. bulk_create would not.
                    ExtraWorkAssignment.objects.create(
                        extra_work_request=extra_work,
                        user=user,
                        role=role,
                        assigned_by=request.user,
                    )
                    created += 1
                else:
                    if existing is None:
                        not_assigned += 1
                        continue
                    # Instance .delete() fires post_delete per row.
                    existing.delete()
                    removed += 1

        return Response(
            {
                "created": created,
                "removed": removed,
                "already_assigned": already,
                "not_assigned": not_assigned,
            },
            status=status.HTTP_200_OK,
        )


class _AssignmentRowSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    user_full_name = serializers.CharField(
        source="user.full_name", read_only=True
    )
    # `User.phone` — the ungated account field. Never `StaffProfile.phone`,
    # which is customer-visibility-gated (Sprint 154 §K's privacy floor).
    user_phone = serializers.CharField(source="user.phone", read_only=True)
    user_role = serializers.CharField(source="user.role", read_only=True)

    class Meta:
        model = ExtraWorkAssignment
        fields = [
            "id",
            "extra_work_request",
            "user_id",
            "user_email",
            "user_full_name",
            "user_phone",
            "user_role",
            "role",
            "assigned_at",
        ]
        read_only_fields = fields


class ExtraWorkAssignmentListView(APIView):
    """GET /api/extra-work/<id>/assignments/ — who is on this request."""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, pk: int, *args, **kwargs):
        from django.shortcuts import get_object_or_404

        # Scoped resolution: a request the actor may not see is a 404,
        # never a 403.
        extra_work = get_object_or_404(
            scope_extra_work_for(request.user), pk=pk
        )
        rows = (
            ExtraWorkAssignment.objects.filter(extra_work_request=extra_work)
            .select_related("user")
            .order_by("role", "user__full_name", "user__email")
        )
        return Response(
            _AssignmentRowSerializer(rows, many=True).data,
            status=status.HTTP_200_OK,
        )


class ExtraWorkAssignableUsersView(APIView):
    """GET /api/extra-work/<id>/assignments/candidates/?role=WORKER|MANAGER

    The picker's source, and the SAME helper the write validator uses.

    Sprint 152.1 §1a is the lesson this exists for: when the list an
    operator picks from and the list the server accepts are computed
    separately, they drift, and the operator gets options that always
    fail. One helper means "offerable" and "acceptable" cannot disagree —
    and `test_sprint158_assignment_eligibility` walks this endpoint's
    entire output through the assign endpoint to prove it.
    """

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, pk: int, *args, **kwargs):
        if request.user.role not in {
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        }:
            return Response(
                {"detail": "You may not assign people to extra work."},
                status=status.HTTP_403_FORBIDDEN,
            )
        role = request.query_params.get("role", ExtraWorkAssignmentRole.WORKER)
        if role not in ExtraWorkAssignmentRole.values:
            raise serializers.ValidationError(
                {"role": ["Unknown assignment role."]}
            )
        # Scoped resolution: a request the actor may not see is a 404,
        # never a 403.
        extra_work = get_object_or_404(
            scope_extra_work_for(request.user), pk=pk
        )
        users = eligible_users_for_building(
            extra_work.building, role, request.user
        )
        return Response(
            [
                {
                    "id": user.id,
                    "email": user.email,
                    "full_name": user.full_name,
                    "role": user.role,
                }
                for user in users
            ],
            status=status.HTTP_200_OK,
        )
