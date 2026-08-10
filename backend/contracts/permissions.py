"""
Sprint 160 — permission layer for the contracts module.

Deliberately ROLE-BASED, with NO new `osius.*` permission keys, for the
same reason `timesheets/permissions.py` gives: the module has exactly
two tiers (read the contracts you can see / manage them), which a key
pair would only restate, and a key nobody can grant selectively yet is
a promise the permission editor has to keep. Adding keys later is
additive.

Tiers:

  * BUILDING_MANAGER — READ ONLY, and only the contracts covering a
    building they manage (`scope.filter_contracts_for` applies the
    narrowing; this class applies the read-only half).
  * COMPANY_ADMIN — full management within their own company.
  * SUPER_ADMIN — the same, in the company they are working in (the
    company comes from the request — Sprint 149's one-company-at-a-time
    model).
  * STAFF — nothing. Negotiated prices are not field-staff data.
  * CUSTOMER_USER — nothing, ever, on every endpoint.
"""
from __future__ import annotations

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from accounts.models import UserRole

from .scope import CONTRACT_MANAGER_ROLES, CONTRACT_ROLES


# Stable error codes raised from this module.
ERR_CONTRACT_CROSS_COMPANY = "contract_cross_company_forbidden"


class IsContractReader(BasePermission):
    """SA / CA / BM may reach the read surface. STAFF and every
    customer-side role are denied (403); unauthenticated is denied (401
    via the DRF authentication layer).
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.role in set(CONTRACT_ROLES)


class IsContractManager(BasePermission):
    """SUPER_ADMIN / COMPANY_ADMIN only — every write surface."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.role in set(CONTRACT_MANAGER_ROLES)


def enforce_contract_management(user, company):
    """Raise `PermissionDenied` with a stable code if `user` may not
    manage contracts owned by `company`. Returns silently when allowed.

    Mirrors `timesheets.permissions._enforce_timesheet_management`:
    SUPER_ADMIN passes; a COMPANY_ADMIN must hold a membership in the
    target company. One failure mode, one code.
    """
    if getattr(user, "role", None) == UserRole.SUPER_ADMIN:
        return
    if getattr(user, "role", None) != UserRole.COMPANY_ADMIN:
        # `IsContractManager` already blocks everyone else with a 403;
        # this branch is defensive.
        raise PermissionDenied(detail="Forbidden.")

    from companies.models import CompanyUserMembership

    is_member = CompanyUserMembership.objects.filter(
        user=user, company=company
    ).exists()
    if not is_member:
        raise PermissionDenied(
            detail={
                "detail": (
                    "You may only manage the contracts of your own "
                    "provider company."
                ),
                "code": ERR_CONTRACT_CROSS_COMPANY,
            }
        )
