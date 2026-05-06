from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus

from sla import services
from sla.business_hours import add_business_seconds


class OnTicketCreatedTests(TenantFixtureMixin, TestCase):
    def test_active_ticket_gets_started_and_due_at(self):
        # self.ticket was created via TenantFixtureMixin.setUp, signals fired.
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.sla_started_at, self.ticket.created_at)
        self.assertIsNotNone(self.ticket.sla_due_at)
        self.assertEqual(self.ticket.sla_status, "ON_TRACK")

    def test_due_at_equals_24_business_hours_from_creation(self):
        self.ticket.refresh_from_db()
        expected = add_business_seconds(self.ticket.created_at, 24 * 3600)
        self.assertEqual(self.ticket.sla_due_at, expected)

    def test_pre_cutoff_ticket_marked_historical(self):
        with self.settings(SLA_ENGINE_START_DATE="2099-01-01"):
            ticket = Ticket.objects.create(
                company=self.company,
                building=self.building,
                customer=self.customer,
                created_by=self.customer_user,
                title="X",
                description="X",
            )
        ticket.refresh_from_db()
        self.assertEqual(ticket.sla_status, "HISTORICAL")
        self.assertIsNone(ticket.sla_due_at)
        self.assertIsNone(ticket.sla_started_at)


class ReconcileTests(TenantFixtureMixin, TestCase):
    def test_below_threshold_stays_on_track(self):
        self.ticket.refresh_from_db()
        changed = services.reconcile(self.ticket, now=self.ticket.sla_started_at)
        self.assertFalse(changed)
        self.assertEqual(self.ticket.sla_status, "ON_TRACK")

    def test_at_risk_when_above_threshold(self):
        self.ticket.refresh_from_db()
        # 85% of 24 business hours.
        now = add_business_seconds(self.ticket.sla_started_at, int(0.85 * 24 * 3600))
        changed = services.reconcile(self.ticket, now=now)
        self.assertTrue(changed)
        self.assertEqual(self.ticket.sla_status, "AT_RISK")

    def test_breached_when_past_due(self):
        self.ticket.refresh_from_db()
        now = add_business_seconds(self.ticket.sla_started_at, int(1.1 * 24 * 3600))
        changed = services.reconcile(self.ticket, now=now)
        self.assertTrue(changed)
        self.assertEqual(self.ticket.sla_status, "BREACHED")
        self.assertEqual(self.ticket.sla_first_breached_at, now)

    def test_first_breached_at_is_sticky(self):
        self.ticket.refresh_from_db()
        first_when = add_business_seconds(
            self.ticket.sla_started_at, int(1.1 * 24 * 3600)
        )
        services.reconcile(self.ticket, now=first_when)
        first = self.ticket.sla_first_breached_at
        # Reconcile again later — first_breached_at must not move.
        services.reconcile(
            self.ticket,
            now=add_business_seconds(self.ticket.sla_started_at, int(2.0 * 24 * 3600)),
        )
        self.assertEqual(self.ticket.sla_first_breached_at, first)

    def test_historical_never_reconciles(self):
        self.ticket.refresh_from_db()
        Ticket.objects.filter(pk=self.ticket.pk).update(sla_status="HISTORICAL")
        self.ticket.refresh_from_db()
        changed = services.reconcile(self.ticket, now=timezone.now())
        self.assertFalse(changed)
        self.assertEqual(self.ticket.sla_status, "HISTORICAL")

    def test_paused_ticket_does_not_reconcile(self):
        self.ticket.refresh_from_db()
        Ticket.objects.filter(pk=self.ticket.pk).update(
            sla_paused_at=timezone.now(),
            sla_status="AT_RISK",
        )
        self.ticket.refresh_from_db()
        # Even at 200% elapsed, paused tickets stay frozen.
        now = add_business_seconds(self.ticket.sla_started_at, int(2.0 * 24 * 3600))
        changed = services.reconcile(self.ticket, now=now)
        self.assertFalse(changed)
        self.assertEqual(self.ticket.sla_status, "AT_RISK")

    def test_terminal_status_does_not_reconcile(self):
        self.ticket.refresh_from_db()
        Ticket.objects.filter(pk=self.ticket.pk).update(status=TicketStatus.APPROVED)
        self.ticket.refresh_from_db()
        changed = services.reconcile(self.ticket, now=timezone.now())
        self.assertFalse(changed)


