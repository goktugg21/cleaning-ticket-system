"""
Employees directory (provider) — GET /api/employees/.

The multi-role provider workforce directory: lists COMPANY_ADMIN /
BUILDING_MANAGER / STAFF scoped per viewer, EXCLUDING SUPER_ADMIN (a
platform admin, not a provider employee) and every customer-side user.
Distinct from the STAFF-only /api/staff/ roster.

RBAC matrix pinned here:
  VIEW: SUPER_ADMIN (all), COMPANY_ADMIN (own company),
        BUILDING_MANAGER (own company, read-only).
  EDIT (employment_type via the existing /staff-profile/ PATCH):
        SUPER_ADMIN, COMPANY_ADMIN; BUILDING_MANAGER cannot; a PA cannot
        edit another provider company's staff.
  STAFF / CUSTOMER_USER -> 403 (IsProviderRosterReader).
Cross-tenant isolation: a PA never sees another provider company's people.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import StaffProfile, UserRole
from buildings.models import (
    Building,
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
URL = "/api/employees/"


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class ProviderEmployeesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="Emp Co A", slug="emp-co-a")
        cls.company_b = Company.objects.create(name="Emp Co B", slug="emp-co-b")
        cls.building_a = Building.objects.create(
            company=cls.company_a, name="Emp A1"
        )
        cls.building_b = Building.objects.create(
            company=cls.company_b, name="Emp B1"
        )

        cls.super_admin = _mk(
            "emp-super@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )

        cls.admin_a = _mk("emp-admin-a@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin_a, company=cls.company_a
        )
        cls.admin_b = _mk("emp-admin-b@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin_b, company=cls.company_b
        )

        cls.manager_a = _mk("emp-mgr-a@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager_a, building=cls.building_a
        )
        cls.manager_b = _mk("emp-mgr-b@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager_b, building=cls.building_b
        )

        cls.staff_a = _mk("emp-staff-a@example.com", UserRole.STAFF)
        StaffProfile.objects.create(
            user=cls.staff_a,
            employment_type=StaffProfile.EmploymentType.ZZP,
        )
        BuildingStaffVisibility.objects.create(
            user=cls.staff_a, building=cls.building_a
        )
        cls.staff_b = _mk("emp-staff-b@example.com", UserRole.STAFF)
        StaffProfile.objects.create(
            user=cls.staff_b,
            employment_type=StaffProfile.EmploymentType.INTERNAL_STAFF,
        )
        BuildingStaffVisibility.objects.create(
            user=cls.staff_b, building=cls.building_b
        )

        # A customer-side user that must NEVER appear in the provider
        # workforce directory.
        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Emp Cust A", building=cls.building_a
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a, building=cls.building_a
        )
        cls.cust_user = _mk("emp-cust@example.com", UserRole.CUSTOMER_USER)
        mem = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=mem,
            building=cls.building_a,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _rows(self, resp):
        return resp.data["results"] if isinstance(resp.data, dict) else resp.data

    def _emails(self, resp):
        return {r["email"] for r in self._rows(resp)}

    # ---- VIEW scope ----------------------------------------------------

    def test_super_admin_sees_all_provider_employees(self):
        resp = self._api(self.super_admin).get(URL)
        self.assertEqual(resp.status_code, 200, resp.data)
        emails = self._emails(resp)
        self.assertIn(self.admin_a.email, emails)
        self.assertIn(self.manager_b.email, emails)
        self.assertIn(self.staff_a.email, emails)
        # SUPER_ADMIN itself is NOT a provider employee.
        self.assertNotIn(self.super_admin.email, emails)
        # Customer-side users never appear.
        self.assertNotIn(self.cust_user.email, emails)

    def test_company_admin_sees_only_own_company(self):
        resp = self._api(self.admin_a).get(URL)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(
            self._emails(resp),
            {self.admin_a.email, self.manager_a.email, self.staff_a.email},
        )

    def test_building_manager_sees_own_company_readonly(self):
        resp = self._api(self.manager_a).get(URL)
        self.assertEqual(resp.status_code, 200, resp.data)
        emails = self._emails(resp)
        self.assertIn(self.staff_a.email, emails)
        self.assertIn(self.admin_a.email, emails)
        # Cross-company isolation: company B people never leak.
        self.assertNotIn(self.staff_b.email, emails)
        self.assertNotIn(self.admin_b.email, emails)

    def test_employment_type_present_on_staff_null_for_pa_bm(self):
        resp = self._api(self.super_admin).get(URL)
        by_email = {r["email"]: r for r in self._rows(resp)}
        self.assertEqual(by_email[self.staff_a.email]["employment_type"], "ZZP")
        self.assertIsNone(by_email[self.admin_a.email]["employment_type"])
        self.assertIsNone(by_email[self.manager_a.email]["employment_type"])

    # ---- filters -------------------------------------------------------

    def test_role_filter(self):
        emails = self._emails(self._api(self.super_admin).get(URL + "?role=STAFF"))
        self.assertIn(self.staff_a.email, emails)
        self.assertNotIn(self.admin_a.email, emails)
        self.assertNotIn(self.manager_a.email, emails)

    def test_role_filter_invalid_returns_400(self):
        resp = self._api(self.super_admin).get(URL + "?role=SUPER_ADMIN")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "role_invalid")

    def test_employment_type_filter_and_invalid(self):
        ok = self._api(self.super_admin).get(URL + "?employment_type=ZZP")
        self.assertIn(self.staff_a.email, self._emails(ok))
        self.assertNotIn(self.staff_b.email, self._emails(ok))
        bad = self._api(self.super_admin).get(URL + "?employment_type=NOPE")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.data["code"], "employment_type_invalid")

    # ---- forbidden roles ----------------------------------------------

    def test_staff_and_customer_forbidden(self):
        self.assertEqual(self._api(self.staff_a).get(URL).status_code, 403)
        self.assertEqual(self._api(self.cust_user).get(URL).status_code, 403)

    # ---- privacy floor -------------------------------------------------

    def test_privacy_floor_exact_fields(self):
        resp = self._api(self.super_admin).get(URL)
        for r in self._rows(resp):
            self.assertEqual(
                set(r.keys()),
                {"id", "full_name", "email", "role", "employment_type", "is_active"},
            )

    # ---- employment_type EDIT (reuse the staff-profile PATCH) ----------

    def _profile_url(self, user):
        return f"/api/users/{user.id}/staff-profile/"

    def test_pa_can_edit_own_company_staff_employment_type(self):
        resp = self._api(self.admin_a).patch(
            self._profile_url(self.staff_a),
            {"employment_type": "INHUUR"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.staff_a.staff_profile.refresh_from_db()
        self.assertEqual(self.staff_a.staff_profile.employment_type, "INHUUR")

    def test_building_manager_cannot_edit_employment_type(self):
        resp = self._api(self.manager_a).patch(
            self._profile_url(self.staff_a),
            {"employment_type": "INHUUR"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_pa_cannot_edit_cross_company_staff(self):
        resp = self._api(self.admin_a).patch(
            self._profile_url(self.staff_b),
            {"employment_type": "INHUUR"},
            format="json",
        )
        self.assertIn(resp.status_code, (403, 404))
