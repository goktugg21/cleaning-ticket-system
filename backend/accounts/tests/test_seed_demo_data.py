"""
Sprint 21 — tests for the canonical two-company `seed_demo_data`
management command.

The command provisions:

  Company A — "Osius Demo"
    Buildings: B1 / B2 / B3 Amsterdam
    Customer:  "B Amsterdam"
    Users:     8 (super + 7 company-A personas)

  Company B — "Bright Facilities"
    Buildings: R1 / R2 Rotterdam
    Customer:  "City Office Rotterdam"
    Users:     3 (admin-b / manager-b / customer-b)

These tests verify:
  1. A fresh seed produces both companies with the documented shape.
  2. Re-running is idempotent (no duplicate users, buildings, or tickets).
  3. The scope helpers in accounts.scoping respect company isolation:
     a Company A admin must not see Company B buildings / customers /
     tickets / users, and vice versa.
  4. SUPER_ADMIN sees both companies.
  5. Building managers and customer users only see their assigned scope.

The command refuses on DJANGO_DEBUG=False unless
--i-know-this-is-not-prod is passed. The Django test runner already
sets DEBUG=True, so the standard `call_command` invocation works
without the override. The refusal path itself is covered separately
to make sure Sprint 19's pilot-safety gate is still in place.
"""
from __future__ import annotations

from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from accounts.models import User, UserRole
from accounts.scoping import (
    building_ids_for,
    company_ids_for,
    customer_ids_for,
    scope_tickets_for,
)
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from tickets.models import Ticket


COMPANY_A_NAME = "Osius Demo"
COMPANY_A_SLUG = "osius-demo"
COMPANY_A_BUILDINGS = {"B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam"}
COMPANY_A_CUSTOMER = "B Amsterdam"

COMPANY_B_NAME = "Bright Facilities"
COMPANY_B_SLUG = "bright-facilities"
COMPANY_B_BUILDINGS = {"R1 Rotterdam", "R2 Rotterdam"}
COMPANY_B_CUSTOMER = "City Office Rotterdam"

DEMO_PASSWORD = "Demo12345!"


def _seed():
    """
    Run the canonical seed, swallowing the human-readable stdout.

    The test environment runs against the production-shaped settings
    (DEBUG=False) on CI, so we always pass the explicit
    --i-know-this-is-not-prod flag here. The refusal path on
    DEBUG=False *without* the flag is exercised separately by
    SeedDemoDataSafetyTests so the pilot safety gate stays covered.
    """
    out = StringIO()
    call_command(
        "seed_demo_data",
        "--i-know-this-is-not-prod",
        stdout=out,
        stderr=StringIO(),
    )
    return out.getvalue()


