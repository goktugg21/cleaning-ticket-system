from unittest.mock import patch

from django.test import TestCase, override_settings

from notifications.models import NotificationEventType, NotificationLog, NotificationStatus
from notifications.services import (
    send_password_reset_email,
    send_ticket_assigned_email,
    send_ticket_created_email,
    send_ticket_status_changed_email,
)
from test_utils import TenantFixtureMixin


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class NotificationEmailTests(TenantFixtureMixin, TestCase):
    def test_ticket_created_emails_only_staff_in_company_and_excludes_actor(self):
        logs = send_ticket_created_email(self.ticket, actor=self.company_admin)

        recipients = {log.recipient_email for log in logs}
        self.assertEqual(recipients, {self.manager.email})
        self.assertNotIn(self.other_manager.email, recipients)

    def test_assignment_email_sent_on_change_only_target(self):
        self.ticket.assigned_to = self.manager
        self.ticket.save(update_fields=["assigned_to", "updated_at"])

        logs = send_ticket_assigned_email(self.ticket, actor=self.company_admin)

        self.assertEqual([log.recipient_email for log in logs], [self.manager.email])

    def test_recipient_dedupe_and_actor_exclusion(self):
        logs = send_ticket_status_changed_email(
            self.ticket,
            old_status="OPEN",
            new_status="IN_PROGRESS",
            actor=self.customer_user,
        )

        recipients = [log.recipient_email for log in logs]
        self.assertEqual(len(recipients), len(set(recipients)))
        self.assertNotIn(self.customer_user.email, recipients)

    @patch("notifications.services.send_mail", side_effect=RuntimeError("smtp down"))
    def test_email_failure_logs_failed_status(self, _send_mail):
        logs = send_ticket_created_email(self.ticket, actor=self.customer_user)

        self.assertTrue(logs)
        self.assertTrue(all(log.status == NotificationStatus.FAILED for log in logs))
        self.assertTrue(
            NotificationLog.objects.filter(
                status=NotificationStatus.FAILED,
                error_message__icontains="smtp down",
            ).exists()
        )

    def test_password_reset_email_uses_notification_log(self):
        log = send_password_reset_email(self.customer_user, uid="abc", token="token")

        self.assertEqual(log.event_type, NotificationEventType.PASSWORD_RESET)
        self.assertEqual(log.recipient_email, self.customer_user.email)
        self.assertEqual(log.status, NotificationStatus.SENT)

    def test_admin_override_subject_and_body_when_acting_for_customer(self):
        logs = send_ticket_status_changed_email(
            self.ticket,
            old_status="WAITING_CUSTOMER_APPROVAL",
            new_status="APPROVED",
            actor=self.super_admin,
            is_admin_override=True,
        )

        self.assertTrue(logs)
        for log in logs:
            self.assertIn("Approved on behalf of customer", log.subject)
            self.assertIn(self.super_admin.email, log.subject)
            self.assertIn("on behalf of the customer", log.body)

    def test_normal_status_change_does_not_use_override_copy(self):
        logs = send_ticket_status_changed_email(
            self.ticket,
            old_status="OPEN",
            new_status="IN_PROGRESS",
            actor=self.company_admin,
        )

        self.assertTrue(logs)
        for log in logs:
            self.assertIn("Status changed", log.subject)
            self.assertNotIn("on behalf of customer", log.subject)
