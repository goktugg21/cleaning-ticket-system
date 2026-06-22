from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketType


class CustomerMeldingCoercionTests(TenantFixtureMixin, APITestCase):
    """M7.1 — a ticket created by a CUSTOMER_USER is always a "melding"
    (type=REPORT), regardless of the type sent on the wire. The coercion is
    server-side (TicketViewSet.perform_create) so the M6 meldingen split
    (meldingen = REPORT) holds even against a raw API call. Provider-created
    types are NOT coerced.

    Reuses the TenantFixtureMixin customer-create chain (CustomerUserMembership
    + CustomerUserBuildingAccess granting customer.ticket.create), the same
    setup test_ticket_no.py relies on for a successful customer POST.
    """

    def test_customer_complaint_is_coerced_to_report(self):
        self.authenticate(self.customer_user)
        response = self.client.post(
            "/api/tickets/",
            self.create_ticket_payload(type="COMPLAINT"),
            format="json",
        )

        # The customer POST must succeed before we assert the coercion.
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["type"], TicketType.REPORT)
        ticket = Ticket.objects.get(id=response.data["id"])
        self.assertEqual(ticket.type, TicketType.REPORT)

    def test_customer_report_stays_report(self):
        self.authenticate(self.customer_user)
        response = self.client.post(
            "/api/tickets/",
            self.create_ticket_payload(type="REPORT"),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["type"], TicketType.REPORT)
        ticket = Ticket.objects.get(id=response.data["id"])
        self.assertEqual(ticket.type, TicketType.REPORT)

    def test_provider_complaint_is_not_coerced(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            "/api/tickets/",
            self.create_ticket_payload(type="COMPLAINT"),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["type"], TicketType.COMPLAINT)
        ticket = Ticket.objects.get(id=response.data["id"])
        self.assertEqual(ticket.type, TicketType.COMPLAINT)