class SeedDemoDataShapeTests(TestCase):
    """The seed creates two isolated companies with the documented shape."""

    @classmethod
    def setUpTestData(cls):
        _seed()

    def test_both_companies_exist_with_expected_buildings(self):
        company_a = Company.objects.get(slug=COMPANY_A_SLUG)
        self.assertEqual(company_a.name, COMPANY_A_NAME)
        self.assertTrue(company_a.is_active)
        self.assertEqual(
            set(company_a.buildings.values_list("name", flat=True)),
            COMPANY_A_BUILDINGS,
        )

        company_b = Company.objects.get(slug=COMPANY_B_SLUG)
        self.assertEqual(company_b.name, COMPANY_B_NAME)
        self.assertTrue(company_b.is_active)
        self.assertEqual(
            set(company_b.buildings.values_list("name", flat=True)),
            COMPANY_B_BUILDINGS,
        )

    def test_each_company_has_consolidated_customer(self):
        # The Sprint-14 consolidated-customer shape: customer.building is
        # NULL and links to the company's buildings via M:N memberships.
        company_a = Company.objects.get(slug=COMPANY_A_SLUG)
        customer_a = Customer.objects.get(
            company=company_a, name=COMPANY_A_CUSTOMER
        )
        self.assertIsNone(customer_a.building)
        self.assertEqual(
            set(
                CustomerBuildingMembership.objects.filter(customer=customer_a)
                .values_list("building__name", flat=True)
            ),
            COMPANY_A_BUILDINGS,
        )

        company_b = Company.objects.get(slug=COMPANY_B_SLUG)
        customer_b = Customer.objects.get(
            company=company_b, name=COMPANY_B_CUSTOMER
        )
        self.assertIsNone(customer_b.building)
        self.assertEqual(
            set(
                CustomerBuildingMembership.objects.filter(customer=customer_b)
                .values_list("building__name", flat=True)
            ),
            COMPANY_B_BUILDINGS,
        )

    def test_company_admins_are_scoped_to_their_company_only(self):
        # Company A admin has exactly one CompanyUserMembership row, to
        # Company A. Company B admin has one row, to Company B.
        admin_a = User.objects.get(email="admin@cleanops.demo")
        admin_b = User.objects.get(email="admin-b@cleanops.demo")

        self.assertEqual(admin_a.role, UserRole.COMPANY_ADMIN)
        self.assertEqual(admin_b.role, UserRole.COMPANY_ADMIN)

        a_companies = set(
            CompanyUserMembership.objects.filter(user=admin_a)
            .values_list("company__slug", flat=True)
        )
        b_companies = set(
            CompanyUserMembership.objects.filter(user=admin_b)
            .values_list("company__slug", flat=True)
        )
        self.assertEqual(a_companies, {COMPANY_A_SLUG})
        self.assertEqual(b_companies, {COMPANY_B_SLUG})

    def test_demo_passwords_all_work(self):
        # All seeded accounts must authenticate with Demo12345!.
        for email in (
            "super@cleanops.demo",
            "admin@cleanops.demo",
            "gokhan@cleanops.demo",
            "murat@cleanops.demo",
            "isa@cleanops.demo",
            "tom@cleanops.demo",
            "iris@cleanops.demo",
            "amanda@cleanops.demo",
            "admin-b@cleanops.demo",
            "manager-b@cleanops.demo",
            "customer-b@cleanops.demo",
        ):
            user = User.objects.get(email=email)
            self.assertTrue(
                user.check_password(DEMO_PASSWORD),
                msg=f"{email} should authenticate with Demo12345!",
            )

    def test_demo_tickets_are_per_company(self):
        company_a = Company.objects.get(slug=COMPANY_A_SLUG)
        company_b = Company.objects.get(slug=COMPANY_B_SLUG)
        tickets_a = list(
            Ticket.objects.filter(
                company=company_a, title__startswith="[DEMO]"
            ).values_list("title", flat=True)
        )
        tickets_b = list(
            Ticket.objects.filter(
                company=company_b, title__startswith="[DEMO]"
            ).values_list("title", flat=True)
        )
        # Counts match the documented seed (4 in A, 2 in B).
        self.assertEqual(len(tickets_a), 4)
        self.assertEqual(len(tickets_b), 2)
        # No ticket in Company A points at a Company B building, and
        # vice versa.
        for t in Ticket.objects.filter(company=company_a):
            self.assertEqual(t.building.company_id, company_a.id)
        for t in Ticket.objects.filter(company=company_b):
            self.assertEqual(t.building.company_id, company_b.id)


