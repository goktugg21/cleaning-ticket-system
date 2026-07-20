"""
#109 Part A (audit P2-2) — ticket customer-approval permission gate.

The ticket state machine's SCOPE_CUSTOMER_LINKED branch now mirrors the
Extra Work machine's `_user_can_drive_transition`: a customer-side
actor driving WAITING_CUSTOMER_APPROVAL -> APPROVED / REJECTED must
RESOLVE `customer.ticket.approve_own` (own ticket) or
`customer.ticket.approve_location` through
`customers.permissions.user_can` — which honors per-building
access-role defaults, per-user permission_overrides and the
CustomerCompanyPolicy family
(customer_users_can_approve_ticket_completion). A bare
CustomerUserBuildingAccess row is no longer sufficient.

The provider-driven override path (BM/CA with is_override + reason) is
untouched and re-locked here.
"""
from rest_framework.test import APITestCase

from customers.models import (
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from accounts.models import UserRole
from test_utils import TenantFixtureMixin
from tickets.models import TicketStatus, TicketStatusHistory
from tickets.state_machine import (
    TransitionError,
    apply_transition,
    can_transition,
)


class CustomerApprovalGateTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # A colleague of self.customer_user at the SAME (customer,
        # building) pair — plain CUSTOMER_USER access role.
        self.colleague = self.make_user(
            "colleague-109@example.com", UserRole.CUSTOMER_USER
        )
        colleague_membership = CustomerUserMembership.objects.create(
            user=self.colleague, customer=self.customer
        )
        self.colleague_access = CustomerUserBuildingAccess.objects.create(
            membership=colleague_membership, building=self.building
        )
        # A CLM-tier colleague at the same pair.
        self.clm = self.make_user("clm-109@example.com", UserRole.CUSTOMER_USER)
        clm_membership = CustomerUserMembership.objects.create(
            user=self.clm, customer=self.customer
        )
        self.clm_access = CustomerUserBuildingAccess.objects.create(
            membership=clm_membership,
            building=self.building,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER
            ),
        )
        # The fixture ticket is created_by=self.customer_user; park it
        # at the customer-decision state.
        self.move_ticket_to_customer_approval()

    # --- creator / own-ticket resolution -----------------------------------

    def test_creator_with_default_approve_own_is_allowed(self):
        self.assertTrue(
            can_transition(
                self.customer_user, self.ticket, TicketStatus.APPROVED
            )
        )
        ticket = apply_transition(
            self.ticket, self.customer_user, TicketStatus.APPROVED
        )
        self.assertEqual(ticket.status, TicketStatus.APPROVED)

    def test_plain_customer_user_cannot_approve_foreign_ticket(self):
        # The colleague holds a valid access row for the exact pair —
        # pre-#109 that alone passed. approve_location defaults False
        # for the CUSTOMER_USER access role, so the gate now denies.
        self.assertFalse(
            can_transition(self.colleague, self.ticket, TicketStatus.APPROVED)
        )
        with self.assertRaises(TransitionError):
            apply_transition(
                self.ticket, self.colleague, TicketStatus.APPROVED
            )

    def test_clm_can_approve_colleagues_ticket_at_their_building(self):
        # CUSTOMER_LOCATION_MANAGER role default grants approve_location.
        self.assertTrue(
            can_transition(self.clm, self.ticket, TicketStatus.APPROVED)
        )
        ticket = apply_transition(
            self.ticket, self.clm, TicketStatus.REJECTED
        )
        self.assertEqual(ticket.status, TicketStatus.REJECTED)

    # --- policy family ------------------------------------------------------

    def test_policy_toggle_off_denies_customer_approval(self):
        policy = self.customer.policy
        policy.customer_users_can_approve_ticket_completion = False
        policy.save(
            update_fields=["customer_users_can_approve_ticket_completion"]
        )
        # Denies BOTH approve_own (the creator) and approve_location
        # (the CLM) — the whole family is policy-bounded.
        self.assertFalse(
            can_transition(
                self.customer_user, self.ticket, TicketStatus.APPROVED
            )
        )
        self.assertFalse(
            can_transition(self.clm, self.ticket, TicketStatus.APPROVED)
        )
        with self.assertRaises(TransitionError):
            apply_transition(
                self.ticket, self.customer_user, TicketStatus.APPROVED
            )

    # --- per-user overrides -------------------------------------------------

    def test_override_revoking_approve_own_denies_creator(self):
        access = CustomerUserBuildingAccess.objects.get(
            membership__user=self.customer_user,
            membership__customer=self.customer,
            building=self.building,
        )
        access.permission_overrides = {"customer.ticket.approve_own": False}
        access.save(update_fields=["permission_overrides"])
        self.assertFalse(
            can_transition(
                self.customer_user, self.ticket, TicketStatus.APPROVED
            )
        )

    def test_override_granting_approve_location_allows_colleague(self):
        # Inverse direction: a plain CUSTOMER_USER granted the location
        # key via permission_overrides may now approve a colleague's
        # ticket (the Sprint 27C modular-permission promise).
        self.colleague_access.permission_overrides = {
            "customer.ticket.approve_location": True
        }
        self.colleague_access.save(update_fields=["permission_overrides"])
        self.assertTrue(
            can_transition(self.colleague, self.ticket, TicketStatus.APPROVED)
        )

    # --- pair exactness is preserved ---------------------------------------

    def test_no_access_row_for_pair_still_denied(self):
        other_building_ticket_customer = self.make_user(
            "no-pair-109@example.com", UserRole.CUSTOMER_USER
        )
        membership = CustomerUserMembership.objects.create(
            user=other_building_ticket_customer, customer=self.customer
        )
        extra_building = self.building.__class__.objects.create(
            company=self.company, name="B-extra-109", address="x"
        )
        CustomerBuildingMembership.objects.create(
            customer=self.customer, building=extra_building
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership, building=extra_building
        )
        # Access at ANOTHER building of the same customer resolves
        # nothing for self.ticket's building.
        self.assertFalse(
            can_transition(
                other_building_ticket_customer,
                self.ticket,
                TicketStatus.APPROVED,
            )
        )

    # --- provider override path untouched ----------------------------------

    def test_bm_override_path_still_works(self):
        ticket = apply_transition(
            self.ticket,
            self.manager,
            TicketStatus.APPROVED,
            override_reason="Customer approved by phone.",
        )
        self.assertEqual(ticket.status, TicketStatus.APPROVED)
        history = TicketStatusHistory.objects.get(
            ticket=ticket,
            old_status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            new_status=TicketStatus.APPROVED,
        )
        self.assertTrue(history.is_override)
        self.assertEqual(history.override_reason, "Customer approved by phone.")
