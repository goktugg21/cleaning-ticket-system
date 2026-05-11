"""
Sprint 23A — customer-side permission resolution.

Resolves a permission key against a CustomerUserBuildingAccess
row's `access_role` and `permission_overrides`. A missing override
falls back to the role default; an `is_active=False` row resolves
every permission to False.

The full key list lives in
docs/architecture/sprint-23a-domain-permissions-foundation.md.
This module is intentionally small: a dict of role defaults + a
single resolver function. Sprint 23B may grow it into a manager
class with caching once admin UI starts using it heavily.
"""
from __future__ import annotations

from typing import Iterable, Optional

from .models import CustomerUserBuildingAccess


# Sprint 23A canonical customer-side permission keys. Listed
# explicitly so an IDE / test / admin UI can autocomplete; the
# resolver itself does not require a key to live in this set
# (returns False for unknown keys after falling through).
CUSTOMER_PERMISSION_KEYS: frozenset[str] = frozenset(
    {
        "customer.ticket.create",
        "customer.ticket.view_own",
        "customer.ticket.view_location",
        "customer.ticket.view_company",
        "customer.ticket.approve_own",
        "customer.ticket.approve_location",
        "customer.extra_work.create",
        "customer.extra_work.view_own",
        "customer.extra_work.view_location",
        "customer.extra_work.view_company",
        "customer.extra_work.approve_own",
        "customer.extra_work.approve_location",
        "customer.users.invite",
        "customer.users.manage",
        "customer.users.assign_location_role",
        "customer.users.manage_permissions",
    }
)


# Per-role default grants. Anything missing from a role's set
# defaults to False. Sprint 23B is expected to flesh out the
# extra_work.* keys once that workflow lands; today they mirror
# the customer.ticket.* shape so the resolver returns sane
# answers for early integration code.
_TICKET_ROLE_DEFAULTS: dict[str, frozenset[str]] = {
    CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER: frozenset(
        {
            "customer.ticket.create",
            "customer.ticket.view_own",
            "customer.ticket.approve_own",
            "customer.extra_work.create",
            "customer.extra_work.view_own",
            "customer.extra_work.approve_own",
        }
    ),
    CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER: frozenset(
        {
            "customer.ticket.create",
            "customer.ticket.view_own",
            "customer.ticket.view_location",
            "customer.ticket.approve_own",
            "customer.ticket.approve_location",
            "customer.extra_work.create",
            "customer.extra_work.view_own",
            "customer.extra_work.view_location",
            "customer.extra_work.approve_own",
            "customer.extra_work.approve_location",
            "customer.users.assign_location_role",
        }
    ),
    CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN: frozenset(
        # COMPANY_ADMIN gets everything the role layer can grant.
        # Specific revocations are still possible via overrides.
        {
            "customer.ticket.create",
            "customer.ticket.view_own",
            "customer.ticket.view_location",
            "customer.ticket.view_company",
            "customer.ticket.approve_own",
            "customer.ticket.approve_location",
            "customer.extra_work.create",
            "customer.extra_work.view_own",
            "customer.extra_work.view_location",
            "customer.extra_work.view_company",
            "customer.extra_work.approve_own",
            "customer.extra_work.approve_location",
            "customer.users.invite",
            "customer.users.manage",
            "customer.users.assign_location_role",
            "customer.users.manage_permissions",
        }
    ),
}


def role_default(access_role: str, permission_key: str) -> bool:
    """Return the per-role default for `permission_key` (True/False)."""
    return permission_key in _TICKET_ROLE_DEFAULTS.get(access_role, frozenset())


def access_has_permission(
    access: CustomerUserBuildingAccess, permission_key: str
) -> bool:
    """
    Resolve a permission key against a single access row.

    Rules:
      1. If the access row is inactive, every key resolves to False.
      2. If `permission_overrides` contains the key, the boolean
         value of the override wins (True = grant, False = revoke).
      3. Otherwise, the per-role default applies.
    """
    if not access.is_active:
        return False
    overrides = access.permission_overrides or {}
    if permission_key in overrides:
        return bool(overrides[permission_key])
    return role_default(access.access_role, permission_key)


def any_access_has_permission(
    accesses: Iterable[CustomerUserBuildingAccess], permission_key: str
) -> bool:
    """True if at least one access row resolves the key to True."""
    return any(access_has_permission(a, permission_key) for a in accesses)


def user_can(
    user,
    customer_id: int,
    building_id: Optional[int],
    permission_key: str,
) -> bool:
    """
    Convenience: resolve a permission for a (user, customer, building)
    tuple. When `building_id` is None the resolver succeeds if ANY of
    the user's active access rows under that customer grants the
    permission (used for "view_company" decisions which span
    buildings).
    """
    if user is None or not user.is_authenticated:
        return False
    accesses = CustomerUserBuildingAccess.objects.filter(
        membership__user=user,
        membership__customer_id=customer_id,
    )
    if building_id is not None:
        accesses = accesses.filter(building_id=building_id)
    return any_access_has_permission(accesses, permission_key)
