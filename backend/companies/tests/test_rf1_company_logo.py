"""RF-1 Part A — provider company logo upload / delete / serve.

Hardcoded write rule: the provider company logo may be set only by a
COMPANY_ADMIN of that company (a CompanyUserMembership row) or by
SUPER_ADMIN; everyone else 403.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin, make_fake_upload, make_image_upload


def logo_url(company_id):
    return f"/api/companies/{company_id}/logo/"


class CompanyLogoPermissionTests(TenantFixtureMixin, APITestCase):
    def test_company_admin_can_set_own_company_logo(self):
        self.authenticate(self.company_admin)
        resp = self.client.post(
            logo_url(self.company.id),
            {"file": make_image_upload()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["logo_url"])
        self.company.refresh_from_db()
        self.assertTrue(self.company.logo)

    def test_super_admin_can_set_any_company_logo(self):
        self.authenticate(self.super_admin)
        resp = self.client.post(
            logo_url(self.company.id),
            {"file": make_image_upload()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_other_company_admin_cannot_set_logo(self):
        # company_admin of the OTHER company must not touch this one.
        self.authenticate(self.other_company_admin)
        resp = self.client.post(
            logo_url(self.company.id),
            {"file": make_image_upload()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.company.refresh_from_db()
        self.assertFalse(self.company.logo)

    def test_building_manager_cannot_set_company_logo(self):
        self.authenticate(self.manager)
        resp = self.client.post(
            logo_url(self.company.id),
            {"file": make_image_upload()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_user_cannot_set_company_logo(self):
        self.authenticate(self.customer_user)
        resp = self.client.post(
            logo_url(self.company.id),
            {"file": make_image_upload()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_company_admin_can_delete_logo(self):
        self.company.logo = make_image_upload()
        self.company.save(update_fields=["logo"])
        self.authenticate(self.company_admin)
        resp = self.client.delete(logo_url(self.company.id))
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.company.refresh_from_db()
        self.assertFalse(self.company.logo)

    def test_serve_and_serializer_url(self):
        self.company.logo = make_image_upload()
        self.company.save(update_fields=["logo"])
        self.authenticate(self.company_admin)
        resp = self.client.get(logo_url(self.company.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        detail = self.client.get(f"/api/companies/{self.company.id}/")
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertTrue(detail.data["logo_url"])
        self.assertIn("/logo/", detail.data["logo_url"])

    def test_serve_missing_is_404(self):
        self.authenticate(self.company_admin)
        resp = self.client.get(logo_url(self.company.id))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_rejects_non_image(self):
        self.authenticate(self.company_admin)
        resp = self.client.post(
            logo_url(self.company.id),
            {"file": make_fake_upload("x.webp", "image/webp", b"nope")},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
