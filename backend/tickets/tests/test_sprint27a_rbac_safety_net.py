"""
Sprint 27A — RBAC / permission / hierarchy safety net (tickets app).

T-4  test_staff_cannot_approve_or_override_ticket_completion

Asserts hard invariant H-5 from docs/architecture/sprint-27-rbac-matrix.md:
STAFF must never be able to drive a ticket from
WAITING_CUSTOMER_APPROVAL into APPROVED or REJECTED — that decision
belongs to the customer (or, via a separately-modelled workflow
override, to a provider operator).

The ticket state-machine `ALLOWED_TRANSITIONS` map at
`backend/tickets/state_machine.py` does not include STAFF for the
two outbound transitions of WAITING_CUSTOMER_APPROVAL, so a STAFF
user attempting either via the state machine OR the HTTP endpoint
must be rejected. This test locks both paths.

Today this is enforced by:
  * State machine: STAFF not in `ALLOWED_TRANSITIONS[(WCA, *)]`
    → `can_transition` returns False → `forbidden_transition`.
  * View layer: customers and customer-side users (including
    `User.role=STAFF` which is provider-side, but the gate at
    `tickets/views.py:200-207` rejects every non-staff-role-from-
    customer-side-perspective; STAFF passes that gate and then
    hits the state machine).

The test does NOT introduce any new behavior — it pins existing
behavior so a future refactor that, e.g., adds STAFF to a "manager
override" branch by accident would surface immediately.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from tickets.models import (
    Ticket,
    TicketStaffAssignment,
    TicketStatus,
)
from tickets.state_machine import TransitionError, apply_transition
from test_utils import TenantFixtureMixin


class StaffCannotApproveOrOverrideTicketTests(
    TenantFixtureMixin, APITestCase
):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.staff_user = User.objects.create_user(
            email="staff@example.com",
            password=self.password,
            role=UserRole.STAFF,
            full_name="Staff",
        )
        StaffProfile.objects.create(user=self.staff_user, is_active=True)
        # Give staff broad visibility AND a direct assignment so the
        # scope_tickets_for query returns the ticket — proving the
        # block is on the decision, not just on visibility.
        BuildingStaffVisibility.objects.create(
            user=self.staff_user, building=self.building
        )
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.staff_user
        )

        # Move the ticket into WAITING_CUSTOMER_APPROVAL so the
        # APPROVED / REJECTED transitions are the candidates.
        self.ticket.status = TicketStatus.WAITING_CUSTOMER_APPROVAL
        self.ticket.save(update_fields=["status", "updated_at"])

    def test_staff_cannot_approve_or_override_ticket_completion(self):
        """T-4: STAFF cannot drive WAITING_CUSTOMER_APPROVAL → APPROVED
        or REJECTED via the state machine OR the HTTP endpoint."""

        # --- direct state-machine path
        for target in (TicketStatus.APPROVED, TicketStatus.REJECTED):
            with self.assertRaises(TransitionError) as ctx:
                apply_transition(self.ticket, self.staff_user, target)
            self.assertEqual(
                ctx.exception.code,
                "forbidden_transition",
                f"STAFF must hit forbidden_transition on "
                f"WAITING_CUSTOMER_APPROVAL -> {target}, got "
                f"{ctx.exception.code!r}",
            )
            self.ticket.refresh_from_db()
            self.assertEqual(
                self.ticket.status,
                TicketStatus.WAITING_CUSTOMER_APPROVAL,
                "Ticket status must not have advanced.",
            )

        # --- HTTP path
        self.authenticate(self.staff_user)
        for target in (TicketStatus.APPROVED, TicketStatus.REJECTED):
            response = self.client.post(
                f"/api/tickets/{self.ticket.id}/status/",
                {"to_status": target},
                format="json",
            )
            # Reject as 403 (view-layer customer-decision gate) or
            # 400 (state-machine forbidden_transition). What matters
            # is NOT 200 — staff must never approve.
            self.assertIn(
                response.status_code,
                (
                    status.HTTP_403_FORBIDDEN,
                    status.HTTP_400_BAD_REQUEST,
                ),
                f"STAFF POST /status/ {target} must not succeed; "
                f"got {response.status_code}: {response.content!r}",
            )
            self.ticket.refresh_from_db()
            self.assertEqual(
                self.ticket.status,
                TicketStatus.WAITING_CUSTOMER_APPROVAL,
                f"Ticket status changed after a {response.status_code} "
                f"response — security regression.",
            )
