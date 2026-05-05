from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin


class InactiveScopingTests(TenantFixtureMixin, APITestCase):
    def test_inactive_building_hidden_from_company_admin_list(self):
        self.building.is_active = False
        self.building.save(update_fields=["is_active"])

        self.authenticate(self.company_admin)
        response = self.client.get("/api/buildings/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.response_ids(response), set())

    def test_inactive_building_still_visible_to_super_admin(self):
        self.building.is_active = False
        self.building.save(update_fields=["is_active"])

        self.authenticate(self.super_admin)
        response = self.client.get("/api/buildings/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(self.building.id, self.response_ids(response))

    def test_inactive_customer_hidden_from_customer_user_list(self):
        self.customer.is_active = False
        self.customer.save(update_fields=["is_active"])

        self.authenticate(self.customer_user)
        response = self.client.get("/api/customers/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.response_ids(response), set())

    def test_inactive_company_hidden_from_company_admin_list(self):
        self.company.is_active = False
        self.company.save(update_fields=["is_active"])

        self.authenticate(self.company_admin)
        response = self.client.get("/api/companies/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.response_ids(response), set())

    def test_create_ticket_against_inactive_building_is_rejected(self):
        self.building.is_active = False
        self.building.save(update_fields=["is_active"])

        self.authenticate(self.super_admin)
        response = self.client.post(
            "/api/tickets/",
            self.create_ticket_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("building", response.data)

    def test_create_ticket_against_inactive_customer_is_rejected(self):
        self.customer.is_active = False
        self.customer.save(update_fields=["is_active"])

        self.authenticate(self.super_admin)
        response = self.client.post(
            "/api/tickets/",
            self.create_ticket_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("customer", response.data)

    def test_existing_tickets_on_inactive_building_remain_visible_to_staff(self):
        # Audit/staff use case: archived building still has prior tickets to read.
        self.building.is_active = False
        self.building.save(update_fields=["is_active"])

        self.authenticate(self.super_admin)
        response = self.client.get("/api/tickets/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(self.ticket.id, self.response_ids(response))
