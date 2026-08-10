"""
Sprint 160 — tenant scope helpers for the contracts module (RBAC H-1).

Mirrors the SHAPE of `timesheets/scope.py` — one
`scope_company_ids_for_contracts(user)` answering "which provider
companies may this actor see contracts for", plus one `filter_*_for`
per noun — and imports nothing from it. Module independence is this
app's architectural rule; sharing a scope helper is exactly the import
that stops the app standing on its own.

The rule it enforces: **every queryset resolves through scope,
including the serializer's validation lookups.** An out-of-scope
`customer`, `building` or `contract_type` id must read as NONEXISTENT
(DRF's `does_not_exist` 400), never as "exists but forbidden" — the two
answers differ, and the difference is an existence oracle against
another tenant's data. That is the Sprint 142.1 defect class.

Role logic:

  * SUPER_ADMIN: all companies (sentinel `None` = do not filter). Which
    ONE company they are working in at a time is a REQUEST-level choice
    (Sprint 149/150), applied on top by the views' `?company=`
    handling.
  * COMPANY_ADMIN: their `CompanyUserMembership` companies.
  * BUILDING_MANAGER: companies of the buildings they manage — and,
    on top of that, only the contracts that actually touch one of
    THEIR buildings (`filter_contracts_for`). Read-only; the write
    permission class never admits them.
  * STAFF: NOTHING. A contract carries negotiated prices; a field
    worker has no business reading them, and unlike hours there is no
    "your own" subset that would make sense to show.
  * CUSTOMER_USER: NOTHING, EVER — an empty frozenset. A contract
    carries the customer's own negotiated prices, which sounds like
    something they may see, and this sprint deliberately does not open
    that surface: the provider decides what a customer is shown about
    money, and no customer-side endpoint exists here to decide it with.
    The view layer 403s them first; this is the second, independent
    floor.

Anonymous / unauthenticated: empty scope.
"""
from __future__ import annotations

from typing import Optional

from accounts.models import UserRole


# Roles allowed to reach ANY contracts endpoint at all.
CONTRACT_ROLES = (
    UserRole.SUPER_ADMIN,
    UserRole.COMPANY_ADMIN,
    UserRole.BUILDING_MANAGER,
)

# Roles that may WRITE contracts. BUILDING_MANAGER is deliberately
# absent: a BM manages buildings and reads the contracts covering
# them, but the commercial terms are not theirs to change.
CONTRACT_MANAGER_ROLES = (
    UserRole.SUPER_ADMIN,
    UserRole.COMPANY_ADMIN,
)


def scope_company_ids_for_contracts(user) -> Optional[frozenset[int]]:
    """Return the `companies.Company` ids whose contracts are visible
    to `user`.

    Returns `None` for SUPER_ADMIN to signal "no scope filter"; a real
    `frozenset` (possibly empty) means "filter to these ids". The empty
    set is a legitimate answer, not an error: it yields no rows.
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

    # STAFF, CUSTOMER_USER and anything else: nothing.
    return frozenset()


def managed_building_ids(user) -> Optional[frozenset[int]]:
    """The building ids a BUILDING_MANAGER manages, or `None` for every
    actor whose visibility is not narrowed by building.

    `None` means "do not narrow by building" and is returned for
    SUPER_ADMIN and COMPANY_ADMIN — they see every contract of a
    company in scope, including one covering a building nobody manages
    yet. For a BM it is the concrete set; for everyone else it is an
    empty frozenset, which combines with the empty company scope to
    yield nothing.
    """
    role = getattr(user, "role", None)
    if role in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN):
        return None
    if role == UserRole.BUILDING_MANAGER:
        from buildings.models import BuildingManagerAssignment

        return frozenset(
            BuildingManagerAssignment.objects.filter(user=user).values_list(
                "building_id", flat=True
            )
        )
    return frozenset()


def is_contract_manager(user) -> bool:
    """True for the actors who may create / edit / delete contracts."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return getattr(user, "role", None) in CONTRACT_MANAGER_ROLES


def _apply_company(user, queryset, field="company_id"):
    scope = scope_company_ids_for_contracts(user)
    if scope is None:
        return queryset
    return queryset.filter(**{f"{field}__in": scope})


def filter_contracts_for(user, queryset):
    """Scope a `Contract` queryset.

    TWO independent narrowings, applied in this order and deliberately
    not collapsed into one: the company filter answers the TENANT
    question (H-1), and the building filter answers the BUILDING
    MANAGER's narrower "only what you manage" question. Collapsing them
    would make it possible to satisfy one and silently lose the other.

    The building narrowing uses `.distinct()` because a contract
    covering three of a manager's buildings would otherwise be returned
    three times by the join.
    """
    queryset = _apply_company(user, queryset)
    buildings = managed_building_ids(user)
    if buildings is None:
        return queryset
    return queryset.filter(building_links__building_id__in=buildings).distinct()


def filter_contract_types_for(user, queryset):
    """Scope a `ContractType` queryset."""
    return _apply_company(user, queryset)


def filter_customers_for_contracts(user, queryset):
    """Scope a `Customer` queryset for the contract form's customer
    picker AND for the serializer's validation lookup — the same
    queryset backs both, so "offerable" equals "acceptable" by
    construction rather than by two lists that happen to agree today.

    Company-level only. A BUILDING_MANAGER never reaches a write path
    (the permission class stops them), so there is no narrower
    customer set to compute for them here.
    """
    return _apply_company(user, queryset)


def filter_buildings_for_contracts(user, queryset):
    """Scope a `Building` queryset for the contract's locations picker
    and its validation lookup.

    Company-level, like the customer picker: a contract may cover any
    building of its own provider. The cross-company rejection the
    serializer performs is a SECOND, narrower check — the building must
    belong to the same company as the CONTRACT, which may be narrower
    than the actor's whole scope when a SUPER_ADMIN works across
    several.
    """
    return _apply_company(user, queryset)


def filter_revisions_for(user, queryset):
    """Scope a `ContractRevision` queryset through its contract."""
    scope = scope_company_ids_for_contracts(user)
    if scope is not None:
        queryset = queryset.filter(contract__company_id__in=scope)
    buildings = managed_building_ids(user)
    if buildings is None:
        return queryset
    return queryset.filter(
        contract__building_links__building_id__in=buildings
    ).distinct()


def filter_lines_for(user, queryset):
    """Scope a `ContractLine` queryset through its revision's contract."""
    scope = scope_company_ids_for_contracts(user)
    if scope is not None:
        queryset = queryset.filter(revision__contract__company_id__in=scope)
    buildings = managed_building_ids(user)
    if buildings is None:
        return queryset
    return queryset.filter(
        revision__contract__building_links__building_id__in=buildings
    ).distinct()
