"""
Sprint 13C — StaffProfile.employment_type (employee category) +
provider/BM-scoped STAFF roster (Employees page backend).

Part A — employment_type:
  - Defaults to INTERNAL_STAFF on a freshly created StaffProfile.
  - SUPER_ADMIN / COMPANY_ADMIN can PATCH it to ZZP / INHUUR via
    `/api/users/<id>/staff-profile/`; an out-of-enum value -> 400.
  - BUILDING_MANAGER cannot PATCH the profile (403) — the category is
    SA/CA-managed; BM reads it via the Part B roster.

Part B — roster (`GET /api/staff/`):
  - SUPER_ADMIN lists all STAFF.
  - COMPANY_ADMIN lists STAFF in their company.
  - BUILDING_MANAGER lists ONLY staff visible in their assigned
    building(s) and NOT a staff visible only in a different building.
  - CUSTOMER_USER -> 403; STAFF -> 403.
  - `?employment_type=ZZP` returns only ZZP staff; an invalid value ->
    400 with code `employment_type_invalid`.
  - NO-LEAK: a roster row carries employment_type + building_visibility
    but NEVER internal_note / phone / any customer or pricing key, and
    building_visibility rows are scoped to the viewer's buildings.
"""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import Building, BuildingStaffVisibility
from test_utils import TenantFixtureMixin


User = get_user_model()


class StaffRosterFixtureMixin(TenantFixtureMixin):
    """
    Adds STAFF personas across two companies + an extra in-company
    building so building-scope narrowing for BM/CA is testable.

      - staff_a: Company A, visible on self.building (manager-a's
        assigned building), INTERNAL_STAFF.
      - staff_b: Company B, visible on self.other_building, ZZP.
      - staff_a2: Company A, visible ONLY on building_a2 (a second
        Company-A building the BM `manager` is NOT assigned to). Lets
        us prove BM scope excludes a same-company staff who is only
        visible outside the BM's buildings.
    """

    def setUp(self):
        super().setUp()
        self.building_a2 = Building.objects.create(
            company=self.company, name="Building A2", address="Second Street 2"
        )

        self.staff_a = self.make_user("staff-a@example.com", UserRole.STAFF)
        self.staff_b = self.make_user("staff-b@example.com", UserRole.STAFF)
        self.staff_a2 = self.make_user("staff-a2@example.com", UserRole.STAFF)

        self.profile_a = StaffProfile.objects.create(
            user=self.staff_a,
            phone="+31 6 0000 1111",
            internal_note="Secret scheduling note A",
            is_active=True,
        )
        self.profile_b = StaffProfile.objects.create(
            user=self.staff_b,
            phone="+31 6 2222 3333",
            internal_note="Secret scheduling note B",
            is_active=True,
            employment_type=StaffProfile.EmploymentType.ZZP,
        )
        self.profile_a2 = StaffProfile.objects.create(
            user=self.staff_a2, is_active=True
        )

        BuildingStaffVisibility.objects.create(
            user=self.staff_a, building=self.building
        )
        BuildingStaffVisibility.objects.create(
            user=self.staff_b, building=self.other_building
        )
        BuildingStaffVisibility.objects.create(
            user=self.staff_a2, building=self.building_a2
        )

    def profile_url(self, user_id):
        return f"/api/users/{user_id}/staff-profile/"

    ROSTER_URL = "/api/staff/"

    def roster_emails(self, response):
        results = response.data.get("results", response.data)
        return {row["email"] for row in results}

    def roster_row(self, response, email):
        results = response.data.get("results", response.data)
        for row in results:
            if row["email"] == email:
                return row
        return None


