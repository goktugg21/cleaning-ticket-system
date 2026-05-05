from unittest import mock

from django.test import TestCase

from notifications.models import NotificationEventType, NotificationLog, NotificationStatus
from notifications.services import send_logged_email


class CeleryEmailTaskTests(TestCase):
    def test_eager_send_marks_log_sent(self):
        with mock.patch("notifications.tasks.send_mail", return_value=1) as send:
            log = send_logged_email(
                recipient_email="dest@example.com",
                subject="hello",
                body="body",
                event_type=NotificationEventType.TICKET_CREATED,
            )

        send.assert_called_once()
        log.refresh_from_db()
        self.assertEqual(log.status, NotificationStatus.SENT)
        self.assertIsNotNone(log.sent_at)

    def test_zero_sent_count_marks_log_failed(self):
        with mock.patch("notifications.tasks.send_mail", return_value=0):
            log = send_logged_email(
                recipient_email="dest@example.com",
                subject="hello",
                body="body",
                event_type=NotificationEventType.TICKET_CREATED,
            )

        log.refresh_from_db()
        self.assertEqual(log.status, NotificationStatus.FAILED)
        self.assertIn("0 sent messages", log.error_message)

    def test_smtp_failure_after_max_retries_marks_failed(self):
        # In eager mode with EAGER_PROPAGATES, retries run inline.
        # send_email_task autoretries up to 3 times then marks FAILED.
        with mock.patch(
            "notifications.tasks.send_mail",
            side_effect=RuntimeError("smtp boom"),
        ):
            log = send_logged_email(
                recipient_email="dest@example.com",
                subject="hello",
                body="body",
                event_type=NotificationEventType.TICKET_CREATED,
            )

        log.refresh_from_db()
        self.assertEqual(log.status, NotificationStatus.FAILED)
        self.assertIn("smtp boom", log.error_message)

    def test_log_starts_in_queued_state_before_task_runs(self):
        # Disable eager mode just to assert the pre-task state.
        # We do this by patching the task's delay to a no-op.
        with mock.patch(
            "notifications.tasks.send_email_task.delay"
        ) as delay:
            log = send_logged_email(
                recipient_email="dest@example.com",
                subject="hello",
                body="body",
                event_type=NotificationEventType.TICKET_CREATED,
            )

        delay.assert_called_once()
        log.refresh_from_db()
        self.assertEqual(log.status, NotificationStatus.QUEUED)
