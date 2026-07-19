"""RF-1 Part A — customer logo upload / delete / serve.

Hardcoded write rule: a customer's logo may be set only by that
customer's CUSTOMER_COMPANY_ADMIN (the `is_company_admin` membership
flag) or by SUPER_ADMIN; everyone else 403.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from customers.models import CustomerUserBuildingAccess, CustomerUserMembership
from test_utils import TenantFixtureMixin, make_fake_upload, make_image_upload


def logo_url(customer_id):
    return f"/api/customers/{customer_id}/logo/"


class CustomerLogoPermissionTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # A CUSTOMER_COMPANY_ADMIN of self.customer.
        self.cca = self.make_user("cca-a@example.com", UserRole.CUSTOMER_USER)
        cca_membership = CustomerUserMembership.objects.create(
            user=self.cca, customer=self.customer, is_company_admin=True
        )
        CustomerUserBuildingAccess.objects.create(
            membership=cca_membership, building=self.building
        )
        # A CUSTOMER_COMPANY_ADMIN of the OTHER customer (wrong customer).
        self.other_cca = self.make_user("cca-b@example.com", UserRole.CUSTOMER_USER)
        other_membership = CustomerUserMembership.objects.create(
            user=self.other_cca, customer=self.other_customer, is_company_admin=True
        )
        CustomerUserBuildingAccess.objects.create(
            membership=other_membership, building=self.other_building
        )

    def test_customer_company_admin_can_set_logo(self):
        self.authenticate(self.cca)
        resp = self.client.post(
            logo_url(self.customer.id),
            {"file": make_image_upload()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["logo_url"])
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.logo)

    def test_super_admin_can_set_logo(self):
        self.authenticate(self.super_admin)
        resp = self.client.post(
            logo_url(self.customer.id),
            {"file": make_image_upload()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_wrong_customers_cca_cannot_set_logo(self):
        self.authenticate(self.other_cca)
        resp = self.client.post(
            logo_url(self.customer.id),
            {"file": make_image_upload()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.logo)

    def test_plain_customer_user_cannot_set_logo(self):
        # customer_user is a member of self.customer but NOT a company admin.
        self.authenticate(self.customer_user)
        resp = self.client.post(
            logo_url(self.customer.id),
            {"file": make_image_upload()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_provider_company_admin_cannot_set_customer_logo(self):
        # Only the CUSTOMER company admin (or SA) — not the provider CA.
        self.authenticate(self.company_admin)
        resp = self.client.post(
            logo_url(self.customer.id),
            {"file": make_image_upload()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_cca_can_delete_logo(self):
        self.customer.logo = make_image_upload()
        self.customer.save(update_fields=["logo"])
        self.authenticate(self.cca)
        resp = self.client.delete(logo_url(self.customer.id))
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.logo)

    def test_serve_and_serializer_url(self):
        self.customer.logo = make_image_upload()
        self.customer.save(update_fields=["logo"])
        self.authenticate(self.company_admin)  # any active user may view
        resp = self.client.get(logo_url(self.customer.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # And the customer serializer exposes logo_url.
        detail = self.client.get(f"/api/customers/{self.customer.id}/")
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertTrue(detail.data["logo_url"])
        self.assertIn("/logo/", detail.data["logo_url"])

    def test_serve_missing_is_404(self):
        self.authenticate(self.company_admin)
        resp = self.client.get(logo_url(self.customer.id))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_rejects_non_image(self):
        self.authenticate(self.cca)
        resp = self.client.post(
            logo_url(self.customer.id),
            {"file": make_fake_upload("evil.png", "image/png", b"nope")},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
