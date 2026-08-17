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
    CustomerUserBuildingAccess,
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


class CustomerAccessRoleProjectionTests(TenantFixtureMixin, APITestCase):
    """
    Sprint 2c follow-up — `customer_access_role` field on the admin Users
    list: the user's single HIGHEST effective customer access role
    (CUSTOMER_COMPANY_ADMIN > CUSTOMER_LOCATION_MANAGER > CUSTOMER_USER),
    company-scoped to the viewer; ``None`` for provider users / no in-scope
    active grant. Additive, read-only — no model change.
    """

    URL = "/api/users/"

    def _row_for(self, response, user_id):
        rows = response.data.get("results", response.data)
        for row in rows:
            if row["id"] == user_id:
                return row
        self.fail(f"user {user_id} not present in /api/users/ payload")

    def test_provider_users_have_null_access_role(self):
        staff = self.make_user("staff-car@example.com", UserRole.STAFF)
        self.authenticate(self.super_admin)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for user in (self.super_admin, self.company_admin, self.manager, staff):
            self.assertIsNone(
                self._row_for(response, user.id)["customer_access_role"]
            )

    def test_customer_user_default_role(self):
        # Base fixture: customer_user has one active CUBA with the default
        # CUSTOMER_USER access role.
        self.authenticate(self.super_admin)
        response = self.client.get(self.URL)
        row = self._row_for(response, self.customer_user.id)
        self.assertEqual(row["customer_access_role"], "CUSTOMER_USER")

    def test_highest_role_wins_across_buildings(self):
        # Same user, three buildings, three roles -> the single HIGHEST
        # (CUSTOMER_COMPANY_ADMIN) is returned.
        AccessRole = CustomerUserBuildingAccess.AccessRole
        membership = CustomerUserMembership.objects.get(
            user=self.customer_user, customer=self.customer
        )
        for name, role in (
            ("Wing LM", AccessRole.CUSTOMER_LOCATION_MANAGER),
            ("Wing CCA", AccessRole.CUSTOMER_COMPANY_ADMIN),
        ):
            b = Building.objects.create(company=self.company, name=name)
            CustomerBuildingMembership.objects.create(
                customer=self.customer, building=b
            )
            CustomerUserBuildingAccess.objects.create(
                membership=membership, building=b, access_role=role
            )

        self.authenticate(self.super_admin)
        response = self.client.get(self.URL)
        row = self._row_for(response, self.customer_user.id)
        self.assertEqual(row["customer_access_role"], "CUSTOMER_COMPANY_ADMIN")

    def test_location_manager_beats_customer_user(self):
        AccessRole = CustomerUserBuildingAccess.AccessRole
        membership = CustomerUserMembership.objects.get(
            user=self.customer_user, customer=self.customer
        )
        extra = Building.objects.create(company=self.company, name="Wing LM2")
        CustomerBuildingMembership.objects.create(
            customer=self.customer, building=extra
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=extra,
            access_role=AccessRole.CUSTOMER_LOCATION_MANAGER,
        )
        self.authenticate(self.super_admin)
        response = self.client.get(self.URL)
        row = self._row_for(response, self.customer_user.id)
        self.assertEqual(
            row["customer_access_role"], "CUSTOMER_LOCATION_MANAGER"
        )

    def test_inactive_grant_excluded(self):
        # A disabled grant must not count. customer_user's only grant
        # becomes inactive -> None.
        access = CustomerUserBuildingAccess.objects.get(
            membership__user=self.customer_user
        )
        access.access_role = (
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER
        )
        access.is_active = False
        access.save(update_fields=["access_role", "is_active"])

        self.authenticate(self.super_admin)
        response = self.client.get(self.URL)
        row = self._row_for(response, self.customer_user.id)
        self.assertIsNone(row["customer_access_role"])

    def test_company_scoped_to_viewer(self):
        # Codex scenario: customer_user has a CUSTOMER_USER grant under
        # company A (base fixture) AND a CUSTOMER_COMPANY_ADMIN grant under
        # company B. A company-A admin must see only the A role; a super
        # admin sees the highest across both.
        AccessRole = CustomerUserBuildingAccess.AccessRole
        cross_customer = Customer.objects.create(
            company=self.other_company,
            building=self.other_building,
            name="Cross B",
            contact_email="cross-b@example.com",
        )
        CustomerBuildingMembership.objects.create(
            customer=cross_customer, building=self.other_building
        )
        m_b = CustomerUserMembership.objects.create(
            user=self.customer_user, customer=cross_customer
        )
        CustomerUserBuildingAccess.objects.create(
            membership=m_b,
            building=self.other_building,
            access_role=AccessRole.CUSTOMER_COMPANY_ADMIN,
        )

        # Super: highest across both companies = CCA.
        self.authenticate(self.super_admin)
        response = self.client.get(self.URL)
        self.assertEqual(
            self._row_for(response, self.customer_user.id)[
                "customer_access_role"
            ],
            "CUSTOMER_COMPANY_ADMIN",
        )

        # Company-A admin: only the in-company grant is visible = CUSTOMER_USER.
        self.authenticate(self.company_admin)
        response = self.client.get(self.URL)
        self.assertEqual(
            self._row_for(response, self.customer_user.id)[
                "customer_access_role"
            ],
            "CUSTOMER_USER",
        )


