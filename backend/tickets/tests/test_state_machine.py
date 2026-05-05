from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin
from tickets.models import TicketStatus, TicketStatusHistory
from tickets.state_machine import TransitionError, apply_transition


class TicketStateMachineTests(TenantFixtureMixin, APITestCase):
    def test_staff_transition_creates_history(self):
        self.authenticate(self.manager)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {"to_status": TicketStatus.IN_PROGRESS, "note": "starting"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            TicketStatusHistory.objects.filter(
                ticket=self.ticket,
                old_status=TicketStatus.OPEN,
                new_status=TicketStatus.IN_PROGRESS,
                changed_by=self.manager,
            ).exists()
        )

    def test_disallowed_transition_returns_error(self):
        self.authenticate(self.manager)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {"to_status": TicketStatus.CLOSED},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_approval_stamps_resolved_at(self):
        ticket = apply_transition(self.ticket, self.manager, TicketStatus.IN_PROGRESS)
        ticket = apply_transition(ticket, self.manager, TicketStatus.WAITING_CUSTOMER_APPROVAL)

        self.assertIsNone(ticket.resolved_at)

        ticket = apply_transition(ticket, self.customer_user, TicketStatus.APPROVED)

        self.assertIsNotNone(ticket.resolved_at)
        self.assertEqual(ticket.resolved_at, ticket.approved_at)

    def test_company_admin_can_approve_in_company_scope(self):
        ticket = self.move_ticket_to_customer_approval()

        ticket = apply_transition(ticket, self.company_admin, TicketStatus.APPROVED)

        self.assertEqual(ticket.status, TicketStatus.APPROVED)
        self.assertIsNotNone(ticket.approved_at)
        self.assertEqual(ticket.resolved_at, ticket.approved_at)
        self.assertTrue(
            TicketStatusHistory.objects.filter(
                ticket=ticket,
                old_status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
                new_status=TicketStatus.APPROVED,
                changed_by=self.company_admin,
            ).exists()
        )

    def test_company_admin_can_reject_in_company_scope(self):
        ticket = self.move_ticket_to_customer_approval()

        ticket = apply_transition(
            ticket,
            self.company_admin,
            TicketStatus.REJECTED,
            note="Customer did not respond within SLA window.",
        )

        self.assertEqual(ticket.status, TicketStatus.REJECTED)
        self.assertIsNotNone(ticket.rejected_at)
        history_row = TicketStatusHistory.objects.get(
            ticket=ticket,
            old_status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            new_status=TicketStatus.REJECTED,
            changed_by=self.company_admin,
        )
        self.assertEqual(
            history_row.note,
            "Customer did not respond within SLA window.",
        )

    def test_company_admin_cannot_approve_outside_company_scope(self):
        ticket = self.move_ticket_to_customer_approval()

        with self.assertRaises(TransitionError) as ctx:
            apply_transition(ticket, self.other_company_admin, TicketStatus.APPROVED)

        self.assertEqual(ctx.exception.code, "forbidden_transition")

    def test_building_manager_still_cannot_approve(self):
        ticket = self.move_ticket_to_customer_approval()

        with self.assertRaises(TransitionError) as ctx:
            apply_transition(ticket, self.manager, TicketStatus.APPROVED)

        self.assertEqual(ctx.exception.code, "forbidden_transition")

    def test_reapproval_overwrites_resolved_at(self):
        ticket = apply_transition(self.ticket, self.manager, TicketStatus.IN_PROGRESS)
        ticket = apply_transition(ticket, self.manager, TicketStatus.WAITING_CUSTOMER_APPROVAL)
        ticket = apply_transition(ticket, self.customer_user, TicketStatus.REJECTED)

        ticket = apply_transition(ticket, self.manager, TicketStatus.IN_PROGRESS)
        ticket = apply_transition(ticket, self.manager, TicketStatus.WAITING_CUSTOMER_APPROVAL)
        ticket = apply_transition(ticket, self.customer_user, TicketStatus.APPROVED)

        first_resolved = ticket.resolved_at
        self.assertIsNotNone(first_resolved)

        ticket = apply_transition(ticket, self.company_admin, TicketStatus.CLOSED)
        ticket = apply_transition(ticket, self.company_admin, TicketStatus.REOPENED_BY_ADMIN)
        ticket = apply_transition(ticket, self.manager, TicketStatus.IN_PROGRESS)
        ticket = apply_transition(ticket, self.manager, TicketStatus.WAITING_CUSTOMER_APPROVAL)
        ticket = apply_transition(ticket, self.customer_user, TicketStatus.APPROVED)

        self.assertIsNotNone(ticket.resolved_at)
        self.assertGreater(ticket.resolved_at, first_resolved)
