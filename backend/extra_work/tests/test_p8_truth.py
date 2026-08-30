"""
P-8R — the truth round. The audit's backend truths, pinned.

Web-Claude's audit of the P-7 build (2026-08-30) named four things the
server does that the screen must keep true. Each class below pins one:

  * `PlanDoorStartIsExplicitTests`     — A2. `POST /extra-work/<id>/plan/`
    (and bulk-plan) writes a plan and does NOT start the work unless the
    body says `start: true`. Under attack (an unpriced quote work with a
    crew and a date) even `start: true` cannot start it.
  * `QuoteDecisionOnBehalfTests`       — A4. A provider approving or
    rejecting a SENT quote is the on-behalf override the state machine
    says it is: `override_reason_required` without a reason, on both the
    proposal door and the EW transition door.
  * `ListNeverHidesAServerRowTests`    — A1. Every row the list endpoint
    returns carries a `display_phase` from the closed phase set, and a
    row that already has an operational ticket is IN the list. The page
    buckets rows by exactly this field, so a non-empty server list can
    never bucket to all-zero chips.
  * `AgreedPriceRoutesInstantTests`    — A6. A cart whose every line has
    an agreed price routes INSTANT and is planned right away (a ticket
    exists, the phase is past WAITING_PRICE) — for the customer AND for
    the provider creating on their behalf.
"""
from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import UserRole
from buildings.models import BuildingStaffVisibility
from extra_work.display_phase import EXTRA_WORK_PHASES, PHASE_WAITING_PRICE
from extra_work.models import (
    ExtraWorkAssignment,
    ExtraWorkAssignmentRole,
    ExtraWorkCategory,
    ExtraWorkRequest,
    ExtraWorkRequestIntent,
    ExtraWorkRoutingDecision,
    ExtraWorkStatus,
)
from extra_work.proposal_state_machine import ProposalStatus
from test_utils import TenantFixtureMixin
from tickets.models import Ticket

from .test_sprint28_instant_tickets import InstantSpawnFixtureMixin
from .test_sprint28_proposal import ProposalFixtureMixin


LIST_URL = "/api/extra-work/"
BULK_PLAN_URL = "/api/extra-work/bulk-plan/"


def plan_url(request_id: int) -> str:
    return f"/api/extra-work/{request_id}/plan/"


def transition_url(request_id: int) -> str:
    return f"/api/extra-work/{request_id}/transition/"


# ---------------------------------------------------------------------------
# A2 — the plan door does not start by default
# ---------------------------------------------------------------------------
class PlanDoorStartIsExplicitTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.worker = self.make_user("p8-worker@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.worker, building=self.building
        )

    def make_ew(self, **kwargs) -> ExtraWorkRequest:
        defaults = dict(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="P-8 plan door",
            description="x",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
        )
        defaults.update(kwargs)
        return ExtraWorkRequest.objects.create(**defaults)

    def crew(self, ew):
        for role in (ExtraWorkAssignmentRole.WORKER, ExtraWorkAssignmentRole.MANAGER):
            ExtraWorkAssignment.objects.create(
                extra_work_request=ew,
                user=self.worker if role == ExtraWorkAssignmentRole.WORKER else self.company_admin,
                role=role,
                assigned_by=self.super_admin,
            )

    def plan(self, ew, body):
        self.authenticate(self.company_admin)
        return self.client.post(plan_url(ew.id), body, format="json")

    def test_a_plan_without_start_is_a_plan_not_a_start(self):
        ew = self.make_ew()
        start = timezone.localdate() + timedelta(days=3)

        response = self.plan(
            ew,
            {"provider_planned_date": start.isoformat(), "budget_hours": "4.00"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(response.data["plan"]["started"])
        self.assertEqual(response.data["plan"]["start_skipped"], "start_not_requested")
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)
        self.assertEqual(ew.provider_planned_date, start)

    def test_start_true_starts_approved_work(self):
        ew = self.make_ew()
        response = self.plan(ew, {"budget_hours": "4.00", "start": True})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data["plan"]["started"])
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.IN_PROGRESS)

    def test_start_false_is_honoured(self):
        ew = self.make_ew()
        response = self.plan(ew, {"budget_hours": "4.00", "start": False})
        self.assertFalse(response.data["plan"]["started"])
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)

    def test_unpriced_quote_work_with_a_crew_cannot_be_started_through_the_plan_door(self):
        """The audit's attack: a REQUEST_QUOTE work nobody has priced,
        with people and a date on it. The plan lands; the start is
        refused as `invalid_transition` even when asked for."""
        ew = self.make_ew(
            status=ExtraWorkStatus.REQUESTED,
            request_intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
        )
        self.crew(ew)
        start = timezone.localdate() + timedelta(days=3)

        for body in (
            {"provider_planned_date": start.isoformat(), "budget_hours": "2.00"},
            {"provider_planned_date": start.isoformat(), "budget_hours": "2.00", "start": True},
        ):
            with self.subTest(body=body):
                response = self.plan(ew, body)
                self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
                self.assertFalse(response.data["plan"]["started"])
                ew.refresh_from_db()
                self.assertEqual(ew.status, ExtraWorkStatus.REQUESTED)
                self.assertEqual(ew.provider_planned_date, start)
        self.assertEqual(response.data["plan"]["start_skipped"], "invalid_transition")

    def test_bulk_plan_without_start_does_not_start(self):
        ew_a = self.make_ew(title="A")
        ew_b = self.make_ew(title="B")
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_PLAN_URL,
            {"requests": [ew_a.id, ew_b.id], "budget_hours": "2.00"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        for row in response.data["results"]:
            self.assertFalse(row["started"])
            self.assertEqual(row["start_skipped"], "start_not_requested")
        for ew in (ew_a, ew_b):
            ew.refresh_from_db()
            self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)


