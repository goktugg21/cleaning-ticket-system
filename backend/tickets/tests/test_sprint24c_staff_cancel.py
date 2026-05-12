"""
Sprint 24C — STAFF self-cancellation of a PENDING assignment request.

Pins the `/api/staff-assignment-requests/<id>/cancel/` contract:

  - STAFF can cancel their own PENDING request; status flips to
    CANCELLED and persists.
  - STAFF cannot cancel another STAFF user's request — the viewset
    queryset hides it (404).
  - STAFF cannot cancel an APPROVED / REJECTED / CANCELLED request
    (400 — not PENDING).
  - CUSTOMER_USER cannot cancel (403, class-level role gate).
  - COMPANY_ADMIN / BUILDING_MANAGER / SUPER_ADMIN cannot use the
    self-cancel endpoint (it is STAFF-only by design; admins act
    via reject if they want to deny the request).
  - Cross-company STAFF (visibility somewhere else) cannot cancel
    a request that doesn't belong to them — 404.
  - After cancellation, the row cannot be approved or rejected
    (400 — not PENDING).
  - STAFF can submit a fresh request for the same ticket after
    cancelling the previous one — Sprint 23A's duplicate guard
    only fires on PENDING rows.
  - Sprint 24B reviewer_note approve/reject flow is unchanged
    (a separate file exercises that; we re-pin a single happy
    path here as defence in depth).
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
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from tickets.models import (
    AssignmentRequestStatus,
    StaffAssignmentRequest,
    Ticket,
    TicketStaffAssignment,
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


class StaffSelfCancelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="Co A", slug="co-a")
        cls.company_b = Company.objects.create(name="Co B", slug="co-b")
        cls.building_a = Building.objects.create(
            company=cls.company_a, name="Building A1"
        )
        cls.building_b = Building.objects.create(
            company=cls.company_b, name="Building B1"
        )
        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Customer A", building=cls.building_a
        )
        cls.customer_b = Customer.objects.create(
            company=cls.company_b, name="Customer B", building=cls.building_b
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a, building=cls.building_a
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_b, building=cls.building_b
        )

        cls.super_admin = _mk(
            "super@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin_a = _mk("admin-a@example.com", UserRole.COMPANY_ADMIN)
        cls.admin_b = _mk("admin-b@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin_a, company=cls.company_a
        )
        CompanyUserMembership.objects.create(
            user=cls.admin_b, company=cls.company_b
        )

        cls.manager_a = _mk("mgr-a@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager_a, building=cls.building_a
        )

        cls.staff_a = _mk("staff-a@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_a)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_a, building=cls.building_a
        )

        cls.staff_b = _mk("staff-b@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_b)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_b, building=cls.building_b
        )

        cls.cust_user_a = _mk("cust-a@example.com", UserRole.CUSTOMER_USER)
        mem_a = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_user_a
        )
        CustomerUserBuildingAccess.objects.create(
            membership=mem_a, building=cls.building_a
        )

        cls.ticket_a = Ticket.objects.create(
            company=cls.company_a,
            building=cls.building_a,
            customer=cls.customer_a,
            created_by=cls.cust_user_a,
            title="Ticket A",
            description="x",
        )
        cls.ticket_b = Ticket.objects.create(
            company=cls.company_b,
            building=cls.building_b,
            customer=cls.customer_b,
            created_by=cls.admin_b,
            title="Ticket B",
            description="x",
        )

    def _api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def _make_pending(self, staff, ticket):
        return StaffAssignmentRequest.objects.create(staff=staff, ticket=ticket)

    def _cancel_url(self, pk):
        return f"/api/staff-assignment-requests/{pk}/cancel/"

    # ---- Happy path ----------------------------------------------------

    def test_staff_can_cancel_own_pending_request(self):
        req = self._make_pending(self.staff_a, self.ticket_a)
        response = self._api(self.staff_a).post(self._cancel_url(req.id))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data["status"], AssignmentRequestStatus.CANCELLED
        )
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.CANCELLED)
        # Cancellation is NOT a review — no reviewer is stamped.
        self.assertIsNone(req.reviewed_by)
        self.assertIsNone(req.reviewed_at)
        self.assertEqual(req.reviewer_note, "")
        # No TicketStaffAssignment row created (sanity check vs. approve path).
        self.assertFalse(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket_a, user=self.staff_a
            ).exists()
        )

    # ---- Staff cannot cancel another staff's request -------------------

    def test_staff_cannot_cancel_other_staffs_request(self):
        req = self._make_pending(self.staff_a, self.ticket_a)
        # staff_b's queryset doesn't include staff_a's request → 404.
        response = self._api(self.staff_b).post(self._cancel_url(req.id))
        self.assertEqual(response.status_code, 404)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.PENDING)

    # ---- Wrong status -------------------------------------------------

    def test_staff_cannot_cancel_approved_request(self):
        req = self._make_pending(self.staff_a, self.ticket_a)
        req.status = AssignmentRequestStatus.APPROVED
        req.save(update_fields=["status"])
        response = self._api(self.staff_a).post(self._cancel_url(req.id))
        self.assertEqual(response.status_code, 400)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.APPROVED)

    def test_staff_cannot_cancel_rejected_request(self):
        req = self._make_pending(self.staff_a, self.ticket_a)
        req.status = AssignmentRequestStatus.REJECTED
        req.save(update_fields=["status"])
        response = self._api(self.staff_a).post(self._cancel_url(req.id))
        self.assertEqual(response.status_code, 400)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.REJECTED)

    def test_staff_cannot_cancel_already_cancelled_request(self):
        req = self._make_pending(self.staff_a, self.ticket_a)
        # First cancel succeeds.
        first = self._api(self.staff_a).post(self._cancel_url(req.id))
        self.assertEqual(first.status_code, 200)
        # Second attempt — not pending any more.
        second = self._api(self.staff_a).post(self._cancel_url(req.id))
        self.assertEqual(second.status_code, 400)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.CANCELLED)

    # ---- Non-STAFF roles cannot self-cancel ---------------------------

    def test_customer_user_cannot_cancel(self):
        req = self._make_pending(self.staff_a, self.ticket_a)
        response = self._api(self.cust_user_a).post(self._cancel_url(req.id))
        # CUSTOMER_USER hits the role gate (403); even if it didn't,
        # the queryset returns none() so the row would 404. Either is
        # an acceptable rejection — both prove the customer cannot
        # cancel staff requests.
        self.assertIn(response.status_code, (403, 404))
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.PENDING)

    def test_company_admin_cannot_self_cancel(self):
        req = self._make_pending(self.staff_a, self.ticket_a)
        response = self._api(self.admin_a).post(self._cancel_url(req.id))
        self.assertEqual(response.status_code, 403)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.PENDING)

    def test_building_manager_cannot_self_cancel(self):
        req = self._make_pending(self.staff_a, self.ticket_a)
        response = self._api(self.manager_a).post(self._cancel_url(req.id))
        self.assertEqual(response.status_code, 403)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.PENDING)

    def test_super_admin_cannot_self_cancel(self):
        """
        Self-cancel is STAFF-only. SUPER_ADMIN can still REJECT the
        same request through the existing Sprint 23A endpoint — they
        just cannot use the staff self-cancel path, which is a
        deliberate scope choice (the rejected vs. cancelled
        distinction stays auditable).
        """
        req = self._make_pending(self.staff_a, self.ticket_a)
        response = self._api(self.super_admin).post(self._cancel_url(req.id))
        self.assertEqual(response.status_code, 403)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.PENDING)

    # ---- After cancellation — review path rejects ---------------------

    def test_cancelled_request_cannot_be_approved(self):
        req = self._make_pending(self.staff_a, self.ticket_a)
        cancel = self._api(self.staff_a).post(self._cancel_url(req.id))
        self.assertEqual(cancel.status_code, 200)
        approve = self._api(self.admin_a).post(
            f"/api/staff-assignment-requests/{req.id}/approve/",
            {"reviewer_note": "should not land"},
            format="json",
        )
        # _review() checks status != PENDING and returns 400.
        self.assertEqual(approve.status_code, 400)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.CANCELLED)
        self.assertEqual(req.reviewer_note, "")

    def test_cancelled_request_cannot_be_rejected(self):
        req = self._make_pending(self.staff_a, self.ticket_a)
        cancel = self._api(self.staff_a).post(self._cancel_url(req.id))
        self.assertEqual(cancel.status_code, 200)
        reject = self._api(self.admin_a).post(
            f"/api/staff-assignment-requests/{req.id}/reject/",
            {"reviewer_note": "should not land"},
            format="json",
        )
        self.assertEqual(reject.status_code, 400)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.CANCELLED)

    # ---- After cancellation — re-request is allowed -------------------

    def test_staff_can_request_again_after_cancelling(self):
        """
        Sprint 23A's duplicate guard fires only on PENDING rows. A
        CANCELLED row should not block a fresh request for the same
        ticket — the staff user may legitimately change their mind.
        """
        first = self._make_pending(self.staff_a, self.ticket_a)
        cancel = self._api(self.staff_a).post(self._cancel_url(first.id))
        self.assertEqual(cancel.status_code, 200)

        # Submit a NEW request through the create endpoint.
        recreate = self._api(self.staff_a).post(
            "/api/staff-assignment-requests/",
            {"ticket": self.ticket_a.id},
            format="json",
        )
        self.assertEqual(recreate.status_code, 201, recreate.data)
        new_id = recreate.data["id"]
        self.assertNotEqual(new_id, first.id)
        self.assertEqual(
            recreate.data["status"], AssignmentRequestStatus.PENDING
        )
        # The old CANCELLED row still exists alongside the new PENDING one.
        self.assertEqual(
            StaffAssignmentRequest.objects.filter(
                ticket=self.ticket_a, staff=self.staff_a
            ).count(),
            2,
        )

    # ---- Cross-company STAFF cannot cancel out-of-scope ---------------

    def test_cross_company_staff_cannot_cancel_other_company_request(self):
        # Company-A staff cancelling a Company-B staff's request → 404.
        req_b = self._make_pending(self.staff_b, self.ticket_b)
        response = self._api(self.staff_a).post(self._cancel_url(req_b.id))
        self.assertEqual(response.status_code, 404)
        req_b.refresh_from_db()
        self.assertEqual(req_b.status, AssignmentRequestStatus.PENDING)

    # ---- Sprint 24B regression: approve still works after Sprint 24C --

    def test_sprint_24b_approve_with_reviewer_note_still_works(self):
        req = self._make_pending(self.staff_a, self.ticket_a)
        note = "Sprint 24B compat — note still persists."
        response = self._api(self.admin_a).post(
            f"/api/staff-assignment-requests/{req.id}/approve/",
            {"reviewer_note": note},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.APPROVED)
        self.assertEqual(req.reviewer_note, note)
        self.assertEqual(req.reviewed_by, self.admin_a)
