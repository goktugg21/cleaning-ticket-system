"""
Sprint 25A — pilot-readiness audit: admin/manager direct staff
assignment.

The Sprint 23B `StaffAssignmentRequest` flow only attaches STAFF to a
ticket via a staff-initiated request → admin approve. Pilot
operations need the inverse: an admin or manager assigns a STAFF
member directly without requiring the staff member to file a
request. Sprint 25A adds:

  GET    /api/tickets/<id>/assignable-staff/             (viewset action)
  GET    /api/tickets/<id>/staff-assignments/            list current rows
  POST   /api/tickets/<id>/staff-assignments/  {user_id} → add
  DELETE /api/tickets/<id>/staff-assignments/<user_id>/  remove

These tests pin the contract:
  - SUPER_ADMIN can assign anywhere.
  - COMPANY_ADMIN can assign in own company; cross-company → 404.
  - BUILDING_MANAGER can assign for their building; out-of-building → 404.
  - STAFF cannot assign (self or others) → 403.
  - CUSTOMER_USER cannot assign → 404 (queryset hides the ticket).
  - Target must be STAFF with active profile + BuildingStaffVisibility.
  - Duplicates are idempotent (POST returns 200 with existing row).
  - Delete is idempotent only when the row existed (404 otherwise).
  - Sprint 23B's approve flow remains functional alongside this path.
  - `ticket.assigned_staff` payload (used by the frontend) reflects
    new admin-driven assignments.
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


class DirectStaffAssignmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="Co A", slug="co-a")
        cls.company_b = Company.objects.create(name="Co B", slug="co-b")
        cls.building_a = Building.objects.create(
            company=cls.company_a, name="Building A1"
        )
        cls.building_a2 = Building.objects.create(
            company=cls.company_a, name="Building A2"
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
        cls.manager_a2 = _mk("mgr-a2@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager_a2, building=cls.building_a2
        )

        cls.staff_a = _mk("staff-a@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_a)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_a, building=cls.building_a
        )

        cls.staff_a_inactive_profile = _mk(
            "staff-inactive@example.com", UserRole.STAFF
        )
        StaffProfile.objects.create(
            user=cls.staff_a_inactive_profile, is_active=False
        )
        BuildingStaffVisibility.objects.create(
            user=cls.staff_a_inactive_profile, building=cls.building_a
        )

        cls.staff_a_no_visibility = _mk(
            "staff-no-vis@example.com", UserRole.STAFF
        )
        StaffProfile.objects.create(user=cls.staff_a_no_visibility)
        # No BuildingStaffVisibility row for building_a — exercises the
        # "no visibility on building" reject path.

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
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _list_url(self, ticket):
        return f"/api/tickets/{ticket.id}/staff-assignments/"

    def _detail_url(self, ticket, user):
        return f"/api/tickets/{ticket.id}/staff-assignments/{user.id}/"

    def _assignable_url(self, ticket):
        return f"/api/tickets/{ticket.id}/assignable-staff/"

    # ---- happy paths ---------------------------------------------------

    def test_super_admin_can_add_and_remove(self):
        client = self._api(self.super_admin)
        add = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.staff_a.id},
            format="json",
        )
        self.assertEqual(add.status_code, 201, add.data)
        self.assertEqual(add.data["user_id"], self.staff_a.id)
        self.assertEqual(
            add.data["assigned_by_email"], self.super_admin.email
        )
        self.assertTrue(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket_a, user=self.staff_a
            ).exists()
        )

        remove = client.delete(self._detail_url(self.ticket_a, self.staff_a))
        self.assertEqual(remove.status_code, 204)
        self.assertFalse(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket_a, user=self.staff_a
            ).exists()
        )

    def test_company_admin_can_add_in_own_company(self):
        client = self._api(self.admin_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.staff_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["assigned_by_email"], self.admin_a.email
        )

    def test_building_manager_can_add_for_assigned_building(self):
        client = self._api(self.manager_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.staff_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_assignable_staff_lists_eligible_only(self):
        client = self._api(self.admin_a)
        response = client.get(self._assignable_url(self.ticket_a))
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.data]
        self.assertIn(self.staff_a.id, ids)
        # Inactive profile and no-visibility staff must NOT appear.
        self.assertNotIn(self.staff_a_inactive_profile.id, ids)
        self.assertNotIn(self.staff_a_no_visibility.id, ids)
        # Cross-company staff must NOT appear.
        self.assertNotIn(self.staff_b.id, ids)
        # Non-staff users must NOT appear.
        self.assertNotIn(self.admin_a.id, ids)
        self.assertNotIn(self.manager_a.id, ids)

    def test_add_is_idempotent(self):
        client = self._api(self.admin_a)
        first = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.staff_a.id},
            format="json",
        )
        self.assertEqual(first.status_code, 201)
        second = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.staff_a.id},
            format="json",
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket_a, user=self.staff_a
            ).count(),
            1,
        )

    def test_delete_unknown_returns_404(self):
        client = self._api(self.admin_a)
        response = client.delete(
            self._detail_url(self.ticket_a, self.staff_a)
        )
        self.assertEqual(response.status_code, 404)

    def test_list_includes_admin_added_row(self):
        TicketStaffAssignment.objects.create(
            ticket=self.ticket_a,
            user=self.staff_a,
            assigned_by=self.admin_a,
        )
        client = self._api(self.admin_a)
        response = client.get(self._list_url(self.ticket_a))
        self.assertEqual(response.status_code, 200)
        ids = [row["user_id"] for row in response.data["results"]]
        self.assertIn(self.staff_a.id, ids)

    # ---- staff request flow not required ------------------------------

    def test_direct_assign_does_not_require_staff_request(self):
        """
        Pilot brief: 'A staff member does NOT need to request
        assignment in order to be assigned to a ticket.' Sanity-check
        that no StaffAssignmentRequest exists after a direct add.
        """
        self.assertFalse(
            StaffAssignmentRequest.objects.filter(
                staff=self.staff_a, ticket=self.ticket_a
            ).exists()
        )
        client = self._api(self.admin_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.staff_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        # No StaffAssignmentRequest fabricated on the side.
        self.assertFalse(
            StaffAssignmentRequest.objects.filter(
                staff=self.staff_a, ticket=self.ticket_a
            ).exists()
        )
        # The TicketStaffAssignment row IS created.
        self.assertTrue(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket_a, user=self.staff_a
            ).exists()
        )

    # ---- cross-company / out-of-scope ---------------------------------

    def test_cross_company_admin_cannot_add(self):
        # admin_b tries to act on a Company-A ticket → queryset hides
        # the ticket → 404.
        client = self._api(self.admin_b)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.staff_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket_a, user=self.staff_a
            ).exists()
        )

    def test_cross_building_manager_cannot_add(self):
        # manager_a2 is assigned to building_a2; ticket_a is in
        # building_a. scope_tickets_for hides it → 404.
        client = self._api(self.manager_a2)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.staff_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_cross_company_staff_target_blocked(self):
        # admin_a tries to add a Bright STAFF (no visibility on A1) → 400.
        client = self._api(self.admin_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.staff_b.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("user_id", response.data)
        self.assertFalse(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket_a, user=self.staff_b
            ).exists()
        )

    def test_target_with_inactive_profile_rejected(self):
        client = self._api(self.admin_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.staff_a_inactive_profile.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_target_without_building_visibility_rejected(self):
        client = self._api(self.admin_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.staff_a_no_visibility.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_target_must_be_staff_role(self):
        client = self._api(self.admin_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.manager_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    # ---- forbidden roles ---------------------------------------------

    def test_staff_cannot_add(self):
        # STAFF tries to assign another staff → 403.
        client = self._api(self.staff_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.staff_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_customer_user_cannot_add(self):
        # CUSTOMER_USER sees the ticket (their own) but the gate
        # rejects with 403 before queryset can hide it.
        client = self._api(self.cust_user_a)
        response = client.post(
            self._list_url(self.ticket_a),
            {"user_id": self.staff_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_customer_user_cannot_list_assignable_staff(self):
        client = self._api(self.cust_user_a)
        response = client.get(self._assignable_url(self.ticket_a))
        self.assertEqual(response.status_code, 403)

    # ---- coexistence with Sprint 23B approve path ---------------------

    def test_sprint_23b_approve_path_still_works_alongside(self):
        # Direct-add a STAFF via Sprint 25A.
        admin = self._api(self.admin_a)
        direct = admin.post(
            self._list_url(self.ticket_a),
            {"user_id": self.staff_a.id},
            format="json",
        )
        self.assertEqual(direct.status_code, 201)

        # Sprint 23B staff request → approve still works for a
        # different ticket without contention.
        BuildingStaffVisibility.objects.create(
            user=self.staff_a, building=self.building_a2
        )
        ticket_a2 = Ticket.objects.create(
            company=self.company_a,
            building=self.building_a2,
            customer=self.customer_a,
            created_by=self.admin_a,
            title="Ticket A2",
            description="x",
        )
        # Need CustomerBuildingMembership for the new pair.
        CustomerBuildingMembership.objects.get_or_create(
            customer=self.customer_a, building=self.building_a2
        )
        req = StaffAssignmentRequest.objects.create(
            staff=self.staff_a, ticket=ticket_a2
        )
        approve = admin.post(
            f"/api/staff-assignment-requests/{req.id}/approve/",
            {"reviewer_note": "approved via 23B path"},
            format="json",
        )
        self.assertEqual(approve.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.status, AssignmentRequestStatus.APPROVED)
        # Sanity: both rows exist.
        self.assertTrue(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket_a, user=self.staff_a
            ).exists()
        )
        self.assertTrue(
            TicketStaffAssignment.objects.filter(
                ticket=ticket_a2, user=self.staff_a
            ).exists()
        )

    # ---- ticket detail payload reflects new assignment ----------------

    def test_ticket_detail_assigned_staff_reflects_admin_add(self):
        admin = self._api(self.admin_a)
        admin.post(
            self._list_url(self.ticket_a),
            {"user_id": self.staff_a.id},
            format="json",
        )
        detail = admin.get(f"/api/tickets/{self.ticket_a.id}/")
        self.assertEqual(detail.status_code, 200)
        ids = [
            entry.get("id")
            for entry in detail.data["assigned_staff"]
            if not entry.get("anonymous")
        ]
        self.assertIn(self.staff_a.id, ids)
