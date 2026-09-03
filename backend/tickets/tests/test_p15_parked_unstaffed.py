"""P-15 — an unstaffed ON_HOLD job is on the parked lane, not nowhere.

P-14's S3 finding (ticket 309, live): `_ticket_source` gates the whole
team board on `Exists(non-cancelled slot)`, the undated lane excludes
ON_HOLD by design, so an on-hold job whose crew was pulled vanished
from the ENTIRE planning surface — counts.parked said 0 while the job
existed. The fix (`_ticket_parked_source`): the parked list and its
count read their own staffed-or-not source; the columns and every other
chip keep the staffed membership deliberately.
"""
from __future__ import annotations

from rest_framework.test import APITestCase

from tickets.models import StaffAssignmentSlotStatus, TicketStatus
from tickets.tests.test_sprint179a_work_plan import WorkPlanFixture


class ParkedUnstaffedTests(WorkPlanFixture, APITestCase):
    def test_an_unstaffed_on_hold_job_is_in_the_parked_lane(self):
        ticket = self.make_ticket("Parked, crew pulled", TicketStatus.ON_HOLD)
        payload = self.get_plan(self.company_admin, scope="company")
        key = f"ticket-{ticket.id}"
        parked = {e["key"] for e in payload["parked_entries"]}
        self.assertIn(key, parked)
        self.assertEqual(payload["counts"]["parked"], 1)
        # Nowhere else: the columns keep the staffed membership.
        for bucket in ("entries", "undated_entries", "overdue_entries"):
            self.assertNotIn(
                key, {e["key"] for e in payload.get(bucket, [])}, bucket
            )

    def test_a_cancelled_crew_counts_as_unstaffed(self):
        ticket = self.make_ticket("Parked, slot cancelled", TicketStatus.ON_HOLD)
        self.make_slot(
            ticket, slot_status=StaffAssignmentSlotStatus.CANCELLED
        )
        payload = self.get_plan(self.company_admin, scope="company")
        parked = {e["key"] for e in payload["parked_entries"]}
        self.assertIn(f"ticket-{ticket.id}", parked)
        self.assertEqual(payload["counts"]["parked"], 1)

    def test_a_staffed_parked_job_still_shows_once(self):
        ticket = self.make_ticket("Parked, still crewed", TicketStatus.ON_HOLD)
        self.make_slot(ticket)
        payload = self.get_plan(self.company_admin, scope="company")
        keys = [e["key"] for e in payload["parked_entries"]]
        self.assertEqual(keys.count(f"ticket-{ticket.id}"), 1)
        self.assertEqual(payload["counts"]["parked"], 1)
