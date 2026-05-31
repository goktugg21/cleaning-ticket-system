"""
Sprint 3B — provider-catalog scope helpers.

Two questions this module answers, in one place, for the catalog
view layer + the role-aware ServiceSerializer:

  1. Which provider-company ids is THIS actor allowed to see catalog
     rows for? `scope_company_ids_for_catalog(user)` returns the
     id set.
  2. May THIS actor see `default_unit_price` / `default_vat_pct`
     for a given Service? `can_view_provider_defaults(user, service)`
     answers True/False.

Role logic (matches Sprint 3B spec):

  * SUPER_ADMIN: all companies; sees defaults everywhere.
  * COMPANY_ADMIN: companies they hold a `CompanyUserMembership`
    in; sees defaults for those companies.
  * BUILDING_MANAGER: companies of any building they are
    assigned to via `BuildingManagerAssignment`; sees defaults
    for those companies (BM is provider-side personnel, and SoT
    §5.8 explicitly grants BM view of provider defaults by default).
  * STAFF: company of any building they have visibility on via
    `BuildingStaffVisibility`; **never** sees defaults.
  * CUSTOMER_USER (any access role): companies of any
    `Customer` they hold an active `CustomerUserBuildingAccess`
    row for (via the `CustomerUserMembership.customer` link);
    **never** sees defaults.

Anonymous / unauthenticated: empty scope, no defaults.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Optional

from accounts.models import UserRole

if TYPE_CHECKING:  # pragma: no cover - typing only
    from companies.models import Company

    from .models import Service


# ---------------------------------------------------------------------------
# Scope (queryset visibility)
# ---------------------------------------------------------------------------
def scope_company_ids_for_catalog(user) -> Optional[frozenset[int]]:
    """Return the set of `companies.Company` ids whose catalog rows
    are visible to `user`.

    Returns `None` to signal "no scope filter" (SUPER_ADMIN). The
    caller treats `None` as "do not filter the queryset"; a real
    `frozenset()` (possibly empty) is treated as "filter to these
    ids" (empty ⇒ no rows visible).
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return frozenset()

    role = getattr(user, "role", None)

    if role == UserRole.SUPER_ADMIN:
        return None

    if role == UserRole.COMPANY_ADMIN:
        from companies.models import CompanyUserMembership

        return frozenset(
            CompanyUserMembership.objects.filter(user=user).values_list(
                "company_id", flat=True
            )
        )

    if role == UserRole.BUILDING_MANAGER:
        from buildings.models import BuildingManagerAssignment

        return frozenset(
            BuildingManagerAssignment.objects.filter(user=user)
            .values_list("building__company_id", flat=True)
            .distinct()
        )

    if role == UserRole.STAFF:
        from buildings.models import BuildingStaffVisibility

        return frozenset(
            BuildingStaffVisibility.objects.filter(user=user)
            .values_list("building__company_id", flat=True)
            .distinct()
        )

    if role == UserRole.CUSTOMER_USER:
        from customers.models import CustomerUserBuildingAccess

        return frozenset(
            CustomerUserBuildingAccess.objects.filter(
                membership__user=user, is_active=True
            )
            .values_list("membership__customer__company_id", flat=True)
            .distinct()
        )

    return frozenset()


def filter_services_for(user, queryset):
    """Apply `scope_company_ids_for_catalog` to a Service / Category
    queryset. Returns the (possibly empty) filtered queryset. SUPER_
    ADMIN gets the queryset back unchanged.
    """
    scope = scope_company_ids_for_catalog(user)
    if scope is None:
        return queryset
    return queryset.filter(company_id__in=scope)


def filter_categories_for(user, queryset):
    """Sprint 3B — ServiceCategory stays GLOBAL (no `company` FK),
    so this helper is the identity. It exists as a hook so a
    future "provider-scoped categories" sprint can flip behaviour
    in one place without revisiting the view layer.

    Anonymous callers still see an empty queryset because the view-
    layer permission classes (IsAuthenticated) reject them before
    this helper is reached.
    """
    return queryset


# ---------------------------------------------------------------------------
# Provider-default-price visibility
# ---------------------------------------------------------------------------
def can_view_provider_defaults(user, service: "Service") -> bool:
    """Return True iff `user` is allowed to see this Service's
    `default_unit_price` and `default_vat_pct`.

    Rule (SoT §5.7 / §5.8):
      * SUPER_ADMIN: True.
      * COMPANY_ADMIN of `service.company`: True.
      * BUILDING_MANAGER assigned to any building in
        `service.company`: True.
      * STAFF: False. (Even if STAFF can see the row exists, the
        price fields are stripped.)
      * CUSTOMER_USER: False. (Same.)
      * Provider operators outside `service.company`: False.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    role = getattr(user, "role", None)
    if role == UserRole.SUPER_ADMIN:
        return True
    if role not in {UserRole.COMPANY_ADMIN, UserRole.BUILDING_MANAGER}:
        return False
    scope = scope_company_ids_for_catalog(user)
    if scope is None:
        return True
    return service.company_id in scope


def can_manage_catalog(user, company) -> bool:
    """Return True iff `user` may CRUD a Service / ServiceCategory
    row owned by `company`.

    Rule:
      * SUPER_ADMIN: True.
      * COMPANY_ADMIN of `company` AND
        `company.provider_admin_may_manage_catalog`: True.
      * Anyone else: False.

    Callers that need to surface a specific 403 code differentiate
    between "wrong company" and "policy disabled" by checking the
    membership themselves; this helper only returns the boolean.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    role = getattr(user, "role", None)
    if role == UserRole.SUPER_ADMIN:
        return True
    if role != UserRole.COMPANY_ADMIN:
        return False
    if not company.provider_admin_may_manage_catalog:
        return False
    from companies.models import CompanyUserMembership

    return CompanyUserMembership.objects.filter(
        user=user, company=company
    ).exists()


def can_manage_customer_prices(user, company) -> bool:
    """Return True iff `user` may CRUD a CustomerServicePrice row
    on a customer under `company`. Mirrors `can_manage_catalog`
    but reads the `provider_admin_may_manage_customer_prices`
    toggle.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    role = getattr(user, "role", None)
    if role == UserRole.SUPER_ADMIN:
        return True
    if role != UserRole.COMPANY_ADMIN:
        return False
    if not company.provider_admin_may_manage_customer_prices:
        return False
    from companies.models import CompanyUserMembership

    return CompanyUserMembership.objects.filter(
        user=user, company=company
    ).exists()
