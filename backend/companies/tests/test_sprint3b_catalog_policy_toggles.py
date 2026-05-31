"""
Sprint 3B — Super-Admin-only Company policy toggles for catalog +
customer-price management.

Locks the rules added by Sprint 3B on
`companies.Company`:

  * `provider_admin_may_manage_catalog`
  * `provider_admin_may_manage_customer_prices`

Both default True (preserves pre-Sprint-3B behaviour) and may only
be flipped by SUPER_ADMIN. The B5 toggle
(`provider_admin_may_manage_customer_company_admins`) follows the
same SA-only pattern; this file extends the coverage to the two
new fields.

Coverage:
  1. Both fields appear in the GET response.
  2. SUPER_ADMIN can PATCH both fields together and the response
     reflects the new values.
  3. COMPANY_ADMIN PATCH on either field returns 400; the stored
     value is unchanged.
  4. COMPANY_ADMIN PATCH of an unrelated field (name) still works.
  5. SUPER_ADMIN-driven toggle PATCH writes an AuditLog UPDATE row
     (full-CRUD diff is already registered for Company; this
     proves the new fields join the diff).
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import UserRole
from companies.models import Company, CompanyUserMembership


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class _S3BFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            name="Prov S3B-policy", slug="prov-s3b-policy"
        )
        cls.super_admin = _mk(
            "super-s3b-policy@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk(
            "pa-s3b-policy@example.com", UserRole.COMPANY_ADMIN
        )
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _url(self):
        return f"/api/companies/{self.company.id}/"


class CompanyToggleVisibilityTests(_S3BFixture):
    def test_get_exposes_both_new_toggle_fields(self):
        response = self._api(self.super_admin).get(self._url())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("provider_admin_may_manage_catalog", response.data)
        self.assertIn(
            "provider_admin_may_manage_customer_prices", response.data
        )
        self.assertTrue(
            response.data["provider_admin_may_manage_catalog"]
        )
        self.assertTrue(
            response.data["provider_admin_may_manage_customer_prices"]
        )


class SuperAdminCanFlipBothToggles(_S3BFixture):
    def test_super_admin_can_patch_both_toggles_in_one_call(self):
        response = self._api(self.super_admin).patch(
            self._url(),
            {
                "provider_admin_may_manage_catalog": False,
                "provider_admin_may_manage_customer_prices": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(
            response.data["provider_admin_may_manage_catalog"]
        )
        self.assertFalse(
            response.data["provider_admin_may_manage_customer_prices"]
        )

        self.company.refresh_from_db()
        self.assertFalse(self.company.provider_admin_may_manage_catalog)
        self.assertFalse(
            self.company.provider_admin_may_manage_customer_prices
        )

    def test_super_admin_can_flip_back_to_true(self):
        # Pre-set False so the round-trip exercises both directions.
        self.company.provider_admin_may_manage_catalog = False
        self.company.provider_admin_may_manage_customer_prices = False
        self.company.save(
            update_fields=[
                "provider_admin_may_manage_catalog",
                "provider_admin_may_manage_customer_prices",
            ]
        )
        response = self._api(self.super_admin).patch(
            self._url(),
            {
                "provider_admin_may_manage_catalog": True,
                "provider_admin_may_manage_customer_prices": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.company.refresh_from_db()
        self.assertTrue(self.company.provider_admin_may_manage_catalog)
        self.assertTrue(
            self.company.provider_admin_may_manage_customer_prices
        )


class CompanyAdminBlockedFromTogglesTests(_S3BFixture):
    def test_company_admin_cannot_patch_catalog_toggle(self):
        response = self._api(self.admin).patch(
            self._url(),
            {"provider_admin_may_manage_catalog": False},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        # Stored value unchanged.
        self.company.refresh_from_db()
        self.assertTrue(self.company.provider_admin_may_manage_catalog)

    def test_company_admin_cannot_patch_customer_prices_toggle(self):
        response = self._api(self.admin).patch(
            self._url(),
            {"provider_admin_may_manage_customer_prices": False},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.company.refresh_from_db()
        self.assertTrue(
            self.company.provider_admin_may_manage_customer_prices
        )

    def test_company_admin_cannot_patch_both_toggles_at_once(self):
        # Either-field validation suffices to reject the whole
        # payload; the stored row stays untouched.
        response = self._api(self.admin).patch(
            self._url(),
            {
                "provider_admin_may_manage_catalog": False,
                "provider_admin_may_manage_customer_prices": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.company.refresh_from_db()
        self.assertTrue(self.company.provider_admin_may_manage_catalog)
        self.assertTrue(
            self.company.provider_admin_may_manage_customer_prices
        )

    def test_company_admin_can_still_patch_unrelated_field(self):
        # The field-scoped validators must NOT block edits to other
        # Company fields (mirror the B5 contract verified in
        # customers.tests.test_b5_provider_admin_cca_policy).
        response = self._api(self.admin).patch(
            self._url(),
            {"name": "Renamed Provider S3B"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.company.refresh_from_db()
        self.assertEqual(self.company.name, "Renamed Provider S3B")


class CompanyToggleAuditTests(_S3BFixture):
    def test_super_admin_toggle_patch_writes_audit_log(self):
        from audit.models import AuditAction, AuditLog

        before = AuditLog.objects.filter(
            target_model="companies.Company",
            target_id=self.company.id,
            action=AuditAction.UPDATE,
        ).count()
        response = self._api(self.super_admin).patch(
            self._url(),
            {"provider_admin_may_manage_catalog": False},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        after = AuditLog.objects.filter(
            target_model="companies.Company",
            target_id=self.company.id,
            action=AuditAction.UPDATE,
        ).count()
        self.assertEqual(after, before + 1)
