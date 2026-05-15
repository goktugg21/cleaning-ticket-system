"""
Sprint 27F-B1 — Ticket workflow override (closes G-B3).

Mirrors the proven Extra Work override surface at
`backend/extra_work/state_machine.py:195-313` /
`backend/extra_work/models.py:362-368`.

Locks the following behaviours on the new
`TicketStatusHistory.is_override + override_reason` columns and the
extended `apply_transition` / `TicketStatusChangeSerializer` /
`/api/tickets/<id>/status/` surface:

1. A COMPANY_ADMIN override on a WAITING_CUSTOMER_APPROVAL ticket
   persists `is_override=True` + the reason on the new history row,
   and stamps the usual `approved_at` / `resolved_at` timestamps.
2. A COMPANY_ADMIN override without `override_reason` is rejected
   with HTTP 400 + stable code `override_reason_required`.
3. A SUPER_ADMIN provider-driven customer-decision transition is
   coerced into `is_override=True` even when the client forgot the
   flag, matching the Extra Work coercion at
   `extra_work/state_machine.py:250-265`.
4. A CUSTOMER_USER who self-approves their own ticket does NOT have
   `is_override` set — the override flag is exclusively a
   provider-side concept (matrix H-11).
5. A STAFF actor cannot drive the customer-decision transition at
   all (locks matrix H-5).
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from tickets.models import (
    TicketStaffAssignment,
    TicketStatus,
    TicketStatusHistory,
)
from test_utils import TenantFixtureMixin


class TicketWorkflowOverrideTests(TenantFixtureMixin, APITestCase):
    """Provider-side overrides on WAITING_CUSTOMER_APPROVAL → APPROVED/REJECTED."""

    def setUp(self):
        super().setUp()
        self.move_ticket_to_customer_approval()

    def _post_status(self, actor, payload):
        self.authenticate(actor)
        return self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            payload,
            format="json",
        )

    def test_company_admin_override_persists_is_override_and_reason(self):
        response = self._post_status(
            self.company_admin,
            {
                "to_status": TicketStatus.APPROVED,
                "is_override": True,
                "override_reason": "Customer phoned",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.APPROVED)
        self.assertIsNotNone(self.ticket.approved_at)
        self.assertIsNotNone(self.ticket.resolved_at)

        history_row = (
            TicketStatusHistory.objects.filter(
                ticket=self.ticket,
                new_status=TicketStatus.APPROVED,
            )
            .order_by("-created_at")
            .first()
        )
        self.assertIsNotNone(history_row)
        self.assertTrue(history_row.is_override)
        self.assertEqual(history_row.override_reason, "Customer phoned")
        self.assertEqual(history_row.changed_by_id, self.company_admin.id)

    def test_company_admin_override_without_reason_returns_400_override_reason_required(self):
        response = self._post_status(
            self.company_admin,
            {
                "to_status": TicketStatus.APPROVED,
                "is_override": True,
                "override_reason": "",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Stable error contract — same shape Extra Work uses
        # (`{detail, code}`) so the FE can branch on it without
        # string-matching the message.
        self.assertEqual(response.data.get("code"), "override_reason_required")

        self.ticket.refresh_from_db()
        self.assertEqual(
            self.ticket.status, TicketStatus.WAITING_CUSTOMER_APPROVAL
        )
        self.assertFalse(
            TicketStatusHistory.objects.filter(
                ticket=self.ticket,
                new_status=TicketStatus.APPROVED,
            ).exists()
        )

    def test_super_admin_override_without_explicit_flag_is_coerced(self):
        # Mirror `extra_work/state_machine.py:250-265` — a provider
        # operator driving a customer-decision transition is ALWAYS
        # an override even if the client forgot the flag. Reason is
        # still required.
        response = self._post_status(
            self.super_admin,
            {
                "to_status": TicketStatus.APPROVED,
                "override_reason": "x",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        history_row = (
            TicketStatusHistory.objects.filter(
                ticket=self.ticket,
                new_status=TicketStatus.APPROVED,
            )
            .order_by("-created_at")
            .first()
        )
        self.assertIsNotNone(history_row)
        self.assertTrue(history_row.is_override)
        self.assertEqual(history_row.override_reason, "x")

    def test_customer_user_self_approval_does_not_set_is_override(self):
        # H-11: workflow override is a provider-side concept. A
        # customer driving their own approve transition is NOT an
        # override — even if the request body smuggles in the
        # is_override field, the state machine must not coerce it
        # (only the provider-driven branch coerces).
        response = self._post_status(
            self.customer_user,
            {"to_status": TicketStatus.APPROVED},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        history_row = (
            TicketStatusHistory.objects.filter(
                ticket=self.ticket,
                new_status=TicketStatus.APPROVED,
            )
            .order_by("-created_at")
            .first()
        )
        self.assertIsNotNone(history_row)
        self.assertFalse(history_row.is_override)
        self.assertEqual(history_row.override_reason, "")


class StaffCannotOverrideTests(TenantFixtureMixin, APITestCase):
    """Locks matrix H-5: STAFF must never drive the customer-decision
    transition, with OR without an override payload."""

    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.staff_user = User.objects.create_user(
            email="staff-27f@example.com",
            password=self.password,
            role=UserRole.STAFF,
            full_name="Staff 27F",
        )
        StaffProfile.objects.create(user=self.staff_user, is_active=True)
        BuildingStaffVisibility.objects.create(
            user=self.staff_user, building=self.building
        )
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.staff_user
        )
        self.move_ticket_to_customer_approval()

    def test_staff_cannot_override(self):
        self.authenticate(self.staff_user)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {
                "to_status": TicketStatus.APPROVED,
                "is_override": True,
                "override_reason": "I will not be allowed through",
            },
            format="json",
        )
        # View-layer gate at tickets/views.py:200-207 rejects STAFF
        # from customer-decision transitions with a 403; if that gate
        # ever changes to let STAFF reach the state machine, the
        # state-machine forbidden_transition (400) is the floor.
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_400_BAD_REQUEST),
            f"STAFF override must not succeed; got {response.status_code}: "
            f"{response.content!r}",
        )

        self.ticket.refresh_from_db()
        self.assertEqual(
            self.ticket.status, TicketStatus.WAITING_CUSTOMER_APPROVAL
        )
        self.assertFalse(
            TicketStatusHistory.objects.filter(
                ticket=self.ticket,
                new_status=TicketStatus.APPROVED,
                is_override=True,
            ).exists()
        )
