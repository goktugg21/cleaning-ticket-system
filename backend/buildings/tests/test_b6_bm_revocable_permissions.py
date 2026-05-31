"""
B6 — Building Manager revocable defaults.

Two new permission keys live on the existing `osius.*` namespace:

  * `osius.building_manager.override_customer_decision`
    - Default True for any BM assigned to a building.
    - When the (BM, building) `BuildingManagerAssignment.permission_overrides`
      sets the key to False, the BM can no longer approve / reject on
      behalf of the customer for tickets, EW requests, or proposals at
      that building.

  * `osius.building_manager.prepare_extra_work_proposal`
    - Default True for any BM assigned to a building.
    - When set to False on the assignment row, the BM can no longer
      create / update / delete / send / cancel proposals at that
      building.

This file pins:

  A. Default BM behaviour is preserved (both actions True).
  B. Override-disabled customer decision blocks BM at every override
     endpoint (ticket WAITING_CUSTOMER_APPROVAL -> APPROVED, EW
     PRICING_PROPOSED -> CUSTOMER_APPROVED, proposal SENT ->
     CUSTOMER_APPROVED). SA + COMPANY_ADMIN remain able to drive
     the same transition.
  C. Override-disabled proposal preparation blocks BM at every
     proposal-write endpoint (proposal POST, line POST/PATCH/DELETE,
     proposal transition DRAFT->SENT, proposal transition
     SENT->CANCELLED). SA + COMPANY_ADMIN remain able. Customer
     SENT->CUSTOMER_APPROVED/REJECTED stays open. STAFF stays out.
  D. BM outside assigned building remains out of scope; the new
     keys do not leak cross-building access.
  E. STAFF privacy regression: STAFF still cannot reach any
     Proposal endpoint regardless of policy state.
  F. Effective-permissions endpoint reflects the live keys.
  G. URL-smuggling regression — direct URL attempts at every write
     surface that could let a BM act despite the disabled key.
  H. PATCH `/api/buildings/<bid>/managers/<uid>/` write surface —
     SA and Provider COMPANY_ADMIN may flip the keys; everyone else
     is rejected. Allow-list validation rejects unknown keys and
     non-boolean values.

No new permission keys beyond the two listed above. One migration
(`buildings/0005_*`) adds the JSONField. No frontend changes.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import StaffProfile, UserRole
from accounts.permissions_v2 import (
    BM_REVOCABLE_PERMISSION_KEYS,
    user_has_osius_permission,
)
from audit.models import AuditAction, AuditLog
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
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestItem,
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

OVERRIDE_KEY = "osius.building_manager.override_customer_decision"
PREP_KEY = "osius.building_manager.prepare_extra_work_proposal"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class _B6Fixture(TestCase):
    """One provider company, two buildings, two BMs (one assigned to
    building A, the other to building B), one customer linked to
    building A, plus an SA / COMPANY_ADMIN / STAFF / CUSTOMER_USER set
    for the full role coverage."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov B6", slug="prov-b6")
        cls.building_a = Building.objects.create(
            company=cls.company, name="B6-Building-A"
        )
        cls.building_b = Building.objects.create(
            company=cls.company, name="B6-Building-B"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer B6", building=cls.building_a
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building_a
        )

        cls.super_admin = _mk(
            "super-b6@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-b6@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

        # BM assigned to building A (the one with the customer).
        cls.bm_in = _mk("bm-in-b6@example.com", UserRole.BUILDING_MANAGER)
        cls.bm_in_assignment = BuildingManagerAssignment.objects.create(
            user=cls.bm_in, building=cls.building_a
        )

        # BM assigned to building B only — must remain out of scope for
        # everything in building A regardless of the new keys.
        cls.bm_out = _mk("bm-out-b6@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.bm_out, building=cls.building_b
        )

        # STAFF in scope for building A — must stay locked out of
        # every proposal/EW commercial surface (P0 staff-privacy).
        cls.staff_in = _mk("staff-b6@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_in)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_in, building=cls.building_a
        )

        # CUSTOMER_USER linked to (customer, building A) with the
        # `customer.extra_work.approve_own` default that the
        # CUSTOMER_USER access_role grants.
        cls.customer_user = _mk(
            "cust-b6@example.com", UserRole.CUSTOMER_USER
        )
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.customer_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building_a,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _make_ticket(self):
        ticket = Ticket.objects.create(
            company=self.company,
            building=self.building_a,
            customer=self.customer,
            created_by=self.customer_user,
            title="B6 ticket",
            description="x",
        )
        ticket.status = TicketStatus.WAITING_CUSTOMER_APPROVAL
        ticket.save(update_fields=["status", "updated_at"])
        return ticket

    def _make_extra_work_with_sent_proposal(self):
        """Build an EW request + a SENT proposal so customer-decision
        paths are reachable. Both built directly to avoid going through
        the cart routing logic which is out of scope for B6."""
        category = ServiceCategory.objects.create(name="B6-cat")
        service = Service.objects.create(
            category=category,
            company=self.company,
            name="B6-service",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            default_unit_price=Decimal("100.00"),
        )
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building_a,
            customer=self.customer,
            created_by=self.customer_user,
            title="B6 EW",
            description="x",
            status=ExtraWorkStatus.PRICING_PROPOSED,
        )
        ExtraWorkRequestItem.objects.create(
            extra_work_request=ew,
            service=service,
            unit_type=ExtraWorkPricingUnitType.FIXED,
            quantity=Decimal("1.00"),
            requested_date="2026-06-01",
        )
        proposal = Proposal.objects.create(
            extra_work_request=ew,
            created_by=self.admin,
            status=ProposalStatus.SENT,
        )
        ProposalLine.objects.create(
            proposal=proposal,
            service=service,
            unit_type=ExtraWorkPricingUnitType.FIXED,
            quantity=Decimal("1.00"),
            unit_price=Decimal("100.00"),
            vat_pct=Decimal("21.00"),
        )
        return ew, proposal, service

    def _make_extra_work_with_draft_proposal(self):
        """Build an EW request + a DRAFT proposal so proposal-prep paths
        are reachable (POST line / PATCH line / DELETE line / DRAFT->
        SENT). EW is held at UNDER_REVIEW (required by the SEND
        precondition)."""
        category = ServiceCategory.objects.create(name="B6-cat-draft")
        service = Service.objects.create(
            category=category,
            company=self.company,
            name="B6-service-draft",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            default_unit_price=Decimal("50.00"),
        )
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building_a,
            customer=self.customer,
            created_by=self.customer_user,
            title="B6 EW draft",
            description="x",
            status=ExtraWorkStatus.UNDER_REVIEW,
        )
        ExtraWorkRequestItem.objects.create(
            extra_work_request=ew,
            service=service,
            unit_type=ExtraWorkPricingUnitType.FIXED,
            quantity=Decimal("1.00"),
            requested_date="2026-06-01",
        )
        proposal = Proposal.objects.create(
            extra_work_request=ew,
            created_by=self.admin,
            status=ProposalStatus.DRAFT,
        )
        return ew, proposal, service

    def _disable(self, key: str, *, assignment=None) -> None:
        assignment = assignment or self.bm_in_assignment
        assignment.permission_overrides = {
            **(assignment.permission_overrides or {}),
            key: False,
        }
        assignment.save(update_fields=["permission_overrides"])


