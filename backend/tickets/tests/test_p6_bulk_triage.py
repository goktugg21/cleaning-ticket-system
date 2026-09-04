"""P-6 V4 — stale-work triage: park / close many tickets with ONE reason.

Every move goes through `apply_transition`, so the history rows carry
the reason, the override flag where the machine was jumped, and the
per-item breakdown never aborts the batch.
"""
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus, TicketStatusHistory

URL = "/api/tickets/bulk-triage/"


class BulkTriageTests(TenantFixtureMixin, APITestCase):
    def _history(self, ticket):
        return list(
            TicketStatusHistory.objects.filter(ticket=ticket).order_by("id")
        )

    def test_reason_is_required(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            URL,
            {"ticket_ids": [self.ticket.id], "action": "park", "reason": "  "},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("reason", response.data)

    def test_staff_and_customer_are_refused_at_the_door(self):
        staff = self.make_user("staff-triage@example.com", UserRole.STAFF)
        for user in (staff, self.customer_user):
            self.authenticate(user)
            response = self.client.post(
                URL,
                {"ticket_ids": [self.ticket.id], "action": "park", "reason": "junk"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_company_admin_parks_an_open_ticket_through_the_machine(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            URL,
            {"ticket_ids": [self.ticket.id], "action": "park", "reason": "test entry"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["succeeded"], 1)
        self.assertEqual(response.data["failed"], 0)
        self.assertEqual(response.data["results"][0]["status"], TicketStatus.ON_HOLD)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.ON_HOLD)
        # OPEN -> ACKNOWLEDGED -> ON_HOLD: two legs, each with the reason.
        rows = self._history(self.ticket)
        self.assertEqual(
            [(row.old_status, row.new_status) for row in rows[-2:]],
            [
                (TicketStatus.OPEN, TicketStatus.ACKNOWLEDGED),
                (TicketStatus.ACKNOWLEDGED, TicketStatus.ON_HOLD),
            ],
        )
        self.assertTrue(all(row.note == "test entry" for row in rows[-2:]))
        self.assertFalse(any(row.is_override for row in rows[-2:]))

    def test_park_twice_says_already_parked(self):
        self.authenticate(self.company_admin)
        self.client.post(
            URL,
            {"ticket_ids": [self.ticket.id], "action": "park", "reason": "junk"},
            format="json",
        )
        response = self.client.post(
            URL,
            {"ticket_ids": [self.ticket.id], "action": "park", "reason": "junk"},
            format="json",
        )
        self.assertEqual(response.data["failed"], 1)
        self.assertEqual(response.data["results"][0]["error"], "already_parked")

    def test_company_admin_cannot_close_an_open_ticket(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            URL,
            {"ticket_ids": [self.ticket.id], "action": "close", "reason": "junk"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["failed"], 1)
        self.assertEqual(response.data["results"][0]["error"], "no_path")
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.OPEN)

    def test_super_admin_closes_an_open_ticket_as_a_recorded_override(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            URL,
            {"ticket_ids": [self.ticket.id], "action": "close", "reason": "created twice"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["succeeded"], 1)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.CLOSED)
        last = self._history(self.ticket)[-1]
        self.assertEqual((last.old_status, last.new_status), (TicketStatus.OPEN, TicketStatus.CLOSED))
        self.assertTrue(last.is_override)
        self.assertEqual(last.override_reason, "created twice")

    def test_out_of_scope_ticket_is_not_found_and_does_not_abort_the_batch(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            URL,
            {
                "ticket_ids": [self.other_ticket.id, self.ticket.id],
                "action": "park",
                "reason": "junk",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["succeeded"], 1)
        self.assertEqual(response.data["failed"], 1)
        by_id = {row["id"]: row for row in response.data["results"]}
        self.assertEqual(by_id[self.other_ticket.id]["error"], "not_found")
        self.assertTrue(by_id[self.ticket.id]["ok"])
        self.other_ticket.refresh_from_db()
        self.assertEqual(self.other_ticket.status, TicketStatus.OPEN)

    def test_approved_ticket_closes_through_the_machine_without_override(self):
        approved = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Approved one",
            description="approved",
            status=TicketStatus.APPROVED,
        )
        self.authenticate(self.company_admin)
        response = self.client.post(
            URL,
            {"ticket_ids": [approved.id], "action": "close", "reason": "done and dusted"},
            format="json",
        )
        self.assertEqual(response.data["succeeded"], 1)
        approved.refresh_from_db()
        self.assertEqual(approved.status, TicketStatus.CLOSED)
        last = self._history(approved)[-1]
        self.assertFalse(last.is_override)
        self.assertEqual(last.note, "done and dusted")
