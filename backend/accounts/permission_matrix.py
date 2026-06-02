"""
Sprint 14B — Permission Matrix Backend Contract (read-side / catalog only).

A read-only catalog of permission-key metadata plus two pure builders
that turn a single grant row (a `CustomerUserBuildingAccess` or a
`BuildingManagerAssignment`) into a list of tri-state matrix rows for an
admin-facing "permission matrix" UI.

Hard constraints honoured here:

  * This module changes NO resolver semantics. `effective` always mirrors
    the live resolver (`customers.permissions.access_has_permission` /
    `accounts.permissions_v2.user_has_osius_permission`). It never
    re-implements precedence.
  * Override-wins-over-policy is the live precedence (see
    `customers/permissions.py` docstring lines 26-31). An explicit
    override True therefore beats a policy deny, and `effective` reports
    that truthfully. `policy_denied` is a SEPARATE, narrower signal that
    flags only the canonical "policy removed an otherwise-granted key"
    case (override None + inherited True + policy restricts the family).
  * No customer.* keys ever appear in a building-manager matrix, and no
    osius.* keys ever appear in a customer matrix. The two target key
    sets are disjoint and locked below.

There is NO registry of human-readable permission metadata in the
codebase today; the small CATALOG below is new descriptive metadata,
not a behavioural source of truth.
"""
from __future__ import annotations

from typing import Optional

from accounts.models import UserRole
from accounts.permissions_v2 import (
    BM_REVOCABLE_PERMISSION_KEYS,
    PROVIDER_DANGEROUS_PERMISSION_KEYS,
    user_has_osius_permission,
)
from customers.permissions import (
    CUSTOMER_PERMISSION_KEYS,
    _POLICY_FAMILY_FIELD,
    _policy_denies,
    access_has_permission,
    role_default,
)


# ---------------------------------------------------------------------------
# Target key sets
# ---------------------------------------------------------------------------

# Customer-side matrix surfaces all 16 customer.* keys. osius.* keys are
# never customer-editable and never appear here.
CUSTOMER_MATRIX_KEYS: tuple[str, ...] = tuple(sorted(CUSTOMER_PERMISSION_KEYS))


# Building-manager matrix surfaces the building-scoped read-only set that
# a BM resolves True for when assigned to the building, PLUS the two
# BM-revocable keys. It EXCLUDES the company-management keys
# (osius.staff.manage / osius.building.manage / osius.customer_company.manage)
# and the STAFF keys (osius.staff.request_assignment /
# osius.staff.complete_assigned_work), and of course every customer.* key.
_BM_BUILDING_SCOPED_KEYS: frozenset[str] = frozenset(
    {
        "osius.ticket.view_building",
        "osius.ticket.assign_staff",
        "osius.ticket.manager_review",
        "osius.assignment_request.approve",
        "osius.assignment_request.reject",
        "osius.staff.view_building_work",
    }
)

BM_MATRIX_KEYS: tuple[str, ...] = tuple(
    sorted(_BM_BUILDING_SCOPED_KEYS | BM_REVOCABLE_PERMISSION_KEYS)
)


# ---------------------------------------------------------------------------
# Catalog — human-readable metadata for every matrix key
# ---------------------------------------------------------------------------


def _category_for(key: str) -> str:
    if key.startswith("customer.ticket.") or key.startswith("osius.ticket."):
        return "tickets"
    if key.startswith("customer.extra_work.") or key.startswith(
        "provider.extra_work."
    ):
        return "extra_work"
    if key.startswith("customer.users."):
        return "users"
    if key.startswith("osius.assignment_request."):
        return "assignment"
    if key.startswith("osius.staff."):
        return "staff"
    if key.startswith("osius.building_manager."):
        return "building_manager"
    # Defensive: should never happen for the locked key sets above.
    return "other"