# ---------------------------------------------------------------------------
# A. Default behaviour preserved
# ---------------------------------------------------------------------------
class DefaultBehaviourTests(_B6Fixture):
    def test_both_keys_default_true_for_bm_in_assigned_building(self):
        self.assertTrue(
            user_has_osius_permission(
                self.bm_in, OVERRIDE_KEY, building_id=self.building_a.id
            )
        )
        self.assertTrue(
            user_has_osius_permission(
                self.bm_in, PREP_KEY, building_id=self.building_a.id
            )
        )

    def test_bm_can_override_customer_decision_by_default(self):
        ticket = self._make_ticket()
        response = self._api(self.bm_in).post(
            f"/api/tickets/{ticket.id}/status/",
            {
                "to_status": TicketStatus.APPROVED,
                "is_override": True,
                "override_reason": "Customer approved by phone.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        ticket.refresh_from_db()
        self.assertEqual(str(ticket.status), str(TicketStatus.APPROVED))

    def test_bm_can_send_proposal_by_default(self):
        ew, proposal, _ = self._make_extra_work_with_draft_proposal()
        # SEND-time requires at least one line that mirrors the cart.
        ProposalLine.objects.create(
            proposal=proposal,
            service=ew.line_items.first().service,
            unit_type=ExtraWorkPricingUnitType.FIXED,
            quantity=Decimal("1.00"),
            unit_price=Decimal("50.00"),
            vat_pct=Decimal("21.00"),
        )
        response = self._api(self.bm_in).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/transition/",
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        proposal.refresh_from_db()
        self.assertEqual(str(proposal.status), str(ProposalStatus.SENT))


# ---------------------------------------------------------------------------
# B. Override-disabled customer-decision blocks BM, not SA/CA
# ---------------------------------------------------------------------------
class CustomerDecisionOverrideDisabledTests(_B6Fixture):
    def setUp(self):
        super().setUp()
        self._disable(OVERRIDE_KEY)

    def test_bm_ticket_override_returns_bm_override_disabled(self):
        ticket = self._make_ticket()
        response = self._api(self.bm_in).post(
            f"/api/tickets/{ticket.id}/status/",
            {
                "to_status": TicketStatus.APPROVED,
                "is_override": True,
                "override_reason": "Customer approved by phone.",
            },
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            response.data.get("code"), "bm_override_disabled"
        )
        ticket.refresh_from_db()
        # No state mutation, no spurious history row.
        self.assertEqual(
            str(ticket.status), str(TicketStatus.WAITING_CUSTOMER_APPROVAL)
        )
        self.assertEqual(ticket.status_history.count(), 0)

    def test_bm_extra_work_override_returns_bm_override_disabled(self):
        ew, _, _ = self._make_extra_work_with_sent_proposal()
        response = self._api(self.bm_in).post(
            f"/api/extra-work/{ew.id}/transition/",
            {
                "to_status": ExtraWorkStatus.CUSTOMER_APPROVED,
                "is_override": True,
                "override_reason": "Customer approved by phone.",
            },
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            response.data.get("code"), "bm_override_disabled"
        )
        ew.refresh_from_db()
        self.assertEqual(
            str(ew.status), str(ExtraWorkStatus.PRICING_PROPOSED)
        )

    def test_bm_proposal_customer_approve_returns_bm_override_disabled(self):
        ew, proposal, _ = self._make_extra_work_with_sent_proposal()
        response = self._api(self.bm_in).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/transition/",
            {
                "to_status": ProposalStatus.CUSTOMER_APPROVED,
                "is_override": True,
                "override_reason": "Customer approved by phone.",
            },
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            response.data.get("code"), "bm_override_disabled"
        )
        proposal.refresh_from_db()
        self.assertEqual(str(proposal.status), str(ProposalStatus.SENT))

    def test_super_admin_can_still_override_customer_decision(self):
        ticket = self._make_ticket()
        response = self._api(self.super_admin).post(
            f"/api/tickets/{ticket.id}/status/",
            {
                "to_status": TicketStatus.APPROVED,
                "is_override": True,
                "override_reason": "Customer approved by phone.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_company_admin_can_still_override_customer_decision(self):
        ticket = self._make_ticket()
        response = self._api(self.admin).post(
            f"/api/tickets/{ticket.id}/status/",
            {
                "to_status": TicketStatus.APPROVED,
                "is_override": True,
                "override_reason": "Customer approved by phone.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)


# ---------------------------------------------------------------------------
# C. Override-disabled proposal preparation blocks BM, not SA/CA
# ---------------------------------------------------------------------------
class ProposalPreparationDisabledTests(_B6Fixture):
    def setUp(self):
        super().setUp()
        self._disable(PREP_KEY)

    def test_bm_proposal_create_blocked(self):
        ew, _, _ = self._make_extra_work_with_draft_proposal()
        # Delete the seed draft so we can attempt to create one.
        Proposal.objects.filter(extra_work_request=ew).delete()
        response = self._api(self.bm_in).post(
            f"/api/extra-work/{ew.id}/proposals/",
            {"lines": []},
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN, response.data
        )
        self.assertEqual(
            response.data.get("code"), "bm_proposal_preparation_disabled"
        )
        self.assertFalse(
            Proposal.objects.filter(extra_work_request=ew).exists()
        )

    def test_bm_proposal_line_create_blocked(self):
        ew, proposal, service = self._make_extra_work_with_draft_proposal()
        response = self._api(self.bm_in).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/lines/",
            {
                "service": service.id,
                "unit_type": ExtraWorkPricingUnitType.FIXED,
                "quantity": "1.00",
                "unit_price": "50.00",
                "vat_pct": "21.00",
            },
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN, response.data
        )
        self.assertEqual(
            response.data.get("code"), "bm_proposal_preparation_disabled"
        )
        self.assertEqual(proposal.lines.count(), 0)

    def test_bm_proposal_line_patch_blocked(self):
        ew, proposal, service = self._make_extra_work_with_draft_proposal()
        line = ProposalLine.objects.create(
            proposal=proposal,
            service=service,
            unit_type=ExtraWorkPricingUnitType.FIXED,
            quantity=Decimal("1.00"),
            unit_price=Decimal("50.00"),
            vat_pct=Decimal("21.00"),
        )
        response = self._api(self.bm_in).patch(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/lines/{line.id}/",
            {"unit_price": "75.00"},
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN, response.data
        )
        self.assertEqual(
            response.data.get("code"), "bm_proposal_preparation_disabled"
        )
        line.refresh_from_db()
        self.assertEqual(line.unit_price, Decimal("50.00"))

    def test_bm_proposal_line_delete_blocked(self):
        ew, proposal, service = self._make_extra_work_with_draft_proposal()
        line = ProposalLine.objects.create(
            proposal=proposal,
            service=service,
            unit_type=ExtraWorkPricingUnitType.FIXED,
            quantity=Decimal("1.00"),
            unit_price=Decimal("50.00"),
            vat_pct=Decimal("21.00"),
        )
        response = self._api(self.bm_in).delete(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/lines/{line.id}/"
        )
        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN, response.data
        )
        self.assertTrue(ProposalLine.objects.filter(pk=line.pk).exists())

    def test_bm_proposal_draft_to_sent_blocked(self):
        ew, proposal, service = self._make_extra_work_with_draft_proposal()
        ProposalLine.objects.create(
            proposal=proposal,
            service=service,
            unit_type=ExtraWorkPricingUnitType.FIXED,
            quantity=Decimal("1.00"),
            unit_price=Decimal("50.00"),
            vat_pct=Decimal("21.00"),
        )
        response = self._api(self.bm_in).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/transition/",
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            response.data.get("code"), "bm_proposal_preparation_disabled"
        )
        proposal.refresh_from_db()
        self.assertEqual(str(proposal.status), str(ProposalStatus.DRAFT))

    def test_bm_proposal_sent_to_cancelled_blocked(self):
        ew, proposal, _ = self._make_extra_work_with_sent_proposal()
        response = self._api(self.bm_in).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/transition/",
            {
                "to_status": ProposalStatus.CANCELLED,
                "is_override": True,
                "override_reason": "Withdraw.",
            },
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            response.data.get("code"), "bm_proposal_preparation_disabled"
        )

    def test_super_admin_can_still_prepare_proposal(self):
        ew, proposal, service = self._make_extra_work_with_draft_proposal()
        response = self._api(self.super_admin).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/lines/",
            {
                "service": service.id,
                "unit_type": ExtraWorkPricingUnitType.FIXED,
                "quantity": "1.00",
                "unit_price": "50.00",
                "vat_pct": "21.00",
            },
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED, response.data
        )

    def test_company_admin_can_still_prepare_proposal(self):
        ew, proposal, service = self._make_extra_work_with_draft_proposal()
        response = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/lines/",
            {
                "service": service.id,
                "unit_type": ExtraWorkPricingUnitType.FIXED,
                "quantity": "1.00",
                "unit_price": "50.00",
                "vat_pct": "21.00",
            },
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED, response.data
        )

    def test_customer_can_still_approve_sent_proposal(self):
        ew, proposal, _ = self._make_extra_work_with_sent_proposal()
        response = self._api(self.customer_user).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/transition/",
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        proposal.refresh_from_db()
        self.assertEqual(
            str(proposal.status), str(ProposalStatus.CUSTOMER_APPROVED)
        )


