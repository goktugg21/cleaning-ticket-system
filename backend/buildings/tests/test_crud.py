from rest_framework import status
from rest_framework.test import APITestCase

from buildings.models import Building
from test_utils import TenantFixtureMixin


class BuildingCRUDTests(TenantFixtureMixin, APITestCase):
    URL = "/api/buildings/"

    def detail_url(self, pk):
        return f"/api/buildings/{pk}/"

    def reactivate_url(self, pk):
        return f"/api/buildings/{pk}/reactivate/"

    # ---- Create -----------------------------------------------------------

    def test_super_admin_can_create_building_in_any_company(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.URL,
            {"company": self.other_company.id, "name": "SA Building"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_company_admin_can_create_building_in_own_company(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            self.URL,
            {"company": self.company.id, "name": "CA Building"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_company_admin_cannot_create_building_in_other_company(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            self.URL,
            {"company": self.other_company.id, "name": "Hijack"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_building_manager_cannot_create_building(self):
        self.authenticate(self.manager)
        response = self.client.post(
            self.URL,
            {"company": self.company.id, "name": "BM"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_user_cannot_create_building(self):
        self.authenticate(self.customer_user)
        response = self.client.post(
            self.URL,
            {"company": self.company.id, "name": "CU"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ---- Update -----------------------------------------------------------

    def test_company_admin_can_rename_building_in_scope(self):
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.detail_url(self.building.id), {"name": "Renamed"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.building.refresh_from_db()
        self.assertEqual(self.building.name, "Renamed")

    def test_company_admin_cannot_rename_building_out_of_scope(self):
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.detail_url(self.other_building.id), {"name": "Hijack"}, format="json"
        )
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

    # ---- Delete + reactivate ---------------------------------------------

    def test_delete_soft_deletes_building(self):
        self.authenticate(self.super_admin)
        response = self.client.delete(self.detail_url(self.building.id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.building.refresh_from_db()
        self.assertFalse(self.building.is_active)
        self.assertTrue(Building.objects.filter(pk=self.building.id).exists())

    def test_existing_tickets_on_deactivated_building_remain_visible_to_staff(self):
        # CHANGE-6 contract: scope_tickets_for is unchanged. Soft-deleting a
        # building must NOT hide tickets that already exist on it from staff.
        self.building.is_active = False
        self.building.save(update_fields=["is_active"])
        self.authenticate(self.super_admin)
        response = self.client.get("/api/tickets/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(self.ticket.id, self.response_ids(response))

    def test_super_admin_can_reactivate_building(self):
        self.building.is_active = False
        self.building.save(update_fields=["is_active"])
        self.authenticate(self.super_admin)
        response = self.client.post(self.reactivate_url(self.building.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.building.refresh_from_db()
        self.assertTrue(self.building.is_active)

    def test_company_admin_cannot_reactivate_building(self):
        self.building.is_active = False
        self.building.save(update_fields=["is_active"])
        self.authenticate(self.company_admin)
        response = self.client.post(self.reactivate_url(self.building.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
