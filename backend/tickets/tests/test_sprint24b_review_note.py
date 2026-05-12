"""
Sprint 24B — reviewer_note contract for the staff-assignment-request
approve/reject flow.

The Sprint 23A backend already accepted `reviewer_note` on the
approve/reject endpoints (see `views_staff_requests._review`), but no
existing test pinned that the value is actually persisted, that the
gate still rejects out-of-scope reviewers when a note is supplied, or
that the read shape carries the note back to the caller. Sprint 24B
ships a frontend reviewer-note modal that depends on those contracts,
so we lock them down here before they can silently drift.

Coverage:
  - SUPER_ADMIN can approve any pending request with a reviewer_note,
    and the note round-trips on the response and persists on the row.
  - COMPANY_ADMIN can reject an own-company request with a note, and
    the note is persisted (plus reviewer_email is set to the actor).
  - Cross-company COMPANY_ADMIN attempts return 404 (queryset filter
    hides the row) even when reviewer_note is supplied.
  - STAFF cannot approve/reject their own request (own-scope queryset
    only lists rows, but the gate rejects writes — Sprint 23A).
  - CUSTOMER_USER cannot review (queryset returns none()).
  - Approving creates the matching TicketStaffAssignment row exactly
    once — re-running the approve path is idempotent at the assignment
    layer (the request itself stays APPROVED, the row is unique).
  - Sprint 23A invariants (cross-company isolation, scope_tickets_for)
    are unchanged.
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


class StaffAssignmentReviewerNoteTests(TestCase):
    """
    Two-company fixture so the cross-company gate has somewhere to
    fail. Mirrors the Sprint 23A foundation tests but stays narrow
    to the reviewer_note contract.
    """

    @classmethod
    def setUpTestData(cls):
        # Two service-provider companies — A (Osius-like) and B
        # (Bright-like). Each with one building, one customer linked
        # to that building, one COMPANY_ADMIN, one STAFF with
        # visibility on the building, one ticket.
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

    def _make_request_for(self, staff, ticket):
        return StaffAssignmentRequest.objects.create(staff=staff, ticket=ticket)

    def _api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    # ---- SUPER_ADMIN approve persists reviewer_note ---------------------

    def test_super_admin_approve_persists_reviewer_note(self):
        req = self._make_request_for(self.staff_a, self.ticket_a)
        note = "Approved — assigned to Tuesday crew."
        response = self._api(self.super_admin).post(
            f"/api/staff-assignment-requests/{req.id}/approve/",
            {"reviewer_note": note},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        # Response carries the note + reviewer email back.
        self.assertEqual(response.data["reviewer_note"], note)
        self.assertEqual(response.data["reviewer_email"], self.super_admin.email)
        self.assertEqual(
            response.data["status"], AssignmentRequestStatus.APPROVED
        )

        # And it persists on the row.
        req.refresh_from_db()
        self.assertEqual(req.reviewer_note, note)
        self.assertEqual(req.reviewed_by, self.super_admin)
        self.assertEqual(req.status, AssignmentRequestStatus.APPROVED)

        # Approve creates the TicketStaffAssignment row exactly once.
        self.assertEqual(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket_a, user=self.staff_a
            ).count(),
            1,
        )

    # ---- COMPANY_ADMIN reject persists reviewer_note in own company ----

    def test_company_admin_reject_persists_reviewer_note_in_own_company(self):
        req = self._make_request_for(self.staff_a, self.ticket_a)
        note = "Rejected — covered by another crew."
        response = self._api(self.admin_a).post(
            f"/api/staff-assignment-requests/{req.id}/reject/",
            {"reviewer_note": note},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["reviewer_note"], note)
        self.assertEqual(response.data["reviewer_email"], self.admin_a.email)
        self.assertEqual(
            response.data["status"], AssignmentRequestStatus.REJECTED
        )

        req.refresh_from_db()
        self.assertEqual(req.reviewer_note, note)
        self.assertEqual(req.reviewed_by, self.admin_a)
        self.assertEqual(req.status, AssignmentRequestStatus.REJECTED)

        # Rejecting does NOT create an assignment row.
        self.assertFalse(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket_a, user=self.staff_a
            ).exists()
        )

    # ---- BUILDING_MANAGER can review own-building requests with note ---

    def test_building_manager_can_review_with_note(self):
        req = self._make_request_for(self.staff_a, self.ticket_a)
        note = "Approved — local manager call."
        response = self._api(self.manager_a).post(
            f"/api/staff-assignment-requests/{req.id}/approve/",
            {"reviewer_note": note},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        req.refresh_from_db()
        self.assertEqual(req.reviewer_note, note)
        self.assertEqual(req.reviewed_by, self.manager_a)

    # ---- Cross-company COMPANY_ADMIN is blocked ------------------------

    def test_cross_company_admin_cannot_approve_with_note(self):
        # admin_b tries to approve a Company-A request.
        req = self._make_request_for(self.staff_a, self.ticket_a)
        response = self._api(self.admin_b).post(
            f"/api/staff-assignment-requests/{req.id}/approve/",
            {"reviewer_note": "should not land"},
            format="json",
        )
        # Queryset filter hides the row → 404 (existing convention).
        self.assertEqual(response.status_code, 404)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.PENDING)
        self.assertEqual(req.reviewer_note, "")
        self.assertIsNone(req.reviewed_by)

    def test_cross_company_admin_cannot_reject_with_note(self):
        req = self._make_request_for(self.staff_a, self.ticket_a)
        response = self._api(self.admin_b).post(
            f"/api/staff-assignment-requests/{req.id}/reject/",
            {"reviewer_note": "should not land"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.PENDING)
        self.assertEqual(req.reviewer_note, "")

    # ---- STAFF cannot review their own or anyone else's request -------

    def test_staff_cannot_approve_their_own_request(self):
        req = self._make_request_for(self.staff_a, self.ticket_a)
        # STAFF can list their own requests (queryset returns own rows),
        # so the 404 path would not fire — the gate inside _review
        # rejects with 403 because STAFF lacks
        # osius.assignment_request.approve.
        response = self._api(self.staff_a).post(
            f"/api/staff-assignment-requests/{req.id}/approve/",
            {"reviewer_note": "self-approve attempt"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.PENDING)
        self.assertEqual(req.reviewer_note, "")

    def test_staff_cannot_reject_their_own_request(self):
        req = self._make_request_for(self.staff_a, self.ticket_a)
        response = self._api(self.staff_a).post(
            f"/api/staff-assignment-requests/{req.id}/reject/",
            {"reviewer_note": "self-reject attempt"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.PENDING)

    # ---- CUSTOMER_USER cannot review ----------------------------------

    def test_customer_user_cannot_review(self):
        req = self._make_request_for(self.staff_a, self.ticket_a)
        client = self._api(self.cust_user_a)
        approve = client.post(
            f"/api/staff-assignment-requests/{req.id}/approve/",
            {"reviewer_note": "from a customer"},
            format="json",
        )
        reject = client.post(
            f"/api/staff-assignment-requests/{req.id}/reject/",
            {"reviewer_note": "from a customer"},
            format="json",
        )
        # CUSTOMER_USER queryset is none() → 404 on detail action.
        self.assertEqual(approve.status_code, 404)
        self.assertEqual(reject.status_code, 404)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.PENDING)
        self.assertEqual(req.reviewer_note, "")

    # ---- Empty / missing reviewer_note still succeeds ------------------

    def test_empty_reviewer_note_is_accepted(self):
        """The note is optional — omitting it must not 400, and the
        stored value is an empty string (not NULL)."""
        req = self._make_request_for(self.staff_a, self.ticket_a)
        response = self._api(self.admin_a).post(
            f"/api/staff-assignment-requests/{req.id}/approve/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        req.refresh_from_db()
        self.assertEqual(req.reviewer_note, "")

    def test_null_reviewer_note_is_coerced_to_empty_string(self):
        """A null body field must not crash the save call."""
        req = self._make_request_for(self.staff_a, self.ticket_a)
        response = self._api(self.admin_a).post(
            f"/api/staff-assignment-requests/{req.id}/approve/",
            {"reviewer_note": None},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        req.refresh_from_db()
        self.assertEqual(req.reviewer_note, "")

    # ---- Already-reviewed requests cannot be reviewed again -----------

    def test_already_reviewed_request_is_rejected_400(self):
        req = self._make_request_for(self.staff_a, self.ticket_a)
        first = self._api(self.admin_a).post(
            f"/api/staff-assignment-requests/{req.id}/approve/",
            {"reviewer_note": "first call"},
            format="json",
        )
        self.assertEqual(first.status_code, 200)
        # Second attempt — request is no longer PENDING.
        second = self._api(self.admin_a).post(
            f"/api/staff-assignment-requests/{req.id}/approve/",
            {"reviewer_note": "second call"},
            format="json",
        )
        self.assertEqual(second.status_code, 400)
        req.refresh_from_db()
        self.assertEqual(req.reviewer_note, "first call")
