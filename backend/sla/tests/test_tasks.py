from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus

from sla.tasks import reconcile_sla_states


class ReconcileTaskTests(TenantFixtureMixin, TestCase):
    def test_updates_at_risk_and_breached(self):
        # self.ticket is fresh; force its sla_started_at deep into the past.
        Ticket.objects.filter(pk=self.ticket.pk).update(
            sla_started_at=timezone.now() - timedelta(days=10),
            sla_status="ON_TRACK",
        )
        result = reconcile_sla_states()
        self.assertGreaterEqual(result["checked"], 1)
        self.assertGreaterEqual(result["updated"], 1)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.sla_status, "BREACHED")
        self.assertIsNotNone(self.ticket.sla_first_breached_at)

    def test_skips_historical(self):
        Ticket.objects.filter(pk=self.ticket.pk).update(sla_status="HISTORICAL")
        before = Ticket.objects.get(pk=self.ticket.pk).sla_status
        reconcile_sla_states()
        after = Ticket.objects.get(pk=self.ticket.pk).sla_status
        self.assertEqual(before, "HISTORICAL")
        self.assertEqual(after, "HISTORICAL")

    def test_skips_terminal_status(self):
        Ticket.objects.filter(pk=self.ticket.pk).update(
            status=TicketStatus.APPROVED,
            sla_started_at=timezone.now() - timedelta(days=10),
            sla_status="COMPLETED",
        )
        reconcile_sla_states()
        self.ticket.refresh_from_db()
        # Stayed COMPLETED (not flipped to BREACHED).
        self.assertEqual(self.ticket.sla_status, "COMPLETED")

    def test_idempotent(self):
        Ticket.objects.filter(pk=self.ticket.pk).update(
            sla_started_at=timezone.now() - timedelta(days=10),
            sla_status="ON_TRACK",
        )
        first = reconcile_sla_states()
        second = reconcile_sla_states()
        # First run flips to BREACHED; second run sees no work.
        self.assertGreaterEqual(first["updated"], 1)
        self.assertEqual(second["updated"], 0)
