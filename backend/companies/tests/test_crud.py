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

    # ---- Retrieve of soft-deleted companies (CHANGE-17.6 regression) -----

    def test_super_admin_can_retrieve_inactive_company(self):
        self.company.is_active = False
        self.company.save(update_fields=["is_active"])
        self.authenticate(self.super_admin)
        response = self.client.get(self.detail_url(self.company.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.company.id)
        self.assertFalse(response.data["is_active"])

    def test_company_admin_cannot_retrieve_inactive_company(self):
        self.company.is_active = False
        self.company.save(update_fields=["is_active"])
        self.authenticate(self.company_admin)
        response = self.client.get(self.detail_url(self.company.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class CompanyPaginationTests(TenantFixtureMixin, APITestCase):
    """Sprint 134 gave CompanyViewSet `pagination_class = UnboundedPagination`
    to stop the admin picker call sites' `page_size: 200` silently clamping
    to 200 for any tenant exceeding it. Sprint 135 REVERTED that — it applies
    to EVERY caller, not just the pickers, and `CustomersAdminPage`'s
    sibling `CompaniesAdminPage`-style list UI has real pagination (page
    state + prev/next), which `page_size_query_param=None` + a fixed 10000
    page permanently broke (`next` always null). The real fix is client-
    side exhaustive paging for the PICKERS specifically (Sprint 120's own
    pattern — see frontend/src/api/admin.ts::listAllCompanies), leaving the
    default `StandardResultsSetPagination` (200/page max) untouched here.
    This test asserts the end-state that fix depends on: the default
    pagination correctly reports the true count and pages a >200-row
    tenant to completion when the CLIENT follows `next`."""

    URL = "/api/companies/"

    def test_more_than_200_companies_fully_retrievable_by_a_paging_client(self):
        Company.objects.bulk_create(
            [Company(name=f"Bulk {i}", slug=f"bulk-{i}") for i in range(210)]
        )
        self.authenticate(self.super_admin)

        response = self.client.get(self.URL, {"page_size": 200})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # 210 bulk + the 2 fixture companies (self.company, self.other_company).
        self.assertEqual(response.data["count"], 212)
        # The default page cap is genuinely back in effect — one page
        # cannot hold all 212 rows. (Sprint 134's UnboundedPagination
        # would have returned all 212 here with next=None; that's exactly
        # the override this test now proves is gone.)
        self.assertEqual(len(response.data["results"]), 200)
        self.assertIsNotNone(response.data["next"])

        seen_ids = {row["id"] for row in response.data["results"]}
        next_url = response.data["next"]
        for _ in range(10):  # hard iteration cap, mirrors listAllCompanies's own
            response = self.client.get(next_url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            seen_ids.update(row["id"] for row in response.data["results"])
            next_url = response.data["next"]
            if not next_url:
                break
        else:
            self.fail("Did not reach the end of pagination within 10 pages.")

        # A client that pages exhaustively (the actual fix — see
        # frontend/src/api/admin.ts::listAllCompanies) retrieves every row.
        self.assertEqual(len(seen_ids), 212)
