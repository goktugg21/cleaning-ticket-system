"""
Per-line pricing-source fields on every Extra Work line serializer
plus the `?customer=<id>` query-param filter on the EW list endpoint.

Pins the wire-shape contract the frontend invoice renderer consumes:

  * Every line shape (cart line, proposal line admin, proposal line
    customer, pricing line admin, pricing line customer) emits the
    same three fields:

      - `price_source`: stable enum string. Values:
          "CONTRACT"        — line is anchored to an active
                              `CustomerServicePrice` row.
          "CUSTOM"          — operator-typed price; either no contract
                              row exists OR the line's snapshot diverges
                              from the contract.
          "NEEDS_PROPOSAL"  — cart line with no contract row resolvable
                              (only emitted by `ExtraWorkRequestItem`).
      - `contract_unit_price`: Decimal-as-string OR None.
      - `contract_vat_pct`:    Decimal-as-string OR None.

  * Snapshot rule: a persisted proposal line carries its own
    `unit_price` + `vat_pct` and the serializer NEVER mutates them.
    When the proposal line is labelled CONTRACT, the `contract_*`
    fields mirror the line's snapshot (which by construction equals
    the contract row's values at the moment we resolve). When the
    contract row exists but the prices diverge — operator overrode it
    on the proposal — the line is CUSTOM.

  * Cart lines (`ExtraWorkRequestItem`) have no persisted price
    snapshot of their own. The resolver IS the truth at read time.

  * Customer-facing read paths surface the three fields (they are
    customer-safe — same numbers the customer already sees) but
    continue to redact `internal_cost_note` / `internal_note`.

  * `/api/extra-work/?customer=<id>` filter composes with the existing
    scope helper. Non-integer values are rejected with HTTP 400.
"""
from __future__ import annotations

from datetime import date
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
    ExtraWorkPricingLineItem,
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