# ---------------------------------------------------------------------------
# Sprint 187B §1 — WHICH companies, beside scope_summary's HOW MANY
# ---------------------------------------------------------------------------


class UserCompaniesFieldTests(TenantFixtureMixin, APITestCase):
    """`companies` names the companies a user belongs to.

    A sibling field rather than an extension of `scope_summary`: that
    field is pinned above by exact dict equality in six places, and more
    importantly its `count` means a different thing per role (buildings
    for a BM), so company names inside it would put two axes in one
    object. See `UserListSerializer.get_companies`.
    """

    URL = "/api/users/"

    def _row_for(self, response, user_id):
        rows = response.data.get("results", response.data)
        for row in rows:
            if row["id"] == user_id:
                return row
        self.fail(f"user {user_id} not present in /api/users/ payload")

    def test_the_list_renders_the_field_for_every_role(self):
        """Reads the RENDERED row, per role. A filter test cannot catch a
        missing `fields` entry — that is what took the Extra Work page
        down in Sprint 173."""
        self.authenticate(self.super_admin)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(
            self._row_for(response, self.company_admin.id)["companies"],
            {"all": False, "names": ["Company A"]},
        )
        self.assertEqual(
            self._row_for(response, self.manager.id)["companies"],
            {"all": False, "names": ["Company A"]},
        )
        self.assertEqual(
            self._row_for(response, self.other_manager.id)["companies"],
            {"all": False, "names": ["Company B"]},
        )

    def test_a_super_admin_returns_the_all_sentinel(self):
        """Kept rendering as "All companies" exactly as the scope chip
        already does for this role — a SUPER_ADMIN holds no membership
        row, so a names list would be empty and read as "belongs to
        nothing", which is the opposite of the truth."""
        self.authenticate(self.super_admin)
        row = self._row_for(
            self.client.get(self.URL), self.super_admin.id
        )
        self.assertEqual(row["companies"], {"all": True, "names": []})

    def test_scope_summary_is_untouched(self):
        """The whole reason this is a sibling field. If `scope_summary`
        had been extended, this exact-equality assertion — and the five
        like it above — would have had to be rewritten."""
        self.authenticate(self.super_admin)
        row = self._row_for(self.client.get(self.URL), self.company_admin.id)
        self.assertEqual(row["scope_summary"], {"label": "companies", "count": 1})

    def test_many_companies_are_named_once_each_and_sorted(self):
        """A user can belong to MANY companies — that is the point of
        company_memberships. Names are a SET: a BM assigned to several
        buildings of one company names it once."""
        CompanyUserMembership.objects.create(
            user=self.company_admin, company=self.other_company
        )
        second_a = Building.objects.create(
            company=self.company, name="Building A2"
        )
        BuildingManagerAssignment.objects.create(
            user=self.manager, building=second_a
        )

        self.authenticate(self.super_admin)
        response = self.client.get(self.URL)
        self.assertEqual(
            self._row_for(response, self.company_admin.id)["companies"],
            {"all": False, "names": ["Company A", "Company B"]},
        )
        self.assertEqual(
            self._row_for(response, self.manager.id)["companies"],
            {"all": False, "names": ["Company A"]},
        )

    def test_a_staff_user_names_the_company_of_its_visible_buildings(self):
        staff = self.make_user("staff-a@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=staff, building=self.building
        )
        self.authenticate(self.super_admin)
        row = self._row_for(self.client.get(self.URL), staff.id)
        self.assertEqual(row["companies"], {"all": False, "names": ["Company A"]})

    def test_a_customer_user_names_the_provider_behind_its_customer(self):
        """Deliberate: the page asks "whose people am I looking at", and
        for a customer user the answer is the provider that serves them.
        It names no CUSTOMER, so it is not customer linkage.

        No membership is created here: `TenantFixtureMixin.setUp` already
        links `customer_user` to `customer` (which is under `company`).
        Creating it again violates the (customer, user) unique constraint.
        """
        self.authenticate(self.super_admin)
        row = self._row_for(self.client.get(self.URL), self.customer_user.id)
        self.assertEqual(row["companies"], {"all": False, "names": ["Company A"]})

    def test_naming_the_companies_costs_a_constant_number_of_queries(self):
        """§1a's requirement: the new field must ride the EXISTING
        prefetch. Asserted as constant across a small and a large list
        rather than as one magic number — a hardcoded number just gets
        rewritten to whatever the code happens to do, while a constant
        across sizes is the actual claim ("no N+1")."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def count_queries():
            with CaptureQueriesContext(connection) as ctx:
                response = self.client.get(self.URL)
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                rows = response.data.get("results", response.data)
                self.assertTrue(rows, "no rows to measure")
                # Read the field INSIDE the context: a lazily-deferred
                # query would otherwise fire after it closed, uncounted.
                self.assertTrue(all("companies" in r for r in rows))
            return len(ctx.captured_queries)

        self.authenticate(self.super_admin)
        # Warm-up: the first request of a test can carry one-off queries
        # that would make the baseline artificially high and this flaky.
        count_queries()
        baseline = count_queries()

        for index in range(12):
            extra = self.make_user(
                f"bulk-{index}@example.com", UserRole.BUILDING_MANAGER
            )
            BuildingManagerAssignment.objects.create(
                user=extra,
                building=self.building if index % 2 else self.other_building,
            )

        grown = count_queries()
        self.assertEqual(
            baseline,
            grown,
            f"query count grew with the number of users: "
            f"{baseline} -> {grown} (N+1)",
        )


class UserCompanyFilterTests(TenantFixtureMixin, APITestCase):
    """Sprint 187B §1b — `?company=<id>` narrows; it never widens."""

    URL = "/api/users/"

    def _emails(self, response):
        rows = response.data.get("results", response.data)
        return {row["email"] for row in rows}

    def test_a_super_admin_can_narrow_to_one_company(self):
        self.authenticate(self.super_admin)
        emails = self._emails(
            self.client.get(f"{self.URL}?company={self.company.id}")
        )
        self.assertIn(self.company_admin.email, emails)
        self.assertIn(self.manager.email, emails)
        self.assertNotIn(self.other_company_admin.email, emails)
        self.assertNotIn(self.other_manager.email, emails)

    def test_a_company_admin_cannot_read_another_company_by_passing_its_id(
        self,
    ):
        """H-1/H-2, and a P0 if it is wrong.

        The company_admin holds Company A only. Passing Company B's id
        must narrow their own scope to nothing — never return B's users
        — and must not reveal that B exists, which is why this asserts
        200-with-no-rows rather than an error. A 400 or 404 here would
        itself confirm the id.
        """
        self.authenticate(self.company_admin)
        response = self.client.get(f"{self.URL}?company={self.other_company.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = self._emails(response)
        self.assertNotIn(self.other_company_admin.email, emails)
        self.assertNotIn(self.other_manager.email, emails)
        self.assertEqual(emails, set())

    def test_a_company_admin_passing_its_own_id_still_sees_its_own_people(self):
        """The control. Without it, an implementation returning nothing
        for EVERY ?company= value would pass the test above while being
        entirely broken."""
        self.authenticate(self.company_admin)
        emails = self._emails(
            self.client.get(f"{self.URL}?company={self.company.id}")
        )
        self.assertIn(self.company_admin.email, emails)
        self.assertNotIn(self.other_company_admin.email, emails)

    def test_a_junk_value_cannot_500_the_page(self):
        """Tolerant parse, matching the other list endpoints: junk is
        ignored rather than raising. The requirement is that it is never
        a server error."""
        self.authenticate(self.super_admin)
        response = self.client.get(f"{self.URL}?company=NOPE")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(self.company_admin.email, self._emails(response))

    def test_an_unknown_company_id_is_empty_not_an_error(self):
        self.authenticate(self.super_admin)
        response = self.client.get(f"{self.URL}?company=99999999")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._emails(response), set())

    def test_the_filter_matches_all_four_membership_axes(self):
        """The filter and the `companies` column must agree about what
        "belongs to" means, so it tests the same four axes the serializer
        reads: company membership, BM assignment, staff visibility and
        the provider behind a customer membership."""
        staff = self.make_user("staff-axis@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=staff, building=self.building
        )
        # `customer_user` -> `customer` (under `company`) already exists
        # from TenantFixtureMixin.setUp; re-creating it would violate the
        # (customer, user) unique constraint.

        self.authenticate(self.super_admin)
        emails = self._emails(
            self.client.get(f"{self.URL}?company={self.company.id}")
        )
        self.assertIn(self.company_admin.email, emails)   # CompanyUserMembership
        self.assertIn(self.manager.email, emails)         # BM assignment
        self.assertIn(staff.email, emails)                # staff visibility
        self.assertIn(self.customer_user.email, emails)   # customer's provider

    def test_a_super_admin_row_drops_out_when_filtering_by_company(self):
        """Deliberate and worth pinning, because it could surprise.

        §1b says the filter returns "users holding a membership in that
        company". A SUPER_ADMIN holds none — they are global by
        construction — so filtering to one company removes them. That is
        the coherent reading: the question the filter answers is "whose
        staff are these", and a platform admin is nobody's staff.
        """
        self.authenticate(self.super_admin)
        emails = self._emails(
            self.client.get(f"{self.URL}?company={self.company.id}")
        )
        self.assertNotIn(self.super_admin.email, emails)


class UserCustomerFilterTests(TenantFixtureMixin, APITestCase):
    """Sprint 188 — `?customer=<id>`: "who at this customer can log in?"

    Same rule as the company filter 187B added: it NARROWS the caller's
    already-scoped set and can never widen it.
    """

    URL = "/api/users/"

    def _emails(self, response):
        rows = response.data.get("results", response.data)
        return {row["email"] for row in rows}

    def test_a_super_admin_can_narrow_to_one_customer(self):
        self.authenticate(self.super_admin)
        response = self.client.get(f"{self.URL}?customer={self.customer.id}")
        self.assertEqual(response.status_code, 200, response.data)
        emails = self._emails(response)
        self.assertIn(self.customer_user.email, emails)
        self.assertNotIn(self.other_customer_user.email, emails)
        # A provider-side account holds no CustomerUserMembership, so it
        # is not "at" any customer.
        self.assertNotIn(self.company_admin.email, emails)

    def test_a_company_admin_cannot_read_another_tenant_by_customer_id(self):
        """The clause that matters. Asserted as 200-with-nothing rather
        than an error: a 404 would confirm the id exists."""
        self.authenticate(self.company_admin)
        response = self.client.get(
            f"{self.URL}?customer={self.other_customer.id}"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._emails(response), set())

    def test_a_company_admin_passing_its_own_customer_still_sees_them(self):
        """The control. Without it, an implementation that returned
        nothing for every ?customer= value would pass the test above
        while being completely broken."""
        self.authenticate(self.company_admin)
        response = self.client.get(f"{self.URL}?customer={self.customer.id}")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn(self.customer_user.email, self._emails(response))

    def test_a_junk_value_cannot_500_the_page(self):
        self.authenticate(self.super_admin)
        response = self.client.get(f"{self.URL}?customer=not-a-number")
        self.assertEqual(response.status_code, 200, response.data)

    def test_an_unknown_customer_id_is_empty_not_an_error(self):
        self.authenticate(self.super_admin)
        response = self.client.get(f"{self.URL}?customer=99999")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._emails(response), set())


class EmployedByTests(TenantFixtureMixin, APITestCase):
    """Sprint 188 — "employed by" is not "whose data can you see".

    The Users detail page rendered `company_ids` under the heading
    "Companies ... this user belongs to". For a CUSTOMER_USER that array
    is filled by `customer.company` — the provider that SERVES them — so
    the page told the owner his customer's contact was a member of his
    own company.
    """

    def _detail(self, user):
        self.authenticate(self.super_admin)
        return self.client.get(f"/api/users/{user.id}/")

    def test_a_customer_user_is_employed_by_nobody(self):
        response = self._detail(self.customer_user)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["employed_by"], [])
        # ...while the scoping array still carries the provider, because
        # that is a different question and other callers rely on it.
        self.assertNotEqual(response.data["company_ids"], [])

    def test_a_company_admin_names_its_company(self):
        response = self._detail(self.company_admin)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["employed_by"], [self.company.name])

    def test_a_super_admin_is_nobodys_employee(self):
        response = self._detail(self.super_admin)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["employed_by"], [])