# label + description per key. Factual, human-readable; not a behavioural
# source of truth.
_CATALOG_TEXT: dict[str, tuple[str, str]] = {
    # customer.ticket.*
    "customer.ticket.create": (
        "Create tickets",
        "Create new tickets for this building.",
    ),
    "customer.ticket.view_own": (
        "View own tickets",
        "View tickets the user created.",
    ),
    "customer.ticket.view_location": (
        "View location tickets",
        "View all tickets at this building / location.",
    ),
    "customer.ticket.view_company": (
        "View company tickets",
        "View tickets across every building of this customer.",
    ),
    "customer.ticket.approve_own": (
        "Approve own tickets",
        "Approve completion of tickets the user created.",
    ),
    "customer.ticket.approve_location": (
        "Approve location tickets",
        "Approve completion of any ticket at this location.",
    ),
    # customer.extra_work.*
    "customer.extra_work.create": (
        "Create extra work",
        "Create extra-work requests for this building.",
    ),
    "customer.extra_work.view_own": (
        "View own extra work",
        "View extra-work requests the user created.",
    ),
    "customer.extra_work.view_location": (
        "View location extra work",
        "View all extra-work requests at this location.",
    ),
    "customer.extra_work.view_company": (
        "View company extra work",
        "View extra-work requests across every building of this customer.",
    ),
    "customer.extra_work.approve_own": (
        "Approve own extra work pricing",
        "Approve pricing on extra-work requests the user created.",
    ),
    "customer.extra_work.approve_location": (
        "Approve location extra work pricing",
        "Approve pricing on any extra-work request at this location.",
    ),
    # customer.users.*
    "customer.users.invite": (
        "Invite customer users",
        "Invite new users into this customer organisation.",
    ),
    "customer.users.manage": (
        "Manage customer users",
        "Manage existing customer users (access, deactivation).",
    ),
    "customer.users.assign_location_role": (
        "Assign location roles",
        "Assign per-building access roles to customer users.",
    ),
    "customer.users.manage_permissions": (
        "Manage customer permissions",
        "Edit per-user permission overrides for customer users.",
    ),
    # osius.ticket.*
    "osius.ticket.view_building": (
        "View building tickets",
        "View tickets at the assigned building.",
    ),
    "osius.ticket.assign_staff": (
        "Assign staff to tickets",
        "Assign field staff to tickets at the assigned building.",
    ),
    "osius.ticket.manager_review": (
        "Manager ticket review",
        "Perform manager review on tickets at the assigned building.",
    ),
    # osius.assignment_request.*
    "osius.assignment_request.approve": (
        "Approve assignment requests",
        "Approve staff assignment requests at the assigned building.",
    ),
    "osius.assignment_request.reject": (
        "Reject assignment requests",
        "Reject staff assignment requests at the assigned building.",
    ),
    # osius.staff.*
    "osius.staff.view_building_work": (
        "View building staff work",
        "View staff work at the assigned building.",
    ),
    # osius.building_manager.*
    "osius.building_manager.override_customer_decision": (
        "Override customer decision",
        "Override a customer's approve/reject decision with a reason.",
    ),
    "osius.building_manager.prepare_extra_work_proposal": (
        "Prepare extra-work proposal",
        "Create and edit extra-work proposals at the assigned building.",
    ),
    # provider.* — Sprint 14E DANGEROUS keys.
    "provider.extra_work.quote_override_start": (
        "Quote-bypass: start work without customer approval",
        "DANGEROUS. Directly publish a Request-a-Quote Extra Work "
        "proposal and start operational work WITHOUT the customer's "
        "approval. Super Admin-granted per provider company; default "
        "off; every use is high-severity audited.",
    ),
}


# Sprint 14E — keys the UI must render with a danger / locked treatment.
DANGEROUS_PERMISSION_KEYS: frozenset[str] = PROVIDER_DANGEROUS_PERMISSION_KEYS


def _catalog_entry(key: str) -> dict:
    label, description = _CATALOG_TEXT.get(key, (key, ""))
    return {
        "label": label,
        "category": _category_for(key),
        "description": description,
        # Sprint 14E — frontend renders dangerous keys with a red /
        # locked treatment (SoT §9.2 / §5.5).
        "dangerous": key in DANGEROUS_PERMISSION_KEYS,
    }


# Public read-only catalog: key -> {label, category, description, dangerous}
# for every customer matrix key, every BM matrix key, AND every provider
# dangerous key.
CATALOG: dict[str, dict] = {
    key: _catalog_entry(key)
    for key in (
        tuple(CUSTOMER_MATRIX_KEYS)
        + tuple(BM_MATRIX_KEYS)
        + tuple(sorted(PROVIDER_DANGEROUS_PERMISSION_KEYS))
    )
}


# Human-readable policy field text for the policy_denied_reason message.
_POLICY_FIELD_LABEL: dict[str, str] = {
    "customer_users_can_create_tickets": "create tickets",
    "customer_users_can_approve_ticket_completion": (
        "approve ticket completion"
    ),
    "customer_users_can_create_extra_work": "create extra work",
    "customer_users_can_approve_extra_work_pricing": (
        "approve extra-work pricing"
    ),
}


# ---------------------------------------------------------------------------
# Stable string sets (pinned by tests)
# ---------------------------------------------------------------------------
SOURCE_OVERRIDE_ALLOW = "override_allow"
SOURCE_OVERRIDE_DENY = "override_deny"
SOURCE_POLICY_DENIED = "policy_denied"
SOURCE_INHERITED = "inherited"

READ_ONLY_REASON_POLICY_DENIED = "policy_denied"
READ_ONLY_REASON_ACTOR_NOT_ALLOWED = "actor_not_allowed"
READ_ONLY_REASON_SYSTEM_MANAGED = "system_managed"
READ_ONLY_REASON_SELF_EDIT_FORBIDDEN = "self_edit_forbidden"

POLICY_DENIED_CODE = "customer_company_policy_denied"


_EDIT_ROLES = frozenset({UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN})


