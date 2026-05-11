"""
Sprint 23A — service-provider-side permission resolution
("OSIUS-side").

The existing `accounts/permissions.py` defines DRF permission
classes for the four-role world. Sprint 23A adds finer-grain
permission keys for the STAFF role and for staff-assignment-request
review. This module is the resolver; the DRF permission classes
that consume it live in the individual app views.

Keys live in
docs/architecture/sprint-23a-domain-permissions-foundation.md.
The resolver is intentionally tiny — Sprint 23B may extend if
admin UI starts editing per-user overrides.
"""
from __future__ import annotations

from typing import Optional

from buildings.models import BuildingManagerAssignment, BuildingStaffVisibility

from .models import UserRole


OSIUS_PERMISSION_KEYS: frozenset[str] = frozenset(
    {
        "osius.ticket.view_building",
        "osius.ticket.assign_staff",
        "osius.ticket.manager_review",
        "osius.staff.view_building_work",
        "osius.staff.request_assignment",
        "osius.staff.complete_assigned_work",
        "osius.assignment_request.approve",
        "osius.assignment_request.reject",
        "osius.staff.manage",
        "osius.building.manage",
        "osius.customer_company.manage",
    }
)


def user_has_osius_permission(
    user,
    permission_key: str,
    *,
    building_id: Optional[int] = None,
) -> bool:
    """
    Resolve an OSIUS-side permission for `user`. SUPER_ADMIN and
    COMPANY_ADMIN are global; BUILDING_MANAGER and STAFF are
    building-scoped via the membership/visibility tables.

    Where the answer depends on a building (e.g. a manager only
    reviews requests for their own buildings), pass `building_id`.
    When `building_id` is None and the key is building-scoped, the
    resolver returns True if the user can act in AT LEAST ONE
    building they touch.
    """
    if user is None or not user.is_authenticated:
        return False
    if user.role == UserRole.SUPER_ADMIN:
        # SUPER_ADMIN has every osius.* permission by definition.
        return True
    if user.role == UserRole.COMPANY_ADMIN:
        # Company admins see and manage everything inside their
        # service-provider company. Building-scoped is implicit.
        return True

    if user.role == UserRole.BUILDING_MANAGER:
        # Building-scoped manager permissions.
        if permission_key in {
            "osius.ticket.view_building",
            "osius.ticket.assign_staff",
            "osius.ticket.manager_review",
            "osius.assignment_request.approve",
            "osius.assignment_request.reject",
            "osius.staff.view_building_work",
        }:
            if building_id is None:
                return BuildingManagerAssignment.objects.filter(
                    user=user
                ).exists()
            return BuildingManagerAssignment.objects.filter(
                user=user, building_id=building_id
            ).exists()
        return False

    if user.role == UserRole.STAFF:
        if permission_key == "osius.staff.complete_assigned_work":
            # Staff can always complete tickets they are
            # explicitly assigned to. The check at use-site needs
            # to verify the ticket's assignment list contains them.
            return True
        if permission_key in {
            "osius.staff.view_building_work",
            "osius.ticket.view_building",
        }:
            if building_id is None:
                return BuildingStaffVisibility.objects.filter(
                    user=user
                ).exists()
            return BuildingStaffVisibility.objects.filter(
                user=user, building_id=building_id
            ).exists()
        if permission_key == "osius.staff.request_assignment":
            # The staff profile + per-building visibility BOTH
            # need to allow it.
            profile = getattr(user, "staff_profile", None)
            if profile is None or not profile.is_active:
                return False
            if not profile.can_request_assignment:
                return False
            qs = BuildingStaffVisibility.objects.filter(
                user=user, can_request_assignment=True
            )
            if building_id is not None:
                qs = qs.filter(building_id=building_id)
            return qs.exists()
        return False

    return False
