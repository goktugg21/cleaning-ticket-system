"""
Sprint 23B serializer surface tests.

The frontend Customer admin form (CustomerFormPage) writes three new
Customer fields (`show_assigned_staff_{name,email,phone}`) and reads
back the Sprint 23A `access_role` / `is_active` / `permission_overrides`
on each CustomerUserBuildingAccess row. These tests pin both behaviours
so a future serializer refactor cannot silently revert them.

Sprint 23A model + ticket-payload tests live in
`backend/accounts/tests/test_sprint23a_foundation.py`; this file
only covers the wire format that Sprint 23B's UI depends on.
"""

from rest_framework import status
from rest_framework.test import APITestCase

from customers.models import CustomerUserBuildingAccess
from test_utils import TenantFixtureMixin


class CustomerVisibilityWritesTests(TenantFixtureMixin, APITestCase):
    """
    `PATCH /api/customers/<id>/` accepts the three visibility flags
    when the caller is super admin or the customer's owning company
    admin. Building managers and customer users cannot flip them.
    """

    def detail_url(self, pk):
        return f"/api/customers/{pk}/"

    def test_super_admin_can_toggle_visibility_flags(self):
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.detail_url(self.customer.id),
            {
                "show_assigned_staff_name": False,
                "show_assigned_staff_email": False,
                "show_assigned_staff_phone": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.show_assigned_staff_name)
        self.assertFalse(self.customer.show_assigned_staff_email)
        self.assertTrue(self.customer.show_assigned_staff_phone)

    def test_owning_company_admin_can_toggle_visibility_flags(self):
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.detail_url(self.customer.id),
            {"show_assigned_staff_name": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.show_assigned_staff_name)

    def test_other_company_admin_cannot_toggle_visibility_flags(self):
        self.authenticate(self.other_company_admin)
        response = self.client.patch(
            self.detail_url(self.customer.id),
            {"show_assigned_staff_name": False},
            format="json",
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )

    def test_building_manager_cannot_toggle_visibility_flags(self):
        self.authenticate(self.manager)
        response = self.client.patch(
            self.detail_url(self.customer.id),
            {"show_assigned_staff_name": False},
            format="json",
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )

    def test_customer_user_cannot_toggle_visibility_flags(self):
        self.authenticate(self.customer_user)
        response = self.client.patch(
            self.detail_url(self.customer.id),
            {"show_assigned_staff_name": False},
            format="json",
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )

    def test_retrieve_exposes_visibility_flags(self):
        self.authenticate(self.company_admin)
        response = self.client.get(self.detail_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for field in (
            "show_assigned_staff_name",
            "show_assigned_staff_email",
            "show_assigned_staff_phone",
        ):
            self.assertIn(field, response.data)
            self.assertTrue(response.data[field])  # defaults


class CustomerUserBuildingAccessSerializerTests(TenantFixtureMixin, APITestCase):
    """
    The customer-user access list endpoint surfaces every Sprint 23A
    field read-only: `access_role`, `is_active`, `permission_overrides`.
    The frontend depends on these three keys being present in each row
    to render the role badge and (eventually) the override editor.
    """

    def setUp(self):
        super().setUp()
        # The shared fixture already creates one access row for the
        # customer_user via membership FK. Upgrade it to a richer
        # Sprint 23A shape so the serializer has something
        # non-default to expose.
        access = CustomerUserBuildingAccess.objects.get(
            membership__user=self.customer_user,
            membership__customer=self.customer,
            building=self.building,
        )
        access.access_role = (
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER
        )
        access.permission_overrides = {"can_view_costs": True}
        access.is_active = True
        access.save(
            update_fields=["access_role", "permission_overrides", "is_active"],
        )

    def access_list_url(self):
        return (
            f"/api/customers/{self.customer.id}"
            f"/users/{self.customer_user.id}/access/"
        )

    def test_access_list_exposes_sprint23a_fields(self):
        self.authenticate(self.company_admin)
        response = self.client.get(self.access_list_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertTrue(results, "Expected at least one access row")
        row = next(r for r in results if r["building_id"] == self.building.id)
        self.assertEqual(row["access_role"], "CUSTOMER_LOCATION_MANAGER")
        self.assertTrue(row["is_active"])
        self.assertEqual(row["permission_overrides"], {"can_view_costs": True})
