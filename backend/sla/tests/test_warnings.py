"""Sprint W1-B §2.7 — the time-driven warnings and the one escalation hop.

The engine measured and told nobody. These tests are about the telling:
that each warning fires on the right threshold, reaches the right ring,
escalates exactly one hop, repeats no more than once a day, and never
crosses a tenant boundary.

Every `now` in this module is a fixed Wednesday inside the business
window (Europe/Amsterdam, Mon-Fri 09:00-17:00), so the business-hours
arithmetic in the assertions is arithmetic and not a guess.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from buildings.models import BuildingManagerAssignment
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from notifications.models import NotificationEventType, NotificationLog
from sla import warnings as sla_warnings
from sla.tasks import sweep_sla_warnings
from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus


def _local(y, m, d, hh=12, mm=0):
    return timezone.make_aware(
        datetime.datetime(y, m, d, hh, mm), timezone.get_current_timezone()
    )


#: Wednesday 19-08-2026, 12:00 Amsterdam — mid-window on a business day.
NOW = _local(2026, 8, 19, 12, 0)


def _recipients(event_type):
    return set(
        NotificationLog.objects.filter(event_type=event_type).values_list(
            "recipient_email", flat=True
        )
    )


class WarningTestBase(TenantFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        # The sender is the only thing mocked, per the project rule: real
        # Postgres, real models, only the SMTP transport faked.
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


# ---------------------------------------------------------------------------
# 1. Approval due before the billing cutoff
# ---------------------------------------------------------------------------

class ApprovalCutoffWarningTests(WarningTestBase):
    def _stage(self, *, sent_days_ago=1, billing_day=21, ticket=None):
        self.customer.invoice_day_of_month = billing_day
        self.customer.save(update_fields=["invoice_day_of_month"])
        ew = self.make_extra_work()
        ticket = ticket or self.ticket
        Ticket.objects.filter(pk=ticket.pk).update(
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            sent_for_approval_at=NOW - datetime.timedelta(days=sent_days_ago),
            extra_work_request=ew,
        )
        return ew, Ticket.objects.get(pk=ticket.pk)

    def test_warns_the_customer_when_the_cutoff_is_near(self):
        # Cutoff on the 21st, today is the 19th -> 2 days out.
        self._stage(billing_day=21)
        result = sla_warnings.sweep(now=NOW)
        self.assertEqual(result["failed"], 0)
        self.assertGreaterEqual(result["approval_cutoff"], 1)
        self.assertIn(
            self.customer_user.email,
            _recipients(NotificationEventType.SLA_APPROVAL_CUTOFF_DUE),
        )

    def test_body_states_the_rule_and_the_reversal(self):
        self._stage(billing_day=21)
        sla_warnings.sweep(now=NOW)
        log = NotificationLog.objects.filter(
            event_type=NotificationEventType.SLA_APPROVAL_CUTOFF_DUE,
            recipient_email=self.customer_user.email,
        ).first()
        self.assertIsNotNone(log)
        self.assertIn("facturatiedatum", log.body)
        self.assertIn("creditnota", log.body)

    def test_silent_while_the_cutoff_is_far_away(self):
        # Cutoff on the 28th, today is the 19th -> 9 days, past the
        # 5-day default warning window.
        self._stage(billing_day=28)
        result = sla_warnings.sweep(now=NOW)
        self.assertEqual(result["approval_cutoff"], 0)

    def test_customer_without_a_billing_schedule_is_never_warned(self):
        self.customer.invoice_day_of_month = None
        self.customer.invoice_day_rule = ""
        self.customer.save(
            update_fields=["invoice_day_of_month", "invoice_day_rule"]
        )
        ew = self.make_extra_work()
        Ticket.objects.filter(pk=self.ticket.pk).update(
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            sent_for_approval_at=NOW - datetime.timedelta(days=1),
            extra_work_request=ew,
        )
        result = sla_warnings.sweep(now=NOW)
        self.assertEqual(result["approval_cutoff"], 0)

    def test_escalates_one_hop_to_the_provider_inside_the_second_window(self):
        # Cutoff on the 20th -> 1 day out, inside the 2-day escalation.
        self._stage(billing_day=20)
        sla_warnings.sweep(now=NOW)
        got = _recipients(NotificationEventType.SLA_APPROVAL_CUTOFF_DUE)
        self.assertIn(self.customer_user.email, got)
        self.assertIn(self.manager.email, got)

    def test_does_not_escalate_outside_the_second_window(self):
        # Cutoff on the 23rd -> 4 days out: warn, do not escalate.
        self._stage(billing_day=23)
        sla_warnings.sweep(now=NOW)
        got = _recipients(NotificationEventType.SLA_APPROVAL_CUTOFF_DUE)
        self.assertIn(self.customer_user.email, got)
        self.assertNotIn(self.manager.email, got)

    def test_a_plain_melding_with_no_extra_work_is_not_warned_about(self):
        self.customer.invoice_day_of_month = 21
        self.customer.save(update_fields=["invoice_day_of_month"])
        Ticket.objects.filter(pk=self.ticket.pk).update(
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            sent_for_approval_at=NOW - datetime.timedelta(days=1),
            extra_work_request=None,
        )
        result = sla_warnings.sweep(now=NOW)
        self.assertEqual(result["approval_cutoff"], 0)

    def test_already_invoiced_work_is_not_warned_about(self):
        ew, _ = self._stage(billing_day=21)
        ew.is_invoiced = True
        ew.save(update_fields=["is_invoiced"])
        result = sla_warnings.sweep(now=NOW)
        self.assertEqual(result["approval_cutoff"], 0)

    def test_cooldown_stops_the_five_minute_repeat(self):
        self._stage(billing_day=21)
        first = sla_warnings.sweep(now=NOW)
        second = sla_warnings.sweep(now=NOW + datetime.timedelta(minutes=5))
        self.assertGreaterEqual(first["approval_cutoff"], 1)
        self.assertEqual(second["approval_cutoff"], 0)

    def test_it_speaks_again_once_the_cooldown_expires(self):
        self._stage(billing_day=21)
        sla_warnings.sweep(now=NOW)
        # `NotificationLog.created_at` is auto_now_add, i.e. the REAL
        # clock, while `now` here is a fixed simulated instant. In
        # production those are the same clock; in a test they are not, so
        # the row is aged against the SIMULATED clock rather than the
        # sweep being run 25 hours "later" — otherwise the assertion
        # would be about the difference between the two clocks and not
        # about the cooldown at all.
        NotificationLog.objects.filter(
            event_type=NotificationEventType.SLA_APPROVAL_CUTOFF_DUE
        ).update(created_at=NOW - datetime.timedelta(hours=25))
        again = sla_warnings.sweep(now=NOW)
        self.assertGreaterEqual(again["approval_cutoff"], 1)

    def test_never_reaches_another_tenant(self):
        self._stage(billing_day=21)
        sla_warnings.sweep(now=NOW)
        got = _recipients(NotificationEventType.SLA_APPROVAL_CUTOFF_DUE)
        self.assertNotIn(self.other_customer_user.email, got)
        self.assertNotIn(self.other_manager.email, got)
        self.assertNotIn(self.other_company_admin.email, got)


# ---------------------------------------------------------------------------
# 2. Manager review past its target
# ---------------------------------------------------------------------------

class ManagerReviewWarningTests(WarningTestBase):
    def _stage(self, *, business_days_ago=2):
        Ticket.objects.filter(pk=self.ticket.pk).update(
            status=TicketStatus.WAITING_MANAGER_REVIEW,
            manager_review_at=NOW - datetime.timedelta(days=business_days_ago),
        )

    def test_warns_the_responsible_manager(self):
        self._stage(business_days_ago=2)
        result = sla_warnings.sweep(now=NOW)
        self.assertEqual(result["failed"], 0)
        self.assertGreaterEqual(result["manager_review"], 1)
        self.assertIn(
            self.manager.email,
            _recipients(NotificationEventType.SLA_MANAGER_REVIEW_OVERDUE),
        )

    def test_silent_inside_the_target(self):
        # 12:00 Wednesday minus 1 hour = 1 business hour, under the
        # 8-business-hour default.
        Ticket.objects.filter(pk=self.ticket.pk).update(
            status=TicketStatus.WAITING_MANAGER_REVIEW,
            manager_review_at=NOW - datetime.timedelta(hours=1),
        )
        result = sla_warnings.sweep(now=NOW)
        self.assertEqual(result["manager_review"], 0)

    def test_escalates_one_hop_to_the_company_admin(self):
        # A week back is well past the 24-business-hour escalation.
        self._stage(business_days_ago=7)
        sla_warnings.sweep(now=NOW)
        got = _recipients(NotificationEventType.SLA_MANAGER_REVIEW_OVERDUE)
        self.assertIn(self.manager.email, got)
        self.assertIn(self.company_admin.email, got)

    def test_does_not_escalate_at_the_first_threshold(self):
        # 2 days back = 16 business hours: past 8, under 24.
        self._stage(business_days_ago=2)
        sla_warnings.sweep(now=NOW)
        got = _recipients(NotificationEventType.SLA_MANAGER_REVIEW_OVERDUE)
        self.assertIn(self.manager.email, got)
        self.assertNotIn(self.company_admin.email, got)

    def test_the_customer_is_never_told_about_a_manager_review(self):
        """WAITING_MANAGER_REVIEW is provider-internal: staff said done
        and nobody has checked. The customer must not hear about work
        that has not been verified."""
        self._stage(business_days_ago=7)
        sla_warnings.sweep(now=NOW)
        got = _recipients(NotificationEventType.SLA_MANAGER_REVIEW_OVERDUE)
        self.assertNotIn(self.customer_user.email, got)

    def test_never_reaches_another_tenant(self):
        self._stage(business_days_ago=7)
        sla_warnings.sweep(now=NOW)
        got = _recipients(NotificationEventType.SLA_MANAGER_REVIEW_OVERDUE)
        self.assertNotIn(self.other_manager.email, got)
        self.assertNotIn(self.other_company_admin.email, got)


# ---------------------------------------------------------------------------
# 3. Should have started and has not
# ---------------------------------------------------------------------------

class NotStartedWarningTests(WarningTestBase):
    def test_warns_when_a_ticket_is_past_its_planned_start(self):
        Ticket.objects.filter(pk=self.ticket.pk).update(
            status=TicketStatus.OPEN,
            scheduled_start_at=NOW - datetime.timedelta(days=2),
        )
        result = sla_warnings.sweep(now=NOW)
        self.assertEqual(result["failed"], 0)
        self.assertGreaterEqual(result["not_started_tickets"], 1)
        # No crew is on it, so the hop fires straight away.
        self.assertIn(
            self.manager.email,
            _recipients(NotificationEventType.SLA_WORK_NOT_STARTED),
        )

    def test_silent_inside_the_grace(self):
        Ticket.objects.filter(pk=self.ticket.pk).update(
            status=TicketStatus.OPEN,
            scheduled_start_at=NOW - datetime.timedelta(hours=1),
        )
        result = sla_warnings.sweep(now=NOW)
        self.assertEqual(result["not_started_tickets"], 0)

    def test_started_work_is_not_warned_about(self):
        Ticket.objects.filter(pk=self.ticket.pk).update(
            status=TicketStatus.IN_PROGRESS,
            scheduled_start_at=NOW - datetime.timedelta(days=5),
        )
        result = sla_warnings.sweep(now=NOW)
        self.assertEqual(result["not_started_tickets"], 0)

    def test_extra_work_gets_its_own_clock(self):
        """The engine iterates Ticket only; an Extra Work with no spawned
        ticket had no clock at all before this sprint."""
        self.make_extra_work(
            provider_planned_date=(NOW - datetime.timedelta(days=3)).date()
        )
        result = sla_warnings.sweep(now=NOW)
        self.assertEqual(result["failed"], 0)
        self.assertGreaterEqual(result["not_started_extra_work"], 1)
        got = _recipients(NotificationEventType.SLA_WORK_NOT_STARTED)
        self.assertIn(self.company_admin.email, got)
        self.assertIn(self.manager.email, got)

    def test_extra_work_clock_ignores_the_customers_requested_date(self):
        """`preferred_date` is what the customer ASKED for; only
        `provider_planned_date` is what the provider committed to."""
        self.make_extra_work(
            preferred_date=(NOW - datetime.timedelta(days=10)).date(),
            provider_planned_date=None,
        )
        result = sla_warnings.sweep(now=NOW)
        self.assertEqual(result["not_started_extra_work"], 0)

    def test_extra_work_already_in_progress_is_not_warned_about(self):
        self.make_extra_work(
            status=ExtraWorkStatus.IN_PROGRESS,
            provider_planned_date=(NOW - datetime.timedelta(days=3)).date(),
        )
        result = sla_warnings.sweep(now=NOW)
        self.assertEqual(result["not_started_extra_work"], 0)

    def test_extra_work_warning_never_reaches_another_tenant(self):
        self.make_extra_work(
            provider_planned_date=(NOW - datetime.timedelta(days=3)).date()
        )
        sla_warnings.sweep(now=NOW)
        got = _recipients(NotificationEventType.SLA_WORK_NOT_STARTED)
        self.assertNotIn(self.other_company_admin.email, got)
        self.assertNotIn(self.other_manager.email, got)
        self.assertNotIn(self.customer_user.email, got)

    def test_extra_work_cooldown_is_keyed_on_the_extra_work(self):
        """The Extra Work has no ticket, so the cooldown can only key on
        the `NotificationLog.extra_work` FK this sprint added."""
        self.make_extra_work(
            provider_planned_date=(NOW - datetime.timedelta(days=3)).date()
        )
        first = sla_warnings.sweep(now=NOW)
        second = sla_warnings.sweep(now=NOW + datetime.timedelta(minutes=5))
        self.assertGreaterEqual(first["not_started_extra_work"], 1)
        self.assertEqual(second["not_started_extra_work"], 0)

    def test_warns_the_assigned_staff_before_the_manager(self):
        from tickets.models import TicketStaffAssignment

        staff = self.make_user("staff-w1b@example.com", "STAFF")
        Ticket.objects.filter(pk=self.ticket.pk).update(
            status=TicketStatus.OPEN,
            scheduled_start_at=NOW - datetime.timedelta(days=1),
        )
        TicketStaffAssignment.objects.create(
            ticket=Ticket.objects.get(pk=self.ticket.pk), user=staff
        )
        sla_warnings.sweep(now=NOW)
        got = _recipients(NotificationEventType.SLA_WORK_NOT_STARTED)
        self.assertIn(staff.email, got)
        # 1 day back = 8 business hours, under the 16-hour escalation.
        self.assertNotIn(self.manager.email, got)


# ---------------------------------------------------------------------------
# The task wrapper
# ---------------------------------------------------------------------------

class SweepTaskTests(WarningTestBase):
    def test_task_returns_counts_and_never_raises(self):
        result = sweep_sla_warnings(now=NOW.isoformat())
        self.assertIn("approval_cutoff", result)
        self.assertIn("manager_review", result)
        self.assertIn("not_started_tickets", result)
        self.assertIn("not_started_extra_work", result)
        self.assertEqual(result["failed"], 0)

    def test_task_swallows_a_sweep_failure(self):
        with patch(
            "sla.warnings.sweep", side_effect=RuntimeError("boom")
        ):
            result = sweep_sla_warnings(now=NOW.isoformat())
        self.assertEqual(result["failed"], 1)

    def test_quiet_when_there_is_nothing_to_warn_about(self):
        result = sweep_sla_warnings(now=NOW.isoformat())
        self.assertEqual(result["approval_cutoff"], 0)
        self.assertEqual(result["manager_review"], 0)
        self.assertEqual(result["not_started_tickets"], 0)
        self.assertEqual(result["not_started_extra_work"], 0)


class ResponsibleManagerRingTests(WarningTestBase):
    def test_explicit_per_ticket_manager_wins_over_the_building_ring(self):
        from notifications.services import ticket_responsible_manager_recipients
        from tickets.models import TicketManagerAssignment

        named = self.make_user("named-bm-w1b@example.com", "BUILDING_MANAGER")
        BuildingManagerAssignment.objects.create(
            user=named, building=self.building
        )
        TicketManagerAssignment.objects.create(ticket=self.ticket, user=named)
        got = {u.email for u in ticket_responsible_manager_recipients(self.ticket)}
        self.assertEqual(got, {named.email})

    def test_falls_back_to_the_building_ring_when_nobody_is_named(self):
        from notifications.services import ticket_responsible_manager_recipients

        got = {u.email for u in ticket_responsible_manager_recipients(self.ticket)}
        self.assertEqual(got, {self.manager.email})


@override_settings(SLA_WARN_COOLDOWN_HOURS=0)
class CooldownDisabledTests(WarningTestBase):
    def test_zero_hour_cooldown_still_only_sends_once_per_tick(self):
        """A zero cooldown is a foot-gun, not a crash: the per-tick dedupe
        by recipient id still holds inside one sweep."""
        Ticket.objects.filter(pk=self.ticket.pk).update(
            status=TicketStatus.OPEN,
            scheduled_start_at=NOW - datetime.timedelta(days=2),
        )
        sla_warnings.sweep(now=NOW)
        self.assertEqual(
            NotificationLog.objects.filter(
                event_type=NotificationEventType.SLA_WORK_NOT_STARTED,
                recipient_email=self.manager.email,
            ).count(),
            1,
        )
