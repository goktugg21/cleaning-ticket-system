"""
Sprint 14 — customer/building/user-scope refactor coverage.

These tests exercise the new visibility model end-to-end:

  Customer            ↔ many Buildings via CustomerBuildingMembership
  Customer            ↔ Customer-users via CustomerUserMembership
  Customer-user       ↔ subset of the customer's buildings via
                        CustomerUserBuildingAccess

A customer-user sees a ticket iff
    ticket.customer is in their CustomerUserMembership set
    AND
    ticket.building is in their CustomerUserBuildingAccess set
        for that membership
    AND
    ticket is not soft-deleted (Sprint 12).

The 16 cases below come from the Sprint 14 brief, Phase 6.
"""
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus, TicketType


class _BAmsterdamScenarioMixin(TenantFixtureMixin):
    """
    Build the brief's B Amsterdam scenario on top of the standard tenant
    fixture. The standard fixture gives us self.company / self.building /
    self.customer; we add the multi-building "B Amsterdam" customer with
    three buildings and three customer-users with different access shapes.

    Layout:

      self.company                                              (Company A)
        ├─ self.building                                          (existing)
        ├─ b1, b2, b3                                             (Sprint 14)
        ├─ self.customer  (legacy, anchored to self.building)
        └─ b_amsterdam    (NEW, building=NULL, M:N to b1/b2/b3)

      Customer users on b_amsterdam:
        tom        access → b1, b2, b3
        iris       access → b1, b2
        amanda     access → b3

      Building managers (Osius-side):
        gokhan     assigned → b1, b2, b3
        murat      assigned → b1
        isa        assigned → b2

    We deliberately keep the standard self.customer / self.ticket so the
    legacy single-building data path is also exercised by the existing
    suite while these tests focus on the new shape.
    """

    def setUp(self):
        super().setUp()

        self.b1 = Building.objects.create(
            company=self.company, name="B1 Amsterdam", address="Maroastraat 3"
        )
        self.b2 = Building.objects.create(
            company=self.company, name="B2 Amsterdam", address="Maroastraat 3"
        )
        self.b3 = Building.objects.create(
            company=self.company, name="B3 Amsterdam", address="Maroastraat 3"
        )

        # Consolidated customer — building=NULL, M:N to b1/b2/b3.
        self.b_amsterdam = Customer.objects.create(
            company=self.company,
            name="B Amsterdam",
            building=None,
            contact_email="",
            phone="",
            language="nl",
            is_active=True,
        )
        for b in (self.b1, self.b2, self.b3):
            CustomerBuildingMembership.objects.create(
                customer=self.b_amsterdam, building=b
            )

        self.tom = self.make_user("tom@b-amsterdam.com", UserRole.CUSTOMER_USER)
        self.iris = self.make_user("iris@b-amsterdam.com", UserRole.CUSTOMER_USER)
        self.amanda = self.make_user("amanda@b-amsterdam.com", UserRole.CUSTOMER_USER)

        self.tom_membership = CustomerUserMembership.objects.create(
            customer=self.b_amsterdam, user=self.tom
        )
        self.iris_membership = CustomerUserMembership.objects.create(
            customer=self.b_amsterdam, user=self.iris
        )
        self.amanda_membership = CustomerUserMembership.objects.create(
            customer=self.b_amsterdam, user=self.amanda
        )

        # Tom: all three buildings.
        for b in (self.b1, self.b2, self.b3):
            CustomerUserBuildingAccess.objects.create(
                membership=self.tom_membership, building=b
            )
        # Iris: B1 + B2.
        for b in (self.b1, self.b2):
            CustomerUserBuildingAccess.objects.create(
                membership=self.iris_membership, building=b
            )
        # Amanda: B3 only.
        CustomerUserBuildingAccess.objects.create(
            membership=self.amanda_membership, building=self.b3
        )

        self.gokhan = self.make_user("gokhan@osius.demo", UserRole.BUILDING_MANAGER)
        self.murat = self.make_user("murat@osius.demo", UserRole.BUILDING_MANAGER)
        self.isa = self.make_user("isa@osius.demo", UserRole.BUILDING_MANAGER)
        for b in (self.b1, self.b2, self.b3):
            BuildingManagerAssignment.objects.create(building=b, user=self.gokhan)
        BuildingManagerAssignment.objects.create(building=self.b1, user=self.murat)
        BuildingManagerAssignment.objects.create(building=self.b2, user=self.isa)

        # One ticket per B Amsterdam building, with customer-user "tom"
        # as creator (same person across all three for simplicity —
        # different creators would also work, but these tests focus on
        # *visibility*, not creator).
        self.ticket_b1 = Ticket.objects.create(
            company=self.company,
            building=self.b1,
            customer=self.b_amsterdam,
            created_by=self.tom,
            title="B1 ticket",
            description="d",
            type=TicketType.REPORT,
        )
        self.ticket_b2 = Ticket.objects.create(
            company=self.company,
            building=self.b2,
            customer=self.b_amsterdam,
            created_by=self.tom,
            title="B2 ticket",
            description="d",
            type=TicketType.REPORT,
        )
        self.ticket_b3 = Ticket.objects.create(
            company=self.company,
            building=self.b3,
            customer=self.b_amsterdam,
            created_by=self.tom,
            title="B3 ticket",
            description="d",
            type=TicketType.REPORT,
        )


