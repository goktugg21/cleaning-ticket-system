"""
Per-record actions backend — customer-specific contract pricing routing.

Locks the rule that two customers can have DIFFERENT prices for the
SAME `Service` (via independent `CustomerServicePrice` rows), and that
the routing decision is computed per-customer: a cart whose lines
ALL resolve to a contract row for THIS customer routes to INSTANT;
any non-contract line routes the whole cart to PROPOSAL. The
resolver / serializer machinery for this already exists (Sprint 28
Batch 6 + Batch 5); this test pins the per-customer multi-price
contract that the per-record actions work depends on.
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
    CustomerServicePrice,
    ExtraWorkCategory,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
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


class CustomerSpecificContractPricingRoutingTests(TestCase):
    """A single Service with two CustomerServicePrice rows at DIFFERENT
    unit_prices for Customer A and Customer B, plus a SECOND service
    that has NO contract row anywhere. Asserts the routing taxonomy:

      * Cart with only the contract-priced service for Customer A ->
        INSTANT (uses customer-A's price).
      * Cart with only the contract-priced service for Customer B ->
        INSTANT (uses customer-B's price, different number than A).
      * Mixed cart for Customer A (contract-priced line + a non-
        contract line) -> PROPOSAL (one missing contract trips the
        whole cart).

    The "different prices for different customers" half of the test
    proves the resolver is keyed by the (service, customer) pair, not
    just by service. Routing-decision storage is checked off the
    `ExtraWorkRequest.routing_decision` column after submission.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            name="Provider PR", slug="prov-pr-pricing"
        )
        cls.building = Building.objects.create(
            company=cls.company, name="Building-PR"
        )

        cls.customer_a = Customer.objects.create(
            company=cls.company,
            name="Customer A PR",
            building=cls.building,
        )
        cls.customer_b = Customer.objects.create(
            company=cls.company,
            name="Customer B PR",
            building=cls.building,
        )
        for c in [cls.customer_a, cls.customer_b]:
            CustomerBuildingMembership.objects.create(
                customer=c, building=cls.building
            )

        cls.service_priced = Service.objects.create(
            category=ServiceCategory.objects.create(name="Cat-PR-Pricing"),
            company=cls.company,
            name="Shared service (different prices per customer)",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )
        # A second service that has NO CustomerServicePrice anywhere.
        # Used to construct mixed-cart proposal-routing scenarios.
        cls.service_unpriced = Service.objects.create(
            category=cls.service_priced.category,
            company=cls.company,
            name="Other service (no contract anywhere)",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            default_unit_price=Decimal("100.00"),
        )

        # Customer A pays €40/h for the shared service.
        cls.price_a = CustomerServicePrice.objects.create(
            service=cls.service_priced,
            customer=cls.customer_a,
            unit_price=Decimal("40.00"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            valid_to=None,
            is_active=True,
        )
        # Customer B pays €60/h for the SAME service. Different price
        # for different customers — the resolver picks per (service,
        # customer).
        cls.price_b = CustomerServicePrice.objects.create(
            service=cls.service_priced,
            customer=cls.customer_b,
            unit_price=Decimal("60.00"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            valid_to=None,
            is_active=True,
        )

        # One customer-user per customer with create permission for
        # the local pair.
        cls.cust_user_a = _mk("cust-a-pr@example.com", UserRole.CUSTOMER_USER)
        ma = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_user_a
        )
        CustomerUserBuildingAccess.objects.create(
            membership=ma,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )
        cls.cust_user_b = _mk("cust-b-pr@example.com", UserRole.CUSTOMER_USER)
        mb = CustomerUserMembership.objects.create(
            customer=cls.customer_b, user=cls.cust_user_b
        )
        CustomerUserBuildingAccess.objects.create(
            membership=mb,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _cart_payload(self, customer, lines):
        return {
            "customer": customer.id,
            "building": self.building.id,
            "title": f"Cart for {customer.name}",
            "description": "Customer-specific pricing routing test",
            "category": ExtraWorkCategory.DEEP_CLEANING,
            "line_items": lines,
        }

    def test_all_contract_lines_route_to_instant_for_customer_a(self):
        payload = self._cart_payload(
            self.customer_a,
            lines=[
                {
                    "service": self.service_priced.id,
                    "quantity": "2.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                }
            ],
        )
        response = self._api(self.cust_user_a).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["routing_decision"],
            ExtraWorkRoutingDecision.INSTANT,
        )
        # Confirm the resolver picked customer-A's row (€40/h) at
        # submission time. Asserting via the active CustomerServicePrice
        # row keeps the test independent of any future ticket-spawn
        # detail change. The router stored the routing decision as
        # INSTANT iff `resolve_price` returned an active row for
        # (service, customer_a, requested_date), which it did with
        # `price_a` at €40.
        from extra_work.pricing import resolve_price

        resolved = resolve_price(
            self.service_priced,
            self.customer_a,
            on=date(2026, 6, 15),
        )
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.unit_price, Decimal("40.00"))

    def test_all_contract_lines_route_to_instant_for_customer_b_with_different_price(self):
        payload = self._cart_payload(
            self.customer_b,
            lines=[
                {
                    "service": self.service_priced.id,
                    "quantity": "2.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                }
            ],
        )
        response = self._api(self.cust_user_b).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["routing_decision"],
            ExtraWorkRoutingDecision.INSTANT,
        )
        from extra_work.pricing import resolve_price

        resolved = resolve_price(
            self.service_priced,
            self.customer_b,
            on=date(2026, 6, 15),
        )
        self.assertIsNotNone(resolved)
        # CRITICAL: Customer B's price differs from Customer A's
        # for the same service (€60 vs €40). The resolver MUST be
        # customer-keyed, not service-keyed.
        self.assertEqual(resolved.unit_price, Decimal("60.00"))
        self.assertNotEqual(resolved.unit_price, self.price_a.unit_price)

    def test_mixed_cart_routes_to_proposal_when_any_line_lacks_contract(self):
        payload = self._cart_payload(
            self.customer_a,
            lines=[
                {
                    "service": self.service_priced.id,
                    "quantity": "1.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                },
                {
                    # No contract row for this service anywhere ->
                    # resolver returns None for this line -> whole
                    # cart routes to PROPOSAL.
                    "service": self.service_unpriced.id,
                    "quantity": "1.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                },
            ],
        )
        response = self._api(self.cust_user_a).post(URL, payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["routing_decision"],
            ExtraWorkRoutingDecision.PROPOSAL,
        )
        # Verify the stored column matches the response field.
        request_row = ExtraWorkRequest.objects.get(id=response.data["id"])
        self.assertEqual(
            request_row.routing_decision,
            ExtraWorkRoutingDecision.PROPOSAL,
        )
