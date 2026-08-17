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

    # ---- Sprint 187B §2 — company identity + the company filter -------

    def test_every_row_names_the_company_that_employs_it(self):
        """The field is rendered, for each of the three roles this
        directory lists, by the endpoint that actually serves it.

        A filter test would not catch a missing `fields` entry — that is
        what took the Extra Work page down in Sprint 173 — so this reads
        the rendered row.
        """
        by_email = {
            r["email"]: r
            for r in self._rows(self._api(self.super_admin).get(URL))
        }
        self.assertEqual(
            by_email[self.admin_a.email]["companies"], ["Emp Co A"]
        )
        self.assertEqual(
            by_email[self.manager_b.email]["companies"], ["Emp Co B"]
        )
        self.assertEqual(
            by_email[self.staff_a.email]["companies"], ["Emp Co A"]
        )

    def test_a_person_in_two_companies_names_both_once(self):
        """Company identity is a SET, not a row count.

        A building manager assigned to several buildings of one company
        must name it once; one assigned across two companies must name
        both. `company_ids_for` carries a .distinct() for this same
        fan-out on these same relations.
        """
        second_a = Building.objects.create(
            company=self.company_a, name="Emp A2"
        )
        BuildingManagerAssignment.objects.create(
            user=self.manager_a, building=second_a
        )
        BuildingManagerAssignment.objects.create(
            user=self.manager_a, building=self.building_b
        )
        row = next(
            r
            for r in self._rows(self._api(self.super_admin).get(URL))
            if r["email"] == self.manager_a.email
        )
        self.assertEqual(row["companies"], ["Emp Co A", "Emp Co B"])

    def test_company_filter_narrows_for_a_super_admin(self):
        emails = self._emails(
            self._api(self.super_admin).get(f"{URL}?company={self.company_a.id}")
        )
        self.assertIn(self.admin_a.email, emails)
        self.assertIn(self.staff_a.email, emails)
        self.assertNotIn(self.admin_b.email, emails)
        self.assertNotIn(self.staff_b.email, emails)

    def test_company_filter_invalid_returns_400_with_a_named_code(self):
        resp = self._api(self.super_admin).get(URL + "?company=NOPE")
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.data["code"], "company_invalid")

    def test_a_company_admin_cannot_read_another_company_by_passing_its_id(
        self,
    ):
        """H-1/H-2. The parameter INTERSECTS with the caller's scope; it
        never replaces it.

        admin_a holds company A only. Passing company B's id must narrow
        A's scope to nothing — never return B's people — and must not
        signal that B exists, which is why this asserts 200-with-no-rows
        rather than a 400 or a 404. An error code here would itself
        confirm the id.
        """
        resp = self._api(self.admin_a).get(f"{URL}?company={self.company_b.id}")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(self._emails(resp), set())

    def test_a_company_admin_passing_its_own_id_still_sees_its_own_people(
        self,
    ):
        """The control for the test above.

        Without it, an implementation that returned nothing for EVERY
        ?company= value would pass the cross-tenant test while being
        completely broken.
        """
        emails = self._emails(
            self._api(self.admin_a).get(f"{URL}?company={self.company_a.id}")
        )
        self.assertIn(self.admin_a.email, emails)
        self.assertIn(self.staff_a.email, emails)
        self.assertNotIn(self.admin_b.email, emails)

    def test_an_unknown_company_id_is_empty_not_an_error(self):
        """An id nobody holds must look exactly like an id with no
        employees. A 404 would leak which ids are real."""
        resp = self._api(self.admin_a).get(f"{URL}?company=99999999")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(self._emails(resp), set())

    def test_naming_the_companies_costs_a_constant_number_of_queries(self):
        """This endpoint is UnboundedPagination — it returns the WHOLE
        workforce in one response. A per-row company lookup would be an
        N+1 across every provider employee in the system, so the cost is
        pinned rather than assumed.

        Asserted as constant across two very different result sizes
        rather than as one magic number, because the number itself is an
        implementation detail and a hardcoded one would be rewritten to
        whatever the code happened to do.
        """
        # Warm-up request first: the very first call in a test can carry
        # one-off queries (session/content-type lookups) that would make
        # the baseline artificially high and the comparison flaky.
        self._count_queries_for(self.super_admin)
        baseline = self._count_queries_for(self.super_admin)

        # Twelve more employees across both companies.
        for index in range(12):
            extra = _mk(f"emp-bulk-{index}@example.com", UserRole.STAFF)
            StaffProfile.objects.create(
                user=extra,
                employment_type=StaffProfile.EmploymentType.INTERNAL_STAFF,
            )
            BuildingStaffVisibility.objects.create(
                user=extra,
                building=self.building_a if index % 2 else self.building_b,
            )

        grown = self._count_queries_for(self.super_admin)
        self.assertEqual(
            baseline,
            grown,
            f"query count grew with the number of employees: "
            f"{baseline} -> {grown} (N+1)",
        )

    def _count_queries_for(self, user):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        client = self._api(user)
        with CaptureQueriesContext(connection) as ctx:
            resp = client.get(URL)
            self.assertEqual(resp.status_code, 200, resp.data)
            # Read the rows INSIDE the context: any lazy query the
            # serializer defers would otherwise fire after it closed and
            # go uncounted, which is exactly the N+1 being measured.
            rows = self._rows(resp)
            self.assertTrue(rows, "no rows to measure")
            self.assertTrue(all("companies" in r for r in rows))
        return len(ctx.captured_queries)

    def test_staff_and_customer_forbidden(self):
        self.assertEqual(self._api(self.staff_a).get(URL).status_code, 403)
        self.assertEqual(self._api(self.cust_user).get(URL).status_code, 403)

    # ---- privacy floor -------------------------------------------------

    def test_privacy_floor_exact_fields(self):
        """The allow-list for `/api/employees/`. Read gate is
        `IsProviderRosterReader` — SUPER_ADMIN, COMPANY_ADMIN and
        BUILDING_MANAGER; STAFF and customer users are 403.

        Sprint 154 §K/§I.1 added `phone`, and the addition is
        DELIBERATE — recorded here rather than left to a reader to
        infer from a diff:

          * It is `User.phone`, the account's own contact number, added
            in `accounts.0009`. It is ungated by design and is the same
            class of datum as `email`, which this surface has always
            exposed.
          * It is NOT `StaffProfile.phone`. That one is STAFF-only and
            its visibility is governed by
            `Customer.show_assigned_staff_phone` / the
            CustomerCompanyPolicy mirror, and it remains forbidden here
            — see the assertion below, which is the half of this floor
            that must never be relaxed.

        Sprint 187B §2 added `companies`, and this assertion failing is
        exactly how that addition was noticed — the mechanism working,
        not the mechanism in the way. The amendment in one sentence:
        **a provider company name is not customer linkage** — the floor
        bans naming the CUSTOMERS a person is tied to, while this names
        the PROVIDER that employs them, which is the page's whole
        purpose. No customer and no building is named by it.

        Everything else the floor exists to keep out — `internal_note`,
        `StaffProfile.phone`, customer linkage, any pricing field — is
        still absent, and the set below is still EXACT (a subset check
        would defeat the whole point), so the next field cannot arrive
        here unnoticed either.
        """
        resp = self._api(self.super_admin).get(URL)
        rows = self._rows(resp)
        self.assertTrue(rows, "no rows to assert the privacy floor against")
        for r in rows:
            self.assertEqual(
                set(r.keys()),
                {
                    "id",
                    "full_name",
                    "email",
                    "phone",
                    "role",
                    "employment_type",
                    "companies",
                    "is_active",
                },
            )

    def test_privacy_floor_never_exposes_the_gated_staff_phone(self):
        """The half of the floor that must never be relaxed.

        `StaffProfile.phone` is a DIFFERENT field from `User.phone` and
        is customer-visibility-gated. A staff member with BOTH set must
        surface only the ungated one on this directory.
        """
        profile = self.staff_a.staff_profile
        profile.phone = "+31 6 9999 0000"
        profile.save(update_fields=["phone"])
        self.staff_a.phone = "+31 20 555 0100"
        self.staff_a.save(update_fields=["phone"])

        resp = self._api(self.super_admin).get(URL)
        row = next(
            r for r in self._rows(resp) if r["email"] == self.staff_a.email
        )
        self.assertEqual(row["phone"], "+31 20 555 0100")
        self.assertNotIn(
            "+31 6 9999 0000",
            str(resp.data),
            "StaffProfile.phone leaked onto the employees directory",
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
