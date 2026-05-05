from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketPriority, TicketStatus


class TicketStatsTests(TenantFixtureMixin, APITestCase):
    def test_super_admin_sees_aggregate_across_companies(self):
        self.authenticate(self.super_admin)
        response = self.client.get("/api/tickets/stats/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 2)
        self.assertEqual(response.data["by_status"][TicketStatus.OPEN], 2)

    def test_company_admin_only_counts_own_company(self):
        self.authenticate(self.company_admin)
        response = self.client.get("/api/tickets/stats/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 1)
        self.assertNotIn(self.other_ticket.id, [self.ticket.id])  # sanity
        self.assertEqual(response.data["by_status"][TicketStatus.OPEN], 1)

    def test_customer_only_counts_linked_tickets(self):
        self.authenticate(self.customer_user)
        response = self.client.get("/api/tickets/stats/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 1)

    def test_my_open_excludes_closed_approved_rejected(self):
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Closed",
            description="closed ticket",
            status=TicketStatus.CLOSED,
        )
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Approved",
            description="approved ticket",
            status=TicketStatus.APPROVED,
        )

        self.authenticate(self.company_admin)
        response = self.client.get("/api/tickets/stats/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # 3 in company total: original OPEN + CLOSED + APPROVED.
        self.assertEqual(response.data["total"], 3)
        # my_open counts only the OPEN one.
        self.assertEqual(response.data["my_open"], 1)

    def test_urgent_counts_only_non_closed(self):
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Urgent open",
            description="hot",
            priority=TicketPriority.URGENT,
            status=TicketStatus.OPEN,
        )
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Urgent closed",
            description="historical",
            priority=TicketPriority.URGENT,
            status=TicketStatus.CLOSED,
        )

        self.authenticate(self.company_admin)
        response = self.client.get("/api/tickets/stats/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["urgent"], 1)
        self.assertEqual(response.data["by_priority"][TicketPriority.URGENT], 2)

    def test_waiting_customer_approval_count(self):
        self.move_ticket_to_customer_approval()
        self.authenticate(self.company_admin)
        response = self.client.get("/api/tickets/stats/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["waiting_customer_approval"], 1)