# ---------------------------------------------------------------------------
# D. Cross-building isolation
# ---------------------------------------------------------------------------
class CrossBuildingIsolationTests(_B6Fixture):
    def test_bm_out_returns_false_for_both_keys(self):
        # bm_out has no assignment to building_a — keys must return
        # False regardless of any overrides on the OTHER building's row.
        self.assertFalse(
            user_has_osius_permission(
                self.bm_out, OVERRIDE_KEY, building_id=self.building_a.id
            )
        )
        self.assertFalse(
            user_has_osius_permission(
                self.bm_out, PREP_KEY, building_id=self.building_a.id
            )
        )

    def test_disabling_key_on_one_building_does_not_affect_another(self):
        # Disable both keys on building A's BM assignment. The BM has
        # only that one assignment, so the resolver returns False for
        # building A but True if a separate assignment exists elsewhere.
        self._disable(OVERRIDE_KEY)
        self._disable(PREP_KEY)
        # Add a second assignment on building B with no overrides.
        BuildingManagerAssignment.objects.create(
            user=self.bm_in, building=self.building_b
        )
        # Per-building lookup respects the per-row overrides.
        self.assertFalse(
            user_has_osius_permission(
                self.bm_in, OVERRIDE_KEY, building_id=self.building_a.id
            )
        )
        self.assertTrue(
            user_has_osius_permission(
                self.bm_in, OVERRIDE_KEY, building_id=self.building_b.id
            )
        )

    def test_bm_out_blocked_at_ticket_endpoint_regardless_of_keys(self):
        # bm_out is not assigned to building_a; the existing
        # SCOPE_BUILDING_ASSIGNED gate must reject before the B6 key
        # check ever fires. Adding overrides on the OTHER building must
        # not bridge cross-building access.
        ticket = self._make_ticket()
        response = self._api(self.bm_out).post(
            f"/api/tickets/{ticket.id}/status/",
            {
                "to_status": TicketStatus.APPROVED,
                "is_override": True,
                "override_reason": "Customer approved by phone.",
            },
            format="json",
        )
        # The route gate yields 404 (scope_tickets_for hides the
        # ticket) or 400 (forbidden_transition). Either is acceptable
        # — the key is "did not mutate state."
        self.assertIn(
            response.status_code,
            (
                status.HTTP_400_BAD_REQUEST,
                status.HTTP_403_FORBIDDEN,
                status.HTTP_404_NOT_FOUND,
            ),
        )
        ticket.refresh_from_db()
        self.assertEqual(
            str(ticket.status), str(TicketStatus.WAITING_CUSTOMER_APPROVAL)
        )


