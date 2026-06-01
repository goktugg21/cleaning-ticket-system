"""
Sprint 12B — promote-to-user service.

Bridges a customer-side `Contact` (a communication-only person record,
no login) to an authenticated `User` (spec
docs/product/meeting-2026-05-15-system-requirements.md §1: Contacts and
Users are distinct entities; promotion is explicit, never a side-effect
of editing a Contact).

Two modes, chosen by whether a User already exists for the contact's
email:

  * INVITE MODE (no matching User) — seed a pending `Invitation` tied to
    this contact. The invitation's `accept` handler (extended in 12B)
    creates the User, the `CustomerUserMembership`, the per-building
    `CustomerUserBuildingAccess` rows, and links `Contact.user`. Email
    send happens in the VIEW after the atomic commit.
  * LINK MODE (a matching active CUSTOMER_USER) — idempotently
    materialise the membership + per-building access rows now and link
    `Contact.user`.

Everything is `get_or_create`-based so re-promoting is idempotent (no
duplicate membership / CUBA / invitation rows). `access_role` is applied
to a CUBA row only on CREATE — an existing row's role is never clobbered.
"""
from __future__ import annotations

from typing import Optional

from django.db import transaction
from django.utils import timezone

from accounts.invitations import Invitation, generate_invitation_token
from accounts.models import User, UserRole
from buildings.models import Building

from .models import (
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)


class PromotionError(Exception):
    """Raised by `promote_contact` on a guard failure. `code` is the
    stable contract surfaced by the view as the JSON `code` field;
    `status_code` is the HTTP status the view returns."""

    def __init__(self, message: str, code: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@transaction.atomic
def promote_contact(
    *,
    customer,
    contact,
    actor,
    access_role: Optional[str] = None,
    building_ids: Optional[list[int]] = None,
) -> dict:
    AccessRole = CustomerUserBuildingAccess.AccessRole

    access_role = access_role or AccessRole.CUSTOMER_USER
    if access_role not in AccessRole.values:
        raise PromotionError("Unknown access role.", "invalid_access_role")

    email = (contact.email or "").strip()
    if not email:
        raise PromotionError(
            "Contact has no email to promote.", "contact_email_required"
        )

    # Resolve target building ids: explicit list, else the union of the
    # contact's multi-building links + the legacy single-building anchor.
    if building_ids is not None:
        target_building_ids = list(building_ids)
    else:
        target_building_ids = list(
            contact.building_links.values_list("building_id", flat=True)
        )
        if contact.building_id is not None:
            target_building_ids.append(contact.building_id)
    target_building_ids = list(dict.fromkeys(target_building_ids))

    for bid in target_building_ids:
        if not CustomerBuildingMembership.objects.filter(
            customer=customer, building_id=bid
        ).exists():
            raise PromotionError(
                "Building is not linked to this customer.", "building_not_linked"
            )

    # H-7 CCA grant guard: a Provider Company Admin may grant the
    # Customer Company Admin role only if the provider company's policy
    # allows it. SUPER_ADMIN always passes; the view already blocked
    # BM / STAFF / CUSTOMER.
    if (
        access_role == AccessRole.CUSTOMER_COMPANY_ADMIN
        and actor.role == UserRole.COMPANY_ADMIN
        and not customer.company.provider_admin_may_manage_customer_company_admins
    ):
        raise PromotionError(
            "Provider Company Admin cannot grant the Customer Company "
            "Admin role on this provider company.",
            "cca_grant_forbidden",
            status_code=403,
        )

    existing = User.objects.filter(email__iexact=email).first()

    # ------------------------------------------------------------------
    # INVITE MODE — no User yet.
    # ------------------------------------------------------------------
    if existing is None:
        # Guard: a contact that is ALREADY promoted (linked to a User)
        # must not spawn a fresh invitation for a different identity —
        # e.g. if its email was edited to a brand-new address after the
        # original link and it is re-promoted. The link-mode branch below
        # has the symmetric guard for the "email now matches a different
        # existing user" case.
        if contact.user_id is not None:
            raise PromotionError(
                "Contact is already promoted to a user.",
                "contact_already_promoted",
            )
        now = timezone.now()
        pending = Invitation.objects.filter(
            contact=contact,
            accepted_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=now,
        ).first()
        if pending is not None:
            return {
                "mode": "invited",
                "invitation_id": pending.id,
                "detail": "already_invited",
            }

        raw_token, token_hash = generate_invitation_token()

        # Mirror InvitationCreateSerializer.save_with_token: auto-revoke
        # any prior PENDING invitation for the same email so a stale link
        # cannot be used after this re-invite.
        Invitation.objects.filter(
            email__iexact=email,
            accepted_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=now,
        ).update(revoked_at=now, revoked_by=actor)

        invitation = Invitation.objects.create(
            email=email,
            full_name=contact.full_name,
            role=UserRole.CUSTOMER_USER,
            customer_access_role=access_role,
            permission_overrides={},
            contact=contact,
            created_by=actor,
            token_hash=token_hash,
        )
        invitation.customers.set([customer])
        if target_building_ids:
            invitation.buildings.set(
                list(Building.objects.filter(id__in=target_building_ids))
            )
        return {
            "mode": "invited",
            "invitation_id": invitation.id,
            "_raw_token": raw_token,
        }

    # ------------------------------------------------------------------
    # LINK MODE — a User already exists for this email.
    # ------------------------------------------------------------------
    if existing.role != UserRole.CUSTOMER_USER:
        raise PromotionError(
            "Email belongs to a non-customer user.",
            "email_belongs_to_non_customer_user",
        )
    if (not existing.is_active) or existing.deleted_at is not None:
        raise PromotionError("The matching user is inactive.", "user_inactive")
    if contact.user_id is not None and contact.user_id != existing.id:
        raise PromotionError(
            "Contact is already promoted to a different user.",
            "contact_already_promoted",
        )

    membership, _ = CustomerUserMembership.objects.get_or_create(
        customer=customer, user=existing
    )
    for bid in target_building_ids:
        CustomerUserBuildingAccess.objects.get_or_create(
            membership=membership,
            building_id=bid,
            defaults={"access_role": access_role, "permission_overrides": {}},
        )

    if contact.user_id is None:
        contact.user = existing
        contact.save(update_fields=["user", "updated_at"])

    return {"mode": "linked", "user_id": existing.id}
