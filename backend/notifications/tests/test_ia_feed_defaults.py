"""IA 2026-06-25 — message events leave the notification feed by default.

TICKET_MESSAGE / EXTRA_WORK_MESSAGE rows are hidden from the feed, the
unread count, and read-all UNLESS the row is directed at the viewer
(is_directed=True) or the viewer holds an explicit opt-in preference row
(muted=False). Suppression is read-time: rows keep being emitted, so an
opt-in also restores history. Workflow events are unaffected.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.test import APITestCase

from notifications.models import (
    Notification,
    NotificationPreference,
    NotificationType,
)
from test_utils import TenantFixtureMixin

FEED = "/api/notifications/"
UNREAD = "/api/notifications/unread-count/"
READ_ALL = "/api/notifications/read-all/"
PREFS = "/api/auth/notification-preferences/"


class _FeedFixture(TenantFixtureMixin, APITestCase):
    def _notify(self, event_type, *, directed=False, extra_work=None):
        return Notification.objects.create(
            recipient=self.company_admin,
            actor=self.customer_user,
            event_type=event_type,
            ticket=None if extra_work else self.ticket,
            extra_work=extra_work,
            is_directed=directed,
            summary="x",
            read_at=None,
        )

    def _feed_ids(self):
        resp = self.client.get(FEED)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        return {row["id"] for row in resp.data["results"]}, resp.data[
            "unread_count"
        ]


class MessageFeedDefaultOffTests(_FeedFixture):
    def test_fresh_user_sees_no_message_notifications(self):
        msg = self._notify(NotificationType.TICKET_MESSAGE)
        self.authenticate(self.company_admin)
        ids, unread = self._feed_ids()
        self.assertNotIn(msg.id, ids)
        self.assertEqual(unread, 0)
        resp = self.client.get(UNREAD)
        self.assertEqual(resp.data["unread_count"], 0)

    def test_ew_message_also_hidden_by_default(self):
        from extra_work.models import ExtraWorkCategory, ExtraWorkRequest

        ew = ExtraWorkRequest.objects.create(
            company=self.company, building=self.building,
            customer=self.customer, created_by=self.customer_user,
            title="EW", description="d",
            category=ExtraWorkCategory.DEEP_CLEANING,
        )
        msg = self._notify(NotificationType.EXTRA_WORK_MESSAGE, extra_work=ew)
        self.authenticate(self.company_admin)
        ids, unread = self._feed_ids()
        self.assertNotIn(msg.id, ids)
        self.assertEqual(unread, 0)

    def test_directed_message_always_visible(self):
        directed = self._notify(NotificationType.TICKET_MESSAGE, directed=True)
        self.authenticate(self.company_admin)
        ids, unread = self._feed_ids()
        self.assertIn(directed.id, ids)
        self.assertEqual(unread, 1)

    def test_workflow_events_unaffected(self):
        wf = self._notify(NotificationType.EXTRA_WORK_REQUESTED)
        self.authenticate(self.company_admin)
        ids, unread = self._feed_ids()
        self.assertIn(wf.id, ids)
        self.assertEqual(unread, 1)

    def test_opt_in_restores_messages_including_history(self):
        msg = self._notify(NotificationType.TICKET_MESSAGE)  # pre-opt-in row
        NotificationPreference.objects.create(
            user=self.company_admin,
            event_type=NotificationType.TICKET_MESSAGE,
            muted=False,
        )
        self.authenticate(self.company_admin)
        ids, unread = self._feed_ids()
        self.assertIn(msg.id, ids)
        self.assertEqual(unread, 1)

    def test_opt_in_is_per_type(self):
        from extra_work.models import ExtraWorkCategory, ExtraWorkRequest

        ew = ExtraWorkRequest.objects.create(
            company=self.company, building=self.building,
            customer=self.customer, created_by=self.customer_user,
            title="EW", description="d",
            category=ExtraWorkCategory.DEEP_CLEANING,
        )
        t_msg = self._notify(NotificationType.TICKET_MESSAGE)
        e_msg = self._notify(NotificationType.EXTRA_WORK_MESSAGE, extra_work=ew)
        NotificationPreference.objects.create(
            user=self.company_admin,
            event_type=NotificationType.TICKET_MESSAGE,
            muted=False,
        )
        self.authenticate(self.company_admin)
        ids, _ = self._feed_ids()
        self.assertIn(t_msg.id, ids)
        self.assertNotIn(e_msg.id, ids)

    def test_read_all_does_not_consume_hidden_messages(self):
        msg = self._notify(NotificationType.TICKET_MESSAGE)
        self._notify(NotificationType.EXTRA_WORK_REQUESTED)
        self.authenticate(self.company_admin)
        resp = self.client.post(READ_ALL)
        self.assertEqual(resp.data["updated"], 1)  # only the workflow row
        msg.refresh_from_db()
        self.assertIsNone(msg.read_at)  # hidden row untouched — opt-in later
        # still surfaces it as unread history.


class PreferencesEndpointInAppTests(_FeedFixture):
    def test_get_lists_inapp_types_with_muted_default(self):
        self.authenticate(self.company_admin)
        resp = self.client.get(PREFS)
        by_type = {e["event_type"]: e for e in resp.data["preferences"]}
        self.assertIn("TICKET_MESSAGE", by_type)
        self.assertIn("EXTRA_WORK_MESSAGE", by_type)
        self.assertTrue(by_type["TICKET_MESSAGE"]["muted"])
        self.assertTrue(by_type["EXTRA_WORK_MESSAGE"]["muted"])
        # Email types keep their unmuted default.
        self.assertFalse(by_type["TICKET_CREATED"]["muted"])

    def test_patch_opt_in_roundtrip(self):
        self.authenticate(self.company_admin)
        resp = self.client.patch(
            PREFS,
            {"preferences": [
                {"event_type": "TICKET_MESSAGE", "muted": False}
            ]},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        by_type = {e["event_type"]: e for e in resp.data["preferences"]}
        self.assertFalse(by_type["TICKET_MESSAGE"]["muted"])
        # And the feed now shows message rows.
        msg = self._notify(NotificationType.TICKET_MESSAGE)
        ids, _ = self._feed_ids()
        self.assertIn(msg.id, ids)

    def test_transactional_types_still_rejected(self):
        self.authenticate(self.company_admin)
        resp = self.client.patch(
            PREFS,
            {"preferences": [
                {"event_type": "PASSWORD_RESET", "muted": True}
            ]},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
