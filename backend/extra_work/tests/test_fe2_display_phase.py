"""
FE-2 (Addendum D §D.4) — the `display_phase` mapping and its serializer.

Three kinds of claim:

1. THE MAPPING, as a pure function — including the per-viewer split on
   PRICING_PROPOSED, the auto-start exception, the completion-approval
   read of the spawned ticket, and the invoiced terminal.
2. EXHAUSTIVENESS — every combination of status × routing × intent ×
   spawned-ticket status × invoiced × viewer maps to a known phase.
   An unmapped combination must FAIL here, never fall through to a
   blank banner in production.
3. THE FIELD on rendered responses: present on list and detail,
   per-viewer, and never writable (a client-supplied value is ignored
   by the create serializer).
"""
from __future__ import annotations

from itertools import product

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status as http
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
from extra_work.display_phase import (
    EXTRA_WORK_PHASES,
    PHASE_DONE,
    PHASE_IN_EXECUTION,
    PHASE_INVOICED,
    PHASE_SCHEDULED,
    PHASE_WAITING_PLANNING,
    PHASE_WAITING_COMPLETION_APPROVAL,
    PHASE_WAITING_CUSTOMER_APPROVAL,
    PHASE_WAITING_MANAGER_CHECK,
    PHASE_WAITING_PRICE,
    PHASE_WAITING_YOUR_APPROVAL,
    display_phase,
)
from extra_work.models import (
    ExtraWorkRequest,
    ExtraWorkRequestIntent,
    ExtraWorkRoutingDecision,
    ExtraWorkStatus,
)
from tickets.models import Ticket, TicketStatus, TicketType

User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def _phase(status, **kwargs):
    defaults = dict(
        routing_decision=ExtraWorkRoutingDecision.PROPOSAL,
        request_intent=None,
        ticket_status=None,
        is_invoiced=False,
        viewer_is_customer=True,
    )
    defaults.update(kwargs)
    return display_phase(status=status, **defaults)


