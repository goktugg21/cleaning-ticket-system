"""
P0 staff-privacy regression tests (post-2026-05-20 audit, decision A4).

The 2026-05-20 business-logic audit found Sprint 29 Batch 29.8 had
widened `scope_extra_work_for(STAFF)` from `.none()` to "every EW
whose spawned ticket the staff can see," but every EW + Proposal
serializer still gated provider-only field stripping on
`_is_customer(user)`. Result: STAFF — now in scope — was served the
full provider payload (`internal_cost_note`, `manager_note`,
`override_*`, ProposalLine.internal_note, ProposalTimelineEvent
.metadata, plus DRAFT proposals).

Decision A4 was the stricter fix: STAFF must NEVER reach any
`/api/extra-work/` parent endpoint. Operational visibility lives on
the spawned Ticket via `Ticket.extra_work_origin` (id / title /
status / item id / service name only — no pricing, no notes, no
override info).

This file pins:

  1. STAFF gets 404 / empty on EVERY EW + Proposal read endpoint,
     even when a spawned ticket of the EW is in their scope.
  2. STAFF cannot write through EW + Proposal endpoints either.
  3. STAFF still sees its assigned operational Ticket and the
     `extra_work_origin` payload carries ONLY the safe metadata
     subset (no pricing / internal-note / override leak).
  4. Provider + customer flows are unchanged (smoke).

No migrations were added for the fix and no new permission keys
were introduced; this file deliberately avoids relying on either.
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
    ProposalTimelineEvent,
    ProposalTimelineEventType,
    Service,
    ServiceCategory,
)
from extra_work.scoping import scope_extra_work_for
from tickets.models import Ticket, TicketStaffAssignment, TicketStatus


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


# ---------------------------------------------------------------------------
# URL helpers — kept here so a future url-rename forces one edit, not many.
# ---------------------------------------------------------------------------
def _ew_list_url() -> str:
    return "/api/extra-work/"


def _ew_detail_url(ew_id: int) -> str:
    return f"/api/extra-work/{ew_id}/"


def _ew_transition_url(ew_id: int) -> str:
    return f"/api/extra-work/{ew_id}/transition/"


def _ew_status_history_url(ew_id: int) -> str:
    return f"/api/extra-work/{ew_id}/status-history/"


def _ew_spawn_url(ew_id: int) -> str:
    return f"/api/extra-work/{ew_id}/spawn/"


def _ew_pricing_list_url(ew_id: int) -> str:
    return f"/api/extra-work/{ew_id}/pricing-items/"


def _ew_pricing_detail_url(ew_id: int, lid: int) -> str:
    return f"/api/extra-work/{ew_id}/pricing-items/{lid}/"


def _proposals_list_url(ew_id: int) -> str:
    return f"/api/extra-work/{ew_id}/proposals/"


def _proposal_detail_url(ew_id: int, pid: int) -> str:
    return f"/api/extra-work/{ew_id}/proposals/{pid}/"


def _proposal_transition_url(ew_id: int, pid: int) -> str:
    return f"/api/extra-work/{ew_id}/proposals/{pid}/transition/"


def _proposal_status_history_url(ew_id: int, pid: int) -> str:
    return f"/api/extra-work/{ew_id}/proposals/{pid}/status-history/"


def _proposal_timeline_url(ew_id: int, pid: int) -> str:
    return f"/api/extra-work/{ew_id}/proposals/{pid}/timeline/"


def _proposal_lines_url(ew_id: int, pid: int) -> str:
    return f"/api/extra-work/{ew_id}/proposals/{pid}/lines/"


def _proposal_line_detail_url(ew_id: int, pid: int, lid: int) -> str:
    return f"/api/extra-work/{ew_id}/proposals/{pid}/lines/{lid}/"


def _proposal_pdf_url(ew_id: int, pid: int) -> str:
    return f"/api/extra-work/{ew_id}/proposals/{pid}/pdf/"


def _ticket_detail_url(ticket_id: int) -> str:
    return f"/api/tickets/{ticket_id}/"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


# ---------------------------------------------------------------------------
# Shared fixture — a single provider company, building, customer, EW with
# pricing line item, SENT proposal with one line, two spawned operational
# tickets (one per FK path so both legs are covered), assigned to STAFF.
# ---------------------------------------------------------------------------
class _StaffPrivacyFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        suffix = "p0"
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

        # Roles.
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
        cls.manager = _mk(
            f"mgr-{suffix}@example.com", UserRole.BUILDING_MANAGER
        )
        BuildingManagerAssignment.objects.create(
            user=cls.manager, building=cls.building
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
        CustomerUserBuildingAccess.objects.create(
            membership=membership, building=cls.building
        )

        # Catalog + service.
        cls.service_cat = ServiceCategory.objects.create(name=f"Cat {suffix}")
        cls.service = Service.objects.create(
            category=cls.service_cat,
            company=cls.company,
            name=f"Service {suffix}",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )

        # EW with both spawn paths populated.
        cls.ew = ExtraWorkRequest.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.cust_user,
            title=f"EW {suffix}",
            description="seed",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            routing_decision=ExtraWorkRoutingDecision.PROPOSAL,
            # Provider-internal text that must not leak.
            manager_note="MANAGER-ONLY",
            internal_cost_note="COST-ONLY",
            customer_visible_note="customer-side note",
        )
        cls.ew_pricing = ExtraWorkPricingLineItem.objects.create(
            extra_work=cls.ew,
            description="Pricing line",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            quantity=Decimal("1.00"),
            unit_price=Decimal("50.00"),
            vat_rate=Decimal("21.00"),
            customer_visible_note="visible to customer",
            internal_cost_note="LINE-COST-ONLY",
        )
        cls.line_a = ExtraWorkRequestItem.objects.create(
            extra_work_request=cls.ew,
            service=cls.service,
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=date(2026, 6, 1),
        )

        # SENT proposal + line + a provider-only timeline event.
        cls.proposal = Proposal.objects.create(
            extra_work_request=cls.ew,
            status=ProposalStatus.SENT,
            created_by=cls.admin,
            override_reason="",
        )
        cls.proposal_line = ProposalLine.objects.create(
            proposal=cls.proposal,
            service=cls.service,
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            unit_price=Decimal("50.00"),
            vat_pct=Decimal("21.00"),
            customer_explanation="visible explanation",
            internal_note="PROVIDER-ONLY LINE NOTE",
        )
        ProposalTimelineEvent.objects.create(
            proposal=cls.proposal,
            event_type=ProposalTimelineEventType.SENT,
            actor=cls.admin,
            customer_visible=True,
            metadata={"override_reason": "should-not-leak"},
        )

        # Spawned ticket via cart-item FK + STAFF assignment so the
        # ticket itself IS in scope_tickets_for(staff).
        cls.ticket_cart = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.admin,
            title="Cart Ticket",
            description="cart-spawn",
            status=TicketStatus.OPEN,
            extra_work_request_item=cls.line_a,
        )
        TicketStaffAssignment.objects.create(
            ticket=cls.ticket_cart, user=cls.staff
        )

        # Spawned ticket via proposal-line FK (the other spawn path)
        # so the regression test reaches both branches of
        # `extra_work_origin`.
        cls.ticket_proposal = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.admin,
            title="Proposal Ticket",
            description="proposal-spawn",
            status=TicketStatus.OPEN,
            proposal_line=cls.proposal_line,
        )
        TicketStaffAssignment.objects.create(
            ticket=cls.ticket_proposal, user=cls.staff
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c


# ---------------------------------------------------------------------------
# 1. STAFF cannot reach the parent ExtraWorkRequest at all.
# ---------------------------------------------------------------------------
class StaffCannotAccessExtraWorkParentTests(_StaffPrivacyFixture):
    def test_scope_returns_empty_even_with_spawned_ticket_in_scope(self):
        self.assertFalse(scope_extra_work_for(self.staff).exists())

    def test_list_returns_zero_results(self):
        response = self._api(self.staff).get(_ew_list_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # DRF default pagination is off here; both shapes are valid.
        body = response.data
        items = body.get("results", body) if isinstance(body, dict) else body
        self.assertEqual(len(items), 0)

    def test_detail_404(self):
        response = self._api(self.staff).get(_ew_detail_url(self.ew.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_status_history_404(self):
        response = self._api(self.staff).get(
            _ew_status_history_url(self.ew.id)
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_pricing_items_list_404(self):
        response = self._api(self.staff).get(
            _ew_pricing_list_url(self.ew.id)
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_pricing_items_detail_refused(self):
        # The pricing-item detail view exposes PATCH and DELETE only.
        # A staff-driven mutation must be refused before the verb is
        # even evaluated — 404 (out-of-scope EW gate) is the expected
        # response from the in-view `_resolve_extra_work_or_404`. We
        # exercise PATCH (the meaningful refusal path).
        response = self._api(self.staff).patch(
            _ew_pricing_detail_url(self.ew.id, self.ew_pricing.id),
            {"unit_price": "99.00"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_pricing_items_create_refused(self):
        # 404 (out of scope) is the strongest refusal; 403 (role gate)
        # is also acceptable. We assert "not 2xx".
        response = self._api(self.staff).post(
            _ew_pricing_list_url(self.ew.id),
            {
                "description": "x",
                "unit_type": ExtraWorkPricingUnitType.HOURS,
                "quantity": "1.00",
                "unit_price": "10.00",
                "vat_rate": "21.00",
            },
            format="json",
        )
        self.assertGreaterEqual(response.status_code, 400)

    def test_transition_refused(self):
        response = self._api(self.staff).post(
            _ew_transition_url(self.ew.id),
            {"to_status": ExtraWorkStatus.IN_PROGRESS},
            format="json",
        )
        self.assertGreaterEqual(response.status_code, 400)
        self.ew.refresh_from_db()
        self.assertEqual(self.ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)

    def test_spawn_endpoint_refused(self):
        # Even if STAFF guessed the EW id, the endpoint gates on the
        # SUPER_ADMIN / COMPANY_ADMIN role list BEFORE checking scope —
        # but the scope check would 404 first anyway. Either refusal
        # is fine; we assert "not 2xx".
        response = self._api(self.staff).post(_ew_spawn_url(self.ew.id))
        self.assertGreaterEqual(response.status_code, 400)


# ---------------------------------------------------------------------------
# 2. STAFF cannot reach any Proposal endpoint, in any verb.
# ---------------------------------------------------------------------------
class StaffCannotAccessProposalsTests(_StaffPrivacyFixture):
    def test_proposal_list_404(self):
        response = self._api(self.staff).get(_proposals_list_url(self.ew.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_proposal_detail_404(self):
        response = self._api(self.staff).get(
            _proposal_detail_url(self.ew.id, self.proposal.id)
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_proposal_transition_404(self):
        response = self._api(self.staff).post(
            _proposal_transition_url(self.ew.id, self.proposal.id),
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_proposal_status_history_404(self):
        response = self._api(self.staff).get(
            _proposal_status_history_url(self.ew.id, self.proposal.id)
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_proposal_timeline_404(self):
        response = self._api(self.staff).get(
            _proposal_timeline_url(self.ew.id, self.proposal.id)
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_proposal_lines_list_404(self):
        response = self._api(self.staff).get(
            _proposal_lines_url(self.ew.id, self.proposal.id)
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_proposal_line_detail_404(self):
        response = self._api(self.staff).patch(
            _proposal_line_detail_url(
                self.ew.id, self.proposal.id, self.proposal_line.id
            ),
            {"quantity": "5.00"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_proposal_pdf_404(self):
        response = self._api(self.staff).get(
            _proposal_pdf_url(self.ew.id, self.proposal.id)
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# 3. STAFF retains operational visibility through the spawned Ticket, AND
#    the `extra_work_origin` payload carries ONLY the safe metadata subset.
# ---------------------------------------------------------------------------
class StaffTicketExtraWorkOriginIsSafeTests(_StaffPrivacyFixture):
    # The full set of keys we are willing to expose on `extra_work_origin`.
    # Any key outside this set is treated as a leak — the assertion below
    # is intentionally strict.
    _ALLOWED_ORIGIN_KEYS = {
        "extra_work_request_id",
        "extra_work_request_title",
        "extra_work_request_status",
        "extra_work_request_item_id",
        "service_name",
        "origin",
    }

    # Substrings that, if they appear inside any string value of the
    # origin payload, indicate provider-internal text leaked through the
    # ticket detail. Pinned against the fixture's deliberate canaries.
    _FORBIDDEN_SUBSTRINGS = (
        "MANAGER-ONLY",
        "COST-ONLY",
        "LINE-COST-ONLY",
        "PROVIDER-ONLY LINE NOTE",
        "should-not-leak",
    )

    def _assert_origin_payload_safe(self, origin: dict) -> None:
        # Key whitelist — strict.
        self.assertEqual(
            set(origin.keys()),
            self._ALLOWED_ORIGIN_KEYS,
            f"extra_work_origin exposes unexpected keys: {set(origin.keys())}",
        )
        # No internal text in any value.
        for value in origin.values():
            if isinstance(value, str):
                for canary in self._FORBIDDEN_SUBSTRINGS:
                    self.assertNotIn(
                        canary,
                        value,
                        f"extra_work_origin string value leaked canary "
                        f"{canary!r}",
                    )

    def test_staff_sees_cart_spawned_ticket_and_origin_is_safe(self):
        response = self._api(self.staff).get(
            _ticket_detail_url(self.ticket_cart.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        origin = response.data.get("extra_work_origin")
        self.assertIsNotNone(origin)
        self.assertEqual(origin.get("origin"), "INSTANT")
        # The origin should reference the EW the staff cannot otherwise
        # reach, but only with safe metadata.
        self.assertEqual(origin.get("extra_work_request_id"), self.ew.id)
        self.assertEqual(origin.get("extra_work_request_title"), self.ew.title)
        self.assertEqual(
            origin.get("extra_work_request_status"),
            ExtraWorkStatus.CUSTOMER_APPROVED,
        )
        self._assert_origin_payload_safe(origin)

    def test_staff_sees_proposal_spawned_ticket_and_origin_is_safe(self):
        response = self._api(self.staff).get(
            _ticket_detail_url(self.ticket_proposal.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        origin = response.data.get("extra_work_origin")
        self.assertIsNotNone(origin)
        self.assertEqual(origin.get("origin"), "PROPOSAL")
        self.assertEqual(origin.get("extra_work_request_id"), self.ew.id)
        self.assertEqual(origin.get("service_name"), self.service.name)
        self._assert_origin_payload_safe(origin)

    def test_ticket_detail_does_not_carry_any_ew_internal_fields(self):
        # Tighter defence in depth: the TOP-LEVEL ticket detail must not
        # carry any EW provider-internal text either. The set below is
        # the union of keys the EW serializer strips for customers + the
        # proposal line internal_note key + the timeline metadata key.
        response = self._api(self.staff).get(
            _ticket_detail_url(self.ticket_proposal.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.data
        for forbidden_key in (
            "manager_note",
            "internal_cost_note",
            "override_by",
            "override_reason",
            "override_at",
            "internal_note",
            "metadata",
            "pricing_line_items",
        ):
            self.assertNotIn(
                forbidden_key,
                body,
                f"ticket detail leaked forbidden EW key {forbidden_key!r}",
            )


# ---------------------------------------------------------------------------
# 4. Provider + customer smoke — the fix must not regress legitimate access.
# ---------------------------------------------------------------------------
class ProviderAndCustomerStillWorkTests(_StaffPrivacyFixture):
    def test_company_admin_sees_full_ew_detail_including_internal(self):
        response = self._api(self.admin).get(_ew_detail_url(self.ew.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        # Provider sees the internal fields.
        self.assertEqual(response.data.get("manager_note"), "MANAGER-ONLY")
        self.assertEqual(
            response.data.get("internal_cost_note"), "COST-ONLY"
        )

    def test_company_admin_sees_proposal_line_internal_note(self):
        response = self._api(self.admin).get(
            _proposals_list_url(self.ew.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Provider sees the proposal in any status.
        ids = [row["id"] for row in response.data]
        self.assertIn(self.proposal.id, ids)
        # Walk to the line list.
        response = self._api(self.admin).get(
            _proposal_lines_url(self.ew.id, self.proposal.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            response.data[0].get("internal_note"),
            "PROVIDER-ONLY LINE NOTE",
        )

    def test_customer_user_sees_ew_detail_but_no_internal_fields(self):
        response = self._api(self.cust_user).get(_ew_detail_url(self.ew.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        # Customer-side stripping is unchanged by the P0 fix.
        self.assertNotIn("manager_note", response.data)
        self.assertNotIn("internal_cost_note", response.data)
        self.assertNotIn("override_by", response.data)
        self.assertNotIn("override_reason", response.data)

    def test_customer_user_sees_pricing_line_without_internal_cost_note(self):
        response = self._api(self.cust_user).get(
            _ew_pricing_list_url(self.ew.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertNotIn("internal_cost_note", response.data[0])
        # But customer-visible note is still surfaced.
        self.assertEqual(
            response.data[0].get("customer_visible_note"),
            "visible to customer",
        )

    def test_customer_user_proposal_line_strips_internal_note(self):
        response = self._api(self.cust_user).get(
            _proposal_lines_url(self.ew.id, self.proposal.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertNotIn("internal_note", response.data[0])
        self.assertEqual(
            response.data[0].get("customer_explanation"),
            "visible explanation",
        )
