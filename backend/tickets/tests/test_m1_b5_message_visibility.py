"""
M1 B5 — ticket message visibility model rewrite (security-critical).

Five channels. Read-visibility (who may SEE a NORMAL message of each tier):

  message_type        SA   MGMT  STAFF  CUST
  ------------------   ---  ----  -----  ----
  PUBLIC_REPLY          v    v     -      v     (B5: STAFF dropped)
  STAFF_COMPLETION      v    v     v      v
  STAFF_OPERATIONAL     v    v     v      -
  INTERNAL_NOTE         v    v     -      -
  CUSTOMER_INTERNAL     v    -     -      v     (B5: new, customer-only)

Posting (who may CREATE each tier):
  PUBLIC_REPLY       CUST + MGMT + SA   (NOT staff)
  STAFF_COMPLETION   STAFF (+ provider-side)
  STAFF_OPERATIONAL  STAFF + MGMT + SA
  INTERNAL_NOTE      MGMT + SA
  CUSTOMER_INTERNAL  CUST

directed_to / RESTRICTED:
  * CUST author: directed_to is customer-side only (never a provider user, on
    ANY tier); RESTRICTED only on CUSTOMER_INTERNAL.
  * STAFF author: no directed_to and no RESTRICTED, ever.
  * MGMT / SA author: directed_to across the full tier audience; RESTRICTED on
    any tier (existing B2/B3 behaviour).

Everything below is enforced SERVER-SIDE (chokepoint + create-path authz +
validation). The FE composer only mirrors it.
"""
from __future__ import annotations

import json

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from customers.models import CustomerUserBuildingAccess, CustomerUserMembership
from notifications.models import Notification
from test_utils import TenantFixtureMixin
from tickets.models import (
    TicketMessage,
    TicketMessageType,
    TicketMessageVisibility,
    TicketStaffAssignment,
)

MT = TicketMessageType
VIS = TicketMessageVisibility
AccessRole = CustomerUserBuildingAccess.AccessRole


