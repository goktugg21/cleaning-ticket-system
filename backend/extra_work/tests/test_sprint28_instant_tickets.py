"""
Sprint 28 Batch 7 — instant-ticket spawn backend tests.

Covers:
  * InstantSpawnHappyPathTests   — N=1, N=3 lines spawn N tickets,
                                   parent status moves to
                                   CUSTOMER_APPROVED, EW status-history
                                   row exists, initial Ticket OPEN
                                   history row exists.
  * InstantSpawnAtomicRollbackTests — mid-loop resolve_price failure
                                   rolls back the whole submission
                                   (no tickets, no parent row).
  * InstantSpawnIdempotencyTests — calling spawn_tickets_for_request
                                   twice is a no-op on the second call.
  * ProposalRoutingDoesNotSpawnTests — PROPOSAL routing creates zero
                                   tickets and keeps status REQUESTED.
  * SystemOnlyTransitionTests    — the (REQUESTED, CUSTOMER_APPROVED)
                                   transition is not reachable via the
                                   public transition endpoint by any
                                   role; the spawn service still drives
                                   it without error.
  * TicketTraceabilityTests      — Ticket.extra_work_request_item is
                                   set; SET_NULL behaviour holds when
                                   the cart line is deleted.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

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
from extra_work.instant_tickets import spawn_tickets_for_request
from extra_work.models import (
    CustomerServicePrice,
    ExtraWorkCategory,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkRoutingDecision,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
    Service,
    ServiceCategory,
)
from extra_work.state_machine import TransitionError
from tickets.models import Ticket, TicketStatus, TicketStatusHistory


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


class InstantSpawnFixtureMixin:
    """Shared fixture: provider A with one customer and a three-service
    catalog, all three services backed by an active contract row so a
    cart submitted with any subset of them resolves to INSTANT.

    The fixture intentionally creates three contract rows so the
    three-line happy-path test can submit a cart with three distinct
    services in one submission.
    """

    @classmethod
    def _setup_fixture(cls):
        cls.company = Company.objects.create(
            name="Instant Provider", slug="instant-b7"
        )
        cls.building = Building.objects.create(
            company=cls.company, name="Building-B7"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer-B7", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            "super-b7@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-b7@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

        cls.cust_user = _mk("cust-b7@example.com", UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        cls.service_cat = ServiceCategory.objects.create(name="Cat-B7")
        cls.service_a = Service.objects.create(
            category=cls.service_cat,
            name="Service A",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
            description="Reference description for Service A",
        )
        cls.service_b = Service.objects.create(
            category=cls.service_cat,
            name="Service B",
            unit_type=ExtraWorkPricingUnitType.SQUARE_METERS,
            default_unit_price=Decimal("3.50"),
        )
        cls.service_c = Service.objects.create(
            category=cls.service_cat,
            name="Service C",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            default_unit_price=Decimal("100.00"),
        )
        cls.service_unpriced = Service.objects.create(
            category=cls.service_cat,
            name="No contract",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("40.00"),
        )

        # Contract rows for A / B / C — covers the entire test horizon.
        for service in (cls.service_a, cls.service_b, cls.service_c):
            CustomerServicePrice.objects.create(
                service=service,
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

    def _submit_one_line(self, *, service=None, actor=None):
        """POST a one-line cart and return the deserialized response."""
        actor = actor or self.cust_user
        service = service or self.service_a
        payload = {
            "customer": self.customer.id,
            "building": self.building.id,
            "title": "Instant submission",
            "description": "happy path",
            "category": ExtraWorkCategory.DEEP_CLEANING,
            "line_items": [
                {
                    "service": service.id,
                    "quantity": "2.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "first line note",
                }
            ],
        }
        return self._api(actor).post(URL, payload, format="json")

    def _submit_three_line(self, *, actor=None):
        actor = actor or self.cust_user
        payload = {
            "customer": self.customer.id,
            "building": self.building.id,
            "title": "Three-line submission",
            "description": "three-line happy path",
            "category": ExtraWorkCategory.DEEP_CLEANING,
            "line_items": [
                {
                    "service": self.service_a.id,
                    "quantity": "1.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                },
                {
                    "service": self.service_b.id,
                    "quantity": "2.00",
                    "requested_date": "2026-06-16",
                    "customer_note": "",
                },
                {
                    "service": self.service_c.id,
                    "quantity": "3.00",
                    "requested_date": "2026-06-17",
                    "customer_note": "",
                },
            ],
        }
        return self._api(actor).post(URL, payload, format="json")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
class InstantSpawnHappyPathTests(InstantSpawnFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_single_line_spawns_one_ticket(self):
        before = Ticket.objects.count()
        response = self._submit_one_line()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["routing_decision"],
            ExtraWorkRoutingDecision.INSTANT,
        )
        self.assertEqual(Ticket.objects.count(), before + 1)

        ew = ExtraWorkRequest.objects.get(id=response.data["id"])
        line = ew.line_items.get()
        ticket = Ticket.objects.get(extra_work_request_item=line)
        # Ticket field defaults per master plan §6 Batch 7 bullet 2.
        self.assertEqual(ticket.status, TicketStatus.OPEN)
        self.assertEqual(ticket.priority, "NORMAL")
        self.assertEqual(ticket.company_id, ew.company_id)
        self.assertEqual(ticket.building_id, ew.building_id)
        self.assertEqual(ticket.customer_id, ew.customer_id)
        self.assertEqual(ticket.created_by_id, self.cust_user.id)
        # Title derivation: "<service name> × <quantity>".
        self.assertIn(self.service_a.name, ticket.title)
        # Description composes request.description + line note + service description.
        self.assertIn("happy path", ticket.description)
        self.assertIn("first line note", ticket.description)
        self.assertIn(
            "Reference description for Service A", ticket.description
        )
        # ticket_no is auto-generated by the model save().
        self.assertTrue(ticket.ticket_no)
        self.assertTrue(ticket.ticket_no.startswith("TCK-"))

    def test_three_lines_spawn_three_tickets(self):
        before = Ticket.objects.count()
        response = self._submit_three_line()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["routing_decision"],
            ExtraWorkRoutingDecision.INSTANT,
        )
        self.assertEqual(Ticket.objects.count(), before + 3)

        ew = ExtraWorkRequest.objects.get(id=response.data["id"])
        lines = list(ew.line_items.all().order_by("id"))
        self.assertEqual(len(lines), 3)
        for line in lines:
            self.assertEqual(line.spawned_tickets.count(), 1)

    def test_parent_status_advances_to_customer_approved(self):
        response = self._submit_one_line()
        self.assertEqual(response.status_code, 201, response.data)
        ew = ExtraWorkRequest.objects.get(id=response.data["id"])
        self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)
        self.assertIsNotNone(ew.customer_decided_at)

    def test_extra_work_status_history_row_exists(self):
        response = self._submit_one_line()
        self.assertEqual(response.status_code, 201, response.data)
        ew = ExtraWorkRequest.objects.get(id=response.data["id"])
        history = list(
            ExtraWorkStatusHistory.objects.filter(extra_work=ew).order_by(
                "created_at"
            )
        )
        # Exactly one history row for the REQUESTED -> CUSTOMER_APPROVED jump.
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].old_status, ExtraWorkStatus.REQUESTED)
        self.assertEqual(
            history[0].new_status, ExtraWorkStatus.CUSTOMER_APPROVED
        )
        self.assertEqual(history[0].changed_by_id, self.cust_user.id)
        self.assertFalse(history[0].is_override)

    def test_initial_ticket_status_history_row_exists(self):
        response = self._submit_one_line()
        self.assertEqual(response.status_code, 201, response.data)
        ew = ExtraWorkRequest.objects.get(id=response.data["id"])
        line = ew.line_items.get()
        ticket = Ticket.objects.get(extra_work_request_item=line)
        history = list(
            TicketStatusHistory.objects.filter(ticket=ticket).order_by(
                "created_at"
            )
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].new_status, TicketStatus.OPEN)
        # First history row has no prior state.
        self.assertEqual(history[0].old_status, "")
        self.assertEqual(history[0].changed_by_id, self.cust_user.id)
        self.assertFalse(history[0].is_override)


# ---------------------------------------------------------------------------
# Atomic rollback on mid-loop failure
# ---------------------------------------------------------------------------
class InstantSpawnAtomicRollbackTests(InstantSpawnFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_resolve_price_returning_none_aborts_submission(self):
        # When the serializer thinks routing="INSTANT" but the spawn
        # service then sees a None for any line, the whole submission
        # must roll back — no parent, no items, no tickets persist.
        #
        # Setup: patch the SPAWN-side resolver only (so the serializer
        # still computes routing_decision="INSTANT" against the real
        # contract rows), forcing the spawn to abort. The serializer
        # owns the atomic block, so the parent + line items + tickets
        # all roll back together.
        before_ticket = Ticket.objects.count()
        before_ew = ExtraWorkRequest.objects.count()
        before_item = ExtraWorkRequestItem.objects.count()

        client = APIClient(raise_request_exception=False)
        client.force_authenticate(user=self.cust_user)
        payload = {
            "customer": self.customer.id,
            "building": self.building.id,
            "title": "Atomic-rollback test",
            "description": "should not persist",
            "category": ExtraWorkCategory.DEEP_CLEANING,
            "line_items": [
                {
                    "service": self.service_a.id,
                    "quantity": "1.00",
                    "requested_date": "2026-06-15",
                    "customer_note": "",
                }
            ],
        }
        with patch(
            "extra_work.instant_tickets.resolve_price",
            return_value=None,
        ):
            response = client.post(URL, payload, format="json")

        # The uncaught TransitionError surfaces as a 500 (DRF's create
        # view has no try/except for non-API exceptions). The point is
        # the rollback, not the status code shape.
        self.assertGreaterEqual(response.status_code, 400)
        self.assertEqual(Ticket.objects.count(), before_ticket)
        self.assertEqual(ExtraWorkRequest.objects.count(), before_ew)
        self.assertEqual(ExtraWorkRequestItem.objects.count(), before_item)

    def test_error_code_is_instant_spawn_price_lost(self):
        # Drive the spawn service directly (not through the API) so we
        # can assert on the TransitionError code attribute.
        # Create a request + lines manually in REQUESTED + INSTANT
        # state, then force resolve_price to return None and call
        # spawn_tickets_for_request inside an atomic block.
        from django.db import transaction

        request = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title="Direct spawn test",
            description="d",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.REQUESTED,
            routing_decision=ExtraWorkRoutingDecision.INSTANT,
        )
        ExtraWorkRequestItem.objects.create(
            extra_work_request=request,
            service=self.service_a,
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=date(2026, 6, 15),
            customer_note="",
        )
        with patch(
            "extra_work.instant_tickets.resolve_price",
            return_value=None,
        ):
            try:
                with transaction.atomic():
                    spawn_tickets_for_request(
                        request, actor=self.cust_user
                    )
                raised = None
            except TransitionError as exc:
                raised = exc
        self.assertIsNotNone(raised)
        self.assertEqual(raised.code, "instant_spawn_price_lost")


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------
class InstantSpawnIdempotencyTests(InstantSpawnFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_second_call_is_noop(self):
        response = self._submit_three_line()
        self.assertEqual(response.status_code, 201, response.data)
        ew = ExtraWorkRequest.objects.get(id=response.data["id"])
        self.assertEqual(Ticket.objects.filter(
            extra_work_request_item__extra_work_request=ew
        ).count(), 3)

        # Re-call the spawn service directly. Each line already has a
        # spawned ticket, so the second call returns an empty list and
        # creates no new rows.
        before = Ticket.objects.count()
        from django.db import transaction
        with transaction.atomic():
            new_tickets = spawn_tickets_for_request(ew, actor=self.cust_user)
        self.assertEqual(new_tickets, [])
        self.assertEqual(Ticket.objects.count(), before)
        # Still exactly N tickets per line (not 2N).
        for line in ew.line_items.all():
            self.assertEqual(line.spawned_tickets.count(), 1)


# ---------------------------------------------------------------------------
# Proposal routing does not spawn
# ---------------------------------------------------------------------------
class ProposalRoutingDoesNotSpawnTests(InstantSpawnFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_proposal_creates_zero_tickets_and_status_stays_requested(self):
        # Service has no contract row ⇒ resolver returns None ⇒
        # routing_decision="PROPOSAL" ⇒ no spawn fires.
        before = Ticket.objects.count()
        response = self._submit_one_line(service=self.service_unpriced)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["routing_decision"],
            ExtraWorkRoutingDecision.PROPOSAL,
        )
        self.assertEqual(Ticket.objects.count(), before)

        ew = ExtraWorkRequest.objects.get(id=response.data["id"])
        self.assertEqual(ew.status, ExtraWorkStatus.REQUESTED)
        # No ExtraWorkStatusHistory row because the parent never
        # transitioned.
        self.assertFalse(
            ExtraWorkStatusHistory.objects.filter(extra_work=ew).exists()
        )


# ---------------------------------------------------------------------------
# System-only transition gate
# ---------------------------------------------------------------------------
class SystemOnlyTransitionTests(InstantSpawnFixtureMixin, TestCase):
    """The new (REQUESTED, CUSTOMER_APPROVED) pair MUST NOT be reachable
    via the public /transition/ endpoint by any role. The spawn service
    is the only allowed driver."""

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _make_requested_proposal_row(self) -> ExtraWorkRequest:
        # Submit a cart that routes to PROPOSAL so the row stays at
        # REQUESTED. This is the only state from which the system-only
        # transition is theoretically reachable.
        response = self._submit_one_line(service=self.service_unpriced)
        self.assertEqual(response.status_code, 201, response.data)
        return ExtraWorkRequest.objects.get(id=response.data["id"])

    def test_customer_cannot_drive_via_transition_endpoint(self):
        ew = self._make_requested_proposal_row()
        response = self._api(self.cust_user).post(
            f"/api/extra-work/{ew.id}/transition/",
            {"to_status": ExtraWorkStatus.CUSTOMER_APPROVED},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "forbidden_transition")
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.REQUESTED)

    def test_super_admin_cannot_drive_via_transition_endpoint(self):
        ew = self._make_requested_proposal_row()
        response = self._api(self.super_admin).post(
            f"/api/extra-work/{ew.id}/transition/",
            {
                "to_status": ExtraWorkStatus.CUSTOMER_APPROVED,
                "is_override": True,
                "override_reason": "trying to skip the gate",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "forbidden_transition")
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.REQUESTED)

    def test_company_admin_cannot_drive_via_transition_endpoint(self):
        ew = self._make_requested_proposal_row()
        response = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/transition/",
            {
                "to_status": ExtraWorkStatus.CUSTOMER_APPROVED,
                "is_override": True,
                "override_reason": "trying to skip the gate",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "forbidden_transition")
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.REQUESTED)

    def test_spawn_service_can_drive_the_transition(self):
        # Same state-machine pair, driven through the spawn service
        # path: this must succeed.
        from django.db import transaction

        # Build a REQUESTED row with INSTANT routing manually so we
        # know the spawn service is the only thing driving the
        # transition.
        request = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title="Spawn-service direct test",
            description="d",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.REQUESTED,
            routing_decision=ExtraWorkRoutingDecision.INSTANT,
        )
        ExtraWorkRequestItem.objects.create(
            extra_work_request=request,
            service=self.service_a,
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=date(2026, 6, 15),
            customer_note="",
        )
        with transaction.atomic():
            tickets = spawn_tickets_for_request(
                request, actor=self.cust_user
            )
        self.assertEqual(len(tickets), 1)
        request.refresh_from_db()
        self.assertEqual(request.status, ExtraWorkStatus.CUSTOMER_APPROVED)


# ---------------------------------------------------------------------------
# Traceability + SET_NULL on cart-line delete
# ---------------------------------------------------------------------------
class TicketTraceabilityTests(InstantSpawnFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_ticket_has_extra_work_request_item_fk(self):
        response = self._submit_one_line()
        self.assertEqual(response.status_code, 201, response.data)
        ew = ExtraWorkRequest.objects.get(id=response.data["id"])
        line = ew.line_items.get()
        ticket = Ticket.objects.get(extra_work_request_item=line)
        self.assertEqual(ticket.extra_work_request_item_id, line.id)

    def test_deleting_line_sets_ticket_fk_to_null(self):
        response = self._submit_one_line()
        self.assertEqual(response.status_code, 201, response.data)
        ew = ExtraWorkRequest.objects.get(id=response.data["id"])
        line = ew.line_items.get()
        ticket = Ticket.objects.get(extra_work_request_item=line)
        ticket_id = ticket.id

        line.delete()

        ticket.refresh_from_db()
        # The Ticket itself is NOT deleted; the FK goes to NULL.
        self.assertEqual(Ticket.objects.filter(id=ticket_id).count(), 1)
        self.assertIsNone(ticket.extra_work_request_item_id)
