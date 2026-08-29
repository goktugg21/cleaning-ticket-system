"""FE-5 step 0 — `can_plan` on the work-plan payload.

The undated lane's one action ("Plan vandaag") writes through
`POST /tickets/<id>/schedule/` and `POST /extra-work/bulk-dates/`, and
both refuse every role outside provider management with a 403. The
payload now says up front whether this viewer may press it, so the
button is rendered only for a viewer it can work for and a refusal can
no longer be clicked into existence.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import (
    Building,
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
from companies.models import Company, CompanyUserMembership


User = get_user_model()
PASSWORD = "StrongerTestPasswordFE5!"
WORK_PLAN_URL = "/api/tickets/work-plan/"


class CanPlanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov", slug="prov-fe5")
        cls.building = Building.objects.create(
            company=cls.company, name="B", address="B 1"
        )
        cls.admin = User.objects.create_user(
            email="ca-fe5@example.com",
            password=PASSWORD,
            role=UserRole.COMPANY_ADMIN,
            full_name="CA",
        )
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )
        cls.manager = User.objects.create_user(
            email="bm-fe5@example.com",
            password=PASSWORD,
            role=UserRole.BUILDING_MANAGER,
            full_name="BM",
        )
        CompanyUserMembership.objects.create(
            user=cls.manager, company=cls.company
        )
        BuildingManagerAssignment.objects.create(
            user=cls.manager, building=cls.building
        )
        cls.staff = User.objects.create_user(
            email="staff-fe5@example.com",
            password=PASSWORD,
            role=UserRole.STAFF,
            full_name="Staff",
        )
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.building
        )

    def _plan(self, user, **params):
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(WORK_PLAN_URL, params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_company_admin_may_plan(self):
        self.assertIs(self._plan(self.admin)["can_plan"], True)

    def test_company_admin_may_plan_on_the_team_week_too(self):
        self.assertIs(
            self._plan(self.admin, scope="company")["can_plan"], True
        )

    def test_building_manager_may_plan(self):
        self.assertIs(self._plan(self.manager)["can_plan"], True)

    def test_staff_may_not_plan(self):
        # The schedule endpoint answers STAFF with
        # `schedule_forbidden_for_role`; the lane must not offer what
        # the server will refuse.
        self.assertIs(self._plan(self.staff)["can_plan"], False)