class _B5Fixture(TenantFixtureMixin, APITestCase):
    """Roles on `self.ticket` (Building A / Customer A):

      * SA    = self.super_admin
      * MGMT  = self.company_admin (CA) + self.manager (BM of the building)
      * STAFF = self.staff_user (assigned to the ticket)
      * CUST  = self.customer_user (the ticket creator, view_own) +
                self.customer_user2 / self.customer_user3 (view_location, so
                they can read the ticket regardless of who created it).
    """

    def setUp(self):
        super().setUp()
        self.staff_user = self.make_user("staff-b5@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=self.staff_user, is_active=True)
        BuildingStaffVisibility.objects.create(
            user=self.staff_user, building=self.building
        )
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.staff_user
        )

        self.customer_user2 = self._customer_member("cust2-b5@example.com")
        self.customer_user3 = self._customer_member("cust3-b5@example.com")

    def _customer_member(self, email):
        user = self.make_user(email, UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            user=user, customer=self.customer
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=self.building,
            access_role=AccessRole.CUSTOMER_LOCATION_MANAGER,
        )
        return user

    # -- helpers ---------------------------------------------------------
    def _messages_url(self, ticket=None):
        return f"/api/tickets/{(ticket or self.ticket).id}/messages/"

    def _recipients_url(self, ticket=None):
        return f"/api/tickets/{(ticket or self.ticket).id}/message-recipients/"

    def _timeline_url(self, ticket=None):
        return f"/api/audit/tickets/{(ticket or self.ticket).id}/timeline/"

    def _mk(self, author, message_type, *, visibility=VIS.NORMAL, directed=None,
            message="x"):
        msg = TicketMessage.objects.create(
            ticket=self.ticket,
            author=author,
            message_type=message_type,
            visibility_mode=visibility,
            message=message,
            is_hidden=(message_type == MT.INTERNAL_NOTE),
        )
        if directed:
            msg.directed_to.set(directed)
        return msg

    def _visible_ids(self, actor):
        self.authenticate(actor)
        resp = self.client.get(self._messages_url())
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        data = resp.data.get("results", resp.data)
        return {row["id"] for row in data}

    def _post(self, author, **payload):
        self.authenticate(author)
        body = {"message": payload.pop("message", "hi")}
        body.update(payload)
        return self.client.post(self._messages_url(), body, format="json")

    def _recipients(self, actor, message_type):
        self.authenticate(actor)
        resp = self.client.get(
            self._recipients_url() + f"?message_type={message_type}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        return resp.data["results"]

    def _recipient_ids_for(self, message):
        return set(
            Notification.objects.filter(ticket=self.ticket).values_list(
                "recipient_id", flat=True
            )
        )


# ---------------------------------------------------------------------------
# READ visibility per role (NORMAL)
# ---------------------------------------------------------------------------
class ReadVisibilityTests(_B5Fixture):
    def setUp(self):
        super().setUp()
        self.public = self._mk(self.manager, MT.PUBLIC_REPLY)
        self.internal = self._mk(self.manager, MT.INTERNAL_NOTE)
        self.operational = self._mk(self.manager, MT.STAFF_OPERATIONAL)
        self.completion = self._mk(self.staff_user, MT.STAFF_COMPLETION)
        self.customer_internal = self._mk(self.customer_user, MT.CUSTOMER_INTERNAL)

    def test_super_admin_sees_every_tier(self):
        self.assertEqual(
            self._visible_ids(self.super_admin),
            {
                self.public.id,
                self.internal.id,
                self.operational.id,
                self.completion.id,
                self.customer_internal.id,
            },
        )

    def test_mgmt_sees_all_except_customer_internal(self):
        for actor in (self.company_admin, self.manager):
            self.assertEqual(
                self._visible_ids(actor),
                {
                    self.public.id,
                    self.internal.id,
                    self.operational.id,
                    self.completion.id,
                },
                f"actor={actor.email}",
            )
            self.assertNotIn(
                self.customer_internal.id, self._visible_ids(actor)
            )

    def test_staff_sees_operational_and_completion_only(self):
        ids = self._visible_ids(self.staff_user)
        self.assertEqual(ids, {self.operational.id, self.completion.id})
        # STAFF must NOT read PUBLIC_REPLY, INTERNAL_NOTE, or CUSTOMER_INTERNAL.
        self.assertNotIn(self.public.id, ids)
        self.assertNotIn(self.internal.id, ids)
        self.assertNotIn(self.customer_internal.id, ids)

    def test_customer_sees_public_completion_and_customer_internal(self):
        ids = self._visible_ids(self.customer_user)
        self.assertEqual(
            ids,
            {self.public.id, self.completion.id, self.customer_internal.id},
        )
        # Never the provider-only tiers.
        self.assertNotIn(self.internal.id, ids)
        self.assertNotIn(self.operational.id, ids)


# ---------------------------------------------------------------------------
# RESTRICTED CUSTOMER_INTERNAL — party-only (layer b), incl. NOT SA on the list
# ---------------------------------------------------------------------------
class RestrictedCustomerInternalReadTests(_B5Fixture):
    def setUp(self):
        super().setUp()
        # Customer author makes a CUSTOMER_INTERNAL RESTRICTED, directed at
        # one other customer-side member.
        self.msg = self._mk(
            self.customer_user,
            MT.CUSTOMER_INTERNAL,
            visibility=VIS.RESTRICTED,
            directed=[self.customer_user2],
            message="CUST-PRIVATE-marker",
        )

    def test_visible_only_to_author_and_directed_customer(self):
        self.assertIn(self.msg.id, self._visible_ids(self.customer_user))   # author
        self.assertIn(self.msg.id, self._visible_ids(self.customer_user2))  # directed
        # Non-directed customer member: customer-side + can read the ticket,
        # but NOT a party to the RESTRICTED message.
        self.assertNotIn(self.msg.id, self._visible_ids(self.customer_user3))
        # MGMT can't read CUSTOMER_INTERNAL at all.
        self.assertNotIn(self.msg.id, self._visible_ids(self.manager))
        self.assertNotIn(self.msg.id, self._visible_ids(self.company_admin))
        # SA is forensic for the TIER but is STILL bound by the RESTRICTED
        # party filter on the per-ticket list (B2 decision).
        self.assertNotIn(self.msg.id, self._visible_ids(self.super_admin))


# ---------------------------------------------------------------------------
# Audit timeline inherits the chokepoint: MGMT never sees CUSTOMER_INTERNAL
# ---------------------------------------------------------------------------
class TimelineCustomerInternalRedactionTests(_B5Fixture):
    def _timeline_message_ids(self, actor):
        self.authenticate(actor)
        resp = self.client.get(self._timeline_url())
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        ids = {
            entry.get("target_id")
            for entry in resp.data["timeline"]
            if entry.get("source") == "audit_log"
            and entry.get("target_model") == "tickets.TicketMessage"
        }
        return ids, json.dumps(resp.data)

    def test_mgmt_timeline_excludes_customer_internal(self):
        body = "CUSTOMER-INTERNAL-TIMELINE-marker"
        resp = self._post(
            self.customer_user, message=body, message_type=MT.CUSTOMER_INTERNAL
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        msg_id = resp.data["id"]
        ids, raw = self._timeline_message_ids(self.company_admin)
        self.assertNotIn(msg_id, ids)
        self.assertNotIn(body, raw)


# ---------------------------------------------------------------------------
# POSTING authz (the POSTING table)
# ---------------------------------------------------------------------------
class PostingAuthzTests(_B5Fixture):
    def test_staff_cannot_post_public_reply(self):
        resp = self._post(self.staff_user, message_type=MT.PUBLIC_REPLY)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)
        self.assertEqual(
            getattr(resp.data["message_type"][0], "code", None),
            "message_type_not_allowed",
        )
        self.assertFalse(TicketMessage.objects.exists())

    def test_customer_cannot_post_internal_note(self):
        resp = self._post(self.customer_user, message_type=MT.INTERNAL_NOTE)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)
        self.assertFalse(TicketMessage.objects.exists())

    def test_customer_cannot_post_staff_operational(self):
        resp = self._post(self.customer_user, message_type=MT.STAFF_OPERATIONAL)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)
        self.assertFalse(TicketMessage.objects.exists())

    def test_mgmt_cannot_post_customer_internal(self):
        for actor in (self.manager, self.company_admin):
            resp = self._post(actor, message_type=MT.CUSTOMER_INTERNAL)
            self.assertEqual(
                resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content
            )
        self.assertFalse(
            TicketMessage.objects.filter(
                message_type=MT.CUSTOMER_INTERNAL
            ).exists()
        )

    def test_mgmt_can_post_staff_operational(self):
        # The expansion: MGMT relays operational instructions to staff.
        resp = self._post(self.manager, message_type=MT.STAFF_OPERATIONAL)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        self.assertEqual(resp.data["message_type"], MT.STAFF_OPERATIONAL)

    def test_customer_can_post_customer_internal(self):
        resp = self._post(self.customer_user, message_type=MT.CUSTOMER_INTERNAL)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        # Saved verbatim — NOT coerced to PUBLIC_REPLY.
        self.assertEqual(resp.data["message_type"], MT.CUSTOMER_INTERNAL)

    def test_customer_can_still_post_public_reply(self):
        resp = self._post(self.customer_user, message_type=MT.PUBLIC_REPLY)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        self.assertEqual(resp.data["message_type"], MT.PUBLIC_REPLY)

    def test_staff_post_without_message_type_is_rejected(self):
        # Default path: a STAFF POST with no message_type would default to
        # PUBLIC_REPLY, which STAFF may not author -> 400 (the validate()
        # gate covers the defaulted-field path, not just explicit input).
        resp = self._post(self.staff_user)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)
        self.assertFalse(TicketMessage.objects.exists())


