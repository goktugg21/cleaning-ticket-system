"""
Sprint 28 Batch 12 — Building Manager read-only customer + contact scope.

What changed in Batch 12:
  * Backend: `views_contacts.py` swapped its permission class from
    `IsSuperAdminOrCompanyAdminForCompany` to
    `IsSuperAdminOrCompanyAdminOrBuildingManagerReadCustomer`.
    BUILDING_MANAGER now gets safe-method (GET) access scoped to
    customers in `scope_customers_for(BM)`; POST / PATCH / DELETE
    still 403 for BM.
  * `CustomerViewSet` (customers list/detail) was already correctly
    behaved for BM via `IsAuthenticatedAndActive` + the existing
    `scope_customers_for` queryset; the tests here lock that
    behaviour against regression.
  * SUPER_ADMIN / COMPANY_ADMIN / CUSTOMER_USER behaviour is
    intentionally unchanged.

Coverage matrix:
  * BM list/detail customers IN scope → 200 / row visible.
  * BM detail customer OUT of scope → 404 (queryset filter).
  * BM list/detail contacts for in-scope customer → 200 / row visible.
  * BM list/detail contacts for out-of-scope customer → 404.
  * BM POST / PATCH / DELETE customer or contact → 403.
  * SUPER_ADMIN + COMPANY_ADMIN behaviour unchanged on contacts
    (cross-company COMPANY_ADMIN still 403 / list-not-visible).
"""
from rest_framework import status
from rest_framework.test import APITestCase

from buildings.models import Building, BuildingManagerAssignment
from customers.models import Contact, Customer, CustomerBuildingMembership
from test_utils import TenantFixtureMixin


