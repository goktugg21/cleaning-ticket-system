"""
Sprint 157 §2 — assign workers and managers to Extra Work, in bulk.

    POST /api/extra-work/bulk-assign/
    Body: {"requests": [id,...], "users": [id,...],
           "role": "WORKER"|"MANAGER", "mode": "assign"|"unassign"}
    Response: {"created": N, "removed": N,
               "already_assigned": N, "not_assigned": N}

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

Nothing here imports from `tickets`. `TicketStaffAssignment` is the
model this one is shaped after, but extra work and tickets are separate
modules and coupling them would make an extra-work change depend on the
ticket state machine.
"""
from __future__ import annotations

from django.db import transaction
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User, UserRole
from accounts.permissions import IsAuthenticatedAndActive
from accounts.scoping import manageable_user_ids_for
from audit import context as audit_context

from .models import ExtraWorkAssignment, ExtraWorkAssignmentRole
from .scoping import scope_extra_work_for


ERR_BULK_ASSIGN_INVALID = "extra_work_bulk_assign_invalid"

# ONE constant message for every rejection reason. A message that named
# WHICH id failed, or why, would be the oracle this is written to avoid.
_BULK_ASSIGN_INVALID_MESSAGE = (
    "One or more of the selected requests or people could not be "
    "resolved, or cannot be assigned to each other. Nothing was changed."
)

# The two provider-side roles that can do the work. A COMPANY_ADMIN can
# be a MANAGER on a request; a SUPER_ADMIN is not a provider employee and
# is deliberately not assignable, exactly as they cannot have timesheet
# hours of their own.
_ASSIGNABLE_ROLES = frozenset(
    {UserRole.STAFF, UserRole.BUILDING_MANAGER, UserRole.COMPANY_ADMIN}
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


def assignable_users_for(actor, ids):
    """The people `actor` may put on a request, keyed by id.

    An id missing from the returned mapping is rejected, whatever the
    reason — out of scope, wrong role, deleted, inactive, or simply not
    a real id. That collapsing is the point: the caller cannot tell the
    reasons apart.

    CUSTOMER_* roles can never appear here: the role filter admits only
    provider-side roles, so a customer user is unassignable even to a
    request of their own customer.
    """
    qs = User.objects.filter(
        id__in=ids,
        role__in=_ASSIGNABLE_ROLES,
        is_active=True,
        deleted_at__isnull=True,
    )
    allowed = manageable_user_ids_for(actor)
    # `None` means unrestricted (SUPER_ADMIN). Treating it as an empty
    # set would lock out exactly the role that can do everything — the
    # trap Sprint 154 documented on this helper.
    if allowed is not None:
        qs = qs.filter(id__in=allowed)
    return {u.id: u for u in qs}


def user_is_in_company(user, company_id: int) -> bool:
    """Is this person reachable within the request's provider company?

    The three attachments a provider-side person can have, same union the
    company detail page uses (Sprint 156 §1): a COMPANY_ADMIN through
    `CompanyUserMembership`, a BUILDING_MANAGER through their building
    assignments, a STAFF member through building visibility. Asking only
    the membership table would report False for exactly the roles that do
    the work.
    """
    if user.company_memberships.filter(company_id=company_id).exists():
        return True
    if user.building_assignments.filter(
        building__company_id=company_id
    ).exists():
        return True
    return user.building_visibility.filter(
        building__company_id=company_id
    ).exists()


class _BulkAssignInputSerializer(serializers.Serializer):
    requests = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False
    )
    users = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False
    )
    role = serializers.ChoiceField(choices=ExtraWorkAssignmentRole.values)
    mode = serializers.ChoiceField(
        choices=["assign", "unassign"], default="assign"
    )


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
        user_ids = list(dict.fromkeys(payload.validated_data["users"]))
        role = payload.validated_data["role"]
        mode = payload.validated_data["mode"]

        # (1) Requests, through the actor's own extra-work scope.
        requests = {
            r.id: r
            for r in scope_extra_work_for(request.user).filter(id__in=request_ids)
        }
        if len(requests) != len(request_ids):
            _reject()

        # (2) People, through the provider-employee scope.
        users = assignable_users_for(request.user, user_ids)
        if len(users) != len(user_ids):
            _reject()

        # (3) Every pair, before any write. A person who is not reachable
        # within the request's company would be a cross-tenant
        # assignment; it is rejected with the SAME body as any invalid
        # id, and the picker never offers it in the first place.
        pairs = []
        for extra_work in requests.values():
            for user in users.values():
                if not user_is_in_company(user, extra_work.company_id):
                    _reject()
                pairs.append((extra_work, user))

        try:
            audit_context.set_current_reason(
                f"extra_work_bulk_{mode}_{role.lower()}"
            )
        except Exception:  # pragma: no cover - defensive
            pass

        created = removed = already = not_assigned = 0
        with transaction.atomic():
            for extra_work, user in pairs:
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
