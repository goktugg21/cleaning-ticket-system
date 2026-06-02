"""
Sprint 14G — Codex P2: a BUILDING_MANAGER reading a multi-building
customer's contacts must not see building associations (or whole
contacts) for buildings outside their `building_ids_for()` scope.

Fixture: Company A has Building A (managed by `self.manager`) and a new
Building A2 (NOT managed by `self.manager`), both linked to the same
`self.customer`. Contacts exercise every link shape:
  * c_a_only      — linked only to A (managed)          -> visible, [A]
  * c_b_only      — linked only to A2 (unmanaged)       -> HIDDEN
  * c_ab          — linked to A + A2                    -> visible, [A]
  * c_legacy_b    — legacy `building` = A2 + links A/A2 -> visible, building redacted, [A]
  * c_no_links    — no building links (customer-level)  -> visible, []
SUPER_ADMIN / COMPANY_ADMIN see everything (no narrowing).
"""
from rest_framework import status
from rest_framework.test import APITestCase

from buildings.models import Building
from customers.models import (
    Contact,
    ContactBuildingLink,
    CustomerBuildingMembership,
)
from test_utils import TenantFixtureMixin


class _BMContactScopeFixture(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # A second building under Company A, linked to self.customer,
        # NOT managed by self.manager (who manages only self.building).
        self.building_a2 = Building.objects.create(
            company=self.company, name="Building A2", address="Main Street 2"
        )
        CustomerBuildingMembership.objects.create(
            customer=self.customer, building=self.building_a2
        )

        self.c_a_only = Contact.objects.create(
            customer=self.customer, full_name="A only"
        )
        ContactBuildingLink.objects.create(
            contact=self.c_a_only, building=self.building
        )

        self.c_b_only = Contact.objects.create(
            customer=self.customer, full_name="B only"
        )
        ContactBuildingLink.objects.create(
            contact=self.c_b_only, building=self.building_a2
        )

        self.c_ab = Contact.objects.create(
            customer=self.customer, full_name="A and B"
        )
        ContactBuildingLink.objects.create(
            contact=self.c_ab, building=self.building
        )
        ContactBuildingLink.objects.create(
            contact=self.c_ab, building=self.building_a2
        )

        # Legacy single-building anchor on an UNMANAGED building + a
        # managed link — exercises the `building` field redaction.
        self.c_legacy_b = Contact.objects.create(
            customer=self.customer,
            full_name="Legacy B anchor",
            building=self.building_a2,
        )
        ContactBuildingLink.objects.create(
            contact=self.c_legacy_b, building=self.building
        )
        ContactBuildingLink.objects.create(
            contact=self.c_legacy_b, building=self.building_a2
        )

        self.c_no_links = Contact.objects.create(
            customer=self.customer, full_name="No links"
        )

    def list_url(self, cid=None):
        return f"/api/customers/{cid or self.customer.id}/contacts/"

    def detail_url(self, contact_id, cid=None):
        return f"/api/customers/{cid or self.customer.id}/contacts/{contact_id}/"

    def _by_id(self, response):
        data = response.data.get("results", response.data)
        return {item["id"]: item for item in data}


class BMContactBuildingScopeTests(_BMContactScopeFixture):
    # --- list narrowing ---------------------------------------------------
    def test_bm_list_hides_unmanaged_only_contact(self):
        self.authenticate(self.manager)
        resp = self.client.get(self.list_url())
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = self.response_ids(resp)
        self.assertNotIn(self.c_b_only.id, ids)  # linked only to A2 -> hidden
        self.assertIn(self.c_a_only.id, ids)
        self.assertIn(self.c_ab.id, ids)
        self.assertIn(self.c_legacy_b.id, ids)
        self.assertIn(self.c_no_links.id, ids)  # customer-level -> still shown

    def test_bm_list_narrows_linked_building_ids_for_mixed_contact(self):
        self.authenticate(self.manager)
        resp = self.client.get(self.list_url())
        by_id = self._by_id(resp)
        self.assertEqual(
            by_id[self.c_ab.id]["linked_building_ids"], [self.building.id]
        )

    # --- detail narrowing -------------------------------------------------
    def test_bm_detail_mixed_contact_narrows_links(self):
        self.authenticate(self.manager)
        resp = self.client.get(self.detail_url(self.c_ab.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["linked_building_ids"], [self.building.id])

    def test_bm_detail_unmanaged_only_contact_is_404(self):
        self.authenticate(self.manager)
        resp = self.client.get(self.detail_url(self.c_b_only.id))
        # 404 (not 403): existence not revealed across building scopes.
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_bm_legacy_building_field_redacted_when_unmanaged(self):
        self.authenticate(self.manager)
        resp = self.client.get(self.detail_url(self.c_legacy_b.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNone(resp.data["building"])  # A2 redacted for BM
        self.assertEqual(resp.data["linked_building_ids"], [self.building.id])

    def test_bm_no_link_contact_still_visible(self):
        self.authenticate(self.manager)
        resp = self.client.get(self.detail_url(self.c_no_links.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["linked_building_ids"], [])

    # --- admins unchanged -------------------------------------------------
    def test_company_admin_sees_all_contacts_and_full_links(self):
        self.authenticate(self.company_admin)
        resp = self.client.get(self.list_url())
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = self.response_ids(resp)
        for c in (
            self.c_a_only, self.c_b_only, self.c_ab,
            self.c_legacy_b, self.c_no_links,
        ):
            self.assertIn(c.id, ids)
        by_id = self._by_id(resp)
        self.assertCountEqual(
            by_id[self.c_ab.id]["linked_building_ids"],
            [self.building.id, self.building_a2.id],
        )
        # Legacy building field intact for the admin.
        self.assertEqual(
            by_id[self.c_legacy_b.id]["building"], self.building_a2.id
        )

    def test_super_admin_sees_full_links(self):
        self.authenticate(self.super_admin)
        resp = self.client.get(self.detail_url(self.c_ab.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertCountEqual(
            resp.data["linked_building_ids"],
            [self.building.id, self.building_a2.id],
        )
        # B-only contact remains retrievable for SA.
        resp_b = self.client.get(self.detail_url(self.c_b_only.id))
        self.assertEqual(resp_b.status_code, status.HTTP_200_OK)

    # --- out-of-scope BM unchanged (existing 403 pattern) -----------------
    def test_out_of_scope_bm_forbidden(self):
        # other_manager manages other_building in Company B; self.customer
        # is Company A -> out of scope -> 403 via has_object_permission
        # on the URL-bound customer (unchanged Sprint 28 Batch 12 pattern).
        self.authenticate(self.other_manager)
        resp = self.client.get(self.list_url())
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
