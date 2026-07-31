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

    # ---- Retrieve of soft-deleted buildings (CHANGE-17.6 regression) -----

    def test_super_admin_can_retrieve_inactive_building(self):
        self.building.is_active = False
        self.building.save(update_fields=["is_active"])
        self.authenticate(self.super_admin)
        response = self.client.get(self.detail_url(self.building.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.building.id)
        self.assertFalse(response.data["is_active"])

    def test_company_admin_cannot_retrieve_inactive_building(self):
        self.building.is_active = False
        self.building.save(update_fields=["is_active"])
        self.authenticate(self.company_admin)
        response = self.client.get(self.detail_url(self.building.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class BuildingPaginationTests(TenantFixtureMixin, APITestCase):
    """Sprint 135 — see CompanyPaginationTests (companies/tests/test_crud.py)
    for the full revert rationale; same shape, on BuildingViewSet: the
    default pagination correctly reports the true count and pages a
    >200-row tenant to completion when the CLIENT follows `next`. The
    picker call sites' truncation fix is now client-side exhaustive
    paging (frontend/src/api/admin.ts::listAllBuildings), not this
    ViewSet's own `pagination_class`."""

    URL = "/api/buildings/"

    def test_more_than_200_buildings_fully_retrievable_by_a_paging_client(self):
        Building.objects.bulk_create(
            [
                Building(
                    company=self.company,
                    name=f"Bulk Building {i}",
                    address=f"Bulk Street {i}",
                )
                for i in range(210)
            ]
        )
        self.authenticate(self.super_admin)

        response = self.client.get(self.URL, {"page_size": 200})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # 210 bulk + the 2 fixture buildings (self.building, self.other_building).
        self.assertEqual(response.data["count"], 212)
        self.assertEqual(len(response.data["results"]), 200)
        self.assertIsNotNone(response.data["next"])

        seen_ids = {row["id"] for row in response.data["results"]}
        next_url = response.data["next"]
        for _ in range(10):  # hard iteration cap, mirrors listAllBuildings's own
            response = self.client.get(next_url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            seen_ids.update(row["id"] for row in response.data["results"])
            next_url = response.data["next"]
            if not next_url:
                break
        else:
            self.fail("Did not reach the end of pagination within 10 pages.")

        self.assertEqual(len(seen_ids), 212)
