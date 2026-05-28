"""
Sprint 28 Batch 2 — STAFF cannot reassign tickets via the BM-assign endpoint.

Audit gap (docs/audits/current-state-2026-05-16-system-audit.md row 26,
master plan Batch 2): the gate at `tickets/views.py:250` and
`tickets/serializers.py:626` both use `is_staff_role(user)` which by
design returns True for STAFF (Sprint 23A widened that helper so STAFF
inherits provider-side ticket behaviour: internal-note visibility,
hidden-attachment access, first-response stamping). The side effect is
that the `/api/tickets/<id>/assign/` BM-reassign endpoint — meant only
for SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER — also lets STAFF
through. A STAFF user with `BuildingStaffVisibility` (or
`TicketStaffAssignment`) on the ticket's building could un-assign or
re-assign the ticket.

Sprint 25A's `test_staff_cannot_add` locks the analogous gate for the
DIFFERENT endpoint `/api/tickets/<id>/staff-assignments/`, so the gap
was easy to miss.

This module locks the BM-assign endpoint:

  T-1 STAFF with building visibility cannot un-assign (assigned_to: null) → 403
  T-2 STAFF with building visibility cannot re-assign to a valid BM     → 403
  T-3 STAFF with direct ticket assignment also cannot re-assign         → 403
  T-4 Customer-user 403 path still holds (regression lock for the
       existing test_assignment.test_customer_cannot_call_assign_endpoint)
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
from tickets.models import Ticket, TicketStaffAssignment


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


class StaffCannotAssignTicketTests(TestCase):
    """STAFF must not be able to mutate `Ticket.assigned_to` via
    `POST /api/tickets/<id>/assign/` — neither un-assign nor re-assign."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Provider Co", slug="provider-co")
        cls.building = Building.objects.create(company=cls.company, name="Building One")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer One", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.manager = _mk("mgr@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(user=cls.manager, building=cls.building)

        cls.other_manager = _mk("mgr-other@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.other_manager, building=cls.building
        )

        # STAFF user A — has building visibility (sees every ticket in the
        # building). This is the "I have scope to see the ticket but not
        # to mutate its assignment" actor.
        cls.staff_with_visibility = _mk("staff-vis@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff_with_visibility)
        BuildingStaffVisibility.objects.create(
            user=cls.staff_with_visibility, building=cls.building
        )

        # STAFF user B — has a direct ticket assignment (the H-4 path).
        # Same expected behaviour: cannot mutate the ticket's BM
        # assignment even though they're assigned to do the work.
        cls.staff_with_direct_assignment = _mk(
            "staff-direct@example.com", UserRole.STAFF
        )
        StaffProfile.objects.create(user=cls.staff_with_direct_assignment)
        # Intentionally NO BuildingStaffVisibility row — direct ticket
        # assignment alone gives the H-4 "always sees assigned work"
        # path.

        cls.customer_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)
        cust_membership = CustomerUserMembership.objects.create(
            user=cls.customer_user, customer=cls.customer
        )
        CustomerUserBuildingAccess.objects.create(
            membership=cust_membership, building=cls.building
        )

        cls.ticket = Ticket.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.customer_user,
            assigned_to=cls.manager,
            title="Sprint 28 assign-block ticket",
            description="STAFF reassign regression lock",
        )
        TicketStaffAssignment.objects.create(
            ticket=cls.ticket, user=cls.staff_with_direct_assignment
        )

    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def _assign_url(self):
        return f"/api/tickets/{self.ticket.id}/assign/"

    # -----------------------------------------------------------------
    # T-1: STAFF with building visibility → cannot un-assign
    # -----------------------------------------------------------------
    def test_staff_with_building_visibility_cannot_unassign(self):
        client = self._client(self.staff_with_visibility)
        response = client.post(
            self._assign_url(), {"assigned_to": None}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_to_id, self.manager.id)

    # -----------------------------------------------------------------
    # T-2: STAFF with building visibility → cannot re-assign to another BM
    # -----------------------------------------------------------------
    def test_staff_with_building_visibility_cannot_reassign(self):
        client = self._client(self.staff_with_visibility)
        response = client.post(
            self._assign_url(),
            {"assigned_to": self.other_manager.id},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_to_id, self.manager.id)

    # -----------------------------------------------------------------
    # T-3: STAFF with direct ticket assignment → also cannot mutate
    # -----------------------------------------------------------------
    def test_staff_with_direct_assignment_cannot_reassign(self):
        client = self._client(self.staff_with_direct_assignment)
        response = client.post(
            self._assign_url(),
            {"assigned_to": self.other_manager.id},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_to_id, self.manager.id)

    # -----------------------------------------------------------------
    # T-4: regression lock — customer-user 403 path is unaffected
    #
    # Mirrors `test_assignment.test_customer_cannot_call_assign_endpoint`
    # so a future change to the assign gate doesn't silently re-open the
    # customer side either.
    # -----------------------------------------------------------------
    def test_customer_user_cannot_reassign(self):
        client = self._client(self.customer_user)
        response = client.post(
            self._assign_url(),
            {"assigned_to": self.other_manager.id},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_to_id, self.manager.id)
