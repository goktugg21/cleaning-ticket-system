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
from django.db.models import Q
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
        admin_a = User.objects.get(email="ramazan-admin-osius@b-amsterdam.demo")
        admin_b = User.objects.get(email="sophie-admin-bright@bright-facilities.demo")

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
        for email in CANONICAL_USER_EMAILS:
            user = User.objects.get(email=email)
            self.assertTrue(
                user.check_password(DEMO_PASSWORD),
                msg=f"{email} should authenticate with Demo12345!",
            )

    def test_exactly_one_active_super_admin_after_seed(self):
        # Sprint 21 v2 invariant: exactly one canonical super admin at
        # superadmin@cleanops.demo. Any stray super-admin under a demo
        # TLD (e.g. the historical superadmin@osius.demo) must be
        # pruned. The check counts active rows with role=SUPER_ADMIN
        # whose email lives under a demo TLD.
        active_demo_supers = User.objects.filter(
            role=UserRole.SUPER_ADMIN, is_active=True
        ).filter(
            Q(email__iendswith="@cleanops.demo")
            | Q(email__iendswith="@b-amsterdam.demo")
            | Q(email__iendswith="@bright-facilities.demo")
        )
        emails = list(active_demo_supers.values_list("email", flat=True))
        self.assertEqual(
            emails,
            ["superadmin@cleanops.demo"],
            f"expected exactly one canonical super admin, got: {emails}",
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

        cls.super_admin = User.objects.get(email="superadmin@cleanops.demo")
        cls.admin_a = User.objects.get(
            email="ramazan-admin-osius@b-amsterdam.demo"
        )
        cls.admin_b = User.objects.get(
            email="sophie-admin-bright@bright-facilities.demo"
        )
        cls.manager_a_full = User.objects.get(
            email="gokhan-manager-osius@b-amsterdam.demo"
        )
        cls.manager_b = User.objects.get(
            email="bram-manager-bright@bright-facilities.demo"
        )
        cls.customer_a_full = User.objects.get(
            email="tom-customer-b-amsterdam@b-amsterdam.demo"
        )
        cls.customer_b = User.objects.get(
            email="lotte-customer-bright@bright-facilities.demo"
        )
        cls.customer_a_b3_only = User.objects.get(
            email="amanda-customer-b-amsterdam@b-amsterdam.demo"
        )

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
            "sophie-admin-bright@bright-facilities.demo",
            "bram-manager-bright@bright-facilities.demo",
            "lotte-customer-bright@bright-facilities.demo",
        }
        self.assertTrue(
            company_b_user_emails.isdisjoint(a_visible),
            f"Company A admin must not see Company B users, but saw: "
            f"{company_b_user_emails & a_visible}",
        )

        # Company A users must not appear in B's visibility.
        company_a_user_emails = {
            "ramazan-admin-osius@b-amsterdam.demo",
            "gokhan-manager-osius@b-amsterdam.demo",
            "tom-customer-b-amsterdam@b-amsterdam.demo",
            "iris-customer-b-amsterdam@b-amsterdam.demo",
            "amanda-customer-b-amsterdam@b-amsterdam.demo",
        }
        self.assertTrue(
            company_a_user_emails.isdisjoint(b_visible),
            f"Company B admin must not see Company A users, but saw: "
            f"{company_a_user_emails & b_visible}",
        )

        # And both admins do see their own users — sanity check.
        self.assertIn("gokhan-manager-osius@b-amsterdam.demo", a_visible)
        self.assertIn("bram-manager-bright@bright-facilities.demo", b_visible)

    def test_manager_b_sees_only_company_b_buildings(self):
        # bram-manager-bright@bright-facilities.demo is assigned to
        # R1+R2 Rotterdam only.
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
        # lotte-customer-bright@bright-facilities.demo has
        # CustomerUserBuildingAccess to R1+R2 Rotterdam only.
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


CANONICAL_USER_EMAILS = (
    # ---- Sprint 21 v2 canonical demo accounts ----
    "superadmin@cleanops.demo",
    # Company A — Osius Demo / B Amsterdam
    "ramazan-admin-osius@b-amsterdam.demo",
    "gokhan-manager-osius@b-amsterdam.demo",
    "murat-manager-osius@b-amsterdam.demo",
    "isa-manager-osius@b-amsterdam.demo",
    "tom-customer-b-amsterdam@b-amsterdam.demo",
    "iris-customer-b-amsterdam@b-amsterdam.demo",
    "amanda-customer-b-amsterdam@b-amsterdam.demo",
    # Company B — Bright Facilities
    "sophie-admin-bright@bright-facilities.demo",
    "bram-manager-bright@bright-facilities.demo",
    "lotte-customer-bright@bright-facilities.demo",
)

