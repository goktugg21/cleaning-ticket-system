"""
B2 — Extra Work cart-first proposal flow.

Pins the canonical §7.0 (system-business-logic-and-workflows.md):

  1. All-contract cart  -> INSTANT path. Proposal phase skipped;
     spawned tickets created at submission time.
  2. Mixed cart (any non-contract line) -> PROPOSAL path. Whole cart
     goes through the proposal builder.
  3. POST /api/extra-work/<id>/proposals/ with `lines=[]` or no
     `lines` key auto-seeds ProposalLine rows ONLY for AGREED-priced
     (contract) cart items, pre-filling `unit_price` + `vat_pct` from
     the resolver. Non-contract (custom / needs-proposal) cart items
     are SKIPPED — the operator adds them deliberately via the
     composer (2026-06-03 owner decision; auto-seeding a custom line
     at 0.00 forced a remove + re-add because saved lines are
     read-only in the UI). A mixed cart therefore seeds exactly the
     contract lines; an all-custom cart seeds ZERO lines (empty DRAFT
     proposal — the existing `proposal_lines_required` SEND gate
     blocks sending it).
  4. POST with explicit `lines` still works.
  5. SEND succeeds with explicit lines (any priced shape).
  6. SEND succeeds with FREE-FORM proposal lines that do NOT mirror
     the submitted cart 1:1 — extra lines, a changed unit_type, and
     contract-service lines priced differently from the contract.
     (Owner decision 2026-06-03: the cart-coverage + contract-price-
     floor SEND gate was REMOVED. The proposal is the provider's
     quote and need not mirror the cart.)
  7. Customer approval after a clean SEND spawns one operational
     ticket for the whole request, linked through Ticket.proposal_line.
  8. STAFF still cannot reach any EW or Proposal endpoint
     (cross-reference to test_staff_privacy_p0.py — re-asserted
     lightly here so a future scope refactor cannot quietly
     regress that on the B2 surface).

No migrations. No new permission keys. No frontend.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import StaffProfile, UserRole
from buildings.models import (
    Building,
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
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
    ExtraWorkStatus,
    Proposal,
    ProposalLine,
    ProposalStatus,
    Service,
    ServiceCategory,
)
from tickets.models import Ticket


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class _B2Fixture(TestCase):
    """Provider + customer + two services. One service (window
    cleaning) has an active CustomerServicePrice for this customer;
    the other service (grass cutting) does not — perfect for mixed-
    cart routing tests."""

    @classmethod
    def setUpTestData(cls):
        suffix = "b2"
        cls.company = Company.objects.create(
            name=f"Provider {suffix}", slug=f"prov-{suffix}"
        )
        cls.building = Building.objects.create(
            company=cls.company, name=f"Building {suffix}"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            name=f"Customer {suffix}",
            building=cls.building,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            f"super-{suffix}@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk(f"admin-{suffix}@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )
        cls.bm = _mk(f"bm-{suffix}@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.bm, building=cls.building
        )
        cls.staff = _mk(f"staff-{suffix}@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.building
        )
        cls.cust_user = _mk(
            f"cust-{suffix}@example.com", UserRole.CUSTOMER_USER
        )
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        cls.access = CustomerUserBuildingAccess.objects.create(
            membership=membership, building=cls.building
        )

        cls.service_cat = ServiceCategory.objects.create(name=f"Cat {suffix}")
        # Service A: contract-priced for this customer.
        cls.svc_window = Service.objects.create(
            category=cls.service_cat,
            company=cls.company,
            name=f"Window cleaning {suffix}",
            unit_type=ExtraWorkPricingUnitType.SQUARE_METERS,
            default_unit_price=Decimal("7.00"),
        )
        cls.svc_window_price = CustomerServicePrice.objects.create(
            service=cls.svc_window,
            customer=cls.customer,
            unit_price=Decimal("5.00"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            is_active=True,
        )
        # Service B: NOT contract-priced for this customer.
        cls.svc_grass = Service.objects.create(
            category=cls.service_cat,
            company=cls.company,
            name=f"Grass cutting {suffix}",
            unit_type=ExtraWorkPricingUnitType.SQUARE_METERS,
            default_unit_price=Decimal("2.00"),
        )
        # Service C: also contract-priced for this customer (used by
        # the all-contract multi-line routing test below; the
        # cart-create serializer rejects duplicate services per
        # submission, so a multi-line all-contract cart needs two
        # distinct contract-priced services).
        cls.svc_polish = Service.objects.create(
            category=cls.service_cat,
            company=cls.company,
            name=f"Floor polish {suffix}",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("60.00"),
        )
        cls.svc_polish_price = CustomerServicePrice.objects.create(
            service=cls.svc_polish,
            customer=cls.customer,
            unit_price=Decimal("45.00"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            is_active=True,
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _ew_create_url(self):
        return "/api/extra-work/"

    def _proposals_url(self, ew_id: int):
        return f"/api/extra-work/{ew_id}/proposals/"

    def _proposal_transition_url(self, ew_id: int, pid: int):
        return f"/api/extra-work/{ew_id}/proposals/{pid}/transition/"

    def _ew_detail_url(self, ew_id: int):
        return f"/api/extra-work/{ew_id}/"

    # Customer-side cart creation helper. The view runs the routing
    # serializer (computes INSTANT vs PROPOSAL) inside its own atomic
    # block, so each call returns a freshly-routed EW.
    def _submit_cart(self, line_specs: list[dict]) -> ExtraWorkRequest:
        payload = {
            "title": "B2 cart",
            "description": "B2 description",
            "building": self.building.id,
            "customer": self.customer.id,
            "category": ExtraWorkCategory.DEEP_CLEANING,
            "line_items": line_specs,
        }
        response = self._api(self.cust_user).post(
            self._ew_create_url(), payload, format="json"
        )
        if response.status_code != status.HTTP_201_CREATED:
            raise AssertionError(
                f"cart create failed: {response.status_code} {response.data}"
            )
        return ExtraWorkRequest.objects.get(pk=response.data["id"])

    def _move_ew_to_under_review(self, ew: ExtraWorkRequest) -> None:
        ew.status = ExtraWorkStatus.UNDER_REVIEW
        ew.save(update_fields=["status"])


# ---------------------------------------------------------------------------
# 1. Routing — all-contract cart -> INSTANT.
# ---------------------------------------------------------------------------
class RoutingAllContractTests(_B2Fixture):
    def test_all_contract_cart_routes_to_instant(self):
        # Two distinct contract-priced services so the cart-create
        # `no-duplicate-service` rule does not fire.
        ew = self._submit_cart(
            [
                {
                    "service": self.svc_window.id,
                    "quantity": "50",
                    "requested_date": "2026-06-01",
                },
                {
                    "service": self.svc_polish.id,
                    "quantity": "3",
                    "requested_date": "2026-06-01",
                },
            ]
        )
        self.assertEqual(ew.routing_decision, ExtraWorkRoutingDecision.INSTANT)
        self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)
        # Sprint 6A — exactly ONE ticket spawned for the whole request.
        ticket_count = Ticket.objects.filter(extra_work_request=ew).count()
        self.assertEqual(ticket_count, 1)


# ---------------------------------------------------------------------------
# 2. Routing — mixed cart -> PROPOSAL.
# ---------------------------------------------------------------------------
class RoutingMixedCartTests(_B2Fixture):
    def test_mixed_cart_routes_to_proposal(self):
        ew = self._submit_cart(
            [
                # Contract-priced line.
                {
                    "service": self.svc_window.id,
                    "quantity": "50",
                    "requested_date": "2026-06-01",
                },
                # Non-contract line (no CustomerServicePrice for this
                # customer / svc_grass pair).
                {
                    "service": self.svc_grass.id,
                    "quantity": "100",
                    "requested_date": "2026-06-01",
                },
            ]
        )
        self.assertEqual(ew.routing_decision, ExtraWorkRoutingDecision.PROPOSAL)
        # Routed to proposal -> EW stays REQUESTED (no auto-approve, no
        # instant spawn).
        self.assertEqual(ew.status, ExtraWorkStatus.REQUESTED)
        self.assertFalse(
            Ticket.objects.filter(
                extra_work_request_item__extra_work_request=ew
            ).exists()
        )


# ---------------------------------------------------------------------------
# 3. Auto-seed: POST proposal with omitted lines seeds ONLY the
#    AGREED-priced (contract) cart lines. Non-contract lines are
#    SKIPPED (2026-06-03 owner decision) — the operator adds them via
#    the composer.
# ---------------------------------------------------------------------------
class ProposalAutoSeedTests(_B2Fixture):
    def _build_mixed_cart(self) -> ExtraWorkRequest:
        ew = self._submit_cart(
            [
                {
                    "service": self.svc_window.id,
                    "quantity": "50",
                    "requested_date": "2026-06-01",
                },
                {
                    "service": self.svc_grass.id,
                    "quantity": "100",
                    "requested_date": "2026-06-01",
                },
            ]
        )
        self._move_ew_to_under_review(ew)
        return ew

    def _build_all_custom_cart(self) -> ExtraWorkRequest:
        # Single no-contract service -> routes to PROPOSAL with an
        # all-custom cart.
        ew = self._submit_cart(
            [
                {
                    "service": self.svc_grass.id,
                    "quantity": "100",
                    "requested_date": "2026-06-01",
                },
            ]
        )
        self._move_ew_to_under_review(ew)
        return ew

    def test_omitted_lines_payload_auto_seeds_only_contract_lines(self):
        ew = self._build_mixed_cart()
        response = self._api(self.admin).post(
            self._proposals_url(ew.id),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        proposal_id = response.data["id"]
        seeded = list(
            ProposalLine.objects.filter(proposal_id=proposal_id).order_by(
                "id"
            )
        )
        # Only the AGREED-priced (window) cart line is auto-seeded; the
        # non-contract (grass) cart line is skipped.
        self.assertEqual(len(seeded), 1)
        window_line = seeded[0]
        self.assertEqual(window_line.service_id, self.svc_window.id)
        # Contract-priced line auto-filled from CustomerServicePrice.
        self.assertEqual(window_line.unit_price, Decimal("5.00"))
        self.assertEqual(window_line.vat_pct, Decimal("21.00"))
        # customer_explanation must NOT be used as a metadata marker.
        self.assertEqual(window_line.customer_explanation, "")
        # The non-contract grass line was NOT auto-seeded.
        self.assertFalse(
            ProposalLine.objects.filter(
                proposal_id=proposal_id, service_id=self.svc_grass.id
            ).exists()
        )

    def test_empty_lines_array_also_auto_seeds_only_contract_lines(self):
        ew = self._build_mixed_cart()
        response = self._api(self.admin).post(
            self._proposals_url(ew.id),
            {"lines": []},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        seeded = ProposalLine.objects.filter(
            proposal_id=response.data["id"]
        )
        self.assertEqual(seeded.count(), 1)
        self.assertEqual(seeded.get().service_id, self.svc_window.id)

    def test_all_custom_cart_auto_seeds_zero_lines(self):
        # An all-custom cart yields an empty DRAFT proposal — no
        # ProposalLine is seeded. The existing SEND gate
        # (`proposal_lines_required`) blocks sending it; auto-seed adds
        # no new gate of its own.
        ew = self._build_all_custom_cart()
        response = self._api(self.admin).post(
            self._proposals_url(ew.id),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            ProposalLine.objects.filter(
                proposal_id=response.data["id"]
            ).count(),
            0,
        )


# ---------------------------------------------------------------------------
# 4. Explicit lines that cover the cart still work.
# ---------------------------------------------------------------------------
class ProposalExplicitLinesCoveringCartTests(_B2Fixture):
    def test_explicit_lines_pass_send_when_they_cover_cart(self):
        ew = self._submit_cart(
            [
                {
                    "service": self.svc_window.id,
                    "quantity": "50",
                    "requested_date": "2026-06-01",
                },
                {
                    "service": self.svc_grass.id,
                    "quantity": "100",
                    "requested_date": "2026-06-01",
                },
            ]
        )
        self._move_ew_to_under_review(ew)
        # Operator explicitly specifies both lines, with the contract
        # price matched on the window line.
        response = self._api(self.admin).post(
            self._proposals_url(ew.id),
            {
                "lines": [
                    {
                        "service": self.svc_window.id,
                        "quantity": "50",
                        "unit_type": ExtraWorkPricingUnitType.SQUARE_METERS,
                        "unit_price": "5.00",
                        "vat_pct": "21.00",
                    },
                    {
                        "service": self.svc_grass.id,
                        "quantity": "100",
                        "unit_type": ExtraWorkPricingUnitType.SQUARE_METERS,
                        "unit_price": "2.50",
                        "vat_pct": "21.00",
                    },
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        proposal_id = response.data["id"]
        # SEND must succeed.
        response = self._api(self.admin).post(
            self._proposal_transition_url(ew.id, proposal_id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)


# ---------------------------------------------------------------------------
# 5. Free-form proposal lines — SEND no longer requires the proposal to
#    mirror the submitted cart.
#
# Owner decision (2026-06-03): the cart-coverage + contract-price-floor
# SEND gate (`_validate_proposal_covers_cart`, codes
# proposal_has_extra_line / proposal_does_not_cover_cart /
# proposal_contract_price_drift / proposal_custom_line_missing_price)
# was REMOVED. A single Extra Work event may legitimately need multiple
# custom-priced lines and fees that do NOT mirror the cart 1:1. The
# proposal is the provider's quote and need not match the cart.
# ---------------------------------------------------------------------------
class ProposalFreeFormLinesSendTests(_B2Fixture):
    def test_free_form_proposal_lines_pass_send(self):
        # Mixed cart routes to PROPOSAL. The cart has TWO lines
        # (window 50 m², grass 100 m²) but the provider composes a
        # quote that does NOT mirror it:
        #   * window cleaning is RE-priced away from the EUR 5.00
        #     contract (no contract-price-floor anymore),
        #   * with a CHANGED unit_type (FIXED instead of SQUARE_METERS),
        #   * the grass cart line is DROPPED entirely,
        #   * a brand-new travel-fee line the customer never put in the
        #     cart is ADDED (would previously trip
        #     `proposal_has_extra_line`).
        ew = self._submit_cart(
            [
                {
                    "service": self.svc_window.id,
                    "quantity": "50",
                    "requested_date": "2026-06-01",
                },
                {
                    "service": self.svc_grass.id,
                    "quantity": "100",
                    "requested_date": "2026-06-01",
                },
            ]
        )
        self.assertEqual(
            ew.routing_decision, ExtraWorkRoutingDecision.PROPOSAL
        )
        self._move_ew_to_under_review(ew)
        response = self._api(self.admin).post(
            self._proposals_url(ew.id),
            {
                "lines": [
                    # Contract service, re-priced + unit_type changed.
                    {
                        "service": self.svc_window.id,
                        "quantity": "1",
                        "unit_type": ExtraWorkPricingUnitType.FIXED,
                        "unit_price": "300.00",
                        "vat_pct": "21.00",
                        "customer_explanation": "Fixed package price.",
                    },
                    # Free-form travel fee with no cart counterpart and
                    # no service FK.
                    {
                        "description": "Travel and material surcharge",
                        "quantity": "1",
                        "unit_type": ExtraWorkPricingUnitType.FIXED,
                        "unit_price": "45.00",
                        "vat_pct": "21.00",
                        "customer_explanation": "One-off surcharge.",
                    },
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        proposal_id = response.data["id"]
        # SEND succeeds: the cart-coverage / contract-price-floor gate
        # is gone, so a free-form quote is accepted.
        response = self._api(self.admin).post(
            self._proposal_transition_url(ew.id, proposal_id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        proposal = Proposal.objects.get(pk=proposal_id)
        self.assertEqual(proposal.status, ProposalStatus.SENT)
        # Parent EW advanced to PRICING_PROPOSED on SEND.
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.PRICING_PROPOSED)


# ---------------------------------------------------------------------------
# 6. Post-approval spawn — customer approval spawns one ticket.
# ---------------------------------------------------------------------------
class ProposalApprovalSpawnTests(_B2Fixture):
    def test_customer_approval_spawns_one_ticket_per_request(self):
        ew = self._submit_cart(
            [
                {
                    "service": self.svc_window.id,
                    "quantity": "50",
                    "requested_date": "2026-06-01",
                },
                {
                    "service": self.svc_grass.id,
                    "quantity": "100",
                    "requested_date": "2026-06-01",
                },
            ]
        )
        self._move_ew_to_under_review(ew)
        # Auto-seed from cart (seeds ONLY the contract window line);
        # the operator then ADDS the non-contract grass line via the
        # composer (2026-06-03 owner decision: custom lines are not
        # auto-seeded).
        response = self._api(self.admin).post(
            self._proposals_url(ew.id), {}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        proposal_id = response.data["id"]
        # The non-contract grass line was not auto-seeded — add it.
        add = self._api(self.admin).post(
            f"{self._proposals_url(ew.id)}{proposal_id}/lines/",
            {
                "service": self.svc_grass.id,
                "quantity": "100",
                "unit_type": ExtraWorkPricingUnitType.SQUARE_METERS,
                "unit_price": "2.50",
                "vat_pct": "21.00",
            },
            format="json",
        )
        self.assertEqual(add.status_code, 201, add.data)
        # SEND.
        response = self._api(self.admin).post(
            self._proposal_transition_url(ew.id, proposal_id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        # Customer approves.
        before = Ticket.objects.count()
        response = self._api(self.cust_user).post(
            self._proposal_transition_url(ew.id, proposal_id),
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        # Sprint 6A — exactly ONE ticket for the whole request.
        self.assertEqual(Ticket.objects.count(), before + 1)
        ticket = Ticket.objects.get(extra_work_request=ew)
        # Back-compat link is the FIRST approved-for-spawn proposal line.
        proposal = Proposal.objects.get(pk=proposal_id)
        first_line = proposal.lines.order_by("id").first()
        self.assertEqual(ticket.proposal_line_id, first_line.id)


# ---------------------------------------------------------------------------
# 7. STAFF still cannot reach proposal endpoints (B2 surface re-pin).
# ---------------------------------------------------------------------------
class StaffStillBlockedFromProposalsTests(_B2Fixture):
    def test_staff_cannot_reach_proposal_list(self):
        ew = self._submit_cart(
            [
                {
                    "service": self.svc_grass.id,
                    "quantity": "100",
                    "requested_date": "2026-06-01",
                },
            ]
        )
        self._move_ew_to_under_review(ew)
        response = self._api(self.staff).get(self._proposals_url(ew.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
