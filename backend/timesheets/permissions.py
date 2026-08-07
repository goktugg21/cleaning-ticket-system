"""
Sprint 152 — permission layer for the timesheets module.

Deliberately ROLE-BASED, with NO new `osius.*` permission keys in v1.
Two reasons, and they are not "we ran out of time": the module has
exactly two permission tiers (own hours / the company's hours), which a
key pair would only restate; and a key that nobody can grant selectively
yet becomes a promise the permission editor has to keep. Per-user keys
are explicitly out of scope for v1 — see the sprint brief — and adding
them later is additive.

Tiers:

  * STAFF / BUILDING_MANAGER — their OWN entries only (list, create,
    edit, delete), while the week is open. They never see another
    employee's entries or name through any endpoint here.
  * COMPANY_ADMIN — everything within their own company: all employees'
    entries, CRUD for anyone, hour-type management, week close/reopen,
    reporting.
  * SUPER_ADMIN — the same, in the company they are working in (the
    company comes from the request — Sprint 149's one-company-at-a-time
    model).
  * CUSTOMER_USER — nothing, ever, on every endpoint. Multipliers are
    wage-adjacent and hour records are personnel data.
"""
from __future__ import annotations

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from accounts.models import UserRole

from .scope import TIMESHEET_MANAGER_ROLES, TIMESHEET_ROLES


# Stable error codes raised from this module.
ERR_TIMESHEET_CROSS_COMPANY = "timesheet_cross_company_forbidden"
ERR_TIMESHEET_EMPLOYEE_FORBIDDEN = "timesheet_employee_forbidden"


class IsTimesheetUser(BasePermission):
    """Any provider-side role may reach the own-hours surface.
    CUSTOMER_USER is denied (403); unauthenticated is denied (401 via
    the DRF default authentication layer).
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.role in set(TIMESHEET_ROLES)


class IsTimesheetManager(BasePermission):
    """SUPER_ADMIN / COMPANY_ADMIN only — the admin surface (all
    employees' entries, hour types, week close/reopen, CSV export).

    BUILDING_MANAGER is deliberately NOT admitted, unlike the reports
    module: a BM manages buildings, and this module's rows are personnel
    records with wage-adjacent weights on them.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.role in set(TIMESHEET_MANAGER_ROLES)


def _enforce_timesheet_management(user, company):
    """Raise `PermissionDenied` with a stable code if `user` may not
    manage timesheet rows owned by `company`. Returns silently when the
    action is allowed.

    Mirrors the SHAPE of `extra_work.views_catalog._enforce_catalog_
    management` — SUPER_ADMIN passes; a COMPANY_ADMIN must hold a
    membership in the target company — but WITHOUT its second branch.
    There is no `Company.provider_admin_may_manage_timesheets` toggle
    and this sprint does not add one: the catalog toggle exists because
    a provider admin editing PRICES is a commercial decision an owner
    may want to withhold, and "may this admin manage their own company's
    hour types" is not that decision. So this helper has exactly one
    failure mode, and the caller gets exactly one code.
    """
    if getattr(user, "role", None) == UserRole.SUPER_ADMIN:
        return
    if getattr(user, "role", None) != UserRole.COMPANY_ADMIN:
        # `IsTimesheetManager` already blocks everyone else with a 403;
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
                    "You may only manage the hours of your own provider "
                    "company."
                ),
                "code": ERR_TIMESHEET_CROSS_COMPANY,
            }
        )
