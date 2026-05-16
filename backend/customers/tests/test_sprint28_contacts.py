"""
Sprint 28 Batch 4 — Contact (customer phone-book) CRUD tests.

Coverage matrix:

  * Happy path — SUPER_ADMIN + COMPANY_ADMIN can list / create /
    retrieve / update / delete contacts for customers in their scope.
  * Scope isolation — a COMPANY_ADMIN from provider B cannot touch
    contacts of a customer in provider A. CUSTOMER_USER, STAFF and
    BUILDING_MANAGER never reach any endpoint.
  * ID smuggling — a SUPER_ADMIN cannot operate on contact B by
    requesting it under the URL of customer A.
  * building validation — the FK is optional; when supplied, it MUST
    point at a building linked to the customer via
    `CustomerBuildingMembership`.
  * Contact-is-not-a-User — the serialized response NEVER contains
    auth-shaped fields (password / role / is_active / user /
    permission_overrides / last_login).
"""
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import Building
from customers.models import (
    Contact,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
)
from test_utils import TenantFixtureMixin


class ContactCrudHappyPathTests(TenantFixtureMixin, APITestCase):
    def list_url(self, customer_id):
        return f"/api/customers/{customer_id}/contacts/"

    def detail_url(self, customer_id, contact_id):
        return f"/api/customers/{customer_id}/contacts/{contact_id}/"

    def test_super_admin_can_create_and_list_contact(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.list_url(self.customer.id),
            {
                "full_name": "Jane Receptionist",
                "email": "jane@cust-a.example",
                "phone": "+31 20 555 1212",
                "role_label": "Reception",
                "notes": "Front desk Monday-Friday 9-17.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["full_name"], "Jane Receptionist")
        self.assertEqual(response.data["customer"], self.customer.id)
        # The contact appears in the subsequent list call.
        list_response = self.client.get(self.list_url(self.customer.id))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data["count"], 1)
        self.assertEqual(
            list_response.data["results"][0]["id"], response.data["id"]
        )

    def test_company_admin_can_crud_contact_in_own_scope(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            self.list_url(self.customer.id),
            {"full_name": "Alice Lead", "phone": "+31 6 1234 5678"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        contact_id = response.data["id"]

        # Retrieve.
        retrieve = self.client.get(self.detail_url(self.customer.id, contact_id))
        self.assertEqual(retrieve.status_code, status.HTTP_200_OK)
        self.assertEqual(retrieve.data["full_name"], "Alice Lead")

        # Update.
        update = self.client.patch(
            self.detail_url(self.customer.id, contact_id),
            {"role_label": "Operations Lead"},
            format="json",
        )
        self.assertEqual(update.status_code, status.HTTP_200_OK)
        self.assertEqual(update.data["role_label"], "Operations Lead")

        # Delete.
        delete = self.client.delete(
            self.detail_url(self.customer.id, contact_id)
        )
        self.assertEqual(delete.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Contact.objects.filter(pk=contact_id).exists())

    def test_create_contact_with_no_building_is_allowed(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.list_url(self.customer.id),
            {"full_name": "Bob No-Building", "phone": "+31 6 0000 0000"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data["building"])

    def test_create_contact_with_valid_building_membership(self):
        # `self.building` is already linked to `self.customer` via the
        # fixture's CustomerBuildingMembership row, so this is a
        # legitimate building attachment.
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.list_url(self.customer.id),
            {
                "full_name": "Carol Building",
                "phone": "+31 6 1111 2222",
                "building": self.building.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["building"], self.building.id)

    def test_customer_field_is_read_only_on_create(self):
        # POSTing a `customer` in the body must NOT override the
        # URL-bound customer. The serializer marks it read-only.
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.list_url(self.customer.id),
            {
                "full_name": "URL Wins",
                "customer": self.other_customer.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["customer"], self.customer.id)


class ContactScopeIsolationTests(TenantFixtureMixin, APITestCase):
    def list_url(self, customer_id):
        return f"/api/customers/{customer_id}/contacts/"

    def detail_url(self, customer_id, contact_id):
        return f"/api/customers/{customer_id}/contacts/{contact_id}/"

    def setUp(self):
        super().setUp()
        # One contact per tenant so the cross-company tests have a real
        # row to either succeed-on or be-blocked-from.
        self.contact_a = Contact.objects.create(
            customer=self.customer, full_name="Owner of Company A"
        )
        self.contact_b = Contact.objects.create(
            customer=self.other_customer, full_name="Owner of Company B"
        )

    def test_company_admin_cannot_list_contacts_of_other_company(self):
        self.authenticate(self.company_admin)
        response = self.client.get(self.list_url(self.other_customer.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_company_admin_cannot_create_contact_for_other_company(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            self.list_url(self.other_customer.id),
            {"full_name": "Should fail"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            Contact.objects.filter(full_name="Should fail").exists()
        )

    def test_company_admin_cannot_retrieve_contact_of_other_company(self):
        self.authenticate(self.company_admin)
        response = self.client.get(
            self.detail_url(self.other_customer.id, self.contact_b.id)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_company_admin_cannot_update_contact_of_other_company(self):
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.detail_url(self.other_customer.id, self.contact_b.id),
            {"full_name": "Hijack"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.contact_b.refresh_from_db()
        self.assertEqual(self.contact_b.full_name, "Owner of Company B")

    def test_company_admin_cannot_delete_contact_of_other_company(self):
        self.authenticate(self.company_admin)
        response = self.client.delete(
            self.detail_url(self.other_customer.id, self.contact_b.id)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Contact.objects.filter(pk=self.contact_b.id).exists())

    def test_customer_user_blocked_on_every_endpoint(self):
        self.authenticate(self.customer_user)
        list_resp = self.client.get(self.list_url(self.customer.id))
        self.assertEqual(list_resp.status_code, status.HTTP_403_FORBIDDEN)
        create_resp = self.client.post(
            self.list_url(self.customer.id),
            {"full_name": "Nope"},
            format="json",
        )
        self.assertEqual(create_resp.status_code, status.HTTP_403_FORBIDDEN)
        retrieve_resp = self.client.get(
            self.detail_url(self.customer.id, self.contact_a.id)
        )
        self.assertEqual(retrieve_resp.status_code, status.HTTP_403_FORBIDDEN)
        update_resp = self.client.patch(
            self.detail_url(self.customer.id, self.contact_a.id),
            {"full_name": "Hijack"},
            format="json",
        )
        self.assertEqual(update_resp.status_code, status.HTTP_403_FORBIDDEN)
        delete_resp = self.client.delete(
            self.detail_url(self.customer.id, self.contact_a.id)
        )
        self.assertEqual(delete_resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_building_manager_blocked_on_every_endpoint(self):
        self.authenticate(self.manager)
        list_resp = self.client.get(self.list_url(self.customer.id))
        self.assertEqual(list_resp.status_code, status.HTTP_403_FORBIDDEN)
        create_resp = self.client.post(
            self.list_url(self.customer.id),
            {"full_name": "Nope"},
            format="json",
        )
        self.assertEqual(create_resp.status_code, status.HTTP_403_FORBIDDEN)
        retrieve_resp = self.client.get(
            self.detail_url(self.customer.id, self.contact_a.id)
        )
        self.assertEqual(retrieve_resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_role_blocked_on_every_endpoint(self):
        # STAFF (Sprint 23A service-provider-side field staff) is not on
        # the IsSuperAdminOrCompanyAdminForCompany allow-list.
        staff_user = self.make_user("staff-a@example.com", UserRole.STAFF)
        self.authenticate(staff_user)
        list_resp = self.client.get(self.list_url(self.customer.id))
        self.assertEqual(list_resp.status_code, status.HTTP_403_FORBIDDEN)
        retrieve_resp = self.client.get(
            self.detail_url(self.customer.id, self.contact_a.id)
        )
        self.assertEqual(retrieve_resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_id_smuggling_returns_404(self):
        # A SUPER_ADMIN asking for contact_b under customer A's URL
        # must 404 — never silently mutate the other customer's row.
        self.authenticate(self.super_admin)
        retrieve_resp = self.client.get(
            self.detail_url(self.customer.id, self.contact_b.id)
        )
        self.assertEqual(retrieve_resp.status_code, status.HTTP_404_NOT_FOUND)

        patch_resp = self.client.patch(
            self.detail_url(self.customer.id, self.contact_b.id),
            {"full_name": "Smuggled"},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, status.HTTP_404_NOT_FOUND)
        self.contact_b.refresh_from_db()
        self.assertEqual(self.contact_b.full_name, "Owner of Company B")

        delete_resp = self.client.delete(
            self.detail_url(self.customer.id, self.contact_b.id)
        )
        self.assertEqual(delete_resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Contact.objects.filter(pk=self.contact_b.id).exists())


class ContactBuildingValidationTests(TenantFixtureMixin, APITestCase):
    def list_url(self, customer_id):
        return f"/api/customers/{customer_id}/contacts/"

    def detail_url(self, customer_id, contact_id):
        return f"/api/customers/{customer_id}/contacts/{contact_id}/"

    def setUp(self):
        super().setUp()
        # Building in the same company that is NOT linked to
        # `self.customer` via CustomerBuildingMembership.
        self.unlinked_building = Building.objects.create(
            company=self.company,
            name="Building Unlinked",
            address="Side Street 99",
        )
        # `self.other_building` is in `self.other_company` — used to
        # test that even cross-company building attachment 400s.
        self.contact = Contact.objects.create(
            customer=self.customer, full_name="Existing Contact"
        )

    def test_create_with_unlinked_building_in_same_company_returns_400(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.list_url(self.customer.id),
            {
                "full_name": "Will Fail",
                "building": self.unlinked_building.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("building", response.data)

    def test_create_with_cross_company_building_returns_400(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.list_url(self.customer.id),
            {
                "full_name": "Cross-Tenant Fail",
                "building": self.other_building.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("building", response.data)

    def test_patch_to_unlinked_building_returns_400(self):
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.detail_url(self.customer.id, self.contact.id),
            {"building": self.unlinked_building.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("building", response.data)
        self.contact.refresh_from_db()
        self.assertIsNone(self.contact.building_id)

    def test_patch_to_valid_membership_building_succeeds(self):
        # Add a fresh building linked to self.customer.
        new_b = Building.objects.create(
            company=self.company, name="Building C", address="Main 3"
        )
        CustomerBuildingMembership.objects.create(
            customer=self.customer, building=new_b
        )
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.detail_url(self.customer.id, self.contact.id),
            {"building": new_b.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["building"], new_b.id)


class ContactIsNotAUserTests(TenantFixtureMixin, APITestCase):
    """Contacts must NEVER carry auth-shaped fields on the wire. The
    spec hard rule (§1) is that a Contact is not a login user; the
    serializer must reflect that contract.
    """

    list_url_tmpl = "/api/customers/{customer_id}/contacts/"
    detail_url_tmpl = "/api/customers/{customer_id}/contacts/{contact_id}/"

    FORBIDDEN_KEYS = (
        "password",
        "role",
        "is_active",
        "user",
        "user_id",
        "permission_overrides",
        "last_login",
    )

    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.create(
            customer=self.customer, full_name="No-Auth Contact"
        )

    def _assert_no_auth_keys(self, payload):
        for key in payload:
            self.assertNotIn(
                key,
                self.FORBIDDEN_KEYS,
                f"Auth-shaped key {key!r} leaked into contact serialization.",
            )

    def test_create_response_carries_no_auth_keys(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.list_url_tmpl.format(customer_id=self.customer.id),
            {"full_name": "Brand New"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self._assert_no_auth_keys(response.data)

    def test_list_response_carries_no_auth_keys(self):
        self.authenticate(self.super_admin)
        response = self.client.get(
            self.list_url_tmpl.format(customer_id=self.customer.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # results carry contact payloads
        for row in response.data["results"]:
            self._assert_no_auth_keys(row)

    def test_retrieve_response_carries_no_auth_keys(self):
        self.authenticate(self.super_admin)
        response = self.client.get(
            self.detail_url_tmpl.format(
                customer_id=self.customer.id, contact_id=self.contact.id
            )
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self._assert_no_auth_keys(response.data)

    def test_creating_contact_does_not_create_user_or_membership(self):
        # Belt and braces: writing a Contact must not create a User, a
        # CustomerUserMembership or a CustomerUserBuildingAccess row.
        from django.contrib.auth import get_user_model
        from customers.models import CustomerUserMembership

        user_count_before = get_user_model().objects.count()
        membership_count_before = CustomerUserMembership.objects.count()
        access_count_before = CustomerUserBuildingAccess.objects.count()

        self.authenticate(self.super_admin)
        response = self.client.post(
            self.list_url_tmpl.format(customer_id=self.customer.id),
            {"full_name": "Phonebook Only", "email": "pb@cust.example"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(
            get_user_model().objects.count(),
            user_count_before,
            "Creating a contact must not create a User row.",
        )
        self.assertEqual(
            CustomerUserMembership.objects.count(),
            membership_count_before,
            "Creating a contact must not create a CustomerUserMembership row.",
        )
        self.assertEqual(
            CustomerUserBuildingAccess.objects.count(),
            access_count_before,
            "Creating a contact must not create a CustomerUserBuildingAccess row.",
        )