# ===========================================================================
# Phase 6 — visibility / access matrix
# ===========================================================================


class CustomerLinkedBuildingsTests(_BAmsterdamScenarioMixin, APITestCase):
    def test_customer_can_be_linked_to_three_buildings(self):
        """Phase 6 #1 — Customer ↔ Buildings is M:N."""
        linked_ids = set(
            CustomerBuildingMembership.objects.filter(
                customer=self.b_amsterdam
            ).values_list("building_id", flat=True)
        )
        self.assertEqual(linked_ids, {self.b1.id, self.b2.id, self.b3.id})


class TomFullAccessTests(_BAmsterdamScenarioMixin, APITestCase):
    def test_tom_sees_all_b_amsterdam_tickets(self):
        """Phase 6 #2 — Tom (B1+B2+B3 access) sees every B Amsterdam ticket."""
        self.authenticate(self.tom)
        response = self.client.get("/api/tickets/")
        ids = self.response_ids(response)
        self.assertEqual(
            ids,
            {self.ticket_b1.id, self.ticket_b2.id, self.ticket_b3.id},
        )


class AmandaB3OnlyTests(_BAmsterdamScenarioMixin, APITestCase):
    def test_amanda_sees_only_b3_ticket(self):
        """Phase 6 #3 — Amanda (B3 only) sees only the B3 ticket."""
        self.authenticate(self.amanda)
        response = self.client.get("/api/tickets/")
        ids = self.response_ids(response)
        self.assertEqual(ids, {self.ticket_b3.id})

    def test_amanda_cannot_create_ticket_for_b1(self):
        """Phase 6 #4 — Amanda cannot create a ticket at B1."""
        self.authenticate(self.amanda)
        response = self.client.post(
            "/api/tickets/",
            {
                "title": "Amanda tries B1",
                "description": "should fail",
                "type": "REPORT",
                "priority": "NORMAL",
                "building": self.b1.id,
                "customer": self.b_amsterdam.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("building", response.data)

    def test_amanda_cannot_view_b1_ticket_by_id(self):
        """Phase 6 #5 — Amanda cannot retrieve a B1 ticket by direct API id."""
        self.authenticate(self.amanda)
        response = self.client.get(f"/api/tickets/{self.ticket_b1.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TicketCreatePairValidationTests(_BAmsterdamScenarioMixin, APITestCase):
    def test_super_admin_cannot_create_for_unlinked_pair(self):
        """Phase 6 #6 — Even SUPER_ADMIN cannot create a (customer, building) outside the M:N link."""
        # self.other_building belongs to other_company — definitely not linked
        # to self.b_amsterdam. The legacy customer.building check would have
        # said "customer.building != building" too; the new check rejects on
        # the membership table.
        self.authenticate(self.super_admin)
        response = self.client.post(
            "/api/tickets/",
            {
                "title": "Cross-tenant pair",
                "description": "should fail",
                "type": "REPORT",
                "priority": "NORMAL",
                "building": self.other_building.id,
                "customer": self.b_amsterdam.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("customer", response.data)


class BuildingManagerVisibilityTests(_BAmsterdamScenarioMixin, APITestCase):
    def test_murat_sees_only_b1_tickets(self):
        """Phase 6 #7 — Murat (assigned only to B1) sees only B1 tickets."""
        self.authenticate(self.murat)
        response = self.client.get("/api/tickets/")
        ids = self.response_ids(response)
        # Note: self.ticket (legacy fixture) is at self.building, not B1.
        self.assertEqual(ids, {self.ticket_b1.id})

    def test_gokhan_sees_all_three_b_amsterdam_tickets(self):
        """Phase 6 #8 — Gokhan (assigned to B1+B2+B3) sees all three."""
        self.authenticate(self.gokhan)
        response = self.client.get("/api/tickets/")
        ids = self.response_ids(response)
        self.assertEqual(
            ids,
            {self.ticket_b1.id, self.ticket_b2.id, self.ticket_b3.id},
        )


class CompanyAdminAndCrossCompanyTests(_BAmsterdamScenarioMixin, APITestCase):
    def test_company_admin_sees_company_scope_tickets(self):
        """Phase 6 #9 — Company admin sees all in-company tickets."""
        self.authenticate(self.company_admin)
        response = self.client.get("/api/tickets/")
        ids = self.response_ids(response)
        # company_admin is a member of self.company; they see all four
        # company-A tickets (the legacy self.ticket plus the three new ones).
        self.assertEqual(
            ids,
            {
                self.ticket.id,
                self.ticket_b1.id,
                self.ticket_b2.id,
                self.ticket_b3.id,
            },
        )

    def test_cross_company_access_remains_blocked(self):
        """Phase 6 #10 — other_company_admin cannot see Company A's tickets."""
        self.authenticate(self.other_company_admin)
        response = self.client.get(
            f"/api/tickets/{self.ticket_b1.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class DashboardStatsTests(_BAmsterdamScenarioMixin, APITestCase):
    def test_amanda_dashboard_stats_only_count_b3(self):
        """Phase 6 #11 — Stats endpoint respects per-user building access."""
        self.authenticate(self.amanda)
        response = self.client.get("/api/tickets/stats/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Only the B3 ticket is in scope; legacy self.ticket lives in
        # a different customer that Amanda is not a member of.
        self.assertEqual(response.data["total"], 1)


class SoftDeletedTicketRemainsHiddenTests(_BAmsterdamScenarioMixin, APITestCase):
    def test_soft_deleted_b3_ticket_hidden_from_amanda(self):
        """Phase 6 #12 — Sprint-12 soft-delete still hides under Sprint-14 scope."""
        self.ticket_b3.deleted_at = timezone.now()
        self.ticket_b3.deleted_by = self.super_admin
        self.ticket_b3.save(update_fields=["deleted_at", "deleted_by"])

        self.authenticate(self.amanda)
        response = self.client.get("/api/tickets/")
        ids = self.response_ids(response)
        self.assertNotIn(self.ticket_b3.id, ids)


class AssignableManagersTests(_BAmsterdamScenarioMixin, APITestCase):
    def test_assignable_managers_only_for_target_building(self):
        """Phase 6 #13 — Assignable-managers list only returns managers assigned to the ticket building."""
        self.authenticate(self.gokhan)
        response = self.client.get(
            f"/api/tickets/{self.ticket_b1.id}/assignable-managers/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {row["email"] for row in response.data}
        # Gokhan and Murat are assigned to B1; Isa is not.
        self.assertIn(self.gokhan.email, emails)
        self.assertIn(self.murat.email, emails)
        self.assertNotIn(self.isa.email, emails)


class MigrationBackfillTests(TenantFixtureMixin, APITestCase):
    def test_backfill_function_seeds_access_for_legacy_membership(self):
        """
        Phase 6 #14 — calling the migration's backfill function on a
        pre-Sprint-14-shaped scenario seeds exactly one access row per
        pre-existing CustomerUserMembership, pointing at the customer's
        legacy `building`.

        Tests in this suite create their fixtures *after* the migrations
        have already run on the test DB (so the backfill has no rows to
        process at migration time). To test the backfill behaviour we
        therefore: (a) wipe access for an existing legacy-shaped row,
        (b) call the migration's `backfill_customer_user_building_access`
        function directly via Django's `apps.get_model`, (c) assert the
        access row reappears.
        """
        from importlib import import_module

        from django.apps import apps as global_apps

        # Migration filenames start with a digit, which is not a valid
        # Python identifier — but importlib accepts the dotted path
        # because Django creates a regular package under
        # `customers/migrations/` with `__init__.py`.
        backfill_module = import_module(
            "customers.migrations.0003_backfill_building_links"
        )

        # Wipe any access rows the test DB happens to have, so we can
        # observe the backfill running on a clean slate.
        CustomerUserBuildingAccess.objects.all().delete()

        backfill_module.backfill_customer_user_building_access(
            global_apps, schema_editor=None
        )

        # Every membership whose customer has a legacy building should
        # now have exactly one access row pointing at that building.
        for membership in CustomerUserMembership.objects.select_related(
            "customer"
        ):
            legacy_building_id = membership.customer.building_id
            if legacy_building_id is None:
                continue
            access = CustomerUserBuildingAccess.objects.filter(
                membership=membership, building_id=legacy_building_id
            )
            self.assertTrue(
                access.exists(),
                f"backfill should have created access for membership #{membership.pk} "
                f"pointing at legacy building #{legacy_building_id}",
            )


class NoBuildingAccessTests(_BAmsterdamScenarioMixin, APITestCase):
    def test_member_with_no_building_access_sees_nothing_for_customer(self):
        """Phase 6 #15 — A CustomerUserMembership without any access row sees zero tickets."""
        # A new B Amsterdam member with no access rows.
        bart = self.make_user("bart@b-amsterdam.com", UserRole.CUSTOMER_USER)
        CustomerUserMembership.objects.create(
            customer=self.b_amsterdam, user=bart
        )
        # Intentionally no CustomerUserBuildingAccess rows.
        self.authenticate(bart)
        response = self.client.get("/api/tickets/")
        ids = self.response_ids(response)
        self.assertEqual(ids, set())


class RemoveAccessRevokesVisibilityTests(_BAmsterdamScenarioMixin, APITestCase):
    def test_removing_amandas_b3_access_removes_visibility(self):
        """Phase 6 #16 — revoking the only access row removes the user's visibility."""
        self.authenticate(self.amanda)
        before = self.client.get("/api/tickets/")
        self.assertEqual(self.response_ids(before), {self.ticket_b3.id})

        CustomerUserBuildingAccess.objects.filter(
            membership=self.amanda_membership, building=self.b3
        ).delete()

        after = self.client.get("/api/tickets/")
        self.assertEqual(self.response_ids(after), set())


# ===========================================================================
# Sprint 14 hotfix — /api/customers/ must expose linked_building_ids so the
# CreateTicketPage frontend filter can match a consolidated customer to a
# selected building. Without this field a customer-user picks B3 in the
# Location dropdown and the Customer dropdown shows "No customers in this
# location" because Customer.building is NULL.
# ===========================================================================


class LinkedBuildingIdsSerializerTests(_BAmsterdamScenarioMixin, APITestCase):
    def _get_customer(self, response, customer_id):
        """Find one customer payload in the paginated list response."""
        for row in response.data["results"]:
            if row["id"] == customer_id:
                return row
        self.fail(
            f"Customer #{customer_id} not in list response: {response.data}"
        )

    def test_super_admin_sees_all_three_linked_buildings(self):
        self.authenticate(self.super_admin)
        response = self.client.get("/api/customers/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = self._get_customer(response, self.b_amsterdam.id)
        self.assertEqual(
            sorted(row["linked_building_ids"]),
            sorted([self.b1.id, self.b2.id, self.b3.id]),
        )

    def test_amanda_sees_b_amsterdam_with_full_linked_building_list(self):
        """
        Hotfix contract: /api/customers/ returns the FULL linked-building
        list for a customer the caller is a member of, NOT filtered to
        the caller's per-building access. The frontend uses the list
        only to match a selected building to the customer; the backend
        ticket-create endpoint enforces per-(customer, building) user
        access on submit.
        """
        self.authenticate(self.amanda)
        response = self.client.get("/api/customers/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = self._get_customer(response, self.b_amsterdam.id)
        # Amanda's CustomerUserBuildingAccess only covers B3, but the
        # serializer reports the full linked set — that is intentional
        # so the dropdown match works when Amanda picks B3.
        self.assertEqual(
            sorted(row["linked_building_ids"]),
            sorted([self.b1.id, self.b2.id, self.b3.id]),
        )

    def test_legacy_single_building_customer_falls_back_to_legacy_anchor(self):
        """
        A customer with no CustomerBuildingMembership rows but a non-null
        Customer.building still surfaces the legacy id, so an unmigrated
        row stays usable in the frontend filter.
        """
        # The fixture's self.customer was given a CustomerBuildingMembership
        # by TenantFixtureMixin (mirrors the migration backfill). To
        # exercise the legacy fallback, wipe the M:N row and confirm the
        # serializer falls back to customer.building.
        from customers.models import CustomerBuildingMembership

        CustomerBuildingMembership.objects.filter(
            customer=self.customer
        ).delete()

        self.authenticate(self.super_admin)
        response = self.client.get("/api/customers/")
        row = self._get_customer(response, self.customer.id)
        self.assertEqual(
            row["linked_building_ids"],
            [self.customer.building_id],
        )

    def test_consolidated_customer_with_no_links_returns_empty_list(self):
        """A truly empty consolidated customer returns []."""
        from customers.models import CustomerBuildingMembership

        # Wipe both the M:N rows AND the legacy anchor so no link
        # exists at all.
        CustomerBuildingMembership.objects.filter(
            customer=self.b_amsterdam
        ).delete()
        # b_amsterdam already has building=NULL.

        self.authenticate(self.super_admin)
        response = self.client.get("/api/customers/")
        row = self._get_customer(response, self.b_amsterdam.id)
        self.assertEqual(row["linked_building_ids"], [])
