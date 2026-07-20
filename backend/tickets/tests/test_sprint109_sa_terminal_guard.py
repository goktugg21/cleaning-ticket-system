"""
#109 Part C (audit P3-3) — the SUPER_ADMIN any-transition bypass
excludes CONVERTED_TO_EXTRA_WORK in BOTH directions.

Only the convert machinery (extra_work.conversion — a direct write in
its own atomic block) may enter that status, and it is terminal: no
transition leaves it, not even for a SUPER_ADMIN through the generic
status endpoint.
"""
from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin
from tickets.models import TicketStatus
from tickets.state_machine import can_transition


class SuperAdminConvertedTerminalGuardTests(TenantFixtureMixin, APITestCase):
    def test_sa_cannot_enter_converted_via_generic_endpoint(self):
        self.assertFalse(
            can_transition(
                self.super_admin,
                self.ticket,
                TicketStatus.CONVERTED_TO_EXTRA_WORK,
            )
        )
        self.authenticate(self.super_admin)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {"to_status": TicketStatus.CONVERTED_TO_EXTRA_WORK},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_sa_cannot_leave_converted(self):
        self.ticket.status = TicketStatus.CONVERTED_TO_EXTRA_WORK
        self.ticket.save(update_fields=["status", "updated_at"])
        self.assertFalse(
            can_transition(
                self.super_admin, self.ticket, TicketStatus.IN_PROGRESS
            )
        )
        self.authenticate(self.super_admin)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {"to_status": TicketStatus.OPEN},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_sa_normal_bypass_untouched_elsewhere(self):
        # OPEN -> CLOSED is not in ALLOWED_TRANSITIONS for anyone, but
        # the SA bypass still admits it (the pre-#109 behavior).
        self.assertTrue(
            can_transition(self.super_admin, self.ticket, TicketStatus.CLOSED)
        )
