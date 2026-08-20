"""Sprint W4-Q §1 — the time-driven warnings inside the notification feed.

`sla/tests/test_w4q_inapp_warnings.py` covers the EMITTER (who gets a
row, and the shared cooldown). This module covers the FEED: that the
rows the sweep writes actually survive the read-side chokepoint, show up
in the bell count, mark read like anything else, and stay
recipient-scoped.

The chokepoint is the part worth guarding. `views._feed_queryset` hides
message-type events by default (they duplicate the Berichten inbox), and
that rule is expressed as an exclusion list. A warning silently landing
in that list would be a notification system that writes rows nobody ever
sees — the exact failure W1-B set out to end, reintroduced one layer
further down.
"""
from __future__ import annotations

import datetime

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from notifications.models import (
    Notification,
    NotificationEventType,
    NotificationPreference,
    NotificationType,
    SLA_WARNING_INAPP_TYPES,
)
from test_utils import TenantFixtureMixin

LIST_URL = "/api/notifications/"
COUNT_URL = "/api/notifications/unread-count/"
READ_ALL_URL = "/api/notifications/read-all/"


class SlaWarningEnumInvariantTests(APITestCase):
    """The three values are spelled identically in BOTH enums on purpose
    (one event, two channels, one name). That is only safe while none of
    them is user-mutable, because `NotificationPreference.event_type`
    stores values from both enums in ONE column and a shared value would
    make a preference row ambiguous.

    If somebody later makes one of them mutable, this fails loudly here
    rather than silently muting the wrong channel in production."""

    def test_the_three_values_are_shared_by_both_enums(self):
        for value in SLA_WARNING_INAPP_TYPES:
            self.assertIn(str(value), NotificationEventType.values)
            self.assertIn(str(value), NotificationType.values)

    def test_none_of_them_is_user_mutable_on_either_channel(self):
        mutable = {
            str(v) for v in NotificationPreference.USER_MUTABLE_EVENT_TYPES
        } | {
            str(v)
            for v in NotificationPreference.USER_MUTABLE_INAPP_EVENT_TYPES
        }
        for value in SLA_WARNING_INAPP_TYPES:
            self.assertNotIn(
                str(value),
                mutable,
                "A shared enum value became user-mutable: one preference "
                "row would now be ambiguous between the e-mail and the "
                "in-app channel. Either give the in-app value its own "
                "spelling or keep this event unmutable.",
            )

    def test_the_set_has_exactly_the_three_warnings(self):
        self.assertEqual(
            {str(v) for v in SLA_WARNING_INAPP_TYPES},
            {
                "SLA_APPROVAL_CUTOFF_DUE",
                "SLA_MANAGER_REVIEW_OVERDUE",
                "SLA_WORK_NOT_STARTED",
            },
        )


