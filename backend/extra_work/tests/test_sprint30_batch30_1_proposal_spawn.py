"""
Sprint 30 Batch 30.1 — legacy pricing-flow ticket spawn tests.

Covers the four behaviours wired in 30.1:

  1. PRICING_PROPOSED -> CUSTOMER_APPROVED (customer-driven) spawns
     one ticket per ExtraWorkRequestItem on the EW.
  2. The new retry-spawn endpoint POST /api/extra-work/<id>/spawn/
     recovers an EW that landed in CUSTOMER_APPROVED with zero
     tickets (pre-fix data).
  3. The retry endpoint refuses with a stable 400 when spawn has
     already happened (idempotency at the API layer).
  4. The retry endpoint refuses CUSTOMER_USER callers with 403 —
     not customer-callable per the brief.
  5. The new TicketFilter.extra_work_request param returns ONLY the
     spawned tickets for the chosen EW (no cross-EW bleed).

Hermetic per-test-class fixture; mirrors the InstantSpawn test
shape so both spawn paths read identically in the test footprint.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import Building
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from extra_work.models import (
    ExtraWorkCategory,
    ExtraWorkPricingLineItem,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkRoutingDecision,
    ExtraWorkStatus,
    Service,
    ServiceCategory,
)
from extra_work.state_machine import apply_transition
from tickets.models import Ticket, TicketStatus, TicketStatusHistory


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
SPAWN_URL = "/api/extra-work/{ew_id}/spawn/"
TICKETS_URL = "/api/tickets/"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class Sprint30Batch30_1FixtureMixin:
    """Shared fixture: provider with a customer, one building, and a
    catalog service. Customer-user has CustomerUserBuildingAccess with
    approve_own permission so a customer-driven approval test path is
    available.
    """

    @classmethod
    def _setup_fixture(cls):
        cls.company = Company.objects.create(
            name="Sprint30 Provider", slug="sprint30-b30-1"
        )
        cls.building = Building.objects.create(
            company=cls.company, name="Building-30.1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            name="Customer-30.1",
            building=cls.building,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            "super-30.1@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-30.1@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

        cls.cust_user = _mk(
            "cust-30.1@example.com", UserRole.CUSTOMER_USER
        )
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        # Sprint 27C — approve_own is a default key on
        # CUSTOMER_USER access role; nothing extra needed beyond
        # creating the access row.
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        cls.service_cat = ServiceCategory.objects.create(
            name="Sprint30-Cat"
        )
        cls.service = Service.objects.create(
            category=cls.service_cat,
            name="Sprint30-Service",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )

    @classmethod
    def _make_ew(
        cls,
        *,
        status: str = ExtraWorkStatus.PRICING_PROPOSED,
        with_cart_item: bool = True,
        with_pricing_item: bool = True,
        title: str = "Legacy EW",
    ) -> ExtraWorkRequest:
        ew = ExtraWorkRequest.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.cust_user,
            title=title,
            description="legacy pricing flow",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=status,
            routing_decision=ExtraWorkRoutingDecision.PROPOSAL,
        )
        if with_cart_item:
            ExtraWorkRequestItem.objects.create(
                extra_work_request=ew,
                service=cls.service,
                quantity=Decimal("2.00"),
                unit_type=ExtraWorkPricingUnitType.HOURS,
                requested_date=date(2026, 6, 15),
                customer_note="first line",
            )
        if with_pricing_item:
            ExtraWorkPricingLineItem.objects.create(
                extra_work=ew,
                description="Cleaning quote",
                unit_type=ExtraWorkPricingUnitType.FIXED,
                quantity=Decimal("1.00"),
                unit_price=Decimal("100.00"),
                vat_rate=Decimal("21.00"),
            )
        return ew

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c


# ---------------------------------------------------------------------------
# Test 1 — proposal approval spawns tickets
# ---------------------------------------------------------------------------
class ProposalApprovalSpawnsTicketsTests(
    Sprint30Batch30_1FixtureMixin, TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_proposal_approval_spawns_tickets(self):
        ew = self._make_ew(status=ExtraWorkStatus.PRICING_PROPOSED)
        before = Ticket.objects.count()

        # Customer-driven PRICING_PROPOSED -> CUSTOMER_APPROVED via
        # the legacy state-machine entry point. apply_transition is
        # the same code path the customer's POST /transition/ takes.
        updated = apply_transition(
            ew,
            self.cust_user,
            ExtraWorkStatus.CUSTOMER_APPROVED,
            note="customer approves quote",
        )

        self.assertEqual(updated.status, ExtraWorkStatus.CUSTOMER_APPROVED)
        # Exactly one ticket spawned (one cart line).
        self.assertEqual(Ticket.objects.count(), before + 1)

        cart_item = ew.line_items.get()
        ticket = Ticket.objects.get(extra_work_request_item=cart_item)
        self.assertEqual(ticket.status, TicketStatus.OPEN)
        self.assertEqual(ticket.company_id, ew.company_id)
        self.assertEqual(ticket.building_id, ew.building_id)
        self.assertEqual(ticket.customer_id, ew.customer_id)
        self.assertEqual(ticket.created_by_id, self.cust_user.id)
        self.assertEqual(
            ticket.extra_work_request_item_id, cart_item.id
        )
        # Initial OPEN status-history row exists, mirroring the
        # INSTANT-route and proposal-route shapes.
        history = list(
            TicketStatusHistory.objects.filter(ticket=ticket).order_by(
                "created_at"
            )
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].new_status, TicketStatus.OPEN)
        self.assertEqual(history[0].old_status, "")


# ---------------------------------------------------------------------------
# Test 2 — retry endpoint recovers a stuck EW
# ---------------------------------------------------------------------------
class RetrySpawnEndpointRecoversStuckEwTests(
    Sprint30Batch30_1FixtureMixin, TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_retry_spawn_endpoint_recovers_stuck_ew(self):
        # Construct an EW directly in CUSTOMER_APPROVED with NO
        # spawned tickets — mirrors the pre-fix production state of
        # EW #7. The state machine isn't used here because the
        # whole point is recovering rows where the spawn-hook
        # didn't run at approval time.
        ew = self._make_ew(status=ExtraWorkStatus.CUSTOMER_APPROVED)
        self.assertEqual(Ticket.objects.count(), 0)

        response = self._api(self.super_admin).post(
            SPAWN_URL.format(ew_id=ew.id)
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(len(response.data["spawned_ticket_ids"]), 1)

        cart_item = ew.line_items.get()
        ticket = Ticket.objects.get(extra_work_request_item=cart_item)
        self.assertEqual(ticket.status, TicketStatus.OPEN)
        self.assertEqual(ticket.id, response.data["spawned_ticket_ids"][0])


# ---------------------------------------------------------------------------
# Test 3 — retry refuses when tickets already exist
# ---------------------------------------------------------------------------
class RetrySpawnRejectsWhenAlreadySpawnedTests(
    Sprint30Batch30_1FixtureMixin, TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_retry_spawn_rejects_when_already_spawned(self):
        ew = self._make_ew(status=ExtraWorkStatus.CUSTOMER_APPROVED)
        cart_item = ew.line_items.get()
        # Manually create one ticket linked to the cart item so the
        # retry endpoint sees existing spawned tickets.
        Ticket.objects.create(
            company=ew.company,
            building=ew.building,
            customer=ew.customer,
            created_by=self.super_admin,
            title="Pre-existing ticket",
            description="already spawned",
            status=TicketStatus.OPEN,
            extra_work_request_item=cart_item,
        )

        response = self._api(self.super_admin).post(
            SPAWN_URL.format(ew_id=ew.id)
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "spawn_already_done")


# ---------------------------------------------------------------------------
# Test 4 — retry refuses customer callers
# ---------------------------------------------------------------------------
class RetrySpawnRejectsCustomerUserTests(
    Sprint30Batch30_1FixtureMixin, TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_retry_spawn_rejects_customer_user(self):
        ew = self._make_ew(status=ExtraWorkStatus.CUSTOMER_APPROVED)
        response = self._api(self.cust_user).post(
            SPAWN_URL.format(ew_id=ew.id)
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data["code"], "spawn_forbidden_role")
        # And no tickets were created.
        self.assertEqual(
            Ticket.objects.filter(
                extra_work_request_item__extra_work_request_id=ew.id
            ).count(),
            0,
        )


# ---------------------------------------------------------------------------
# Test 5 — TicketFilter.extra_work_request scopes the list
# ---------------------------------------------------------------------------
class TicketFilterExtraWorkRequestTests(
    Sprint30Batch30_1FixtureMixin, TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_filter_extra_work_request_returns_only_spawned(self):
        # Two EWs, each with one cart item and one spawned ticket.
        ew_a = self._make_ew(
            status=ExtraWorkStatus.PRICING_PROPOSED, title="EW-A"
        )
        ew_b = self._make_ew(
            status=ExtraWorkStatus.PRICING_PROPOSED, title="EW-B"
        )

        apply_transition(
            ew_a,
            self.cust_user,
            ExtraWorkStatus.CUSTOMER_APPROVED,
            note="approve A",
        )
        apply_transition(
            ew_b,
            self.cust_user,
            ExtraWorkStatus.CUSTOMER_APPROVED,
            note="approve B",
        )

        cart_a = ew_a.line_items.get()
        cart_b = ew_b.line_items.get()
        ticket_a = Ticket.objects.get(extra_work_request_item=cart_a)
        ticket_b = Ticket.objects.get(extra_work_request_item=cart_b)
        self.assertNotEqual(ticket_a.id, ticket_b.id)

        client = self._api(self.super_admin)
        response = client.get(
            TICKETS_URL, {"extra_work_request": ew_a.id}
        )
        self.assertEqual(response.status_code, 200, response.data)
        results = response.data.get("results", response.data)
        ids = {row["id"] for row in results}
        self.assertEqual(ids, {ticket_a.id})
        self.assertNotIn(ticket_b.id, ids)

        # And the inverse — querying for ew_b returns only ticket_b.
        response = client.get(
            TICKETS_URL, {"extra_work_request": ew_b.id}
        )
        self.assertEqual(response.status_code, 200, response.data)
        results = response.data.get("results", response.data)
        ids = {row["id"] for row in results}
        self.assertEqual(ids, {ticket_b.id})
