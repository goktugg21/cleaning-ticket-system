"""Tests for GET /api/buildings/<id>/eligible-crew/.

The endpoint feeds the planned-work recurring-job form's default crew
pickers BEFORE any ticket exists. Eligibility mirrors the recurring-job
write validation (RecurringJobWriteSerializer):
  - staff    = role=STAFF users with BuildingStaffVisibility for the building
  - managers = role=BUILDING_MANAGER users with BuildingManagerAssignment

Provider-management only (SA / CA / scoped BM); STAFF + CUSTOMER_USER 403.
Out-of-scope provider actors get a 404 (anti-enumeration).
"""
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import Building, BuildingStaffVisibility
from test_utils import TenantFixtureMixin


class BuildingEligibleCrewTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # STAFF with visibility on building A (company A).
        self.staff = self.make_user("staff-a@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.staff, building=self.building
        )
        # STAFF with visibility only on the OTHER building (company B) —
        # must never surface for building A.
        self.other_staff = self.make_user("staff-b@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.other_staff, building=self.other_building
        )
        # STAFF with no visibility row anywhere.
        self.unscoped_staff = self.make_user(
            "staff-none@example.com", UserRole.STAFF
        )

    def url(self, building_id):
        return f"/api/buildings/{building_id}/eligible-crew/"

    # ---- access matrix --------------------------------------------------

    def test_super_admin_sees_staff_and_managers_any_building(self):
        self.authenticate(self.super_admin)
        resp = self.client.get(self.url(self.building.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertIn(
            self.staff.id, {r["id"] for r in resp.data["staff"]}
        )
        self.assertIn(
            self.manager.id, {r["id"] for r in resp.data["managers"]}
        )
        # SA can also read another company's building.
        resp_other = self.client.get(self.url(self.other_building.id))
        self.assertEqual(resp_other.status_code, status.HTTP_200_OK)
        self.assertIn(
            self.other_staff.id,
            {r["id"] for r in resp_other.data["staff"]},
        )
        self.assertIn(
            self.other_manager.id,
            {r["id"] for r in resp_other.data["managers"]},
        )

    def test_company_admin_sees_eligible_crew_own_building(self):
        self.authenticate(self.company_admin)
        resp = self.client.get(self.url(self.building.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertIn(self.staff.id, {r["id"] for r in resp.data["staff"]})
        self.assertIn(
            self.manager.id, {r["id"] for r in resp.data["managers"]}
        )

    def test_company_admin_out_of_scope_404(self):
        self.authenticate(self.company_admin)
        resp = self.client.get(self.url(self.other_building.id))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_building_manager_assigned_sees_eligible_crew(self):
        self.authenticate(self.manager)
        resp = self.client.get(self.url(self.building.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertIn(self.staff.id, {r["id"] for r in resp.data["staff"]})
        self.assertIn(
            self.manager.id, {r["id"] for r in resp.data["managers"]}
        )

    def test_building_manager_out_of_scope_404(self):
        self.authenticate(self.manager)
        resp = self.client.get(self.url(self.other_building.id))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_forbidden(self):
        self.authenticate(self.staff)
        resp = self.client.get(self.url(self.building.id))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_user_forbidden(self):
        self.authenticate(self.customer_user)
        resp = self.client.get(self.url(self.building.id))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    # ---- content correctness -------------------------------------------

    def test_staff_list_only_includes_visibility_users_for_building(self):
        self.authenticate(self.super_admin)
        resp = self.client.get(self.url(self.building.id))
        staff_ids = {r["id"] for r in resp.data["staff"]}
        self.assertIn(self.staff.id, staff_ids)
        # STAFF whose visibility is on another building is excluded.
        self.assertNotIn(self.other_staff.id, staff_ids)
        # STAFF with no visibility row at all is excluded.
        self.assertNotIn(self.unscoped_staff.id, staff_ids)
        # A manager never leaks into the staff list.
        self.assertNotIn(self.manager.id, staff_ids)

    def test_managers_list_only_includes_assignment_users_for_building(self):
        self.authenticate(self.super_admin)
        resp = self.client.get(self.url(self.building.id))
        manager_ids = {r["id"] for r in resp.data["managers"]}
        self.assertIn(self.manager.id, manager_ids)
        # A BM assigned to another building is excluded.
        self.assertNotIn(self.other_manager.id, manager_ids)
        # A staff user never leaks into the managers list.
        self.assertNotIn(self.staff.id, manager_ids)

    def test_empty_crew_returns_empty_arrays(self):
        empty_building = Building.objects.create(
            company=self.company, name="Empty Building A"
        )
        self.authenticate(self.company_admin)
        resp = self.client.get(self.url(empty_building.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["staff"], [])
        self.assertEqual(resp.data["managers"], [])

    def test_row_shape_is_id_full_name_email(self):
        self.authenticate(self.super_admin)
        resp = self.client.get(self.url(self.building.id))
        row = next(r for r in resp.data["staff"] if r["id"] == self.staff.id)
        self.assertEqual(set(row.keys()), {"id", "full_name", "email"})
        self.assertEqual(row["email"], "staff-a@example.com")

    def test_unauthenticated_rejected(self):
        resp = self.client.get(self.url(self.building.id))
        self.assertIn(
            resp.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
