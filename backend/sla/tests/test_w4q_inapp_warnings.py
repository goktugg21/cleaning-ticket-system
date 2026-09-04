"""Sprint W4-Q §1 — the three time-driven warnings reach the BELL.

W1-B sent email and said plainly that it did not do the in-app feed.
These tests are about that half: that a bell row is written for the same
people the mail goes to, that it never crosses a tenant boundary, and —
the part that actually matters — that opening a second channel did not
turn one cooldown into two.

Every `now` is the same fixed Wednesday inside the business window that
`test_warnings.py` uses, for the same reason: so the business-hours
arithmetic in the assertions is arithmetic and not a guess.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from notifications.models import (
    Notification,
    NotificationEventType,
    NotificationLog,
    NotificationType,
)
from sla import warnings as sla_warnings
from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus


def _local(y, m, d, hh=12, mm=0):
    return timezone.make_aware(
        datetime.datetime(y, m, d, hh, mm), timezone.get_current_timezone()
    )


#: Wednesday 19-08-2026, 12:00 Amsterdam — mid-window on a business day.
NOW = _local(2026, 8, 19, 12, 0)


def _bell_recipients(event_type):
    return set(
        Notification.objects.filter(event_type=event_type).values_list(
            "recipient__email", flat=True
        )
    )


def _mail_recipients(event_type):
    return set(
        NotificationLog.objects.filter(event_type=event_type).values_list(
            "recipient_email", flat=True
        )
    )


class InAppWarningTestBase(TenantFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        patcher = patch("notifications.services.send_mail")
        self.send_mail = patcher.start()
        self.addCleanup(patcher.stop)

    def make_extra_work(self, **overrides):
        fields = dict(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.company_admin,
            title="Trapportaal reinigen",
            description="customer-visible description",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            subtotal_amount=Decimal("100.00"),
            vat_amount=Decimal("21.00"),
            total_amount=Decimal("121.00"),
        )
        fields.update(overrides)
        return ExtraWorkRequest.objects.create(**fields)

    def stage_not_started_ticket(self, days=2):
        Ticket.objects.filter(pk=self.ticket.pk).update(
            status=TicketStatus.OPEN,
            scheduled_start_at=NOW - datetime.timedelta(days=days),
        )

    def stage_manager_review(self, days=2):
        Ticket.objects.filter(pk=self.ticket.pk).update(
            status=TicketStatus.WAITING_MANAGER_REVIEW,
            manager_review_at=NOW - datetime.timedelta(days=days),
        )

    def stage_approval_cutoff(self, billing_day=21, sent_days_ago=1):
        self.customer.invoice_day_of_month = billing_day
        self.customer.save(update_fields=["invoice_day_of_month"])
        ew = self.make_extra_work()
        Ticket.objects.filter(pk=self.ticket.pk).update(
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            sent_for_approval_at=NOW - datetime.timedelta(days=sent_days_ago),
            extra_work_request=ew,
        )
        return ew


# ---------------------------------------------------------------------------
# The bell rows exist at all, and carry a usable deep link
# ---------------------------------------------------------------------------

class BellRowsTests(InAppWarningTestBase):
    def test_not_started_writes_a_bell_row_for_the_manager(self):
        self.stage_not_started_ticket()
        sla_warnings.sweep(now=NOW)
        self.assertIn(
            self.manager.email,
            _bell_recipients(NotificationType.SLA_WORK_NOT_STARTED),
        )

    def test_manager_review_writes_a_bell_row(self):
        self.stage_manager_review()
        sla_warnings.sweep(now=NOW)
        self.assertIn(
            self.manager.email,
            _bell_recipients(NotificationType.SLA_MANAGER_REVIEW_OVERDUE),
        )

    def test_approval_cutoff_writes_a_bell_row_for_the_customer(self):
        self.stage_approval_cutoff()
        sla_warnings.sweep(now=NOW)
        self.assertIn(
            self.customer_user.email,
            _bell_recipients(NotificationType.SLA_APPROVAL_CUTOFF_DUE),
        )

    def test_the_two_channels_reach_exactly_the_same_people(self):
        """The whole reason `_emit` writes both from one list."""
        self.stage_not_started_ticket()
        sla_warnings.sweep(now=NOW)
        event = NotificationType.SLA_WORK_NOT_STARTED
        self.assertEqual(_bell_recipients(event), _mail_recipients(event))
        self.assertTrue(_bell_recipients(event))

    def test_the_row_deep_links_to_its_ticket(self):
        self.stage_not_started_ticket()
        sla_warnings.sweep(now=NOW)
        row = Notification.objects.filter(
            event_type=NotificationType.SLA_WORK_NOT_STARTED,
            recipient=self.manager,
        ).first()
        self.assertIsNotNone(row)
        self.assertEqual(row.ticket_id, self.ticket.pk)
        self.assertIsNone(row.extra_work_id)

    def test_an_extra_work_row_deep_links_to_the_extra_work(self):
        ew = self.make_extra_work(
            provider_planned_date=(NOW - datetime.timedelta(days=3)).date()
        )
        sla_warnings.sweep(now=NOW)
        row = Notification.objects.filter(
            event_type=NotificationType.SLA_WORK_NOT_STARTED,
            recipient=self.company_admin,
        ).first()
        self.assertIsNotNone(row)
        self.assertEqual(row.extra_work_id, ew.pk)
        self.assertIsNone(row.ticket_id)

    def test_the_row_is_unread_has_no_actor_and_is_not_directed(self):
        """Nobody did this. That is the whole category."""
        self.stage_not_started_ticket()
        sla_warnings.sweep(now=NOW)
        row = Notification.objects.filter(
            event_type=NotificationType.SLA_WORK_NOT_STARTED,
            recipient=self.manager,
        ).first()
        self.assertIsNone(row.read_at)
        self.assertIsNone(row.actor_id)
        self.assertFalse(row.is_directed)

    def test_the_summary_carries_facts_and_not_a_headline(self):
        """The sentence naming the warning is rendered by the frontend
        through t(); a Dutch headline stored here would be a string
        nobody can translate. The summary is the ticket and the clock."""
        self.stage_not_started_ticket()
        sla_warnings.sweep(now=NOW)
        row = Notification.objects.filter(
            event_type=NotificationType.SLA_WORK_NOT_STARTED,
            recipient=self.manager,
        ).first()
        self.assertIn(self.ticket.ticket_no, row.summary)
        self.assertIn("werkuren", row.summary)

    def test_emit_does_not_require_an_email_for_the_bell(self):
        """W1-B's `_emit` dropped an address-less user before the send,
        so they got nothing at all. The bell no longer inherits that.

        Tested at `_emit` and not through the sweep on purpose: the
        rosters in `notifications.services` still exclude `email=""`
        upstream (`_active_users`), so no such recipient reaches the
        sweep today. Asserting it end-to-end would be asserting a path
        that does not exist; asserting it here is asserting the code
        this sprint actually changed."""
        addressless = self.make_user("nomail-w4q@example.com", "BUILDING_MANAGER")
        type(addressless).objects.filter(pk=addressless.pk).update(email="")
        addressless.refresh_from_db()
        # P-16 Part D — `_emit` takes (template_key, params) now; the
        # words render through the copy catalogue per recipient.
        warned = sla_warnings._emit(
            event_type=NotificationType.SLA_WORK_NOT_STARTED,
            template_key="sla_not_started_ticket",
            params={
                "ticket_no": self.ticket.ticket_no,
                "ticket_title": self.ticket.title,
                "planned_label": "01-09-2026 08:00",
                "hours": 9,
            },
            users=[addressless],
            now=NOW,
            cooldown_hours=24,
            ticket=self.ticket,
        )
        self.assertEqual(warned, 1)
        self.assertTrue(
            Notification.objects.filter(
                event_type=NotificationType.SLA_WORK_NOT_STARTED,
                recipient_id=addressless.pk,
            ).exists()
        )
        self.assertFalse(
            NotificationLog.objects.filter(
                recipient_user_id=addressless.pk
            ).exists()
        )


# ---------------------------------------------------------------------------
# Tenant scoping — the bell is a second door into the same building
# ---------------------------------------------------------------------------

class BellTenantScopingTests(InAppWarningTestBase):
    def test_not_started_bell_never_reaches_another_company(self):
        self.stage_not_started_ticket()
        sla_warnings.sweep(now=NOW)
        got = _bell_recipients(NotificationType.SLA_WORK_NOT_STARTED)
        self.assertNotIn(self.other_manager.email, got)
        self.assertNotIn(self.other_company_admin.email, got)
        self.assertNotIn(self.other_customer_user.email, got)

    def test_manager_review_bell_never_reaches_the_customer(self):
        """WAITING_MANAGER_REVIEW is invisible to the customer by design;
        a bell row would be the leak the e-mail path does not have."""
        self.stage_manager_review(days=5)
        sla_warnings.sweep(now=NOW)
        got = _bell_recipients(NotificationType.SLA_MANAGER_REVIEW_OVERDUE)
        self.assertNotIn(self.customer_user.email, got)
        self.assertNotIn(self.other_customer_user.email, got)

    def test_approval_cutoff_bell_never_reaches_another_tenant(self):
        self.stage_approval_cutoff()
        sla_warnings.sweep(now=NOW)
        got = _bell_recipients(NotificationType.SLA_APPROVAL_CUTOFF_DUE)
        self.assertNotIn(self.other_customer_user.email, got)
        self.assertNotIn(self.other_manager.email, got)
        self.assertNotIn(self.other_company_admin.email, got)

    def test_extra_work_bell_never_reaches_another_tenant(self):
        self.make_extra_work(
            provider_planned_date=(NOW - datetime.timedelta(days=3)).date()
        )
        sla_warnings.sweep(now=NOW)
        got = _bell_recipients(NotificationType.SLA_WORK_NOT_STARTED)
        self.assertNotIn(self.other_company_admin.email, got)
        self.assertNotIn(self.other_manager.email, got)
        self.assertNotIn(self.customer_user.email, got)


# ---------------------------------------------------------------------------
# ONE cooldown, shared. A 5-minute sweep with a broken cooldown is 288 a day.
# ---------------------------------------------------------------------------

class SharedCooldownTests(InAppWarningTestBase):
    def test_the_bell_does_not_repeat_five_minutes_later(self):
        self.stage_not_started_ticket()
        sla_warnings.sweep(now=NOW)
        before = Notification.objects.filter(
            event_type=NotificationType.SLA_WORK_NOT_STARTED
        ).count()
        sla_warnings.sweep(now=NOW + datetime.timedelta(minutes=5))
        after = Notification.objects.filter(
            event_type=NotificationType.SLA_WORK_NOT_STARTED
        ).count()
        self.assertGreaterEqual(before, 1)
        self.assertEqual(before, after)

    def test_a_bell_row_alone_holds_the_window_shut_for_the_email(self):
        """The shared-cooldown decision, stated as a test. Delete the
        mail log and leave the bell row: the next tick must still stay
        quiet. Two independent clocks would re-send the mail here, which
        is one problem told to one person twice in one day."""
        self.stage_not_started_ticket()
        sla_warnings.sweep(now=NOW)
        NotificationLog.objects.filter(
            event_type=NotificationEventType.SLA_WORK_NOT_STARTED
        ).delete()
        result = sla_warnings.sweep(now=NOW + datetime.timedelta(minutes=5))
        self.assertEqual(result["not_started_tickets"], 0)
        self.assertFalse(
            NotificationLog.objects.filter(
                event_type=NotificationEventType.SLA_WORK_NOT_STARTED
            ).exists()
        )

    def test_a_mail_row_alone_holds_the_window_shut_for_the_bell(self):
        """The same argument, the other way round — the case that
        matters most, because W1-B's rows already exist in production
        and must not all re-fire as bells on the first sweep after
        deploy."""
        self.stage_not_started_ticket()
        sla_warnings.sweep(now=NOW)
        Notification.objects.filter(
            event_type=NotificationType.SLA_WORK_NOT_STARTED
        ).delete()
        result = sla_warnings.sweep(now=NOW + datetime.timedelta(minutes=5))
        self.assertEqual(result["not_started_tickets"], 0)
        self.assertFalse(
            Notification.objects.filter(
                event_type=NotificationType.SLA_WORK_NOT_STARTED
            ).exists()
        )

    def test_both_channels_speak_again_once_the_window_expires(self):
        self.stage_not_started_ticket()
        sla_warnings.sweep(now=NOW)
        aged = NOW - datetime.timedelta(hours=25)
        NotificationLog.objects.filter(
            event_type=NotificationEventType.SLA_WORK_NOT_STARTED
        ).update(created_at=aged)
        Notification.objects.filter(
            event_type=NotificationType.SLA_WORK_NOT_STARTED
        ).update(created_at=aged)
        result = sla_warnings.sweep(now=NOW)
        self.assertGreaterEqual(result["not_started_tickets"], 1)

    def test_one_person_gets_exactly_one_bell_row_per_tick(self):
        """The responsible ring and the escalation ring overlap on
        purpose; the dedupe by recipient id is what stops the same
        person collecting the warning twice in one sweep."""
        self.stage_not_started_ticket(days=5)
        sla_warnings.sweep(now=NOW)
        self.assertEqual(
            Notification.objects.filter(
                event_type=NotificationType.SLA_WORK_NOT_STARTED,
                recipient=self.manager,
            ).count(),
            1,
        )