class _LineSourceFixtureMixin:
    """Compact fixture: provider with one building, one customer, one
    service catalog with two services (one contract-priced, one not).
    Built once per test class via setUpTestData on the subclasses.
    """

    @classmethod
    def _setup(cls):
        cls.company = Company.objects.create(
            name="Provider LS", slug="prov-line-source"
        )
        cls.building = Building.objects.create(
            company=cls.company, name="Building-LS-A"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            name="Customer-LS-A",
            building=cls.building,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            "super-ls@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-ls@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

        cls.cust_user = _mk("cust-ls@example.com", UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        cls.service_cat = ServiceCategory.objects.create(name="Cleaning-LS")
        cls.service_priced = Service.objects.create(
            category=cls.service_cat,
            name="Window cleaning LS",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )
        cls.service_unpriced = Service.objects.create(
            category=cls.service_cat,
            name="Floor maintenance LS",
            unit_type=ExtraWorkPricingUnitType.SQUARE_METERS,
            default_unit_price=Decimal("3.50"),
        )

        # Contract row that the resolver will return for
        # `service_priced` + `customer`. service_unpriced has NO
        # contract row.
        cls.contract = CustomerServicePrice.objects.create(
            service=cls.service_priced,
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

    def _cart_payload(self, lines):
        return {
            "customer": self.customer.id,
            "building": self.building.id,
            "title": "Line-source cart",
            "description": "cart for line-source tests",
            "category": ExtraWorkCategory.DEEP_CLEANING,
            "line_items": lines,
        }

    def _submit_cart(self, lines):
        response = self._api(self.cust_user).post(
            URL, self._cart_payload(lines), format="json"
        )
        assert response.status_code == 201, response.data
        return response

    def _ew(self, ew_id):
        return ExtraWorkRequest.objects.get(id=ew_id)

    def _make_proposal(self, ew, *, status=ProposalStatus.DRAFT):
        proposal = Proposal.objects.create(
            extra_work_request=ew,
            status=status,
            created_by=self.admin,
        )
        proposal.recompute_totals()
        proposal.refresh_from_db()
        return proposal


# ---------------------------------------------------------------------------
# Acceptance criterion 1 — CONTRACT cart line
# ---------------------------------------------------------------------------
class CartLineContractTests(_LineSourceFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup()

    def test_contract_cart_line_emits_contract_source_and_values(self):
        # service_priced has an active contract row at requested_date
        # 2026-06-15. The cart line should surface price_source=
        # CONTRACT with the contract's unit_price + vat_pct.
        response = self._submit_cart(
            [
                {
                    "service": self.service_priced.id,
                    "quantity": "2.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                }
            ]
        )
        # Read the detail back to get the canonical line shape.
        ew_id = response.data["id"]
        detail = self._api(self.admin).get(f"{URL}{ew_id}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        lines = detail.data["line_items"]
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertEqual(line["price_source"], "CONTRACT")
        self.assertEqual(line["contract_unit_price"], "48.50")
        self.assertEqual(line["contract_vat_pct"], "21.00")


# ---------------------------------------------------------------------------
# Acceptance criterion 2 — NEEDS_PROPOSAL cart line
# ---------------------------------------------------------------------------
class CartLineNeedsProposalTests(_LineSourceFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup()

    def test_no_contract_cart_line_emits_needs_proposal_and_nulls(self):
        response = self._submit_cart(
            [
                {
                    # service_unpriced has NO CustomerServicePrice row
                    # for self.customer.
                    "service": self.service_unpriced.id,
                    "quantity": "100.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                }
            ]
        )
        ew_id = response.data["id"]
        # routing_decision must be PROPOSAL — pins the surrounding
        # contract that a no-contract line never routes INSTANT.
        self.assertEqual(
            response.data["routing_decision"],
            ExtraWorkRoutingDecision.PROPOSAL,
        )
        detail = self._api(self.admin).get(f"{URL}{ew_id}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        line = detail.data["line_items"][0]
        self.assertEqual(line["price_source"], "NEEDS_PROPOSAL")
        self.assertIsNone(line["contract_unit_price"])
        self.assertIsNone(line["contract_vat_pct"])


# ---------------------------------------------------------------------------
# Acceptance criterion 3 — CONTRACT proposal line (snapshot matches)
# ---------------------------------------------------------------------------
class ProposalLineContractTests(_LineSourceFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup()

    def test_proposal_line_matching_contract_emits_contract_source(self):
        # 1) Build an EW with the unpriced service so we go through the
        #    proposal flow.
        response = self._submit_cart(
            [
                {
                    "service": self.service_unpriced.id,
                    "quantity": "1.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                }
            ]
        )
        ew = self._ew(response.data["id"])
        # Drive to UNDER_REVIEW so we can create a proposal.
        ew.status = ExtraWorkStatus.UNDER_REVIEW
        ew.save(update_fields=["status"])

        # 2) Build a proposal line whose unit_price + vat_pct EXACTLY
        #    match the contract row for service_priced + customer.
        proposal = self._make_proposal(ew)
        ProposalLine.objects.create(
            proposal=proposal,
            service=self.service_priced,
            description="",
            quantity=Decimal("2.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            unit_price=self.contract.unit_price,  # 48.50
            vat_pct=self.contract.vat_pct,        # 21.00
            customer_explanation="",
            internal_note="",
            is_approved_for_spawn=True,
        )
        proposal.recompute_totals()
        proposal.refresh_from_db()

        # 3) Read the proposal as admin and assert.
        detail = self._api(self.admin).get(
            f"{URL}{ew.id}/proposals/{proposal.id}/"
        )
        self.assertEqual(detail.status_code, 200, detail.data)
        lines = detail.data["lines"]
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertEqual(line["price_source"], "CONTRACT")
        self.assertEqual(line["contract_unit_price"], "48.50")
        self.assertEqual(line["contract_vat_pct"], "21.00")


# ---------------------------------------------------------------------------
# Acceptance criterion 4 — CUSTOM proposal line (operator overrode contract)
# ---------------------------------------------------------------------------
class ProposalLineCustomOverrideTests(_LineSourceFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup()

    def test_proposal_line_diverging_from_contract_is_custom(self):
        # Even though a contract row exists for service_priced, the
        # operator typed a different unit_price on the proposal line.
        # The snapshot is the line's typed value — classify CUSTOM.
        response = self._submit_cart(
            [
                {
                    "service": self.service_unpriced.id,
                    "quantity": "1.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                }
            ]
        )
        ew = self._ew(response.data["id"])
        ew.status = ExtraWorkStatus.UNDER_REVIEW
        ew.save(update_fields=["status"])
        proposal = self._make_proposal(ew)

        # Operator's typed price diverges from contract (48.50 vs 60).
        ProposalLine.objects.create(
            proposal=proposal,
            service=self.service_priced,
            description="",
            quantity=Decimal("3.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            unit_price=Decimal("60.00"),
            vat_pct=Decimal("21.00"),
            customer_explanation="surcharge applied",
            internal_note="margin lift requested by sales",
        )
        proposal.recompute_totals()

        detail = self._api(self.admin).get(
            f"{URL}{ew.id}/proposals/{proposal.id}/"
        )
        self.assertEqual(detail.status_code, 200, detail.data)
        line = detail.data["lines"][0]
        # The persisted snapshot is still 60.00 — the serializer
        # never mutates it.
        self.assertEqual(line["unit_price"], "60.00")
        self.assertEqual(line["vat_pct"], "21.00")
        # But the source is CUSTOM and the contract_* fields are null
        # — the operator overrode the contract on this proposal.
        self.assertEqual(line["price_source"], "CUSTOM")
        self.assertIsNone(line["contract_unit_price"])
        self.assertIsNone(line["contract_vat_pct"])

    def test_contract_edit_does_not_rewrite_snapshot_on_contract_line(self):
        # Defence-in-depth on the snapshot rule. Build a CONTRACT-
        # labelled proposal line, then mutate the underlying
        # CustomerServicePrice row's unit_price. The serializer must:
        #   * keep the line's persisted `unit_price` unchanged,
        #   * KEEP the line labelled CUSTOM going forward (because the
        #     contract row no longer matches the snapshot).
        #
        # This pins the "we never silently re-resolve on read" rule.
        response = self._submit_cart(
            [
                {
                    "service": self.service_unpriced.id,
                    "quantity": "1.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                }
            ]
        )
        ew = self._ew(response.data["id"])
        ew.status = ExtraWorkStatus.UNDER_REVIEW
        ew.save(update_fields=["status"])
        proposal = self._make_proposal(ew)
        ProposalLine.objects.create(
            proposal=proposal,
            service=self.service_priced,
            description="",
            quantity=Decimal("2.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            unit_price=self.contract.unit_price,  # 48.50
            vat_pct=self.contract.vat_pct,        # 21.00
            customer_explanation="",
            internal_note="",
        )
        proposal.recompute_totals()

        # Mutate the contract row underneath.
        self.contract.unit_price = Decimal("99.99")
        self.contract.save(update_fields=["unit_price"])

        detail = self._api(self.admin).get(
            f"{URL}{ew.id}/proposals/{proposal.id}/"
        )
        self.assertEqual(detail.status_code, 200, detail.data)
        line = detail.data["lines"][0]
        # Snapshot UNCHANGED.
        self.assertEqual(line["unit_price"], "48.50")
        # And because the contract no longer matches the snapshot,
        # the source flipped to CUSTOM (the operator's 48.50 is no
        # longer "the contract price").
        self.assertEqual(line["price_source"], "CUSTOM")
        self.assertIsNone(line["contract_unit_price"])
        self.assertIsNone(line["contract_vat_pct"])


# ---------------------------------------------------------------------------
# Acceptance criterion 5 — Ad-hoc proposal line (no service FK)
# ---------------------------------------------------------------------------
class ProposalLineAdHocTests(_LineSourceFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup()

    def test_ad_hoc_proposal_line_is_custom(self):
        response = self._submit_cart(
            [
                {
                    "service": self.service_unpriced.id,
                    "quantity": "1.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                }
            ]
        )
        ew = self._ew(response.data["id"])
        ew.status = ExtraWorkStatus.UNDER_REVIEW
        ew.save(update_fields=["status"])
        proposal = self._make_proposal(ew)

        ProposalLine.objects.create(
            proposal=proposal,
            service=None,  # ad-hoc
            description="Weekend cleanup surcharge",
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.FIXED,
            unit_price=Decimal("250.00"),
            vat_pct=Decimal("21.00"),
            customer_explanation="One-off charge",
            internal_note="",
        )
        proposal.recompute_totals()

        detail = self._api(self.admin).get(
            f"{URL}{ew.id}/proposals/{proposal.id}/"
        )
        self.assertEqual(detail.status_code, 200, detail.data)
        line = detail.data["lines"][0]
        self.assertEqual(line["price_source"], "CUSTOM")
        self.assertIsNone(line["contract_unit_price"])
        self.assertIsNone(line["contract_vat_pct"])


# ---------------------------------------------------------------------------
# Acceptance criterion 6 — Mixed cart (one contract + one needs-proposal)
# ---------------------------------------------------------------------------
class MixedCartTests(_LineSourceFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup()

    def test_mixed_cart_lines_emit_independent_sources(self):
        response = self._submit_cart(
            [
                {
                    "service": self.service_priced.id,
                    "quantity": "1.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                },
                {
                    "service": self.service_unpriced.id,
                    "quantity": "10.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                },
            ]
        )
        # Any non-contract line routes the whole cart to PROPOSAL.
        self.assertEqual(
            response.data["routing_decision"],
            ExtraWorkRoutingDecision.PROPOSAL,
        )

        ew_id = response.data["id"]
        detail = self._api(self.admin).get(f"{URL}{ew_id}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        lines = detail.data["line_items"]
        # Lines are ordered by id. The priced one is first.
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["price_source"], "CONTRACT")
        self.assertEqual(lines[0]["contract_unit_price"], "48.50")
        self.assertEqual(lines[0]["contract_vat_pct"], "21.00")
        self.assertEqual(lines[1]["price_source"], "NEEDS_PROPOSAL")
        self.assertIsNone(lines[1]["contract_unit_price"])
        self.assertIsNone(lines[1]["contract_vat_pct"])


# ---------------------------------------------------------------------------
# Acceptance criterion 7 — Customer-facing safety
# ---------------------------------------------------------------------------
class CustomerFacingFieldVisibilityTests(_LineSourceFixtureMixin, TestCase):
    """The three new fields are customer-safe by construction (same
    numbers the customer already sees in unit_price / vat_pct), so they
    MUST appear on the customer-facing serializers. The existing
    customer/provider visibility split for `internal_*` notes is
    unaffected."""

    @classmethod
    def setUpTestData(cls):
        cls._setup()

    def test_customer_sees_cart_line_source_fields(self):
        response = self._submit_cart(
            [
                {
                    "service": self.service_priced.id,
                    "quantity": "1.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                }
            ]
        )
        ew_id = response.data["id"]
        detail = self._api(self.cust_user).get(f"{URL}{ew_id}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        line = detail.data["line_items"][0]
        self.assertIn("price_source", line)
        self.assertIn("contract_unit_price", line)
        self.assertIn("contract_vat_pct", line)
        self.assertEqual(line["price_source"], "CONTRACT")
        self.assertEqual(line["contract_unit_price"], "48.50")
        self.assertEqual(line["contract_vat_pct"], "21.00")

    def test_customer_sees_proposal_line_source_fields_no_internal_note(self):
        # Create an EW + UNDER_REVIEW + DRAFT proposal with an
        # `internal_note` populated. The customer must see the line's
        # source fields but must NOT see `internal_note`.
        response = self._submit_cart(
            [
                {
                    "service": self.service_unpriced.id,
                    "quantity": "1.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                }
            ]
        )
        ew = self._ew(response.data["id"])
        ew.status = ExtraWorkStatus.UNDER_REVIEW
        ew.save(update_fields=["status"])
        proposal = self._make_proposal(ew, status=ProposalStatus.SENT)
        ProposalLine.objects.create(
            proposal=proposal,
            service=self.service_priced,
            description="",
            quantity=Decimal("2.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            unit_price=self.contract.unit_price,
            vat_pct=self.contract.vat_pct,
            customer_explanation="visible to customer",
            internal_note="hidden margin note",
        )
        proposal.recompute_totals()

        detail = self._api(self.cust_user).get(
            f"{URL}{ew.id}/proposals/{proposal.id}/"
        )
        self.assertEqual(detail.status_code, 200, detail.data)
        line = detail.data["lines"][0]
        # New source fields present + correct.
        self.assertEqual(line["price_source"], "CONTRACT")
        self.assertEqual(line["contract_unit_price"], "48.50")
        self.assertEqual(line["contract_vat_pct"], "21.00")
        # internal_note STRIPPED from the customer-facing serializer.
        self.assertNotIn("internal_note", line)
        # customer_explanation is the customer-visible counterpart.
        self.assertEqual(line["customer_explanation"], "visible to customer")

    def test_customer_sees_pricing_line_source_fields_no_internal_cost_note(self):
        # The legacy ExtraWorkPricingLineItem shape: customer-facing
        # serializer must surface the three source fields (always
        # CUSTOM, contract_* null) and must NOT carry
        # `internal_cost_note`.
        response = self._submit_cart(
            [
                {
                    "service": self.service_unpriced.id,
                    "quantity": "1.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                }
            ]
        )
        ew = self._ew(response.data["id"])
        ExtraWorkPricingLineItem.objects.create(
            extra_work=ew,
            description="Hourly cleaning",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            quantity=Decimal("4.00"),
            unit_price=Decimal("40.00"),
            vat_rate=Decimal("21.00"),
            customer_visible_note="visible",
            internal_cost_note="hidden cost note",
        )
        ew.recompute_totals()

        detail = self._api(self.cust_user).get(f"{URL}{ew.id}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        items = detail.data["pricing_line_items"]
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["price_source"], "CUSTOM")
        self.assertIsNone(item["contract_unit_price"])
        self.assertIsNone(item["contract_vat_pct"])
        self.assertNotIn("internal_cost_note", item)
        self.assertEqual(item["customer_visible_note"], "visible")

    def test_pricing_line_admin_serializer_keeps_internal_cost_note(self):
        # Twin of the above — provider-side serializer keeps
        # internal_cost_note AND emits the source fields.
        response = self._submit_cart(
            [
                {
                    "service": self.service_unpriced.id,
                    "quantity": "1.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                }
            ]
        )
        ew = self._ew(response.data["id"])
        ExtraWorkPricingLineItem.objects.create(
            extra_work=ew,
            description="Hourly cleaning",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            quantity=Decimal("4.00"),
            unit_price=Decimal("40.00"),
            vat_rate=Decimal("21.00"),
            customer_visible_note="visible",
            internal_cost_note="hidden cost note",
        )
        ew.recompute_totals()

        detail = self._api(self.admin).get(f"{URL}{ew.id}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        item = detail.data["pricing_line_items"][0]
        self.assertEqual(item["price_source"], "CUSTOM")
        self.assertIsNone(item["contract_unit_price"])
        self.assertIsNone(item["contract_vat_pct"])
        self.assertEqual(item["internal_cost_note"], "hidden cost note")


# ---------------------------------------------------------------------------
# Acceptance criterion 8 — `?customer=<id>` filter
# ---------------------------------------------------------------------------
class CustomerFilterTests(_LineSourceFixtureMixin, TestCase):
    """Pins the headline list filter the customer detail Extra Work
    tab needs. Composes with `scope_extra_work_for` — never widens
    the queryset."""

    @classmethod
    def setUpTestData(cls):
        cls._setup()
        # Second customer + a building manager for the BM/CU
        # cross-tenant tests below.
        cls.customer_other = Customer.objects.create(
            company=cls.company,
            name="Customer-LS-Other",
            building=cls.building,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_other, building=cls.building
        )
        cls.bm = _mk("bm-ls@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.bm, building=cls.building
        )

    def _make_ew_for(self, customer, *, created_by=None):
        return ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=customer,
            created_by=created_by or self.admin,
            title=f"EW for {customer.name}",
            description="",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.REQUESTED,
        )

    def test_admin_filter_returns_only_target_customer(self):
        # Two EWs, one per customer.
        ew_a = self._make_ew_for(self.customer)
        self._make_ew_for(self.customer_other)
        response = self._api(self.admin).get(
            f"{URL}?customer={self.customer.id}"
        )
        self.assertEqual(response.status_code, 200, response.data)
        ids = [row["id"] for row in response.data["results"]]
        self.assertIn(ew_a.id, ids)
        self.assertEqual(len(ids), 1)
        # Every row in the response targets the requested customer.
        for row in response.data["results"]:
            self.assertEqual(row["customer"], self.customer.id)

    def test_super_admin_filter_returns_only_target_customer(self):
        ew_a = self._make_ew_for(self.customer)
        self._make_ew_for(self.customer_other)
        response = self._api(self.super_admin).get(
            f"{URL}?customer={self.customer.id}"
        )
        self.assertEqual(response.status_code, 200, response.data)
        ids = [row["id"] for row in response.data["results"]]
        self.assertEqual(ids, [ew_a.id])

    def test_bm_filter_composes_with_building_scope(self):
        ew_a = self._make_ew_for(self.customer)
        self._make_ew_for(self.customer_other)
        response = self._api(self.bm).get(
            f"{URL}?customer={self.customer.id}"
        )
        self.assertEqual(response.status_code, 200, response.data)
        ids = [row["id"] for row in response.data["results"]]
        # BM is assigned to self.building — both customers are in
        # that building — so the filter correctly narrows to
        # customer-A only.
        self.assertEqual(ids, [ew_a.id])

    def test_customer_user_out_of_scope_customer_returns_empty(self):
        # cust_user has access to self.customer ONLY. Asking the API
        # for the OTHER customer must return zero rows (the scope
        # helper removed them BEFORE the filter ran — no 403 leak).
        self._make_ew_for(self.customer, created_by=self.cust_user)
        self._make_ew_for(self.customer_other)
        response = self._api(self.cust_user).get(
            f"{URL}?customer={self.customer_other.id}"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["results"], [])

    def test_customer_user_own_customer_returns_own_rows(self):
        ew_own = self._make_ew_for(
            self.customer, created_by=self.cust_user
        )
        response = self._api(self.cust_user).get(
            f"{URL}?customer={self.customer.id}"
        )
        self.assertEqual(response.status_code, 200, response.data)
        ids = [row["id"] for row in response.data["results"]]
        self.assertIn(ew_own.id, ids)

    def test_invalid_customer_value_returns_400(self):
        # django-filter's NumberFilter rejects non-integer values
        # with HTTP 400. This pins that contract for the frontend.
        response = self._api(self.admin).get(f"{URL}?customer=abc")
        self.assertEqual(response.status_code, 400, response.data)
