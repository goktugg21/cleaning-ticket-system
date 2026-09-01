"""
P-10 B1 — the phase words are the ticket's own words.

The owner: "Don't tickets have their own statuses? Why aren't you using
them?" The Approved tab of the Extra work list now reads the spawned
ticket's status words, and the one state that had no phase of its own —
the crew reported the work done, the manager has not checked it yet
(ticket WAITING_MANAGER_REVIEW) — becomes `WAITING_MANAGER_CHECK` for
the provider. The customer keeps IN_EXECUTION: the internal check is
execution as far as the requester is concerned (`display_phase.py`).

Pinned here:

  (a) the pure mapping, both viewers on the same row, and the phase's
      membership in the closed set;
  (b) the rendered field: list and detail, provider vs customer, on a
      fixture whose spawned ticket sits at WAITING_MANAGER_REVIEW;
  (c) the tab placement: the P-9 mirror of the frontend's one tab table
      puts the phase on the Approved tab (the frontend's copy is checked
      by the compiler, the mirror by `test_p9_tabs`).
"""
from __future__ import annotations

from rest_framework import status as http
from rest_framework.test import APITestCase

from extra_work.display_phase import (
    EXTRA_WORK_PHASES,
    PHASE_IN_EXECUTION,
    PHASE_WAITING_COMPLETION_APPROVAL,
    PHASE_WAITING_MANAGER_CHECK,
    display_phase,
)
from extra_work.models import (
    ExtraWorkRequest,
    ExtraWorkRequestIntent,
    ExtraWorkRoutingDecision,
    ExtraWorkStatus,
)
from extra_work.tests.test_p9_tabs import TAB_APPROVED, TAB_OF_PHASE
from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus


def _phase(viewer_is_customer: bool, ticket_status=TicketStatus.WAITING_MANAGER_REVIEW):
    return display_phase(
        status=ExtraWorkStatus.IN_PROGRESS,
        routing_decision=ExtraWorkRoutingDecision.PROPOSAL,
        request_intent=None,
        ticket_status=ticket_status,
        is_invoiced=False,
        viewer_is_customer=viewer_is_customer,
        has_real_plan=True,
    )


class ManagerCheckPhaseMappingTests(APITestCase):
    def test_the_provider_reads_the_tickets_own_word(self):
        self.assertEqual(_phase(viewer_is_customer=False), PHASE_WAITING_MANAGER_CHECK)

    def test_the_customer_still_reads_execution(self):
        """The internal check is execution to the requester — the same
        row, the other viewer."""
        self.assertEqual(_phase(viewer_is_customer=True), PHASE_IN_EXECUTION)

    def test_the_phase_is_in_the_closed_set(self):
        self.assertIn(PHASE_WAITING_MANAGER_CHECK, EXTRA_WORK_PHASES)

    def test_only_the_manager_review_state_maps_to_it(self):
        """Every other ticket status under IN_PROGRESS keeps its P-9
        reading: the customer wait is its own phase, the rest execution."""
        for viewer in (False, True):
            self.assertEqual(
                _phase(viewer, TicketStatus.WAITING_CUSTOMER_APPROVAL),
                PHASE_WAITING_COMPLETION_APPROVAL,
            )
            for ticket_status in (
                TicketStatus.IN_PROGRESS,
                TicketStatus.ACKNOWLEDGED,
                TicketStatus.ON_HOLD,
                None,
            ):
                self.assertEqual(_phase(viewer, ticket_status), PHASE_IN_EXECUTION)

    def test_the_phase_sits_on_the_approved_tab(self):
        self.assertEqual(TAB_OF_PHASE[PHASE_WAITING_MANAGER_CHECK], TAB_APPROVED)


class ManagerCheckPhaseRenderedTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # Asked by the customer user, so their own scope holds the row.
        self.ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="P-10 reported done",
            description="x",
            status=ExtraWorkStatus.IN_PROGRESS,
            routing_decision=ExtraWorkRoutingDecision.PROPOSAL,
            request_intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
        )
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Ticket for P-10 reported done",
            description="x",
            extra_work_request=self.ew,
            status=TicketStatus.WAITING_MANAGER_REVIEW,
        )

    def _detail(self, user):
        self.authenticate(user)
        response = self.client.get(f"/api/extra-work/{self.ew.id}/")
        self.assertEqual(response.status_code, http.HTTP_200_OK, response.data)
        return response.data

    def _list_row(self, user):
        self.authenticate(user)
        response = self.client.get("/api/extra-work/", {"page_size": 100})
        self.assertEqual(response.status_code, http.HTTP_200_OK, response.data)
        rows = {row["id"]: row for row in response.data["results"]}
        self.assertIn(self.ew.id, rows)
        return rows[self.ew.id]

    def test_provider_readers_get_the_manager_check_phase(self):
        for user in (self.super_admin, self.company_admin):
            self.assertEqual(
                self._detail(user)["display_phase"], PHASE_WAITING_MANAGER_CHECK
            )
            self.assertEqual(
                self._list_row(user)["display_phase"], PHASE_WAITING_MANAGER_CHECK
            )

    def test_the_customer_reader_gets_execution_on_the_same_row(self):
        self.assertEqual(
            self._detail(self.customer_user)["display_phase"], PHASE_IN_EXECUTION
        )
        self.assertEqual(
            self._list_row(self.customer_user)["display_phase"], PHASE_IN_EXECUTION
        )

    def test_the_manager_check_ends_when_the_ticket_moves_on(self):
        Ticket.objects.filter(extra_work_request=self.ew).update(
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL
        )
        self.assertEqual(
            self._detail(self.super_admin)["display_phase"],
            PHASE_WAITING_COMPLETION_APPROVAL,
        )
