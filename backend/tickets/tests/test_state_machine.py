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
        # Sprint 25C — IN_PROGRESS -> WAITING_CUSTOMER_APPROVAL requires
        # a completion note or visible attachment. A note is sufficient.
        ticket = apply_transition(
            ticket,
            self.manager,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            note="completion ok",
        )

        self.assertIsNone(ticket.resolved_at)

        ticket = apply_transition(ticket, self.customer_user, TicketStatus.APPROVED)

        self.assertIsNotNone(ticket.resolved_at)
        self.assertEqual(ticket.resolved_at, ticket.approved_at)

    def test_company_admin_can_approve_in_company_scope(self):
        ticket = self.move_ticket_to_customer_approval()

        # Sprint 27F-B1 — COMPANY_ADMIN driving WAITING_CUSTOMER_APPROVAL
        # → APPROVED is, by definition, a workflow override of the
        # customer's decision. The new state-machine layer coerces
        # is_override=True and enforces an override_reason on this
        # transition. Pass a reason so the existing scope test still
        # locks COMPANY_ADMIN-can-approve behaviour.
        ticket = apply_transition(
            ticket,
            self.company_admin,
            TicketStatus.APPROVED,
            override_reason="Customer phoned to approve.",
        )

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

        # Sprint 27F-B1 — same override coercion as the approve sibling
        # above. The reason is the standard "customer non-response" case
        # that the new override surface exists to handle.
        ticket = apply_transition(
            ticket,
            self.company_admin,
            TicketStatus.REJECTED,
            note="Customer did not respond within SLA window.",
            override_reason="Customer did not respond within SLA window.",
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
        # Sprint 25C — every IN_PROGRESS -> WAITING_CUSTOMER_APPROVAL hop
        # in this loop test gets a completion note so the evidence rule
        # passes. Other transitions are unchanged.
        ticket = apply_transition(self.ticket, self.manager, TicketStatus.IN_PROGRESS)
        ticket = apply_transition(
            ticket,
            self.manager,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            note="completion ok",
        )
        ticket = apply_transition(ticket, self.customer_user, TicketStatus.REJECTED)

        ticket = apply_transition(ticket, self.manager, TicketStatus.IN_PROGRESS)
        ticket = apply_transition(
            ticket,
            self.manager,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            note="completion ok",
        )
        ticket = apply_transition(ticket, self.customer_user, TicketStatus.APPROVED)

        first_resolved = ticket.resolved_at
        self.assertIsNotNone(first_resolved)

        ticket = apply_transition(ticket, self.company_admin, TicketStatus.CLOSED)
        ticket = apply_transition(ticket, self.company_admin, TicketStatus.REOPENED_BY_ADMIN)
        ticket = apply_transition(ticket, self.manager, TicketStatus.IN_PROGRESS)
        ticket = apply_transition(
            ticket,
            self.manager,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            note="completion ok",
        )
        ticket = apply_transition(ticket, self.customer_user, TicketStatus.APPROVED)

        self.assertIsNotNone(ticket.resolved_at)
        self.assertGreater(ticket.resolved_at, first_resolved)


# ===========================================================================
# Sprint 15 — customer-user transitions require EXACT (customer, building)
# pair access, not just a CustomerUserMembership for the customer.
#
# Sprint 14 introduced CustomerUserBuildingAccess but
# state_machine._user_passes_scope still only checked CustomerUserMembership
# for SCOPE_CUSTOMER_LINKED. Sprint 15 closes that gap so a customer-user
# whose access list does not include the ticket's building cannot
# approve or reject the ticket — even if they share the customer with
# the rightful approver.
# ===========================================================================

from buildings.models import Building
from customers.models import (
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from accounts.models import UserRole
from tickets.models import Ticket, TicketType
from tickets.permissions import user_has_scope_for_ticket
from tickets.state_machine import allowed_next_statuses, can_transition


class CustomerUserPairAccessTransitionTests(TenantFixtureMixin, APITestCase):
    """
    Build a multi-building B Amsterdam-style scenario on top of the
    standard fixture so the per-building pair check is observable.
    """

    def setUp(self):
        super().setUp()

        # Two extra buildings under self.company. self.building (from
        # the fixture) plus self.b_extra is enough to prove the pair
        # check; self.b_third gives us a building Amanda has no access
        # to at all, distinct from the fixture's self.building.
        self.b_extra = Building.objects.create(
            company=self.company, name="Building A2", address="Other Street"
        )
        self.b_third = Building.objects.create(
            company=self.company, name="Building A3", address="Third Street"
        )

        # Promote self.customer to the consolidated shape: link it to
        # all three buildings via CustomerBuildingMembership. The
        # fixture already created the (customer, self.building) row,
        # so we add the two new ones.
        CustomerBuildingMembership.objects.get_or_create(
            customer=self.customer, building=self.b_extra
        )
        CustomerBuildingMembership.objects.get_or_create(
            customer=self.customer, building=self.b_third
        )

        # Amanda: customer-user of self.customer with access ONLY to
        # self.b_third.
        self.amanda = self.make_user(
            "amanda-sprint15@example.com", UserRole.CUSTOMER_USER
        )
        amanda_membership = CustomerUserMembership.objects.create(
            user=self.amanda, customer=self.customer
        )
        CustomerUserBuildingAccess.objects.create(
            membership=amanda_membership, building=self.b_third
        )

        # Two tickets: one at self.b_third (in-scope for Amanda), one
        # at self.b_extra (out-of-scope for Amanda but same customer).
        # Both start in WAITING_CUSTOMER_APPROVAL so the
        # APPROVED/REJECTED transitions are testable directly.
        self.ticket_in_scope = Ticket.objects.create(
            company=self.company,
            building=self.b_third,
            customer=self.customer,
            created_by=self.amanda,
            title="Amanda-scope ticket",
            description="d",
            type=TicketType.REPORT,
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
        )
        self.ticket_out_of_scope = Ticket.objects.create(
            company=self.company,
            building=self.b_extra,
            customer=self.customer,
            created_by=self.customer_user,  # someone else
            title="Other-building ticket",
            description="d",
            type=TicketType.REPORT,
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
        )

    # --- can_transition ----------------------------------------------------

    def test_can_approve_ticket_in_scope_building(self):
        self.assertTrue(
            can_transition(self.amanda, self.ticket_in_scope, TicketStatus.APPROVED)
        )

    def test_can_reject_ticket_in_scope_building(self):
        self.assertTrue(
            can_transition(self.amanda, self.ticket_in_scope, TicketStatus.REJECTED)
        )

    def test_cannot_approve_ticket_out_of_scope_building(self):
        self.assertFalse(
            can_transition(
                self.amanda, self.ticket_out_of_scope, TicketStatus.APPROVED
            )
        )

    def test_cannot_reject_ticket_out_of_scope_building(self):
        self.assertFalse(
            can_transition(
                self.amanda, self.ticket_out_of_scope, TicketStatus.REJECTED
            )
        )

    # --- allowed_next_statuses --------------------------------------------

    def test_allowed_next_statuses_in_scope_includes_approved_and_rejected(self):
        next_statuses = set(allowed_next_statuses(self.amanda, self.ticket_in_scope))
        self.assertIn(TicketStatus.APPROVED, next_statuses)
        self.assertIn(TicketStatus.REJECTED, next_statuses)

    def test_allowed_next_statuses_out_of_scope_excludes_approval_actions(self):
        next_statuses = set(allowed_next_statuses(self.amanda, self.ticket_out_of_scope))
        self.assertNotIn(TicketStatus.APPROVED, next_statuses)
        self.assertNotIn(TicketStatus.REJECTED, next_statuses)
        # In fact a customer-user has no transitions at all on a ticket
        # that is out of their building access — the empty set is the
        # expected shape.
        self.assertEqual(next_statuses, set())

    # --- apply_transition end-to-end --------------------------------------

    def test_apply_transition_rejects_out_of_scope_approval(self):
        with self.assertRaises(TransitionError) as ctx:
            apply_transition(
                self.ticket_out_of_scope, self.amanda, TicketStatus.APPROVED
            )
        self.assertEqual(ctx.exception.code, "forbidden_transition")

    def test_apply_transition_allows_in_scope_approval(self):
        ticket = apply_transition(
            self.ticket_in_scope, self.amanda, TicketStatus.APPROVED
        )
        self.assertEqual(ticket.status, TicketStatus.APPROVED)

    # --- user_has_scope_for_ticket (Sprint 15 hardening) ------------------

    def test_user_has_scope_for_ticket_true_for_in_scope_pair(self):
        self.assertTrue(user_has_scope_for_ticket(self.amanda, self.ticket_in_scope))

    def test_user_has_scope_for_ticket_false_for_out_of_scope_pair(self):
        self.assertFalse(
            user_has_scope_for_ticket(self.amanda, self.ticket_out_of_scope)
        )
