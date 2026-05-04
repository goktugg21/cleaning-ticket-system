from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin
from tickets.models import TicketStatus


class TicketAssignmentTests(TenantFixtureMixin, APITestCase):
    def test_customer_cannot_call_assign_endpoint(self):
        self.authenticate(self.customer_user)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/assign/",
            {"assigned_to": self.manager.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_company_admin_can_assign_building_manager_in_scope(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/assign/",
            {"assigned_to": self.manager.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_to_id, self.manager.id)

    def test_assignee_must_belong_to_ticket_building(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/assign/",
            {"assigned_to": self.other_manager.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_customer_cannot_view_assignable_managers(self):
        self.authenticate(self.customer_user)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/assignable-managers/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_cannot_call_staff_only_status_transition(self):
        self.authenticate(self.customer_user)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {"to_status": TicketStatus.IN_PROGRESS},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_can_use_customer_approval_transition_in_scope(self):
        self.move_ticket_to_customer_approval()
        self.authenticate(self.customer_user)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {"to_status": TicketStatus.APPROVED},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
