"""
Sprint 111 — building-manager "My tickets" filter (`my_managed`).

Pins the additive `my_managed` BooleanFilter on the ticket list. Unlike
the staff `my_jobs` filter (which keys off the `TicketStaffAssignment`
M:N), `my_managed` narrows to tickets the caller MANAGES — the UNION of:

  * the legacy single primary-manager FK (`Ticket.assigned_to`), and
  * the responsible-manager M:N (`TicketManagerAssignment`, reverse
    relation `manager_assignments`).

Assertions:

  * a BM set as the PRIMARY assignee (`assigned_to`) sees that ticket
    via `?my_managed=1`;
  * a BM added only as a RESPONSIBLE manager (`TicketManagerAssignment`)
    sees that ticket;
  * a BM sees the UNION of both, and NOT a same-building scope-visible
    ticket they hold neither relation on;
  * the filter is request-scoped — a different BM on the same building
    does not see the first BM's tickets;
  * `my_managed` with no / false value returns the unfiltered (scoped)
    set — proving it is opt-in;
  * cross-tenant isolation holds — a BM of company A gets nothing from
    company B even when a company-B ticket is name-matched onto them
    (the view applies `scope_tickets_for` first).

The filter is OPT-IN and additive: the default list (no `my_managed`
param) is unchanged. It runs on top of `scope_tickets_for` (already
applied in `get_queryset`), so it can only ever narrow within the
caller's own scope.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User, UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company
from customers.models import Customer
from tickets.models import Ticket, TicketManagerAssignment


class _MyManagedBase(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Osius", slug="osius")
        self.building = Building.objects.create(
            company=self.company, name="B1"
        )
        self.customer = Customer.objects.create(
            company=self.company, name="Cust"
        )

        # The actor under test: a BUILDING_MANAGER assigned to B1, so
        # scope_tickets_for shows every ticket in that building.
        self.bm = User.objects.create_user(
            email="bm@osius.nl", password="x", role=UserRole.BUILDING_MANAGER
        )
        BuildingManagerAssignment.objects.create(
            user=self.bm, building=self.building
        )

        # A second BM, also assigned to B1 — used to prove the filter is
        # request-scoped (the same-building scope shows them the ticket,
        # my_managed narrows it out).
        self.other_bm = User.objects.create_user(
            email="other-bm@osius.nl",
            password="x",
            role=UserRole.BUILDING_MANAGER,
        )
        BuildingManagerAssignment.objects.create(
            user=self.other_bm, building=self.building
        )

        # An admin used only as `created_by` / `assigned_by`.
        self.admin = User.objects.create_user(
            email="sa@osius.nl", password="x", role=UserRole.SUPER_ADMIN
        )

    def _ticket(self, title, **extra):
        return Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title=title,
            description="d",
            **extra,
        )

    def _ids(self, resp):
        return [row["id"] for row in resp.data["results"]]


class MyManagedPrimaryAssigneeTests(_MyManagedBase):
    def test_primary_assignee_seen_via_my_managed(self):
        # assigned_to == the BM, no responsible-manager row.
        mine = self._ticket("primary-mine", assigned_to=self.bm)
        not_mine = self._ticket("neither")

        self.client.force_authenticate(user=self.bm)
        resp = self.client.get("/api/tickets/", {"my_managed": "1"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        ids = self._ids(resp)
        self.assertIn(mine.id, ids)
        self.assertNotIn(not_mine.id, ids)


class MyManagedResponsibleManagerTests(_MyManagedBase):
    def test_responsible_manager_seen_via_my_managed(self):
        # No assigned_to; the BM is only a responsible manager (M:N).
        mine = self._ticket("responsible-mine")
        TicketManagerAssignment.objects.create(
            ticket=mine, user=self.bm, assigned_by=self.admin
        )
        not_mine = self._ticket("neither")

        self.client.force_authenticate(user=self.bm)
        resp = self.client.get("/api/tickets/", {"my_managed": "1"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        ids = self._ids(resp)
        self.assertIn(mine.id, ids)
        self.assertNotIn(not_mine.id, ids)


class MyManagedUnionTests(_MyManagedBase):
    def test_union_of_both_relations_excludes_neither(self):
        # Primary-only, responsible-only, and a same-building ticket the
        # BM holds NEITHER relation on (scope-visible but must be excluded).
        primary_only = self._ticket("primary-only", assigned_to=self.bm)
        responsible_only = self._ticket("responsible-only")
        TicketManagerAssignment.objects.create(
            ticket=responsible_only, user=self.bm, assigned_by=self.admin
        )
        neither = self._ticket("neither")

        self.client.force_authenticate(user=self.bm)
        resp = self.client.get("/api/tickets/", {"my_managed": "1"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        ids = self._ids(resp)
        self.assertIn(primary_only.id, ids)
        self.assertIn(responsible_only.id, ids)
        self.assertNotIn(neither.id, ids)

    def test_both_relations_on_one_ticket_returns_single_row(self):
        # A ticket where the BM is BOTH primary assignee and a responsible
        # manager must appear exactly once (`.distinct()` collapses the
        # M:N-join fan-out).
        both = self._ticket("both-relations", assigned_to=self.bm)
        TicketManagerAssignment.objects.create(
            ticket=both, user=self.bm, assigned_by=self.admin
        )

        self.client.force_authenticate(user=self.bm)
        resp = self.client.get("/api/tickets/", {"my_managed": "1"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        ids = self._ids(resp)
        self.assertEqual(ids.count(both.id), 1, ids)


class MyManagedRequestScopedTests(_MyManagedBase):
    def test_other_bm_does_not_see_first_bms_tickets(self):
        # Both tickets are scope-visible to other_bm (same building), but
        # my_managed keys off the CALLER, so other_bm sees neither.
        primary = self._ticket("bm-primary", assigned_to=self.bm)
        responsible = self._ticket("bm-responsible")
        TicketManagerAssignment.objects.create(
            ticket=responsible, user=self.bm, assigned_by=self.admin
        )

        self.client.force_authenticate(user=self.other_bm)

        # Scope floor: without the filter, both are visible (building-wide).
        plain = self.client.get("/api/tickets/")
        plain_ids = self._ids(plain)
        self.assertIn(primary.id, plain_ids)
        self.assertIn(responsible.id, plain_ids)

        # With my_managed=1 the other BM sees neither (request-scoped).
        narrowed = self.client.get("/api/tickets/", {"my_managed": "1"})
        narrowed_ids = self._ids(narrowed)
        self.assertNotIn(primary.id, narrowed_ids)
        self.assertNotIn(responsible.id, narrowed_ids)


class MyManagedOptInTests(_MyManagedBase):
    def test_default_list_unchanged_without_filter(self):
        mine = self._ticket("mine", assigned_to=self.bm)
        neither = self._ticket("neither")

        self.client.force_authenticate(user=self.bm)
        resp = self.client.get("/api/tickets/")
        ids = self._ids(resp)
        self.assertIn(mine.id, ids)
        self.assertIn(neither.id, ids)

    def test_my_managed_false_does_not_narrow(self):
        mine = self._ticket("mine", assigned_to=self.bm)
        neither = self._ticket("neither")

        self.client.force_authenticate(user=self.bm)
        resp = self.client.get("/api/tickets/", {"my_managed": "false"})
        ids = self._ids(resp)
        self.assertIn(mine.id, ids)
        self.assertIn(neither.id, ids)


class MyManagedCrossTenantTests(_MyManagedBase):
    def test_cross_tenant_isolation_holds(self):
        # A separate tenant. The BM has NO BuildingManagerAssignment on
        # company B, so scope_tickets_for excludes company-B tickets even
        # when one is name-matched onto them via assigned_to.
        company_b = Company.objects.create(name="Rivalco", slug="rivalco")
        building_b = Building.objects.create(company=company_b, name="RB1")
        customer_b = Customer.objects.create(
            company=company_b, name="CustB"
        )
        foreign = Ticket.objects.create(
            company=company_b,
            building=building_b,
            customer=customer_b,
            created_by=self.admin,
            title="foreign-but-name-matched",
            description="d",
            assigned_to=self.bm,
        )
        # Also name-match via the responsible-manager M:N.
        TicketManagerAssignment.objects.create(
            ticket=foreign, user=self.bm, assigned_by=self.admin
        )
        mine = self._ticket("mine-in-scope", assigned_to=self.bm)

        self.client.force_authenticate(user=self.bm)

        # Scope floor: the foreign ticket is invisible even unfiltered.
        plain_ids = self._ids(self.client.get("/api/tickets/"))
        self.assertNotIn(foreign.id, plain_ids)

        # my_managed=1 still yields only the in-scope ticket.
        resp = self.client.get("/api/tickets/", {"my_managed": "1"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        ids = self._ids(resp)
        self.assertIn(mine.id, ids)
        self.assertNotIn(foreign.id, ids)