class TransitionTests(TenantFixtureMixin, TestCase):
    def test_pause_sets_sla_paused_at(self):
        self.ticket.refresh_from_db()
        when = self.ticket.sla_started_at + timedelta(hours=1)
        services.on_ticket_status_changed(
            self.ticket,
            TicketStatus.IN_PROGRESS,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            when=when,
        )
        self.assertEqual(self.ticket.sla_paused_at, when)

    def test_resume_extends_due_at_by_paused_business_seconds(self):
        self.ticket.refresh_from_db()
        # Simulate a 1h pause inside business hours.
        pause_at = add_business_seconds(self.ticket.sla_started_at, 3600)
        resume_at = add_business_seconds(self.ticket.sla_started_at, 2 * 3600)
        Ticket.objects.filter(pk=self.ticket.pk).update(sla_paused_at=pause_at)
        self.ticket.refresh_from_db()

        services.on_ticket_status_changed(
            self.ticket,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            TicketStatus.IN_PROGRESS,
            when=resume_at,
        )
        self.assertIsNone(self.ticket.sla_paused_at)
        self.assertEqual(self.ticket.sla_paused_seconds, 3600)
        expected_due = add_business_seconds(
            self.ticket.sla_started_at, 24 * 3600 + 3600
        )
        self.assertEqual(self.ticket.sla_due_at, expected_due)

    def test_complete_sets_sla_completed_at_and_status(self):
        self.ticket.refresh_from_db()
        when = self.ticket.sla_started_at + timedelta(hours=2)
        services.on_ticket_status_changed(
            self.ticket,
            TicketStatus.IN_PROGRESS,
            TicketStatus.APPROVED,
            when=when,
        )
        self.assertEqual(self.ticket.sla_status, "COMPLETED")
        self.assertEqual(self.ticket.sla_completed_at, when)

    def test_resume_then_complete_in_single_transition(self):
        # WAITING_CUSTOMER_APPROVAL → APPROVED: resume first, then complete.
        self.ticket.refresh_from_db()
        pause_at = self.ticket.sla_started_at + timedelta(hours=1)
        Ticket.objects.filter(pk=self.ticket.pk).update(sla_paused_at=pause_at)
        self.ticket.refresh_from_db()

        complete_at = pause_at + timedelta(minutes=15)
        services.on_ticket_status_changed(
            self.ticket,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            TicketStatus.APPROVED,
            when=complete_at,
        )
        self.assertIsNone(self.ticket.sla_paused_at)
        self.assertEqual(self.ticket.sla_status, "COMPLETED")
        self.assertEqual(self.ticket.sla_completed_at, complete_at)

    def test_reopen_restarts_clock_preserving_first_breached(self):
        self.ticket.refresh_from_db()
        breached_at = add_business_seconds(
            self.ticket.sla_started_at, int(1.5 * 24 * 3600)
        )
        Ticket.objects.filter(pk=self.ticket.pk).update(
            sla_first_breached_at=breached_at,
            sla_status="BREACHED",
            sla_completed_at=breached_at,
            status=TicketStatus.CLOSED,
        )
        self.ticket.refresh_from_db()

        reopen_at = breached_at + timedelta(hours=1)
        services.on_ticket_status_changed(
            self.ticket,
            TicketStatus.CLOSED,
            TicketStatus.REOPENED_BY_ADMIN,
            when=reopen_at,
        )
        self.assertEqual(self.ticket.sla_started_at, reopen_at)
        self.assertEqual(self.ticket.sla_paused_seconds, 0)
        self.assertIsNone(self.ticket.sla_completed_at)
        # Permanent breach marker preserved.
        self.assertEqual(self.ticket.sla_first_breached_at, breached_at)
        self.assertEqual(
            self.ticket.sla_due_at, add_business_seconds(reopen_at, 24 * 3600)
        )

    def test_historical_status_change_no_op(self):
        self.ticket.refresh_from_db()
        Ticket.objects.filter(pk=self.ticket.pk).update(sla_status="HISTORICAL")
        self.ticket.refresh_from_db()
        services.on_ticket_status_changed(
            self.ticket,
            TicketStatus.OPEN,
            TicketStatus.IN_PROGRESS,
            when=timezone.now(),
        )
        self.assertEqual(self.ticket.sla_status, "HISTORICAL")
