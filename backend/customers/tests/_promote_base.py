"""
Sprint 12B Batch 3 — shared fixture base for the Contacts →
promote-to-user test suite.

Extends `TenantFixtureMixin.setUp` with the extra rows the
multi-building + promote tests need:

  * `self.building2` — a second building under `self.company`, linked to
    `self.customer` via `CustomerBuildingMembership`, so the
    multi-building link tests have a real second target inside the same
    customer.
  * `self.staff` — a STAFF user (+ StaffProfile) for the permission /
    tenancy denial tests.

Plus the helpers the suite reuses:

  * `make_contact(...)` — create a `Contact` row directly (the
    phone-book path, NOT the promote path).
  * `contact_list_url` / `contact_detail_url` / `promote_url` — URL
    builders for the contact CRUD + promote endpoints.

The raw-invitation-token capture helper mirrors
`accounts/tests/test_invitations.py`: the promote view calls
`notifications.services.send_invitation_email` via a local
`from notifications.services import send_invitation_email` inside
`post()`. A local `from X import Y` still resolves `Y` from module `X`
at call time, so patching `notifications.services.send_invitation_email`
intercepts the call and lets us read the `raw_token` kwarg.
"""
from __future__ import annotations

from unittest import mock

from accounts.models import StaffProfile, UserRole
from buildings.models import Building
from customers.models import (
    Contact,
    CustomerBuildingMembership,
)
from test_utils import TenantFixtureMixin


class PromoteContactFixtureMixin(TenantFixtureMixin):
    """Shared fixture for the promote-to-user suite.

    NOTE: invite-mode tests mock `notifications.services.send_invitation_email`
    so no real SMTP transport is ever exercised; the concrete invite-mode
    test class still pins the locmem email backend defensively via
    `@override_settings` so an unmocked path (should one ever exist) cannot
    reach a real transport.
    """

    def setUp(self):
        super().setUp()

        # Second building under company A, linked to customer A so
        # multi-building grants have a real second target.
        self.building2 = Building.objects.create(
            company=self.company,
            name="Building A2",
            address="Main Street 2",
        )
        CustomerBuildingMembership.objects.create(
            customer=self.customer, building=self.building2
        )

        # STAFF principal (+ profile) for the permission denial tests.
        self.staff = self.make_user("staff-a@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=self.staff)

    # ---- fixture helpers --------------------------------------------------

    def make_contact(self, customer=None, **fields) -> Contact:
        """Create a `Contact` directly (phone-book path, not promote).

        Sprint 12C — promotion now requires a valid NL phone on the
        contact, so the fixture seeds a valid default phone unless the
        caller overrides it. Tests for the missing/invalid-phone guards
        pass `phone=""` / `phone="<garbage>"` explicitly.
        """
        customer = customer or self.customer
        fields.setdefault("phone", "+31612345678")
        return Contact.objects.create(customer=customer, **fields)

    # ---- URL builders -----------------------------------------------------

    def contact_list_url(self, customer_id=None) -> str:
        customer_id = customer_id if customer_id is not None else self.customer.id
        return f"/api/customers/{customer_id}/contacts/"

    def contact_detail_url(self, contact_id, customer_id=None) -> str:
        customer_id = customer_id if customer_id is not None else self.customer.id
        return f"/api/customers/{customer_id}/contacts/{contact_id}/"

    def promote_url(self, contact_id, customer_id=None) -> str:
        customer_id = customer_id if customer_id is not None else self.customer.id
        return (
            f"/api/customers/{customer_id}/contacts/{contact_id}/"
            "promote-to-user/"
        )

    # ---- raw-token capture (mirrors accounts/tests/test_invitations.py) ---

    def promote_and_capture_raw(self, contact_id, payload=None, customer_id=None):
        """POST the promote endpoint while intercepting
        `send_invitation_email` to capture the raw invitation token.

        Returns `(response, raw_token)`. `raw_token` is None when the
        email helper was not called (link mode, conflict, or an
        already-invited re-promote)."""
        captured = {}

        def fake_send(invitation, raw_token, accept_url):
            captured["raw"] = raw_token

        with mock.patch(
            "notifications.services.send_invitation_email",
            side_effect=fake_send,
        ):
            response = self.client.post(
                self.promote_url(contact_id, customer_id=customer_id),
                payload or {},
                format="json",
            )
        return response, captured.get("raw")
