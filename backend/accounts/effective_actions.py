"""
B3 — derived "effective actions" for the
`GET /api/users/<id>/effective-permissions/` endpoint.

This module computes a flat, JSON-serialisable dict of business-level
booleans ("can the target user do X in this customer/building context?")
derived from:

  * the target user's role,
  * the target user's customer/building scope (via the existing scope
    helpers),
  * the target user's effective permissions (via
    `accounts.permissions_effective.effective_permissions`).

The booleans are **derived facts**, not new permission keys. They are
the single source of truth for frontend permission-overview screens
(Customer Permissions page, Customer Users tab, User detail page).
The frontend must not re-derive these from raw permission keys; doing
so duplicates the resolver logic and drifts over time.

Hard rules followed by this module:

  * No new permission keys are introduced — every "can_X" boolean is
    computed from existing keys + role / scope helpers.
  * No workflow side effects — purely read-only computation.
  * The note-visibility actions reflect the live B7 four-tier taxonomy
    on `TicketMessage` plus the by-purpose classification on
    Extra Work / Proposal text fields documented in §9 of the
    canonical doc.

Surface-narrowing assumption: where one action name maps to multiple
backend surfaces with different visibility today (e.g. ticket
INTERNAL_NOTE vs EW internal_cost_note), the action reflects the
canonical-doc intent (system-business-logic-and-workflows.md §9). The
two-tier ticket model is acknowledged in the response's `notes`.
"""
from __future__ import annotations

from typing import Optional

