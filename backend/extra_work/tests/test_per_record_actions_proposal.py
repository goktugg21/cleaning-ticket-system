"""
Per-record actions backend — EW detail and Proposal detail
`actions` blocks.

Pins the contract:

  * EW detail `actions.can_prepare_extra_work_proposal` is False
    for a BM whose B6 prep key is revoked, True otherwise (SA / CA
    / BM-with-prep-True).
  * Proposal detail `actions` for a BM with prep revoked:
      - can_edit_lines=False
      - can_send=False
      - can_cancel=False
      - can_direct_publish=False
      - BUT can_view_proposal_pricing=True
      - AND can_view_proposal_pdf=True
    (the critical product-rule: revoking prep removes mutation but
    NOT pricing visibility.)
  * Other shape checks (allowed_next_statuses agreement; the
    customer / SA shapes) for confidence.
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
    ExtraWorkCategory,
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


class _ActionsFixtureMixin:
    """Compact fixture: provider company, one building, one customer,
    a service catalog with one service, a BM assigned to the building,
    and a CUSTOMER_USER with default-tier access. The EW + Proposal
    are built per-test so individual tests can vary status.
    """

    @classmethod
    def _setup(cls):
        cls.company = Company.objects.create(
            name="Provider PR", slug="prov-pr-actions"
        )
        cls.building = Building.objects.create(
            company=cls.company, name="Building-PR-A"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            name="Customer-PR-A",
            building=cls.building,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            "super-pr@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-pr@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(user=cls.admin, company=cls.company)
        cls.bm = _mk("bm-pr@example.com", UserRole.BUILDING_MANAGER)
        cls.bma = BuildingManagerAssignment.objects.create(
            user=cls.bm, building=cls.building
        )
        cls.cust_user = _mk("cust-pr@example.com", UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )
        cls.service = Service.objects.create(
            category=ServiceCategory.objects.create(name="Cat-PR"),
            name="Window cleaning",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )

    @classmethod
    def _revoke_bm_prep_key(cls):
        cls.bma.refresh_from_db()
        cls.bma.permission_overrides = {
            "osius.building_manager.prepare_extra_work_proposal": False,
        }
        cls.bma.save(update_fields=["permission_overrides"])

    @classmethod
    def _revoke_bm_override_key(cls):
        cls.bma.refresh_from_db()
        overrides = dict(cls.bma.permission_overrides or {})
        overrides["osius.building_manager.override_customer_decision"] = False
        cls.bma.permission_overrides = overrides
        cls.bma.save(update_fields=["permission_overrides"])

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _make_ew(self, *, status=ExtraWorkStatus.UNDER_REVIEW) -> ExtraWorkRequest:
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title="Test EW",
            description="parent description",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=status,
        )
        ExtraWorkRequestItem.objects.create(
            extra_work_request=ew,
            service=self.service,
            quantity=Decimal("2.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=date(2026, 6, 15),
            customer_note="",
        )
        return ew

    def _make_proposal(
        self,
        ew: ExtraWorkRequest,
        *,
        status: str = ProposalStatus.DRAFT,
        actor=None,
    ) -> Proposal:
        proposal = Proposal.objects.create(
            extra_work_request=ew,
            status=status,
            created_by=actor or self.admin,
        )
        ProposalLine.objects.create(
            proposal=proposal,
            service=self.service,
            description="",
            quantity=Decimal("2.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            unit_price=Decimal("50.00"),
            vat_pct=Decimal("21.00"),
            customer_explanation="Visible explanation",
            internal_note="Provider-only",
        )
        proposal.recompute_totals()
        proposal.refresh_from_db()
        return proposal

    def _ew_detail(self, user, ew):
        return self._api(user).get(f"/api/extra-work/{ew.id}/")

    def _proposal_detail(self, user, ew, proposal):
        return self._api(user).get(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/"
        )


# ---------------------------------------------------------------------------
# EW detail actions
# ---------------------------------------------------------------------------
class ExtraWorkActionsBlockTests(_ActionsFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup()

    def test_actions_block_shape_for_admin(self):
        # Status set to PRICING_PROPOSED so the tightened
        # can_override_customer_decision (now status-gated, not authority-
        # only) is True for an in-scope admin.
        ew = self._make_ew(status=ExtraWorkStatus.PRICING_PROPOSED)
        response = self._ew_detail(self.admin, ew)
        self.assertEqual(response.status_code, 200, response.data)
        actions = response.data["actions"]
        for key in [
            "allowed_next_statuses",
            "can_prepare_extra_work_proposal",
            "can_override_customer_decision",
            "can_view_pricing",
            "can_view_proposal_pdf",
            "can_approve",
            "can_reject",
        ]:
            self.assertIn(key, actions, f"missing {key}")
        # Admin in scope must be able to prepare + override + view.
        self.assertTrue(actions["can_prepare_extra_work_proposal"])
        self.assertTrue(actions["can_override_customer_decision"])
        self.assertTrue(actions["can_view_pricing"])
        self.assertTrue(actions["can_view_proposal_pdf"])

    def test_actions_can_prepare_extra_work_proposal_false_for_bm_with_prep_revoked(self):
        # Revoke before making the EW so the resolver sees the False
        # override at action-computation time.
        self._revoke_bm_prep_key()
        ew = self._make_ew()
        response = self._ew_detail(self.bm, ew)
        self.assertEqual(response.status_code, 200, response.data)
        actions = response.data["actions"]
        self.assertFalse(
            actions["can_prepare_extra_work_proposal"],
            "BM with prep key revoked must NOT see can_prepare True",
        )

    def test_actions_can_prepare_extra_work_proposal_true_for_bm_default(self):
        # Reset to a clean BMA row (no overrides).
        self.bma.refresh_from_db()
        self.bma.permission_overrides = {}
        self.bma.save(update_fields=["permission_overrides"])
        ew = self._make_ew()
        response = self._ew_detail(self.bm, ew)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["actions"]["can_prepare_extra_work_proposal"])

    def test_actions_allowed_next_statuses_matches_top_level(self):
        ew = self._make_ew()
        response = self._ew_detail(self.admin, ew)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data["actions"]["allowed_next_statuses"],
            response.data["allowed_next_statuses"],
        )

    # -----------------------------------------------------------------
    # Tightened-precondition tests: can_override_customer_decision is
    # False outside PRICING_PROPOSED even for actors with full override
    # authority. The boolean now reflects CURRENT record state, not
    # just authority.
    # -----------------------------------------------------------------
    def test_can_override_customer_decision_true_at_pricing_proposed_for_admin(self):
        # Positive case — admin in scope sees True at PRICING_PROPOSED.
        ew = self._make_ew(status=ExtraWorkStatus.PRICING_PROPOSED)
        response = self._ew_detail(self.admin, ew)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["actions"]["can_override_customer_decision"])

    def test_can_override_customer_decision_false_at_requested_for_super_admin(self):
        ew = self._make_ew(status=ExtraWorkStatus.REQUESTED)
        response = self._ew_detail(self.super_admin, ew)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(
            response.data["actions"]["can_override_customer_decision"],
            "SA must see False on a REQUESTED EW — authority alone is not enough",
        )

    def test_can_override_customer_decision_false_at_under_review_for_super_admin(self):
        ew = self._make_ew(status=ExtraWorkStatus.UNDER_REVIEW)
        response = self._ew_detail(self.super_admin, ew)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(
            response.data["actions"]["can_override_customer_decision"],
            "SA must see False on an UNDER_REVIEW EW",
        )

    def test_can_override_customer_decision_false_at_customer_approved_for_admin(self):
        ew = self._make_ew(status=ExtraWorkStatus.CUSTOMER_APPROVED)
        response = self._ew_detail(self.admin, ew)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(
            response.data["actions"]["can_override_customer_decision"],
            "Admin must see False on an already-CUSTOMER_APPROVED EW",
        )

    def test_can_override_customer_decision_false_at_in_progress_for_super_admin(self):
        ew = self._make_ew(status=ExtraWorkStatus.IN_PROGRESS)
        response = self._ew_detail(self.super_admin, ew)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(
            response.data["actions"]["can_override_customer_decision"],
            "SA must see False on an IN_PROGRESS EW",
        )

    def test_can_override_customer_decision_false_at_completed_for_super_admin(self):
        ew = self._make_ew(status=ExtraWorkStatus.COMPLETED)
        response = self._ew_detail(self.super_admin, ew)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(
            response.data["actions"]["can_override_customer_decision"],
            "SA must see False on a COMPLETED EW",
        )


# ---------------------------------------------------------------------------
# Proposal detail actions — the critical product-rule fixture
# ---------------------------------------------------------------------------
class ProposalActionsBlockBMPrepRevokedTests(_ActionsFixtureMixin, TestCase):
    """The headline product-rule test: a BM whose prep key has been
    revoked must STILL see `can_view_proposal_pricing=True` and
    `can_view_proposal_pdf=True` on a proposal detail, while every
    mutation boolean (edit_lines / send / cancel / direct_publish)
    is False. Revoking prep narrows MUTATION authority; it does NOT
    revoke pricing READ access.
    """

    @classmethod
    def setUpTestData(cls):
        cls._setup()
        cls._revoke_bm_prep_key()

    def test_bm_with_prep_revoked_sees_pricing_and_pdf_but_no_mutations(self):
        ew = self._make_ew()
        proposal = self._make_proposal(ew, status=ProposalStatus.DRAFT)
        response = self._proposal_detail(self.bm, ew, proposal)
        self.assertEqual(response.status_code, 200, response.data)
        actions = response.data["actions"]

        # CRITICAL: pricing + PDF visibility remain True.
        self.assertTrue(
            actions["can_view_proposal_pricing"],
            "BM-with-prep-revoked must STILL see pricing",
        )
        self.assertTrue(
            actions["can_view_proposal_pdf"],
            "BM-with-prep-revoked must STILL see the PDF",
        )

        # Every mutation boolean is False — the prep revocation
        # locked them out of editing / sending / cancelling / direct-
        # publishing this proposal.
        self.assertFalse(actions["can_edit_lines"])
        self.assertFalse(actions["can_send"])
        self.assertFalse(actions["can_cancel"])
        self.assertFalse(actions["can_direct_publish"])


class ProposalActionsBlockShapeTests(_ActionsFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup()

    def test_admin_on_draft_can_send_edit_cancel_direct_publish(self):
        ew = self._make_ew()
        proposal = self._make_proposal(ew, status=ProposalStatus.DRAFT)
        response = self._proposal_detail(self.admin, ew, proposal)
        self.assertEqual(response.status_code, 200, response.data)
        actions = response.data["actions"]
        self.assertTrue(actions["can_view_proposal_pricing"])
        self.assertTrue(actions["can_view_proposal_pdf"])
        self.assertTrue(actions["can_edit_lines"])
        self.assertTrue(actions["can_send"])
        self.assertTrue(actions["can_cancel"])
        self.assertTrue(actions["can_direct_publish"])
        # Customer-decision booleans False — proposal is DRAFT, not SENT.
        self.assertFalse(actions["can_approve"])
        self.assertFalse(actions["can_reject"])

    def test_admin_on_sent_can_approve_and_reject(self):
        ew = self._make_ew()
        proposal = self._make_proposal(ew, status=ProposalStatus.SENT)
        response = self._proposal_detail(self.admin, ew, proposal)
        self.assertEqual(response.status_code, 200, response.data)
        actions = response.data["actions"]
        # Override authority for an admin in scope.
        self.assertTrue(actions["can_approve"])
        self.assertTrue(actions["can_reject"])
        # No edit / send on a SENT proposal.
        self.assertFalse(actions["can_edit_lines"])
        self.assertFalse(actions["can_send"])
        # Direct-publish is DRAFT-only.
        self.assertFalse(actions["can_direct_publish"])

    def test_customer_on_sent_can_approve_only_with_approve_key(self):
        ew = self._make_ew()
        proposal = self._make_proposal(ew, status=ProposalStatus.SENT)
        # cust_user holds CUSTOMER_USER access -> approve_own only if
        # they are the EW's creator. Our fixture has cust_user as the
        # creator, so approve_own resolves True via the role default.
        response = self._proposal_detail(self.cust_user, ew, proposal)
        self.assertEqual(response.status_code, 200, response.data)
        actions = response.data["actions"]
        self.assertTrue(actions["can_approve"])
        self.assertTrue(actions["can_reject"])

    def test_customer_cannot_direct_publish(self):
        ew = self._make_ew()
        proposal = self._make_proposal(ew, status=ProposalStatus.DRAFT)
        # Customer can't even see a DRAFT proposal (404), so the
        # action block is unreachable through the API. Confirm
        # the 404 to lock the behaviour.
        response = self._proposal_detail(self.cust_user, ew, proposal)
        self.assertEqual(response.status_code, 404)

    def test_bm_with_only_override_revoked_can_still_send_but_not_direct_publish(self):
        # Override revoked but prep intact: BM can SEND a draft (no
        # override needed) but cannot DIRECT-PUBLISH (which requires
        # both keys).
        self.bma.refresh_from_db()
        self.bma.permission_overrides = {
            "osius.building_manager.override_customer_decision": False,
        }
        self.bma.save(update_fields=["permission_overrides"])

        ew = self._make_ew()
        proposal = self._make_proposal(ew, status=ProposalStatus.DRAFT)
        response = self._proposal_detail(self.bm, ew, proposal)
        self.assertEqual(response.status_code, 200, response.data)
        actions = response.data["actions"]
        self.assertTrue(actions["can_view_proposal_pricing"])
        self.assertTrue(actions["can_edit_lines"])
        self.assertTrue(actions["can_send"])
        self.assertTrue(actions["can_cancel"])
        # Direct-publish requires BOTH keys -> False.
        self.assertFalse(actions["can_direct_publish"])

    # -----------------------------------------------------------------
    # Tightened-precondition tests: can_send and can_direct_publish are
    # False when the parent EW is NOT in UNDER_REVIEW even for actors
    # who hold full mutation + override authority. can_direct_publish
    # is derived from can_send so they cannot drift.
    # -----------------------------------------------------------------
    def test_draft_with_parent_requested_can_send_and_direct_publish_false_for_sa(self):
        # Parent EW in REQUESTED — the send-time gate would 400, so
        # both can_send and the tightened can_direct_publish must be
        # False even for SA.
        ew = self._make_ew(status=ExtraWorkStatus.REQUESTED)
        proposal = self._make_proposal(ew, status=ProposalStatus.DRAFT)
        response = self._proposal_detail(self.super_admin, ew, proposal)
        self.assertEqual(response.status_code, 200, response.data)
        actions = response.data["actions"]
        self.assertFalse(
            actions["can_send"],
            "SA must see can_send=False when parent EW is not UNDER_REVIEW",
        )
        self.assertFalse(
            actions["can_direct_publish"],
            "SA must see can_direct_publish=False — derived from can_send",
        )

    def test_draft_with_parent_pricing_proposed_can_send_and_direct_publish_false_for_bm_both_keys(self):
        # Parent EW already in PRICING_PROPOSED — DRAFT->SENT is not
        # legal from that parent state, so a BM with BOTH keys still
        # sees both booleans False. Reset BMA to ensure both keys are
        # at their True default.
        self.bma.refresh_from_db()
        self.bma.permission_overrides = {}
        self.bma.save(update_fields=["permission_overrides"])
        ew = self._make_ew(status=ExtraWorkStatus.PRICING_PROPOSED)
        proposal = self._make_proposal(ew, status=ProposalStatus.DRAFT)
        response = self._proposal_detail(self.bm, ew, proposal)
        self.assertEqual(response.status_code, 200, response.data)
        actions = response.data["actions"]
        self.assertFalse(
            actions["can_send"],
            "BM-with-both-keys must see can_send=False when parent EW is not UNDER_REVIEW",
        )
        self.assertFalse(
            actions["can_direct_publish"],
            "BM-with-both-keys must see can_direct_publish=False — derived from can_send",
        )

    def test_draft_with_parent_under_review_can_direct_publish_true_for_sa(self):
        # Positive control — parent UNDER_REVIEW + DRAFT proposal -> SA
        # sees both can_send and the derived can_direct_publish True.
        ew = self._make_ew(status=ExtraWorkStatus.UNDER_REVIEW)
        proposal = self._make_proposal(ew, status=ProposalStatus.DRAFT)
        response = self._proposal_detail(self.super_admin, ew, proposal)
        self.assertEqual(response.status_code, 200, response.data)
        actions = response.data["actions"]
        self.assertTrue(actions["can_send"])
        self.assertTrue(actions["can_direct_publish"])
