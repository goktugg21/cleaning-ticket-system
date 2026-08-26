"""W-N1 §3 — the Work Plan payload carries parts.

The gap this closes was found by reading `_entry_from_slot`: it built the
ticket entry by hand and emitted thirty keys, none of them the slot's
sub-task, so the front end had nothing to render even though
`TicketStaffAssignment.sub_task` had existed since W26.3.

What matters here is not that the key appears — it is that it obeys the
SAME scope the rest of the row already does. A staff member must see
their own parts and nobody else's.
"""
from __future__ import annotations

from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from test_utils import TenantFixtureMixin
from tickets.models import SubTask, TicketStaffAssignment, TicketStatus


class WorkPlanPartsTests(TenantFixtureMixin, APITestCase):
    URL = "/api/tickets/work-plan/"

    def setUp(self):
        super().setUp()
        self.ticket.status = TicketStatus.IN_PROGRESS
        self.ticket.save(update_fields=["status"])
        self.windows = SubTask.objects.create(
            ticket=self.ticket, title="Windows"
        )
        self.kitchen = SubTask.objects.create(
            ticket=self.ticket, title="Kitchen"
        )
        self.ayse = self._staff("wn1-ayse@example.com")
        self.bora = self._staff("wn1-bora@example.com")
        # Each has a base slot and one part; different parts.
        self._slot(self.ayse, None)
        self._slot(self.ayse, self.windows)
        self._slot(self.bora, None)
        self._slot(self.bora, self.kitchen)

    def _staff(self, email):
        user = self.make_user(email, UserRole.STAFF)
        StaffProfile.objects.create(user=user)
        BuildingStaffVisibility.objects.create(user=user, building=self.building)
        return user

    def _slot(self, user, sub_task):
        return TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=user, sub_task=sub_task,
            assigned_by=self.company_admin,
        )

    def _rows(self, payload):
        # W-FIX1 E2 — these slots carry no date, so they live in the
        # undated lane rather than on today's column; the parts travel
        # with the row wherever it sits.
        return (
            payload["entries"]
            + payload["overdue_entries"]
            + payload["undated_entries"]
        )

    def _titles(self, payload):
        out = set()
        for entry in self._rows(payload):
            for part in entry.get("parts", []):
                out.add(part["title"])
        return out

    def test_staff_sees_only_their_own_parts(self):
        self.authenticate(self.ayse)
        payload = self.client.get(self.URL).data
        titles = self._titles(payload)
        self.assertIn("Windows", titles)
        self.assertNotIn(
            "Kitchen", titles, "a staff member saw another person's part"
        )

    def test_every_entry_carries_a_parts_list(self):
        """Never null — the renderer should not have to ask."""
        self.authenticate(self.ayse)
        payload = self.client.get(self.URL).data
        rows = self._rows(payload)
        self.assertTrue(rows, "fixture produced no work-plan rows")
        for entry in rows:
            self.assertIsInstance(entry.get("parts"), list)

    def test_a_manager_sees_the_parts_of_everyone_on_the_ticket(self):
        self.authenticate(self.company_admin)
        payload = self.client.get(self.URL, {"scope": "company"}).data
        titles = self._titles(payload)
        self.assertIn("Windows", titles)
        self.assertIn("Kitchen", titles)