LEGACY_USER_EMAILS = (
    # ---- Sprint 10 seed_demo (removed) ----
    "demo-super@example.com",
    "demo-company-admin@example.com",
    "demo-manager@example.com",
    "demo-customer@example.com",
    # ---- Pre-Sprint-21 scripts/demo_up.sh inline shell ----
    "admin@example.com",
    "companyadmin@example.com",
    "manager@example.com",
    "customer@example.com",
    # ---- Sprint 14 seed_b_amsterdam_demo (removed) ----
    "tom@b-amsterdam.com",
    "iris@b-amsterdam.com",
    "amanda@b-amsterdam.com",
    "gokhan.kocak@osius.demo",
    "murat.ugurlu@osius.demo",
    "isa.ugurlu@osius.demo",
    # ---- Sprint 21 v1 canonical (superseded in v2) ----
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
    # ---- Sprint 21 v2 stray operator super-admin ----
    "superadmin@osius.demo",
)


class SeedDemoDataLegacyPruneTests(TestCase):
    """
    Sprint 21 follow-up: legacy demo personas left in the local DB by
    the deleted `seed_demo` and `seed_b_amsterdam_demo` commands must
    be pruned by the canonical seed so /admin/users does not show
    stale rows alongside the Sprint 21 set.
    """

    def _create_legacy_user(self, email, role=UserRole.CUSTOMER_USER):
        return User.objects.create_user(
            email=email,
            password="Demo12345!",
            role=role,
        )

    def test_legacy_users_are_soft_deleted_after_seed(self):
        # Pre-create every legacy email the prune list targets. We
        # vary the role across the set so a regression that mis-typed
        # the role filter would be caught too.
        roles_cycle = [
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
            UserRole.CUSTOMER_USER,
        ]
        for i, email in enumerate(LEGACY_USER_EMAILS):
            self._create_legacy_user(email, role=roles_cycle[i % len(roles_cycle)])

        # Pre-create the legacy single-company seed companies so the
        # prune step has something to deactivate.
        Company.objects.create(
            slug="demo-cleaning-bv",
            name="Demo Cleaning BV",
            default_language="nl",
            is_active=True,
        )
        Company.objects.create(
            slug="demo-cleaning-company",
            name="Demo Cleaning Company",
            default_language="nl",
            is_active=True,
        )

        _seed()

        for email in LEGACY_USER_EMAILS:
            user = User.objects.get(email=email)
            self.assertFalse(
                user.is_active,
                f"{email} should be inactive after prune",
            )
            self.assertIsNotNone(
                user.deleted_at,
                f"{email} should have deleted_at set after prune",
            )
            # deleted_by should point at the super admin (the seed
            # creates super_admin before running the prune so it can
            # be the soft-delete actor).
            self.assertIsNotNone(
                user.deleted_by_id,
                f"{email} should have deleted_by set after prune",
            )
            self.assertEqual(
                User.objects.get(id=user.deleted_by_id).email,
                "superadmin@cleanops.demo",
            )

    def test_canonical_users_remain_active_after_prune(self):
        # First run: seed only — establishes canonical users.
        _seed()
        # Inject the legacy ones now and re-seed; canonical users must
        # not flip to inactive.
        for email in LEGACY_USER_EMAILS:
            self._create_legacy_user(email)
        _seed()
        for email in CANONICAL_USER_EMAILS:
            user = User.objects.get(email=email)
            self.assertTrue(
                user.is_active,
                f"canonical user {email} must remain active after prune",
            )
            self.assertIsNone(
                user.deleted_at,
                f"canonical user {email} must have deleted_at=None after prune",
            )

    def test_company_b_canonical_users_are_not_pruned(self):
        # The Company B trio shares no email prefix with any legacy
        # entry but a regression that walked the wrong list could
        # still hit them. Seed twice with legacy users injected
        # between, then assert the Company B users are intact.
        _seed()
        for email in LEGACY_USER_EMAILS:
            self._create_legacy_user(email)
        _seed()
        for email in (
            "sophie-admin-bright@bright-facilities.demo",
            "bram-manager-bright@bright-facilities.demo",
            "lotte-customer-bright@bright-facilities.demo",
        ):
            user = User.objects.get(email=email)
            self.assertTrue(user.is_active, f"{email} must remain active")
            self.assertIsNone(user.deleted_at, f"{email} must not be soft-deleted")

    def test_legacy_user_memberships_are_removed(self):
        # A legacy user that was a manager of B1 Amsterdam in the old
        # seed should no longer have any BuildingManagerAssignment
        # row after the prune; same for company / customer rows.
        _seed()  # establishes the canonical company A buildings.
        b1 = Building.objects.get(name="B1 Amsterdam")
        legacy_user = self._create_legacy_user(
            "gokhan.kocak@osius.demo", role=UserRole.BUILDING_MANAGER
        )
        BuildingManagerAssignment.objects.create(
            user=legacy_user, building=b1
        )
        company_a = Company.objects.get(slug=COMPANY_A_SLUG)
        # CompanyUserMembership is also created in the old code path
        # for managers; we replicate it here so the prune has both
        # row types to remove.
        CompanyUserMembership.objects.create(
            user=legacy_user, company=company_a
        )

        _seed()

        self.assertFalse(
            BuildingManagerAssignment.objects.filter(user=legacy_user).exists(),
            "legacy manager's BuildingManagerAssignment must be removed",
        )
        self.assertFalse(
            CompanyUserMembership.objects.filter(user=legacy_user).exists(),
            "legacy manager's CompanyUserMembership must be removed",
        )

    def test_legacy_customer_user_access_rows_are_removed(self):
        # The Sprint 14 seed wired tom@b-amsterdam.com to all 3 B
        # buildings via CustomerUserMembership + CustomerUserBuildingAccess.
        # The prune must drop both.
        _seed()
        customer_a = Customer.objects.get(
            company__slug=COMPANY_A_SLUG, name=COMPANY_A_CUSTOMER
        )
        legacy_tom = self._create_legacy_user(
            "tom@b-amsterdam.com", role=UserRole.CUSTOMER_USER
        )
        membership = CustomerUserMembership.objects.create(
            customer=customer_a, user=legacy_tom
        )
        for bname in COMPANY_A_BUILDINGS:
            CustomerUserBuildingAccess.objects.create(
                membership=membership,
                building=Building.objects.get(name=bname),
            )

        _seed()

        self.assertFalse(
            CustomerUserMembership.objects.filter(user=legacy_tom).exists(),
            "legacy customer user's membership must be removed",
        )
        self.assertFalse(
            CustomerUserBuildingAccess.objects.filter(
                membership__user=legacy_tom
            ).exists(),
            "legacy customer user's per-building access rows must be removed",
        )

    def test_legacy_demo_cleaning_bv_company_is_deactivated(self):
        Company.objects.create(
            slug="demo-cleaning-bv",
            name="Demo Cleaning BV",
            default_language="nl",
            is_active=True,
        )
        _seed()
        legacy = Company.objects.get(slug="demo-cleaning-bv")
        self.assertFalse(legacy.is_active)

        # Canonical companies remain active.
        self.assertTrue(Company.objects.get(slug=COMPANY_A_SLUG).is_active)
        self.assertTrue(Company.objects.get(slug=COMPANY_B_SLUG).is_active)

    def test_admin_users_api_hides_legacy_after_seed(self):
        # End-to-end check: GET /api/users/ as superadmin@cleanops.demo
        # must not return any of the legacy emails after the prune.
        from rest_framework.test import APIClient

        for email in LEGACY_USER_EMAILS:
            self._create_legacy_user(email)
        _seed()

        super_admin = User.objects.get(email="superadmin@cleanops.demo")
        client = APIClient()
        client.force_authenticate(user=super_admin)
        response = client.get("/api/users/")
        self.assertEqual(response.status_code, 200)
        # The default list filters by is_active=True, so soft-deleted
        # legacy users must not appear.
        returned_emails = {row["email"] for row in response.data["results"]}
        for email in LEGACY_USER_EMAILS:
            self.assertNotIn(
                email,
                returned_emails,
                f"/api/users/ leaked legacy email {email} after prune",
            )
        # Canonical users still appear.
        for email in CANONICAL_USER_EMAILS:
            self.assertIn(
                email,
                returned_emails,
                f"/api/users/ missing canonical email {email}",
            )

    def test_no_legacy_users_present_is_a_no_op(self):
        # Running the prune on a clean DB must not raise and must
        # leave the canonical seed intact.
        _seed()
        for email in CANONICAL_USER_EMAILS:
            self.assertTrue(
                User.objects.filter(email=email, is_active=True).exists(),
                f"{email} must be present and active after clean re-seed",
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