class DisplayPhaseMappingTests(TestCase):
    def test_the_price_is_owed(self):
        self.assertEqual(_phase(ExtraWorkStatus.REQUESTED), PHASE_WAITING_PRICE)
        self.assertEqual(
            _phase(ExtraWorkStatus.UNDER_REVIEW), PHASE_WAITING_PRICE
        )

    def test_an_instant_request_is_scheduled_not_waiting(self):
        """All-agreed carts route INSTANT: approved by construction.
        Even mid-spawn (or awaiting a spawn retry) the honest phase is
        "scheduled" — nobody owes a price."""
        self.assertEqual(
            _phase(
                ExtraWorkStatus.REQUESTED,
                routing_decision=ExtraWorkRoutingDecision.INSTANT,
                has_real_plan=True,
            ),
            PHASE_SCHEDULED,
        )

    def test_the_quote_waits_on_whoever_is_reading(self):
        self.assertEqual(
            _phase(ExtraWorkStatus.PRICING_PROPOSED, viewer_is_customer=True),
            PHASE_WAITING_YOUR_APPROVAL,
        )
        self.assertEqual(
            _phase(ExtraWorkStatus.PRICING_PROPOSED, viewer_is_customer=False),
            PHASE_WAITING_CUSTOMER_APPROVAL,
        )

    def test_auto_start_never_waits_on_the_customer(self):
        """SoT §5.3 — "It does NOT go back to customer approval". A
        priced auto-start reads as scheduled, both viewers."""
        for viewer in (True, False):
            self.assertEqual(
                _phase(
                    ExtraWorkStatus.PRICING_PROPOSED,
                    request_intent=ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING,
                    viewer_is_customer=viewer,
                    has_real_plan=True,
                ),
                PHASE_SCHEDULED,
            )

    def test_approved_work_is_scheduled(self):
        """Once a person planned it (P-2 ruling 1)."""
        self.assertEqual(
            _phase(ExtraWorkStatus.CUSTOMER_APPROVED, has_real_plan=True),
            PHASE_SCHEDULED,
        )

    def test_execution_reads_the_spawned_ticket(self):
        self.assertEqual(
            _phase(ExtraWorkStatus.IN_PROGRESS), PHASE_IN_EXECUTION
        )
        # The internal manager check is execution to the requester...
        self.assertEqual(
            _phase(
                ExtraWorkStatus.IN_PROGRESS,
                ticket_status=TicketStatus.WAITING_MANAGER_REVIEW,
            ),
            PHASE_IN_EXECUTION,
        )
        # ...and the ticket's own "waiting for the manager" to the
        # provider (P-10 B1).
        self.assertEqual(
            _phase(
                ExtraWorkStatus.IN_PROGRESS,
                ticket_status=TicketStatus.WAITING_MANAGER_REVIEW,
                viewer_is_customer=False,
            ),
            PHASE_WAITING_MANAGER_CHECK,
        )
        # The finished work reaching the customer is its own phase.
        self.assertEqual(
            _phase(
                ExtraWorkStatus.IN_PROGRESS,
                ticket_status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            ),
            PHASE_WAITING_COMPLETION_APPROVAL,
        )

    def test_done_and_invoiced_are_two_ends(self):
        self.assertEqual(_phase(ExtraWorkStatus.COMPLETED), PHASE_DONE)
        self.assertEqual(
            _phase(ExtraWorkStatus.COMPLETED, is_invoiced=True), PHASE_INVOICED
        )

    def test_the_two_refusals(self):
        self.assertEqual(_phase(ExtraWorkStatus.CUSTOMER_REJECTED), "REJECTED")
        self.assertEqual(_phase(ExtraWorkStatus.CANCELLED), "CANCELLED")

    def test_agreed_work_nobody_planned_is_to_be_planned(self):
        """P-2 ruling 1 — "Ingepland" was the last phantom word: an
        approved meerwerk whose ticket carries no person's plan reads
        WAITING_PLANNING, and SCHEDULED only once a real plan exists.
        Both viewers read the same value; the labels differ."""
        for status_v, kwargs in (
            (ExtraWorkStatus.CUSTOMER_APPROVED, {}),
            (
                ExtraWorkStatus.PRICING_PROPOSED,
                {"request_intent": ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING},
            ),
            (
                ExtraWorkStatus.REQUESTED,
                {"routing_decision": ExtraWorkRoutingDecision.INSTANT},
            ),
        ):
            for viewer in (False, True):
                self.assertEqual(
                    _phase(status_v, viewer_is_customer=viewer, **kwargs),
                    PHASE_WAITING_PLANNING,
                )
                self.assertEqual(
                    _phase(
                        status_v, viewer_is_customer=viewer, has_real_plan=True, **kwargs
                    ),
                    PHASE_SCHEDULED,
                )

    def test_every_combination_maps_somewhere_known(self):
        """THE exhaustiveness net. The cross product of every input the
        function branches on must map into the closed phase set without
        raising — and an unknown status must raise, so a future enum
        value fails HERE instead of falling through silently."""
        statuses = [choice[0] for choice in ExtraWorkStatus.choices]
        routings = [choice[0] for choice in ExtraWorkRoutingDecision.choices]
        intents = [None] + [
            choice[0] for choice in ExtraWorkRequestIntent.choices
        ]
        ticket_statuses = [None] + [
            choice[0] for choice in TicketStatus.choices
        ]
        for combo in product(
            statuses,
            routings,
            intents,
            ticket_statuses,
            (False, True),
            (False, True),
            # P-2 ruling 1 — whether a person planned it.
            (False, True),
        ):
            status_v, routing, intent, ticket_status, invoiced, viewer, planned = combo
            with self.subTest(combo=combo):
                result = display_phase(
                    status=status_v,
                    routing_decision=routing,
                    request_intent=intent,
                    ticket_status=ticket_status,
                    is_invoiced=invoiced,
                    viewer_is_customer=viewer,
                    has_real_plan=planned,
                )
                self.assertIn(result, EXTRA_WORK_PHASES)
        with self.assertRaises(ValueError):
            display_phase(
                status="A_STATUS_NOBODY_ADDED_TO_THE_MAPPING",
                routing_decision=ExtraWorkRoutingDecision.PROPOSAL,
                request_intent=None,
                ticket_status=None,
                is_invoiced=False,
                viewer_is_customer=True,
            )


class DisplayPhaseSerializerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        suffix = "fe2dp"
        cls.company = Company.objects.create(
            name=f"Provider {suffix}", slug=f"prov-{suffix}"
        )
        cls.building = Building.objects.create(
            company=cls.company, name=f"Building {suffix}"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name=f"Customer {suffix}", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.admin = User.objects.create_user(
            email=f"admin-{suffix}@example.com",
            password=PASSWORD,
            role=UserRole.COMPANY_ADMIN,
        )
        CompanyUserMembership.objects.create(user=cls.admin, company=cls.company)
        cls.cust_user = User.objects.create_user(
            email=f"cust-{suffix}@example.com",
            password=PASSWORD,
            role=UserRole.CUSTOMER_USER,
        )
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership, building=cls.building
        )
        cls.ew = ExtraWorkRequest.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.cust_user,
            title=f"EW {suffix}",
            description="seed",
            status=ExtraWorkStatus.PRICING_PROPOSED,
        )

    def _get(self, user, path):
        client = APIClient()
        client.force_authenticate(user)
        return client.get(path)

    def test_the_same_state_reads_differently_per_viewer(self):
        mine = self._get(self.cust_user, f"/api/extra-work/{self.ew.id}/")
        self.assertEqual(mine.status_code, http.HTTP_200_OK, mine.data)
        self.assertEqual(mine.data["display_phase"], PHASE_WAITING_YOUR_APPROVAL)

        theirs = self._get(self.admin, f"/api/extra-work/{self.ew.id}/")
        self.assertEqual(
            theirs.data["display_phase"], PHASE_WAITING_CUSTOMER_APPROVAL
        )

    def test_the_list_carries_the_field_too(self):
        payload = self._get(self.cust_user, "/api/extra-work/")
        self.assertEqual(payload.status_code, http.HTTP_200_OK, payload.data)
        rows = payload.data["results"]
        self.assertTrue(rows)
        self.assertEqual(rows[0]["display_phase"], PHASE_WAITING_YOUR_APPROVAL)

    def test_the_completion_wait_reads_the_spawned_ticket(self):
        self.ew.status = ExtraWorkStatus.IN_PROGRESS
        self.ew.save(update_fields=["status"])
        Ticket.objects.create(
            company=self.company,
            customer=self.customer,
            building=self.building,
            title="Spawned",
            description="x",
            type=TicketType.REQUEST,
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            created_by=self.admin,
            extra_work_request=self.ew,
        )
        payload = self._get(self.cust_user, f"/api/extra-work/{self.ew.id}/")
        self.assertEqual(
            payload.data["display_phase"], PHASE_WAITING_COMPLETION_APPROVAL
        )

    def test_the_field_is_never_writable(self):
        """The create serializer does not know the field; a client that
        sends one gets a computed phase back, not an echo."""
        client = APIClient()
        client.force_authenticate(self.admin)
        response = client.post(
            "/api/extra-work/",
            {
                "building": self.building.id,
                "customer": self.customer.id,
                "title": "Phase cannot be set",
                "description": "x",
                "display_phase": "DONE",
                "line_items": [
                    {"custom_description": "Iets anders", "quantity": "1"}
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, http.HTTP_201_CREATED, response.data)
        self.assertNotEqual(response.data["display_phase"], "DONE")
        self.assertIn(response.data["display_phase"], EXTRA_WORK_PHASES)