class SeedDemoDataIsolationTests(TestCase):
    """The scope helpers respect cross-company isolation after seeding."""

    @classmethod
    def setUpTestData(cls):
        _seed()
        cls.company_a = Company.objects.get(slug=COMPANY_A_SLUG)
        cls.company_b = Company.objects.get(slug=COMPANY_B_SLUG)

        cls.super_admin = User.objects.get(email="super@cleanops.demo")
        cls.admin_a = User.objects.get(email="admin@cleanops.demo")
        cls.admin_b = User.objects.get(email="admin-b@cleanops.demo")
        cls.manager_a_full = User.objects.get(email="gokhan@cleanops.demo")
        cls.manager_b = User.objects.get(email="manager-b@cleanops.demo")
        cls.customer_a_full = User.objects.get(email="tom@cleanops.demo")
        cls.customer_b = User.objects.get(email="customer-b@cleanops.demo")
        cls.customer_a_b3_only = User.objects.get(email="amanda@cleanops.demo")

    def test_super_admin_sees_both_companies(self):
        ids = set(company_ids_for(self.super_admin))
        self.assertIn(self.company_a.id, ids)
        self.assertIn(self.company_b.id, ids)

    def test_company_a_admin_sees_only_company_a(self):
        self.assertEqual(
            set(company_ids_for(self.admin_a)), {self.company_a.id}
        )
        # Building visibility too.
        a_building_ids = set(
            Building.objects.filter(company=self.company_a)
            .values_list("id", flat=True)
        )
        self.assertEqual(set(building_ids_for(self.admin_a)), a_building_ids)
        # No Company B buildings.
        b_building_ids = set(
            Building.objects.filter(company=self.company_b)
            .values_list("id", flat=True)
        )
        self.assertTrue(b_building_ids.isdisjoint(set(building_ids_for(self.admin_a))))

    def test_company_b_admin_sees_only_company_b(self):
        self.assertEqual(
            set(company_ids_for(self.admin_b)), {self.company_b.id}
        )
        b_building_ids = set(
            Building.objects.filter(company=self.company_b)
            .values_list("id", flat=True)
        )
        self.assertEqual(set(building_ids_for(self.admin_b)), b_building_ids)
        a_building_ids = set(
            Building.objects.filter(company=self.company_a)
            .values_list("id", flat=True)
        )
        self.assertTrue(a_building_ids.isdisjoint(set(building_ids_for(self.admin_b))))

    def test_cross_company_ticket_visibility_is_blocked(self):
        # scope_tickets_for(admin_a) must not contain any Company B ticket
        # and vice versa.
        a_ticket_qs = scope_tickets_for(self.admin_a)
        b_ticket_qs = scope_tickets_for(self.admin_b)
        self.assertTrue(
            a_ticket_qs.filter(company=self.company_b).count() == 0,
            "Company A admin must not see Company B tickets",
        )
        self.assertTrue(
            b_ticket_qs.filter(company=self.company_a).count() == 0,
            "Company B admin must not see Company A tickets",
        )
        # And both actually see *something* — the seed put 4 in A, 2 in B.
        self.assertEqual(a_ticket_qs.filter(company=self.company_a).count(), 4)
        self.assertEqual(b_ticket_qs.filter(company=self.company_b).count(), 2)

    def test_cross_company_customer_visibility_is_blocked(self):
        a_customer_ids = set(customer_ids_for(self.admin_a))
        b_customer_ids = set(customer_ids_for(self.admin_b))
        # Company A admin sees Company A customers, none of B.
        company_a_customer_id = Customer.objects.get(
            company=self.company_a, name=COMPANY_A_CUSTOMER
        ).id
        company_b_customer_id = Customer.objects.get(
            company=self.company_b, name=COMPANY_B_CUSTOMER
        ).id
        self.assertIn(company_a_customer_id, a_customer_ids)
        self.assertNotIn(company_b_customer_id, a_customer_ids)
        self.assertIn(company_b_customer_id, b_customer_ids)
        self.assertNotIn(company_a_customer_id, b_customer_ids)

    def test_cross_company_user_admin_visibility_is_blocked(self):
        # The Users admin endpoint scopes by company (the logic lives
        # inline in accounts.views_users.UserViewSet.get_queryset, not
        # in a helper). We test the visibility-set by replicating the
        # same union-of-membership queries that the view uses: a
        # Company A admin should see exactly the users with at least
        # one membership/assignment inside Company A, and likewise for
        # Company B. This catches a regression where two companies
        # share user IDs through some membership row.
        def visible_to_company_admin(admin):
            actor_company_ids = list(
                CompanyUserMembership.objects.filter(user=admin).values_list(
                    "company_id", flat=True
                )
            )
            ids = set(
                CompanyUserMembership.objects.filter(
                    company_id__in=actor_company_ids
                ).values_list("user_id", flat=True)
            )
            ids.update(
                BuildingManagerAssignment.objects.filter(
                    building__company_id__in=actor_company_ids
                ).values_list("user_id", flat=True)
            )
            ids.update(
                CustomerUserMembership.objects.filter(
                    customer__company_id__in=actor_company_ids
                ).values_list("user_id", flat=True)
            )
            return set(
                User.objects.filter(id__in=ids).values_list("email", flat=True)
            )

        a_visible = visible_to_company_admin(self.admin_a)
        b_visible = visible_to_company_admin(self.admin_b)

        # Company B users must not appear in A's visibility.
        company_b_user_emails = {
            "admin-b@cleanops.demo",
            "manager-b@cleanops.demo",
            "customer-b@cleanops.demo",
        }
        self.assertTrue(
            company_b_user_emails.isdisjoint(a_visible),
            f"Company A admin must not see Company B users, but saw: "
            f"{company_b_user_emails & a_visible}",
        )

        # Company A users must not appear in B's visibility.
        company_a_user_emails = {
            "admin@cleanops.demo",
            "gokhan@cleanops.demo",
            "tom@cleanops.demo",
            "iris@cleanops.demo",
            "amanda@cleanops.demo",
        }
        self.assertTrue(
            company_a_user_emails.isdisjoint(b_visible),
            f"Company B admin must not see Company A users, but saw: "
            f"{company_a_user_emails & b_visible}",
        )

        # And both admins do see their own users — sanity check.
        self.assertIn("gokhan@cleanops.demo", a_visible)
        self.assertIn("manager-b@cleanops.demo", b_visible)

    def test_manager_b_sees_only_company_b_buildings(self):
        # manager-b@cleanops.demo is assigned to R1+R2 Rotterdam only.
        expected = set(
            Building.objects.filter(
                company=self.company_b, name__in=COMPANY_B_BUILDINGS
            ).values_list("id", flat=True)
        )
        self.assertEqual(set(building_ids_for(self.manager_b)), expected)
        # No Company A buildings.
        company_a_ids = set(
            Building.objects.filter(company=self.company_a).values_list(
                "id", flat=True
            )
        )
        self.assertTrue(
            company_a_ids.isdisjoint(set(building_ids_for(self.manager_b)))
        )

    def test_customer_b_sees_only_company_b_buildings(self):
        # customer-b@cleanops.demo has CustomerUserBuildingAccess to
        # R1+R2 Rotterdam only.
        accessible = set(
            CustomerUserBuildingAccess.objects.filter(
                membership__user=self.customer_b
            ).values_list("building__name", flat=True)
        )
        self.assertEqual(accessible, COMPANY_B_BUILDINGS)
        self.assertTrue(
            set(building_ids_for(self.customer_b)).isdisjoint(
                set(
                    Building.objects.filter(company=self.company_a)
                    .values_list("id", flat=True)
                )
            )
        )

    def test_customer_a_amanda_sees_only_b3(self):
        # Sanity check that the Company A per-user-building-access shape
        # we relied on in Sprint 14 still works after the Sprint 21 refactor.
        accessible = set(
            CustomerUserBuildingAccess.objects.filter(
                membership__user=self.customer_a_b3_only
            ).values_list("building__name", flat=True)
        )
        self.assertEqual(accessible, {"B3 Amsterdam"})


