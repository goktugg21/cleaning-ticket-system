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

from buildings.models import (
    Building,
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
from companies.models import Company, CompanyUserMembership

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
        # B6 — Building Manager defaults that the operator can revoke
        # per-(BM, building) via `BuildingManagerAssignment.
        # permission_overrides`. Both default to True for any BM assigned
        # to a building; an explicit False entry in the overrides map
        # narrows the default to False for that specific (BM, building)
        # pair. SUPER_ADMIN and COMPANY_ADMIN always resolve True for
        # these keys — they have the same powers by virtue of their
        # higher role. The two keys are write-allowed via the new
        # `PATCH /api/buildings/<bid>/managers/<uid>/` endpoint
        # (SA/COMPANY_ADMIN only).
        "osius.building_manager.override_customer_decision",
        "osius.building_manager.prepare_extra_work_proposal",
    }
)


# B6 — the subset of `OSIUS_PERMISSION_KEYS` that is editable through
# `BuildingManagerAssignment.permission_overrides`. The write surface
# (`BuildingManagerAssignmentUpdateSerializer.validate_permission_overrides`)
# rejects every other key to prevent scope-bleed via the override map.
BM_REVOCABLE_PERMISSION_KEYS: frozenset[str] = frozenset(
    {
        "osius.building_manager.override_customer_decision",
        "osius.building_manager.prepare_extra_work_proposal",
    }
)


# Sprint 27D — closes G-B9.
#
# These three keys had been declared in OSIUS_PERMISSION_KEYS since
# Sprint 23A but were never narrowed: COMPANY_ADMIN's universal
# "return True" branch granted them globally, which left a latent
# cross-provider leak waiting for the first call site to pass a
# building_id from another provider. The set below scopes them so:
#
#   * SUPER_ADMIN keeps universal True (unchanged).
#   * COMPANY_ADMIN gets them only inside their own provider company
#     (membership-anchored; building_id, if provided, must belong
#     to one of their companies).
#   * BUILDING_MANAGER / STAFF / CUSTOMER_USER stay False — these
#     are explicitly company-level management keys and live above
#     the building-manager pay grade by design.
_PROVIDER_MANAGEMENT_KEYS: frozenset[str] = frozenset(
    {
        "osius.staff.manage",
        "osius.building.manage",
        "osius.customer_company.manage",
    }
)


def _company_admin_has_management_key(
    user, building_id: Optional[int]
) -> bool:
    """Sprint 27D — narrowed COMPANY_ADMIN handler for the three
    management keys. Returns True iff the actor is a member of at
    least one provider company AND (when `building_id` is given)
    that building's company is one of the actor's companies.
    """
    actor_company_ids = list(
        CompanyUserMembership.objects.filter(user=user).values_list(
            "company_id", flat=True
        )
    )
    if not actor_company_ids:
        return False
    if building_id is None:
        return True
    return Building.objects.filter(
        id=building_id, company_id__in=actor_company_ids
    ).exists()


# ---------------------------------------------------------------------------
# Sprint 14E — DANGEROUS provider-side quote-bypass permission.
#
# Distinct namespace (`provider.*`) from the operational `osius.*` keys
# because this is a SoT §5.5 dangerous capability with its own grant
# surface, default-OFF semantics, and HIGH-severity audit. It is
# explicitly NOT in `OSIUS_PERMISSION_KEYS`, so the generic osius
# resolver / matrix never grants it and holding the generic B6
# `osius.building_manager.override_customer_decision` key can never
# imply it (matrix H-11 + SoT §5.5 "this is dangerous").
#
# Grant model: a single Super-Admin-controlled boolean on the provider
# `Company` (`provider_admin_may_quote_override_start`, default False).
#   * SUPER_ADMIN          -> always True (omnipotent + the grant
#                             authority). Use is still HIGH-audited.
#   * COMPANY_ADMIN        -> True iff a provider company they belong to
#                             (CompanyUserMembership) has the grant ON.
#   * BUILDING_MANAGER     -> True iff a provider company that owns a
#                             building they manage has the grant ON.
#   * STAFF / CUSTOMER_USER-> always False.
#
# Even CA / BM need the dedicated grant — neither silently bypasses
# (SoT §2.1 "dangerous permissions default OFF").
# ---------------------------------------------------------------------------
PROVIDER_DANGEROUS_PERMISSION_KEYS: frozenset[str] = frozenset(
    {
        "provider.extra_work.quote_override_start",
    }
)


def user_has_provider_dangerous_permission(
    user,
    permission_key: str,
    *,
    company_id: Optional[int] = None,
) -> bool:
    """Resolve a `provider.*` dangerous permission for `user`.

    When `company_id` is given the grant is checked against THAT
    provider company (the canonical call from the direct-publish view,
    anchored on the Extra Work's company). When it is None the key
    resolves True if ANY provider company the actor belongs to / manages
    has the grant ON (the surface used by the effective-permissions
    composer, which has no company context).
    """
    if user is None or not user.is_authenticated:
        return False
    if permission_key not in PROVIDER_DANGEROUS_PERMISSION_KEYS:
        return False
    if user.role == UserRole.SUPER_ADMIN:
        return True

    if user.role == UserRole.COMPANY_ADMIN:
        granted = Company.objects.filter(
            user_memberships__user=user,
            provider_admin_may_quote_override_start=True,
        )
        if company_id is not None:
            granted = granted.filter(id=company_id)
        return granted.exists()

    if user.role == UserRole.BUILDING_MANAGER:
        # BM is in scope of a company iff they manage one of its
        # buildings. The grant is company-level, so a BM at a granted
        # company inherits it (still narrowed to their assigned
        # buildings' company).
        granted = Company.objects.filter(
            buildings__manager_assignments__user=user,
            provider_admin_may_quote_override_start=True,
        )
        if company_id is not None:
            granted = granted.filter(id=company_id)
        return granted.exists()

    # STAFF / CUSTOMER_USER: never.
    return False


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
        # Sprint 27D (closes G-B9): the three provider-management
        # keys are narrowed to the actor's own provider company.
        # Every other osius.* key keeps the pre-27D universal True
        # behavior for COMPANY_ADMIN — call sites that need a
        # building-scoped check already pass `building_id` and the
        # downstream scoping helpers do the queryset filtering.
        if permission_key in _PROVIDER_MANAGEMENT_KEYS:
            return _company_admin_has_management_key(user, building_id)
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
        # B6 — BM-revocable defaults. Default is True iff BM is assigned
        # to the building; an explicit `False` in the assignment's
        # `permission_overrides[key]` narrows the default. Missing key
        # or non-False value (including `True`) means "use the default".
        if permission_key in BM_REVOCABLE_PERMISSION_KEYS:
            qs = BuildingManagerAssignment.objects.filter(user=user)
            if building_id is not None:
                assignment = qs.filter(building_id=building_id).first()
                if assignment is None:
                    return False
                override_value = (
                    assignment.permission_overrides or {}
                ).get(permission_key)
                if override_value is False:
                    return False
                return True
            # No building_id: True iff at least one assigned building
            # resolves the key True. Iterate so per-row overrides apply.
            for assignment in qs:
                override_value = (
                    assignment.permission_overrides or {}
                ).get(permission_key)
                if override_value is not False:
                    return True
            return False
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
