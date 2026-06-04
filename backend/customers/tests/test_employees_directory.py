"""
Employees directory (customer) — GET /api/customers/<cid>/employees/.

Lists a single customer's people with their EFFECTIVE access role
(CUSTOMER_COMPANY_ADMIN > CUSTOMER_LOCATION_MANAGER > CUSTOMER_USER).

RBAC matrix pinned here:
  VIEW: SUPER_ADMIN (any customer), COMPANY_ADMIN (own company's
        customers), CCA / CLM / CU (own customer); CLM / CU read-only.
        BUILDING_MANAGER / STAFF -> 403.
  EDIT (access role via the existing /access/<bid>/ PATCH): SUPER_ADMIN,
        COMPANY_ADMIN (own company), CCA (own customer only); CLM / CU
        cannot edit; a PA cannot edit a customer outside their company.
Cross-tenant isolation: a cross-customer / cross-company <cid> -> 404
(not a 403 leak); a CCA never reaches another customer.
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
AR = CustomerUserBuildingAccess.AccessRole


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class CustomerEmployeesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="CE Co A", slug="ce-co-a")
        cls.company_b = Company.objects.create(name="CE Co B", slug="ce-co-b")
        cls.building_a1 = Building.objects.create(
            company=cls.company_a, name="CE A1"
        )
        cls.building_a2 = Building.objects.create(
            company=cls.company_a, name="CE A2"
        )
        cls.building_b1 = Building.objects.create(
            company=cls.company_b, name="CE B1"
        )

        cls.super_admin = _mk(
            "ce-super@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin_a = _mk("ce-admin-a@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin_a, company=cls.company_a
        )

        cls.manager_a = _mk("ce-mgr-a@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager_a, building=cls.building_a1
        )
        cls.staff_a = _mk("ce-staff-a@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_a)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_a, building=cls.building_a1
        )

        # Customers: a1 + a2 in company A, b1 in company B.
        cls.customer_a1 = Customer.objects.create(
            company=cls.company_a, name="CE Cust A1", building=cls.building_a1
        )
        cls.customer_a2 = Customer.objects.create(
            company=cls.company_a, name="CE Cust A2", building=cls.building_a1
        )
        cls.customer_b1 = Customer.objects.create(
            company=cls.company_b, name="CE Cust B1", building=cls.building_b1
        )
        # a1 spans buildings A1 + A2 (for the multi-building effective-role
        # test); a2 + b1 single-building.
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a1, building=cls.building_a1
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a1, building=cls.building_a2
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a2, building=cls.building_a1
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_b1, building=cls.building_b1
        )

        cls.cca_user = cls._customer_user(
            "ce-cca@example.com",
            cls.customer_a1,
            [(cls.building_a1, AR.CUSTOMER_COMPANY_ADMIN)],
        )
        cls.clm_user = cls._customer_user(
            "ce-clm@example.com",
            cls.customer_a1,
            [(cls.building_a1, AR.CUSTOMER_LOCATION_MANAGER)],
        )
        cls.cu_user = cls._customer_user(
            "ce-cu@example.com",
            cls.customer_a1,
            [(cls.building_a1, AR.CUSTOMER_USER)],
        )
        # Multi-building: CU on A1 + CCA on A2 -> EFFECTIVE = CCA.
        cls.multi_user = cls._customer_user(
            "ce-multi@example.com",
            cls.customer_a1,
            [
                (cls.building_a1, AR.CUSTOMER_USER),
                (cls.building_a2, AR.CUSTOMER_COMPANY_ADMIN),
            ],
        )
        # A customer-B CCA for cross-company isolation tests.
        cls.cb_cca = cls._customer_user(
            "ce-b-cca@example.com",
            cls.customer_b1,
            [(cls.building_b1, AR.CUSTOMER_COMPANY_ADMIN)],
        )

    @classmethod
    def _customer_user(cls, email, customer, access_rows):
        user = _mk(email, UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            customer=customer, user=user
        )
        for building, role in access_rows:
            CustomerUserBuildingAccess.objects.create(
                membership=membership,
                building=building,
                access_role=role,
                is_active=True,
            )
        return user

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _url(self, customer):
        return f"/api/customers/{customer.id}/employees/"

    def _rows(self, resp):
        return resp.data["results"] if isinstance(resp.data, dict) else resp.data

    def _emails(self, resp):
        return {r["email"] for r in self._rows(resp)}

    def _by_email(self, resp):
        return {r["email"]: r for r in self._rows(resp)}

    # ---- VIEW scope + effective role ----------------------------------

    def test_super_admin_sees_people_with_effective_roles(self):
        resp = self._api(self.super_admin).get(self._url(self.customer_a1))
        self.assertEqual(resp.status_code, 200, resp.data)
        by = self._by_email(resp)
        self.assertEqual(
            by[self.cca_user.email]["customer_access_role"],
            "CUSTOMER_COMPANY_ADMIN",
        )
        self.assertEqual(
            by[self.clm_user.email]["customer_access_role"],
            "CUSTOMER_LOCATION_MANAGER",
        )
        self.assertEqual(
            by[self.cu_user.email]["customer_access_role"], "CUSTOMER_USER"
        )
        # Highest grant wins across buildings.
        self.assertEqual(
            by[self.multi_user.email]["customer_access_role"],
            "CUSTOMER_COMPANY_ADMIN",
        )
        # Customer-B people never appear under customer A1.
        self.assertNotIn(self.cb_cca.email, by)

    def test_company_admin_sees_own_company_customer(self):
        resp = self._api(self.admin_a).get(self._url(self.customer_a1))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn(self.cca_user.email, self._emails(resp))

    def test_company_admin_cross_company_customer_404(self):
        resp = self._api(self.admin_a).get(self._url(self.customer_b1))
        self.assertEqual(resp.status_code, 404)

    def test_cca_sees_own_customer(self):
        resp = self._api(self.cca_user).get(self._url(self.customer_a1))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn(self.clm_user.email, self._emails(resp))

    def test_clm_and_cu_can_view_own_customer(self):
        for u in (self.clm_user, self.cu_user):
            resp = self._api(u).get(self._url(self.customer_a1))
            self.assertEqual(resp.status_code, 200, (u.email, resp.data))

    def test_cca_cannot_open_other_customers_404(self):
        # cca_user belongs only to customer_a1.
        self.assertEqual(
            self._api(self.cca_user).get(self._url(self.customer_a2)).status_code,
            404,
        )
        self.assertEqual(
            self._api(self.cca_user).get(self._url(self.customer_b1)).status_code,
            404,
        )

    def test_building_manager_and_staff_forbidden(self):
        self.assertEqual(
            self._api(self.manager_a).get(self._url(self.customer_a1)).status_code,
            403,
        )
        self.assertEqual(
            self._api(self.staff_a).get(self._url(self.customer_a1)).status_code,
            403,
        )

    # ---- access_role filter -------------------------------------------

    def test_access_role_filter_effective(self):
        cca = self._emails(
            self._api(self.super_admin).get(
                self._url(self.customer_a1) + "?access_role=CUSTOMER_COMPANY_ADMIN"
            )
        )
        self.assertIn(self.cca_user.email, cca)
        self.assertIn(self.multi_user.email, cca)  # effective CCA
        self.assertNotIn(self.clm_user.email, cca)
        self.assertNotIn(self.cu_user.email, cca)

        clm = self._emails(
            self._api(self.super_admin).get(
                self._url(self.customer_a1)
                + "?access_role=CUSTOMER_LOCATION_MANAGER"
            )
        )
        self.assertIn(self.clm_user.email, clm)
        # multi_user is effective-CCA, so the CLM filter excludes them.
        self.assertNotIn(self.multi_user.email, clm)

        cu = self._emails(
            self._api(self.super_admin).get(
                self._url(self.customer_a1) + "?access_role=CUSTOMER_USER"
            )
        )
        self.assertIn(self.cu_user.email, cu)
        self.assertNotIn(self.multi_user.email, cu)

    def test_access_role_filter_invalid_returns_400(self):
        resp = self._api(self.super_admin).get(
            self._url(self.customer_a1) + "?access_role=NOPE"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "access_role_invalid")

    # ---- privacy floor -------------------------------------------------

    def test_privacy_floor_exact_fields(self):
        resp = self._api(self.super_admin).get(self._url(self.customer_a1))
        for r in self._rows(resp):
            self.assertEqual(
                set(r.keys()),
                {"id", "full_name", "email", "customer_access_role", "is_active"},
            )

    # ---- access-role EDIT (reuse the existing /access/<bid>/ PATCH) -----

    def _access_url(self, customer, user, building):
        return (
            f"/api/customers/{customer.id}/users/{user.id}"
            f"/access/{building.id}/"
        )

    def test_cca_can_edit_access_role_on_own_customer(self):
        resp = self._api(self.cca_user).patch(
            self._access_url(self.customer_a1, self.cu_user, self.building_a1),
            {"access_role": "CUSTOMER_LOCATION_MANAGER"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_pa_can_edit_own_company_customer_access(self):
        resp = self._api(self.admin_a).patch(
            self._access_url(self.customer_a1, self.cu_user, self.building_a1),
            {"access_role": "CUSTOMER_LOCATION_MANAGER"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_clm_cannot_edit_access_role(self):
        resp = self._api(self.clm_user).patch(
            self._access_url(self.customer_a1, self.cu_user, self.building_a1),
            {"access_role": "CUSTOMER_LOCATION_MANAGER"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_cu_cannot_edit_access_role(self):
        resp = self._api(self.cu_user).patch(
            self._access_url(self.customer_a1, self.clm_user, self.building_a1),
            {"access_role": "CUSTOMER_USER"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_pa_cannot_edit_cross_company_customer_access(self):
        resp = self._api(self.admin_a).patch(
            self._access_url(self.customer_b1, self.cb_cca, self.building_b1),
            {"access_role": "CUSTOMER_USER"},
            format="json",
        )
        self.assertIn(resp.status_code, (403, 404))

    def test_cca_cannot_edit_other_customer_access(self):
        resp = self._api(self.cca_user).patch(
            self._access_url(self.customer_b1, self.cb_cca, self.building_b1),
            {"access_role": "CUSTOMER_USER"},
            format="json",
        )
        self.assertIn(resp.status_code, (403, 404))
