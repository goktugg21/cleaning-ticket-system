"""P-16 — `/api/auth/me/` says which companies you may FILE HOURS in.

The P-14 finding's persona was a building-assigned STAFF spanning two
companies: they hold NO CompanyUserMembership, so `company_ids` is []
for exactly the user whose My-hours page must resolve a company — and
P-15's fix, reading `company_ids`, healed only membership-backed users.
`timesheet_company_ids` is computed by the server from the timesheet
scope (`scope_company_ids_for_timesheets`) — the same authority the
write path enforces, so the page can never resolve a company the API
would refuse.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User, UserRole
from buildings.models import Building, BuildingStaffVisibility
from companies.models import Company, CompanyUserMembership

ME_URL = "/api/auth/me/"


class MeTimesheetCompanyIdsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="TS-A", slug="ts-a-p16")
        cls.company_b = Company.objects.create(name="TS-B", slug="ts-b-p16")
        cls.building_a = Building.objects.create(
            company=cls.company_a, name="A1"
        )
        cls.building_b = Building.objects.create(
            company=cls.company_b, name="B1"
        )
        cls.staff = User.objects.create_user(
            email="two-company-staff-p16@example.com",
            password="x",
            role=UserRole.STAFF,
        )
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.building_a
        )
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.building_b
        )
        cls.admin = User.objects.create_user(
            email="ca-p16-me@example.com",
            password="x",
            role=UserRole.COMPANY_ADMIN,
        )
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company_a
        )

    def _me(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(ME_URL)
        self.assertEqual(response.status_code, 200)
        return response.data

    def test_building_assigned_staff_gets_both_companies(self):
        data = self._me(self.staff)
        # The old field is honestly empty (no memberships)...
        self.assertEqual(data["company_ids"], [])
        # ...and the new one answers from the timesheet scope.
        self.assertEqual(
            data["timesheet_company_ids"],
            sorted([self.company_a.id, self.company_b.id]),
        )

    def test_membership_admin_gets_their_company(self):
        data = self._me(self.admin)
        self.assertEqual(data["timesheet_company_ids"], [self.company_a.id])
