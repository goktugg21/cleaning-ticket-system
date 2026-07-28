from rest_framework import status
from rest_framework.test import APITestCase

from customers.models import Customer
from test_utils import TenantFixtureMixin


class CustomerCRUDTests(TenantFixtureMixin, APITestCase):
    URL = "/api/customers/"

    def detail_url(self, pk):
        return f"/api/customers/{pk}/"

    def reactivate_url(self, pk):
        return f"/api/customers/{pk}/reactivate/"

    def _create_payload(self, **overrides):
        payload = {
            "company": self.company.id,
            "building": self.building.id,
            "name": "New Customer",
            "contact_email": "new@example.com",
        }
        payload.update(overrides)
        return payload

    # ---- Create -----------------------------------------------------------

    def test_super_admin_can_create_customer_in_any_company(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.URL,
            self._create_payload(
                company=self.other_company.id,
                building=self.other_building.id,
                name="SA Cust",
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_company_admin_can_create_customer_in_own_company(self):
        self.authenticate(self.company_admin)
        response = self.client.post(self.URL, self._create_payload(name="CA Cust"), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_company_admin_cannot_create_customer_in_other_company(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            self.URL,
            self._create_payload(
                company=self.other_company.id,
                building=self.other_building.id,
                name="Hijack",
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_building_manager_cannot_create_customer(self):
        self.authenticate(self.manager)
        response = self.client.post(self.URL, self._create_payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_user_cannot_create_customer(self):
        self.authenticate(self.customer_user)
        response = self.client.post(self.URL, self._create_payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ---- Update -----------------------------------------------------------

    def test_company_admin_can_rename_customer_in_scope(self):
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.detail_url(self.customer.id), {"name": "Renamed"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.name, "Renamed")

    def test_company_admin_cannot_rename_customer_out_of_scope(self):
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.detail_url(self.other_customer.id), {"name": "Hijack"}, format="json"
        )
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

    # ---- Delete + reactivate ---------------------------------------------

    def test_delete_soft_deletes_customer(self):
        self.authenticate(self.super_admin)
        response = self.client.delete(self.detail_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        self.assertTrue(Customer.objects.filter(pk=self.customer.id).exists())

    def test_existing_tickets_on_deactivated_customer_remain_visible_to_staff(self):
        self.customer.is_active = False
        self.customer.save(update_fields=["is_active"])
        self.authenticate(self.super_admin)
        response = self.client.get("/api/tickets/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(self.ticket.id, self.response_ids(response))

    def test_super_admin_can_reactivate_customer(self):
        self.customer.is_active = False
        self.customer.save(update_fields=["is_active"])
        self.authenticate(self.super_admin)
        response = self.client.post(self.reactivate_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_active)

    def test_company_admin_cannot_reactivate_customer(self):
        self.customer.is_active = False
        self.customer.save(update_fields=["is_active"])
        self.authenticate(self.company_admin)
        response = self.client.post(self.reactivate_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ---- Retrieve of soft-deleted customers (CHANGE-17.6 regression) -----

    def test_super_admin_can_retrieve_inactive_customer(self):
        self.customer.is_active = False
        self.customer.save(update_fields=["is_active"])
        self.authenticate(self.super_admin)
        response = self.client.get(self.detail_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.customer.id)
        self.assertFalse(response.data["is_active"])

    def test_company_admin_cannot_retrieve_inactive_customer(self):
        self.customer.is_active = False
        self.customer.save(update_fields=["is_active"])
        self.authenticate(self.company_admin)
        response = self.client.get(self.detail_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class CustomerPaginationTests(TenantFixtureMixin, APITestCase):
    """Sprint 134 — see CompanyPaginationTests (companies/tests/test_crud.py)
    for the full rationale; identical fix (`UnboundedPagination`), same test
    shape, on CustomerViewSet."""

    URL = "/api/customers/"

    def test_more_than_200_customers_returned_in_one_page(self):
        Customer.objects.bulk_create(
            [
                Customer(
                    company=self.company,
                    building=self.building,
                    name=f"Bulk Customer {i}",
                    contact_email=f"bulk-customer-{i}@example.com",
                )
                for i in range(210)
            ]
        )
        self.authenticate(self.super_admin)
        response = self.client.get(self.URL, {"page_size": 200})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # 210 bulk + the 2 fixture customers (self.customer, self.other_customer).
        self.assertEqual(response.data["count"], 212)
        self.assertEqual(len(response.data["results"]), 212)
        self.assertIsNone(response.data["next"])