from buildings.models import (
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
from companies.models import CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from extra_work.models import CustomerServicePrice

from .models import UserRole


# ---------------------------------------------------------------------------
# Provider-side roles + role helpers.
# ---------------------------------------------------------------------------
_PROVIDER_OPERATOR_ROLES = frozenset(
    {
        UserRole.SUPER_ADMIN,
        UserRole.COMPANY_ADMIN,
        UserRole.BUILDING_MANAGER,
    }
)


def _target_provider_in_scope(target, customer: Customer, building) -> bool:
    """True iff the provider-side target user has reach into the given
    customer (and building, if given) per the existing scope helpers.

    SUPER_ADMIN is global. COMPANY_ADMIN must hold a
    CompanyUserMembership for the customer's company. BUILDING_MANAGER
    must hold a BuildingManagerAssignment for the building (when one is
    given) — when no building is given, the BM is "in scope" iff they
    are assigned to at least one building that the customer is linked
    to via CustomerBuildingMembership.
    """
    role = target.role
    if role == UserRole.SUPER_ADMIN:
        return True
    if role == UserRole.COMPANY_ADMIN:
        return CompanyUserMembership.objects.filter(
            user=target, company_id=customer.company_id
        ).exists()
    if role == UserRole.BUILDING_MANAGER:
        if building is not None:
            return BuildingManagerAssignment.objects.filter(
                user=target, building_id=building.id
            ).exists()
        customer_building_ids = CustomerBuildingMembership.objects.filter(
            customer=customer
        ).values_list("building_id", flat=True)
        return BuildingManagerAssignment.objects.filter(
            user=target, building_id__in=customer_building_ids
        ).exists()
    return False


def _target_staff_in_scope(target, customer: Customer, building) -> bool:
    """True iff a STAFF target has BuildingStaffVisibility on the
    given building, or — when no building is given — on any building
    linked to the customer. Mirrors `scope_buildings_for(STAFF)` shape.
    """
    if target.role != UserRole.STAFF:
        return False
    if building is not None:
        return BuildingStaffVisibility.objects.filter(
            user=target, building_id=building.id
        ).exists()
    customer_building_ids = CustomerBuildingMembership.objects.filter(
        customer=customer
    ).values_list("building_id", flat=True)
    return BuildingStaffVisibility.objects.filter(
        user=target, building_id__in=customer_building_ids
    ).exists()


def _customer_user_access_rows(target, customer: Customer):
    """Active CustomerUserBuildingAccess rows for the target under this
    customer. Used to compute customer-side capability booleans + the
    `overrides` array on the endpoint response.
    """
    return list(
        CustomerUserBuildingAccess.objects.filter(
            membership__user=target,
            membership__customer=customer,
            is_active=True,
        ).select_related("membership", "building")
    )


def _customer_user_pair_access(target, customer: Customer, building):
    """The CustomerUserBuildingAccess row for the (target, customer,
    building) triple, or None. Used for building-specific capability
    answers."""
    if building is None:
        return None
    return (
        CustomerUserBuildingAccess.objects.filter(
            membership__user=target,
            membership__customer=customer,
            building=building,
            is_active=True,
        )
        .select_related("membership")
        .first()
    )


# ---------------------------------------------------------------------------
# Scope (target's reach into this context) — surfaced as `scope` block.
# ---------------------------------------------------------------------------
def compute_scope(target, customer: Customer, building) -> dict:
    """Return `{in_scope: bool, reason: str}` describing whether the
    target user has any visibility into (customer, building). The
    `reason` string is human-readable and intended for the response's
    `scope.reason` field — frontend may surface it as a debug hint.
    """
    role = target.role
    if role == UserRole.SUPER_ADMIN:
        return {"in_scope": True, "reason": "Super Admin (global scope)."}

    if role == UserRole.COMPANY_ADMIN:
        if _target_provider_in_scope(target, customer, building):
            return {
                "in_scope": True,
                "reason": "Company Admin of the customer's provider company.",
            }
        return {
            "in_scope": False,
            "reason": (
                "Company Admin has no membership in the customer's "
                "provider company."
            ),
        }

    if role == UserRole.BUILDING_MANAGER:
        if _target_provider_in_scope(target, customer, building):
            scope_hint = (
                f"assigned to building {building.id}"
                if building is not None
                else "assigned to at least one of the customer's buildings"
            )
            return {
                "in_scope": True,
                "reason": f"Building Manager {scope_hint}.",
            }
        return {
            "in_scope": False,
            "reason": (
                "Building Manager has no assignment to this building "
                "(or to any building of this customer)."
            ),
        }

    if role == UserRole.STAFF:
        if _target_staff_in_scope(target, customer, building):
            scope_hint = (
                f"BuildingStaffVisibility on building {building.id}"
                if building is not None
                else "BuildingStaffVisibility on at least one of the customer's buildings"
            )
            return {"in_scope": True, "reason": f"Staff with {scope_hint}."}
        return {
            "in_scope": False,
            "reason": (
                "Staff has no BuildingStaffVisibility for this building "
                "(or for any building of this customer)."
            ),
        }

    if role == UserRole.CUSTOMER_USER:
        # Customer users need: (a) CustomerUserMembership for this
        # customer, AND (b) at least one active CustomerUserBuildingAccess
        # row pointing at this customer (and the given building if
        # supplied).
        if not CustomerUserMembership.objects.filter(
            user=target, customer=customer
        ).exists():
            return {
                "in_scope": False,
                "reason": "Customer user has no membership for this customer.",
            }
        if building is not None:
            row = _customer_user_pair_access(target, customer, building)
            if row is None:
                return {
                    "in_scope": False,
                    "reason": (
                        "Customer user has no active building access for "
                        "this customer/building pair."
                    ),
                }
            return {
                "in_scope": True,
                "reason": (
                    f"Customer user with active access_role "
                    f"{row.access_role} for this building."
                ),
            }
        # No building given: any active access row anywhere under this
        # customer counts as "in scope" at the customer level.
        if _customer_user_access_rows(target, customer):
            return {
                "in_scope": True,
                "reason": (
                    "Customer user with at least one active building "
                    "access row for this customer."
                ),
            }
        return {
            "in_scope": False,
            "reason": (
                "Customer user has membership but no active building "
                "access rows for this customer."
            ),
        }

    return {"in_scope": False, "reason": "Unknown role."}


# ---------------------------------------------------------------------------
# Role-default permissions for the response's `role_defaults` block.
# ---------------------------------------------------------------------------
def compute_role_defaults(target, customer: Customer, building) -> dict:
    """Return a small block describing the target user's role and (for
    customer-side users with an access row in the given context) the
    `_TICKET_ROLE_DEFAULTS` keys their access_role grants by default.

    For provider-side roles there is no per-access-role default set —
    the role gate itself decides reach. The block carries `access_role:
    None` in that case.
    """
    from customers.permissions import _TICKET_ROLE_DEFAULTS

    role = target.role
    block: dict = {
        "role": role,
        "access_role": None,
        "default_permission_keys": [],
    }
    if role != UserRole.CUSTOMER_USER:
        return block

    # Customer-side default depends on the access row in the given
    # (customer, building) context. When `building` is None we fall
    # back to the strongest active access row across the customer —
    # this matches the "view_company" branch of `scope_tickets_for`.
    pair_row = _customer_user_pair_access(target, customer, building)
    if pair_row is not None:
        block["access_role"] = pair_row.access_role
        block["default_permission_keys"] = sorted(
            _TICKET_ROLE_DEFAULTS.get(pair_row.access_role, frozenset())
        )
        return block

    all_rows = _customer_user_access_rows(target, customer)
    if not all_rows:
        return block

    # Pick the most-permissive access_role across rows. The enum has a
    # stable ordering: CUSTOMER_USER < CUSTOMER_LOCATION_MANAGER <
    # CUSTOMER_COMPANY_ADMIN. We compute "most permissive" by
    # set-membership size rather than relying on string ordering.
    best_role = None
    best_keys: frozenset = frozenset()
    for row in all_rows:
        keys = _TICKET_ROLE_DEFAULTS.get(row.access_role, frozenset())
        if len(keys) > len(best_keys):
            best_role = row.access_role
            best_keys = keys
    block["access_role"] = best_role
    block["default_permission_keys"] = sorted(best_keys)
    return block


# ---------------------------------------------------------------------------
# Overrides — the actual `CustomerUserBuildingAccess` rows for the
# target under this customer, surfaced as a sortable list.
# ---------------------------------------------------------------------------
def compute_overrides(target, customer: Customer, building) -> list[dict]:
    """Return the target's active CustomerUserBuildingAccess rows for
    this customer as a list of plain dicts. When `building` is given,
    the list is narrowed to the matching row (or empty). Each row
    surfaces `building_id`, `access_role`, `is_active`, and the raw
    `permission_overrides` JSON so the frontend can render the
    "default → override → effective" chain.
    """
    rows = _customer_user_access_rows(target, customer)
    if building is not None:
        rows = [r for r in rows if r.building_id == building.id]
    return [
        {
            "building_id": r.building_id,
            "building_name": getattr(r.building, "name", None),
            "access_role": r.access_role,
            "is_active": r.is_active,
            "permission_overrides": dict(r.permission_overrides or {}),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Effective actions — the derived "what can this user do" booleans.
# ---------------------------------------------------------------------------
def _customer_can(target, customer: Customer, building, key: str) -> bool:
    """Helper — does the target hold a customer-side permission key in
    the given (customer, building) context? Re-uses the existing
    customer-side resolver."""
    from customers.permissions import user_can

    building_id = building.id if building is not None else None
    return user_can(target, customer.id, building_id, key)


def _any_customer_view_key(target, customer: Customer, building, family: str) -> bool:
    """True iff target holds at least one of view_own / view_location
    / view_company for the given family ("ticket" or "extra_work")."""
    return (
        _customer_can(target, customer, building, f"customer.{family}.view_own")
        or _customer_can(target, customer, building, f"customer.{family}.view_location")
        or _customer_can(target, customer, building, f"customer.{family}.view_company")
    )


def _any_customer_approve_key(target, customer: Customer, building, family: str) -> bool:
    """True iff target holds approve_own or approve_location for the
    given family."""
    return _customer_can(
        target, customer, building, f"customer.{family}.approve_own"
    ) or _customer_can(
        target, customer, building, f"customer.{family}.approve_location"
    )


def compute_effective_actions(
    target,
    customer: Customer,
    building,
) -> dict[str, bool]:
    """Return the `effective_actions` dict for the endpoint response.

    Each boolean is computed from existing role / scope / permission-key
    logic; no new permission keys are introduced. Future-work tagged
    actions return current backend truth (callers should consult the
    response's `notes` list for caveats).
    """
    role = target.role
    in_provider_scope = _target_provider_in_scope(target, customer, building)
    in_staff_scope = _target_staff_in_scope(target, customer, building)

    is_super = role == UserRole.SUPER_ADMIN
    is_company_admin_in = role == UserRole.COMPANY_ADMIN and in_provider_scope
    is_bm_in = role == UserRole.BUILDING_MANAGER and in_provider_scope
    is_staff_in = role == UserRole.STAFF and in_staff_scope
    is_customer = role == UserRole.CUSTOMER_USER

    actions: dict[str, bool] = {}

    # ----- visibility -----
    actions["can_view_customer"] = (
        is_super
        or is_company_admin_in
        or is_bm_in
        or is_staff_in
        or (
            is_customer
            and bool(_customer_user_access_rows(target, customer))
        )
    )
    actions["can_view_building"] = (
        is_super
        or is_company_admin_in
        or is_bm_in
        or is_staff_in
        or (
            is_customer
            and (
                _customer_user_pair_access(target, customer, building)
                is not None
                if building is not None
                else bool(_customer_user_access_rows(target, customer))
            )
        )
    )

    # ----- tickets -----
    actions["can_view_tickets"] = (
        is_super
        or is_company_admin_in
        or is_bm_in
        or is_staff_in
        or (is_customer and _any_customer_view_key(target, customer, building, "ticket"))
    )
    actions["can_create_ticket"] = (
        is_super
        or is_company_admin_in
        or is_bm_in
        or (is_customer and _customer_can(target, customer, building, "customer.ticket.create"))
    )
    # Operational status changes belong to provider operators in scope.
    # STAFF can drive IN_PROGRESS -> WAITING_MANAGER_REVIEW / WAITING_
    # CUSTOMER_APPROVAL on tickets they are assigned to, but the
    # endpoint cannot know the specific ticket — we report True for
    # provider operators in scope; STAFF in scope on a building can
    # be assigned to tickets there, so we also report True. Customer
    # users never drive non-customer-decision transitions.
    actions["can_change_ticket_status"] = (
        is_super or is_company_admin_in or is_bm_in or is_staff_in
    )
    # B1 + B6 — provider-side override of customer approval/rejection
    # on tickets and Extra Work proposals.
    #
    #   SA: always True.
    #   COMPANY_ADMIN in scope: always True (key is not revocable for
    #     COMPANY_ADMIN — the role default returns True at the
    #     resolver).
    #   BM in assigned building: True by default; False when the
    #     `BuildingManagerAssignment.permission_overrides` row for
    #     this (BM, building) sets
    #     `osius.building_manager.override_customer_decision = False`.
    #   STAFF / CUSTOMER_USER: always False.
    #
    # Calling the resolver uniformly keeps the answer in lockstep with
    # the live backend gate (`tickets.state_machine.apply_transition`
    # + `extra_work.state_machine.apply_transition` + the proposal
    # state machine), so the action mirrors what the user can actually
    # do at the endpoints.
    if is_super or is_company_admin_in:
        actions["can_override_customer_decision"] = True
    elif is_bm_in:
        from .permissions_v2 import user_has_osius_permission

        actions["can_override_customer_decision"] = (
            user_has_osius_permission(
                target,
                "osius.building_manager.override_customer_decision",
                building_id=(building.id if building is not None else None),
            )
        )
    else:
        actions["can_override_customer_decision"] = False

    # ----- extra work -----
    # STAFF cannot reach any EW or Proposal endpoint (P0 staff-privacy
    # patch). The action surface mirrors that.
    actions["can_view_extra_work"] = (
        is_super
        or is_company_admin_in
        or is_bm_in
        or (
            is_customer
            and _any_customer_view_key(target, customer, building, "extra_work")
        )
    )
    actions["can_create_extra_work"] = (
        is_super
        or is_company_admin_in
        or is_bm_in
        or (
            is_customer
            and _customer_can(target, customer, building, "customer.extra_work.create")
        )
    )
    # "Direct-order" path exists for a target who can create extra
    # work AND has at least one active contract price under this
    # customer. The B2 routing decision then decides INSTANT vs
    # PROPOSAL per-line at submission time; this action surfaces
    # only "is the direct-order path even reachable for this user?"
    has_any_contract_price = CustomerServicePrice.objects.filter(
        customer=customer, is_active=True
    ).exists()
    actions["can_use_contract_price_direct_order"] = (
        actions["can_create_extra_work"] and has_any_contract_price
    )
    # Non-contract path is always reachable when create-extra-work is
    # reachable — the user submits a cart and the routing decision
    # chooses the proposal flow at submission.
    actions["can_request_non_contract_extra_work"] = actions["can_create_extra_work"]
    # Proposal preparation is provider-side. STAFF / CUSTOMER_USER never.
    #
    # B6 narrows BM: True by default; False when the
    # `BuildingManagerAssignment.permission_overrides` row for this
    # (BM, building) sets
    # `osius.building_manager.prepare_extra_work_proposal = False`.
    # SA / COMPANY_ADMIN are not revocable through this surface.
    if is_super or is_company_admin_in:
        actions["can_prepare_extra_work_proposal"] = True
    elif is_bm_in:
        from .permissions_v2 import user_has_osius_permission

        actions["can_prepare_extra_work_proposal"] = (
            user_has_osius_permission(
                target,
                "osius.building_manager.prepare_extra_work_proposal",
                building_id=(building.id if building is not None else None),
            )
        )
    else:
        actions["can_prepare_extra_work_proposal"] = False
    # Customer sees customer-visible prices on SENT proposals when
    # their access row resolves any extra_work approve_* key (because
    # only an approver-eligible role meaningfully needs the price).
    # Provider operators in scope see full prices. STAFF never.
    actions["can_view_proposal_prices"] = (
        is_super
        or is_company_admin_in
        or is_bm_in
        or (
            is_customer
            and _any_customer_approve_key(target, customer, building, "extra_work")
        )
    )

    # ----- customer-side admin actions -----
    # B4 — Customer Company Admin (and any customer-side actor whose
    # row resolves `customer.users.manage`) can manage lower customer
    # users (Customer User / Customer Location Manager) inside their
    # own customer scope. The endpoint-level admit is enforced by
    # `accounts.permissions.CanManageCustomerSideUsers`; here we
    # surface the derived fact so the frontend permission-overview
    # UIs can render it. Customer-level scope (building_id=None) on
    # the resolver — the action describes whether the user can manage
    # lower users in this customer, not at a specific building.
    actions["can_manage_customer_users"] = (
        is_super
        or is_company_admin_in
        or (
            is_customer
            and _customer_can(target, customer, None, "customer.users.manage")
        )
    )
    # `can_manage_customer_permissions` is the broad action — "can
    # edit lower customer users' permission_overrides and is_active
    # in this customer." This stays True for COMPANY_ADMIN in scope
    # regardless of the B5 policy: B5 toggles only CCA-grant
    # authority, NOT the broader lower-user-permission management
    # that B4 codified. CCA itself does not get this action because
    # CCA's reach into permission management runs through the same
    # endpoints with B4 admit logic; the derived action label here
    # is conservative.
    actions["can_manage_customer_permissions"] = is_super or is_company_admin_in

    # B5 — derived "can this user manage Customer Company Admin
    # users/permissions for customers under this provider company?"
    # Covers create / grant / promote / edit / demote / revoke of
    # CCA-tier rows. SUPER_ADMIN always; COMPANY_ADMIN in scope only
    # when the provider Company's `provider_admin_may_manage_customer_company_admins`
    # policy is True. Everyone else False (BM / STAFF / Customer users /
    # CCA holders all return False).
    actions["can_manage_customer_company_admins"] = is_super or (
        is_company_admin_in
        and customer.company.provider_admin_may_manage_customer_company_admins
    )

    # ----- note visibility -----
    # B7 implemented the four-tier note taxonomy on `TicketMessage`
    # and tightened the queryset filter + write validation accordingly.
    # The four tiers (§9 of the canonical doc) are:
    #
    #   * PUBLIC_REPLY            — CUSTOMER_VISIBLE
    #   * INTERNAL_NOTE           — PROVIDER_INTERNAL
    #   * STAFF_OPERATIONAL       — STAFF_OPERATIONAL
    #   * STAFF_COMPLETION        — STAFF_COMPLETION
    #
    # Both action booleans below now correspond to the live resolver
    # truth: STAFF is excluded from PROVIDER_INTERNAL; everyone in
    # scope (provider + STAFF) sees STAFF_OPERATIONAL on the safe
    # operational surface; customer-side sees PUBLIC_REPLY +
    # STAFF_COMPLETION only.
    actions["can_view_provider_internal_notes"] = (
        is_super or is_company_admin_in or is_bm_in
    )
    actions["can_view_staff_operational_notes"] = (
        is_super or is_company_admin_in or is_bm_in or is_staff_in
    )

    return actions


def compute_endpoint_notes(target, customer: Customer, building) -> list[str]:
    """Free-text notes returned in the endpoint's `notes` list.

    These document caveats / future-work gaps so the frontend can
    surface them without re-deriving them. Each entry is plain text;
    the list shape is stable but its contents can grow as new
    documented gaps land.
    """
    notes = [
        "Derived from role defaults plus customer/building access "
        "rows and permission overrides as of the latest backend code.",
        "effective_actions are read-only derived facts, not new "
        "permission keys.",
    ]
    if target.role == UserRole.STAFF:
        notes.append(
            "STAFF cannot reach any Extra Work or Proposal endpoint "
            "(staff-privacy P0)."
        )
        notes.append(
            "B7 — STAFF can no longer see PROVIDER_INTERNAL ticket "
            "messages (INTERNAL_NOTE), their attachments, or "
            "PROVIDER_INTERNAL status-history override commentary. "
            "STAFF still sees PUBLIC_REPLY, STAFF_OPERATIONAL, and "
            "STAFF_COMPLETION messages and their attachments per the "
            "four-tier taxonomy in §9 of the canonical doc."
        )
    if target.role == UserRole.COMPANY_ADMIN:
        # B5 — surface the live policy state of the provider company
        # carrying this customer. The toggle controls CCA-grant
        # authority only; lower-user permission management (B4) is
        # unaffected.
        policy_on = bool(
            customer.company.provider_admin_may_manage_customer_company_admins
        )
        if policy_on:
            notes.append(
                "Provider Company Admin can manage customer-side users "
                "and customer-side permissions for customers under "
                "their provider company by default, including create / "
                "grant / promote / edit / demote / revoke of the "
                "Customer Company Admin access role on this provider "
                "company (B5 policy "
                "`provider_admin_may_manage_customer_company_admins` = True)."
            )
        else:
            notes.append(
                "Super Admin has disabled Provider Company Admin's "
                "ability to manage Customer Company Admin users on this "
                "provider company (B5 policy "
                "`provider_admin_may_manage_customer_company_admins` = False). "
                "Provider Admin can no longer create, grant, promote, "
                "edit, demote, or revoke CCA-tier access on any "
                "customer of this provider company; only Super Admin "
                "can. Provider Admin's ability to manage lower customer "
                "users (Customer User / Customer Location Manager) is "
                "unaffected."
            )
    if target.role == UserRole.BUILDING_MANAGER:
        notes.append(
            "BM defaults include preparing extra-work proposals and "
            "overriding customer decisions inside assigned buildings. "
            "B6 added two revocable keys "
            "(`osius.building_manager.override_customer_decision`, "
            "`osius.building_manager.prepare_extra_work_proposal`) "
            "stored on `BuildingManagerAssignment.permission_overrides` "
            "so Super Admin / Provider Company Admin can selectively "
            "revoke either default per-(BM, building) without removing "
            "the BM's operational ticket access. The two derived "
            "actions `can_override_customer_decision` and "
            "`can_prepare_extra_work_proposal` reflect the live key "
            "state for this target+building pair."
        )
    if target.role == UserRole.CUSTOMER_USER:
        notes.append(
            "Customer Company Admin must never create or promote "
            "another Customer Company Admin. B4 added a CCA-callable "
            "path that admits a CCA to the membership + access "
            "management endpoints inside their own customer when the "
            "`customer.users.manage` permission resolves True. CCA can "
            "only manage lower customer users (Customer User and "
            "Customer Location Manager); the H-7 grant gate continues "
            "to block any non-Super-Admin actor from setting "
            "`access_role=CUSTOMER_COMPANY_ADMIN`."
        )
    return notes
