"""
Sprint 28 Batch 15.5 — `scope_summary` field on the admin Users list.

`GET /api/users/` rows carry a short, role-shaped scope tag that the
admin Users page renders in a new column. The tag is a small dict —
``{"label": <enum-like str>, "count": int}`` — so the frontend can
i18n the label and format the number without parsing English copy:

  - SUPER_ADMIN → ``{"label": "all", "count": -1}`` (sentinel; rendered
    as "All companies").
  - COMPANY_ADMIN → ``{"label": "companies", "count": N}`` over
    ``CompanyUserMembership``.
  - BUILDING_MANAGER → ``{"label": "buildings", "count": N}`` over
    ``BuildingManagerAssignment``.
  - STAFF → ``{"label": "buildings", "count": N}`` over
    ``BuildingStaffVisibility``.
  - CUSTOMER_USER → ``{"label": "customers", "count": N}`` over
    ``CustomerUserMembership``.

This is an additive, read-only surface — no new permission keys, no
role enum changes, no model edits.
"""

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import (
    Building,
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserMembership,
)
from test_utils import TenantFixtureMixin


class UserScopeSummaryTests(TenantFixtureMixin, APITestCase):
    URL = "/api/users/"

    def _row_for(self, response, user_id):
        rows = response.data.get("results", response.data)
        for row in rows:
            if row["id"] == user_id:
                return row
        self.fail(f"user {user_id} not present in /api/users/ payload")

    # ---- SUPER_ADMIN -------------------------------------------------------

    def test_super_admin_returns_all_sentinel(self):
        self.authenticate(self.super_admin)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = self._row_for(response, self.super_admin.id)
        self.assertEqual(row["scope_summary"], {"label": "all", "count": -1})

    # ---- COMPANY_ADMIN -----------------------------------------------------

    def test_company_admin_counts_company_memberships(self):
        # Base fixture already gives self.company_admin one
        # CompanyUserMembership on self.company. Add a second company
        # + membership so we can verify the count is the real row count
        # (not hardcoded to 1).
        extra_company = Company.objects.create(
            name="Company C", slug="company-c"
        )
        CompanyUserMembership.objects.create(
            user=self.company_admin, company=extra_company
        )

        self.authenticate(self.super_admin)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = self._row_for(response, self.company_admin.id)
        self.assertEqual(
            row["scope_summary"], {"label": "companies", "count": 2}
        )

    # ---- BUILDING_MANAGER --------------------------------------------------

    def test_building_manager_counts_building_assignments(self):
        # self.manager already has one BuildingManagerAssignment on
        # self.building. Add two more so the count reflects three
        # distinct rows.
        extra_building_1 = Building.objects.create(
            company=self.company, name="Wing North"
        )
        extra_building_2 = Building.objects.create(
            company=self.company, name="Wing South"
        )
        BuildingManagerAssignment.objects.create(
            user=self.manager, building=extra_building_1
        )
        BuildingManagerAssignment.objects.create(
            user=self.manager, building=extra_building_2
        )

        self.authenticate(self.super_admin)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = self._row_for(response, self.manager.id)
        self.assertEqual(
            row["scope_summary"], {"label": "buildings", "count": 3}
        )

    # ---- STAFF -------------------------------------------------------------

    def test_staff_counts_building_visibility_rows(self):
        # Base fixture has no STAFF user; build one with five
        # BuildingStaffVisibility rows so we can prove the resolver hits
        # the `building_visibility` reverse accessor, not (e.g.) the
        # building-manager one.
        staff_user = self.make_user(
            "staff-scope@example.com", UserRole.STAFF
        )
        for index in range(5):
            building = Building.objects.create(
                company=self.company,
                name=f"Staff Building {index}",
            )
            BuildingStaffVisibility.objects.create(
                user=staff_user, building=building
            )

        self.authenticate(self.super_admin)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = self._row_for(response, staff_user.id)
        self.assertEqual(
            row["scope_summary"], {"label": "buildings", "count": 5}
        )

    # ---- CUSTOMER_USER -----------------------------------------------------

    def test_customer_user_counts_customer_memberships(self):
        # self.customer_user already has exactly one
        # CustomerUserMembership in the base fixture, so this test
        # exercises the "1 customer" copy path that the frontend will
        # render most often in pilot data.
        self.authenticate(self.super_admin)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = self._row_for(response, self.customer_user.id)
        self.assertEqual(
            row["scope_summary"], {"label": "customers", "count": 1}
        )

    def test_customer_user_with_multiple_memberships_counts_all(self):
        # Multi-customer CUSTOMER_USER — the same login is attached to
        # two distinct Customer organisations inside self.company. The
        # count must equal 2, not 1.
        extra_customer = Customer.objects.create(
            company=self.company,
            building=self.building,
            name="Customer A2",
            contact_email="customer-a2@example.com",
        )
        CustomerBuildingMembership.objects.create(
            customer=extra_customer, building=self.building
        )
        CustomerUserMembership.objects.create(
            user=self.customer_user, customer=extra_customer
        )

        self.authenticate(self.super_admin)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = self._row_for(response, self.customer_user.id)
        self.assertEqual(
            row["scope_summary"], {"label": "customers", "count": 2}
        )
