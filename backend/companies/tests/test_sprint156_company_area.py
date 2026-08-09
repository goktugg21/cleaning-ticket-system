"""
Sprint 156 §1 — the company detail page's five reads.

What these tests exist to guarantee:

  1. **404, never 403, for a company out of scope.** A 403 confirms the
     id names a real company; the two answers must be indistinguishable
     (H-1, the Sprint 142.1 oracle class).
  2. **The employees list answers "who can do what, where".** A STAFF
     member attaches to a company through `BuildingStaffVisibility` and a
     BUILDING_MANAGER through `BuildingManagerAssignment` — NOT through
     `CompanyUserMembership`, which is the COMPANY_ADMIN route. Asking
     only the membership table reports zero employees for exactly the
     roles the card exists to show, and Sprint 152.1 already paid for
     that mistake once in the timesheets employee picker.
  3. **No N+1.** Each employee row carries their buildings, which is
     where an N+1 would hide. A 10-row page must cost what a 2-row page
     costs.
  4. **`User.phone`, never `StaffProfile.phone`.** The second is
     staff-only and gated by the customer's visibility policy; Sprint 154
     §K established that putting it on a provider read surface breaches
     the documented privacy floor.
"""
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import (
    Building,
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
from companies.models import CompanyUserMembership
from customers.models import Customer, CustomerBuildingMembership
from test_utils import TenantFixtureMixin


def summary_url(company_id):
    return f"/api/companies/{company_id}/summary/"


def admins_url(company_id):
    return f"/api/companies/{company_id}/admins-detail/"


def employees_url(company_id):
    return f"/api/companies/{company_id}/employees/"


def buildings_url(company_id):
    return f"/api/companies/{company_id}/buildings/"


def customers_url(company_id):
    return f"/api/companies/{company_id}/customers/"


def _rows(response):
    return response.data.get("results", response.data)


class CompanySummaryTests(TenantFixtureMixin, APITestCase):
    def test_super_admin_gets_every_count(self):
        self.authenticate(self.super_admin)
        response = self.client.get(summary_url(self.company.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for key in (
            "building_count",
            "customer_count",
            "admin_count",
            "employee_count",
            "ticket_count",
            "open_ticket_count",
            "extra_work_count",
            "open_extra_work_count",
        ):
            self.assertIn(key, response.data, f"{key} missing from the summary")
        self.assertGreaterEqual(response.data["building_count"], 1)
        self.assertGreaterEqual(response.data["customer_count"], 1)

    def test_the_counts_are_this_company_only(self):
        """Company B's rows must not appear in company A's tiles."""
        self.authenticate(self.super_admin)
        a = self.client.get(summary_url(self.company.id)).data
        b = self.client.get(summary_url(self.other_company.id)).data
        # Both companies have exactly one building in the fixture.
        self.assertEqual(a["building_count"], 1)
        self.assertEqual(b["building_count"], 1)

    def test_out_of_scope_company_is_404_not_403(self):
        """H-1. A 403 would confirm the id names a real company."""
        self.authenticate(self.company_admin)
        foreign = self.client.get(summary_url(self.other_company.id))
        fictional = self.client.get(summary_url(999_999))
        self.assertEqual(foreign.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(fictional.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(str(foreign.data), str(fictional.data))

    def test_staff_cannot_reach_the_company_page_at_all(self):
        """STAFF has NO company scope, so this is a 404 — by design.

        My first draft of this test asserted a 200 with `null` extra-work
        counts, on the assumption that a STAFF member with building
        visibility could read their own company. They cannot:
        `accounts.scoping.company_ids_for` has branches for SUPER_ADMIN,
        COMPANY_ADMIN, BUILDING_MANAGER and CUSTOMER_USER and no STAFF
        branch, so `scope_companies_for` is empty for them and the
        resolution 404s before any block runs.

        That is pre-existing and correct — the company page is a
        provider-administration surface — and widening a security-floor
        scope helper to make a UI test pass would be the tail wagging the
        dog. The test now pins the real behaviour.

        The STAFF branch in `_extra_work_counts` stays as defence in
        depth, mirroring `buildings/views_summary.py`: it costs nothing,
        and if a STAFF branch is ever added to the scope helper the
        `null`-not-`0` rule is already in place rather than being
        something a later sprint has to remember.
        """
        staff = self.make_user("staff-156@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(user=staff, building=self.building)
        self.authenticate(staff)

        real = self.client.get(summary_url(self.company.id))
        fictional = self.client.get(summary_url(999_999))
        self.assertEqual(real.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(str(real.data), str(fictional.data))


class CompanyAdminsReadTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        CompanyUserMembership.objects.get_or_create(
            user=self.company_admin, company=self.company
        )

    def test_lists_the_company_admins_with_phone(self):
        self.company_admin.phone = "+31 20 555 0101"
        self.company_admin.save(update_fields=["phone"])
        self.authenticate(self.super_admin)

        response = self.client.get(admins_url(self.company.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = next(
            r for r in _rows(response) if r["email"] == self.company_admin.email
        )
        self.assertEqual(row["phone"], "+31 20 555 0101")

    def test_never_leaks_the_gated_staff_phone(self):
        """The Sprint 154 §K privacy floor, pinned on this surface too.

        `StaffProfile.phone` is governed by the customer's
        `show_assigned_staff_phone` policy. This endpoint is a provider
        read and must carry only the ungated `User.phone`.
        """
        profile = getattr(self.company_admin, "staff_profile", None)
        if profile is not None:
            profile.phone = "+31 6 9999 0000"
            profile.save(update_fields=["phone"])
        self.company_admin.phone = "+31 20 555 0101"
        self.company_admin.save(update_fields=["phone"])

        self.authenticate(self.super_admin)
        response = self.client.get(admins_url(self.company.id))
        self.assertNotIn("+31 6 9999 0000", str(response.data))

    def test_another_companys_admin_is_not_listed(self):
        CompanyUserMembership.objects.get_or_create(
            user=self.other_company_admin, company=self.other_company
        )
        self.authenticate(self.super_admin)
        emails = {r["email"] for r in _rows(self.client.get(admins_url(self.company.id)))}
        self.assertNotIn(self.other_company_admin.email, emails)

    def test_out_of_scope_company_is_404(self):
        self.authenticate(self.company_admin)
        response = self.client.get(admins_url(self.other_company.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class CompanyEmployeesReadTests(TenantFixtureMixin, APITestCase):
    """The "who can do what, where" card."""

    def setUp(self):
        super().setUp()
        self.staff = self.make_user("staff-emp@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.staff, building=self.building
        )

    def test_staff_reached_through_building_visibility_not_membership(self):
        """The trap this list exists to avoid.

        `self.staff` has NO `CompanyUserMembership` row — a STAFF member
        never does. If this endpoint asked the membership table it would
        return an empty list for the role the card is mostly about.
        """
        self.assertFalse(
            CompanyUserMembership.objects.filter(user=self.staff).exists()
        )
        self.authenticate(self.super_admin)
        rows = _rows(self.client.get(employees_url(self.company.id)))
        self.assertIn(self.staff.email, {r["email"] for r in rows})

    def test_building_manager_is_reached_through_their_assignment(self):
        self.authenticate(self.super_admin)
        rows = _rows(self.client.get(employees_url(self.company.id)))
        self.assertIn(self.manager.email, {r["email"] for r in rows})

    def test_each_row_carries_its_buildings_and_role(self):
        self.authenticate(self.super_admin)
        rows = _rows(self.client.get(employees_url(self.company.id)))
        row = next(r for r in rows if r["email"] == self.staff.email)
        self.assertEqual(row["role"], UserRole.STAFF)
        self.assertEqual(
            [b["name"] for b in row["buildings"]], [self.building.name]
        )

    def test_a_person_on_two_buildings_appears_once_with_both(self):
        """`distinct()` is load-bearing, not tidiness.

        A manager of three buildings matches the OR three times and
        would otherwise be listed — and counted — three times.
        """
        second = Building.objects.create(
            company=self.company, name="Second site", address="Second 1"
        )
        BuildingStaffVisibility.objects.create(user=self.staff, building=second)

        self.authenticate(self.super_admin)
        rows = _rows(self.client.get(employees_url(self.company.id)))
        mine = [r for r in rows if r["email"] == self.staff.email]
        self.assertEqual(len(mine), 1, "the same person was listed twice")
        self.assertEqual(
            sorted(b["name"] for b in mine[0]["buildings"]),
            sorted([self.building.name, "Second site"]),
        )

    def test_another_companys_employee_is_not_listed(self):
        other_staff = self.make_user("staff-b@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=other_staff, building=self.other_building
        )
        self.authenticate(self.super_admin)
        emails = {
            r["email"] for r in _rows(self.client.get(employees_url(self.company.id)))
        }
        self.assertNotIn(other_staff.email, emails)

    def test_the_phone_is_the_ungated_user_field(self):
        self.staff.phone = "+31 20 555 0199"
        self.staff.save(update_fields=["phone"])
        profile = getattr(self.staff, "staff_profile", None)
        if profile is not None:
            profile.phone = "+31 6 1111 2222"
            profile.save(update_fields=["phone"])

        self.authenticate(self.super_admin)
        response = self.client.get(employees_url(self.company.id))
        row = next(r for r in _rows(response) if r["email"] == self.staff.email)
        self.assertEqual(row["phone"], "+31 20 555 0199")
        self.assertNotIn(
            "+31 6 1111 2222",
            str(response.data),
            "StaffProfile.phone leaked onto the company employees read",
        )

    def test_ten_employees_cost_the_same_as_two(self):
        """The N+1 guard. Each row's buildings are the place one hides."""
        self.authenticate(self.super_admin)

        def measure():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(employees_url(self.company.id))
            return len(ctx.captured_queries)

        # Warm-up, discarded: the first request pays one-off costs.
        measure()
        two = measure()

        for index in range(10):
            person = self.make_user(f"bulk-{index}@example.com", UserRole.STAFF)
            BuildingStaffVisibility.objects.create(
                user=person, building=self.building
            )
        many = measure()

        self.assertEqual(
            two,
            many,
            f"query count grew with the employee count ({two} -> {many}); "
            "the per-row buildings are no longer prefetched",
        )


class CompanyBuildingsAndCustomersReadTests(TenantFixtureMixin, APITestCase):
    def test_buildings_list_is_this_company_only(self):
        self.authenticate(self.super_admin)
        rows = _rows(self.client.get(buildings_url(self.company.id)))
        self.assertEqual([r["id"] for r in rows], [self.building.id])

    def test_customers_list_is_this_company_only(self):
        self.authenticate(self.super_admin)
        rows = _rows(self.client.get(customers_url(self.company.id)))
        self.assertEqual([r["id"] for r in rows], [self.customer.id])

    def test_customer_rows_carry_the_counts_the_card_renders(self):
        self.authenticate(self.super_admin)
        row = _rows(self.client.get(customers_url(self.company.id)))[0]
        self.assertIn("building_count", row)
        self.assertIn("user_count", row)
        self.assertIsInstance(row["building_count"], int)

    def test_ten_customers_cost_the_same_as_two(self):
        self.authenticate(self.super_admin)

        def measure():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(customers_url(self.company.id))
            return len(ctx.captured_queries)

        measure()
        two = measure()

        for index in range(10):
            extra = Customer.objects.create(
                company=self.company, name=f"Bulk customer {index:02d}"
            )
            CustomerBuildingMembership.objects.create(
                customer=extra, building=self.building
            )
        many = measure()

        self.assertEqual(
            two,
            many,
            f"query count grew with the customer count ({two} -> {many}); "
            "the per-customer counts are no longer annotated",
        )

    def test_out_of_scope_company_404s_on_both_lists(self):
        self.authenticate(self.company_admin)
        for url in (
            buildings_url(self.other_company.id),
            customers_url(self.other_company.id),
        ):
            self.assertEqual(
                self.client.get(url).status_code, status.HTTP_404_NOT_FOUND, url
            )


class CompanyBuildingManagerVisibilityTests(TenantFixtureMixin, APITestCase):
    """A BUILDING_MANAGER may reach the company page for their own company.

    They see it through `scope_companies_for`, and every list is scoped
    on top of that — so this is a narrower read, not a forbidden one.
    """

    def test_manager_can_read_their_own_companys_summary(self):
        """A BM's company comes from their building assignments.

        `company_ids_for` has a BUILDING_MANAGER branch (a JOIN through
        `BuildingManagerAssignment`), so unlike STAFF they DO have a
        company scope and the page resolves. Asserted as a 200 rather
        than "200 or 404" — a test that accepts either answer pins
        nothing.
        """
        BuildingManagerAssignment.objects.get_or_create(
            user=self.manager, building=self.building
        )
        self.authenticate(self.manager)
        response = self.client.get(summary_url(self.company.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["building_count"], 1)

    def test_manager_cannot_read_another_companys_summary(self):
        self.authenticate(self.manager)
        response = self.client.get(summary_url(self.other_company.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
