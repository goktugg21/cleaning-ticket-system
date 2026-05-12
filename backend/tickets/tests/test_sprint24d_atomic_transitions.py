"""
Sprint 24D — atomic state transitions + filterset for the
StaffAssignmentRequest review/cancel paths.

Sprint 24C's review of the cancel flow flagged two non-blocking
concerns:

  1. TicketDetailPage discovered pending requests by walking only the
     first page of `listStaffAssignmentRequests()`, so a staff user
     with >25 historical requests could fail to find their own
     PENDING row.
  2. approve / reject / cancel were not wrapped in a row-lock, so a
     near-simultaneous "admin approve" + "staff cancel" could let the
     loser silently overwrite the winner.

Sprint 24D fixes both:

  - Wraps `_review` (approve/reject) and `cancel` in
    `transaction.atomic()` blocks with `select_for_update()` on the
    StaffAssignmentRequest row. Permission checks stay outside the
    lock; the status check + write form one critical section.
  - Adds `filterset_fields = ["status", "ticket", "staff"]` to the
    viewset so the frontend can target `?ticket=<id>&status=PENDING`
    and get at most one row back (the duplicate guard allows one
    PENDING per (staff, ticket)).

These tests pin both contracts so any future refactor that drops the
atomic block or the filterset gets caught.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
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
)
from tickets.models import (
    AssignmentRequestStatus,
    StaffAssignmentRequest,
    Ticket,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class AtomicTransitionTests(TestCase):
    """
    Pin the sequential stale-state protection that the atomic + lock
    refactor must preserve. We don't attempt true concurrent threads —
    the row lock is a no-op on SQLite and Django's TestCase wraps each
    test in a transaction anyway. Sequential calls are the realistic
    way to exercise the logic; the value of `select_for_update` is
    that the SAME ordering holds under PostgreSQL contention in
    production.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Co", slug="co")
        cls.building = Building.objects.create(
            company=cls.company, name="Building 1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            "super@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )
        cls.manager = _mk("mgr@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager, building=cls.building
        )

        cls.staff = _mk("staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.building
        )

        # Anchor ticket — recreated per test, but a class-level row is
        # cheaper for tests that don't mutate it.
        cls.ticket = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.admin,
            title="Atomic ticket",
            description="x",
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _pending(self, ticket=None):
        return StaffAssignmentRequest.objects.create(
            staff=self.staff, ticket=ticket or self.ticket
        )

    # ---- approve → cancel races (admin wins) --------------------------

    def test_admin_approve_blocks_subsequent_cancel(self):
        """If the admin approves first, a later staff cancel must 400."""
        req = self._pending()
        approve = self._api(self.admin).post(
            f"/api/staff-assignment-requests/{req.id}/approve/",
            {"reviewer_note": "approved first"},
            format="json",
        )
        self.assertEqual(approve.status_code, 200, approve.data)
        cancel = self._api(self.staff).post(
            f"/api/staff-assignment-requests/{req.id}/cancel/"
        )
        self.assertEqual(cancel.status_code, 400)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.APPROVED)
        # The approve note survived the failed cancel attempt.
        self.assertEqual(req.reviewer_note, "approved first")

    # ---- cancel → approve races (staff wins) --------------------------

    def test_staff_cancel_blocks_subsequent_approve(self):
        """If the staff cancels first, a later admin approve must 400."""
        req = self._pending()
        cancel = self._api(self.staff).post(
            f"/api/staff-assignment-requests/{req.id}/cancel/"
        )
        self.assertEqual(cancel.status_code, 200, cancel.data)
        approve = self._api(self.admin).post(
            f"/api/staff-assignment-requests/{req.id}/approve/",
            {"reviewer_note": "approved second"},
            format="json",
        )
        self.assertEqual(approve.status_code, 400)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.CANCELLED)
        # The cancel left the row's reviewer_note empty — the failed
        # approve attempt did not bleed its note into the row.
        self.assertEqual(req.reviewer_note, "")

    # ---- cancel → reject races (staff wins) ---------------------------

    def test_staff_cancel_blocks_subsequent_reject(self):
        req = self._pending()
        cancel = self._api(self.staff).post(
            f"/api/staff-assignment-requests/{req.id}/cancel/"
        )
        self.assertEqual(cancel.status_code, 200)
        reject = self._api(self.admin).post(
            f"/api/staff-assignment-requests/{req.id}/reject/",
            {"reviewer_note": "rejected"},
            format="json",
        )
        self.assertEqual(reject.status_code, 400)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.CANCELLED)
        self.assertEqual(req.reviewer_note, "")

    # ---- reject → cancel races (admin wins) ---------------------------

    def test_admin_reject_blocks_subsequent_cancel(self):
        req = self._pending()
        reject = self._api(self.admin).post(
            f"/api/staff-assignment-requests/{req.id}/reject/",
            {"reviewer_note": "rejected first"},
            format="json",
        )
        self.assertEqual(reject.status_code, 200)
        cancel = self._api(self.staff).post(
            f"/api/staff-assignment-requests/{req.id}/cancel/"
        )
        self.assertEqual(cancel.status_code, 400)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.REJECTED)

    # ---- reviewer_note still persists on the winning act --------------

    def test_reviewer_note_still_persists_after_atomic_refactor(self):
        """Sprint 24B contract — note round-trips on approve/reject."""
        req = self._pending()
        note = "Sprint 24B compat — note still flows through atomic block."
        response = self._api(self.admin).post(
            f"/api/staff-assignment-requests/{req.id}/approve/",
            {"reviewer_note": note},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["reviewer_note"], note)
        req.refresh_from_db()
        self.assertEqual(req.reviewer_note, note)