class EmploymentTypeModelTests(StaffRosterFixtureMixin, APITestCase):
    def test_default_is_internal_staff(self):
        fresh = self.make_user("staff-fresh@example.com", UserRole.STAFF)
        profile = StaffProfile.objects.create(user=fresh)
        self.assertEqual(
            profile.employment_type,
            StaffProfile.EmploymentType.INTERNAL_STAFF,
        )

    def test_read_serializer_exposes_employment_type(self):
        self.authenticate(self.super_admin)
        response = self.client.get(self.profile_url(self.staff_b.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["employment_type"],
            StaffProfile.EmploymentType.ZZP,
        )


class EmploymentTypePatchTests(StaffRosterFixtureMixin, APITestCase):
    def test_super_admin_can_set_zzp(self):
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.profile_url(self.staff_a.id),
            {"employment_type": StaffProfile.EmploymentType.ZZP},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(
            response.data["employment_type"],
            StaffProfile.EmploymentType.ZZP,
        )
        self.profile_a.refresh_from_db()
        self.assertEqual(
            self.profile_a.employment_type,
            StaffProfile.EmploymentType.ZZP,
        )

    def test_company_admin_can_set_inhuur(self):
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.profile_url(self.staff_a.id),
            {"employment_type": StaffProfile.EmploymentType.INHUUR},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.profile_a.refresh_from_db()
        self.assertEqual(
            self.profile_a.employment_type,
            StaffProfile.EmploymentType.INHUUR,
        )

    def test_invalid_value_is_rejected_400(self):
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.profile_url(self.staff_a.id),
            {"employment_type": "FREELANCE_TOTALLY_FAKE"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("employment_type", response.data)
        self.profile_a.refresh_from_db()
        self.assertEqual(
            self.profile_a.employment_type,
            StaffProfile.EmploymentType.INTERNAL_STAFF,
        )

    def test_building_manager_cannot_patch_employment_type(self):
        # BM is read-only for the category (CanManageStaffMember 403s BM
        # at the class-level role gate). BM reads it via /api/staff/.
        self.authenticate(self.manager)
        response = self.client.patch(
            self.profile_url(self.staff_a.id),
            {"employment_type": StaffProfile.EmploymentType.ZZP},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.profile_a.refresh_from_db()
        self.assertEqual(
            self.profile_a.employment_type,
            StaffProfile.EmploymentType.INTERNAL_STAFF,
        )


class StaffRosterScopeTests(StaffRosterFixtureMixin, APITestCase):
    def test_super_admin_lists_all_staff(self):
        self.authenticate(self.super_admin)
        response = self.client.get(self.ROSTER_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = self.roster_emails(response)
        self.assertEqual(
            emails,
            {
                self.staff_a.email,
                self.staff_b.email,
                self.staff_a2.email,
            },
        )

    def test_company_admin_lists_only_own_company_staff(self):
        self.authenticate(self.company_admin)
        response = self.client.get(self.ROSTER_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = self.roster_emails(response)
        # CA sees both Company-A staff (staff_a on self.building, staff_a2
        # on building_a2 — both Company A), never the Company-B staff_b.
        self.assertEqual(
            emails, {self.staff_a.email, self.staff_a2.email}
        )
        self.assertNotIn(self.staff_b.email, emails)

    def test_building_manager_lists_only_staff_in_assigned_building(self):
        # `manager` is assigned to self.building only. staff_a is visible
        # there; staff_a2 is visible only on building_a2 (same company,
        # different building) and must NOT appear; staff_b is Company B.
        self.authenticate(self.manager)
        response = self.client.get(self.ROSTER_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = self.roster_emails(response)
        self.assertEqual(emails, {self.staff_a.email})
        self.assertNotIn(self.staff_a2.email, emails)
        self.assertNotIn(self.staff_b.email, emails)

    def test_customer_user_forbidden(self):
        self.authenticate(self.customer_user)
        response = self.client.get(self.ROSTER_URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_forbidden(self):
        self.authenticate(self.staff_a)
        response = self.client.get(self.ROSTER_URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class StaffRosterEmploymentTypeFilterTests(StaffRosterFixtureMixin, APITestCase):
    def test_filter_zzp_returns_only_zzp_staff(self):
        self.authenticate(self.super_admin)
        response = self.client.get(self.ROSTER_URL, {"employment_type": "ZZP"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = self.roster_emails(response)
        self.assertEqual(emails, {self.staff_b.email})

    def test_filter_internal_staff_excludes_zzp(self):
        self.authenticate(self.super_admin)
        response = self.client.get(
            self.ROSTER_URL, {"employment_type": "INTERNAL_STAFF"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = self.roster_emails(response)
        self.assertEqual(emails, {self.staff_a.email, self.staff_a2.email})
        self.assertNotIn(self.staff_b.email, emails)

    def test_invalid_filter_value_400_with_stable_code(self):
        self.authenticate(self.super_admin)
        response = self.client.get(
            self.ROSTER_URL, {"employment_type": "NONSENSE"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("code"), "employment_type_invalid")


class StaffRosterNoLeakTests(StaffRosterFixtureMixin, APITestCase):
    # Provider-internal keys that must NEVER appear on a roster row.
    FORBIDDEN_KEYS = (
        "internal_note",
        "phone",
        "customer",
        "customers",
        "customer_id",
        "price",
        "pricing",
        "unit_price",
        "vat_pct",
    )

    def test_super_admin_row_has_category_and_visibility_but_no_leak(self):
        self.authenticate(self.super_admin)
        response = self.client.get(self.ROSTER_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = self.roster_row(response, self.staff_a.email)
        self.assertIsNotNone(row)
        # Present: the category + scoped visibility.
        self.assertIn("employment_type", row)
        self.assertIn("building_visibility", row)
        self.assertEqual(
            row["employment_type"],
            StaffProfile.EmploymentType.INTERNAL_STAFF,
        )
        self.assertTrue(row["has_staff_profile"])
        self.assertTrue(row["staff_profile_active"])
        # Absent: every provider-internal / pricing / customer key.
        for key in self.FORBIDDEN_KEYS:
            self.assertNotIn(
                key,
                row,
                f"roster row must not leak `{key}` (privacy floor)",
            )

    def test_building_visibility_rows_scoped_to_viewer_building(self):
        # staff_a holds visibility on self.building AND (we add) on
        # building_a2. A BM assigned only to self.building must see the
        # self.building visibility row but NOT the building_a2 row.
        BuildingStaffVisibility.objects.create(
            user=self.staff_a, building=self.building_a2
        )
        self.authenticate(self.manager)
        response = self.client.get(self.ROSTER_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = self.roster_row(response, self.staff_a.email)
        self.assertIsNotNone(row)
        seen_building_ids = {
            bv["building_id"] for bv in row["building_visibility"]
        }
        self.assertIn(self.building.id, seen_building_ids)
        self.assertNotIn(
            self.building_a2.id,
            seen_building_ids,
            "BM must not see a staff's visibility row for a building "
            "outside the BM's scope",
        )
        # Sanity: the exposed row carries only the three scoped keys.
        for bv in row["building_visibility"]:
            self.assertEqual(
                set(bv.keys()),
                {"building_id", "building_name", "visibility_level"},
            )

    def test_super_admin_sees_all_visibility_rows(self):
        BuildingStaffVisibility.objects.create(
            user=self.staff_a, building=self.building_a2
        )
        self.authenticate(self.super_admin)
        response = self.client.get(self.ROSTER_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = self.roster_row(response, self.staff_a.email)
        seen_building_ids = {
            bv["building_id"] for bv in row["building_visibility"]
        }
        self.assertEqual(
            seen_building_ids, {self.building.id, self.building_a2.id}
        )

    def test_profile_only_staff_without_visibility_appears_for_super_admin(self):
        # A STAFF user with a profile but zero BSV rows is invisible to
        # CA/BM (no building overlap) but SUPER_ADMIN still lists them.
        lonely = self.make_user("staff-lonely@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=lonely)
        self.authenticate(self.super_admin)
        response = self.client.get(self.ROSTER_URL)
        emails = self.roster_emails(response)
        self.assertIn(lonely.email, emails)
        row = self.roster_row(response, lonely.email)
        self.assertEqual(row["building_visibility"], [])
        self.assertTrue(row["has_staff_profile"])