# ---------------------------------------------------------------------------
# 1. CustomerViewSet — BM list / detail read; write 403.
# ---------------------------------------------------------------------------
class BMCustomerListDetailScopeTests(TenantFixtureMixin, APITestCase):
    """BM sees only customers in their assigned-building scope; cannot
    create/update/delete or reactivate."""

    def list_url(self):
        return "/api/customers/"

    def detail_url(self, customer_id):
        return f"/api/customers/{customer_id}/"

    def test_bm_can_list_in_scope_customer(self):
        self.authenticate(self.manager)
        response = self.client.get(self.list_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self.response_ids(response)
        self.assertIn(self.customer.id, ids)
        # Cross-company customer not visible.
        self.assertNotIn(self.other_customer.id, ids)

    def test_bm_can_retrieve_in_scope_customer(self):
        self.authenticate(self.manager)
        response = self.client.get(self.detail_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.customer.id)

    def test_bm_cannot_retrieve_out_of_scope_customer(self):
        self.authenticate(self.manager)
        response = self.client.get(self.detail_url(self.other_customer.id))
        # queryset-level scope hides the row → 404.
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_bm_cannot_create_customer(self):
        self.authenticate(self.manager)
        response = self.client.post(
            self.list_url(),
            {
                "name": "New customer BM tried",
                "company": self.company.id,
                "building": self.building.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_bm_cannot_update_customer(self):
        self.authenticate(self.manager)
        response = self.client.patch(
            self.detail_url(self.customer.id),
            {"name": "Renamed by BM"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.customer.refresh_from_db()
        self.assertNotEqual(self.customer.name, "Renamed by BM")

    def test_bm_cannot_delete_customer(self):
        self.authenticate(self.manager)
        response = self.client.delete(self.detail_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_active)

    def test_bm_cannot_reactivate_customer(self):
        # Soft-delete first so the reactivate action would otherwise
        # have something to flip.
        self.customer.is_active = False
        self.customer.save(update_fields=["is_active"])
        self.authenticate(self.manager)
        response = self.client.post(
            f"{self.detail_url(self.customer.id)}reactivate/"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)


# ---------------------------------------------------------------------------
# 2. Contacts — BM read in scope; write 403.
# ---------------------------------------------------------------------------
class BMContactListDetailScopeTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # Make one contact under the BM's customer and one under the
        # cross-company customer (out of scope).
        self.in_scope_contact = Contact.objects.create(
            customer=self.customer,
            full_name="In-scope contact",
            email="in-scope@example.com",
        )
        self.out_of_scope_contact = Contact.objects.create(
            customer=self.other_customer,
            full_name="Out-of-scope contact",
            email="out@example.com",
        )

    def list_url(self, customer_id):
        return f"/api/customers/{customer_id}/contacts/"

    def detail_url(self, customer_id, contact_id):
        return f"/api/customers/{customer_id}/contacts/{contact_id}/"

    def test_bm_can_list_contacts_for_in_scope_customer(self):
        self.authenticate(self.manager)
        response = self.client.get(self.list_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self.response_ids(response)
        self.assertIn(self.in_scope_contact.id, ids)

    def test_bm_can_retrieve_in_scope_contact(self):
        self.authenticate(self.manager)
        response = self.client.get(
            self.detail_url(self.customer.id, self.in_scope_contact.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.in_scope_contact.id)

    def test_bm_cannot_list_contacts_for_out_of_scope_customer(self):
        self.authenticate(self.manager)
        response = self.client.get(self.list_url(self.other_customer.id))
        # The view's `check_object_permissions` calls
        # `has_object_permission` on the URL-bound Customer — for an
        # out-of-scope customer BM fails the scope check → 403.
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_bm_cannot_retrieve_contact_via_out_of_scope_customer(self):
        self.authenticate(self.manager)
        response = self.client.get(
            self.detail_url(
                self.other_customer.id, self.out_of_scope_contact.id
            )
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_bm_cannot_create_contact(self):
        self.authenticate(self.manager)
        response = self.client.post(
            self.list_url(self.customer.id),
            {"full_name": "Created by BM", "email": "bm@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_bm_cannot_update_contact(self):
        self.authenticate(self.manager)
        response = self.client.patch(
            self.detail_url(self.customer.id, self.in_scope_contact.id),
            {"full_name": "Renamed by BM"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.in_scope_contact.refresh_from_db()
        self.assertEqual(self.in_scope_contact.full_name, "In-scope contact")

    def test_bm_cannot_delete_contact(self):
        self.authenticate(self.manager)
        response = self.client.delete(
            self.detail_url(self.customer.id, self.in_scope_contact.id)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(
            Contact.objects.filter(pk=self.in_scope_contact.id).exists()
        )


# ---------------------------------------------------------------------------
# 3. SUPER_ADMIN + COMPANY_ADMIN unchanged on contacts.
# ---------------------------------------------------------------------------
class BMContactAdminUnchangedTests(TenantFixtureMixin, APITestCase):
    """Locks that the Batch 12 permission swap did not regress admin
    behaviour on the contact endpoints."""

    def setUp(self):
        super().setUp()
        self.in_scope_contact = Contact.objects.create(
            customer=self.customer, full_name="Admin contact"
        )

    def list_url(self, customer_id):
        return f"/api/customers/{customer_id}/contacts/"

    def detail_url(self, customer_id, contact_id):
        return f"/api/customers/{customer_id}/contacts/{contact_id}/"

    def test_super_admin_can_still_create_contact(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.list_url(self.customer.id),
            {"full_name": "Super-admin contact"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_super_admin_can_still_patch_contact(self):
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.detail_url(self.customer.id, self.in_scope_contact.id),
            {"full_name": "Renamed by super admin"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_super_admin_can_still_delete_contact(self):
        self.authenticate(self.super_admin)
        response = self.client.delete(
            self.detail_url(self.customer.id, self.in_scope_contact.id)
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_company_admin_in_scope_can_still_create_contact(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            self.list_url(self.customer.id),
            {"full_name": "Company-admin contact"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_company_admin_cross_company_still_blocked(self):
        self.authenticate(self.other_company_admin)
        response = self.client.get(self.list_url(self.customer.id))
        # has_object_permission on the URL-bound customer rejects the
        # cross-company admin → 403, NOT a leaked 200.
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_and_customer_user_still_403_or_404_on_contacts(self):
        # STAFF + CUSTOMER_USER both fail at has_permission (BUILDING_MANAGER
        # was the only role widened in Batch 12).
        from accounts.models import UserRole
        staff_user = self.make_user("staff@example.com", UserRole.STAFF)
        self.authenticate(staff_user)
        response = self.client.get(self.list_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.authenticate(self.customer_user)
        response = self.client.get(self.list_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# 4. BM without an assigned building — scope must be empty (defence in depth).
# ---------------------------------------------------------------------------
class BMWithoutAssignedBuildingTests(TenantFixtureMixin, APITestCase):
    """A BM with no `BuildingManagerAssignment` rows should see nothing,
    even on the BM-permissive read path."""

    def setUp(self):
        super().setUp()
        # New BM with NO building assignment.
        from accounts.models import UserRole
        self.bare_bm = self.make_user(
            "bare-bm@example.com", UserRole.BUILDING_MANAGER
        )

    def test_bare_bm_sees_zero_customers(self):
        self.authenticate(self.bare_bm)
        response = self.client.get("/api/customers/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self.response_ids(response)
        self.assertNotIn(self.customer.id, ids)
        self.assertNotIn(self.other_customer.id, ids)

    def test_bare_bm_cannot_list_contacts_of_any_customer(self):
        self.authenticate(self.bare_bm)
        response = self.client.get(
            f"/api/customers/{self.customer.id}/contacts/"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