# ---------------------------------------------------------------------------
# A4 — deciding a quote on the customer's behalf needs a reason
# ---------------------------------------------------------------------------
class QuoteDecisionOnBehalfTests(ProposalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _sent(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        response = self._api(self.admin).post(
            self._transition_url(ew.id, proposal.id),
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        return ew, proposal

    def test_provider_approve_and_reject_on_the_proposal_door_need_a_reason(self):
        for target in (ProposalStatus.CUSTOMER_APPROVED, ProposalStatus.CUSTOMER_REJECTED):
            with self.subTest(target=target):
                ew, proposal = self._sent()
                response = self._api(self.admin).post(
                    self._transition_url(ew.id, proposal.id),
                    {"to_status": target},
                    format="json",
                )
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(response.data["code"], "override_reason_required")
                # Even an explicit `is_override` without the words is refused.
                response = self._api(self.admin).post(
                    self._transition_url(ew.id, proposal.id),
                    {"to_status": target, "is_override": True, "override_reason": "  "},
                    format="json",
                )
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(response.data["code"], "override_reason_required")

    def test_provider_decision_on_the_ew_transition_door_needs_a_reason(self):
        ew = self._make_ew(status=ExtraWorkStatus.PRICING_PROPOSED)
        for target in (ExtraWorkStatus.CUSTOMER_APPROVED, ExtraWorkStatus.CUSTOMER_REJECTED):
            with self.subTest(target=target):
                response = self._api(self.admin).post(
                    transition_url(ew.id), {"to_status": target}, format="json"
                )
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(response.data["code"], "override_reason_required")
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.PRICING_PROPOSED)


# ---------------------------------------------------------------------------
# A1 — the list carries a phase for every row, and hides none
# ---------------------------------------------------------------------------
class ListNeverHidesAServerRowTests(TenantFixtureMixin, APITestCase):
    def make_ew(self, **kwargs) -> ExtraWorkRequest:
        defaults = dict(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="P-8 list row",
            description="x",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.REQUESTED,
        )
        defaults.update(kwargs)
        return ExtraWorkRequest.objects.create(**defaults)

    def test_every_row_has_a_closed_set_phase_and_started_rows_are_listed(self):
        waiting = self.make_ew(title="waiting")
        approved = self.make_ew(title="approved", status=ExtraWorkStatus.CUSTOMER_APPROVED)
        started = self.make_ew(title="started", status=ExtraWorkStatus.IN_PROGRESS)
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Operational ticket",
            description="x",
            extra_work_request=started,
        )

        self.authenticate(self.super_admin)
        response = self.client.get(LIST_URL, {"page_size": 100})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        rows = {row["id"]: row for row in response.data["results"]}
        self.assertEqual(response.data["count"], len(rows))
        for ew in (waiting, approved, started):
            self.assertIn(ew.id, rows, f"{ew.title} missing from the list")
            self.assertIn(rows[ew.id]["display_phase"], EXTRA_WORK_PHASES)
        self.assertTrue(rows[started.id]["has_operational_ticket"])
        self.assertFalse(rows[waiting.id]["has_operational_ticket"])
        self.assertEqual(rows[waiting.id]["display_phase"], PHASE_WAITING_PRICE)


# ---------------------------------------------------------------------------
# A6 — an agreed price routes instant, for both creators
# ---------------------------------------------------------------------------
class AgreedPriceRoutesInstantTests(InstantSpawnFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _submit(self, *, service, actor):
        """One agreed-priced line. The date is the request's
        `preferred_date` — a per-line `requested_date` is refused since
        the one-date rule (`line_requested_date_not_accepted`)."""
        payload = {
            "customer": self.customer.id,
            "building": self.building.id,
            "title": "P-8 agreed cart",
            "description": "agreed-only",
            "category": ExtraWorkCategory.DEEP_CLEANING,
            "preferred_date": "2026-06-15",
            "line_items": [{"service": service.id, "quantity": "2.00", "customer_note": ""}],
        }
        return self._api(actor).post(LIST_URL, payload, format="json")

    def _assert_instant(self, response):
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["routing_decision"], ExtraWorkRoutingDecision.INSTANT)
        self.assertEqual(response.data["status"], ExtraWorkStatus.CUSTOMER_APPROVED)
        self.assertNotEqual(response.data["display_phase"], PHASE_WAITING_PRICE)
        self.assertIn(response.data["display_phase"], EXTRA_WORK_PHASES)
        ew = ExtraWorkRequest.objects.get(id=response.data["id"])
        self.assertEqual(Ticket.objects.filter(extra_work_request=ew).count(), 1)
        # The list shows it with the same phase, not as a quote.
        listed = self._api(self.super_admin).get(LIST_URL, {"page_size": 100})
        row = next(r for r in listed.data["results"] if r["id"] == ew.id)
        self.assertEqual(row["display_phase"], response.data["display_phase"])
        self.assertTrue(row["has_operational_ticket"])

    def test_customer_agreed_only_cart_routes_instant(self):
        self._assert_instant(self._submit(service=self.service_a, actor=self.cust_user))

    def test_provider_agreed_only_cart_routes_instant(self):
        self._assert_instant(self._submit(service=self.service_a, actor=self.admin))

    def test_an_unpriced_line_waits_for_a_price(self):
        response = self._submit(service=self.service_unpriced, actor=self.cust_user)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["routing_decision"], ExtraWorkRoutingDecision.PROPOSAL)
        self.assertEqual(response.data["display_phase"], PHASE_WAITING_PRICE)
        ew = ExtraWorkRequest.objects.get(id=response.data["id"])
        self.assertEqual(Ticket.objects.filter(extra_work_request=ew).count(), 0)