class SeedDemoDataIdempotencyTests(TestCase):
    """Re-running the seed does not duplicate any row."""

    def test_running_twice_produces_no_duplicates(self):
        _seed()
        first_counts = {
            "companies": Company.objects.count(),
            "buildings": Building.objects.count(),
            "customers": Customer.objects.count(),
            "users": User.objects.count(),
            "tickets": Ticket.objects.filter(title__startswith="[DEMO]").count(),
            "company_memberships": CompanyUserMembership.objects.count(),
            "manager_assignments": BuildingManagerAssignment.objects.count(),
            "customer_memberships": CustomerUserMembership.objects.count(),
            "customer_user_building_access": CustomerUserBuildingAccess.objects.count(),
            "customer_building_links": CustomerBuildingMembership.objects.count(),
        }
        _seed()
        second_counts = {
            "companies": Company.objects.count(),
            "buildings": Building.objects.count(),
            "customers": Customer.objects.count(),
            "users": User.objects.count(),
            "tickets": Ticket.objects.filter(title__startswith="[DEMO]").count(),
            "company_memberships": CompanyUserMembership.objects.count(),
            "manager_assignments": BuildingManagerAssignment.objects.count(),
            "customer_memberships": CustomerUserMembership.objects.count(),
            "customer_user_building_access": CustomerUserBuildingAccess.objects.count(),
            "customer_building_links": CustomerBuildingMembership.objects.count(),
        }
        self.assertEqual(
            first_counts,
            second_counts,
            f"Idempotency violation:\n  first:  {first_counts}\n  second: {second_counts}",
        )


class SeedDemoDataSafetyTests(TestCase):
    """The seed refuses to run on DJANGO_DEBUG=False without the override."""

    @override_settings(DEBUG=False)
    def test_refuses_on_debug_false_without_override(self):
        with self.assertRaises(CommandError) as cm:
            call_command(
                "seed_demo_data", stdout=StringIO(), stderr=StringIO()
            )
        self.assertIn("DJANGO_DEBUG=False", str(cm.exception))

    @override_settings(DEBUG=False)
    def test_allows_on_debug_false_with_override(self):
        # The flag is the explicit "I know" gate used by demo_up.sh.
        call_command(
            "seed_demo_data",
            "--i-know-this-is-not-prod",
            stdout=StringIO(),
            stderr=StringIO(),
        )
        # The seed actually wrote both companies.
        self.assertTrue(Company.objects.filter(slug=COMPANY_A_SLUG).exists())
        self.assertTrue(Company.objects.filter(slug=COMPANY_B_SLUG).exists())
