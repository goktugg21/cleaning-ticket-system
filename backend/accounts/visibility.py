"""
M2 P3 — the visibility resolver chokepoint for staff credentials and
custom profile properties (SoT Addendum A.3).

Mirrors the M1 B5 lockstep discipline from tickets/permissions.py
(`message_type_visible_to_user` / `filter_messages_visible_to`): ONE
canonical table expressed two ways — a per-item predicate and a
queryset filter — kept cell-for-cell in lockstep and guarded by a
parity regression test (accounts/tests/test_m2_visibility_resolver.py).

The canonical FIELD-visibility table:

  visibility_level    SA   PA   BM   STAFF  CUSTOMER_USER
  -----------------   ---  ---  ---  -----  -------------
  PA_SA_ONLY           v    v    -     -        -
  PROVIDER_ONLY        v    v    v     -        -
  CUSTOMER_VISIBLE     v    v    v     -        v*

  * CUSTOMER_USER additionally requires a grant row
    (CredentialCustomerVisibility / PropertyCustomerVisibility) for the
    CONTEXT customer, AND the viewer must be a member of that customer
    (CustomerUserMembership). STAFF-role viewers see NOTHING this
    milestone (staff self-view is out of scope — M2 locked decision 4);
    "own" records are deliberately NOT special-cased.

Every function takes an explicit `customer` context parameter. It is
REQUIRED (non-None) for CUSTOMER_USER viewers — without a context
customer there is no grant row to check, so the answer is "invisible".
Provider roles ignore it.

This is the FIELD gate only. Company / tenant scoping (which target
users a provider actor may reach at all — H-1) is enforced by the view
layer on top of this table; the table answers "may this role see a row
at this visibility level", not "may this actor reach this target user".

DOCUMENT sub-rule — a second, STRICTER gate layered on top of field
visibility (`credential_document_visible_to_user` /
`property_document_visible_to_user`):

  * EU_NATIONAL_ID document: PA / SA only, unconditionally. Never any
    customer, never BM. (Field visibility already pins EU-ID rows to
    PA_SA_ONLY — the explicit branch is belt-and-suspenders.)
  * RESIDENCE_PERMIT: a customer who passes the field gate sees ONLY
    permit_number + expiry_date; the document (photocopy) additionally
    requires `document_customer_visible=True`. Provider roles that pass
    the field gate see the document.
  * VCA / property documents: document visibility == field visibility.
"""
from __future__ import annotations

from .models import StaffCredential, UserRole, VisibilityLevel


def _viewer_is_member(user, customer) -> bool:
    """A CUSTOMER_USER viewer must hold a CustomerUserMembership row for
    the context customer — the grant alone is not enough (the grant is
    per-customer-org; the membership binds the individual viewer)."""
    if customer is None:
        return False
    from customers.models import CustomerUserMembership

    return CustomerUserMembership.objects.filter(
        user=user, customer=customer
    ).exists()


def _field_visible(level, user, customer, *, has_grant) -> bool:
    """Shared predicate body — the canonical table, row by row.

    `has_grant` is a callable returning whether a grant row exists for
    the context customer (lazy so provider roles never query)."""
    role = getattr(user, "role", None)
    if role in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN):
        return True
    if role == UserRole.BUILDING_MANAGER:
        return level in (
            VisibilityLevel.PROVIDER_ONLY,
            VisibilityLevel.CUSTOMER_VISIBLE,
        )
    if role == UserRole.CUSTOMER_USER:
        return (
            level == VisibilityLevel.CUSTOMER_VISIBLE
            and _viewer_is_member(user, customer)
            and has_grant()
        )
    # STAFF (M2 locked decision 4) / anonymous / anything else: nothing.
    return False


def credential_visible_to_user(credential, user, customer) -> bool:
    """Per-item FIELD-visibility predicate for a StaffCredential."""
    return _field_visible(
        credential.visibility_level,
        user,
        customer,
        has_grant=lambda: customer is not None
        and credential.customer_grants.filter(customer=customer).exists(),
    )


def filter_credentials_visible_to(qs, user, customer):
    """Queryset twin of `credential_visible_to_user` — the SAME table
    expressed as queryset filters; keep the two in lockstep."""
    role = getattr(user, "role", None)
    if role in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN):
        return qs
    if role == UserRole.BUILDING_MANAGER:
        return qs.filter(
            visibility_level__in=(
                VisibilityLevel.PROVIDER_ONLY,
                VisibilityLevel.CUSTOMER_VISIBLE,
            )
        )
    if role == UserRole.CUSTOMER_USER:
        if not _viewer_is_member(user, customer):
            return qs.none()
        # The (credential, customer) grant pair is unique, so the join
        # yields at most one row per credential — no distinct() needed.
        return qs.filter(
            visibility_level=VisibilityLevel.CUSTOMER_VISIBLE,
            customer_grants__customer=customer,
        )
    return qs.none()


def property_visible_to_user(prop, user, customer) -> bool:
    """Per-item FIELD-visibility predicate for a CustomProfileProperty."""
    return _field_visible(
        prop.visibility_level,
        user,
        customer,
        has_grant=lambda: customer is not None
        and prop.customer_grants.filter(customer=customer).exists(),
    )


def filter_properties_visible_to(qs, user, customer):
    """Queryset twin of `property_visible_to_user` — same table, same
    lockstep rule as the credential pair above."""
    role = getattr(user, "role", None)
    if role in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN):
        return qs
    if role == UserRole.BUILDING_MANAGER:
        return qs.filter(
            visibility_level__in=(
                VisibilityLevel.PROVIDER_ONLY,
                VisibilityLevel.CUSTOMER_VISIBLE,
            )
        )
    if role == UserRole.CUSTOMER_USER:
        if not _viewer_is_member(user, customer):
            return qs.none()
        return qs.filter(
            visibility_level=VisibilityLevel.CUSTOMER_VISIBLE,
            customer_grants__customer=customer,
        )
    return qs.none()


def credential_document_visible_to_user(credential, user, customer) -> bool:
    """DOCUMENT sub-rule for credentials — strictly narrower than (or
    equal to) field visibility; never wider."""
    if not credential_visible_to_user(credential, user, customer):
        return False
    role = getattr(user, "role", None)
    if credential.credential_type == StaffCredential.CredentialType.EU_NATIONAL_ID:
        # Field visibility already pins EU-ID to PA_SA_ONLY (so BM and
        # customers fail above); this explicit branch is the
        # belt-and-suspenders compliance block: PA / SA only, ever.
        return role in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN)
    if role == UserRole.CUSTOMER_USER:
        if (
            credential.credential_type
            == StaffCredential.CredentialType.RESIDENCE_PERMIT
        ):
            # "Show the photocopy too?" — fields yes, document only
            # with the explicit per-credential flag.
            return bool(credential.document_customer_visible)
        return True  # VCA: document == field visibility.
    return True  # provider roles that pass the field gate see the document.


def property_document_visible_to_user(prop, user, customer) -> bool:
    """DOCUMENT sub-rule for properties: document == field visibility."""
    return property_visible_to_user(prop, user, customer)
