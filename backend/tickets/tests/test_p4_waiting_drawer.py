"""
P-4 (Part E) — the "Wacht op klant" drawer acts.

The drawer used to be a READ list: work sent to the customer, nothing
for this reader to do. But the person who may answer on the customer's
behalf (the ticket detail's Advanced fold, W11 §1) had to open every
ticket to find that door. Each drawer row now says whether THIS reader
holds that authority — the SAME rule, moved to `override_authority` —
and the button runs the EXISTING override flow: required reason,
`is_override`, the audit row. Nothing new is permitted to anyone.

WHAT THESE TESTS PIN:
  * A waiting row carries `can_override_customer_decision`: True for a
    company admin in the ticket's company, False on a worker's own
    board, False on every row that is not waiting.
  * Approving on the customer's behalf through the existing status
    endpoint lands the ticket SETTLED on its own day column and takes it
    out of the chip — the same landing the customer's own answer gives.
  * The override history row carries `is_override` and the reason.
"""
from __future__ import annotations

from datetime import timedelta

from rest_framework import status
from rest_framework.test import APITestCase

from tickets.models import (
    StaffAssignmentSlotStatus,
    TicketStatus,
    TicketStatusHistory,
)
from tickets.work_plan import PLACEMENT_PLANNED

from .test_p3_schedule_truth import _P3Fixture

DAY = timedelta(days=1)


class WaitingDrawerActsTests(_P3Fixture, APITestCase):
    def _waiting(self, planned, *, title="Sent to the customer"):
        ticket = self.make_ticket(
            title, TicketStatus.WAITING_CUSTOMER_APPROVAL, scheduled=planned
        )
        self.make_slot(
            ticket,
            start=planned,
            slot_status=StaffAssignmentSlotStatus.COMPLETED,
        )
        return ticket

    def test_the_waiting_row_says_whether_this_reader_may_answer(self):
        ticket = self._waiting(self.today)
        payload = self.team()
        card, bucket = self.find(payload, f"ticket-{ticket.id}")
        self.assertEqual(bucket, "waiting_customer_entries")
        self.assertTrue(card["can_override_customer_decision"])
        # The same answer the ticket detail gives this reader.
        self.authenticate(self.company_admin)
        detail = self.client.get(f"/api/tickets/{ticket.id}/")
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertTrue(detail.data["actions"]["can_override_customer_decision"])

    def test_a_worker_never_gets_the_button(self):
        ticket = self._waiting(self.today)
        slot = ticket.staff_assignments.get()
        payload = self.own()
        card, bucket = self.find(payload, f"slot-{slot.id}")
        self.assertEqual(bucket, "waiting_customer_entries")
        self.assertFalse(card["can_override_customer_decision"])

    def test_rows_that_are_not_waiting_carry_false(self):
        ticket = self.make_ticket("Planned", TicketStatus.OPEN, scheduled=self.today)
        self.make_slot(ticket, start=self.today)
        payload = self.team()
        card, bucket = self.find(payload, f"ticket-{ticket.id}")
        self.assertEqual(bucket, "entries")
        self.assertFalse(card["can_override_customer_decision"])

    def test_approving_on_the_customers_behalf_lands_it_settled_on_its_day(self):
        planned = self.today - 2 * DAY if self.today.weekday() >= 2 else self.today
        ticket = self._waiting(planned)
        self.authenticate(self.company_admin)
        response = self.client.post(
            f"/api/tickets/{ticket.id}/status/",
            {
                "to_status": TicketStatus.APPROVED,
                "is_override": True,
                "override_reason": "Customer approved by phone",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        # "When the customer approves and the ticket closes": the machine
        # carries an approved ticket on to CLOSED. Either is a closed
        # shape for the board; what matters is where it lands.
        self.assertIn(
            response.data["status"], {TicketStatus.APPROVED, TicketStatus.CLOSED}
        )

        payload = self.team()
        card, bucket = self.find(payload, f"ticket-{ticket.id}")
        self.assertEqual(bucket, "entries")
        self.assertEqual(card["placement"], PLACEMENT_PLANNED)
        self.assertEqual(card["day"], planned.isoformat())
        self.assertTrue(card["viewer_settled"])
        self.assertEqual(payload["counts"]["waiting_customer"], 0)
        self.assertEqual(payload["waiting_customer_entries"], [])

        row = TicketStatusHistory.objects.filter(
            ticket=ticket, new_status=TicketStatus.APPROVED
        ).latest("id")
        self.assertTrue(row.is_override)
        self.assertEqual(row.override_reason, "Customer approved by phone")

    def test_the_reason_is_required(self):
        ticket = self._waiting(self.today)
        self.authenticate(self.company_admin)
        response = self.client.post(
            f"/api/tickets/{ticket.id}/status/",
            {"to_status": TicketStatus.APPROVED, "is_override": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("code"), "override_reason_required")