# ---------------------------------------------------------------------------
# directed_to / RESTRICTED side-aware authz
# ---------------------------------------------------------------------------
class DirectedRestrictedAuthzTests(_B5Fixture):
    def test_customer_cannot_direct_a_provider_user(self):
        resp = self._post(
            self.customer_user,
            message_type=MT.PUBLIC_REPLY,
            directed_to=[self.manager.id],
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)
        self.assertEqual(
            getattr(resp.data["directed_to"][0], "code", None),
            "directed_to_must_be_customer_side",
        )
        self.assertFalse(TicketMessage.objects.exists())

    def test_customer_can_direct_another_customer_on_public_reply(self):
        resp = self._post(
            self.customer_user,
            message_type=MT.PUBLIC_REPLY,
            directed_to=[self.customer_user2.id],
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)

    def test_customer_cannot_restrict_a_public_reply(self):
        resp = self._post(
            self.customer_user,
            message_type=MT.PUBLIC_REPLY,
            visibility_mode=VIS.RESTRICTED,
            directed_to=[self.customer_user2.id],
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)
        self.assertEqual(
            getattr(resp.data["visibility_mode"][0], "code", None),
            "restricted_only_for_customer_internal",
        )
        self.assertFalse(TicketMessage.objects.exists())

    def test_customer_can_restrict_a_customer_internal(self):
        resp = self._post(
            self.customer_user,
            message_type=MT.CUSTOMER_INTERNAL,
            visibility_mode=VIS.RESTRICTED,
            directed_to=[self.customer_user2.id],
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        self.assertEqual(resp.data["visibility_mode"], VIS.RESTRICTED)

    def test_staff_cannot_direct(self):
        resp = self._post(
            self.staff_user,
            message_type=MT.STAFF_OPERATIONAL,
            directed_to=[self.manager.id],
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)
        self.assertEqual(
            getattr(resp.data["directed_to"][0], "code", None),
            "staff_cannot_direct_or_restrict",
        )
        self.assertFalse(TicketMessage.objects.exists())

    def test_staff_cannot_restrict(self):
        resp = self._post(
            self.staff_user,
            message_type=MT.STAFF_OPERATIONAL,
            visibility_mode=VIS.RESTRICTED,
            directed_to=[self.staff_user.id],
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)
        self.assertEqual(
            getattr(resp.data["directed_to"][0], "code", None),
            "staff_cannot_direct_or_restrict",
        )
        self.assertFalse(TicketMessage.objects.exists())


# ---------------------------------------------------------------------------
# Recipients endpoint — side-aware by caller + no email
# ---------------------------------------------------------------------------
class RecipientsSideAwareTests(_B5Fixture):
    def test_staff_caller_gets_empty_picker(self):
        for tier in (MT.STAFF_OPERATIONAL, MT.STAFF_COMPLETION):
            results = self._recipients(self.staff_user, tier)
            self.assertEqual(results, [])

    def test_customer_caller_gets_customer_side_only(self):
        results = self._recipients(self.customer_user, MT.PUBLIC_REPLY)
        sides = {r["side"] for r in results}
        ids = {r["id"] for r in results}
        # Only customer-side candidates; never a provider/staff user.
        self.assertEqual(sides, {"customer"})
        self.assertIn(self.customer_user2.id, ids)
        self.assertNotIn(self.manager.id, ids)
        self.assertNotIn(self.company_admin.id, ids)
        self.assertNotIn(self.staff_user.id, ids)
        # The caller is never in their own picker.
        self.assertNotIn(self.customer_user.id, ids)
        # No `email` on the payload.
        self.assertTrue(all("email" not in r for r in results))

    def test_customer_internal_picker_is_customer_side_only(self):
        results = self._recipients(self.customer_user, MT.CUSTOMER_INTERNAL)
        self.assertTrue(results)
        self.assertEqual({r["side"] for r in results}, {"customer"})

    def test_mgmt_caller_gets_full_audience(self):
        results = self._recipients(self.manager, MT.PUBLIC_REPLY)
        ids = {r["id"] for r in results}
        # Full tier audience: provider-mgmt + customer-side (no STAFF in the
        # PUBLIC_REPLY audience).
        self.assertIn(self.company_admin.id, ids)
        self.assertIn(self.customer_user.id, ids)
        self.assertNotIn(self.staff_user.id, ids)


# ---------------------------------------------------------------------------
# EMIT — fan-out follows the new audience
# ---------------------------------------------------------------------------
class EmitTests(_B5Fixture):
    def test_public_reply_notifies_mgmt_and_customer_not_staff(self):
        resp = self._post(self.manager, message_type=MT.PUBLIC_REPLY)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        recipients = self._recipient_ids_for(resp.data["id"])
        self.assertIn(self.company_admin.id, recipients)
        self.assertIn(self.customer_user.id, recipients)
        # STAFF is never notified about a PUBLIC_REPLY.
        self.assertNotIn(self.staff_user.id, recipients)
        # Author excluded.
        self.assertNotIn(self.manager.id, recipients)

    def test_customer_internal_normal_notifies_customer_side_only(self):
        resp = self._post(
            self.customer_user, message_type=MT.CUSTOMER_INTERNAL
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        recipients = self._recipient_ids_for(resp.data["id"])
        # Other customer-side members notified; never provider-mgmt or STAFF.
        self.assertIn(self.customer_user2.id, recipients)
        self.assertIn(self.customer_user3.id, recipients)
        self.assertNotIn(self.manager.id, recipients)
        self.assertNotIn(self.company_admin.id, recipients)
        self.assertNotIn(self.staff_user.id, recipients)
        self.assertNotIn(self.super_admin.id, recipients)
        # Author excluded.
        self.assertNotIn(self.customer_user.id, recipients)

    def test_customer_internal_restricted_notifies_directed_only(self):
        resp = self._post(
            self.customer_user,
            message_type=MT.CUSTOMER_INTERNAL,
            visibility_mode=VIS.RESTRICTED,
            directed_to=[self.customer_user2.id],
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        recipients = self._recipient_ids_for(resp.data["id"])
        self.assertEqual(recipients, {self.customer_user2.id})


# ---------------------------------------------------------------------------
# LOCKSTEP — message_type_visible_to_user (predicate) and
# filter_messages_visible_to layer (a) (queryset) are the SAME table in two
# forms. They MUST agree cell-for-cell; if a future tier is added to only one
# form, this regression test fails (the predicate uses allow-lists, the
# queryset uses deny-lists, so they would silently diverge on a new tier).
# ---------------------------------------------------------------------------
class LockstepParityTests(_B5Fixture):
    def test_predicate_and_queryset_agree_for_every_role_and_tier(self):
        from tickets.permissions import (
            filter_messages_visible_to,
            message_type_visible_to_user,
        )

        # One NORMAL, non-hidden message per tier so only the TIER dimension
        # is exercised (is_hidden / RESTRICTED are isolated out — they are
        # no-ops for a non-hidden NORMAL row, so the queryset reflects the
        # pure layer-(a) tier exclusion).
        per_tier = {}
        for tier in (
            MT.PUBLIC_REPLY,
            MT.INTERNAL_NOTE,
            MT.STAFF_OPERATIONAL,
            MT.STAFF_COMPLETION,
            MT.CUSTOMER_INTERNAL,
        ):
            per_tier[tier] = TicketMessage.objects.create(
                ticket=self.ticket,
                author=self.manager,
                message_type=tier,
                visibility_mode=VIS.NORMAL,
                message="x",
                is_hidden=False,
            )

        actors = {
            "SA": self.super_admin,
            "CA": self.company_admin,
            "BM": self.manager,
            "STAFF": self.staff_user,
            "CUST": self.customer_user,
            "anon": None,  # userless / unauthenticated -> customer-side branch
        }
        for label, user in actors.items():
            visible_ids = set(
                filter_messages_visible_to(
                    TicketMessage.objects.filter(ticket=self.ticket), user
                ).values_list("id", flat=True)
            )
            for tier, msg in per_tier.items():
                predicate = message_type_visible_to_user(user, tier)
                in_queryset = msg.id in visible_ids
                self.assertEqual(
                    predicate,
                    in_queryset,
                    f"lockstep drift: actor={label} tier={tier} "
                    f"predicate={predicate} queryset={in_queryset}",
                )
