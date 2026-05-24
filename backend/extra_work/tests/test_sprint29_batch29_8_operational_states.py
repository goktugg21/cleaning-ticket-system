"""
Sprint 29 Batch 29.8 — operational states (IN_PROGRESS / COMPLETED).

Covers the four phases of the batch:

  Phase A: status enum + migration applied cleanly (implicit — the
           Django test runner builds the test DB by applying every
           migration, including 0005_sprint29_batch29_8_operational_states).
  Phase B: state-machine transitions and permission gates.
  Phase C: STAFF scope reuses scope_tickets_for via spawned-ticket join.
  Phase D: dashboard `active` count includes CUSTOMER_APPROVED.
  Phase E: auto-transition hook drives CUSTOMER_APPROVED -> IN_PROGRESS
           on first ticket entering IN_PROGRESS; IN_PROGRESS ->
           COMPLETED when all spawned tickets are terminal.

The tests pin both happy paths and the safety net (STAFF can't drive
provider-only transitions; cascade-cancel doesn't touch ticket rows;
auto-sync swallows errors).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import StaffProfile, UserRole
from buildings.models import (
    Building,
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from extra_work.models import (
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
from extra_work.scoping import scope_extra_work_for
from extra_work.state_machine import (
    ALLOWED_TRANSITIONS,
    SYSTEM_AUTO_TRANSITIONS,
    TransitionError,
    apply_transition as ew_apply_transition,
)
from tickets.models import Ticket, TicketStatus, TicketStatusHistory
from tickets.state_machine import apply_transition as ticket_apply_transition


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
TRANSITION_URL = "/api/extra-work/{ew_id}/transition/"
STATS_URL = "/api/extra-work/stats/"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class _OperationalFixtureMixin:
    """
    Shared seed:
      * Provider company + one building + one customer.
      * SUPER_ADMIN, COMPANY_ADMIN, BUILDING_MANAGER, STAFF (BSV BUILDING_READ),
        CUSTOMER_USER actors.
      * Service catalog + one service.
      * An EW in CUSTOMER_APPROVED with TWO spawned tickets (cart-item
        path) both in OPEN. Tests can transition tickets to drive the
        auto-sync hook.
    """

    @classmethod
    def _setup_fixture(cls, suffix: str = "29-8"):
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
        cls.manager = _mk(f"mgr-{suffix}@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager, building=cls.building
        )
        cls.staff = _mk(f"staff-{suffix}@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.building
        )

        cls.cust_user = _mk(
            f"cust-{suffix}@example.com", UserRole.CUSTOMER_USER
        )
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership, building=cls.building
        )

        cls.service_cat = ServiceCategory.objects.create(
            name=f"Cat {suffix}"
        )
        cls.service = Service.objects.create(
            category=cls.service_cat,
            name=f"Service {suffix}",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )

        cls.ew = ExtraWorkRequest.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.cust_user,
            title=f"EW {suffix}",
            description="seed",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            routing_decision=ExtraWorkRoutingDecision.INSTANT,
        )

        cls.line_a = ExtraWorkRequestItem.objects.create(
            extra_work_request=cls.ew,
            service=cls.service,
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=date(2026, 6, 1),
        )
        cls.line_b = ExtraWorkRequestItem.objects.create(
            extra_work_request=cls.ew,
            service=cls.service,
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=date(2026, 6, 2),
        )

        cls.ticket_a = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.admin,
            title="Ticket A",
            description="seed",
            status=TicketStatus.OPEN,
            extra_work_request_item=cls.line_a,
        )
        cls.ticket_b = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.admin,
            title="Ticket B",
            description="seed",
            status=TicketStatus.OPEN,
            extra_work_request_item=cls.line_b,
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _refresh_ew(self):
        self.ew.refresh_from_db()
        return self.ew


# ---------------------------------------------------------------------------
# 1. Migration applies cleanly + ALLOWED_TRANSITIONS / SYSTEM_AUTO_TRANSITIONS
#    membership sanity.
# ---------------------------------------------------------------------------
class MigrationAndConstantsTests(_OperationalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="29-8-mig")

    def test_new_status_choices_round_trip(self):
        # The migration applied successfully iff we can store +
        # round-trip an IN_PROGRESS / COMPLETED value on the model.
        self.ew.status = ExtraWorkStatus.IN_PROGRESS
        self.ew.save(update_fields=["status"])
        self._refresh_ew()
        self.assertEqual(self.ew.status, ExtraWorkStatus.IN_PROGRESS)
        self.ew.status = ExtraWorkStatus.COMPLETED
        self.ew.save(update_fields=["status"])
        self._refresh_ew()
        self.assertEqual(self.ew.status, ExtraWorkStatus.COMPLETED)

    def test_allowed_transitions_contains_new_pairs(self):
        new_pairs = {
            (ExtraWorkStatus.CUSTOMER_APPROVED, ExtraWorkStatus.IN_PROGRESS),
            (ExtraWorkStatus.IN_PROGRESS, ExtraWorkStatus.COMPLETED),
            (ExtraWorkStatus.IN_PROGRESS, ExtraWorkStatus.CANCELLED),
            (ExtraWorkStatus.COMPLETED, ExtraWorkStatus.IN_PROGRESS),
        }
        self.assertTrue(new_pairs.issubset(ALLOWED_TRANSITIONS))

    def test_system_auto_transitions_pair_membership(self):
        self.assertEqual(
            SYSTEM_AUTO_TRANSITIONS,
            {
                (
                    ExtraWorkStatus.CUSTOMER_APPROVED,
                    ExtraWorkStatus.IN_PROGRESS,
                ),
                (ExtraWorkStatus.IN_PROGRESS, ExtraWorkStatus.COMPLETED),
            },
        )


# ---------------------------------------------------------------------------
# 2. Permission gates on the new transitions.
# ---------------------------------------------------------------------------
class TransitionPermissionTests(_OperationalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="29-8-perm")

    def test_provider_roles_can_drive_customer_approved_to_in_progress(self):
        for actor in (self.super_admin, self.admin, self.manager):
            self.ew.refresh_from_db()
            self.ew.status = ExtraWorkStatus.CUSTOMER_APPROVED
            self.ew.save(update_fields=["status"])
            response = self._api(actor).post(
                TRANSITION_URL.format(ew_id=self.ew.id),
                {"to_status": ExtraWorkStatus.IN_PROGRESS},
                format="json",
            )
            self.assertEqual(
                response.status_code, status.HTTP_200_OK, response.data
            )
            self.assertEqual(
                response.data["status"], ExtraWorkStatus.IN_PROGRESS
            )

    def test_staff_cannot_drive_customer_approved_to_in_progress(self):
        # STAFF cannot drive operational-segment transitions manually.
        # The endpoint returns 404 (out-of-scope before the transition
        # is even evaluated) until a spawned-ticket join makes the EW
        # visible, after which the state-machine returns 400
        # forbidden_transition. Either is an acceptable refusal.
        response = self._api(self.staff).post(
            TRANSITION_URL.format(ew_id=self.ew.id),
            {"to_status": ExtraWorkStatus.IN_PROGRESS},
            format="json",
        )
        self.assertIn(
            response.status_code,
            (
                status.HTTP_400_BAD_REQUEST,
                status.HTTP_403_FORBIDDEN,
                status.HTTP_404_NOT_FOUND,
            ),
        )
        self._refresh_ew()
        self.assertEqual(self.ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)

    def test_customer_user_cannot_drive_in_progress(self):
        response = self._api(self.cust_user).post(
            TRANSITION_URL.format(ew_id=self.ew.id),
            {"to_status": ExtraWorkStatus.IN_PROGRESS},
            format="json",
        )
        self.assertIn(
            response.status_code,
            (
                status.HTTP_400_BAD_REQUEST,
                status.HTTP_403_FORBIDDEN,
                status.HTTP_404_NOT_FOUND,
            ),
        )

    def test_in_progress_to_cancelled_requires_override_reason(self):
        self.ew.status = ExtraWorkStatus.IN_PROGRESS
        self.ew.save(update_fields=["status"])
        # Missing override_reason -> 400 override_reason_required.
        response = self._api(self.super_admin).post(
            TRANSITION_URL.format(ew_id=self.ew.id),
            {"to_status": ExtraWorkStatus.CANCELLED},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("code"), "override_reason_required")
        self._refresh_ew()
        self.assertEqual(self.ew.status, ExtraWorkStatus.IN_PROGRESS)

    def test_completed_to_in_progress_requires_override_reason(self):
        self.ew.status = ExtraWorkStatus.COMPLETED
        self.ew.save(update_fields=["status"])
        response = self._api(self.super_admin).post(
            TRANSITION_URL.format(ew_id=self.ew.id),
            {"to_status": ExtraWorkStatus.IN_PROGRESS},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("code"), "override_reason_required")
        self._refresh_ew()
        self.assertEqual(self.ew.status, ExtraWorkStatus.COMPLETED)

        # With reason supplied: 200.
        response = self._api(self.super_admin).post(
            TRANSITION_URL.format(ew_id=self.ew.id),
            {
                "to_status": ExtraWorkStatus.IN_PROGRESS,
                "is_override": True,
                "override_reason": "wrongly completed",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self._refresh_ew()
        self.assertEqual(self.ew.status, ExtraWorkStatus.IN_PROGRESS)


# ---------------------------------------------------------------------------
# 3. Auto-trigger: first spawned ticket entering IN_PROGRESS advances EW.
# ---------------------------------------------------------------------------
class AutoTriggerFirstInProgressTests(_OperationalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="29-8-auto1")

    def test_first_ticket_in_progress_advances_ew(self):
        ticket_apply_transition(
            self.ticket_a, self.admin, TicketStatus.IN_PROGRESS, note="go"
        )
        self._refresh_ew()
        self.assertEqual(self.ew.status, ExtraWorkStatus.IN_PROGRESS)

        history = ExtraWorkStatusHistory.objects.filter(
            extra_work=self.ew,
            new_status=ExtraWorkStatus.IN_PROGRESS,
        ).order_by("-created_at").first()
        self.assertIsNotNone(history)
        # System-driven transition: changed_by is None.
        self.assertIsNone(history.changed_by_id)
        self.assertIn("Sprint 29 Batch 29.8", history.note)

    def test_second_ticket_in_progress_is_idempotent(self):
        ticket_apply_transition(
            self.ticket_a, self.admin, TicketStatus.IN_PROGRESS, note="go"
        )
        ew_history_count = ExtraWorkStatusHistory.objects.filter(
            extra_work=self.ew,
            new_status=ExtraWorkStatus.IN_PROGRESS,
        ).count()
        # Drive second ticket; EW is already IN_PROGRESS, no new EW
        # history row should be written (the hook short-circuits when
        # ew.status is not CUSTOMER_APPROVED).
        ticket_apply_transition(
            self.ticket_b, self.admin, TicketStatus.IN_PROGRESS, note="go"
        )
        self._refresh_ew()
        self.assertEqual(self.ew.status, ExtraWorkStatus.IN_PROGRESS)
        self.assertEqual(
            ExtraWorkStatusHistory.objects.filter(
                extra_work=self.ew,
                new_status=ExtraWorkStatus.IN_PROGRESS,
            ).count(),
            ew_history_count,
        )


# ---------------------------------------------------------------------------
# 4. Auto-trigger: all-terminal tickets advance EW to COMPLETED.
# ---------------------------------------------------------------------------
class AutoTriggerAllTerminalTests(_OperationalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="29-8-auto2")

    def _drive_ticket_to_approved(self, ticket):
        """Walk a ticket OPEN -> IN_PROGRESS -> WAITING_CUSTOMER_APPROVAL
        -> APPROVED via the provider operator path.

        `apply_transition` returns the locked row; we re-bind so the
        next call sees the updated status (the passed object's in-
        memory `.status` is not mutated).
        """
        ticket = ticket_apply_transition(
            ticket, self.admin, TicketStatus.IN_PROGRESS, note="start"
        )
        ticket.refresh_from_db()
        ticket = ticket_apply_transition(
            ticket,
            self.admin,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            note="done — please review",
        )
        ticket.refresh_from_db()
        ticket_apply_transition(
            ticket,
            self.cust_user,
            TicketStatus.APPROVED,
            note="ok",
        )

    def test_ew_stays_in_progress_until_all_terminal(self):
        self._drive_ticket_to_approved(self.ticket_a)
        self._refresh_ew()
        # ticket_a is APPROVED but ticket_b is still OPEN — not all
        # siblings terminal -> EW stays IN_PROGRESS.
        self.assertEqual(self.ew.status, ExtraWorkStatus.IN_PROGRESS)

        self._drive_ticket_to_approved(self.ticket_b)
        self._refresh_ew()
        self.assertEqual(self.ew.status, ExtraWorkStatus.COMPLETED)

        # COMPLETED history row exists, system-driven (changed_by=None).
        completed_row = (
            ExtraWorkStatusHistory.objects.filter(
                extra_work=self.ew,
                new_status=ExtraWorkStatus.COMPLETED,
            )
            .order_by("-created_at")
            .first()
        )
        self.assertIsNotNone(completed_row)
        self.assertIsNone(completed_row.changed_by_id)


# ---------------------------------------------------------------------------
# 5. Auto-sync is fail-safe: a soft-deleted EW between calls does not break
#    the ticket transition; the hook logs and continues.
# ---------------------------------------------------------------------------
class AutoSyncFailSafeTests(_OperationalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="29-8-failsafe")

    def test_soft_deleted_ew_does_not_break_ticket_transition(self):
        # Soft-delete EW; hook should bail quietly.
        from django.utils import timezone as dj_tz

        self.ew.deleted_at = dj_tz.now()
        self.ew.save(update_fields=["deleted_at"])
        # Should NOT raise even though parent EW is missing from the
        # active set; the ticket transition itself must still succeed.
        ticket_apply_transition(
            self.ticket_a, self.admin, TicketStatus.IN_PROGRESS, note="go"
        )
        self.ticket_a.refresh_from_db()
        self.assertEqual(self.ticket_a.status, TicketStatus.IN_PROGRESS)
        # EW status unchanged (still CUSTOMER_APPROVED; soft-deleted).
        self._refresh_ew()
        self.assertEqual(self.ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)


# ---------------------------------------------------------------------------
# 6. STAFF scope: parent EW is always invisible — P0 staff-privacy decision
#    (2026-05-20 A4). The original Sprint 29 Batch 29.8 widening (STAFF sees
#    every EW whose spawned ticket they can see) was reverted once it was
#    proven the EW + Proposal serializers leaked provider-only fields to
#    STAFF. Operational visibility for STAFF lives on the spawned Ticket
#    via `Ticket.extra_work_origin` instead — that field carries a safe
#    subset (id / title / status / item_id / service_name) and never the
#    pricing or internal-note fields. Regression coverage of all EW +
#    Proposal endpoints returning 404 to STAFF lives in
#    `test_staff_privacy_p0.py`.
# ---------------------------------------------------------------------------
class StaffScopeAlwaysEmptyTests(_OperationalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="29-8-stafftrue")

    def test_staff_never_sees_parent_ew_even_with_spawned_ticket_in_scope(self):
        # STAFF holds BSV(BUILDING_READ) on the seeded building so the
        # spawned ticket IS in their `scope_tickets_for` queryset. Pre-fix
        # this leaked the parent EW; post-fix STAFF sees zero EWs.
        self.assertFalse(scope_extra_work_for(self.staff).exists())


# ---------------------------------------------------------------------------
# 7. STAFF scope: negative — no building overlap -> empty queryset.
# ---------------------------------------------------------------------------
class StaffScopeNegativeTests(_OperationalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="29-8-stafffalse")

    def test_staff_without_building_overlap_sees_nothing(self):
        other_company = Company.objects.create(
            name="Other Co", slug="other-29-8-neg"
        )
        other_building = Building.objects.create(
            company=other_company, name="Other Bld"
        )
        outsider = _mk("outsider-29-8@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=outsider)
        BuildingStaffVisibility.objects.create(
            user=outsider, building=other_building
        )
        self.assertFalse(scope_extra_work_for(outsider).exists())


# ---------------------------------------------------------------------------
# 8. Dashboard `active` count includes CUSTOMER_APPROVED (operational entry).
# ---------------------------------------------------------------------------
class DashboardActiveCountTests(_OperationalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="29-8-dash")

    def test_customer_approved_counts_as_active(self):
        # The seeded EW is in CUSTOMER_APPROVED. Pre-29.8 this would
        # have been counted terminal and `active` would have excluded it;
        # post-29.8 it MUST count as active.
        response = self._api(self.super_admin).get(STATS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data["active"], 1)
        # The same EW also shows up in by_status under CUSTOMER_APPROVED.
        self.assertGreaterEqual(
            response.data["by_status"].get(
                ExtraWorkStatus.CUSTOMER_APPROVED, 0
            ),
            1,
        )


# ---------------------------------------------------------------------------
# 9. Cascade-cancel: EW IN_PROGRESS with active spawned tickets can be
#    cancelled by an admin; the tickets stay in their statuses (TicketStatus
#    has no CANCELLED to fall back to, and 29.8 explicitly does NOT
#    auto-cancel tickets when their parent EW is cancelled).
# ---------------------------------------------------------------------------
class CascadeCancelTests(_OperationalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="29-8-cancel")

    def test_admin_cancels_in_progress_ew_with_active_tickets(self):
        # Drive ticket_a to IN_PROGRESS (triggers EW -> IN_PROGRESS).
        ticket_apply_transition(
            self.ticket_a, self.admin, TicketStatus.IN_PROGRESS, note="go"
        )
        self._refresh_ew()
        self.assertEqual(self.ew.status, ExtraWorkStatus.IN_PROGRESS)

        # SUPER_ADMIN cancels IN_PROGRESS with mandatory override_reason.
        response = self._api(self.super_admin).post(
            TRANSITION_URL.format(ew_id=self.ew.id),
            {
                "to_status": ExtraWorkStatus.CANCELLED,
                "is_override": True,
                "override_reason": "customer changed mind",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self._refresh_ew()
        self.assertEqual(self.ew.status, ExtraWorkStatus.CANCELLED)

        # Tickets stay in their statuses — no auto-cancel.
        self.ticket_a.refresh_from_db()
        self.ticket_b.refresh_from_db()
        self.assertEqual(self.ticket_a.status, TicketStatus.IN_PROGRESS)
        self.assertEqual(self.ticket_b.status, TicketStatus.OPEN)


# ---------------------------------------------------------------------------
# 10. Manual provider drive: CUSTOMER_APPROVED -> IN_PROGRESS via direct
#     `ew_apply_transition` (not the API) writes a non-system history row.
# ---------------------------------------------------------------------------
class ManualProviderTransitionTests(_OperationalFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="29-8-manual")

    def test_admin_manual_advance_records_actor(self):
        ew_apply_transition(
            self.ew,
            self.admin,
            ExtraWorkStatus.IN_PROGRESS,
            note="manual go",
        )
        self._refresh_ew()
        self.assertEqual(self.ew.status, ExtraWorkStatus.IN_PROGRESS)
        history = (
            ExtraWorkStatusHistory.objects.filter(
                extra_work=self.ew,
                new_status=ExtraWorkStatus.IN_PROGRESS,
            )
            .order_by("-created_at")
            .first()
        )
        self.assertIsNotNone(history)
        self.assertEqual(history.changed_by_id, self.admin.id)
