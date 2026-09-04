"""P-15 §0.3 — the on-behalf sign-off, said out loud.

The owner's C1 finding: auto-start work at a view_own-only building is
invisible to the customer — the WAITING_CUSTOMER_APPROVAL step can only
be settled by a provider override on their behalf, and the money landed
unbilled unseen. The 0.3 ruling: when the customer structurally cannot
sign off completion, the manager's check IS the sign-off, and the
screen says so ("Checked by {manager} — counts as approved (this
customer cannot approve online)"). Never a provider override in
silence.

Pinned here: the two backend facts the sentence is built from —
`approved_on_behalf` (the approval leg carried `is_override`) and
`customer_can_decide_online` (can ANY active customer-side account
reach the ticket at all).
"""
from __future__ import annotations

from rest_framework.test import APITestCase

from customers.models import Customer, CustomerBuildingMembership
from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus, TicketStatusHistory, TicketType


class OnBehalfSignoffTests(TenantFixtureMixin, APITestCase):
    def _detail(self, ticket):
        self.client.force_authenticate(self.company_admin)
        response = self.client.get(f"/api/tickets/{ticket.id}/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def _approve_on_behalf(self, ticket):
        ticket.status = TicketStatus.APPROVED
        ticket.save(update_fields=["status"])
        TicketStatusHistory.objects.create(
            ticket=ticket,
            old_status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            new_status=TicketStatus.APPROVED,
            changed_by=self.company_admin,
            is_override=True,
            override_reason="Customer cannot reach the system.",
        )

    def _unreachable_ticket(self):
        """A customer organisation with NO user accounts at all — the
        structural extreme of the C1 finding."""
        silent_customer = Customer.objects.create(
            company=self.company,
            building=self.building,
            name="Silent Customer",
            contact_email="nobody@example.com",
        )
        CustomerBuildingMembership.objects.create(
            customer=silent_customer, building=self.building
        )
        return Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=silent_customer,
            created_by=self.company_admin,
            title="Auto-start work nobody customer-side can see",
            description="x",
            type=TicketType.REQUEST,
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
        )

    def test_the_on_behalf_approval_is_named_and_explained(self):
        ticket = self._unreachable_ticket()
        self._approve_on_behalf(ticket)
        detail = self._detail(ticket)
        self.assertTrue(detail["approved_on_behalf"])
        self.assertIs(detail["customer_can_decide_online"], False)

    def test_a_reachable_customer_reads_true_while_waiting(self):
        """The fixture's customer_user holds a default access row
        (view_own) and created the ticket — they can settle it."""
        self.ticket.status = TicketStatus.WAITING_CUSTOMER_APPROVAL
        self.ticket.save(update_fields=["status"])
        detail = self._detail(self.ticket)
        self.assertFalse(detail["approved_on_behalf"])
        self.assertIs(detail["customer_can_decide_online"], True)

    def test_an_ordinary_ticket_answers_neither(self):
        """The reachability walk is paid only while the question is
        live — an OPEN ticket answers None."""
        detail = self._detail(self.ticket)
        self.assertFalse(detail["approved_on_behalf"])
        self.assertIsNone(detail["customer_can_decide_online"])

    def test_a_customer_own_approval_is_not_on_behalf(self):
        self.ticket.status = TicketStatus.APPROVED
        self.ticket.save(update_fields=["status"])
        TicketStatusHistory.objects.create(
            ticket=self.ticket,
            old_status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            new_status=TicketStatus.APPROVED,
            changed_by=self.customer_user,
            is_override=False,
        )
        detail = self._detail(self.ticket)
        self.assertFalse(detail["approved_on_behalf"])
