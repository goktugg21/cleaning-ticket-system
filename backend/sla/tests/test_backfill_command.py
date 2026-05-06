from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus


class BackfillCommandTests(TenantFixtureMixin, TestCase):
    def _make_ticket(self, **overrides):
        defaults = dict(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="X",
            description="X",
        )
        defaults.update(overrides)
        return Ticket.objects.create(**defaults)

    def _force_created_at(self, ticket, when):
        Ticket.objects.filter(pk=ticket.pk).update(created_at=when)
        ticket.refresh_from_db()
        return ticket

    def test_pre_cutoff_marked_historical(self):
        # Force a ticket's created_at into 2020.
        old = self._make_ticket()
        self._force_created_at(old, timezone.now() - timedelta(days=2000))
        out = StringIO()
        call_command("sla_backfill", stdout=out)
        old.refresh_from_db()
        self.assertEqual(old.sla_status, "HISTORICAL")

    def test_active_terminal_marked_completed(self):
        ticket = self._make_ticket()
        Ticket.objects.filter(pk=ticket.pk).update(
            status=TicketStatus.APPROVED,
            resolved_at=timezone.now(),
            sla_status="ON_TRACK",
            sla_due_at=None,
            sla_started_at=None,
        )
        ticket.refresh_from_db()
        out = StringIO()
        call_command("sla_backfill", stdout=out)
        ticket.refresh_from_db()
        self.assertEqual(ticket.sla_status, "COMPLETED")
        self.assertIsNotNone(ticket.sla_completed_at)
        self.assertIsNotNone(ticket.sla_started_at)

    def test_active_non_terminal_gets_due_at(self):
        ticket = self._make_ticket()
        # Reset SLA fields to simulate a ticket from before the engine wired up.
        Ticket.objects.filter(pk=ticket.pk).update(
            sla_status="ON_TRACK",
            sla_due_at=None,
            sla_started_at=None,
        )
        out = StringIO()
        call_command("sla_backfill", stdout=out)
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.sla_due_at)
        self.assertEqual(ticket.sla_started_at, ticket.created_at)
        self.assertIn(ticket.sla_status, {"ON_TRACK", "AT_RISK", "BREACHED"})

    def test_dry_run_does_not_modify_db(self):
        ticket = self._make_ticket()
        Ticket.objects.filter(pk=ticket.pk).update(
            sla_status="ON_TRACK",
            sla_due_at=None,
            sla_started_at=None,
        )
        ticket.refresh_from_db()
        out = StringIO()
        call_command("sla_backfill", "--dry-run", stdout=out)
        ticket.refresh_from_db()
        self.assertIsNone(ticket.sla_due_at)
        self.assertIsNone(ticket.sla_started_at)
        self.assertIn("(dry run)", out.getvalue())
