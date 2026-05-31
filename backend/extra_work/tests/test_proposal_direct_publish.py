"""
Per-record actions backend — `POST /api/extra-work/<ew_id>/proposals/
<pid>/direct-publish/` endpoint tests.

The endpoint atomically drives a DRAFT proposal through SENT to
CUSTOMER_APPROVED. Tests cover:

  * Happy path: SA can direct-publish; proposal becomes
    CUSTOMER_APPROVED with `is_override=True` on the SENT->
    CUSTOMER_APPROVED status-history row; parent EW becomes
    CUSTOMER_APPROVED; operational tickets are spawned.
  * Override-reason gate: HTTP 400 with code
    `override_reason_required` when blank or whitespace-only.
  * DRAFT-only gate: HTTP 400 with code
    `direct_publish_requires_draft` when called on SENT / etc.
  * CUSTOMER_USER / STAFF -> 403.
  * BM with prep key revoked -> 403.
  * BM with override key revoked -> 403.
  * Atomicity: when the SENT->CUSTOMER_APPROVED step raises, the
    DRAFT->SENT step rolls back (proposal stays DRAFT).
  * Normal DRAFT -> SENT customer-approval flow still works
    (existing transition endpoint unaffected).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
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
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkStatus,
    Proposal,
    ProposalLine,
    ProposalStatus,
    ProposalStatusHistory,
    Service,
    ServiceCategory,
)
from extra_work.proposal_state_machine import TransitionError
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


class _DirectPublishFixtureMixin:
    """Shared fixture matching the per-record actions tests but with
    additional STAFF / BM-override-revoked variants for the gate
    assertions.
    """

    @classmethod
    def _setup(cls):
        cls.company = Company.objects.create(
            name="Provider DP", slug="prov-dp"
        )
        cls.building = Building.objects.create(
            company=cls.company, name="Building-DP"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            name="Customer-DP",
            building=cls.building,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            "super-dp@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-dp@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(user=cls.admin, company=cls.company)

        cls.bm = _mk("bm-dp@example.com", UserRole.BUILDING_MANAGER)
        cls.bma = BuildingManagerAssignment.objects.create(
            user=cls.bm, building=cls.building
        )

        cls.staff = _mk("staff-dp@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        # Give STAFF visibility on the building so they can at least
        # see the ticket endpoint (not that they reach EW — scope is
        # .none() for STAFF — but for completeness on the gate test).
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.building
        )

        cls.cust_user = _mk("cust-dp@example.com", UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        cls.service = Service.objects.create(
            category=ServiceCategory.objects.create(name="Cat-DP"),
            company=cls.company,
            name="Direct-publish service",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )

    @classmethod
    def _bm_set_overrides(cls, **flags):
        """Set the BM's permission_overrides map from kwargs. Any flag
        absent from the call leaves the previous value in place.
        """
        cls.bma.refresh_from_db()
        overrides = dict(cls.bma.permission_overrides or {})
        for key, value in flags.items():
            full_key = f"osius.building_manager.{key}"
            overrides[full_key] = value
        cls.bma.permission_overrides = overrides
        cls.bma.save(update_fields=["permission_overrides"])

    def setUp(self):
        # Reset the BM's override map between tests to keep the
        # default (no overrides) starting state predictable.
        self.bma.refresh_from_db()
        self.bma.permission_overrides = {}
        self.bma.save(update_fields=["permission_overrides"])

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _make_ew_under_review(self, *, cart_qty=Decimal("2.00")) -> ExtraWorkRequest:
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title="Direct publish EW",
            description="parent description",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.UNDER_REVIEW,
        )
        ExtraWorkRequestItem.objects.create(
            extra_work_request=ew,
            service=self.service,
            quantity=cart_qty,
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=date(2026, 6, 15),
            customer_note="",
        )
        return ew

    def _make_draft_proposal(
        self,
        ew: ExtraWorkRequest,
        *,
        actor=None,
        quantity=Decimal("2.00"),
        unit_price=Decimal("50.00"),
    ) -> Proposal:
        proposal = Proposal.objects.create(
            extra_work_request=ew,
            status=ProposalStatus.DRAFT,
            created_by=actor or self.admin,
        )
        ProposalLine.objects.create(
            proposal=proposal,
            service=self.service,
            description="",
            quantity=quantity,
            unit_type=ExtraWorkPricingUnitType.HOURS,
            unit_price=unit_price,
            vat_pct=Decimal("21.00"),
            customer_explanation="Visible line note",
            internal_note="Provider-only note",
        )
        proposal.recompute_totals()
        proposal.refresh_from_db()
        return proposal

    def _publish_url(self, ew_id: int, pid: int) -> str:
        return f"/api/extra-work/{ew_id}/proposals/{pid}/direct-publish/"

    def _transition_url(self, ew_id: int, pid: int) -> str:
        return f"/api/extra-work/{ew_id}/proposals/{pid}/transition/"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
class DirectPublishHappyPathTests(_DirectPublishFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup()

    def test_super_admin_can_direct_publish_draft_proposal(self):
        ew = self._make_ew_under_review()
        proposal = self._make_draft_proposal(ew)
        tickets_before = Ticket.objects.count()

        response = self._api(self.super_admin).post(
            self._publish_url(ew.id, proposal.id),
            {"override_reason": "Customer approved verbally over the phone."},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        # Response shape is ProposalDetailSerializer + new actions block.
        self.assertEqual(response.data["status"], ProposalStatus.CUSTOMER_APPROVED)
        self.assertIn("actions", response.data)

        # Proposal status persisted.
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ProposalStatus.CUSTOMER_APPROVED)
        # Override metadata stamped on the proposal row.
        self.assertEqual(proposal.override_by_id, self.super_admin.id)
        self.assertIn("verbally", proposal.override_reason)

        # The SENT->CUSTOMER_APPROVED status-history row carries
        # is_override=True with a non-empty override_reason. We pick
        # the row by its new_status because the DRAFT->SENT row also
        # exists.
        history_row = ProposalStatusHistory.objects.get(
            proposal=proposal,
            new_status=ProposalStatus.CUSTOMER_APPROVED,
        )
        self.assertTrue(history_row.is_override)
        self.assertIn("verbally", history_row.override_reason)

        # Parent EW advanced to CUSTOMER_APPROVED via the existing
        # `_advance_parent_on_customer_decision` hook.
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)

        # Operational ticket spawn ran via the existing
        # `spawn_tickets_for_proposal` path. We seeded one line, so
        # exactly one new ticket should exist.
        self.assertEqual(Ticket.objects.count(), tickets_before + 1)
        spawned = Ticket.objects.filter(
            proposal_line__proposal=proposal
        ).first()
        self.assertIsNotNone(spawned)
        self.assertEqual(spawned.customer_id, self.customer.id)
        self.assertEqual(spawned.building_id, self.building.id)

    def test_company_admin_can_direct_publish(self):
        ew = self._make_ew_under_review()
        proposal = self._make_draft_proposal(ew)
        response = self._api(self.admin).post(
            self._publish_url(ew.id, proposal.id),
            {"override_reason": "Field crew already on site."},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ProposalStatus.CUSTOMER_APPROVED)

    def test_bm_with_both_keys_can_direct_publish(self):
        # Default: BMA has empty overrides -> both keys resolve True.
        ew = self._make_ew_under_review()
        proposal = self._make_draft_proposal(ew)
        response = self._api(self.bm).post(
            self._publish_url(ew.id, proposal.id),
            {"override_reason": "Tenant signed off on paper."},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ProposalStatus.CUSTOMER_APPROVED)


# ---------------------------------------------------------------------------
# Override-reason gate
# ---------------------------------------------------------------------------
class DirectPublishOverrideReasonGateTests(_DirectPublishFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup()

    def test_missing_override_reason_rejected_with_stable_code(self):
        ew = self._make_ew_under_review()
        proposal = self._make_draft_proposal(ew)
        response = self._api(self.super_admin).post(
            self._publish_url(ew.id, proposal.id),
            {},  # no override_reason
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "override_reason_required")
        # Proposal remained DRAFT — no partial transition.
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ProposalStatus.DRAFT)

    def test_whitespace_only_override_reason_rejected(self):
        ew = self._make_ew_under_review()
        proposal = self._make_draft_proposal(ew)
        response = self._api(self.super_admin).post(
            self._publish_url(ew.id, proposal.id),
            {"override_reason": "   \t\n   "},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "override_reason_required")


# ---------------------------------------------------------------------------
# Not-DRAFT gate
# ---------------------------------------------------------------------------
class DirectPublishStatusGateTests(_DirectPublishFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup()

    def test_called_on_sent_proposal_rejected_with_stable_code(self):
        ew = self._make_ew_under_review()
        proposal = self._make_draft_proposal(ew)
        proposal.status = ProposalStatus.SENT
        proposal.save(update_fields=["status"])

        response = self._api(self.super_admin).post(
            self._publish_url(ew.id, proposal.id),
            {"override_reason": "irrelevant"},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "direct_publish_requires_draft")


# ---------------------------------------------------------------------------
# Permission gates — CUSTOMER_USER / STAFF / BM with revoked keys
# ---------------------------------------------------------------------------
class DirectPublishPermissionGateTests(_DirectPublishFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup()

    def test_customer_user_forbidden(self):
        ew = self._make_ew_under_review()
        proposal = self._make_draft_proposal(ew)
        response = self._api(self.cust_user).post(
            self._publish_url(ew.id, proposal.id),
            {"override_reason": "trying anyway"},
            format="json",
        )
        # Customer cannot see DRAFT proposals (404 from the resolver)
        # so the gate fires before the role-check; either 403 OR 404
        # is acceptable as "not 200". The brief explicitly says
        # "CUSTOMER_USER -> 403/400 (not 200)". We accept 403 and
        # 404 here because the customer never reaches the role gate
        # — the scope helper returns the proposal as invisible. 200
        # is the only forbidden outcome.
        self.assertNotEqual(response.status_code, 200, response.data)
        self.assertIn(response.status_code, (403, 404))
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ProposalStatus.DRAFT)

    def test_staff_forbidden(self):
        ew = self._make_ew_under_review()
        proposal = self._make_draft_proposal(ew)
        response = self._api(self.staff).post(
            self._publish_url(ew.id, proposal.id),
            {"override_reason": "trying anyway"},
            format="json",
        )
        # STAFF EW scope is .none() so the EW itself is 404 for them;
        # they never reach the proposal. Either 403 or 404 is fine —
        # 200 is forbidden.
        self.assertNotEqual(response.status_code, 200, response.data)
        self.assertIn(response.status_code, (403, 404))
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ProposalStatus.DRAFT)

    def test_bm_with_prep_revoked_forbidden(self):
        # Revoke the prep key for this BM at this building.
        self._bm_set_overrides(prepare_extra_work_proposal=False)
        ew = self._make_ew_under_review()
        proposal = self._make_draft_proposal(ew)
        response = self._api(self.bm).post(
            self._publish_url(ew.id, proposal.id),
            {"override_reason": "Should be blocked"},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.data)
        # The prep gate has a stable code on the existing helper.
        self.assertEqual(response.data["code"], "bm_proposal_preparation_disabled")
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ProposalStatus.DRAFT)

    def test_bm_with_override_revoked_forbidden(self):
        # Prep granted, override revoked. The endpoint's BM extra
        # gate should fire with bm_override_disabled.
        self._bm_set_overrides(override_customer_decision=False)
        ew = self._make_ew_under_review()
        proposal = self._make_draft_proposal(ew)
        response = self._api(self.bm).post(
            self._publish_url(ew.id, proposal.id),
            {"override_reason": "Should be blocked"},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data["code"], "bm_override_disabled")
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ProposalStatus.DRAFT)


# ---------------------------------------------------------------------------
# Atomicity — mid-flight failure rolls everything back
# ---------------------------------------------------------------------------
class DirectPublishAtomicityTests(_DirectPublishFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup()

    def test_second_transition_failure_rolls_back_first(self):
        ew = self._make_ew_under_review()
        proposal = self._make_draft_proposal(ew)

        # Patch `spawn_tickets_for_proposal` at its source module
        # (`extra_work.proposal_tickets`) — the state machine imports
        # it lazily inside `apply_proposal_transition`, so patching at
        # the consumer's namespace would miss the call. Patching the
        # source module catches the lazy import.
        target = (
            "extra_work.proposal_tickets.spawn_tickets_for_proposal"
        )
        tickets_before = Ticket.objects.count()
        history_before = ProposalStatusHistory.objects.filter(
            proposal=proposal
        ).count()

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated spawn failure")

        # The RuntimeError is not a TransitionError, so the view's
        # except clause does not catch it. DRF's test client re-raises
        # unhandled exceptions by default, so we wrap the POST in
        # `assertRaises` — same pattern as the existing
        # `test_sprint28_proposal.py` atomicity test. The pin is the
        # database state AFTER the failed transaction, NOT the HTTP
        # response shape (which doesn't exist for an unhandled
        # exception).
        with patch(target, side_effect=_boom):
            with self.assertRaises(RuntimeError):
                self._api(self.super_admin).post(
                    self._publish_url(ew.id, proposal.id),
                    {"override_reason": "Will be rolled back"},
                    format="json",
                )

        proposal.refresh_from_db()
        self.assertEqual(
            proposal.status,
            ProposalStatus.DRAFT,
            "DRAFT->SENT must roll back when SENT->CUSTOMER_APPROVED raises",
        )
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.UNDER_REVIEW)
        # No ticket was created (atomic block reverts the spawn).
        self.assertEqual(Ticket.objects.count(), tickets_before)
        # No proposal status-history rows were committed either.
        self.assertEqual(
            ProposalStatusHistory.objects.filter(proposal=proposal).count(),
            history_before,
        )


# ---------------------------------------------------------------------------
# Existing transition endpoint unaffected
# ---------------------------------------------------------------------------
class DirectPublishDoesNotBreakTransitionEndpointTests(
    _DirectPublishFixtureMixin, TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls._setup()

    def test_normal_send_and_customer_approve_still_works(self):
        # The normal flow: admin SENDs, customer approves.
        ew = self._make_ew_under_review()
        proposal = self._make_draft_proposal(ew)

        # Admin SENDs via the existing transition endpoint.
        response = self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ProposalStatus.SENT)

        # Customer approves via the existing transition endpoint.
        response = self._api(self.cust_user).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ProposalStatus.CUSTOMER_APPROVED)
        # is_override stays False — this is a customer-driven flow.
        history_row = ProposalStatusHistory.objects.get(
            proposal=proposal,
            new_status=ProposalStatus.CUSTOMER_APPROVED,
        )
        self.assertFalse(history_row.is_override)
