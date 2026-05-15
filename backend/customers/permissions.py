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

Sprint 27D — wires the new `CustomerCompanyPolicy` permission
booleans into resolution as a deny-layer that sits BETWEEN the
explicit `permission_overrides` and the per-`access_role`
defaults. Documented precedence (high → low):

  1. `access.is_active=False` → False (Sprint 23A short-circuit).
  2. Key present in `permission_overrides` → that value (Sprint 23A).
  3. Customer's `CustomerCompanyPolicy` field for the key's family
     is False → False (Sprint 27D — closes G-B5).
  4. Otherwise → per-`access_role` default (Sprint 23A).

Override-wins-over-policy is the chosen precedence: an explicit
override is an intentional operator opt-in/opt-out for ONE user
and represents the operator's more-specific intent, so it beats
the company-wide policy default. The policy field can only NARROW
role defaults; it never grants a key the role default doesn't
already grant. This keeps the policy's blast radius bounded.
"""
from __future__ import annotations

from typing import Iterable, Optional

from .models import CustomerCompanyPolicy, CustomerUserBuildingAccess


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


# Sprint 27D — closes G-B5 (runtime wiring half).
#
# Maps a customer-side permission key to the CustomerCompanyPolicy
# boolean field whose False value denies that key. A key that is NOT
# in this map is outside the policy's blast radius — only role
# defaults + explicit overrides decide it. The mapping is one-to-many
# from policy field to keys (e.g. approve_ticket_completion denies
# both approve_own and approve_location).
_POLICY_FAMILY_FIELD: dict[str, str] = {
    "customer.ticket.create": "customer_users_can_create_tickets",
    "customer.ticket.approve_own": (
        "customer_users_can_approve_ticket_completion"
    ),
    "customer.ticket.approve_location": (
        "customer_users_can_approve_ticket_completion"
    ),
    "customer.extra_work.create": "customer_users_can_create_extra_work",
    "customer.extra_work.approve_own": (
        "customer_users_can_approve_extra_work_pricing"
    ),
    "customer.extra_work.approve_location": (
        "customer_users_can_approve_extra_work_pricing"
    ),
}


def _policy_denies(access: CustomerUserBuildingAccess, permission_key: str) -> bool:
    """Return True iff the customer's CustomerCompanyPolicy explicitly
    denies the key's family.

    Lookup is keyed by `access.membership.customer_id` so the policy
    that applies is ALWAYS the one anchored at the access row's own
    customer — never the caller-supplied customer_id. Defends in
    depth against any future call site that mismatches anchors.

    Missing policy rows (theoretical only — the Sprint 27C migration
    + auto-create signal guarantee every Customer has one) are
    treated as "policy True for every family", so resolution falls
    through to the role default unchanged.
    """
    field = _POLICY_FAMILY_FIELD.get(permission_key)
    if field is None:
        return False
    # `.filter(...).values(field).first()` keeps this to a single
    # column lookup. The policy row exists for every Customer thanks
    # to the Sprint 27C backfill + post_save auto-create.
    row = (
        CustomerCompanyPolicy.objects.filter(
            customer_id=access.membership.customer_id
        )
        .values(field)
        .first()
    )
    if row is None:
        return False
    return row[field] is False


def access_has_permission(
    access: CustomerUserBuildingAccess, permission_key: str
) -> bool:
    """
    Resolve a permission key against a single access row.

    Rules (precedence high → low):
      1. If the access row is inactive, every key resolves to False.
      2. If `permission_overrides` contains the key, the boolean
         value of the override wins (True = grant, False = revoke).
      3. Sprint 27D: if the customer's CustomerCompanyPolicy field
         for this key's family is False, return False. The policy
         can only NARROW role defaults.
      4. Otherwise, the per-role default applies.
    """
    if not access.is_active:
        return False
    overrides = access.permission_overrides or {}
    if permission_key in overrides:
        return bool(overrides[permission_key])
    if _policy_denies(access, permission_key):
        return False
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
