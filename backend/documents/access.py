"""
Sprint 125 — who may touch a customer's document store, and how.

Two sides, deliberately narrow:

  * PROVIDER side — SUPER_ADMIN (unscoped) and COMPANY_ADMIN (scoped to
    customers of their own provider company) ONLY. Mirrors the contract-PDF
    write gate `views_media._may_manage_contract_pdf`. BUILDING_MANAGER,
    STAFF and every other provider role are excluded on purpose (the owner
    narrowed this mid-spec): they get 404 on read and 403 on write — the tab
    does not exist for them.

  * CUSTOMER side — a user of that customer holding the single coarse
    `customer.documents.manage` key, resolved through
    `customers.permissions.user_can` (NEVER an access-row existence check —
    that was the #109 P2 finding). `user_can` resolves a company-wide CCA on
    its own, so a CCA with no per-building rows still passes.

`resolve_access` returns the actor's SIDE (PROVIDER / CUSTOMER / None); the
view layer combines it with a row's `origin` / `is_system` to decide each
mutation. Anyone whose side is None must 404 on every endpoint (no existence
leak, cross-tenant included).

Placement (creating a subfolder in, or uploading a file into, a folder) is
allowed into ANY folder the actor can see, system folders included — that is
how a customer files a contract into the provider's `Contracten` folder. The
`is_system` flag protects only the folder ROW (rename provider-only; move /
delete rejected for everyone); it never restricts a folder's contents, and
`origin` — stamped from the actor's side at write time — governs who may
later edit each placed row.
"""
from __future__ import annotations

from accounts.models import UserRole
from companies.models import CompanyUserMembership
from customers.permissions import user_can

from .models import DocumentOrigin


# The single customer-side permission key that gates the whole module.
DOCUMENTS_PERMISSION_KEY = "customer.documents.manage"

# The provider roles allowed anywhere near customer documents.
_PROVIDER_DOCUMENT_ROLES = (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN)


class AccessSide:
    PROVIDER = "PROVIDER"
    CUSTOMER = "CUSTOMER"


def provider_can_access(actor, customer) -> bool:
    """SUPER_ADMIN anywhere; COMPANY_ADMIN only for a customer in their own
    provider company. No other provider role (BM / STAFF) qualifies."""
    if actor.role == UserRole.SUPER_ADMIN:
        return True
    if actor.role == UserRole.COMPANY_ADMIN:
        return CompanyUserMembership.objects.filter(
            user=actor, company_id=customer.company_id
        ).exists()
    return False


def customer_can_access(actor, customer) -> bool:
    """A customer user with the documents key on this customer. Routed
    through `user_can` (company-wide CCA resolves with no access rows), never
    a raw membership/access-row existence check."""
    if actor.role != UserRole.CUSTOMER_USER:
        return False
    return user_can(actor, customer.id, None, DOCUMENTS_PERMISSION_KEY)


def resolve_access(actor, customer) -> str | None:
    """Return the actor's side (AccessSide.PROVIDER / .CUSTOMER) or None if
    the actor may not see this customer's documents at all."""
    if provider_can_access(actor, customer):
        return AccessSide.PROVIDER
    if customer_can_access(actor, customer):
        return AccessSide.CUSTOMER
    return None


def origin_for_side(side: str) -> str:
    """The `origin` to stamp on a row created by an actor of `side`.
    Immutable once written; decides later customer-side write eligibility."""
    return (
        DocumentOrigin.PROVIDER
        if side == AccessSide.PROVIDER
        else DocumentOrigin.CUSTOMER
    )


def can_modify_row(side: str, *, origin: str, is_system: bool) -> bool:
    """May an actor of `side` RENAME / MOVE / DELETE this existing row?

      * A system folder is never moved or deleted by anyone (rename is
        handled separately — see `can_rename_system_folder`); this returns
        False for it so the move/delete paths reject it uniformly.
      * PROVIDER may modify any non-system row (either origin).
      * CUSTOMER may modify only its own origin=CUSTOMER rows, and never a
        system folder.
    """
    if is_system:
        return False
    if side == AccessSide.PROVIDER:
        return True
    return origin == DocumentOrigin.CUSTOMER


def can_rename_system_folder(side: str) -> bool:
    """Only the provider may rename a system folder (its display name);
    the slug never changes and a customer may never rename it."""
    return side == AccessSide.PROVIDER
