"""P-15 Part 5 — two S4 shape fixes, pinned.

1. The ticket status endpoint answers the FLAT machine-standard
   `{"detail", "code"}` body on an illegal transition — it was the one
   endpoint that wrapped both keys in one-element lists.
2. A worker READING their own ticket's crew roster gets a read-shaped
   refusal that points at their own surface — never "Staff cannot
   assign other staff to tickets." about an act that did not happen.
"""
from __future__ import annotations

from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import BuildingStaffVisibility
from test_utils import TenantFixtureMixin
from tickets.models import TicketStatus


class S4ShapeTests(TenantFixtureMixin, APITestCase):
    def test_illegal_transition_answers_the_flat_body(self):
        self.client.force_authenticate(self.company_admin)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {"to_status": TicketStatus.APPROVED},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIsInstance(response.data.get("detail"), str)
        self.assertIsInstance(response.data.get("code"), str)

    def test_a_workers_roster_read_is_refused_in_read_words(self):
        worker = self.make_user("s4-worker@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=worker, building=self.building
        )
        self.client.force_authenticate(worker)
        response = self.client.get(
            f"/api/tickets/{self.ticket.id}/staff-assignments/"
        )
        self.assertEqual(response.status_code, 403)
        detail = response.data.get("detail", "")
        self.assertNotIn("assign", detail.lower())
        self.assertIn("My schedule", detail)
