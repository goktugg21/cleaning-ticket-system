"""
M1 — Notification / message center, phase B1 (BACKEND).

Covers:
  * The in-app `Notification` model + recipient-scoped REST feed
    (list / unread-count / mark-read / mark-all-read), including the
    cross-user isolation guard and pagination.
  * The ticket-message emit: per `message_type` audience, branched by
    `visibility_mode`, minus the author, deduped, active only.
  * `directed_to` (NORMAL flagging + RESTRICTED targeting) and its
    validation (`restricted_requires_target`, `directed_to_not_visible`).
  * The HARD invariant: an INTERNAL_NOTE never notifies a customer-side
    user (and never STAFF); STAFF_OPERATIONAL never notifies a customer.
  * Back-compat: a plain pre-B1-shaped POST still works and fans out as
    NORMAL; existing rows default to NORMAL / empty directed_to.

B1 is in-app only — no email assertions here (the lifecycle emails are
unchanged). B1 does NOT enforce RESTRICTED read-side hiding (that is B2);
these tests therefore assert notification *recipients*, not read hiding.
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from customers.models import CustomerUserMembership
from notifications.models import Notification, NotificationType
from test_utils import TenantFixtureMixin
from tickets.models import (
    TicketMessage,
    TicketMessageType,
    TicketMessageVisibility,
    TicketStaffAssignment,
)


class _MsgNotifFixture(TenantFixtureMixin, APITestCase):
    """Tenant fixture + one assigned STAFF and one building-scoped but
    UNASSIGNED staff on `self.ticket` (Building A / Customer A).

    Audience of `self.ticket`:
      * provider-mgmt (`_ticket_staff_users`): company_admin + manager
        (NOT super_admin, NOT other-company actors).
      * assigned-staff: staff_user only (staff_unassigned is in the
        building but holds no slot).
      * customer-side: customer_user (member + created_by).
    """

    def setUp(self):
        super().setUp()
        self.staff_user = self.make_user("staff-m1@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=self.staff_user, is_active=True)
        BuildingStaffVisibility.objects.create(
            user=self.staff_user, building=self.building
        )
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.staff_user
        )

        self.staff_unassigned = self.make_user(
            "staff2-m1@example.com", UserRole.STAFF
        )
        StaffProfile.objects.create(user=self.staff_unassigned, is_active=True)
        BuildingStaffVisibility.objects.create(
            user=self.staff_unassigned, building=self.building
        )

        # A member of Customer A with NO building-access row -> a member of
        # the customer org who CANNOT read this ticket (scope_tickets_for
        # excludes it; the messages endpoint would 404 them). They must NOT
        # be notified even though `_ticket_customer_users` resolves them by
        # bare membership.
        self.customer_no_access = self.make_user(
            "customer-noaccess-m1@example.com", UserRole.CUSTOMER_USER
        )
        CustomerUserMembership.objects.create(
            user=self.customer_no_access, customer=self.customer
        )

    # -- helpers ---------------------------------------------------------
    def _messages_url(self, ticket=None):
        ticket = ticket or self.ticket
        return f"/api/tickets/{ticket.id}/messages/"

    def _post_message(self, author, **payload):
        self.authenticate(author)
        body = {"message": payload.pop("message", "Hello there")}
        body.update(payload)
        return self.client.post(self._messages_url(), body, format="json")

    def _recipient_ids(self):
        return set(
            Notification.objects.filter(
                event_type=NotificationType.TICKET_MESSAGE
            ).values_list("recipient_id", flat=True)
        )

    def _directed_ids(self):
        return set(
            Notification.objects.filter(is_directed=True).values_list(
                "recipient_id", flat=True
            )
        )

    def _mk_notif(self, recipient, **kw):
        # IA 2026-06-25 — undirected TICKET_MESSAGE rows are hidden from
        # the feed by default (see views._feed_queryset). These fixture
        # rows default to is_directed=True so the feed-MECHANICS tests
        # (recipient scoping, pagination, read-all) keep exercising
        # feed-visible rows; the default-hidden semantics themselves are
        # covered by test_ia_feed_defaults.
        return Notification.objects.create(
            recipient=recipient,
            actor=kw.get("actor", self.manager),
            event_type=NotificationType.TICKET_MESSAGE,
            ticket=kw.get("ticket", self.ticket),
            is_directed=kw.get("is_directed", True),
            summary=kw.get("summary", "x"),
            read_at=kw.get("read_at", None),
        )


# ---------------------------------------------------------------------------
# A. Emit per message_type
# ---------------------------------------------------------------------------
class EmitPerMessageTypeTests(_MsgNotifFixture):
    def test_public_reply_full_audience_minus_author(self):
        resp = self._post_message(
            self.manager, message_type=TicketMessageType.PUBLIC_REPLY
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        # M1 B5 — PUBLIC_REPLY no longer reaches STAFF (a field worker has no
        # customer-conversation channel). Audience = provider-mgmt + customer.
        self.assertEqual(
            self._recipient_ids(),
            {self.company_admin.id, self.customer_user.id},
        )
        # M1 B5 — assigned STAFF is NOT notified about a PUBLIC_REPLY.
        self.assertNotIn(self.staff_user.id, self._recipient_ids())
        # Author is never a recipient.
        self.assertNotIn(self.manager.id, self._recipient_ids())
        # Building-scoped but UNASSIGNED staff is not in the fan-out.
        self.assertNotIn(self.staff_unassigned.id, self._recipient_ids())
        # SUPER_ADMIN is deliberately not auto-notified.
        self.assertNotIn(self.super_admin.id, self._recipient_ids())
        # A customer-org member without building access cannot read the
        # ticket, so must not be notified (scope gate).
        self.assertNotIn(self.customer_no_access.id, self._recipient_ids())

    def test_customer_member_without_building_access_not_notified(self):
        # Explicit coverage for the scope gate: customer_no_access is a
        # member of Customer A but holds no CustomerUserBuildingAccess for
        # the ticket's building, so cannot open the ticket and must not be
        # notified for either customer-visible tier.
        self._post_message(
            self.manager, message_type=TicketMessageType.PUBLIC_REPLY
        )
        self.assertNotIn(self.customer_no_access.id, self._recipient_ids())
        self.assertIn(self.customer_user.id, self._recipient_ids())

        Notification.objects.all().delete()
        self._post_message(
            self.staff_user, message_type=TicketMessageType.STAFF_COMPLETION
        )
        self.assertNotIn(self.customer_no_access.id, self._recipient_ids())
        self.assertIn(self.customer_user.id, self._recipient_ids())

    def test_internal_note_provider_mgmt_only(self):
        resp = self._post_message(
            self.manager, message_type=TicketMessageType.INTERNAL_NOTE
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        recipients = self._recipient_ids()
        self.assertEqual(recipients, {self.company_admin.id})
        # HARD invariant: zero customer notifications, zero staff.
        self.assertNotIn(self.customer_user.id, recipients)
        self.assertNotIn(self.staff_user.id, recipients)
        self.assertFalse(
            Notification.objects.filter(
                recipient__role=UserRole.CUSTOMER_USER
            ).exists()
        )

    def test_staff_operational_excludes_customer(self):
        resp = self._post_message(
            self.manager, message_type=TicketMessageType.STAFF_OPERATIONAL
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        recipients = self._recipient_ids()
        self.assertEqual(recipients, {self.company_admin.id, self.staff_user.id})
        self.assertNotIn(self.customer_user.id, recipients)

    def test_staff_completion_is_customer_visible(self):
        # Authored by the assigned STAFF — they are excluded as author.
        resp = self._post_message(
            self.staff_user, message_type=TicketMessageType.STAFF_COMPLETION
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        self.assertEqual(
            self._recipient_ids(),
            {self.company_admin.id, self.manager.id, self.customer_user.id},
        )
        self.assertNotIn(self.staff_user.id, self._recipient_ids())

    def test_no_self_notification_when_provider_admin_authors(self):
        resp = self._post_message(
            self.company_admin, message_type=TicketMessageType.PUBLIC_REPLY
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        self.assertNotIn(self.company_admin.id, self._recipient_ids())
        # M1 B5 — PUBLIC_REPLY audience = provider-mgmt + customer (no STAFF).
        self.assertEqual(
            self._recipient_ids(),
            {self.manager.id, self.customer_user.id},
        )


# ---------------------------------------------------------------------------
# B. directed_to (NORMAL) + visibility_mode (RESTRICTED)
# ---------------------------------------------------------------------------
class DirectedAndRestrictedTests(_MsgNotifFixture):
    def test_normal_directed_flags_only_the_target(self):
        resp = self._post_message(
            self.manager,
            message_type=TicketMessageType.PUBLIC_REPLY,
            directed_to=[self.customer_user.id],
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        # Whole NORMAL PUBLIC_REPLY audience notified — M1 B5: provider-mgmt
        # + customer, STAFF dropped.
        self.assertEqual(
            self._recipient_ids(),
            {self.company_admin.id, self.customer_user.id},
        )
        # Only the directed user carries is_directed=True.
        self.assertEqual(self._directed_ids(), {self.customer_user.id})
        non_directed = Notification.objects.filter(is_directed=False)
        self.assertEqual(
            {n.recipient_id for n in non_directed},
            {self.company_admin.id},
        )

    def test_normal_directed_user_outside_fanout_still_notified(self):
        # staff_unassigned can SEE a STAFF_OPERATIONAL note (building scope)
        # but is not in the assigned-staff fan-out. Directing at them must
        # still produce a flagged notification.
        resp = self._post_message(
            self.manager,
            message_type=TicketMessageType.STAFF_OPERATIONAL,
            directed_to=[self.staff_unassigned.id],
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        recipients = self._recipient_ids()
        self.assertEqual(
            recipients,
            {self.company_admin.id, self.staff_user.id, self.staff_unassigned.id},
        )
        self.assertEqual(self._directed_ids(), {self.staff_unassigned.id})

    def test_restricted_only_directed_users_notified(self):
        resp = self._post_message(
            self.manager,
            message_type=TicketMessageType.PUBLIC_REPLY,
            visibility_mode=TicketMessageVisibility.RESTRICTED,
            directed_to=[self.customer_user.id],
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        # No audience-wide fan-out — only the directed user.
        self.assertEqual(self._recipient_ids(), {self.customer_user.id})
        self.assertEqual(self._directed_ids(), {self.customer_user.id})

    def test_restricted_empty_directed_to_rejected(self):
        resp = self._post_message(
            self.manager,
            message_type=TicketMessageType.PUBLIC_REPLY,
            visibility_mode=TicketMessageVisibility.RESTRICTED,
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            getattr(resp.data["directed_to"][0], "code", None),
            "restricted_requires_target",
        )
        self.assertEqual(Notification.objects.count(), 0)
        self.assertFalse(TicketMessage.objects.exists())

    def test_directing_internal_note_to_customer_rejected(self):
        resp = self._post_message(
            self.manager,
            message_type=TicketMessageType.INTERNAL_NOTE,
            directed_to=[self.customer_user.id],
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            getattr(resp.data["directed_to"][0], "code", None),
            "directed_to_not_visible",
        )
        self.assertEqual(Notification.objects.count(), 0)
        self.assertFalse(TicketMessage.objects.exists())

    def test_directing_internal_note_to_staff_rejected(self):
        resp = self._post_message(
            self.manager,
            message_type=TicketMessageType.INTERNAL_NOTE,
            directed_to=[self.staff_user.id],
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            getattr(resp.data["directed_to"][0], "code", None),
            "directed_to_not_visible",
        )
        # The rejection must write neither the message nor any notification,
        # so a regression moving validation after save (leaking the note)
        # is caught.
        self.assertEqual(Notification.objects.count(), 0)
        self.assertFalse(TicketMessage.objects.exists())

    def test_directing_to_out_of_scope_user_rejected(self):
        # other_customer_user has no scope on this ticket.
        resp = self._post_message(
            self.manager,
            message_type=TicketMessageType.PUBLIC_REPLY,
            directed_to=[self.other_customer_user.id],
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            getattr(resp.data["directed_to"][0], "code", None),
            "directed_to_not_visible",
        )
        self.assertEqual(Notification.objects.count(), 0)
        self.assertFalse(TicketMessage.objects.exists())

    def test_directed_to_over_cap_rejected(self):
        # Oversized attention lists are rejected up front (query-amplification
        # guard). 51 ids > MAX_DIRECTED_TO (50).
        resp = self._post_message(
            self.manager,
            message_type=TicketMessageType.PUBLIC_REPLY,
            directed_to=list(range(1, 52)),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            getattr(resp.data["directed_to"][0], "code", None),
            "too_many_directed_recipients",
        )
        self.assertEqual(Notification.objects.count(), 0)
        self.assertFalse(TicketMessage.objects.exists())


# ---------------------------------------------------------------------------
# C. Back-compat
# ---------------------------------------------------------------------------
class BackCompatTests(_MsgNotifFixture):
    def test_plain_post_defaults_normal_and_fans_out(self):
        resp = self._post_message(self.manager, message="No new fields here")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        msg = TicketMessage.objects.get(pk=resp.data["id"])
        self.assertEqual(
            str(msg.visibility_mode), str(TicketMessageVisibility.NORMAL)
        )
        self.assertEqual(msg.directed_to.count(), 0)
        # M1 B5 — a plain post defaults to PUBLIC_REPLY/NORMAL; audience is
        # provider-mgmt + customer (STAFF dropped from PUBLIC_REPLY).
        self.assertEqual(
            self._recipient_ids(),
            {self.company_admin.id, self.customer_user.id},
        )

    def test_existing_message_reads_with_default_fields(self):
        # A pre-B1-shaped row (created directly, no new fields supplied).
        row = TicketMessage.objects.create(
            ticket=self.ticket,
            author=self.manager,
            message="legacy",
            message_type=TicketMessageType.PUBLIC_REPLY,
        )
        self.assertEqual(
            str(row.visibility_mode), str(TicketMessageVisibility.NORMAL)
        )
        self.authenticate(self.manager)
        resp = self.client.get(self._messages_url())
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data.get("results", resp.data)
        found = next(item for item in data if item["id"] == row.id)
        self.assertEqual(found["visibility_mode"], "NORMAL")
        self.assertEqual(found["directed_to"], [])


# ---------------------------------------------------------------------------
# D. Feed endpoints (recipient-scoped)
# ---------------------------------------------------------------------------
class NotificationFeedTests(_MsgNotifFixture):
    LIST_URL = "/api/notifications/"
    UNREAD_URL = "/api/notifications/unread-count/"
    READ_ALL_URL = "/api/notifications/read-all/"

    def _read_url(self, notif_id):
        return f"/api/notifications/{notif_id}/read/"

    def test_list_returns_only_callers_notifications(self):
        self._mk_notif(self.customer_user, summary="mine 1")
        self._mk_notif(self.customer_user, summary="mine 2")
        self._mk_notif(self.manager, summary="not mine")

        self.authenticate(self.customer_user)
        resp = self.client.get(self.LIST_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 2)
        for item in resp.data["results"]:
            self.assertIn(item["summary"], {"mine 1", "mine 2"})
        self.assertEqual(resp.data["unread_count"], 2)

    def test_unread_count_endpoint_excludes_read(self):
        self._mk_notif(self.customer_user)
        self._mk_notif(self.customer_user)
        self._mk_notif(self.customer_user, read_at=timezone.now())

        self.authenticate(self.customer_user)
        resp = self.client.get(self.UNREAD_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["unread_count"], 2)

    def test_mark_read_marks_own_and_404s_on_others(self):
        mine = self._mk_notif(self.customer_user)
        theirs = self._mk_notif(self.manager)

        self.authenticate(self.customer_user)
        resp = self.client.post(self._read_url(mine.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["is_read"])
        mine.refresh_from_db()
        self.assertIsNotNone(mine.read_at)

        # Cannot touch someone else's notification.
        resp = self.client.post(self._read_url(theirs.id))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        theirs.refresh_from_db()
        self.assertIsNone(theirs.read_at)

    def test_mark_read_is_idempotent(self):
        already = self._mk_notif(self.customer_user, read_at=timezone.now())
        first_ts = already.read_at
        self.authenticate(self.customer_user)
        resp = self.client.post(self._read_url(already.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        already.refresh_from_db()
        # Already-read timestamp is preserved (not overwritten).
        self.assertEqual(already.read_at, first_ts)

    def test_read_all_marks_only_callers_unread(self):
        self._mk_notif(self.customer_user)
        self._mk_notif(self.customer_user)
        theirs = self._mk_notif(self.manager)

        self.authenticate(self.customer_user)
        resp = self.client.post(self.READ_ALL_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["updated"], 2)

        self.assertEqual(
            Notification.objects.filter(
                recipient=self.customer_user, read_at__isnull=True
            ).count(),
            0,
        )
        theirs.refresh_from_db()
        self.assertIsNone(theirs.read_at)

    def test_list_pagination(self):
        for i in range(30):
            self._mk_notif(self.customer_user, summary=f"n{i}")

        self.authenticate(self.customer_user)
        resp = self.client.get(self.LIST_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 30)
        self.assertEqual(len(resp.data["results"]), 25)
        self.assertIsNotNone(resp.data["next"])
        self.assertEqual(resp.data["unread_count"], 30)

        resp2 = self.client.get(self.LIST_URL + "?page=2")
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp2.data["results"]), 5)

    def test_feed_requires_authentication(self):
        resp = self.client.get(self.LIST_URL)
        self.assertIn(
            resp.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )


# ---------------------------------------------------------------------------
# M1 B2 — RESTRICTED feed/deep-link no-inference + Customer Company Admin
# ---------------------------------------------------------------------------
class RestrictedFeedAndCCATests(_MsgNotifFixture):
    def _make_cca(self):
        """A Customer Company Admin: role CUSTOMER_USER + a company-wide
        membership flag, with NO per-building access row (company-wide
        scope). Created per-test so the shared fixture's audience
        assertions are not disturbed."""
        cca = self.make_user("cca-b2@example.com", UserRole.CUSTOMER_USER)
        CustomerUserMembership.objects.create(
            user=cca, customer=self.customer, is_company_admin=True
        )
        return cca

    def test_restricted_message_gives_non_party_admin_no_row_and_no_read(self):
        resp = self._post_message(
            self.manager,
            message_type=TicketMessageType.PUBLIC_REPLY,
            visibility_mode=TicketMessageVisibility.RESTRICTED,
            directed_to=[self.customer_user.id],
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        msg_id = resp.data["id"]

        # company_admin is provider-mgmt + in scope, but not author/directed:
        # no notification row exists (so no deep-link)...
        self.assertEqual(
            Notification.objects.filter(recipient=self.company_admin).count(), 0
        )
        # ...and navigating to the thread does not reveal the message.
        self.authenticate(self.company_admin)
        thread = self.client.get(self._messages_url())
        self.assertEqual(thread.status_code, status.HTTP_200_OK)
        ids = {m["id"] for m in thread.data.get("results", thread.data)}
        self.assertNotIn(msg_id, ids)

    def test_cca_is_notified_and_can_read_normal_customer_visible_message(self):
        cca = self._make_cca()
        resp = self._post_message(
            self.manager, message_type=TicketMessageType.PUBLIC_REPLY
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        msg_id = resp.data["id"]

        # The "even admins" rule does NOT over-redact: a NORMAL customer-
        # visible message reaches a customer company admin in their org.
        self.assertIn(cca.id, self._recipient_ids())
        self.authenticate(cca)
        thread = self.client.get(self._messages_url())
        self.assertEqual(thread.status_code, status.HTTP_200_OK)
        ids = {m["id"] for m in thread.data.get("results", thread.data)}
        self.assertIn(msg_id, ids)

    def test_cca_non_party_cannot_see_or_be_notified_for_restricted(self):
        cca = self._make_cca()
        resp = self._post_message(
            self.manager,
            message_type=TicketMessageType.PUBLIC_REPLY,
            visibility_mode=TicketMessageVisibility.RESTRICTED,
            directed_to=[self.customer_user.id],
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        msg_id = resp.data["id"]

        # The "even admins" rule applies to customer company admins too.
        self.assertNotIn(cca.id, self._recipient_ids())
        self.authenticate(cca)
        thread = self.client.get(self._messages_url())
        self.assertEqual(thread.status_code, status.HTTP_200_OK)
        ids = {m["id"] for m in thread.data.get("results", thread.data)}
        self.assertNotIn(msg_id, ids)