class SlaWarningFeedTests(TenantFixtureMixin, APITestCase):
    def warn(self, recipient=None, event=None, summary="Ticket A - 9 werkuren"):
        return Notification.objects.create(
            recipient=recipient or self.manager,
            actor=None,
            event_type=event or NotificationType.SLA_WORK_NOT_STARTED,
            ticket=self.ticket,
            is_directed=False,
            summary=summary,
        )

    def test_a_warning_is_visible_in_the_feed_by_default(self):
        """No preference row exists, and none should be needed."""
        self.warn()
        self.authenticate(self.manager)
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        types = {row["event_type"] for row in response.data["results"]}
        self.assertIn("SLA_WORK_NOT_STARTED", types)

    def test_a_warning_counts_towards_the_bell_badge(self):
        self.warn()
        self.authenticate(self.manager)
        self.assertEqual(
            self.client.get(COUNT_URL).data["unread_count"], 1
        )

    def test_a_warning_is_not_hidden_by_the_message_mute_default(self):
        """Message events are hidden unless opted in; a warning is not a
        message and must not inherit that rule."""
        self.warn()
        self.warn(
            event=NotificationType.TICKET_MESSAGE, summary="a chat message"
        )
        self.authenticate(self.manager)
        types = {
            row["event_type"] for row in self.client.get(LIST_URL).data["results"]
        }
        self.assertIn("SLA_WORK_NOT_STARTED", types)
        self.assertNotIn("TICKET_MESSAGE", types)

    def test_all_three_warning_types_reach_the_feed(self):
        for event in SLA_WARNING_INAPP_TYPES:
            self.warn(event=event)
        self.authenticate(self.manager)
        types = {
            row["event_type"] for row in self.client.get(LIST_URL).data["results"]
        }
        self.assertEqual(
            types, {str(v) for v in SLA_WARNING_INAPP_TYPES}
        )

    def test_a_warning_marks_read_like_any_other_row(self):
        row = self.warn()
        self.authenticate(self.manager)
        response = self.client.post(f"/api/notifications/{row.id}/read/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row.refresh_from_db()
        self.assertIsNotNone(row.read_at)
        self.assertEqual(
            self.client.get(COUNT_URL).data["unread_count"], 0
        )

    def test_mark_all_read_clears_a_warning(self):
        self.warn()
        self.warn(event=NotificationType.SLA_MANAGER_REVIEW_OVERDUE)
        self.authenticate(self.manager)
        response = self.client.post(READ_ALL_URL)
        self.assertEqual(response.data["updated"], 2)
        self.assertEqual(
            self.client.get(COUNT_URL).data["unread_count"], 0
        )

    def test_the_feed_stays_recipient_scoped(self):
        """The one hard rule the feed has ever had. A warning is a new
        kind of row, not a new kind of visibility."""
        self.warn(recipient=self.manager)
        self.authenticate(self.other_manager)
        response = self.client.get(LIST_URL)
        self.assertEqual(response.data["results"], [])
        self.assertEqual(response.data["unread_count"], 0)

    def test_another_users_warning_cannot_be_marked_read(self):
        row = self.warn(recipient=self.manager)
        self.authenticate(self.other_manager)
        response = self.client.post(f"/api/notifications/{row.id}/read/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        row.refresh_from_db()
        self.assertIsNone(row.read_at)

    def test_the_row_carries_the_ticket_reference_the_ui_deep_links_with(self):
        self.warn()
        self.authenticate(self.manager)
        row = self.client.get(LIST_URL).data["results"][0]
        self.assertEqual(row["ticket"], self.ticket.id)
        self.assertEqual(row["ticket_no"], self.ticket.ticket_no)
        self.assertIsNone(row["actor_id"])
        self.assertFalse(row["is_directed"])

    def test_an_extra_work_warning_carries_its_extra_work_reference(self):
        from decimal import Decimal

        from extra_work.models import ExtraWorkRequest, ExtraWorkStatus

        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.company_admin,
            title="Trapportaal reinigen",
            description="d",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            subtotal_amount=Decimal("10.00"),
            vat_amount=Decimal("2.10"),
            total_amount=Decimal("12.10"),
        )
        Notification.objects.create(
            recipient=self.company_admin,
            event_type=NotificationType.SLA_WORK_NOT_STARTED,
            extra_work=ew,
            summary="Trapportaal reinigen - gepland 19-08-2026",
        )
        self.authenticate(self.company_admin)
        row = self.client.get(LIST_URL).data["results"][0]
        self.assertEqual(row["extra_work"], ew.id)
        self.assertIsNone(row["ticket"])
        self.assertEqual(row["extra_work_title"], "Trapportaal reinigen")


class SlaWarningFeedOrderingTests(TenantFixtureMixin, APITestCase):
    def test_a_warning_sorts_with_everything_else_newest_first(self):
        older = Notification.objects.create(
            recipient=self.manager,
            event_type=NotificationType.SLA_WORK_NOT_STARTED,
            ticket=self.ticket,
            summary="older",
        )
        Notification.objects.filter(pk=older.pk).update(
            created_at=timezone.now() - datetime.timedelta(hours=2)
        )
        newer = Notification.objects.create(
            recipient=self.manager,
            event_type=NotificationType.SLA_MANAGER_REVIEW_OVERDUE,
            ticket=self.ticket,
            summary="newer",
        )
        self.authenticate(self.manager)
        ids = [row["id"] for row in self.client.get(LIST_URL).data["results"]]
        self.assertEqual(ids, [newer.id, older.id])
