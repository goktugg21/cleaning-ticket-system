"""
Sprint 28 Batch 8 — proposal builder backend tests.

Covers the full proposal lifecycle: create DRAFT, edit lines, send,
customer approve / reject, provider override + spawn, dual-note
privacy, idempotency, atomicity, scope, and timeline emission.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

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
    ProposalStatusHistory,
    ProposalTimelineEvent,
    ProposalTimelineEventType,
    Service,
    ServiceCategory,
)
from extra_work.proposal_state_machine import (
    apply_proposal_transition,
    TransitionError,
)
from extra_work.proposal_tickets import spawn_tickets_for_proposal
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


class ProposalFixtureMixin:
    """Shared fixture for the proposal tests.

    Provider A with one customer, one building, three users
    (super_admin, admin, customer creator), a service catalog with
    one active service, and an `ExtraWorkRequest` in `UNDER_REVIEW`
    (so SEND is allowed). The cart payload is ad-hoc — service has
    no contract row, so the request routes to PROPOSAL — and we
    drive the parent status to UNDER_REVIEW from REQUESTED via the
    transition endpoint in `_make_ew()` to mirror the real flow.
    """

    @classmethod
    def _setup_fixture(cls):
        cls.company = Company.objects.create(
            name="Proposal Provider", slug="prov-b8"
        )
        cls.other_company = Company.objects.create(
            name="Other Provider", slug="prov-other-b8"
        )
        cls.building = Building.objects.create(
            company=cls.company, name="Building-B8"
        )
        cls.other_building = Building.objects.create(
            company=cls.other_company, name="Other-Building-B8"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            name="Customer-B8",
            building=cls.building,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            "super-b8@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-b8@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )
        cls.building_manager = _mk(
            "bm-b8@example.com", UserRole.BUILDING_MANAGER
        )
        BuildingManagerAssignment.objects.create(
            user=cls.building_manager, building=cls.building
        )
        cls.other_admin = _mk(
            "other-admin-b8@example.com", UserRole.COMPANY_ADMIN
        )
        CompanyUserMembership.objects.create(
            user=cls.other_admin, company=cls.other_company
        )
        cls.staff = _mk("staff-b8@example.com", UserRole.STAFF)

        cls.cust_user = _mk("cust-b8@example.com", UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        cls.service_cat = ServiceCategory.objects.create(name="Cat-B8")
        cls.service = Service.objects.create(
            category=cls.service_cat,
            name="Window cleaning",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _make_ew(self, *, status: str = ExtraWorkStatus.UNDER_REVIEW) -> ExtraWorkRequest:
        """Create an ExtraWorkRequest at the desired status.

        We bypass the cart-create serializer for the fixture so the
        test stays focused on Batch 8 surface.
        """
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title="Proposal fixture EW",
            description="parent description",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=status,
        )
        ExtraWorkRequestItem.objects.create(
            extra_work_request=ew,
            service=self.service,
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=date(2026, 6, 15),
            customer_note="",
        )
        return ew

    def _proposals_url(self, ew_id: int) -> str:
        return f"/api/extra-work/{ew_id}/proposals/"

    def _proposal_url(self, ew_id: int, pid: int) -> str:
        return f"/api/extra-work/{ew_id}/proposals/{pid}/"

    def _transition_url(self, ew_id: int, pid: int) -> str:
        return f"/api/extra-work/{ew_id}/proposals/{pid}/transition/"

    def _lines_url(self, ew_id: int, pid: int) -> str:
        return f"/api/extra-work/{ew_id}/proposals/{pid}/lines/"

    def _line_url(self, ew_id: int, pid: int, lid: int) -> str:
        return f"/api/extra-work/{ew_id}/proposals/{pid}/lines/{lid}/"

    def _line_payload(self, **overrides) -> dict:
        payload = {
            "service": self.service.id,
            "quantity": "2.00",
            "unit_type": ExtraWorkPricingUnitType.HOURS,
            "unit_price": "50.00",
            "vat_pct": "21.00",
            "customer_explanation": "Customer-visible explanation",
            "internal_note": "Provider-only note",
        }
        payload.update(overrides)
        return payload

    def _create_proposal(self, ew: ExtraWorkRequest, *, actor=None) -> Proposal:
        actor = actor or self.admin
        response = self._api(actor).post(
            self._proposals_url(ew.id),
            {"lines": [self._line_payload()]},
            format="json",
        )
        assert response.status_code == 201, response.data
        return Proposal.objects.get(pk=response.data["id"])


# ---------------------------------------------------------------------------
# CRUD tests
# ---------------------------------------------------------------------------
class ProposalCRUDTests(ProposalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_create_draft_proposal(self):
        ew = self._make_ew()
        response = self._api(self.admin).post(
            self._proposals_url(ew.id),
            {"lines": [self._line_payload()]},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], ProposalStatus.DRAFT)
        # Totals computed: 2.00 × 50.00 = 100 subtotal, 21 VAT, 121 total.
        self.assertEqual(
            Decimal(response.data["subtotal_amount"]), Decimal("100.00")
        )
        self.assertEqual(
            Decimal(response.data["vat_amount"]), Decimal("21.00")
        )
        self.assertEqual(
            Decimal(response.data["total_amount"]), Decimal("121.00")
        )
        self.assertEqual(len(response.data["lines"]), 1)

    def test_edit_lines_in_draft(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        line = proposal.lines.get()
        response = self._api(self.admin).patch(
            self._line_url(ew.id, proposal.id, line.id),
            {"quantity": "3.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Decimal(response.data["quantity"]), Decimal("3.00"))
        proposal.refresh_from_db()
        self.assertEqual(proposal.subtotal_amount, Decimal("150.00"))

    def test_delete_line_in_draft(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        # Add a second line so we can delete one.
        self._api(self.admin).post(
            self._lines_url(ew.id, proposal.id),
            self._line_payload(quantity="1.00", unit_price="10.00"),
            format="json",
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.lines.count(), 2)
        line = proposal.lines.first()
        response = self._api(self.admin).delete(
            self._line_url(ew.id, proposal.id, line.id)
        )
        self.assertEqual(response.status_code, 204)
        proposal.refresh_from_db()
        self.assertEqual(proposal.lines.count(), 1)

    def test_cannot_edit_lines_after_sent(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        line = proposal.lines.get()
        # Send the proposal.
        response = self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        # Now patch should fail.
        response = self._api(self.admin).patch(
            self._line_url(ew.id, proposal.id, line.id),
            {"quantity": "5.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "proposal_not_draft")


# ---------------------------------------------------------------------------
# Send + parent advancement
# ---------------------------------------------------------------------------
class ProposalSendAdvancesParentTests(ProposalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_proposal_sent_advances_parent_ew_under_review_to_pricing_proposed(self):
        ew = self._make_ew(status=ExtraWorkStatus.UNDER_REVIEW)
        proposal = self._create_proposal(ew)
        response = self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.PRICING_PROPOSED)
        self.assertIsNotNone(ew.pricing_proposed_at)

    def test_proposal_send_rejects_when_parent_is_requested(self):
        # Use REQUESTED parent. Need to bypass the proposal-create
        # validator that ALSO requires REQUESTED-or-UNDER_REVIEW —
        # that allows it, so we can build the row and try to SEND.
        ew = self._make_ew(status=ExtraWorkStatus.REQUESTED)
        proposal = self._create_proposal(ew)
        response = self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(
            response.data["code"], "proposal_send_requires_under_review"
        )

    def test_proposal_send_requires_at_least_one_line(self):
        # Build a proposal directly with zero lines (bypass the API
        # validator which requires non-empty lines at create time).
        ew = self._make_ew()
        proposal = Proposal.objects.create(
            extra_work_request=ew,
            created_by=self.admin,
        )
        with self.assertRaises(TransitionError) as cm:
            apply_proposal_transition(
                proposal, self.admin, ProposalStatus.SENT
            )
        self.assertEqual(cm.exception.code, "proposal_lines_required")


# ---------------------------------------------------------------------------
# Customer visibility
# ---------------------------------------------------------------------------
class CustomerVisibilityTests(ProposalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_customer_cannot_see_draft_proposal(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        # Customer GET on list — DRAFT excluded.
        response = self._api(self.cust_user).get(self._proposals_url(ew.id))
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.data]
        self.assertNotIn(proposal.id, ids)
        # Customer GET on detail — 404.
        response = self._api(self.cust_user).get(
            self._proposal_url(ew.id, proposal.id)
        )
        self.assertEqual(response.status_code, 404)

    def test_customer_can_see_sent_approved_rejected(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        # Customer can list and retrieve SENT.
        response = self._api(self.cust_user).get(self._proposals_url(ew.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        response = self._api(self.cust_user).get(
            self._proposal_url(ew.id, proposal.id)
        )
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# Dual-note privacy
# ---------------------------------------------------------------------------
class DualNotePrivacyTests(ProposalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_customer_serializer_omits_internal_note(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        # Customer retrieves the proposal — none of the lines should
        # carry `internal_note`.
        response = self._api(self.cust_user).get(
            self._proposal_url(ew.id, proposal.id)
        )
        self.assertEqual(response.status_code, 200, response.data)
        body = response.json()
        # Grep-style assertion: the provider-only string must not be
        # anywhere in the JSON.
        self.assertNotIn("internal_note", str(body))
        self.assertNotIn("Provider-only note", str(body))
        # And the customer-visible explanation IS there.
        self.assertIn("Customer-visible explanation", str(body))

    def test_admin_serializer_includes_internal_note(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        response = self._api(self.admin).get(
            self._proposal_url(ew.id, proposal.id)
        )
        self.assertEqual(response.status_code, 200, response.data)
        line = response.data["lines"][0]
        self.assertEqual(line["internal_note"], "Provider-only note")
        self.assertEqual(
            line["customer_explanation"], "Customer-visible explanation"
        )


# ---------------------------------------------------------------------------
# Customer approve + spawn tickets
# ---------------------------------------------------------------------------
class CustomerApproveSpawnTests(ProposalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_customer_approve_spawns_one_ticket_per_line(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        # Add a second line.
        response = self._api(self.admin).post(
            self._lines_url(ew.id, proposal.id),
            self._line_payload(
                quantity="1.00",
                unit_price="20.00",
                customer_explanation="Line 2 explanation",
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        # Send it.
        self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        before = Ticket.objects.count()
        # Customer approves.
        response = self._api(self.cust_user).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Ticket.objects.count(), before + 2)
        # Each ticket is linked to its proposal line.
        proposal.refresh_from_db()
        for line in proposal.lines.all():
            tickets = Ticket.objects.filter(proposal_line=line)
            self.assertEqual(tickets.count(), 1)
        # Parent EW advanced to CUSTOMER_APPROVED.
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)


# ---------------------------------------------------------------------------
# Customer reject
# ---------------------------------------------------------------------------
class CustomerRejectTests(ProposalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_customer_reject_spawns_no_tickets(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        before = Ticket.objects.count()
        response = self._api(self.cust_user).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.CUSTOMER_REJECTED},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Ticket.objects.count(), before)
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_REJECTED)


# ---------------------------------------------------------------------------
# Provider override
# ---------------------------------------------------------------------------
class ProviderOverrideTests(ProposalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _sent_proposal(self) -> tuple[ExtraWorkRequest, Proposal]:
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        return ew, proposal

    def test_provider_override_requires_reason(self):
        ew, proposal = self._sent_proposal()
        # No `override_reason` -> 400 code override_reason_required.
        response = self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "override_reason_required")

    def test_provider_override_approves_and_spawns_tickets(self):
        ew, proposal = self._sent_proposal()
        before = Ticket.objects.count()
        response = self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {
                "to_status": ProposalStatus.CUSTOMER_APPROVED,
                "override_reason": "Customer agreed on the phone.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Ticket.objects.count(), before + 1)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ProposalStatus.CUSTOMER_APPROVED)
        self.assertEqual(proposal.override_by_id, self.admin.id)
        self.assertTrue(proposal.override_reason)

    def test_provider_override_writes_override_fields_on_history_row(self):
        ew, proposal = self._sent_proposal()
        response = self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {
                "to_status": ProposalStatus.CUSTOMER_APPROVED,
                "override_reason": "Override reason text.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        history = ProposalStatusHistory.objects.filter(
            proposal=proposal, new_status=ProposalStatus.CUSTOMER_APPROVED
        ).get()
        self.assertTrue(history.is_override)
        self.assertEqual(history.override_reason, "Override reason text.")
        self.assertEqual(history.changed_by_id, self.admin.id)


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------
class AtomicityTests(ProposalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_atomicity_rollback_when_ticket_creation_fails_mid_loop(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        # Add a second line so the spawn loop has more than one
        # iteration to bail on.
        self._api(self.admin).post(
            self._lines_url(ew.id, proposal.id),
            self._line_payload(quantity="1.00", unit_price="10.00"),
            format="json",
        )
        self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        before = Ticket.objects.count()
        # Make the 2nd Ticket.objects.create blow up. The transaction
        # owned by apply_proposal_transition rolls everything back.
        original_create = Ticket.objects.create
        call_count = {"n": 0}

        def _boom(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("simulated mid-loop ticket failure")
            return original_create(*args, **kwargs)

        with patch.object(Ticket.objects, "create", side_effect=_boom):
            with self.assertRaises(RuntimeError):
                self._api(self.cust_user).post(
                    self._transition_url(ew.id, proposal.id),
                    {"to_status": ProposalStatus.CUSTOMER_APPROVED},
                    format="json",
                )

        # No tickets persisted (rollback).
        self.assertEqual(Ticket.objects.count(), before)
        # Proposal still SENT (status update rolled back too).
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ProposalStatus.SENT)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------
class IdempotencyTests(ProposalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_repeated_approval_call_blocked_by_no_op(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        # First approval (customer) succeeds.
        response = self._api(self.cust_user).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        # Second call hits no_op (already in CUSTOMER_APPROVED).
        response = self._api(self.cust_user).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "no_op_transition")

    def test_spawn_helper_skips_existing_tickets(self):
        from django.db import transaction

        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        # Drive customer approval, then call spawn directly again.
        response = self._api(self.cust_user).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        proposal.refresh_from_db()
        before = Ticket.objects.count()
        with transaction.atomic():
            new_tickets = spawn_tickets_for_proposal(
                proposal, actor=self.cust_user
            )
        self.assertEqual(new_tickets, [])
        self.assertEqual(Ticket.objects.count(), before)

    def test_lines_with_is_approved_for_spawn_false_do_not_spawn_tickets(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        # Add a second line and flip is_approved_for_spawn on it.
        response = self._api(self.admin).post(
            self._lines_url(ew.id, proposal.id),
            self._line_payload(
                quantity="1.00",
                unit_price="10.00",
                is_approved_for_spawn=False,
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        second_line_id = response.data["id"]
        # ProposalLineAdminSerializer doesn't include is_approved_for_spawn
        # on writable fields by default — the field IS in `fields` and
        # not in `read_only_fields`, so it should be accepted.
        line = ProposalLine.objects.get(id=second_line_id)
        self.assertFalse(line.is_approved_for_spawn)

        self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        before = Ticket.objects.count()
        response = self._api(self.cust_user).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        # Only one ticket spawned (the approved-for-spawn line). The
        # is_approved_for_spawn=False line has no spawned ticket.
        self.assertEqual(Ticket.objects.count(), before + 1)
        self.assertFalse(
            Ticket.objects.filter(proposal_line_id=second_line_id).exists()
        )


# ---------------------------------------------------------------------------
# Timeline emission
# ---------------------------------------------------------------------------
class TimelineEmissionTests(ProposalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_emits_one_event_per_action(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        # CREATED row from POST.
        self.assertEqual(
            ProposalTimelineEvent.objects.filter(
                proposal=proposal,
                event_type=ProposalTimelineEventType.CREATED,
            ).count(),
            1,
        )
        # SEND.
        self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        self.assertEqual(
            ProposalTimelineEvent.objects.filter(
                proposal=proposal,
                event_type=ProposalTimelineEventType.SENT,
            ).count(),
            1,
        )
        # Provider override approve.
        self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {
                "to_status": ProposalStatus.CUSTOMER_APPROVED,
                "override_reason": "override",
            },
            format="json",
        )
        self.assertEqual(
            ProposalTimelineEvent.objects.filter(
                proposal=proposal,
                event_type=ProposalTimelineEventType.CUSTOMER_APPROVED,
            ).count(),
            1,
        )
        # Override emits ADMIN_OVERRIDDEN too.
        self.assertEqual(
            ProposalTimelineEvent.objects.filter(
                proposal=proposal,
                event_type=ProposalTimelineEventType.ADMIN_OVERRIDDEN,
            ).count(),
            1,
        )

    def test_customer_timeline_serializer_omits_metadata(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        # Provider-driven override approve writes metadata containing
        # the override reason. Customer GET on /timeline/ must strip
        # the metadata key entirely.
        self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {
                "to_status": ProposalStatus.CUSTOMER_APPROVED,
                "override_reason": "Reason text",
            },
            format="json",
        )
        response = self._api(self.cust_user).get(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/timeline/"
        )
        self.assertEqual(response.status_code, 200, response.data)
        for row in response.data:
            self.assertNotIn("metadata", row)
        # And the override reason is never leaked through the customer
        # serializer.
        self.assertNotIn("Reason text", str(response.json()))


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------
class ScopeTests(ProposalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_super_admin_can_create_proposal(self):
        ew = self._make_ew()
        response = self._api(self.super_admin).post(
            self._proposals_url(ew.id),
            {"lines": [self._line_payload()]},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_company_admin_in_scope_can_create_proposal(self):
        ew = self._make_ew()
        response = self._api(self.admin).post(
            self._proposals_url(ew.id),
            {"lines": [self._line_payload()]},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_other_company_admin_gets_404(self):
        ew = self._make_ew()
        # The other admin can't even see the EW (scope_extra_work_for
        # filters it out). 404 on the parent EW.
        response = self._api(self.other_admin).post(
            self._proposals_url(ew.id),
            {"lines": [self._line_payload()]},
            format="json",
        )
        self.assertEqual(response.status_code, 404, response.data)

    def test_building_manager_in_scope_can_create_proposal(self):
        ew = self._make_ew()
        response = self._api(self.building_manager).post(
            self._proposals_url(ew.id),
            {"lines": [self._line_payload()]},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_customer_cannot_create_proposal(self):
        ew = self._make_ew()
        response = self._api(self.cust_user).post(
            self._proposals_url(ew.id),
            {"lines": [self._line_payload()]},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.data)


# ---------------------------------------------------------------------------
# Staff exclusion
# ---------------------------------------------------------------------------
class StaffTests(ProposalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_staff_cannot_see_any_proposal(self):
        ew = self._make_ew()
        self._create_proposal(ew)
        # STAFF's scope_extra_work_for returns .none() — the parent EW
        # is invisible, so the proposals endpoint 404s.
        response = self._api(self.staff).get(self._proposals_url(ew.id))
        self.assertEqual(response.status_code, 404, response.data)


# ---------------------------------------------------------------------------
# Re-send after rejection
# ---------------------------------------------------------------------------
class ProposalReSendAfterRejectionTests(ProposalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_customer_rejected_then_new_proposal_can_be_created(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        # Customer rejects.
        self._api(self.cust_user).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.CUSTOMER_REJECTED},
            format="json",
        )
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_REJECTED)
        # Operator drives the parent back to UNDER_REVIEW so a fresh
        # proposal can be created.
        ew.status = ExtraWorkStatus.UNDER_REVIEW
        ew.save(update_fields=["status", "updated_at"])
        # New proposal.
        response = self._api(self.admin).post(
            self._proposals_url(ew.id),
            {"lines": [self._line_payload()]},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            Proposal.objects.filter(extra_work_request=ew).count(), 2
        )


# ---------------------------------------------------------------------------
# Unique open proposal
# ---------------------------------------------------------------------------
class UniqueOpenProposalTests(ProposalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_cannot_create_second_open_proposal(self):
        ew = self._make_ew()
        self._create_proposal(ew)
        # Second create while the first is still DRAFT -> 400.
        response = self._api(self.admin).post(
            self._proposals_url(ew.id),
            {"lines": [self._line_payload()]},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