class FiltersetTests(TestCase):
    """
    Sprint 24D — `filterset_fields = ["status", "ticket", "staff"]`
    lets the TicketDetailPage discover a staff user's pending request
    on a specific ticket without walking pages of unrelated rows.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Co", slug="co")
        cls.b1 = Building.objects.create(company=cls.company, name="B1")
        cls.b2 = Building.objects.create(company=cls.company, name="B2")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer", building=cls.b1
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.b1
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.b2
        )

        cls.admin = _mk("admin@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

        cls.staff = _mk("staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.b1
        )
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.b2
        )

        cls.ticket_a = Ticket.objects.create(
            company=cls.company,
            building=cls.b1,
            customer=cls.customer,
            created_by=cls.admin,
            title="Ticket A",
            description="x",
        )
        cls.ticket_b = Ticket.objects.create(
            company=cls.company,
            building=cls.b2,
            customer=cls.customer,
            created_by=cls.admin,
            title="Ticket B",
            description="x",
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_staff_filters_by_ticket_and_status_returns_single_pending(self):
        """
        The discovery contract: with a PENDING request on ticket_a
        and a CANCELLED row on ticket_a from the past, a STAFF call
        with `?ticket=<a>&status=PENDING` returns ONLY the pending row.
        """
        old = StaffAssignmentRequest.objects.create(
            staff=self.staff,
            ticket=self.ticket_a,
            status=AssignmentRequestStatus.CANCELLED,
        )
        current = StaffAssignmentRequest.objects.create(
            staff=self.staff,
            ticket=self.ticket_a,
            status=AssignmentRequestStatus.PENDING,
        )
        # Also a PENDING row on a DIFFERENT ticket — must not leak in.
        unrelated = StaffAssignmentRequest.objects.create(
            staff=self.staff,
            ticket=self.ticket_b,
            status=AssignmentRequestStatus.PENDING,
        )

        response = self._api(self.staff).get(
            "/api/staff-assignment-requests/"
            f"?ticket={self.ticket_a.id}&status=PENDING"
        )
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.data["results"]]
        self.assertEqual(ids, [current.id])
        self.assertNotIn(old.id, ids)
        self.assertNotIn(unrelated.id, ids)

    def test_staff_filterset_respects_role_scope(self):
        """
        Even with filters, the queryset role-narrow stays in force —
        a STAFF user only sees their own rows regardless of the
        `staff=` filter value.
        """
        other = _mk("other-staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=other)
        BuildingStaffVisibility.objects.create(user=other, building=self.b1)
        StaffAssignmentRequest.objects.create(
            staff=other, ticket=self.ticket_a
        )
        # Acting as `self.staff`, asking for the other staff's id is
        # silently filtered to their own rows by the queryset.
        response = self._api(self.staff).get(
            "/api/staff-assignment-requests/"
            f"?staff={other.id}&status=PENDING"
        )
        self.assertEqual(response.status_code, 200)
        # No rows because self.staff has no PENDING; and `other`'s row
        # is hidden by the role-scoped queryset.
        self.assertEqual(response.data["results"], [])

    def test_admin_filter_by_status_returns_only_matching_rows(self):
        """COMPANY_ADMIN filtering by status returns the right subset."""
        StaffAssignmentRequest.objects.create(
            staff=self.staff,
            ticket=self.ticket_a,
            status=AssignmentRequestStatus.PENDING,
        )
        approved = StaffAssignmentRequest.objects.create(
            staff=self.staff,
            ticket=self.ticket_b,
            status=AssignmentRequestStatus.APPROVED,
        )
        response = self._api(self.admin).get(
            "/api/staff-assignment-requests/?status=APPROVED"
        )
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.data["results"]]
        self.assertEqual(ids, [approved.id])