def _row(
    *,
    key: str,
    inherited: bool,
    override: Optional[bool],
    effective: bool,
    source: str,
    grantable: bool,
    read_only: bool,
    read_only_reason: Optional[str],
    policy_denied: bool,
    policy_denied_reason: Optional[dict],
) -> dict:
    entry = CATALOG[key]
    return {
        "key": key,
        "label": entry["label"],
        "category": entry["category"],
        "description": entry["description"],
        "inherited": inherited,
        "override": override,
        "effective": effective,
        "source": source,
        "grantable": grantable,
        "read_only": read_only,
        "read_only_reason": read_only_reason,
        "policy_denied": policy_denied,
        "policy_denied_reason": policy_denied_reason,
    }


# ---------------------------------------------------------------------------
# Customer matrix builder
# ---------------------------------------------------------------------------
def build_customer_matrix_rows(access, actor) -> list[dict]:
    """Build per-key matrix rows for one CustomerUserBuildingAccess row.

    `effective` mirrors the live resolver; `policy_denied` flags only the
    canonical "policy removed an otherwise-granted key" case. Object scope
    is the view's responsibility — this builder trusts the caller.
    """
    actor_may_edit = actor.role in _EDIT_ROLES
    overrides = access.permission_overrides or {}

    rows: list[dict] = []
    for key in CUSTOMER_MATRIX_KEYS:
        inherited = role_default(access.access_role, key)
        override = overrides[key] if key in overrides else None
        effective = access_has_permission(access, key)

        policy_restricts = _policy_denies(access, key)
        policy_denied = (
            policy_restricts and override is None and inherited is True
        )

        if override is True:
            source = SOURCE_OVERRIDE_ALLOW
        elif override is False:
            source = SOURCE_OVERRIDE_DENY
        elif policy_denied:
            source = SOURCE_POLICY_DENIED
        else:
            source = SOURCE_INHERITED

        grantable = actor_may_edit and not policy_restricts
        read_only = not grantable
        if policy_restricts:
            read_only_reason: Optional[str] = READ_ONLY_REASON_POLICY_DENIED
        elif not actor_may_edit:
            read_only_reason = READ_ONLY_REASON_ACTOR_NOT_ALLOWED
        else:
            read_only_reason = None

        if policy_restricts:
            field = _POLICY_FAMILY_FIELD[key]
            policy_denied_reason: Optional[dict] = {
                "code": POLICY_DENIED_CODE,
                "message": (
                    "The customer company policy does not allow customer "
                    f"users to {_POLICY_FIELD_LABEL.get(field, field)}."
                ),
                "policy_key": field,
                "scope": "customer",
            }
        else:
            policy_denied_reason = None

        rows.append(
            _row(
                key=key,
                inherited=inherited,
                override=override,
                effective=effective,
                source=source,
                grantable=grantable,
                read_only=read_only,
                read_only_reason=read_only_reason,
                policy_denied=policy_denied,
                policy_denied_reason=policy_denied_reason,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Building-manager matrix builder
# ---------------------------------------------------------------------------
def build_bm_matrix_rows(assignment, actor) -> list[dict]:
    """Build per-key matrix rows for one BuildingManagerAssignment row.

    `effective` mirrors `user_has_osius_permission`. There is no policy
    layer for osius.* keys, so `policy_denied` is always False here.
    """
    actor_may_edit = actor.role in _EDIT_ROLES
    overrides = assignment.permission_overrides or {}
    bm_user = assignment.user
    bid = assignment.building_id
    is_self = actor.id == assignment.user_id

    rows: list[dict] = []
    for key in BM_MATRIX_KEYS:
        is_revocable = key in BM_REVOCABLE_PERMISSION_KEYS
        inherited = True  # every BM_MATRIX_KEY defaults True for this BM.

        if is_revocable and key in overrides:
            override: Optional[bool] = overrides[key]
        else:
            override = None

        effective = user_has_osius_permission(bm_user, key, building_id=bid)

        if is_revocable and override is False:
            source = SOURCE_OVERRIDE_DENY
        elif is_revocable and override is True:
            source = SOURCE_OVERRIDE_ALLOW
        else:
            source = SOURCE_INHERITED

        grantable = is_revocable and actor_may_edit and not is_self
        read_only = not grantable
        if not is_revocable:
            read_only_reason: Optional[str] = READ_ONLY_REASON_SYSTEM_MANAGED
        elif is_self:
            read_only_reason = READ_ONLY_REASON_SELF_EDIT_FORBIDDEN
        elif not actor_may_edit:
            read_only_reason = READ_ONLY_REASON_ACTOR_NOT_ALLOWED
        else:
            read_only_reason = None

        rows.append(
            _row(
                key=key,
                inherited=inherited,
                override=override,
                effective=effective,
                source=source,
                grantable=grantable,
                read_only=read_only,
                read_only_reason=read_only_reason,
                policy_denied=False,
                policy_denied_reason=None,
            )
        )
    return rows
