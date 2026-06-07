"""
M1 B2 — RESTRICTED message read-side ACL.

A RESTRICTED TicketMessage (visibility_mode=RESTRICTED, added in B1) is
readable ONLY by its author + the directed_to users — enforced on the
backend for EVERY role, including provider management. A provider admin (or
a customer company admin) who is neither author nor a directed_to target
must not see it in the message list, must not be able to infer it from the
list length / count, and must not see its existence/body via the audit
timeline.

NORMAL messages and the existing B7 role-based message_type visibility are
UNCHANGED (the chokepoint refactor must be byte-equivalent for NORMAL).

No frontend (B3). No model change / migration. Single chokepoint:
tickets.permissions.filter_messages_visible_to.
"""
from __future__ import annotations

import json

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingManagerAssignment, BuildingStaffVisibility
from test_utils import TenantFixtureMixin
from tickets.models import (
    TicketMessage,
    TicketMessageType,
    TicketMessageVisibility,
    TicketStaffAssignment,
)


class _B2Fixture(TenantFixtureMixin, APITestCase):
    """Tenant fixture + an assigned STAFF, plus a SECOND building manager
    of Building A so there is an in-scope provider-management actor who is
    NOT a party to a directed message (the canonical "non-party admin")."""

    def setUp(self):
        super().setUp()
        self.staff_user = self.make_user("staff-b2@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=self.staff_user, is_active=True)
        BuildingStaffVisibility.objects.create(
            user=self.staff_user, building=self.building
        )
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.staff_user
        )
        # Second BM of the SAME building -> in scope for self.ticket, provider
        # management, but not author/directed on the messages below.
        self.manager2 = self.make_user("manager-a2@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=self.manager2, building=self.building
        )

    def _messages_url(self, ticket=None):
        ticket = ticket or self.ticket
        return f"/api/tickets/{ticket.id}/messages/"

    def _timeline_url(self, ticket=None):
        ticket = ticket or self.ticket
        return f"/api/audit/tickets/{ticket.id}/timeline/"

    def _mk(
        self,
        author,
        body,
        message_type=TicketMessageType.PUBLIC_REPLY,
        visibility_mode=TicketMessageVisibility.NORMAL,
        directed=None,
        is_hidden=None,
    ):
        msg = TicketMessage.objects.create(
            ticket=self.ticket,
            author=author,
            message=body,
            message_type=message_type,
            visibility_mode=visibility_mode,
            is_hidden=(
                is_hidden
                if is_hidden is not None
                else message_type == TicketMessageType.INTERNAL_NOTE
            ),
        )
        if directed:
            msg.directed_to.set(directed)
        return msg

    def _list_ids(self, actor):
        self.authenticate(actor)
        resp = self.client.get(self._messages_url())
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        data = resp.data.get("results", resp.data)
        return {item["id"] for item in data}


# ---------------------------------------------------------------------------
# A. RESTRICTED read enforcement — author + directed only, for every role
# ---------------------------------------------------------------------------
class RestrictedReadEnforcementTests(_B2Fixture):
    def test_restricted_public_reply_visible_only_to_author_and_directed(self):
        msg = self._mk(
            self.manager,
            "restricted public reply",
            message_type=TicketMessageType.PUBLIC_REPLY,
            visibility_mode=TicketMessageVisibility.RESTRICTED,
            directed=[self.customer_user],
        )
        # Party: author + directed see it.
        self.assertIn(msg.id, self._list_ids(self.manager))
        self.assertIn(msg.id, self._list_ids(self.customer_user))
        # Non-party — for EVERY role, including provider management + SA.
        self.assertNotIn(msg.id, self._list_ids(self.company_admin))
        self.assertNotIn(msg.id, self._list_ids(self.super_admin))
        self.assertNotIn(msg.id, self._list_ids(self.manager2))
        self.assertNotIn(msg.id, self._list_ids(self.staff_user))

    def test_restricted_internal_note_directed_to_one_manager(self):
        # INTERNAL_NOTE authored by a provider admin, directed to ONE BM.
        msg = self._mk(
            self.company_admin,
            "restricted internal directed to manager",
            message_type=TicketMessageType.INTERNAL_NOTE,
            visibility_mode=TicketMessageVisibility.RESTRICTED,
            directed=[self.manager],
            is_hidden=True,
        )
        # Party: author (CA) + directed (the one BM).
        self.assertIn(msg.id, self._list_ids(self.company_admin))
        self.assertIn(msg.id, self._list_ids(self.manager))
        # A DIFFERENT provider manager (and SA) — non-party — cannot see it.
        self.assertNotIn(msg.id, self._list_ids(self.manager2))
        self.assertNotIn(msg.id, self._list_ids(self.super_admin))

    def test_restricted_does_not_widen_role_visibility(self):
        # A RESTRICTED STAFF_OPERATIONAL directed to a CUSTOMER is impossible
        # at create time (B1 validation), but even constructed directly it must
        # NOT become visible to that customer if the role gate forbids the
        # tier. Here: RESTRICTED INTERNAL_NOTE directed to a customer (role
        # gate would hide INTERNAL_NOTE) -> customer still cannot read it.
        msg = self._mk(
            self.manager,
            "restricted internal aimed at customer (role gate still wins)",
            message_type=TicketMessageType.INTERNAL_NOTE,
            visibility_mode=TicketMessageVisibility.RESTRICTED,
            directed=[self.customer_user],
            is_hidden=True,
        )
        # The role gate (a) AND the party gate (b) are both AND-ed: a customer
        # can never see an INTERNAL_NOTE even if named in directed_to.
        self.assertNotIn(msg.id, self._list_ids(self.customer_user))
        # Author still sees it.
        self.assertIn(msg.id, self._list_ids(self.manager))


# ---------------------------------------------------------------------------
# B. No-inference via count / list length
# ---------------------------------------------------------------------------
class NoInferenceCountTests(_B2Fixture):
    def test_list_length_reflects_viewer_visible_set(self):
        normal = self._mk(self.manager, "normal one")
        restricted = self._mk(
            self.manager,
            "restricted to customer",
            visibility_mode=TicketMessageVisibility.RESTRICTED,
            directed=[self.customer_user],
        )
        # Party (author + directed) -> 2 messages.
        self.assertEqual(
            self._list_ids(self.manager), {normal.id, restricted.id}
        )
        self.assertEqual(
            self._list_ids(self.customer_user), {normal.id, restricted.id}
        )
        # Non-party admin -> exactly 1; the restricted one is not even
        # counted, so its existence cannot be inferred.
        self.assertEqual(self._list_ids(self.company_admin), {normal.id})
        # And the paginated `count` field itself (not just the id-set) must
        # reflect the viewer-visible set, so no count-delta can leak it.
        self.authenticate(self.company_admin)
        resp = self.client.get(self._messages_url())
        self.assertEqual(resp.data["count"], 1)
        self.authenticate(self.customer_user)
        resp = self.client.get(self._messages_url())
        self.assertEqual(resp.data["count"], 2)


class MessageImmutabilityTests(_B2Fixture):
    def test_message_endpoint_is_create_and_list_only(self):
        # directed_to / visibility_mode are immutable post-create: the
        # messages endpoint is ListCreate only (no detail route, no Update
        # mixin), so no PATCH/PUT can rewrite a message's visibility after
        # the fact and bypass the B1 directed_to validation.
        restricted = self._mk(
            self.manager,
            "locked",
            visibility_mode=TicketMessageVisibility.RESTRICTED,
            directed=[self.customer_user],
        )
        self.authenticate(self.manager)
        for method in (self.client.patch, self.client.put):
            resp = method(
                self._messages_url(),
                {"visibility_mode": "NORMAL"},
                format="json",
            )
            self.assertEqual(
                resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED
            )
        # No per-message detail route exists to target either.
        detail = self.client.patch(
            f"{self._messages_url()}{restricted.id}/",
            {"visibility_mode": "NORMAL"},
            format="json",
        )
        self.assertIn(
            detail.status_code,
            (status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED),
        )
        restricted.refresh_from_db()
        self.assertEqual(
            str(restricted.visibility_mode),
            str(TicketMessageVisibility.RESTRICTED),
        )


# ---------------------------------------------------------------------------
# C. B7 NORMAL/role visibility unchanged by the refactor
# ---------------------------------------------------------------------------
class B7NormalVisibilityUnchangedTests(_B2Fixture):
    def setUp(self):
        super().setUp()
        self.public = self._mk(self.customer_user, "hi", TicketMessageType.PUBLIC_REPLY)
        self.internal = self._mk(
            self.manager, "cost", TicketMessageType.INTERNAL_NOTE, is_hidden=True
        )
        self.operational = self._mk(
            self.manager, "ladder", TicketMessageType.STAFF_OPERATIONAL
        )
        self.completion = self._mk(
            self.staff_user, "done", TicketMessageType.STAFF_COMPLETION
        )

    def test_provider_management_sees_all_normal_tiers(self):
        for actor in (self.super_admin, self.company_admin, self.manager, self.manager2):
            self.assertEqual(
                self._list_ids(actor),
                {self.public.id, self.internal.id, self.operational.id, self.completion.id},
                f"actor={actor.email}",
            )

    def test_staff_sees_operational_and_completion_only(self):
        # M1 B5 — STAFF read narrowed to STAFF_OPERATIONAL + STAFF_COMPLETION;
        # PUBLIC_REPLY (and INTERNAL_NOTE) no longer visible to STAFF.
        self.assertEqual(
            self._list_ids(self.staff_user),
            {self.operational.id, self.completion.id},
        )

    def test_customer_sees_public_and_completion_only(self):
        self.assertEqual(
            self._list_ids(self.customer_user),
            {self.public.id, self.completion.id},
        )


# ---------------------------------------------------------------------------
# D. Audit timeline must not leak a RESTRICTED message to a non-party admin
# ---------------------------------------------------------------------------
class TimelineRestrictedRedactionTests(_B2Fixture):
    def _timeline_message_audit_ids(self, actor):
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

    def test_timeline_hides_restricted_message_from_non_party_admin(self):
        # Create via the API so the audit signal records a real CREATE row
        # (its `changes` diff carries the message body).
        self.authenticate(self.manager)
        body = "TOP-SECRET-RESTRICTED-BODY-marker"
        resp = self.client.post(
            self._messages_url(),
            {
                "message": body,
                "message_type": TicketMessageType.PUBLIC_REPLY,
                "visibility_mode": TicketMessageVisibility.RESTRICTED,
                "directed_to": [self.customer_user.id],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        msg_id = resp.data["id"]

        # Non-party provider-mgmt admin: no message audit row, no body.
        ids, raw = self._timeline_message_audit_ids(self.company_admin)
        self.assertNotIn(msg_id, ids)
        self.assertNotIn(body, raw)

        # Author (party, provider-mgmt) sees its audit row.
        ids2, _ = self._timeline_message_audit_ids(self.manager)
        self.assertIn(msg_id, ids2)

    def test_timeline_shows_normal_message_audit_to_admin(self):
        # Control: a NORMAL message's audit row is visible to any in-scope
        # provider-mgmt admin (refactor did not over-redact).
        self.authenticate(self.manager)
        resp = self.client.post(
            self._messages_url(),
            {"message": "normal note", "message_type": TicketMessageType.PUBLIC_REPLY},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        msg_id = resp.data["id"]
        ids, _ = self._timeline_message_audit_ids(self.company_admin)
        self.assertIn(msg_id, ids)
