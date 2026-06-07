"""
M1 B3 — directed-recipients endpoint + directed_to_detail display field.

GET /api/tickets/<id>/message-recipients/?message_type=<tier> drives the
composer's "notify specific people" picker. Its output must ALWAYS be a
subset of the valid directed_to targets the B1 serializer accepts for that
tier, so the picker can never offer a target the POST would 400:
  * INTERNAL_NOTE      -> provider management only (no customer, no staff).
  * STAFF_OPERATIONAL  -> provider + assigned staff (no customer).
  * PUBLIC_REPLY       -> provider + customer-side (M1 B5: STAFF dropped).
  * STAFF_COMPLETION   -> provider + assigned staff + customer-side.
  * a customer-org member without building access is never returned (scope).
  * the caller is never in their own picker.
  * M1 B5: the picker is side-aware by CALLER — a STAFF caller gets [];
    a CUSTOMER caller gets customer-side candidates only.

directed_to_detail is a read-only display field on the message list; it must
not bypass the B2 chokepoint (a non-party never sees a RESTRICTED message,
so never its directed_to_detail).
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from customers.models import CustomerUserMembership
from test_utils import TenantFixtureMixin
from tickets.models import (
    TicketMessageType,
    TicketMessageVisibility,
    TicketStaffAssignment,
)


class _B3Fixture(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.staff_user = self.make_user("staff-b3@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=self.staff_user, is_active=True)
        BuildingStaffVisibility.objects.create(
            user=self.staff_user, building=self.building
        )
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.staff_user
        )
        # Member of Customer A with NO building access -> cannot read the
        # ticket -> must never be offered as a directed recipient.
        self.customer_no_access = self.make_user(
            "customer-noaccess-b3@example.com", UserRole.CUSTOMER_USER
        )
        CustomerUserMembership.objects.create(
            user=self.customer_no_access, customer=self.customer
        )

    def _recipients_url(self, ticket=None):
        ticket = ticket or self.ticket
        return f"/api/tickets/{ticket.id}/message-recipients/"

    def _messages_url(self, ticket=None):
        ticket = ticket or self.ticket
        return f"/api/tickets/{ticket.id}/messages/"

    def _recipients(self, actor, message_type=None):
        self.authenticate(actor)
        url = self._recipients_url()
        if message_type is not None:
            url += f"?message_type={message_type}"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        return resp.data["results"]

    @staticmethod
    def _ids(results):
        return {r["id"] for r in results}

    @staticmethod
    def _side_of(results, user_id):
        for r in results:
            if r["id"] == user_id:
                return r["side"]
        return None


class RecipientsPerTierTests(_B3Fixture):
    def test_public_reply_includes_provider_and_customer_not_staff(self):
        # M1 B5 — PUBLIC_REPLY audience = provider-mgmt + customer; STAFF is
        # dropped, so a manager composing a PUBLIC_REPLY is never offered a
        # staff target.
        results = self._recipients(self.manager, TicketMessageType.PUBLIC_REPLY)
        ids = self._ids(results)
        self.assertIn(self.company_admin.id, ids)
        self.assertIn(self.customer_user.id, ids)
        self.assertNotIn(self.staff_user.id, ids)
        # Caller excluded; out-of-scope customer-org member excluded.
        self.assertNotIn(self.manager.id, ids)
        self.assertNotIn(self.customer_no_access.id, ids)
        # SUPER_ADMIN is not auto-audience (mirrors emit), so not offered.
        self.assertNotIn(self.super_admin.id, ids)
        # Sides are correctly bucketed.
        self.assertEqual(self._side_of(results, self.company_admin.id), "provider")
        self.assertEqual(self._side_of(results, self.customer_user.id), "customer")
        # M1 B5 — the payload no longer carries an `email` field.
        self.assertTrue(all("email" not in r for r in results))

    def test_internal_note_provider_only(self):
        ids = self._ids(self._recipients(self.manager, TicketMessageType.INTERNAL_NOTE))
        self.assertIn(self.company_admin.id, ids)
        self.assertNotIn(self.customer_user.id, ids)
        self.assertNotIn(self.staff_user.id, ids)
        self.assertNotIn(self.customer_no_access.id, ids)

    def test_staff_operational_excludes_customer(self):
        ids = self._ids(
            self._recipients(self.manager, TicketMessageType.STAFF_OPERATIONAL)
        )
        self.assertIn(self.company_admin.id, ids)
        self.assertIn(self.staff_user.id, ids)
        self.assertNotIn(self.customer_user.id, ids)
        self.assertNotIn(self.customer_no_access.id, ids)

    def test_staff_completion_includes_customer(self):
        ids = self._ids(
            self._recipients(self.manager, TicketMessageType.STAFF_COMPLETION)
        )
        self.assertIn(self.customer_user.id, ids)
        self.assertIn(self.staff_user.id, ids)

    def test_default_message_type_is_public_reply(self):
        with_default = self._ids(self._recipients(self.manager))
        explicit = self._ids(
            self._recipients(self.manager, TicketMessageType.PUBLIC_REPLY)
        )
        self.assertEqual(with_default, explicit)

    def test_invalid_message_type_400(self):
        self.authenticate(self.manager)
        resp = self.client.get(self._recipients_url() + "?message_type=BOGUS")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data.get("code"), "invalid_message_type")

    def test_out_of_scope_caller_404(self):
        # CA of a different company has no scope on this ticket.
        self.authenticate(self.other_company_admin)
        resp = self.client.get(self._recipients_url())
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class RecipientsMatchValidationTests(_B3Fixture):
    """Every user the endpoint offers must be ACCEPTED by the B1 directed_to
    validation for that tier (subset-of-valid invariant)."""

    def _post_directed(self, author, message_type, directed_ids):
        self.authenticate(author)
        return self.client.post(
            self._messages_url(),
            {
                "message": "directed",
                "message_type": message_type,
                "directed_to": list(directed_ids),
            },
            format="json",
        )

    def test_every_public_reply_recipient_is_accepted(self):
        ids = self._ids(self._recipients(self.manager, TicketMessageType.PUBLIC_REPLY))
        resp = self._post_directed(self.manager, TicketMessageType.PUBLIC_REPLY, ids)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)

    def test_every_internal_note_recipient_is_accepted(self):
        ids = self._ids(self._recipients(self.manager, TicketMessageType.INTERNAL_NOTE))
        self.assertTrue(ids)  # at least company_admin
        resp = self._post_directed(self.manager, TicketMessageType.INTERNAL_NOTE, ids)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)

    def test_customer_not_offered_for_internal_note_and_post_would_400(self):
        ids = self._ids(self._recipients(self.manager, TicketMessageType.INTERNAL_NOTE))
        self.assertNotIn(self.customer_user.id, ids)
        # And the POST the picker prevented would indeed be rejected.
        resp = self._post_directed(
            self.manager, TicketMessageType.INTERNAL_NOTE, [self.customer_user.id]
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            getattr(resp.data["directed_to"][0], "code", None),
            "directed_to_not_visible",
        )


class DirectedToDetailDisplayTests(_B3Fixture):
    def test_list_exposes_directed_to_detail_and_visibility_mode(self):
        self.authenticate(self.manager)
        resp = self.client.post(
            self._messages_url(),
            {
                "message": "directed normal",
                "message_type": TicketMessageType.PUBLIC_REPLY,
                "directed_to": [self.customer_user.id],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        msg_id = resp.data["id"]

        listing = self.client.get(self._messages_url())
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        data = listing.data.get("results", listing.data)
        row = next(m for m in data if m["id"] == msg_id)
        self.assertEqual(row["visibility_mode"], "NORMAL")
        self.assertEqual(
            row["directed_to_detail"],
            [{"id": self.customer_user.id, "full_name": self.customer_user.full_name}],
        )

    def test_directed_to_detail_does_not_bypass_b2(self):
        # A RESTRICTED message directed to the customer: a non-party provider
        # admin (company_admin) must not see the message at all -> so cannot
        # see its directed_to_detail either.
        self.authenticate(self.manager)
        resp = self.client.post(
            self._messages_url(),
            {
                "message": "secret",
                "message_type": TicketMessageType.PUBLIC_REPLY,
                "visibility_mode": TicketMessageVisibility.RESTRICTED,
                "directed_to": [self.customer_user.id],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        msg_id = resp.data["id"]

        self.authenticate(self.company_admin)
        listing = self.client.get(self._messages_url())
        ids = {m["id"] for m in listing.data.get("results", listing.data)}
        self.assertNotIn(msg_id, ids)
