"""Sprint 122 (Part C) — wiring `SuperAdminCompanySubscription.email_enabled`
into the email fan-out for TICKET_CREATED / TICKET_STATUS_CHANGED /
TICKET_SLOT_UNABLE ONLY.

Locked contracts:
  * email_enabled False (the model default, incl. for a plain #109 in-app
    subscriber who never touched this toggle) -> the SA never appears in
    the recipients of any of the three emails;
  * email_enabled True -> the SA DOES appear in all three;
  * the in-app feed (#109's own fan-out) is unaffected by this toggle
    either way — it already includes a subscribed SA regardless of email
    preference, and must keep doing so;
  * an in-app-only-subscribed SA (no email opt-in at all — the pre-Sprint-
    122 shape) still receives no email, matching the "no behaviour change
    for anyone already subscribed" requirement.
"""
from __future__ import annotations

import datetime

from django.test import TestCase, override_settings
from django.utils import timezone

from notifications.models import (
    Notification,
    NotificationEventType,
    NotificationType,
    SuperAdminCompanySubscription,
)
from notifications.services import (
    emit_ticket_message_notifications,
    send_slot_unable_to_complete_email,
    send_ticket_created_email,
    send_ticket_status_changed_email,
)
from test_utils import TenantFixtureMixin
from tickets.models import TicketMessage, TicketMessageType, TicketStaffAssignment


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class EmailToggleFanOutTests(TenantFixtureMixin, TestCase):
    def _assignment(self):
        return TicketStaffAssignment.objects.create(
            ticket=self.ticket,
            user=self.manager,
            assigned_by=self.company_admin,
            scheduled_start_at=timezone.make_aware(
                datetime.datetime(2026, 6, 10, 9, 0)
            ),
            time_window_label="ochtend",
            unable_to_complete_reason="toegang geweigerd",
        )

    def _recipients(self, logs):
        return {log.recipient_email for log in logs}

    # -- TICKET_CREATED ------------------------------------------------

    def test_ticket_created_excludes_sa_when_email_disabled(self):
        SuperAdminCompanySubscription.objects.create(
            user=self.super_admin, company=self.company, email_enabled=False,
        )
        logs = send_ticket_created_email(self.ticket, actor=self.customer_user)
        self.assertNotIn(self.super_admin.email, self._recipients(logs))

    def test_ticket_created_excludes_unsubscribed_sa(self):
        # No subscription row at all — the pre-#109 default.
        logs = send_ticket_created_email(self.ticket, actor=self.customer_user)
        self.assertNotIn(self.super_admin.email, self._recipients(logs))

    def test_ticket_created_includes_sa_when_email_enabled(self):
        SuperAdminCompanySubscription.objects.create(
            user=self.super_admin, company=self.company, email_enabled=True,
        )
        logs = send_ticket_created_email(self.ticket, actor=self.customer_user)
        self.assertIn(self.super_admin.email, self._recipients(logs))

    def test_ticket_created_email_enabled_for_other_company_does_not_leak(self):
        SuperAdminCompanySubscription.objects.create(
            user=self.super_admin, company=self.other_company, email_enabled=True,
        )
        logs = send_ticket_created_email(self.ticket, actor=self.customer_user)
        self.assertNotIn(self.super_admin.email, self._recipients(logs))

    # -- TICKET_STATUS_CHANGED ------------------------------------------

    def test_status_changed_includes_sa_when_email_enabled(self):
        SuperAdminCompanySubscription.objects.create(
            user=self.super_admin, company=self.company, email_enabled=True,
        )
        logs = send_ticket_status_changed_email(
            self.ticket,
            old_status="OPEN",
            new_status="IN_PROGRESS",
            actor=self.customer_user,
        )
        self.assertIn(self.super_admin.email, self._recipients(logs))
        self.assertEqual(
            logs[0].event_type, NotificationEventType.TICKET_STATUS_CHANGED
        )

    def test_status_changed_excludes_sa_when_email_disabled(self):
        SuperAdminCompanySubscription.objects.create(
            user=self.super_admin, company=self.company, email_enabled=False,
        )
        logs = send_ticket_status_changed_email(
            self.ticket,
            old_status="OPEN",
            new_status="IN_PROGRESS",
            actor=self.customer_user,
        )
        self.assertNotIn(self.super_admin.email, self._recipients(logs))

    # -- TICKET_SLOT_UNABLE ----------------------------------------------

    def test_slot_unable_includes_sa_when_email_enabled(self):
        SuperAdminCompanySubscription.objects.create(
            user=self.super_admin, company=self.company, email_enabled=True,
        )
        assignment = self._assignment()
        logs = send_slot_unable_to_complete_email(
            self.ticket, assignment, actor=self.manager,
        )
        self.assertIn(self.super_admin.email, self._recipients(logs))

    def test_slot_unable_excludes_sa_when_email_disabled(self):
        SuperAdminCompanySubscription.objects.create(
            user=self.super_admin, company=self.company, email_enabled=False,
        )
        assignment = self._assignment()
        logs = send_slot_unable_to_complete_email(
            self.ticket, assignment, actor=self.manager,
        )
        self.assertNotIn(self.super_admin.email, self._recipients(logs))

    # -- other event types / in-app feed untouched -----------------------

    def test_in_app_feed_unaffected_by_email_toggle_off(self):
        # #109's in-app fan-out already includes a subscribed SA regardless
        # of the email preference; this toggle must not change that.
        SuperAdminCompanySubscription.objects.create(
            user=self.super_admin, company=self.company, email_enabled=False,
        )
        message = TicketMessage.objects.create(
            ticket=self.ticket,
            author=self.customer_user,
            message="hallo provider",
            message_type=TicketMessageType.PUBLIC_REPLY,
        )
        emit_ticket_message_notifications(message, actor=self.customer_user)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.super_admin,
                event_type=NotificationType.TICKET_MESSAGE,
            ).exists()
        )

    def test_in_app_feed_unaffected_by_email_toggle_on(self):
        SuperAdminCompanySubscription.objects.create(
            user=self.super_admin, company=self.company, email_enabled=True,
        )
        message = TicketMessage.objects.create(
            ticket=self.ticket,
            author=self.customer_user,
            message="hallo provider",
            message_type=TicketMessageType.PUBLIC_REPLY,
        )
        emit_ticket_message_notifications(message, actor=self.customer_user)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.super_admin,
                event_type=NotificationType.TICKET_MESSAGE,
            ).exists()
        )