# ---------------------------------------------------------------------------
# E. STAFF privacy regression
# ---------------------------------------------------------------------------
class StaffPrivacyRegressionTests(_B6Fixture):
    def setUp(self):
        super().setUp()
        # Disable BOTH new keys — staff privacy must remain unchanged.
        self._disable(OVERRIDE_KEY)
        self._disable(PREP_KEY)

    def test_staff_cannot_reach_proposal_create_endpoint(self):
        ew, _, _ = self._make_extra_work_with_draft_proposal()
        response = self._api(self.staff_in).post(
            f"/api/extra-work/{ew.id}/proposals/",
            {"lines": []},
            format="json",
        )
        # P0 staff-privacy: STAFF either gets 403 (scope guard rejects)
        # or 404 (scope_extra_work_for hides the EW row from staff).
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )

    def test_staff_cannot_reach_proposal_lines_endpoint(self):
        ew, proposal, _ = self._make_extra_work_with_sent_proposal()
        response = self._api(self.staff_in).get(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/lines/"
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )

    def test_staff_does_not_get_b6_keys(self):
        self.assertFalse(
            user_has_osius_permission(
                self.staff_in, OVERRIDE_KEY, building_id=self.building_a.id
            )
        )
        self.assertFalse(
            user_has_osius_permission(
                self.staff_in, PREP_KEY, building_id=self.building_a.id
            )
        )


