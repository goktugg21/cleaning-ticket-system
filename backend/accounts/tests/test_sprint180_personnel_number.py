"""
Sprint 180 §4 — `StaffProfile.personnel_number`, on a serializer at last.

The column has existed since Sprint 172 §5 and the worker hour report
has printed it as "Personeelsnr." ever since — `reports/worker_hours.py`
selects `employee__staff_profile__personnel_number` and
`reports/exports.py` writes it into the CSV and the PDF. It was on **no
serializer at all**: not the read shape, not the write shape. A payroll
join key that the report joins on, the operator can see nowhere, and
nobody can enter without a database shell.

These tests pin both halves, because the two fail differently and only
one of them is caught by a filter test:

  - the READ shape must actually RENDER the field. A missing `fields`
    entry is invisible to a filter test, which issues a query and never
    serialises a row — it is exactly how a missing entry took the whole
    Extra Work page down in Sprint 173.
  - the WRITE shape must ACCEPT it, and accept a blank, because
    `blank=True` on the model means "cleared" is a real value and not an
    error.

The permission surface is unchanged, so it is asserted rather than
re-derived: the same `CanManageStaffMember` gate that guards every other
field on this endpoint guards this one, and a COMPANY_ADMIN still cannot
reach another company's staff.
"""

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from test_utils import TenantFixtureMixin


class PersonnelNumberTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.staff_a = self.make_user("staff-a-180@example.com", UserRole.STAFF)
        self.staff_b = self.make_user("staff-b-180@example.com", UserRole.STAFF)
        self.profile_a = StaffProfile.objects.create(
            user=self.staff_a, phone="", is_active=True
        )
        StaffProfile.objects.create(user=self.staff_b, phone="", is_active=True)
        # Visibility rows put each STAFF user inside their own company's
        # scope, which is what makes the cross-company assertion below a
        # real 403 rather than an accident of an empty fixture.
        BuildingStaffVisibility.objects.create(
            user=self.staff_a, building=self.building
        )
        BuildingStaffVisibility.objects.create(
            user=self.staff_b, building=self.other_building
        )

    def profile_url(self, user_id):
        return f"/api/users/{user_id}/staff-profile/"

    # ---- read ----------------------------------------------------------

    def test_the_profile_payload_renders_the_personnel_number(self):
        self.profile_a.personnel_number = "10432"
        self.profile_a.save(update_fields=["personnel_number"])

        self.authenticate(self.super_admin)
        response = self.client.get(self.profile_url(self.staff_a.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("personnel_number", response.data)
        self.assertEqual(response.data["personnel_number"], "10432")

    def test_an_unnumbered_worker_renders_an_empty_string_not_a_missing_key(
        self,
    ):
        # `blank=True, default=""` — "not filled in" has ONE
        # representation on this model, and the payload must keep it.
        self.authenticate(self.super_admin)
        response = self.client.get(self.profile_url(self.staff_a.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("personnel_number", response.data)
        self.assertEqual(response.data["personnel_number"], "")

    # ---- write ---------------------------------------------------------

    def test_a_super_admin_can_set_it(self):
        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.profile_url(self.staff_a.id),
            {"personnel_number": "A-77"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        # The response goes back through the READ serializer, so this
        # asserts the round trip, not just the database.
        self.assertEqual(response.data["personnel_number"], "A-77")
        self.profile_a.refresh_from_db()
        self.assertEqual(self.profile_a.personnel_number, "A-77")

    def test_a_company_admin_can_set_it_for_their_own_staff(self):
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.profile_url(self.staff_a.id),
            {"personnel_number": "10432"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.profile_a.refresh_from_db()
        self.assertEqual(self.profile_a.personnel_number, "10432")

    def test_it_can_be_cleared(self):
        self.profile_a.personnel_number = "10432"
        self.profile_a.save(update_fields=["personnel_number"])

        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.profile_url(self.staff_a.id),
            {"personnel_number": ""},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.profile_a.refresh_from_db()
        self.assertEqual(self.profile_a.personnel_number, "")

    def test_a_company_admin_cannot_set_it_on_another_companys_staff(self):
        # The field changes nothing about the gate; this asserts that it
        # did not open a side door into it.
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self.profile_url(self.staff_b.id),
            {"personnel_number": "SNEAK"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            StaffProfile.objects.get(user=self.staff_b).personnel_number, ""
        )
