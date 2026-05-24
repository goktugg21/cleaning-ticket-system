"""
B1 — backend workflow corrections per
docs/product/system-business-logic-and-workflows.md.

This file pins the four B1 changes:

  B1.1  Building Manager may drive
        `WAITING_CUSTOMER_APPROVAL -> APPROVED / REJECTED` on a ticket
        in their assigned building. The transition is coerced to
        `is_override=True` and demands `override_reason` (HTTP 400
        `override_reason_required` when missing). Provider override
        coercion mirrors the existing SA / COMPANY_ADMIN shape so
        the audit row carries the same fields.

  B1.2  The completion-evidence rule
        (`completion_evidence_required`) fires for STAFF actors only.
        Admins / managers driving the same transition bypass the
        gate. Pinned more deeply in `test_sprint25c_completion_evidence`
        — kept here as a one-liner regression that future refactors
        can't accidentally widen the gate.

  B1.3  Customer-facing history serializers redact `note` and (where
        present) `override_reason` for rows authored by provider-side
        actors. Provider readers see everything unchanged. Customer-
        authored and system-driven rows still carry their notes.

  B1.4  `audit.context.snapshot_actor_scope(user)` already records the
        actor's role at write time — the field "role" is present in
        the snapshot dict. Pinned here to defend the contract against
        future refactors of the snapshot shape.

No migrations. No new permission keys. No frontend touched.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.context import snapshot_actor_scope
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from tickets.models import (
    Ticket,
    TicketStatus,
    TicketStatusHistory,
)
from tickets.state_machine import TransitionError, apply_transition


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


# ---------------------------------------------------------------------------
# Fixture — one provider company, one building, one customer, one ticket
# already in WAITING_CUSTOMER_APPROVAL, plus the five role actors.
# ---------------------------------------------------------------------------
class _B1Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        suffix = "b1"
        cls.company = Company.objects.create(
            name=f"Provider {suffix}", slug=f"prov-{suffix}"
        )
        cls.building = Building.objects.create(
            company=cls.company, name=f"Building {suffix}"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            name=f"Customer {suffix}",
            building=cls.building,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            f"super-{suffix}@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk(f"admin-{suffix}@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )
        cls.bm = _mk(f"bm-{suffix}@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.bm, building=cls.building
        )
        cls.other_bm = _mk(
            f"other-bm-{suffix}@example.com", UserRole.BUILDING_MANAGER
        )
        # other_bm has NO assignment to this building — used to test
        # scope refusal.

        cls.cust_user = _mk(
            f"cust-{suffix}@example.com", UserRole.CUSTOMER_USER
        )
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership, building=cls.building
        )

    def setUp(self):
        # Per-test ticket so each test starts fresh in WCA.
        self.ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title="B1 test ticket",
            description="seed",
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c


# ---------------------------------------------------------------------------
# B1.1 — Building Manager customer-decision override.
# ---------------------------------------------------------------------------
class BuildingManagerCustomerDecisionOverrideTests(_B1Fixture):
    """Pins that BM may drive WAITING_CUSTOMER_APPROVAL -> APPROVED /
    REJECTED on assigned-building tickets, BUT only with an
    `override_reason`, AND the resulting history row carries
    `is_override=True` + the reason."""

    def test_bm_without_reason_returns_override_reason_required(self):
        with self.assertRaises(TransitionError) as ctx:
            apply_transition(
                self.ticket,
                self.bm,
                TicketStatus.APPROVED,
                note="",
                is_override=False,
                override_reason="",
            )
        self.assertEqual(ctx.exception.code, "override_reason_required")
        self.ticket.refresh_from_db()
        self.assertEqual(
            self.ticket.status, TicketStatus.WAITING_CUSTOMER_APPROVAL
        )

    def test_bm_with_reason_approves_and_records_override_history(self):
        updated = apply_transition(
            self.ticket,
            self.bm,
            TicketStatus.APPROVED,
            note="",
            is_override=False,
            override_reason="Customer approved verbally over phone.",
        )
        self.assertEqual(updated.status, TicketStatus.APPROVED)

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
        self.assertEqual(
            history_row.override_reason,
            "Customer approved verbally over phone.",
        )
        self.assertEqual(history_row.changed_by_id, self.bm.id)

    def test_bm_with_reason_can_reject(self):
        updated = apply_transition(
            self.ticket,
            self.bm,
            TicketStatus.REJECTED,
            note="",
            is_override=False,
            override_reason="Customer wants the work re-done on-site.",
        )
        self.assertEqual(updated.status, TicketStatus.REJECTED)
        history_row = (
            TicketStatusHistory.objects.filter(
                ticket=self.ticket, new_status=TicketStatus.REJECTED
            )
            .order_by("-created_at")
            .first()
        )
        self.assertTrue(history_row.is_override)
        self.assertEqual(history_row.override_reason, "Customer wants the work re-done on-site.")

    def test_bm_explicit_is_override_true_still_requires_reason(self):
        # Even when the client sends is_override=True, an empty reason
        # must trip the gate. (Defence in depth — the gate runs regardless
        # of the client's flag.)
        with self.assertRaises(TransitionError) as ctx:
            apply_transition(
                self.ticket,
                self.bm,
                TicketStatus.APPROVED,
                note="",
                is_override=True,
                override_reason="   \t  ",
            )
        self.assertEqual(ctx.exception.code, "override_reason_required")

    def test_bm_without_building_assignment_is_forbidden(self):
        # other_bm is BUILDING_MANAGER but has NO assignment to the
        # ticket's building. The scope gate must refuse before the
        # override-reason gate fires.
        with self.assertRaises(TransitionError) as ctx:
            apply_transition(
                self.ticket,
                self.other_bm,
                TicketStatus.APPROVED,
                note="",
                is_override=False,
                override_reason="should not matter",
            )
        self.assertEqual(ctx.exception.code, "forbidden_transition")

    def test_customer_user_path_is_unaffected_no_override_coercion(self):
        # A customer-user (the ticket's creator with access to the
        # building) approves their own ticket. No override coercion —
        # the history row stays is_override=False.
        updated = apply_transition(
            self.ticket,
            self.cust_user,
            TicketStatus.APPROVED,
            note="Looks good.",
        )
        self.assertEqual(updated.status, TicketStatus.APPROVED)
        history_row = (
            TicketStatusHistory.objects.filter(
                ticket=self.ticket, new_status=TicketStatus.APPROVED
            )
            .order_by("-created_at")
            .first()
        )
        self.assertFalse(history_row.is_override)
        self.assertEqual(history_row.override_reason, "")

    def test_bm_api_returns_400_with_stable_code_when_reason_missing(self):
        response = self._api(self.bm).post(
            f"/api/tickets/{self.ticket.id}/status/",
            {"to_status": TicketStatus.APPROVED},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        body = response.json()
        # `code` may be either a top-level string or a single-item list
        # depending on DRF version; accept either.
        code = body.get("code")
        if isinstance(code, list):
            code = code[0] if code else None
        self.assertEqual(code, "override_reason_required")


# ---------------------------------------------------------------------------
# B1.2 — Completion-evidence gate is STAFF-only. (Deep coverage lives in
# test_sprint25c_completion_evidence; this is a one-liner regression.)
# ---------------------------------------------------------------------------
class CompletionEvidenceGateAdminBypassRegressionTests(_B1Fixture):
    def test_bm_completing_a_ticket_does_not_trip_evidence_gate(self):
        # Drive the ticket back to IN_PROGRESS so the completion-evidence
        # transition pair is reachable. Per B1, BM bypasses the gate.
        self.ticket.status = TicketStatus.IN_PROGRESS
        self.ticket.save(update_fields=["status"])

        result = apply_transition(
            self.ticket,
            self.bm,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            note="",
        )
        self.assertEqual(
            result.status, TicketStatus.WAITING_CUSTOMER_APPROVAL
        )


# ---------------------------------------------------------------------------
# B1.3 — History-note redaction (tickets). EW + Proposal coverage lives
# inline in those apps' test suites; here we pin the ticket variant.
# ---------------------------------------------------------------------------
class TicketHistoryNoteRedactionForCustomerTests(_B1Fixture):
    """Customer readers see notes ONLY for customer-authored or
    system-authored history rows. Provider-authored notes (and
    `override_reason`) are redacted to empty strings."""

    def setUp(self):
        super().setUp()
        # Drive a provider override -> APPROVED so the row has a
        # provider author AND an override_reason populated.
        apply_transition(
            self.ticket,
            self.bm,
            TicketStatus.APPROVED,
            note="Provider-internal context that customers must not see.",
            is_override=False,
            override_reason="Customer approved over the phone.",
        )

    def _detail(self, user):
        return self._api(user).get(f"/api/tickets/{self.ticket.id}/")

    def _history_row(self, body, new_status):
        return next(
            (
                row
                for row in body.get("status_history", [])
                if row["new_status"] == new_status
            ),
            None,
        )

    def test_customer_does_not_see_provider_authored_note(self):
        response = self._detail(self.cust_user)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        row = self._history_row(response.data, TicketStatus.APPROVED)
        self.assertIsNotNone(row)
        # Note redacted, override_reason redacted.
        self.assertEqual(row["note"], "")
        self.assertEqual(row["override_reason"], "")
        # The flag itself stays visible — customers should see THAT an
        # override happened, just not the provider's free-text reason.
        self.assertTrue(row["is_override"])

    def test_provider_admin_still_sees_everything(self):
        response = self._detail(self.admin)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        row = self._history_row(response.data, TicketStatus.APPROVED)
        self.assertIsNotNone(row)
        self.assertEqual(
            row["note"],
            "Provider-internal context that customers must not see.",
        )
        self.assertEqual(
            row["override_reason"], "Customer approved over the phone."
        )
        self.assertTrue(row["is_override"])

    def test_bm_still_sees_everything(self):
        response = self._detail(self.bm)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        row = self._history_row(response.data, TicketStatus.APPROVED)
        self.assertIsNotNone(row)
        self.assertEqual(
            row["note"],
            "Provider-internal context that customers must not see.",
        )
        self.assertEqual(
            row["override_reason"], "Customer approved over the phone."
        )

    def test_customer_authored_history_row_keeps_note(self):
        # Reset, drive WCA -> APPROVED as the customer-user themselves.
        # That row's note must remain visible to the same customer
        # reading the timeline.
        fresh_ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title="customer-authored row",
            description="seed",
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
        )
        apply_transition(
            fresh_ticket,
            self.cust_user,
            TicketStatus.APPROVED,
            note="All good — closing.",
        )
        response = self._api(self.cust_user).get(
            f"/api/tickets/{fresh_ticket.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.data.get("status_history", [])
        approved_row = next(
            (r for r in rows if r["new_status"] == TicketStatus.APPROVED),
            None,
        )
        self.assertIsNotNone(approved_row)
        self.assertEqual(approved_row["note"], "All good — closing.")


# ---------------------------------------------------------------------------
# B1.4 — Audit actor_scope snapshot includes the actor's role.
# ---------------------------------------------------------------------------
class AuditActorScopeIncludesRoleTests(_B1Fixture):
    def test_snapshot_includes_role_for_each_actor_role(self):
        for actor, expected in (
            (self.super_admin, UserRole.SUPER_ADMIN),
            (self.admin, UserRole.COMPANY_ADMIN),
            (self.bm, UserRole.BUILDING_MANAGER),
            (self.cust_user, UserRole.CUSTOMER_USER),
        ):
            scope = snapshot_actor_scope(actor)
            self.assertEqual(
                scope.get("role"),
                expected,
                f"actor_scope snapshot for {actor.email} dropped role; got {scope!r}",
            )

    def test_snapshot_is_empty_for_anonymous(self):
        self.assertEqual(snapshot_actor_scope(None), {})
