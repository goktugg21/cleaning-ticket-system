"""
Sprint 28 Batch 15.4 — `extra_work_origin` on TicketDetailSerializer.

Locks the role-agnostic Extra Work parent metadata that
`TicketDetailSerializer` surfaces for tickets that were spawned
through the cart flow:

  * INSTANT-route spawn (`extra_work_request_item` set) -> origin
    "INSTANT", parent EW id/title/status populated, service_name set.
  * PROPOSAL-route spawn (`proposal_line` set) -> origin "PROPOSAL",
    parent EW walked back via `proposal_line.proposal.
    extra_work_request`.
  * Legacy / direct-API ticket (neither FK set) -> field is None.
  * CUSTOMER_USER caller sees the same payload shape as SUPER_ADMIN —
    role-aware stripping is the parent EW endpoint's job, not the
    ticket detail endpoint's.
  * The payload never includes provider-only EW fields
    (`internal_cost_note`, `manager_note`, `override_*`) — those are
    addressable only through the EW detail endpoint with its own
    role-aware to_representation.
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
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkRoutingDecision,
    ExtraWorkStatus,
    Proposal,
    ProposalLine,
    ProposalStatus,
    Service,
    ServiceCategory,
)
from tickets.models import Ticket, TicketStatus


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class ExtraWorkOriginFixtureMixin:
    @classmethod
    def _setup_fixture(cls):
        cls.company = Company.objects.create(
            name="Origin Provider", slug="origin-b154"
        )
        cls.building = Building.objects.create(
            company=cls.company, name="Building-Origin"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            name="Customer-Origin",
            building=cls.building,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            "super-origin@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-origin@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

        cls.cust_user = _mk("cust-origin@example.com", UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        cls.service_cat = ServiceCategory.objects.create(
            name="Cat-Origin"
        )
        cls.service = Service.objects.create(
            category=cls.service_cat,
            name="Window cleaning",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _make_instant_ticket(self):
        """INSTANT-route ticket: extra_work_request_item set,
        proposal_line None. Mirrors what
        `extra_work.instant_tickets.spawn_tickets_for_request` writes."""
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title="Instant cart submission",
            description="contract-priced cart",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            routing_decision=ExtraWorkRoutingDecision.INSTANT,
        )
        item = ExtraWorkRequestItem.objects.create(
            extra_work_request=ew,
            service=self.service,
            quantity=Decimal("2.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=date(2026, 6, 1),
            customer_note="",
        )
        ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title="Spawned ticket (instant)",
            description="from instant cart",
            status=TicketStatus.OPEN,
            extra_work_request_item=item,
        )
        return ew, item, ticket

    def _make_proposal_ticket(self):
        """PROPOSAL-route ticket: proposal_line set,
        extra_work_request_item None. Mirrors what
        `extra_work.proposal_tickets.spawn_tickets_for_proposal`
        writes."""
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title="Proposal-routed EW",
            description="ad-hoc cart",
            category=ExtraWorkCategory.OTHER,
            category_other_text="something custom",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            routing_decision=ExtraWorkRoutingDecision.PROPOSAL,
        )
        proposal = Proposal.objects.create(
            extra_work_request=ew,
            status=ProposalStatus.CUSTOMER_APPROVED,
            created_by=self.admin,
        )
        line = ProposalLine.objects.create(
            proposal=proposal,
            service=self.service,
            description="",
            quantity=Decimal("3.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            unit_price=Decimal("50.00"),
            vat_pct=Decimal("21.00"),
            customer_explanation="visible",
            internal_note="hidden",
        )
        ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title="Spawned ticket (proposal)",
            description="from proposal",
            status=TicketStatus.OPEN,
            proposal_line=line,
        )
        return ew, line, ticket

    def _make_legacy_ticket(self):
        """Direct-API ticket: both EW FKs None."""
        return Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title="Legacy ticket",
            description="not from EW",
            status=TicketStatus.OPEN,
        )


class InstantOriginTests(ExtraWorkOriginFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_instant_route_ticket_surfaces_origin_payload(self):
        ew, item, ticket = self._make_instant_ticket()
        response = self._api(self.super_admin).get(
            f"/api/tickets/{ticket.id}/"
        )
        self.assertEqual(response.status_code, 200, response.data)
        origin = response.data.get("extra_work_origin")
        self.assertIsNotNone(origin)
        self.assertEqual(origin["origin"], "INSTANT")
        self.assertEqual(origin["extra_work_request_id"], ew.id)
        self.assertEqual(origin["extra_work_request_title"], ew.title)
        self.assertEqual(
            origin["extra_work_request_status"],
            ExtraWorkStatus.CUSTOMER_APPROVED,
        )
        self.assertEqual(origin["extra_work_request_item_id"], item.id)
        self.assertEqual(origin["service_name"], self.service.name)


class ProposalOriginTests(ExtraWorkOriginFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_proposal_route_ticket_surfaces_origin_payload(self):
        ew, line, ticket = self._make_proposal_ticket()
        response = self._api(self.super_admin).get(
            f"/api/tickets/{ticket.id}/"
        )
        self.assertEqual(response.status_code, 200, response.data)
        origin = response.data.get("extra_work_origin")
        self.assertIsNotNone(origin)
        self.assertEqual(origin["origin"], "PROPOSAL")
        self.assertEqual(origin["extra_work_request_id"], ew.id)
        self.assertEqual(origin["extra_work_request_title"], ew.title)
        self.assertEqual(
            origin["extra_work_request_status"],
            ExtraWorkStatus.CUSTOMER_APPROVED,
        )
        # Proposal spawn helper does not populate `extra_work_request_
        # item` on the ticket — the link goes through the proposal
        # chain — so we expect None here.
        self.assertIsNone(origin["extra_work_request_item_id"])
        self.assertEqual(origin["service_name"], self.service.name)


class LegacyOriginTests(ExtraWorkOriginFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_legacy_ticket_has_null_origin(self):
        ticket = self._make_legacy_ticket()
        response = self._api(self.super_admin).get(
            f"/api/tickets/{ticket.id}/"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("extra_work_origin", response.data)
        self.assertIsNone(response.data["extra_work_origin"])


class RolePayloadParityTests(ExtraWorkOriginFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_customer_user_sees_same_origin_payload_as_super_admin(self):
        ew, item, ticket = self._make_instant_ticket()
        admin_response = self._api(self.super_admin).get(
            f"/api/tickets/{ticket.id}/"
        )
        cust_response = self._api(self.cust_user).get(
            f"/api/tickets/{ticket.id}/"
        )
        self.assertEqual(admin_response.status_code, 200)
        self.assertEqual(cust_response.status_code, 200)
        self.assertEqual(
            admin_response.data["extra_work_origin"],
            cust_response.data["extra_work_origin"],
        )


class NoProviderOnlyFieldLeakTests(ExtraWorkOriginFixtureMixin, TestCase):
    """The origin payload must NOT carry any of the provider-only
    EW columns. The ticket detail endpoint is reachable by customers
    whose scope includes the ticket — they would otherwise gain a
    backchannel to provider-internal context."""

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_origin_payload_never_carries_provider_only_fields(self):
        ew, item, ticket = self._make_instant_ticket()
        # Stamp provider-only fields on the parent EW so a serialization
        # bug that copies the whole EW row would be caught here.
        ew.manager_note = "Provider-only manager note"
        ew.internal_cost_note = "Provider-only cost"
        ew.override_reason = "Provider justification"
        ew.save()

        for actor in (self.super_admin, self.admin, self.cust_user):
            response = self._api(actor).get(f"/api/tickets/{ticket.id}/")
            self.assertEqual(response.status_code, 200)
            origin = response.data["extra_work_origin"]
            for forbidden in (
                "manager_note",
                "internal_cost_note",
                "override_by",
                "override_reason",
                "override_at",
                "pricing_note",
                "customer_visible_note",
            ):
                self.assertNotIn(
                    forbidden,
                    origin,
                    f"{actor.role} leaked provider-only EW field "
                    f"`{forbidden}` via extra_work_origin",
                )
