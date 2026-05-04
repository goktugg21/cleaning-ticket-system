from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections
from django.test import TransactionTestCase
from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin
from tickets.models import Ticket


class TicketNumberApiTests(TenantFixtureMixin, APITestCase):
    def test_ticket_no_present_immediately_after_api_create(self):
        self.authenticate(self.customer_user)
        response = self.client.post("/api/tickets/", self.create_ticket_payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertRegex(response.data["ticket_no"], r"^TCK-\d{4}-\d{6}$")


class TicketNumberConcurrencyTests(TenantFixtureMixin, TransactionTestCase):
    reset_sequences = True

    def create_ticket(self, index):
        close_old_connections()
        try:
            ticket = Ticket.objects.create(
                company=self.company,
                building=self.building,
                customer=self.customer,
                created_by=self.customer_user,
                title=f"Concurrent {index}",
                description="Concurrent create",
            )
            return ticket.ticket_no
        finally:
            close_old_connections()

    def test_ticket_number_unique_under_concurrent_create(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            ticket_numbers = list(executor.map(self.create_ticket, range(8)))

        self.assertEqual(len(ticket_numbers), len(set(ticket_numbers)))
        for ticket_no in ticket_numbers:
            self.assertRegex(ticket_no, r"^TCK-\d{4}-\d{6}$")
