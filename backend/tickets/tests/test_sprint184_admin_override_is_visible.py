"""Sprint 184 §2 — a super admin's hand-typed status jump leaves a trace.

`can_transition` lets a SUPER_ADMIN past any pair. That power stays — an
admin has to be able to rescue a stuck ticket. What changes is that the
jump is no longer INVISIBLE: it writes `is_override=True` and demands a
reason, exactly as the customer-decision override already does, so the
`TicketStatusHistory` row (which H-11 says IS the audit trail) stops
reading like an ordinary step somebody earned.

Measured on crmtest before the fix: 28 such jumps, all by one account,
all with the flag off and no reason. Most common:
WAITING_MANAGER_REVIEW -> APPROVED (13), CLOSED -> OPEN (7),
CLOSED -> APPROVED (3). All three shapes are tested here.

Why it is money: CLOSED is what makes work invoiceable and `closed_at`
sets the billing month, so a typed jump to CLOSED manufactures billable
work nobody performed — and a jump back out un-bills it.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import Building
from companies.models import Company, CompanyUserMembership
from customers.models import Customer, CustomerBuildingMembership
from tickets.models import Ticket, TicketStatus, TicketStatusHistory
from tickets.state_machine import (
    TransitionError,
    allowed_next_statuses,
    apply_transition,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword184!"


class _Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov", slug="prov-184")
        cls.building = Building.objects.create(
            company=cls.company, name="B", address="B 1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust 184", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.super_admin = User.objects.create_user(
            email="sa-184@example.com",
            password=PASSWORD,
            role=UserRole.SUPER_ADMIN,
            full_name="SA",
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = User.objects.create_user(
            email="ca-184@example.com",
            password=PASSWORD,
            role=UserRole.COMPANY_ADMIN,
            full_name="CA",
        )
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def _ticket(self, status_value=TicketStatus.OPEN):
        return Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title="A ticket",
            description="d",
            status=status_value,
        )


class OutOfMachineJumpRequiresAReasonTests(_Fixture):
    """The three shapes actually observed on crmtest."""

    def test_waiting_manager_review_to_approved_needs_a_reason(self):
        """13 of the 28. It skips the customer's decision entirely while
        looking, in the timeline, like the customer made it."""
        ticket = self._ticket(TicketStatus.WAITING_MANAGER_REVIEW)
        with self.assertRaises(TransitionError) as ctx:
            apply_transition(ticket, self.super_admin, TicketStatus.APPROVED)
        self.assertEqual(ctx.exception.code, "override_reason_required")

    def test_closed_to_open_needs_a_reason(self):
        """7 of the 28. This one un-bills finished work."""
        ticket = self._ticket(TicketStatus.CLOSED)
        with self.assertRaises(TransitionError) as ctx:
            apply_transition(ticket, self.super_admin, TicketStatus.OPEN)
        self.assertEqual(ctx.exception.code, "override_reason_required")

    def test_closed_to_approved_needs_a_reason(self):
        """3 of the 28."""
        ticket = self._ticket(TicketStatus.CLOSED)
        with self.assertRaises(TransitionError) as ctx:
            apply_transition(ticket, self.super_admin, TicketStatus.APPROVED)
        self.assertEqual(ctx.exception.code, "override_reason_required")

    def test_a_jump_to_closed_needs_a_reason(self):
        """The one that manufactures invoiceable work: CLOSED is what
        `extra_work.billing.is_earned` reads, and `closed_at` sets the
        billing month."""
        ticket = self._ticket(TicketStatus.OPEN)
        with self.assertRaises(TransitionError) as ctx:
            apply_transition(ticket, self.super_admin, TicketStatus.CLOSED)
        self.assertEqual(ctx.exception.code, "override_reason_required")


class TheHistoryRowTellsTheTruthTests(_Fixture):
    """Before: `is_override=False`, no reason — indistinguishable from an
    ordinary step. After: flagged and explained."""

    def test_the_jump_still_works_when_a_reason_is_given(self):
        """The power is NOT removed. An admin rescuing a stuck ticket can
        still do it; they just have to say why."""
        ticket = self._ticket(TicketStatus.WAITING_MANAGER_REVIEW)
        apply_transition(
            ticket,
            self.super_admin,
            TicketStatus.APPROVED,
            override_reason="Customer approved by phone; recorded by hand.",
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.APPROVED)

    def test_the_history_row_is_flagged_and_carries_the_reason(self):
        ticket = self._ticket(TicketStatus.CLOSED)
        apply_transition(
            ticket,
            self.super_admin,
            TicketStatus.OPEN,
            override_reason="Closed by mistake; the work was never done.",
        )
        row = TicketStatusHistory.objects.filter(ticket=ticket).latest("id")
        self.assertTrue(
            row.is_override,
            "H-11: the history row IS the audit trail, so it has to say "
            "this was a jump",
        )
        self.assertIn("Closed by mistake", row.override_reason)
        self.assertEqual(row.changed_by, self.super_admin)

    def test_an_ordinary_transition_is_not_flagged(self):
        """The guard is narrow: a normal step inside ALLOWED_TRANSITIONS
        needs no reason and is not marked as an override, or the flag
        would stop meaning anything."""
        ticket = self._ticket(TicketStatus.OPEN)
        apply_transition(ticket, self.super_admin, TicketStatus.IN_PROGRESS)
        row = TicketStatusHistory.objects.filter(ticket=ticket).latest("id")
        self.assertFalse(row.is_override)
        self.assertEqual(row.override_reason, "")

    def test_the_endpoint_returns_the_stable_code(self):
        ticket = self._ticket(TicketStatus.CLOSED)
        resp = self.api(self.super_admin).post(
            f"/api/tickets/{ticket.id}/status/",
            {"to_status": "OPEN"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.data.get("code"), "override_reason_required")

    def test_the_endpoint_accepts_the_jump_with_a_reason(self):
        ticket = self._ticket(TicketStatus.CLOSED)
        resp = self.api(self.super_admin).post(
            f"/api/tickets/{ticket.id}/status/",
            {
                "to_status": "OPEN",
                "override_reason": "Closed in error during the migration.",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.OPEN)


class ConvertedToExtraWorkIsNotOfferedTests(_Fixture):
    """The API used to advertise a target its own endpoint refuses."""

    def test_super_admin_is_not_offered_converted_to_extra_work(self):
        ticket = self._ticket(TicketStatus.OPEN)
        self.assertNotIn(
            TicketStatus.CONVERTED_TO_EXTRA_WORK,
            allowed_next_statuses(self.super_admin, ticket),
        )

    def test_the_rest_of_the_admin_list_is_unchanged(self):
        """Removing one dead option must not quietly narrow the power."""
        ticket = self._ticket(TicketStatus.OPEN)
        offered = set(allowed_next_statuses(self.super_admin, ticket))
        expected = {
            str(s)
            for s, _ in TicketStatus.choices
            if str(s)
            not in {
                str(TicketStatus.OPEN),
                str(TicketStatus.CONVERTED_TO_EXTRA_WORK),
            }
        }
        self.assertEqual({str(s) for s in offered}, expected)

    def test_the_endpoint_still_refuses_it(self):
        """Belt and braces: the list no longer offers it AND the
        transition is still impossible."""
        ticket = self._ticket(TicketStatus.OPEN)
        with self.assertRaises(TransitionError) as ctx:
            apply_transition(
                ticket,
                self.super_admin,
                TicketStatus.CONVERTED_TO_EXTRA_WORK,
                override_reason="trying anyway",
            )
        self.assertEqual(ctx.exception.code, "forbidden_transition")
