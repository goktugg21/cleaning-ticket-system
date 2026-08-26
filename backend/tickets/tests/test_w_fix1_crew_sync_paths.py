"""W-FIX1 C1 (audit F25) — every crew write mirrors to the plan.

`tickets.crew_sync` (W-HOURS5) mirrored the per-slot door and the
manager door. Three other doors wrote ticket crew and never told the
extra work: bulk assign/unassign, the transition modal's
`assigned_staff_ids`, and staff-request approval. A person put on a
spawned ticket through any of them could not be planned
(`planned_hours_invalid`), and a person taken off through bulk-unassign
kept an open plan nobody could clear. One chokepoint, one test per door.

The fourth door the audit named — ticket soft-delete — does not exist
for a spawned ticket: `test_sprint182_extra_work_ticket_delete` pins
`extra_work_ticket_not_deletable`, so there is nothing to mirror there.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import StaffProfile, UserRole
from buildings.models import (
    Building,
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
from companies.models import Company, CompanyUserMembership
from customers.models import Customer, CustomerBuildingMembership
from extra_work.models import (
    ExtraWorkAssignment,
    ExtraWorkAssignmentRole,
    ExtraWorkCategory,
    ExtraWorkPlannedHours,
    ExtraWorkRequest,
    ExtraWorkStatus,
)
from tickets.models import (
    AssignmentRequestStatus,
    StaffAssignmentRequest,
    Ticket,
    TicketManagerAssignment,
    TicketStaffAssignment,
    TicketStatus,
)

User = get_user_model()
PASSWORD = "CrewPathsPass!1"


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class CrewSyncPathsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov FIX1", slug="prov-crew-fix1")
        cls.building = Building.objects.create(company=cls.company, name="B-fix1")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust-fix1", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.admin = _mk("ca-fix1@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(user=cls.admin, company=cls.company)
        cls.bm = _mk("bm-fix1@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(user=cls.bm, building=cls.building)
        cls.ahmet = _mk("ahmet-fix1@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.ahmet)
        BuildingStaffVisibility.objects.create(
            user=cls.ahmet, building=cls.building, can_request_assignment=True
        )

    def setUp(self):
        self.ew = ExtraWorkRequest.objects.create(
            company=self.company,
            customer=self.customer,
            building=self.building,
            title="Crew EW",
            description="d",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            created_by=self.admin,
        )
        self.ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title="Crew ticket",
            description="desc",
            status=TicketStatus.OPEN,
            extra_work_request=self.ew,
        )

    def _api(self, user=None):
        client = APIClient()
        client.force_authenticate(user=user or self.admin)
        return client

    def _worker_rows(self, user):
        return ExtraWorkAssignment.objects.filter(
            extra_work_request=self.ew,
            user=user,
            role=ExtraWorkAssignmentRole.WORKER,
        )

    def _manager_rows(self, user):
        return ExtraWorkAssignment.objects.filter(
            extra_work_request=self.ew,
            user=user,
            role=ExtraWorkAssignmentRole.MANAGER,
        )

    # ---- bulk assign / unassign ---------------------------------------

    def test_bulk_assign_puts_the_worker_on_the_plans_crew(self):
        resp = self._api().post(
            "/api/tickets/bulk-assign/",
            {
                "tickets": [self.ticket.id],
                "workers": [self.ahmet.id],
                "mode": "assign",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["created"], 1)
        self.assertTrue(self._worker_rows(self.ahmet).exists())

    def test_bulk_assign_puts_the_manager_on_the_plans_crew(self):
        resp = self._api().post(
            "/api/tickets/bulk-assign/",
            {
                "tickets": [self.ticket.id],
                "managers": [self.bm.id],
                "mode": "assign",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(self._manager_rows(self.bm).exists())

    def test_bulk_unassign_takes_the_worker_off_and_clears_the_open_plan(self):
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.ahmet, assigned_by=self.admin
        )
        ExtraWorkAssignment.objects.create(
            extra_work_request=self.ew,
            user=self.ahmet,
            role=ExtraWorkAssignmentRole.WORKER,
            assigned_by=self.admin,
        )
        future = ExtraWorkPlannedHours.objects.create(
            extra_work_request=self.ew,
            user=self.ahmet,
            date=timezone.localdate() + dt.timedelta(days=2),
            hours=Decimal("2.00"),
            set_by=self.admin,
        )
        past = ExtraWorkPlannedHours.objects.create(
            extra_work_request=self.ew,
            user=self.ahmet,
            date=timezone.localdate() - dt.timedelta(days=2),
            hours=Decimal("3.00"),
            set_by=self.admin,
        )

        resp = self._api().post(
            "/api/tickets/bulk-assign/",
            {
                "tickets": [self.ticket.id],
                "workers": [self.ahmet.id],
                "mode": "unassign",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["removed"], 1)
        self.assertFalse(self._worker_rows(self.ahmet).exists())
        # The W-HOURS5 ruling: future plan goes, past plan is history.
        self.assertFalse(
            ExtraWorkPlannedHours.objects.filter(pk=future.pk).exists()
        )
        self.assertTrue(ExtraWorkPlannedHours.objects.filter(pk=past.pk).exists())

    # ---- the transition modal's assigned_staff_ids ---------------------

    def test_the_transition_modals_assignee_lands_on_the_plans_crew(self):
        resp = self._api().post(
            f"/api/tickets/{self.ticket.id}/status/",
            {
                "to_status": TicketStatus.ACKNOWLEDGED,
                "assigned_staff_ids": [self.ahmet.id],
                "scheduled_start_at": (
                    timezone.now() + dt.timedelta(days=1)
                ).isoformat(),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket, user=self.ahmet
            ).exists()
        )
        self.assertTrue(self._worker_rows(self.ahmet).exists())

    # ---- staff-request approval ----------------------------------------

    def test_an_approved_staff_request_lands_on_the_plans_crew(self):
        req = StaffAssignmentRequest.objects.create(
            staff=self.ahmet,
            ticket=self.ticket,
            status=AssignmentRequestStatus.PENDING,
        )
        resp = self._api().post(
            f"/api/staff-assignment-requests/{req.id}/approve/",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(
            TicketStaffAssignment.objects.filter(
                ticket=self.ticket, user=self.ahmet
            ).exists()
        )
        self.assertTrue(self._worker_rows(self.ahmet).exists())

    # ---- the planning door proves the mirror is real --------------------

    def test_a_bulk_assigned_worker_can_then_be_planned(self):
        self._api().post(
            "/api/tickets/bulk-assign/",
            {
                "tickets": [self.ticket.id],
                "workers": [self.ahmet.id],
                "mode": "assign",
            },
            format="json",
        )
        resp = self._api().post(
            f"/api/extra-work/{self.ew.id}/plan/",
            {
                "planned_hours": [
                    {"user": self.ahmet.id, "date": None, "hour_type": None, "hours": "1.00"}
                ],
                "start": False,
            },
            format="json",
        )
        self.assertNotEqual(
            resp.data.get("code") if isinstance(resp.data, dict) else None,
            "planned_hours_invalid",
            resp.data,
        )
        self.assertIn(resp.status_code, (200, 201), resp.data)

    def test_a_manager_taken_off_by_bulk_unassign_leaves_the_plan(self):
        TicketManagerAssignment.objects.create(
            ticket=self.ticket, user=self.bm, assigned_by=self.admin
        )
        ExtraWorkAssignment.objects.create(
            extra_work_request=self.ew,
            user=self.bm,
            role=ExtraWorkAssignmentRole.MANAGER,
            assigned_by=self.admin,
        )
        resp = self._api().post(
            "/api/tickets/bulk-assign/",
            {
                "tickets": [self.ticket.id],
                "managers": [self.bm.id],
                "mode": "unassign",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(self._manager_rows(self.bm).exists())
