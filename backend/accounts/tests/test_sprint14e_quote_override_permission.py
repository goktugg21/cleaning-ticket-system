"""
Sprint 14E — dedicated DANGEROUS quote-bypass permission
(`provider.extra_work.quote_override_start`).

Covers the resolver, the effective-permissions composer surface, the
permission-matrix catalog dangerous flag, and the Super-Admin-only
company grant API. The endpoint-level enforcement (direct-publish gate
+ HIGH-severity audit) lives in
`extra_work/tests/test_proposal_direct_publish.py`.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import StaffProfile, UserRole
from accounts.permission_matrix import (
    CATALOG,
    DANGEROUS_PERMISSION_KEYS,
)
from accounts.permissions_effective import effective_permissions, has_permission
from accounts.permissions_v2 import (
    PROVIDER_DANGEROUS_PERMISSION_KEYS,
    user_has_provider_dangerous_permission,
)
from audit.models import AuditAction, AuditLog
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
KEY = "provider.extra_work.quote_override_start"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email, password=PASSWORD, role=role,
        full_name=email.split("@")[0], **extra,
    )


class _Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        # company_on carries the dangerous grant; company_off does not.
        cls.company_on = Company.objects.create(
            name="Prov ON", slug="prov-on-14e",
            provider_admin_may_quote_override_start=True,
        )
        cls.company_off = Company.objects.create(
            name="Prov OFF", slug="prov-off-14e",
        )
        cls.building_on = Building.objects.create(
            company=cls.company_on, name="B-on"
        )
        cls.building_off = Building.objects.create(
            company=cls.company_off, name="B-off"
        )

        cls.super_admin = _mk(
            "sa-14e@example.com", UserRole.SUPER_ADMIN,
            is_staff=True, is_superuser=True,
        )
        cls.admin_on = _mk("ca-on-14e@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin_on, company=cls.company_on
        )
        cls.admin_off = _mk("ca-off-14e@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin_off, company=cls.company_off
        )

        cls.bm_on = _mk("bm-on-14e@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.bm_on, building=cls.building_on
        )
        cls.bm_off = _mk("bm-off-14e@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.bm_off, building=cls.building_off
        )

        cls.staff = _mk("staff-14e@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)

        cls.customer = Customer.objects.create(
            company=cls.company_on, name="Cust-14e", building=cls.building_on
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building_on
        )
        cls.cust_user = _mk("cust-14e@example.com", UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building_on,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN,
        )


class ResolverTests(_Fixture):
    def test_super_admin_always_true(self):
        self.assertTrue(
            user_has_provider_dangerous_permission(self.super_admin, KEY)
        )
        # Even anchored to the OFF company.
        self.assertTrue(
            user_has_provider_dangerous_permission(
                self.super_admin, KEY, company_id=self.company_off.id
            )
        )

    def test_company_admin_granted_company_true(self):
        self.assertTrue(
            user_has_provider_dangerous_permission(self.admin_on, KEY)
        )
        self.assertTrue(
            user_has_provider_dangerous_permission(
                self.admin_on, KEY, company_id=self.company_on.id
            )
        )

    def test_company_admin_non_granted_company_false(self):
        self.assertFalse(
            user_has_provider_dangerous_permission(self.admin_off, KEY)
        )
        # Granted CA anchored to a DIFFERENT (off) company -> False.
        self.assertFalse(
            user_has_provider_dangerous_permission(
                self.admin_on, KEY, company_id=self.company_off.id
            )
        )

    def test_building_manager_follows_company_grant(self):
        self.assertTrue(
            user_has_provider_dangerous_permission(self.bm_on, KEY)
        )
        self.assertFalse(
            user_has_provider_dangerous_permission(self.bm_off, KEY)
        )

    def test_staff_and_customer_always_false(self):
        self.assertFalse(
            user_has_provider_dangerous_permission(self.staff, KEY)
        )
        self.assertFalse(
            user_has_provider_dangerous_permission(self.cust_user, KEY)
        )

    def test_unknown_key_and_anonymous_false(self):
        self.assertFalse(
            user_has_provider_dangerous_permission(
                self.super_admin, "provider.extra_work.nope"
            )
        )
        self.assertFalse(
            user_has_provider_dangerous_permission(AnonymousUser(), KEY)
        )


class EffectivePermissionsSurfaceTests(_Fixture):
    def test_key_present_and_correct_in_effective_permissions(self):
        granted = effective_permissions(self.admin_on)
        self.assertIn(KEY, granted)
        self.assertTrue(granted[KEY])

        not_granted = effective_permissions(self.admin_off)
        self.assertIn(KEY, not_granted)
        self.assertFalse(not_granted[KEY])

    def test_has_permission_routes_provider_namespace(self):
        self.assertTrue(has_permission(self.super_admin, KEY))
        self.assertTrue(has_permission(self.admin_on, KEY))
        self.assertFalse(has_permission(self.admin_off, KEY))
        self.assertFalse(has_permission(self.staff, KEY))


class MatrixCatalogTests(_Fixture):
    def test_key_in_dangerous_set_and_catalog(self):
        self.assertIn(KEY, PROVIDER_DANGEROUS_PERMISSION_KEYS)
        self.assertIn(KEY, DANGEROUS_PERMISSION_KEYS)
        self.assertIn(KEY, CATALOG)
        entry = CATALOG[KEY]
        self.assertTrue(entry["dangerous"])
        self.assertEqual(entry["category"], "extra_work")
        self.assertTrue(entry["label"])


class CompanyGrantApiTests(_Fixture):
    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _url(self, company_id):
        return f"/api/companies/{company_id}/"

    def test_super_admin_can_grant_and_revoke(self):
        # Grant on the OFF company.
        resp = self._api(self.super_admin).patch(
            self._url(self.company_off.id),
            {"provider_admin_may_quote_override_start": True},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.company_off.refresh_from_db()
        self.assertTrue(
            self.company_off.provider_admin_may_quote_override_start
        )
        # Revoke.
        resp = self._api(self.super_admin).patch(
            self._url(self.company_off.id),
            {"provider_admin_may_quote_override_start": False},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.company_off.refresh_from_db()
        self.assertFalse(
            self.company_off.provider_admin_may_quote_override_start
        )

    def test_company_admin_cannot_self_grant(self):
        resp = self._api(self.admin_off).patch(
            self._url(self.company_off.id),
            {"provider_admin_may_quote_override_start": True},
            format="json",
        )
        self.assertNotEqual(resp.status_code, 200, resp.data)
        self.company_off.refresh_from_db()
        self.assertFalse(
            self.company_off.provider_admin_may_quote_override_start
        )

    def test_grant_writes_audit_log(self):
        before = AuditLog.objects.filter(
            target_model="companies.Company",
            target_id=self.company_off.id,
            action=AuditAction.UPDATE,
        ).count()
        self._api(self.super_admin).patch(
            self._url(self.company_off.id),
            {"provider_admin_may_quote_override_start": True},
            format="json",
        )
        rows = AuditLog.objects.filter(
            target_model="companies.Company",
            target_id=self.company_off.id,
            action=AuditAction.UPDATE,
        )
        self.assertEqual(rows.count(), before + 1)
        latest = rows.order_by("-created_at").first()
        self.assertIn(
            "provider_admin_may_quote_override_start", latest.changes
        )
        self.assertEqual(latest.actor_id, self.super_admin.id)
