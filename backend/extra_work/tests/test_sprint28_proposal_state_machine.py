"""
Sprint 28 Batch 8 — proposal state-machine unit tests.

These focus on the structural shape (allowed transitions,
role-scope gate) below the HTTP layer.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

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
from extra_work.proposal_state_machine import (
    ALLOWED_TRANSITIONS,
    TransitionError,
    _user_can_drive_proposal_transition,
    apply_proposal_transition,
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


class ProposalStateMachineFixtureMixin:
    @classmethod
    def _setup_fixture(cls):
        cls.company = Company.objects.create(
            name="SM Provider", slug="sm-b8"
        )
        cls.building = Building.objects.create(
            company=cls.company, name="SM-Building"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="SM-Customer", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            "sm-super@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("sm-admin@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )
        cls.bm = _mk("sm-bm@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.bm, building=cls.building
        )
        cls.staff = _mk("sm-staff@example.com", UserRole.STAFF)
        cls.cust_user = _mk("sm-cust@example.com", UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        cls.service_cat = ServiceCategory.objects.create(name="SM-Cat")
        cls.service = Service.objects.create(
            category=cls.service_cat,
            name="SM-Service",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )

    @classmethod
    def _make_proposal(
        cls,
        *,
        proposal_status: str,
        parent_status: str = ExtraWorkStatus.UNDER_REVIEW,
        with_line: bool = True,
    ) -> Proposal:
        ew = ExtraWorkRequest.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.cust_user,
            title="SM EW",
            description="d",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=parent_status,
        )
        ExtraWorkRequestItem.objects.create(
            extra_work_request=ew,
            service=cls.service,
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=date(2026, 6, 15),
            customer_note="",
        )
        proposal = Proposal.objects.create(
            extra_work_request=ew,
            status=proposal_status,
            created_by=cls.admin,
        )
        if with_line:
            ProposalLine.objects.create(
                proposal=proposal,
                service=cls.service,
                quantity=Decimal("2.00"),
                unit_type=ExtraWorkPricingUnitType.HOURS,
                unit_price=Decimal("50.00"),
                vat_pct=Decimal("21.00"),
            )
        return proposal


class AllowedTransitionsStructureTests(
    ProposalStateMachineFixtureMixin, TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_allowed_transitions_set_is_exactly_what_we_documented(self):
        expected = {
            (ProposalStatus.DRAFT, ProposalStatus.SENT),
            (ProposalStatus.DRAFT, ProposalStatus.CANCELLED),
            (ProposalStatus.SENT, ProposalStatus.CUSTOMER_APPROVED),
            (ProposalStatus.SENT, ProposalStatus.CUSTOMER_REJECTED),
            (ProposalStatus.SENT, ProposalStatus.CANCELLED),
        }
        self.assertEqual(ALLOWED_TRANSITIONS, expected)

    def test_customer_rejected_to_draft_is_not_in_allowed_set(self):
        # Re-send after rejection is a new Proposal row, not a back-
        # transition. This pins the contract.
        self.assertNotIn(
            (ProposalStatus.CUSTOMER_REJECTED, ProposalStatus.DRAFT),
            ALLOWED_TRANSITIONS,
        )

    def test_disallowed_transition_raises_invalid_transition(self):
        proposal = self._make_proposal(
            proposal_status=ProposalStatus.CUSTOMER_REJECTED
        )
        with self.assertRaises(TransitionError) as cm:
            apply_proposal_transition(
                proposal, self.admin, ProposalStatus.DRAFT
            )
        self.assertEqual(cm.exception.code, "invalid_transition")


class UserCanDriveProposalTransitionTests(
    ProposalStateMachineFixtureMixin, TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_super_admin_can_drive_every_allowed_transition(self):
        for from_status, to_status in ALLOWED_TRANSITIONS:
            proposal = self._make_proposal(proposal_status=from_status)
            self.assertTrue(
                _user_can_drive_proposal_transition(
                    self.super_admin, proposal, to_status
                ),
                f"SUPER_ADMIN: {from_status} -> {to_status}",
            )

    def test_company_admin_in_scope_can_drive_provider_transitions(self):
        for from_status, to_status in ALLOWED_TRANSITIONS:
            proposal = self._make_proposal(proposal_status=from_status)
            self.assertTrue(
                _user_can_drive_proposal_transition(
                    self.admin, proposal, to_status
                ),
                f"COMPANY_ADMIN: {from_status} -> {to_status}",
            )

    def test_building_manager_in_scope_can_drive_provider_transitions(self):
        for from_status, to_status in ALLOWED_TRANSITIONS:
            proposal = self._make_proposal(proposal_status=from_status)
            self.assertTrue(
                _user_can_drive_proposal_transition(
                    self.bm, proposal, to_status
                ),
                f"BUILDING_MANAGER: {from_status} -> {to_status}",
            )

    def test_customer_user_can_drive_only_customer_decision_transitions(self):
        cases = {
            (ProposalStatus.DRAFT, ProposalStatus.SENT): False,
            (ProposalStatus.DRAFT, ProposalStatus.CANCELLED): False,
            (ProposalStatus.SENT, ProposalStatus.CUSTOMER_APPROVED): True,
            (ProposalStatus.SENT, ProposalStatus.CUSTOMER_REJECTED): True,
            (ProposalStatus.SENT, ProposalStatus.CANCELLED): False,
        }
        for (from_status, to_status), expected in cases.items():
            proposal = self._make_proposal(proposal_status=from_status)
            actual = _user_can_drive_proposal_transition(
                self.cust_user, proposal, to_status
            )
            self.assertEqual(
                actual,
                expected,
                f"CUSTOMER_USER: {from_status} -> {to_status}: "
                f"expected {expected}, got {actual}",
            )

    def test_staff_can_drive_nothing(self):
        for from_status, to_status in ALLOWED_TRANSITIONS:
            proposal = self._make_proposal(proposal_status=from_status)
            self.assertFalse(
                _user_can_drive_proposal_transition(
                    self.staff, proposal, to_status
                ),
                f"STAFF: {from_status} -> {to_status}",
            )


class ProviderOverrideCoercionTests(
    ProposalStateMachineFixtureMixin, TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_provider_driven_customer_decision_requires_override_reason(self):
        proposal = self._make_proposal(proposal_status=ProposalStatus.SENT)
        with self.assertRaises(TransitionError) as cm:
            apply_proposal_transition(
                proposal,
                self.admin,
                ProposalStatus.CUSTOMER_APPROVED,
                is_override=False,  # serializer-level coercion fires
            )
        self.assertEqual(cm.exception.code, "override_reason_required")

    def test_provider_driven_sent_cancel_requires_override_reason(self):
        proposal = self._make_proposal(proposal_status=ProposalStatus.SENT)
        with self.assertRaises(TransitionError) as cm:
            apply_proposal_transition(
                proposal,
                self.admin,
                ProposalStatus.CANCELLED,
            )
        self.assertEqual(cm.exception.code, "override_reason_required")