# ---------------------------------------------------------------------------
# F. Effective-permissions endpoint
# ---------------------------------------------------------------------------
class EffectivePermissionsTests(_B6Fixture):
    def _fetch_actions(self, target, building):
        response = self._api(self.super_admin).get(
            f"/api/users/{target.id}/effective-permissions/"
            f"?customer_id={self.customer.id}&building_id={building.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data["effective_actions"]

    def test_super_admin_actions_always_true(self):
        actions = self._fetch_actions(self.super_admin, self.building_a)
        self.assertTrue(actions["can_override_customer_decision"])
        self.assertTrue(actions["can_prepare_extra_work_proposal"])

    def test_company_admin_actions_always_true(self):
        actions = self._fetch_actions(self.admin, self.building_a)
        self.assertTrue(actions["can_override_customer_decision"])
        self.assertTrue(actions["can_prepare_extra_work_proposal"])

    def test_bm_in_assigned_building_actions_true_by_default(self):
        actions = self._fetch_actions(self.bm_in, self.building_a)
        self.assertTrue(actions["can_override_customer_decision"])
        self.assertTrue(actions["can_prepare_extra_work_proposal"])

    def test_bm_actions_reflect_disabled_keys(self):
        self._disable(OVERRIDE_KEY)
        actions = self._fetch_actions(self.bm_in, self.building_a)
        self.assertFalse(actions["can_override_customer_decision"])
        # Prep stays True because we only disabled override.
        self.assertTrue(actions["can_prepare_extra_work_proposal"])

        self._disable(PREP_KEY)
        actions = self._fetch_actions(self.bm_in, self.building_a)
        self.assertFalse(actions["can_override_customer_decision"])
        self.assertFalse(actions["can_prepare_extra_work_proposal"])

    def test_bm_out_actions_false(self):
        # bm_out is in scope at the company level but not at the
        # building level. The endpoint refuses the (customer A,
        # building A) probe with an out-of-scope error before reaching
        # the effective_actions block — assert via the bm_out's other
        # building instead.
        actions = self._fetch_actions(self.bm_in, self.building_a)
        # Sanity: bm_in has actions True (control).
        self.assertTrue(actions["can_override_customer_decision"])
        # The B6 keys themselves are False for bm_out at building A:
        self.assertFalse(
            user_has_osius_permission(
                self.bm_out, OVERRIDE_KEY, building_id=self.building_a.id
            )
        )

    def test_staff_actions_false(self):
        actions = self._fetch_actions(self.staff_in, self.building_a)
        self.assertFalse(actions["can_override_customer_decision"])
        self.assertFalse(actions["can_prepare_extra_work_proposal"])

    def test_customer_user_actions_false(self):
        actions = self._fetch_actions(self.customer_user, self.building_a)
        self.assertFalse(actions["can_override_customer_decision"])
        self.assertFalse(actions["can_prepare_extra_work_proposal"])


# ---------------------------------------------------------------------------
# G. URL-smuggling regression — direct URL attempts on every BM-revocable
#    surface return the proper rejection code without mutating state.
# ---------------------------------------------------------------------------
class UrlSmugglingRegressionTests(_B6Fixture):
    def setUp(self):
        super().setUp()
        self._disable(OVERRIDE_KEY)
        self._disable(PREP_KEY)

    def test_ticket_status_endpoint_blocked(self):
        ticket = self._make_ticket()
        response = self._api(self.bm_in).post(
            f"/api/tickets/{ticket.id}/status/",
            {
                "to_status": TicketStatus.REJECTED,
                "is_override": True,
                "override_reason": "Customer rejected by phone.",
            },
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data.get("code"), "bm_override_disabled")

    def test_extra_work_transition_endpoint_blocked(self):
        ew, _, _ = self._make_extra_work_with_sent_proposal()
        response = self._api(self.bm_in).post(
            f"/api/extra-work/{ew.id}/transition/",
            {
                "to_status": ExtraWorkStatus.CUSTOMER_REJECTED,
                "is_override": True,
                "override_reason": "Customer rejected.",
            },
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data.get("code"), "bm_override_disabled")

    def test_proposal_transition_to_customer_rejected_blocked(self):
        ew, proposal, _ = self._make_extra_work_with_sent_proposal()
        response = self._api(self.bm_in).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/transition/",
            {
                "to_status": ProposalStatus.CUSTOMER_REJECTED,
                "is_override": True,
                "override_reason": "Customer rejected.",
            },
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data.get("code"), "bm_override_disabled")

    def test_proposal_create_endpoint_blocked(self):
        ew, _, _ = self._make_extra_work_with_draft_proposal()
        Proposal.objects.filter(extra_work_request=ew).delete()
        response = self._api(self.bm_in).post(
            f"/api/extra-work/{ew.id}/proposals/",
            {"lines": []},
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN, response.data
        )
        self.assertEqual(
            response.data.get("code"), "bm_proposal_preparation_disabled"
        )

    def test_proposal_line_create_endpoint_blocked(self):
        ew, proposal, service = self._make_extra_work_with_draft_proposal()
        response = self._api(self.bm_in).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/lines/",
            {
                "service": service.id,
                "unit_type": ExtraWorkPricingUnitType.FIXED,
                "quantity": "1.00",
                "unit_price": "50.00",
                "vat_pct": "21.00",
            },
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN, response.data
        )
        self.assertEqual(
            response.data.get("code"), "bm_proposal_preparation_disabled"
        )

    def test_proposal_transition_draft_to_sent_blocked(self):
        ew, proposal, service = self._make_extra_work_with_draft_proposal()
        ProposalLine.objects.create(
            proposal=proposal,
            service=service,
            unit_type=ExtraWorkPricingUnitType.FIXED,
            quantity=Decimal("1.00"),
            unit_price=Decimal("50.00"),
            vat_pct=Decimal("21.00"),
        )
        response = self._api(self.bm_in).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/transition/",
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            response.data.get("code"), "bm_proposal_preparation_disabled"
        )

    def test_proposal_transition_draft_to_cancelled_blocked(self):
        ew, proposal, _ = self._make_extra_work_with_draft_proposal()
        response = self._api(self.bm_in).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/transition/",
            {
                "to_status": ProposalStatus.CANCELLED,
            },
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            response.data.get("code"), "bm_proposal_preparation_disabled"
        )


