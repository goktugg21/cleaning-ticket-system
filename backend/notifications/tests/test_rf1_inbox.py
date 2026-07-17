"""RF-1 Part B — aggregated message inbox + read cursors.

The security heart of the sprint: every count / snippet / roster is
computed PER VIEWER through the existing five-mode visibility matrix, so
these tests assert the matrix is honoured end-to-end on the inbox
surface — internal notes never leak into customer counts/snippets/
rosters; CUSTOMER_INTERNAL never leaks into providers'; cursor semantics
(own excluded, advance-on-read); receipts absent for customer viewers;
scoping; ordering; filters.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from customers.models import CustomerUserBuildingAccess, CustomerUserMembership
from extra_work.models import (
    ExtraWorkCategory,
    ExtraWorkMessage,
    ExtraWorkMessageType,
    ExtraWorkMessageVisibility,
    ExtraWorkRequest,
    ExtraWorkStatus,
)
from notifications.models import MessageReadCursor
from test_utils import TenantFixtureMixin
from tickets.models import (
    TicketMessage,
    TicketMessageType,
    TicketMessageVisibility,
    TicketStaffAssignment,
)

MT = TicketMessageType
VIS = TicketMessageVisibility
EMT = ExtraWorkMessageType
EVIS = ExtraWorkMessageVisibility
AccessRole = CustomerUserBuildingAccess.AccessRole

INBOX = "/api/inbox/"
UNREAD = "/api/inbox/unread-count/"
MARK = "/api/inbox/mark-read/"


class _InboxFixture(TenantFixtureMixin, APITestCase):
    """One ticket + one EW, both in Building A / Customer A, with a
    STAFF user assigned and a customer LOCATION_MANAGER who can read both.
    Message timestamps are set explicitly so ordering is deterministic.
    """

    def setUp(self):
        super().setUp()
        self.t0 = timezone.now() - timedelta(hours=5)

        self.staff_user = self.make_user("staff-inbox@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=self.staff_user, is_active=True)
        BuildingStaffVisibility.objects.create(
            user=self.staff_user, building=self.building
        )
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.staff_user
        )

        # A customer LOCATION_MANAGER — reads every thread at the building.
        self.cust_lm = self.make_user("cust-lm@example.com", UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            user=self.cust_lm, customer=self.customer
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=self.building,
            access_role=AccessRole.CUSTOMER_LOCATION_MANAGER,
        )

        self.ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_lm,
            title="EW Thread",
            description="d",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.REQUESTED,
        )

    # -- message builders (explicit created_at for deterministic order) --
    def _tmsg(self, author, message_type, minute, *, message="hi",
              visibility=VIS.NORMAL, directed=None, ticket=None):
        ticket = ticket or self.ticket
        msg = TicketMessage.objects.create(
            ticket=ticket, author=author, message_type=message_type,
            visibility_mode=visibility, message=message,
            is_hidden=(message_type == MT.INTERNAL_NOTE),
        )
        if directed:
            msg.directed_to.set(directed)
        ts = self.t0 + timedelta(minutes=minute)
        TicketMessage.objects.filter(pk=msg.pk).update(created_at=ts)
        msg.refresh_from_db()
        return msg

    def _ewmsg(self, author, message_type, minute, *, message="hi",
               visibility=EVIS.NORMAL, directed=None, ew=None):
        ew = ew or self.ew
        msg = ExtraWorkMessage.objects.create(
            extra_work=ew, author=author, message_type=message_type,
            visibility_mode=visibility, message=message,
        )
        if directed:
            msg.directed_to.set(directed)
        ts = self.t0 + timedelta(minutes=minute)
        ExtraWorkMessage.objects.filter(pk=msg.pk).update(created_at=ts)
        msg.refresh_from_db()
        return msg

    def _inbox(self, viewer, **params):
        self.authenticate(viewer)
        resp = self.client.get(INBOX, params)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        return resp.data

    def _row(self, data, kind, thread_id):
        for r in data["results"]:
            if r["kind"] == kind and r["id"] == thread_id:
                return r
        return None


class InboxVisibilityMatrixTests(_InboxFixture):
    def test_internal_note_never_reaches_customer(self):
        # Provider posts a PUBLIC_REPLY then an INTERNAL_NOTE (later).
        self._tmsg(self.company_admin, MT.PUBLIC_REPLY, 1, message="public hello")
        self._tmsg(self.company_admin, MT.INTERNAL_NOTE, 2, message="SECRET-INTERNAL")

        data = self._inbox(self.cust_lm, kind="ticket")
        row = self._row(data, "ticket", self.ticket.id)
        self.assertIsNotNone(row)
        # Latest visible message for the customer is the PUBLIC_REPLY,
        # NOT the internal note.
        self.assertEqual(row["last_message"]["message_type"], MT.PUBLIC_REPLY)
        self.assertNotIn("SECRET-INTERNAL", row["last_message"]["snippet"])
        # The internal note must not be counted.
        self.assertEqual(row["unread_count"], 1)

    def test_provider_management_never_sees_customer_internal(self):
        self._tmsg(self.company_admin, MT.PUBLIC_REPLY, 1, message="public")
        self._tmsg(self.cust_lm, MT.CUSTOMER_INTERNAL, 2, message="CUST-ONLY-NOTE")

        # CA (MGMT) — latest visible is the PUBLIC_REPLY, count excludes
        # the CUSTOMER_INTERNAL.
        data = self._inbox(self.company_admin, kind="ticket")
        row = self._row(data, "ticket", self.ticket.id)
        self.assertEqual(row["last_message"]["message_type"], MT.PUBLIC_REPLY)
        self.assertNotIn("CUST-ONLY-NOTE", row["last_message"]["snippet"])
        # CA authored the public reply, so their own is excluded -> 0 unread.
        self.assertEqual(row["unread_count"], 0)

    def test_super_admin_sees_customer_internal(self):
        self._tmsg(self.cust_lm, MT.CUSTOMER_INTERNAL, 2, message="CUST-ONLY-NOTE")
        data = self._inbox(self.super_admin, kind="ticket")
        row = self._row(data, "ticket", self.ticket.id)
        self.assertEqual(row["last_message"]["message_type"], MT.CUSTOMER_INTERNAL)
        self.assertIn("CUST-ONLY-NOTE", row["last_message"]["snippet"])

    def test_thread_with_only_invisible_messages_absent(self):
        # A ticket whose ONLY message is an INTERNAL_NOTE must not appear
        # in the customer's inbox at all.
        self._tmsg(self.company_admin, MT.INTERNAL_NOTE, 1)
        data = self._inbox(self.cust_lm, kind="ticket")
        self.assertIsNone(self._row(data, "ticket", self.ticket.id))

    def test_ew_internal_note_hidden_from_customer(self):
        self._ewmsg(self.company_admin, EMT.PUBLIC_REPLY, 1, message="ew public")
        self._ewmsg(self.company_admin, EMT.INTERNAL_NOTE, 2, message="EW-SECRET")
        data = self._inbox(self.cust_lm, kind="extra_work")
        row = self._row(data, "extra_work", self.ew.id)
        self.assertEqual(row["last_message"]["message_type"], EMT.PUBLIC_REPLY)
        self.assertEqual(row["unread_count"], 1)


class InboxCursorTests(_InboxFixture):
    def test_own_messages_excluded_from_unread(self):
        # The customer's own message must not count as unread for them.
        self._tmsg(self.cust_lm, MT.PUBLIC_REPLY, 1, message="my own")
        data = self._inbox(self.cust_lm, kind="ticket")
        row = self._row(data, "ticket", self.ticket.id)
        self.assertEqual(row["unread_count"], 0)

    def test_mark_read_zeroes_unread(self):
        self._tmsg(self.company_admin, MT.PUBLIC_REPLY, 1)
        self._tmsg(self.company_admin, MT.PUBLIC_REPLY, 2)
        data = self._inbox(self.cust_lm, kind="ticket")
        self.assertEqual(
            self._row(data, "ticket", self.ticket.id)["unread_count"], 2
        )
        self.authenticate(self.cust_lm)
        resp = self.client.post(
            MARK, {"kind": "ticket", "id": self.ticket.id}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = self._inbox(self.cust_lm, kind="ticket")
        self.assertEqual(
            self._row(data, "ticket", self.ticket.id)["unread_count"], 0
        )

    def test_new_message_after_read_is_unread_again(self):
        self._tmsg(self.company_admin, MT.PUBLIC_REPLY, 1)
        self.authenticate(self.cust_lm)
        self.client.post(
            MARK, {"kind": "ticket", "id": self.ticket.id}, format="json"
        )
        # A later message (cursor is now, this is created "after" now).
        later = TicketMessage.objects.create(
            ticket=self.ticket, author=self.company_admin,
            message_type=MT.PUBLIC_REPLY, message="new one",
        )
        TicketMessage.objects.filter(pk=later.pk).update(
            created_at=timezone.now() + timedelta(minutes=1)
        )
        data = self._inbox(self.cust_lm, kind="ticket")
        self.assertEqual(
            self._row(data, "ticket", self.ticket.id)["unread_count"], 1
        )

    def test_mark_read_scope_gate_404(self):
        # A user with no scope for the other tenant's ticket cannot mark it.
        self.authenticate(self.cust_lm)
        resp = self.client.post(
            MARK, {"kind": "ticket", "id": self.other_ticket.id}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(
            MessageReadCursor.objects.filter(
                user=self.cust_lm, ticket=self.other_ticket
            ).exists()
        )

    def test_mark_read_advances_never_regresses(self):
        self._tmsg(self.company_admin, MT.PUBLIC_REPLY, 1)
        self.authenticate(self.cust_lm)
        self.client.post(MARK, {"kind": "ticket", "id": self.ticket.id}, format="json")
        cursor = MessageReadCursor.objects.get(user=self.cust_lm, ticket=self.ticket)
        first = cursor.last_read_at
        # A second mark-read should only move forward.
        self.client.post(MARK, {"kind": "ticket", "id": self.ticket.id}, format="json")
        cursor.refresh_from_db()
        self.assertGreaterEqual(cursor.last_read_at, first)


class InboxReceiptsTests(_InboxFixture):
    def test_receipts_present_for_provider_absent_for_customer(self):
        self._tmsg(self.customer_user, MT.PUBLIC_REPLY, 1, message="from customer")
        # Provider management viewer -> unread_by present.
        data = self._inbox(self.company_admin, kind="ticket")
        row = self._row(data, "ticket", self.ticket.id)
        self.assertIn("unread_by", row)
        self.assertIsInstance(row["unread_by"], list)
        # Customer viewer -> no unread_by key at all.
        data = self._inbox(self.cust_lm, kind="ticket")
        row = self._row(data, "ticket", self.ticket.id)
        self.assertNotIn("unread_by", row)

    def test_roster_excludes_message_author(self):
        # CA posts a public reply; CA must not be in "who hasn't read".
        self._tmsg(self.company_admin, MT.PUBLIC_REPLY, 1)
        data = self._inbox(self.manager, kind="ticket")  # BM viewer (mgmt)
        row = self._row(data, "ticket", self.ticket.id)
        ids = {u["id"] for u in row["unread_by"]}
        self.assertNotIn(self.company_admin.id, ids)

    def test_roster_respects_message_visibility(self):
        # A CUSTOMER_INTERNAL latest message: only customer-side can see it.
        # Viewed by SA (who can see it + gets receipts), the roster must
        # contain NO provider-management users.
        self._ewmsg(self.cust_lm, EMT.CUSTOMER_INTERNAL, 1, message="cust internal")
        data = self._inbox(self.super_admin, kind="extra_work")
        row = self._row(data, "extra_work", self.ew.id)
        ids = {u["id"] for u in row.get("unread_by", [])}
        self.assertNotIn(self.company_admin.id, ids)
        self.assertNotIn(self.manager.id, ids)

    def test_read_user_not_in_roster(self):
        self._tmsg(self.customer_user, MT.PUBLIC_REPLY, 1)
        # cust_lm reads the thread.
        self.authenticate(self.cust_lm)
        self.client.post(MARK, {"kind": "ticket", "id": self.ticket.id}, format="json")
        # From the CA's receipts, cust_lm should now count as read (absent).
        data = self._inbox(self.company_admin, kind="ticket")
        row = self._row(data, "ticket", self.ticket.id)
        ids = {u["id"] for u in row["unread_by"]}
        self.assertNotIn(self.cust_lm.id, ids)


class InboxScopingTests(_InboxFixture):
    def test_bm_only_sees_own_building_threads(self):
        # Message on the other tenant's ticket; BM of building A must not
        # see that thread.
        TicketMessage.objects.create(
            ticket=self.other_ticket, author=self.other_company_admin,
            message_type=MT.PUBLIC_REPLY, message="other tenant",
        )
        self._tmsg(self.company_admin, MT.PUBLIC_REPLY, 1)
        data = self._inbox(self.manager)
        self.assertIsNotNone(self._row(data, "ticket", self.ticket.id))
        self.assertIsNone(self._row(data, "ticket", self.other_ticket.id))

    def test_staff_sees_no_extra_work(self):
        self._ewmsg(self.company_admin, EMT.PUBLIC_REPLY, 1)
        data = self._inbox(self.staff_user, kind="extra_work")
        self.assertEqual(data["results"], [])


class InboxOrderingAndFilterTests(_InboxFixture):
    def test_ordering_latest_message_first(self):
        # ticket latest at minute 3, EW latest at minute 5 -> EW first.
        self._tmsg(self.company_admin, MT.PUBLIC_REPLY, 3)
        self._ewmsg(self.company_admin, EMT.PUBLIC_REPLY, 5)
        data = self._inbox(self.company_admin)
        self.assertEqual(data["results"][0]["kind"], "extra_work")
        self.assertEqual(data["results"][1]["kind"], "ticket")

    def test_kind_filter(self):
        self._tmsg(self.company_admin, MT.PUBLIC_REPLY, 1)
        self._ewmsg(self.company_admin, EMT.PUBLIC_REPLY, 2)
        data = self._inbox(self.company_admin, kind="ticket")
        kinds = {r["kind"] for r in data["results"]}
        self.assertEqual(kinds, {"ticket"})

    def test_unread_only_filter(self):
        # Ticket has an unread message; EW is all the viewer's own -> read.
        self._tmsg(self.customer_user, MT.PUBLIC_REPLY, 1)
        self._ewmsg(self.company_admin, EMT.PUBLIC_REPLY, 2)  # CA's own
        data = self._inbox(self.company_admin, unread_only="1")
        kinds = {r["kind"] for r in data["results"]}
        self.assertIn("ticket", kinds)
        self.assertNotIn("extra_work", kinds)

    def test_q_search_by_title(self):
        self._tmsg(self.company_admin, MT.PUBLIC_REPLY, 1)
        self._ewmsg(self.company_admin, EMT.PUBLIC_REPLY, 2)
        data = self._inbox(self.company_admin, q="EW Thread")
        self.assertTrue(all(r["kind"] == "extra_work" for r in data["results"]))
        self.assertTrue(len(data["results"]) >= 1)

    def test_q_search_by_customer_name(self):
        self._tmsg(self.company_admin, MT.PUBLIC_REPLY, 1)
        data = self._inbox(self.company_admin, q="Customer A")
        self.assertTrue(len(data["results"]) >= 1)
        data = self._inbox(self.company_admin, q="no-such-customer-xyz")
        self.assertEqual(data["results"], [])

    def test_date_from_filter(self):
        self._tmsg(self.company_admin, MT.PUBLIC_REPLY, 1)  # at t0+1min
        # A date_from in the far future excludes everything.
        future = (timezone.now() + timedelta(days=2)).date().isoformat()
        data = self._inbox(self.company_admin, date_from=future)
        self.assertEqual(data["results"], [])


class MessageReadCursorConstraintTests(_InboxFixture):
    def test_both_targets_null_rejected(self):
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MessageReadCursor.objects.create(
                    user=self.cust_lm, last_read_at=timezone.now()
                )

    def test_both_targets_set_rejected(self):
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MessageReadCursor.objects.create(
                    user=self.cust_lm, ticket=self.ticket, extra_work=self.ew,
                    last_read_at=timezone.now(),
                )

    def test_unique_per_user_thread(self):
        from django.db import IntegrityError, transaction

        MessageReadCursor.objects.create(
            user=self.cust_lm, ticket=self.ticket, last_read_at=timezone.now()
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MessageReadCursor.objects.create(
                    user=self.cust_lm, ticket=self.ticket,
                    last_read_at=timezone.now(),
                )


class InboxUnreadCountEndpointTests(_InboxFixture):
    def test_unread_count_matches_inbox(self):
        self._tmsg(self.customer_user, MT.PUBLIC_REPLY, 1)
        self._tmsg(self.customer_user, MT.PUBLIC_REPLY, 2)
        self.authenticate(self.company_admin)
        resp = self.client.get(UNREAD)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["unread_count"], 2)

    def test_customer_internal_not_in_provider_unread_count(self):
        self._tmsg(self.cust_lm, MT.CUSTOMER_INTERNAL, 1)
        self.authenticate(self.company_admin)
        resp = self.client.get(UNREAD)
        self.assertEqual(resp.data["unread_count"], 0)
