from rest_framework import status
from rest_framework.test import APITestCase

from companies.models import Company
from test_utils import TenantFixtureMixin


class CompanyCRUDTests(TenantFixtureMixin, APITestCase):
    URL = "/api/companies/"

    def detail_url(self, pk):
        return f"/api/companies/{pk}/"

    def reactivate_url(self, pk):
        return f"/api/companies/{pk}/reactivate/"

    # ---- Create -----------------------------------------------------------

    def test_super_admin_can_create_company_with_auto_slug(self):
        self.authenticate(self.super_admin)
        response = self.client.post(self.URL, {"name": "Brand New Co"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["slug"], "brand-new-co")

    def test_slug_collision_gets_suffixed(self):
        Company.objects.create(name="Echo", slug="echo")
        self.authenticate(self.super_admin)
        response = self.client.post(self.URL, {"name": "Echo"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["slug"], "echo-2")

    def test_explicit_slug_overrides_auto_generation(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.URL, {"name": "Anything", "slug": "custom-slug"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["slug"], "custom-slug")

    def test_company_admin_cannot_create_company(self):
        self.authenticate(self.company_admin)
        response = self.client.post(self.URL, {"name": "Forbidden"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ---- Update -----------------------------------------------------------

    def test_company_admin_can_rename_own_company(self):
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.detail_url(self.company.id), {"name": "Renamed"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.company.refresh_from_db()
        self.assertEqual(self.company.name, "Renamed")

    def test_company_admin_cannot_rename_other_company(self):
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.detail_url(self.other_company.id), {"name": "Hijack"}, format="json"
        )
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

    def test_rename_does_not_auto_change_slug(self):
        original_slug = self.company.slug
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.detail_url(self.company.id), {"name": "Totally Different Name"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.company.refresh_from_db()
        self.assertEqual(self.company.slug, original_slug)

    def test_super_admin_can_change_slug_explicitly(self):
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.detail_url(self.company.id), {"slug": "new-slug"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.company.refresh_from_db()
        self.assertEqual(self.company.slug, "new-slug")

    # ---- Delete + reactivate ---------------------------------------------

    def test_delete_soft_deletes_company(self):
        self.authenticate(self.super_admin)
        response = self.client.delete(self.detail_url(self.company.id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.company.refresh_from_db()
        self.assertFalse(self.company.is_active)
        # Row still exists.
        self.assertTrue(Company.objects.filter(pk=self.company.id).exists())

    def test_super_admin_can_reactivate_company(self):
        self.company.is_active = False
        self.company.save(update_fields=["is_active"])
        self.authenticate(self.super_admin)
        response = self.client.post(self.reactivate_url(self.company.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.company.refresh_from_db()
        self.assertTrue(self.company.is_active)

    def test_company_admin_cannot_reactivate_company(self):
        self.company.is_active = False
        self.company.save(update_fields=["is_active"])
        self.authenticate(self.company_admin)
        response = self.client.post(self.reactivate_url(self.company.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ---- Read regression for CHANGE-6 ------------------------------------

    def test_deactivated_company_hidden_from_company_admin_list(self):
        self.company.is_active = False
        self.company.save(update_fields=["is_active"])
        self.authenticate(self.company_admin)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self.response_ids(response)
        self.assertNotIn(self.company.id, ids)

    def test_deactivated_company_visible_to_super_admin_list(self):
        self.company.is_active = False
        self.company.save(update_fields=["is_active"])
        self.authenticate(self.super_admin)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self.response_ids(response)
        self.assertIn(self.company.id, ids)
