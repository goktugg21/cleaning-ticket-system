from django.test import TestCase

from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus


class SignalIntegrationTests(TenantFixtureMixin, TestCase):
    def test_create_populates_sla_fields(self):
        ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Brand new",
            description="Brand new",
        )
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.sla_started_at)
        self.assertIsNotNone(ticket.sla_due_at)
        self.assertEqual(ticket.sla_status, "ON_TRACK")

    def test_status_change_to_waiting_customer_pauses(self):
        self.ticket.refresh_from_db()
        self.ticket.status = TicketStatus.WAITING_CUSTOMER_APPROVAL
        self.ticket.save(update_fields=["status", "updated_at"])
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.sla_paused_at)

    def test_status_change_back_from_waiting_resumes(self):
        self.ticket.refresh_from_db()
        self.ticket.status = TicketStatus.WAITING_CUSTOMER_APPROVAL
        self.ticket.save(update_fields=["status", "updated_at"])
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.sla_paused_at)
        self.ticket.status = TicketStatus.IN_PROGRESS
        self.ticket.save(update_fields=["status", "updated_at"])
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.sla_paused_at)

    def test_status_change_to_terminal_completes(self):
        self.ticket.refresh_from_db()
        self.ticket.status = TicketStatus.APPROVED
        self.ticket.save(update_fields=["status", "updated_at"])
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.sla_status, "COMPLETED")
        self.assertIsNotNone(self.ticket.sla_completed_at)

    def test_status_change_reopen_restarts_clock(self):
        self.ticket.refresh_from_db()
        self.ticket.status = TicketStatus.CLOSED
        self.ticket.save(update_fields=["status", "updated_at"])
        self.ticket.refresh_from_db()
        original_started = self.ticket.sla_started_at
        original_completed = self.ticket.sla_completed_at
        self.assertIsNotNone(original_completed)

        self.ticket.status = TicketStatus.REOPENED_BY_ADMIN
        self.ticket.save(update_fields=["status", "updated_at"])
        self.ticket.refresh_from_db()
        # sla_started_at moved forward.
        self.assertGreater(self.ticket.sla_started_at, original_started)
        self.assertIsNone(self.ticket.sla_completed_at)
        self.assertEqual(self.ticket.sla_status, "ON_TRACK")

    def test_save_without_status_change_does_not_touch_sla(self):
        self.ticket.refresh_from_db()
        original_due = self.ticket.sla_due_at
        self.ticket.title = "Renamed"
        self.ticket.save(update_fields=["title", "updated_at"])
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.sla_due_at, original_due)
