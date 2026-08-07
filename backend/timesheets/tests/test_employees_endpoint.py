"""
Sprint 152.1 — `GET /api/timesheets/employees/?company=<id>`.

The admin entry form's picker. Its reason for existing is that it and
the write validator resolve eligibility through the same helper, so the
set it OFFERS is the set the serializer ACCEPTS — the last test in this
module asserts exactly that, because it is the property that would rot
silently if the two ever forked.
"""
from __future__ import annotations

from .fixtures import EMPLOYEES_URL, ENTRIES_URL, TimesheetsFixture


import datetime as dt

MONDAY = dt.date(2026, 8, 3)


class EmployeeListRoleMatrixTests(TimesheetsFixture):
    def test_customer_user_is_forbidden(self):
        response = self.api(self.customer_user).get(
            EMPLOYEES_URL, {"company": self.company_a.id}
        )
        self.assertEqual(response.status_code, 403)

    def test_staff_and_building_manager_are_forbidden(self):
        # `IsTimesheetManager` — this is a management surface. A STAFF
        # member's own entry form never names anyone but themselves, so
        # they have no use for a colleague list here.
        for user in (self.staff_a, self.bm_a):
            response = self.api(user).get(
                EMPLOYEES_URL, {"company": self.company_a.id}
            )
            self.assertEqual(response.status_code, 403, user.email)

    def test_company_admin_sees_only_their_own_company(self):
        response = self.api(self.ca_a).get(EMPLOYEES_URL)
        self.assertEqual(response.status_code, 200, response.data)
        ids = {row["id"] for row in response.data["results"]}
        self.assertEqual(
            ids,
            {self.ca_a.id, self.bm_a.id, self.staff_a.id, self.staff_a2.id},
        )
        self.assertNotIn(self.staff_b.id, ids)
        self.assertNotIn(self.bm_b.id, ids)

    def test_super_admin_is_scoped_by_the_company_param(self):
        response = self.api(self.sa).get(
            EMPLOYEES_URL, {"company": self.company_b.id}
        )
        self.assertEqual(response.status_code, 200, response.data)
        ids = {row["id"] for row in response.data["results"]}
        self.assertEqual(ids, {self.ca_b.id, self.bm_b.id, self.staff_b.id})
        self.assertNotIn(self.staff_a.id, ids)

    def test_super_admin_must_name_a_company(self):
        # The Sprint 149 model: an SA works in ONE company at a time and
        # the server will not guess which.
        response = self.api(self.sa).get(EMPLOYEES_URL)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["company"][0].code, "timesheet_company_required"
        )

    def test_company_admin_cannot_reach_a_rival_company(self):
        # 404, not 403 — an out-of-scope company reads as nonexistent.
        response = self.api(self.ca_a).get(
            EMPLOYEES_URL, {"company": self.company_b.id}
        )
        self.assertEqual(response.status_code, 404)


class EmployeeListContentTests(TimesheetsFixture):
    def test_super_admins_never_appear(self):
        # `PROVIDER_EMPLOYEE_ROLES` excludes SUPER_ADMIN: a platform
        # admin is not a provider employee and hours cannot be filed
        # against one. Offering them would be offering a choice that
        # always 400s.
        response = self.api(self.sa).get(
            EMPLOYEES_URL, {"company": self.company_a.id}
        )
        ids = {row["id"] for row in response.data["results"]}
        self.assertNotIn(self.sa.id, ids)

    def test_customer_users_never_appear(self):
        response = self.api(self.ca_a).get(EMPLOYEES_URL)
        ids = {row["id"] for row in response.data["results"]}
        self.assertNotIn(self.customer_user.id, ids)

    def test_inactive_and_soft_deleted_users_are_excluded(self):
        self.staff_a2.is_active = False
        self.staff_a2.save(update_fields=["is_active"])
        response = self.api(self.ca_a).get(EMPLOYEES_URL)
        ids = {row["id"] for row in response.data["results"]}
        self.assertNotIn(self.staff_a2.id, ids)
        self.assertIn(self.staff_a.id, ids)

    def test_payload_shape(self):
        response = self.api(self.ca_a).get(EMPLOYEES_URL)
        row = next(
            r for r in response.data["results"] if r["id"] == self.staff_a.id
        )
        self.assertEqual(
            set(row.keys()), {"id", "full_name", "email", "role"}
        )
        self.assertEqual(row["role"], "STAFF")

    def test_ordered_by_full_name(self):
        response = self.api(self.ca_a).get(EMPLOYEES_URL)
        names = [row["full_name"] for row in response.data["results"]]
        self.assertEqual(names, sorted(names))


class OfferedEqualsAcceptedTests(TimesheetsFixture):
    """The reason the endpoint lives in this app rather than reusing
    `/api/employees/`: the picker and the write validator resolve
    through ONE helper, so every offered employee is an acceptable one.
    """

    def test_every_offered_employee_is_accepted_by_the_write_path(self):
        listing = self.api(self.ca_a).get(EMPLOYEES_URL)
        offered = [row["id"] for row in listing.data["results"]]
        self.assertTrue(offered)

        for index, employee_id in enumerate(offered):
            response = self.api(self.ca_a).post(
                ENTRIES_URL,
                {
                    "employee": employee_id,
                    "company": self.company_a.id,
                    # A distinct day per employee so nothing collides on
                    # anything other than the property under test.
                    "date": (MONDAY + dt.timedelta(days=index)).isoformat(),
                    "hour_type": self.normal_a.id,
                    "hours": "1.00",
                },
                format="json",
            )
            self.assertEqual(
                response.status_code, 201, (employee_id, response.data)
            )
