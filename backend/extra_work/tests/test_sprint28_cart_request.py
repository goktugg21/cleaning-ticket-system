"""
Sprint 28 Batch 6 — cart-submission backend tests.

The ExtraWorkRequest endpoint now accepts a `line_items` array of
catalog-linked cart lines. Each submission computes a
`routing_decision` ("INSTANT" if every line resolves to an active
CustomerServicePrice row, "PROPOSAL" otherwise). Batch 6 stores the
decision but does NOT spawn tickets / proposals; those land in
Batches 7 and 8.

Test classes:
  * CartRequestCreateTests       — happy-path shape + per-line fields
  * CartRequestRoutingDecisionTests — INSTANT / PROPOSAL combinations
  * CartRequestValidationTests   — 400-case coverage
  * CartRequestDoesNotSpawnTicketTests — locks "Batch 6 does not act"
  * CartRequestScopeTests        — cross-tenant rejection + STAFF
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)

from extra_work.models import (
    CustomerServicePrice,
    ExtraWorkCategory,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkRoutingDecision,
    Service,
    ServiceCategory,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
URL = "/api/extra-work/"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class CartFixtureMixin:
    """
    Compact two-customer fixture: provider_a + two customers
    (customer_a, customer_a_alt) under it, a second provider B, a
    catalog with two active services, and a basic customer-user with
    create permission on customer_a / building_a1.
    """

    @classmethod
    def _setup_fixture(cls):
        cls.provider_a = Company.objects.create(
            name="Provider A", slug="prov-a-b6"
        )
        cls.provider_b = Company.objects.create(
            name="Provider B", slug="prov-b-b6"
        )
        cls.building_a1 = Building.objects.create(
            company=cls.provider_a, name="A1"
        )
        cls.building_a2 = Building.objects.create(
            company=cls.provider_a, name="A2"
        )
        cls.building_b = Building.objects.create(
            company=cls.provider_b, name="B1"
        )

        cls.customer_a = Customer.objects.create(
            company=cls.provider_a,
            name="Customer A",
            building=cls.building_a1,
        )
        cls.customer_a_alt = Customer.objects.create(
            company=cls.provider_a,
            name="Customer A-alt",
            building=cls.building_a1,
        )
        cls.customer_b = Customer.objects.create(
            company=cls.provider_b,
            name="Customer B",
            building=cls.building_b,
        )

        for c, b in [
            (cls.customer_a, cls.building_a1),
            (cls.customer_a_alt, cls.building_a1),
            (cls.customer_b, cls.building_b),
        ]:
            CustomerBuildingMembership.objects.create(customer=c, building=b)

        cls.super_admin = _mk(
            "super-b6@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin_a = _mk("admin-a-b6@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin_a, company=cls.provider_a
        )

        cls.staff = _mk("staff-b6@example.com", UserRole.STAFF)
        # STAFF is per the cart-flow contract intentionally blocked
        # from extra-work scope (extra_work/scoping.py returns
        # .none()); no extra wiring needed.

        cls.cust_basic_a = _mk("cust-b6@example.com", UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_basic_a
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building_a1,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        # Customer-A-alt user — used to test that one customer-user
        # cannot create under another customer.
        cls.cust_alt = _mk("cust-alt-b6@example.com", UserRole.CUSTOMER_USER)
        alt_membership = CustomerUserMembership.objects.create(
            customer=cls.customer_a_alt, user=cls.cust_alt
        )
        CustomerUserBuildingAccess.objects.create(
            membership=alt_membership,
            building=cls.building_a1,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        cls.service_cat = ServiceCategory.objects.create(name="Cleaning")
        cls.service_priced = Service.objects.create(
            category=cls.service_cat,
            name="Window cleaning",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )
        cls.service_unpriced = Service.objects.create(
            category=cls.service_cat,
            name="Floor maintenance",
            unit_type=ExtraWorkPricingUnitType.SQUARE_METERS,
            default_unit_price=Decimal("3.50"),
        )
        cls.service_inactive = Service.objects.create(
            category=cls.service_cat,
            name="Discontinued",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            default_unit_price=Decimal("100.00"),
            is_active=False,
        )

        # An active contract row for customer_a + service_priced. The
        # date window spans the test horizon below.
        cls.contract_price = CustomerServicePrice.objects.create(
            service=cls.service_priced,
            customer=cls.customer_a,
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

    def _base_payload(self, customer=None, building=None, **extra):
        customer = customer or self.customer_a
        building = building or self.building_a1
        payload = {
            "customer": customer.id,
            "building": building.id,
            "title": "Cart submission",
            "description": "shopping cart",
            "category": ExtraWorkCategory.DEEP_CLEANING,
            "line_items": [
                {
                    "service": self.service_priced.id,
                    "quantity": "2.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "Top floor",
                }
            ],
        }
        payload.update(extra)
        return payload


# ---------------------------------------------------------------------------
# Happy-path shape
# ---------------------------------------------------------------------------
class CartRequestCreateTests(CartFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_customer_can_post_cart_with_multiple_lines(self):
        payload = self._base_payload()
        payload["line_items"] = [
            {
                "service": self.service_priced.id,
                "quantity": "2.00",
                "requested_date": "2026-06-15",
                "customer_note": "Top floor",
            },
            {
                "service": self.service_unpriced.id,
                "quantity": "50.00",
                "requested_date": "2026-06-20",
                "customer_note": "",
            },
        ]
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        # The detail-serializer response carries the nested lines and
        # the routing_decision field.
        self.assertIn("line_items", response.data)
        self.assertEqual(len(response.data["line_items"]), 2)
        self.assertIn("routing_decision", response.data)
        # The persisted line items match input.
        request = ExtraWorkRequest.objects.get(id=response.data["id"])
        lines = list(request.line_items.all().order_by("id"))
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].service_id, self.service_priced.id)
        self.assertEqual(lines[0].quantity, Decimal("2.00"))
        self.assertEqual(lines[0].requested_date, date(2026, 6, 15))
        self.assertEqual(lines[0].customer_note, "Top floor")
        # `unit_type` denormalised from Service.unit_type at create
        # time (HOURS on the priced service).
        self.assertEqual(lines[0].unit_type, ExtraWorkPricingUnitType.HOURS)
        # Second line denormalises SQUARE_METERS from service_unpriced.
        self.assertEqual(
            lines[1].unit_type, ExtraWorkPricingUnitType.SQUARE_METERS
        )

    def test_unit_type_is_pinned_at_create_time(self):
        # Submit a cart, then mutate the catalog row — the historical
        # line's unit_type must not change.
        response = self._api(self.cust_basic_a).post(
            URL, self._base_payload(), format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        request = ExtraWorkRequest.objects.get(id=response.data["id"])
        line = request.line_items.get()
        self.assertEqual(line.unit_type, ExtraWorkPricingUnitType.HOURS)

        self.service_priced.unit_type = ExtraWorkPricingUnitType.FIXED
        self.service_priced.save(update_fields=["unit_type"])
        line.refresh_from_db()
        self.assertEqual(line.unit_type, ExtraWorkPricingUnitType.HOURS)

    def test_per_line_requested_date_distinct_from_preferred_date(self):
        payload = self._base_payload(preferred_date="2026-07-01")
        payload["line_items"][0]["requested_date"] = "2026-06-15"
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        request = ExtraWorkRequest.objects.get(id=response.data["id"])
        self.assertEqual(request.preferred_date, date(2026, 7, 1))
        line = request.line_items.get()
        self.assertEqual(line.requested_date, date(2026, 6, 15))


# ---------------------------------------------------------------------------
# Routing decision computation
# ---------------------------------------------------------------------------
class CartRequestRoutingDecisionTests(CartFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_all_lines_priced_routes_to_instant(self):
        # service_priced has a contract row for customer_a; submitting
        # one line referencing it should route to INSTANT.
        response = self._api(self.cust_basic_a).post(
            URL, self._base_payload(), format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["routing_decision"],
            ExtraWorkRoutingDecision.INSTANT,
        )

    def test_any_line_unpriced_routes_to_proposal(self):
        payload = self._base_payload()
        payload["line_items"] = [
            {
                "service": self.service_priced.id,
                "quantity": "1.00",
                "requested_date": "2026-06-15",
                "customer_note": "",
            },
            {
                # No contract row exists for this service ↦ resolver
                # returns None ↦ whole cart routes to PROPOSAL.
                "service": self.service_unpriced.id,
                "quantity": "1.00",
                "requested_date": "2026-06-15",
                "customer_note": "",
            },
        ]
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["routing_decision"],
            ExtraWorkRoutingDecision.PROPOSAL,
        )

    def test_all_lines_unpriced_routes_to_proposal(self):
        payload = self._base_payload()
        payload["line_items"] = [
            {
                "service": self.service_unpriced.id,
                "quantity": "1.00",
                "requested_date": "2026-06-15",
                "customer_note": "",
            },
        ]
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["routing_decision"],
            ExtraWorkRoutingDecision.PROPOSAL,
        )

    def test_resolver_called_with_per_line_date(self):
        # Date outside the contract window ↦ resolver returns None
        # even though there IS a contract row for this service. This
        # locks the "resolver is called with line.requested_date"
        # contract.
        payload = self._base_payload()
        payload["line_items"][0]["requested_date"] = "2025-12-01"
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["routing_decision"],
            ExtraWorkRoutingDecision.PROPOSAL,
        )

    def test_inactive_contract_routes_to_proposal(self):
        self.contract_price.is_active = False
        self.contract_price.save(update_fields=["is_active"])
        response = self._api(self.cust_basic_a).post(
            URL, self._base_payload(), format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["routing_decision"],
            ExtraWorkRoutingDecision.PROPOSAL,
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
class CartRequestValidationTests(CartFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_empty_line_items_rejected(self):
        payload = self._base_payload()
        payload["line_items"] = []
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_missing_line_items_rejected(self):
        payload = self._base_payload()
        payload.pop("line_items")
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_duplicate_service_in_cart_rejected(self):
        payload = self._base_payload()
        payload["line_items"] = [
            {
                "service": self.service_priced.id,
                "quantity": "1.00",
                "requested_date": "2026-06-15",
                "customer_note": "",
            },
            {
                "service": self.service_priced.id,
                "quantity": "2.00",
                "requested_date": "2026-06-20",
                "customer_note": "",
            },
        ]
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_inactive_service_rejected(self):
        payload = self._base_payload()
        payload["line_items"][0]["service"] = self.service_inactive.id
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_negative_quantity_rejected(self):
        payload = self._base_payload()
        payload["line_items"][0]["quantity"] = "-1.00"
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_zero_quantity_rejected(self):
        payload = self._base_payload()
        payload["line_items"][0]["quantity"] = "0.00"
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_missing_requested_date_rejected(self):
        payload = self._base_payload()
        payload["line_items"][0].pop("requested_date")
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)


# ---------------------------------------------------------------------------
# Routing → ticket-spawn + status contract (Sprint 28 Batch 7 update)
# ---------------------------------------------------------------------------
# Originally Batch 6 locked "INSTANT routing must NOT spawn tickets and
# the request must stay at REQUESTED". Batch 7 reverses that contract on
# the INSTANT branch only: the spawn service now creates one Ticket per
# line and drives the parent to CUSTOMER_APPROVED. The PROPOSAL branch
# keeps the original Batch 6 behaviour (no tickets, status stays at
# REQUESTED). These tests pin both shapes.
class CartRequestRoutingSpawnTests(CartFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_instant_routing_spawns_one_ticket_per_line(self):
        # Sprint 28 Batch 7 — INSTANT routing now DOES spawn one Ticket
        # per ExtraWorkRequestItem, anchored to the parent request via
        # the new `Ticket.extra_work_request_item` FK.
        from tickets.models import Ticket

        before = Ticket.objects.count()
        response = self._api(self.cust_basic_a).post(
            URL, self._base_payload(), format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["routing_decision"],
            ExtraWorkRoutingDecision.INSTANT,
        )
        # Exactly one new Ticket — the cart had one line.
        self.assertEqual(Ticket.objects.count(), before + 1)
        request = ExtraWorkRequest.objects.get(id=response.data["id"])
        line = request.line_items.get()
        self.assertEqual(line.spawned_tickets.count(), 1)

    def test_proposal_routing_does_not_spawn_tickets(self):
        # Batch 6 contract preserved for the PROPOSAL branch: when any
        # line has no contract price, no Tickets are spawned by
        # submission. Batch 8 will wire the proposal-approval spawn.
        from tickets.models import Ticket

        before = Ticket.objects.count()
        payload = self._base_payload()
        payload["line_items"][0]["service"] = self.service_unpriced.id
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["routing_decision"],
            ExtraWorkRoutingDecision.PROPOSAL,
        )
        self.assertEqual(Ticket.objects.count(), before)

    def test_instant_routing_advances_status_to_customer_approved(self):
        # Sprint 28 Batch 7 — INSTANT routing auto-approves the request
        # (the customer's submission IS the approval because the price
        # is contract-locked). PROPOSAL routing keeps the original Batch
        # 6 behaviour: the request stays at REQUESTED until a provider
        # operator drives it forward.
        for line_service, expected_routing, expected_status in (
            (
                self.service_priced,
                ExtraWorkRoutingDecision.INSTANT,
                "CUSTOMER_APPROVED",
            ),
            (
                self.service_unpriced,
                ExtraWorkRoutingDecision.PROPOSAL,
                "REQUESTED",
            ),
        ):
            payload = self._base_payload()
            payload["line_items"][0]["service"] = line_service.id
            response = self._api(self.cust_basic_a).post(
                URL, payload, format="json"
            )
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(
                response.data["routing_decision"], expected_routing
            )
            self.assertEqual(response.data["status"], expected_status)


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------
class CartRequestScopeTests(CartFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_customer_a_user_cannot_post_for_customer_b(self):
        payload = self._base_payload(
            customer=self.customer_b, building=self.building_b
        )
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_customer_a_user_cannot_post_for_customer_a_alt(self):
        payload = self._base_payload(
            customer=self.customer_a_alt, building=self.building_a1
        )
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_staff_cannot_post(self):
        # STAFF has no extra-work scope at all (scoping returns .none())
        # and falls into the catch-all "this role cannot create" branch
        # of the create serializer ⇒ 400.
        response = self._api(self.staff).post(
            URL, self._base_payload(), format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
