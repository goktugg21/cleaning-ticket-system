from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin
from tickets.models import TicketMessage, TicketMessageType


class TicketScopingTests(TenantFixtureMixin, APITestCase):
    def test_super_admin_sees_all_tickets(self):
        self.authenticate(self.super_admin)
        response = self.client.get("/api/tickets/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.response_ids(response), {self.ticket.id, self.other_ticket.id})

    def test_company_admin_only_sees_own_company_tickets(self):
        self.authenticate(self.company_admin)
        response = self.client.get("/api/tickets/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.response_ids(response), {self.ticket.id})

    def test_building_manager_only_sees_assigned_building_tickets(self):
        self.authenticate(self.manager)
        response = self.client.get("/api/tickets/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.response_ids(response), {self.ticket.id})

    def test_customer_user_only_sees_linked_customer_tickets(self):
        self.authenticate(self.customer_user)
        response = self.client.get("/api/tickets/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.response_ids(response), {self.ticket.id})

    def test_cross_company_ticket_detail_is_not_visible(self):
        self.authenticate(self.company_admin)
        response = self.client.get(f"/api/tickets/{self.other_ticket.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_customer_cannot_view_internal_notes(self):
        TicketMessage.objects.create(
            ticket=self.ticket,
            author=self.manager,
            message="internal",
            message_type=TicketMessageType.INTERNAL_NOTE,
            is_hidden=True,
        )
        TicketMessage.objects.create(
            ticket=self.ticket,
            author=self.customer_user,
            message="public",
            message_type=TicketMessageType.PUBLIC_REPLY,
            is_hidden=False,
        )

        self.authenticate(self.customer_user)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/messages/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        messages = response.data.get("results", response.data)
        self.assertEqual([item["message"] for item in messages], ["public"])

    def test_out_of_scope_messages_are_404(self):
        self.authenticate(self.customer_user)
        response = self.client.get(f"/api/tickets/{self.other_ticket.id}/messages/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_customer_search_does_not_match_description_words(self):
        # Two tickets exist for the customer's company. A second ticket in
        # the customer's scope contains a unique word in its description.
        from tickets.models import Ticket

        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Routine cleaning",
            description="bluepenguin reference word",
        )

        self.authenticate(self.customer_user)
        response = self.client.get("/api/tickets/", {"search": "bluepenguin"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Customer must not be able to substring-search the description.
        results = response.data.get("results", response.data)
        self.assertEqual(results, [])

    def test_staff_search_still_matches_description_words(self):
        from tickets.models import Ticket

        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Routine cleaning",
            description="bluepenguin reference word",
        )

        self.authenticate(self.manager)
        response = self.client.get("/api/tickets/", {"search": "bluepenguin"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 1)
