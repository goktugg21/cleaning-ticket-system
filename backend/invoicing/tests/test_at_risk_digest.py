"""
WP-1 G4 — the weekly billing-month-at-risk digest task.

Only the SMTP transport is mocked (the project's standing test rule);
the `NotificationLog` rows are the assertions, because the log row IS
what the send helper writes first.
"""
from __future__ import annotations

import datetime
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import UserRole
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from invoicing.tasks import (
    AT_RISK_SUBJECT_PREFIX,
    send_billing_month_at_risk_digest,
)
from notifications.models import NotificationLog
from tickets.models import Ticket, TicketStatus, TicketType
from test_utils import TenantFixtureMixin


def _digest_logs():
    return NotificationLog.objects.filter(
        subject__startswith=AT_RISK_SUBJECT_PREFIX
    )


class AtRiskDigestTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        patcher = patch("notifications.tasks.send_mail", return_value=1)
        self.send_mail = patcher.start()
        self.addCleanup(patcher.stop)
        self.today = timezone.localdate()
        self.now = timezone.now()

    def at_risk_ew(self, *, company=None, building=None, customer=None):
        company = company or self.company
        ew = ExtraWorkRequest.objects.create(
            company=company,
            building=building or self.building,
            customer=customer or self.customer,
            created_by=self.super_admin,
            title="Digest bait",
            description="x",
            deadline=self.today,
            status=ExtraWorkStatus.IN_PROGRESS,
        )
        Ticket.objects.create(
            company=company,
            customer=customer or self.customer,
            building=building or self.building,
            title="Spawned",
            description="x",
            type=TicketType.REQUEST,
            status=TicketStatus.WAITING_MANAGER_REVIEW,
            created_by=self.super_admin,
            extra_work_request=ew,
            manager_review_at=self.now - datetime.timedelta(days=9),
        )
        return ew

    def test_admins_of_the_at_risk_company_get_one_mail_each(self):
        self.at_risk_ew()
        result = send_billing_month_at_risk_digest()
        self.assertEqual(result["mailed"], 1)
        self.assertEqual(result["failed"], 0)
        logs = _digest_logs()
        self.assertEqual(logs.count(), 1)
        log = logs.get()
        self.assertEqual(log.recipient_email, self.company_admin.email)
        self.assertIn("wacht op controle", log.body)
        self.assertIn(self.customer.name, log.body)
        # The other company had nothing at risk: its admin gets nothing.
        self.assertFalse(
            _digest_logs()
            .filter(recipient_email=self.other_company_admin.email)
            .exists()
        )

    def test_a_second_run_inside_the_week_sends_nothing_new(self):
        self.at_risk_ew()
        send_billing_month_at_risk_digest()
        result = send_billing_month_at_risk_digest()
        self.assertEqual(result["mailed"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(_digest_logs().count(), 1)

    def test_nothing_at_risk_means_no_mail(self):
        result = send_billing_month_at_risk_digest()
        self.assertEqual(result["mailed"], 0)
        self.assertEqual(_digest_logs().count(), 0)

    def test_the_task_never_raises_and_counts_a_failure(self):
        self.at_risk_ew()
        with patch(
            "invoicing.at_risk.at_risk_groups",
            side_effect=RuntimeError("boom"),
        ):
            result = send_billing_month_at_risk_digest()
        self.assertGreaterEqual(result["failed"], 1)
        self.assertEqual(result["mailed"], 0)
