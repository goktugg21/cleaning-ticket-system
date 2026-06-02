"""
Sprint 6A — one operational Ticket per ExtraWorkRequest.

The invariant under test: an ExtraWorkRequest may carry many cart /
proposal lines but must spawn EXACTLY ONE operational Ticket. Repeated
create / transition / retry must never create a duplicate — the
existing ticket is reused.

Flows are driven end-to-end through the real create serializer and the
real state-machine transitions so the spawn helpers are exercised the
way production reaches them:

  * Direct / instant all-agreed cart  -> POST /api/extra-work/
  * Request-Quote proposal            -> proposal create + SEND +
                                         customer CUSTOMER_APPROVED
  * Retry                             -> POST /api/extra-work/<id>/spawn/

Coverage map:
  1. Instant 2-line all-agreed cart    -> exactly 1 Ticket.
  2. That ticket's extra_work_request  == ew (canonical link).
  3. GET /api/tickets/<id>/ origin     -> not None, INSTANT, ew id;
     legacy ticket -> origin None.
  4. Idempotent create / retry         -> count stays 1.
  5. REGRESSION 3-line cart            -> 1 Ticket (not 3).
  6. Proposal multi-line approved      -> exactly 1 Ticket; PROPOSAL.
  7. Proposal rejected                 -> 0 Tickets.
  8. Proposal retry / spawn endpoint   -> no duplicate; already_spawned.
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
from extra_work.instant_tickets import spawn_tickets_for_request
from extra_work.models import (
    CustomerServicePrice,
    ExtraWorkCategory,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRoutingDecision,
    ExtraWorkStatus,
    ProposalStatus,
    Service,
    ServiceCategory,
)
from tickets.models import Ticket, TicketStatus


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
EW_URL = "/api/extra-work/"
SPAWN_URL = "/api/extra-work/{ew_id}/spawn/"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class OneTicketFixtureMixin:
    """Provider with a customer, one building, a catalog of priced and
    unpriced services. Priced services back the instant / direct flow;
    the unpriced service forces the PROPOSAL (Request-Quote) flow."""

    @classmethod
    def _setup_fixture(cls):
        cls.company = Company.objects.create(
            name="Sprint6A Provider", slug="sprint6a"
        )
        cls.building = Building.objects.create(
            company=cls.company, name="Building-6A"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer-6A", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            "super-6a@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-6a@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

        cls.cust_user = _mk("cust-6a@example.com", UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        cls.service_cat = ServiceCategory.objects.create(name="Cat-6A")
        cls.service_a = Service.objects.create(
            category=cls.service_cat,
            company=cls.company,
            name="Service A",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
            description="Reference description for Service A",
        )
        cls.service_b = Service.objects.create(
            category=cls.service_cat,
            company=cls.company,
            name="Service B",
            unit_type=ExtraWorkPricingUnitType.SQUARE_METERS,
            default_unit_price=Decimal("3.50"),
        )
        cls.service_c = Service.objects.create(
            category=cls.service_cat,
            company=cls.company,
            name="Service C",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            default_unit_price=Decimal("100.00"),
        )
        cls.service_unpriced = Service.objects.create(
            category=cls.service_cat,
            company=cls.company,
            name="No contract",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("40.00"),
        )
        for service in (cls.service_a, cls.service_b, cls.service_c):
            CustomerServicePrice.objects.create(
                service=service,
                customer=cls.customer,
                unit_price=Decimal("48.50"),
                vat_pct=Decimal("21.00"),
                valid_from=date(2026, 1, 1),
                valid_to=None,
                is_active=True,
            )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _submit_cart(self, services, *, actor=None):
        """POST a cart with one line per service; all-agreed services
        route to INSTANT and spawn immediately. Returns the response."""
        actor = actor or self.cust_user
        line_items = [
            {
                "service": svc.id,
                "quantity": "2.00",
                "requested_date": "2026-06-15",
                "customer_note": f"note for {svc.name}",
            }
            for svc in services
        ]
        payload = {
            "customer": self.customer.id,
            "building": self.building.id,
            "title": "Sprint6A cart",
            "description": "cart description",
            "category": ExtraWorkCategory.DEEP_CLEANING,
            "line_items": line_items,
        }
        return self._api(actor).post(EW_URL, payload, format="json")


# ---------------------------------------------------------------------------
# Instant / direct all-agreed flow
# ---------------------------------------------------------------------------
class InstantOneTicketTests(OneTicketFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_two_agreed_lines_spawn_exactly_one_ticket(self):
        response = self._submit_cart([self.service_a, self.service_b])
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["routing_decision"],
            ExtraWorkRoutingDecision.INSTANT,
        )
        ew = ExtraWorkRequest.objects.get(id=response.data["id"])
        self.assertEqual(
            Ticket.objects.filter(extra_work_request=ew).count(), 1
        )

    def test_ticket_carries_request_level_link(self):
        response = self._submit_cart([self.service_a, self.service_b])
        self.assertEqual(response.status_code, 201, response.data)
        ew = ExtraWorkRequest.objects.get(id=response.data["id"])
        ticket = Ticket.objects.get(extra_work_request=ew)
        self.assertEqual(ticket.extra_work_request_id, ew.id)
        # Ticket field defaults.
        self.assertEqual(ticket.status, TicketStatus.OPEN)
        self.assertEqual(ticket.priority, "NORMAL")
        self.assertEqual(ticket.company_id, ew.company_id)
        self.assertEqual(ticket.building_id, ew.building_id)
        self.assertEqual(ticket.customer_id, ew.customer_id)
        self.assertEqual(ticket.created_by_id, self.cust_user.id)
        # Back-compat legacy link points at the FIRST cart line.
        first_line = ew.line_items.order_by("id").first()
        self.assertEqual(ticket.extra_work_request_item_id, first_line.id)
        # Description summarizes ALL lines + the request-level text once.
        self.assertIn("cart description", ticket.description)
        self.assertIn(self.service_a.name, ticket.description)
        self.assertIn(self.service_b.name, ticket.description)

    def test_three_lines_do_not_spawn_three_tickets(self):
        # REGRESSION — a 3-line cart must produce 1 ticket, not 3.
        response = self._submit_cart(
            [self.service_a, self.service_b, self.service_c]
        )
        self.assertEqual(response.status_code, 201, response.data)
        ew = ExtraWorkRequest.objects.get(id=response.data["id"])
        self.assertEqual(ew.line_items.count(), 3)
        self.assertEqual(
            Ticket.objects.filter(extra_work_request=ew).count(), 1
        )

    def test_create_path_is_idempotent_on_re_run(self):
        response = self._submit_cart([self.service_a, self.service_b])
        self.assertEqual(response.status_code, 201, response.data)
        ew = ExtraWorkRequest.objects.get(id=response.data["id"])
        self.assertEqual(
            Ticket.objects.filter(extra_work_request=ew).count(), 1
        )

        before = Ticket.objects.count()
        from django.db import transaction

        with transaction.atomic():
            again = spawn_tickets_for_request(ew, actor=self.cust_user)
        # Idempotent re-run returns [] and creates no new ticket.
        self.assertEqual(again, [])
        self.assertEqual(Ticket.objects.count(), before)
        self.assertEqual(
            Ticket.objects.filter(extra_work_request=ew).count(), 1
        )

    def test_origin_payload_instant(self):
        response = self._submit_cart([self.service_a, self.service_b])
        self.assertEqual(response.status_code, 201, response.data)
        ew = ExtraWorkRequest.objects.get(id=response.data["id"])
        ticket = Ticket.objects.get(extra_work_request=ew)

        detail = self._api(self.super_admin).get(
            f"/api/tickets/{ticket.id}/"
        )
        self.assertEqual(detail.status_code, 200, detail.data)
        origin = detail.data.get("extra_work_origin")
        self.assertIsNotNone(origin)
        self.assertEqual(origin["origin"], "INSTANT")
        self.assertEqual(origin["extra_work_request_id"], ew.id)

    def test_legacy_ticket_has_null_origin(self):
        legacy = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title="Legacy ticket",
            description="not from EW",
            status=TicketStatus.OPEN,
        )
        detail = self._api(self.super_admin).get(
            f"/api/tickets/{legacy.id}/"
        )
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertIn("extra_work_origin", detail.data)
        self.assertIsNone(detail.data["extra_work_origin"])


# ---------------------------------------------------------------------------
# Request-Quote proposal flow
# ---------------------------------------------------------------------------
class ProposalOneTicketTests(OneTicketFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _line_payload(self, **overrides) -> dict:
        payload = {
            "service": self.service_unpriced.id,
            "quantity": "2.00",
            "unit_type": ExtraWorkPricingUnitType.HOURS,
            "unit_price": "50.00",
            "vat_pct": "21.00",
            "customer_explanation": "visible explanation",
            "internal_note": "provider-only note",
        }
        payload.update(overrides)
        return payload

    def _make_quote_ew(self):
        """Submit an unpriced cart so routing -> PROPOSAL and the row
        stays REQUESTED, then drive it to UNDER_REVIEW so a proposal
        can be built."""
        response = self._submit_cart([self.service_unpriced])
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["routing_decision"],
            ExtraWorkRoutingDecision.PROPOSAL,
        )
        ew = ExtraWorkRequest.objects.get(id=response.data["id"])
        # Add a second cart line so the proposal can carry two lines
        # and still pass the SEND coverage gate.
        from extra_work.models import ExtraWorkRequestItem

        ExtraWorkRequestItem.objects.create(
            extra_work_request=ew,
            service=self.service_unpriced,
            quantity=Decimal("2.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=date(2026, 6, 15),
            customer_note="",
        )
        # REQUESTED -> UNDER_REVIEW (provider).
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/transition/",
            {"to_status": ExtraWorkStatus.UNDER_REVIEW},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        return ew

    def _build_sent_proposal(self, ew):
        # Create a DRAFT proposal with two lines.
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/proposals/",
            {"lines": [self._line_payload(), self._line_payload()]},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        proposal_id = resp.data["id"]
        # SEND it.
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal_id}/transition/",
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        return proposal_id

    def test_multi_line_proposal_approval_spawns_one_ticket(self):
        ew = self._make_quote_ew()
        proposal_id = self._build_sent_proposal(ew)

        resp = self._api(self.cust_user).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal_id}/transition/",
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(
            Ticket.objects.filter(extra_work_request=ew).count(), 1
        )
        ticket = Ticket.objects.get(extra_work_request=ew)
        # The proposal helper links the FIRST approved-for-spawn line.
        self.assertIsNotNone(ticket.proposal_line_id)

        detail = self._api(self.super_admin).get(
            f"/api/tickets/{ticket.id}/"
        )
        self.assertEqual(detail.status_code, 200, detail.data)
        origin = detail.data.get("extra_work_origin")
        self.assertIsNotNone(origin)
        self.assertEqual(origin["origin"], "PROPOSAL")
        self.assertEqual(origin["extra_work_request_id"], ew.id)

    def test_proposal_rejected_spawns_zero_tickets(self):
        ew = self._make_quote_ew()
        proposal_id = self._build_sent_proposal(ew)

        resp = self._api(self.cust_user).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal_id}/transition/",
            {"to_status": ProposalStatus.CUSTOMER_REJECTED},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(
            Ticket.objects.filter(extra_work_request=ew).count(), 0
        )

    def test_spawn_endpoint_retry_is_idempotent(self):
        ew = self._make_quote_ew()
        proposal_id = self._build_sent_proposal(ew)
        resp = self._api(self.cust_user).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal_id}/transition/",
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(
            Ticket.objects.filter(extra_work_request=ew).count(), 1
        )
        existing = Ticket.objects.get(extra_work_request=ew)

        # Retry the spawn endpoint — must NOT create a duplicate and
        # must report already_spawned with the existing id.
        resp = self._api(self.super_admin).post(SPAWN_URL.format(ew_id=ew.id))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data["already_spawned"])
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["spawned_ticket_ids"], [existing.id])
        self.assertEqual(
            Ticket.objects.filter(extra_work_request=ew).count(), 1
        )
