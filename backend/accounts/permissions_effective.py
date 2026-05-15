"""
Sprint 27B — effective-permission composer service.

Read-only facade over the two existing permission resolvers:

  * Provider side: `accounts.permissions_v2.user_has_osius_permission`
    keyed on `OSIUS_PERMISSION_KEYS`.
  * Customer side: `customers.permissions.user_can` keyed on
    `CUSTOMER_PERMISSION_KEYS` (which itself walks
    `access_has_permission` over the user's
    `CustomerUserBuildingAccess` rows, honouring per-row
    `permission_overrides` JSON and the `is_active` short-circuit).

This module **introduces no new permission rules**. It does not
invent keys. It does not broaden any scope. Its only job is to
give the rest of the codebase a single entry point that:

  1. Recognises the namespace of a permission key
     (`osius.*` → provider resolver, `customer.*` → customer
     resolver), and
  2. Returns the deterministic answer that the underlying
     resolver would return for the same actor / context.

Shadow / parity tests live at
`accounts/tests/test_sprint27b_effective_permissions.py` and pin
the composer ≡ underlying-resolver invariant for every known key
across representative actors.

Why this exists:
  * Future call sites (the deferred permission-override editor
    in Sprint 27C, future report scoping, etc.) can consume one
    API instead of branching on namespace at the call site.
  * The unified `effective_permissions(user, …)` dict shape is
    a natural input for an admin / debug surface that needs to
    show "what can this user actually do here" without
    duplicating the resolver branching logic.

Hard invariants preserved (per
docs/architecture/sprint-27-rbac-matrix.md):

  * Anonymous users get False for every key.
  * Unknown keys (outside both frozensets) get False.
  * `customer.*` keys without a `customer_id` get False — they
    are inherently per-(customer, building) so there is no
    meaningful answer without that context.
  * Provider-side roles (SUPER_ADMIN / COMPANY_ADMIN /
    BUILDING_MANAGER / STAFF) never collect customer-side keys
    via this composer (they have no CustomerUserBuildingAccess
    rows, so the underlying resolver returns False — the
    composer forwards that).
  * Cross-customer / cross-provider context leakage is
    impossible because the composer never widens the underlying
    resolver's reach.

Sprint 27B intentionally **does not migrate any existing call
site** to this service. Doing so creates risk without a present
consumer; the service is read-only and behaviorally equivalent
to the resolvers it composes, so swapping a call site is a
no-op in terms of runtime semantics. The deferred migration is
documented in `docs/architecture/sprint-27-rbac-matrix.md` under
the Sprint 27B follow-up notes.
"""
from __future__ import annotations

from typing import Optional

from accounts.permissions_v2 import (
    OSIUS_PERMISSION_KEYS,
    user_has_osius_permission,
)
from customers.permissions import (
    CUSTOMER_PERMISSION_KEYS,
    user_can,
)


def has_permission(
    user,
    key: str,
    *,
    customer_id: Optional[int] = None,
    building_id: Optional[int] = None,
) -> bool:
    """
    Return True iff `user` has `key` in the given context.

    Routing rules:
      * If `key` is in `OSIUS_PERMISSION_KEYS` → delegate to
        `user_has_osius_permission(user, key, building_id=...)`.
        `building_id` may be None for keys that are global to
        the provider company (the underlying resolver handles
        that case).
      * If `key` is in `CUSTOMER_PERMISSION_KEYS` → delegate to
        `user_can(user, customer_id, building_id, key)`. If
        `customer_id` is None we return False — customer-side
        permissions are inherently per-(customer, building) and
        there is no defensible default answer for an unspecified
        customer.
      * Otherwise (unknown key) → False.

    Anonymous / unauthenticated users always get False; both
    underlying resolvers already enforce that, but the composer
    short-circuits at the top to make the contract explicit.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False

    if key in OSIUS_PERMISSION_KEYS:
        return user_has_osius_permission(user, key, building_id=building_id)

    if key in CUSTOMER_PERMISSION_KEYS:
        if customer_id is None:
            return False
        return user_can(user, customer_id, building_id, key)

    return False


def effective_permissions(
    user,
    *,
    customer_id: Optional[int] = None,
    building_id: Optional[int] = None,
) -> dict[str, bool]:
    """
    Return a `{key: bool}` dict covering every known permission
    key (`OSIUS_PERMISSION_KEYS` ∪ `CUSTOMER_PERMISSION_KEYS`).

    The value for each key is exactly what `has_permission` would
    return for that (user, key, customer_id, building_id) tuple,
    which means the dict is deterministic and side-effect-free.

    Useful for admin / debug surfaces that need to show "what
    can this user actually do here" without re-implementing the
    namespace branching at the call site.
    """
    result: dict[str, bool] = {}
    for key in OSIUS_PERMISSION_KEYS:
        result[key] = has_permission(
            user, key, customer_id=customer_id, building_id=building_id
        )
    for key in CUSTOMER_PERMISSION_KEYS:
        result[key] = has_permission(
            user, key, customer_id=customer_id, building_id=building_id
        )
    return result
