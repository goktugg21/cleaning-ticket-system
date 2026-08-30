"""P-5 S8 — the owner's additions to the automatic warnings.

Four simple choices, each additive, each defaulting to today's
behaviour:

  1. WHO ELSE receives a warning — extra rings on the first warning,
     and an extra e-mail address.
  2. A THIRD escalation step — "still not fixed N days after the second
     warning -> the company admins", off by default.
  3. WEEKEND handling — working hours (today) or hours on the clock.
  4. A WEEKLY summary — Monday's list of every warning sent.
"""
from __future__ import annotations

import datetime
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from notifications.models import NotificationEventType, NotificationLog
from sla import warnings as sla_warnings
from sla.models import SlaWarningThreshold
from sla.tasks import send_sla_weekly_summary
from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus


def _local(y, m, d, hh=12, mm=0):
    return timezone.make_aware(
        datetime.datetime(y, m, d, hh, mm), timezone.get_current_timezone()
    )


#: A Wednesday noon, so "two working days ago" is Monday and "one
#: calendar day ago" is Tuesday.
NOW = _local(2026, 8, 19, 12, 0)


def _recipients(event_type):
    return set(
        NotificationLog.objects.filter(event_type=event_type).values_list(
            "recipient_email", flat=True
        )
    )


class _Base(TenantFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        patcher = patch("notifications.services.send_mail")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _row(self, **fields):
        row, _ = SlaWarningThreshold.objects.get_or_create(company=self.company)
        for name, value in fields.items():
            setattr(row, name, value)
        row.save()
        return row

    def _in_review(self, *, since):
        Ticket.objects.filter(pk=self.ticket.pk).update(
            status=TicketStatus.WAITING_MANAGER_REVIEW,
            manager_review_at=since,
        )

    def _not_started(self, *, planned):
        Ticket.objects.filter(pk=self.ticket.pk).update(
            status=TicketStatus.OPEN, scheduled_start_at=planned
        )


class WhoReceivesTests(_Base):
    def test_defaults_reproduce_todays_recipients(self):
        self._in_review(since=NOW - datetime.timedelta(days=2))
        sla_warnings.sweep(now=NOW)
        got = _recipients(NotificationEventType.SLA_MANAGER_REVIEW_OVERDUE)
        self.assertIn(self.manager.email, got)
        self.assertNotIn(self.company_admin.email, got)

    def test_also_notify_adds_the_ring_to_the_first_warning(self):
        self._row(manager_review_also_notify=["company_admins"])
        self._in_review(since=NOW - datetime.timedelta(days=2))
        sla_warnings.sweep(now=NOW)
        got = _recipients(NotificationEventType.SLA_MANAGER_REVIEW_OVERDUE)
        self.assertIn(self.manager.email, got)
        self.assertIn(self.company_admin.email, got)

    def test_the_extra_address_is_mailed_and_logged_once_per_cooldown(self):
        self._row(manager_review_extra_email="ops@example.com")
        self._in_review(since=NOW - datetime.timedelta(days=2))
        sla_warnings.sweep(now=NOW)
        sla_warnings.sweep(now=NOW + datetime.timedelta(hours=1))
        rows = NotificationLog.objects.filter(
            event_type=NotificationEventType.SLA_MANAGER_REVIEW_OVERDUE,
            recipient_email="ops@example.com",
        )
        self.assertEqual(rows.count(), 1)
        self.assertIsNone(rows.first().recipient_user_id)


class ThirdStepTests(_Base):
    def test_off_by_default(self):
        self._not_started(planned=NOW - datetime.timedelta(days=30))
        sla_warnings.sweep(now=NOW)
        got = _recipients(NotificationEventType.SLA_WORK_NOT_STARTED)
        self.assertNotIn(self.company_admin.email, got)

    def test_reaches_the_admins_n_days_after_the_second_warning(self):
        self._row(not_started_final_escalate_days=2)
        # Second warning: 16 working hours after the planned start
        # (the platform default) — planned on Monday 09:00, that is
        # Tuesday 17:00; two calendar days later is Thursday 17:00.
        self._not_started(planned=_local(2026, 8, 10, 9, 0))
        sla_warnings.sweep(now=_local(2026, 8, 12, 12, 0))
        self.assertNotIn(
            self.company_admin.email,
            _recipients(NotificationEventType.SLA_WORK_NOT_STARTED),
        )
        NotificationLog.objects.all().delete()
        sla_warnings.sweep(now=_local(2026, 8, 14, 12, 0))
        self.assertIn(
            self.company_admin.email,
            _recipients(NotificationEventType.SLA_WORK_NOT_STARTED),
        )


class WeekendHandlingTests(_Base):
    def test_working_hours_ignore_the_weekend(self):
        # Reported finished Friday 16:00; Monday 09:00 is one working
        # hour later — under the default 8 working hours, silent.
        self._in_review(since=_local(2026, 8, 14, 16, 0))
        result = sla_warnings.sweep(now=_local(2026, 8, 17, 9, 0))
        self.assertEqual(result["manager_review"], 0)

    def test_calendar_hours_count_the_weekend(self):
        self._row(count_calendar_days=True)
        self._in_review(since=_local(2026, 8, 14, 16, 0))
        result = sla_warnings.sweep(now=_local(2026, 8, 17, 9, 0))
        self.assertGreaterEqual(result["manager_review"], 1)


class WeeklySummaryTests(_Base):
    def test_off_by_default_sends_nothing(self):
        result = send_sla_weekly_summary(now=NOW.isoformat())
        self.assertEqual(result["mails"], 0)

    def test_lists_last_weeks_warnings_for_the_admins(self):
        self._row(weekly_summary_enabled=True)
        self._in_review(since=NOW - datetime.timedelta(days=2))
        sla_warnings.sweep(now=NOW)
        # The logs' `created_at` is the REAL clock (auto_now_add), so the
        # summary's week is anchored on a real "now" one day ahead.
        result = send_sla_weekly_summary(
            now=(timezone.now() + datetime.timedelta(days=1)).isoformat()
        )
        self.assertEqual(result["failed"], 0)
        self.assertGreaterEqual(result["mails"], 1)
        row = NotificationLog.objects.filter(
            event_type=NotificationEventType.SLA_WEEKLY_SUMMARY,
            recipient_email=self.company_admin.email,
        ).first()
        self.assertIsNotNone(row)
        self.assertIn(self.ticket.ticket_no, row.body)


class ChoicesApiTests(TenantFixtureMixin, APITestCase):
    def _url(self):
        return f"/api/sla/warning-thresholds/{self.company.id}/"

    def test_get_carries_the_defaults(self):
        self.authenticate(self.company_admin)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        choices = response.data["choices"]
        self.assertFalse(choices["count_calendar_days"])
        self.assertFalse(choices["weekly_summary_enabled"])
        self.assertEqual(choices["warnings"]["not_started"]["also_notify"], [])
        self.assertEqual(choices["warnings"]["not_started"]["extra_email"], "")
        self.assertIsNone(choices["warnings"]["not_started"]["final_escalate_days"])
        self.assertFalse(response.data["is_customized"])

    def test_put_stores_every_choice_and_reset_clears_them(self):
        self.authenticate(self.company_admin)
        response = self.client.put(
            self._url(),
            {
                "count_calendar_days": True,
                "weekly_summary_enabled": True,
                "manager_review_also_notify": ["company_admins"],
                "manager_review_extra_email": "ops@example.com",
                "manager_review_final_escalate_days": 3,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        choices = response.data["choices"]
        self.assertTrue(choices["count_calendar_days"])
        self.assertTrue(choices["weekly_summary_enabled"])
        self.assertEqual(
            choices["warnings"]["manager_review"],
            {
                "also_notify": ["company_admins"],
                "extra_email": "ops@example.com",
                "final_escalate_days": 3,
            },
        )
        self.assertTrue(response.data["is_customized"])
        reset = self.client.delete(self._url())
        self.assertEqual(reset.status_code, status.HTTP_200_OK)
        self.assertFalse(reset.data["choices"]["count_calendar_days"])

    def test_an_unknown_ring_is_refused_and_named(self):
        self.authenticate(self.company_admin)
        response = self.client.put(
            self._url(), {"not_started_also_notify": ["everybody"]}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not_started_also_notify", response.data)