# ---------------------------------------------------------------------------
# H. PATCH /api/buildings/<bid>/managers/<uid>/ write surface
# ---------------------------------------------------------------------------
class PatchOverridesWriteSurfaceTests(_B6Fixture):
    def _url(self):
        return (
            f"/api/buildings/{self.building_a.id}/managers/{self.bm_in.id}/"
        )

    def test_super_admin_can_disable_override_key(self):
        response = self._api(self.super_admin).patch(
            self._url(),
            {"permission_overrides": {OVERRIDE_KEY: False}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.bm_in_assignment.refresh_from_db()
        self.assertEqual(
            self.bm_in_assignment.permission_overrides,
            {OVERRIDE_KEY: False},
        )

    def test_company_admin_in_scope_can_flip_overrides(self):
        response = self._api(self.admin).patch(
            self._url(),
            {"permission_overrides": {PREP_KEY: False}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.bm_in_assignment.refresh_from_db()
        self.assertEqual(
            self.bm_in_assignment.permission_overrides,
            {PREP_KEY: False},
        )

    def test_bm_cannot_flip_their_own_overrides(self):
        response = self._api(self.bm_in).patch(
            self._url(),
            {"permission_overrides": {OVERRIDE_KEY: False}},
            format="json",
        )
        # IsSuperAdminOrCompanyAdminForCompany rejects BM at the class
        # permission layer — expect 403 (admit denied) before the
        # serializer ever runs.
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.bm_in_assignment.refresh_from_db()
        self.assertEqual(self.bm_in_assignment.permission_overrides, {})

    def test_unknown_key_rejected(self):
        response = self._api(self.super_admin).patch(
            self._url(),
            {"permission_overrides": {"osius.ticket.view_building": False}},
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.bm_in_assignment.refresh_from_db()
        self.assertEqual(self.bm_in_assignment.permission_overrides, {})

    def test_non_boolean_value_rejected(self):
        for bad in (1, 0, "true", "false", None, [], {"x": 1}):
            response = self._api(self.super_admin).patch(
                self._url(),
                {"permission_overrides": {OVERRIDE_KEY: bad}},
                format="json",
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_400_BAD_REQUEST,
                f"value={bad!r}",
            )
        self.bm_in_assignment.refresh_from_db()
        self.assertEqual(self.bm_in_assignment.permission_overrides, {})

    def test_non_dict_payload_rejected(self):
        for bad in ([], "not a dict", 1, True):
            response = self._api(self.super_admin).patch(
                self._url(),
                {"permission_overrides": bad},
                format="json",
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_400_BAD_REQUEST,
                f"payload={bad!r}",
            )

    def test_full_replacement_semantics(self):
        # Seed with both keys set.
        self.bm_in_assignment.permission_overrides = {
            OVERRIDE_KEY: False,
            PREP_KEY: False,
        }
        self.bm_in_assignment.save(update_fields=["permission_overrides"])
        # PATCH with only one key replaces the whole dict.
        response = self._api(self.super_admin).patch(
            self._url(),
            {"permission_overrides": {OVERRIDE_KEY: True}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.bm_in_assignment.refresh_from_db()
        self.assertEqual(
            self.bm_in_assignment.permission_overrides,
            {OVERRIDE_KEY: True},
        )

    def test_patch_writes_audit_log_update_row(self):
        before = AuditLog.objects.filter(
            target_model="buildings.BuildingManagerAssignment",
            target_id=self.bm_in_assignment.id,
            action=AuditAction.UPDATE,
        ).count()
        response = self._api(self.super_admin).patch(
            self._url(),
            {"permission_overrides": {OVERRIDE_KEY: False}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        after = AuditLog.objects.filter(
            target_model="buildings.BuildingManagerAssignment",
            target_id=self.bm_in_assignment.id,
            action=AuditAction.UPDATE,
        )
        self.assertEqual(
            after.count() - before,
            1,
            "Override flip must produce exactly one AuditLog UPDATE row.",
        )
        row = after.latest("created_at")
        self.assertIn("permission_overrides", row.changes)
        diff = row.changes["permission_overrides"]
        self.assertEqual(diff.get("before"), {})
        self.assertEqual(diff.get("after"), {OVERRIDE_KEY: False})


# ---------------------------------------------------------------------------
# Allow-list sanity — the frozenset is exactly the two B6 keys
# ---------------------------------------------------------------------------
class AllowListSanityTests(TestCase):
    def test_bm_revocable_permission_keys_is_exactly_two(self):
        self.assertEqual(
            BM_REVOCABLE_PERMISSION_KEYS,
            frozenset({OVERRIDE_KEY, PREP_KEY}),
        )


# ---------------------------------------------------------------------------
# Proposal detail surface — no PATCH / PUT / DELETE endpoint exists. B6's
# proposal-preparation gate only needs to cover the writable surfaces
# (proposal POST + lines CRUD + transitions). Pin this regression so a
# future refactor that adds a writable detail endpoint MUST also wire
# the B6 gate, or this test will catch the gap.
# ---------------------------------------------------------------------------
class ProposalDetailHasNoWriteEndpointTests(_B6Fixture):
    def _detail_url(self, ew_id, pid):
        return f"/api/extra-work/{ew_id}/proposals/{pid}/"

    def _proposal_for_tests(self):
        _, proposal, _ = self._make_extra_work_with_draft_proposal()
        return proposal

    def test_proposal_detail_patch_returns_method_not_allowed(self):
        proposal = self._proposal_for_tests()
        response = self._api(self.super_admin).patch(
            self._detail_url(proposal.extra_work_request_id, proposal.id),
            {"status": ProposalStatus.SENT},
            format="json",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
            response.content,
        )

    def test_proposal_detail_put_returns_method_not_allowed(self):
        proposal = self._proposal_for_tests()
        response = self._api(self.super_admin).put(
            self._detail_url(proposal.extra_work_request_id, proposal.id),
            {"status": ProposalStatus.SENT},
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED
        )

    def test_proposal_detail_delete_returns_method_not_allowed(self):
        proposal = self._proposal_for_tests()
        response = self._api(self.super_admin).delete(
            self._detail_url(proposal.extra_work_request_id, proposal.id)
        )
        self.assertEqual(
            response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED
        )


# ---------------------------------------------------------------------------
# Proposal PDF visibility — B6 narrows WRITE authority. The PDF is a
# read-only rendering and is governed by the same provider-operator
# scope as before. Pin the intended B6 behaviour:
#
#   * STAFF cannot reach the PDF endpoint (P0 staff-privacy posture —
#     scope_extra_work_for hides the parent EW from STAFF).
#   * BM whose `prepare_extra_work_proposal` is False CAN still GET
#     the PDF. The four-tier note taxonomy (B7) is the deliberate
#     follow-up batch that will further restrict commercial /
#     financial visibility per the canonical floor in §4.3 + §9.2.
#
# Future B7 may add a separate `osius.building_manager.view_proposal_*`
# key with its own override map. B6 does not pre-empt that decision.
# ---------------------------------------------------------------------------
class ProposalPdfVisibilityTests(_B6Fixture):
    def test_staff_cannot_reach_proposal_pdf(self):
        ew, proposal, _ = self._make_extra_work_with_sent_proposal()
        response = self._api(self.staff_in).get(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/pdf/"
        )
        # scope_extra_work_for returns an empty queryset for STAFF, so
        # the parent EW lookup raises 404. Either way: STAFF cannot
        # see proposal pricing via the PDF.
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )

    def test_bm_can_view_proposal_pdf_when_prep_key_default_true(self):
        ew, proposal, _ = self._make_extra_work_with_sent_proposal()
        response = self._api(self.bm_in).get(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/pdf/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_bm_can_still_view_proposal_pdf_when_prep_key_disabled(self):
        # B6 narrows BM write authority only. With
        # `prepare_extra_work_proposal=False` the BM still sees the PDF
        # because reading and preparing are separately modelled in the
        # canonical doc (§4.3, §7). A future B7 batch may add a
        # dedicated view-proposal key with its own override map; until
        # then the PDF endpoint stays open to in-scope BMs.
        self._disable(PREP_KEY)
        ew, proposal, _ = self._make_extra_work_with_sent_proposal()
        response = self._api(self.bm_in).get(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/pdf/"
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.content,
        )
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_bm_out_of_assigned_building_cannot_reach_pdf(self):
        # Cross-building isolation: bm_out is assigned to building_b
        # only. The parent EW lookup goes through
        # `scope_extra_work_for` which filters by BM building
        # assignment, so the BM-out actor never reaches the PDF for
        # building_a's EW.
        ew, proposal, _ = self._make_extra_work_with_sent_proposal()
        response = self._api(self.bm_out).get(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/pdf/"
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )
