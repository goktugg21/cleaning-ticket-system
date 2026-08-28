"""
FE-2 (Addendum D §D.4) — the ticket-side `display_phase`.

The melding banner's mapping as a pure function (exhaustive over every
TicketStatus — a new status fails here, never renders blank), and the
field on rendered list + detail responses, per viewer.
"""
from __future__ import annotations

from rest_framework import status as http
from rest_framework.test import APITestCase

from tickets.display_phase import (
    TICKET_PHASES,
    ticket_display_phase,
)
from tickets.models import TicketStatus
from test_utils import TenantFixtureMixin


class TicketDisplayPhaseMappingTests(APITestCase):
    def test_the_mapping(self):
        expected = {
            TicketStatus.OPEN: "RECEIVED",
            TicketStatus.ACKNOWLEDGED: "PLANNED",
            TicketStatus.IN_PROGRESS: "IN_EXECUTION",
            TicketStatus.ON_HOLD: "IN_EXECUTION",
            TicketStatus.WAITING_MANAGER_REVIEW: "IN_EXECUTION",
            TicketStatus.REOPENED_BY_ADMIN: "IN_EXECUTION",
            TicketStatus.WAITING_CUSTOMER_APPROVAL: "WAITING_YOUR_APPROVAL",
            TicketStatus.APPROVED: "DONE",
            TicketStatus.CLOSED: "DONE",
            TicketStatus.REJECTED: "REJECTED",
            TicketStatus.CONVERTED_TO_EXTRA_WORK: "CONVERTED",
        }
        for status_v, phase in expected.items():
            with self.subTest(status=status_v):
                self.assertEqual(
                    ticket_display_phase(
                        status=status_v, viewer_is_customer=True
                    ),
                    phase,
                )

    def test_the_provider_reads_the_wait_from_their_side(self):
        self.assertEqual(
            ticket_display_phase(
                status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
                viewer_is_customer=False,
            ),
            "WAITING_CUSTOMER_APPROVAL",
        )

    def test_every_status_maps_and_unknown_raises(self):
        for choice, _label in TicketStatus.choices:
            for viewer in (True, False):
                with self.subTest(status=choice, viewer=viewer):
                    self.assertIn(
                        ticket_display_phase(
                            status=choice, viewer_is_customer=viewer
                        ),
                        TICKET_PHASES,
                    )
        with self.assertRaises(ValueError):
            ticket_display_phase(
                status="A_STATUS_NOBODY_MAPPED", viewer_is_customer=True
            )


class TicketDisplayPhaseSerializerTests(TenantFixtureMixin, APITestCase):
    def test_list_and_detail_carry_the_phase_per_viewer(self):
        self.ticket.status = TicketStatus.WAITING_CUSTOMER_APPROVAL
        self.ticket.save(update_fields=["status"])

        self.client.force_authenticate(self.customer_user)
        listed = self.client.get("/api/tickets/", {"customer": self.customer.id})
        self.assertEqual(listed.status_code, http.HTTP_200_OK, listed.data)
        row = next(
            r for r in listed.data["results"] if r["id"] == self.ticket.id
        )
        self.assertEqual(row["display_phase"], "WAITING_YOUR_APPROVAL")

        detail = self.client.get(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(detail.data["display_phase"], "WAITING_YOUR_APPROVAL")

        self.client.force_authenticate(self.company_admin)
        detail = self.client.get(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(
            detail.data["display_phase"], "WAITING_CUSTOMER_APPROVAL"
        )
