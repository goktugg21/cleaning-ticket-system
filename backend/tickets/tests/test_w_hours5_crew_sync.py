"""W-HOURS5 Task 2 — the ticket's crew and the plan's crew are ONE crew.

`tickets.crew_sync` mirrors every user-driven crew write on a spawned
ticket onto the extra work's `ExtraWorkAssignment` rows, so the People
tab and the plan modal are two doors to the same crew. Pinned here:

1. A base staff slot created through the ticket endpoint puts the
   person on the plan's crew (WORKER).
2. Deleting that slot takes them off the plan's crew — and clears ONLY
   their today-and-future and undated planned rows; PAST rows stay
   (the ruling: past plan is history, automatic deletion forbidden).
3. A responsible manager added / removed through the ticket endpoint
   mirrors the same way (MANAGER).
4. On a series (two tickets from one extra work) a person removed from
   one ticket stays on the plan's crew while the other still names them.
5. A ticket that came from no extra work mirrors nothing.
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
from tickets.models import Ticket, TicketManagerAssignment, TicketStaffAssignment


User = get_user_model()
PASSWORD = "CrewSyncPass!5"


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class CrewSyncTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov W5", slug="prov-crew-w5")
        cls.building = Building.objects.create(company=cls.company, name="B-crew")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust-crew", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.admin = _mk("ca-crew@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(user=cls.admin, company=cls.company)
        cls.bm = _mk("bm-crew@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(user=cls.bm, building=cls.building)
        cls.ahmet = _mk("ahmet-crew@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.ahmet)
        BuildingStaffVisibility.objects.create(user=cls.ahmet, building=cls.building)

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
        self.ticket = self._ticket(self.ew)

    def _ticket(self, ew, title="Crew ticket"):
        return Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title=title,
            description="desc",
            status="OPEN",
            extra_work_request=ew,
        )

    def _api(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        return client

    def _planned(self, user, on_date, hours="2.00"):
        return ExtraWorkPlannedHours.objects.create(
            extra_work_request=self.ew,
            user=user,
            date=on_date,
            hours=Decimal(hours),
            set_by=self.admin,
        )

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

    # ---- 1 + 2: staff slots -------------------------------------------

    def test_a_base_slot_puts_the_person_on_the_plans_crew(self):
        resp = self._api().post(
            f"/api/tickets/{self.ticket.id}/staff-assignments/",
            {"user_id": self.ahmet.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(self._worker_rows(self.ahmet).count(), 1)
        self.assertEqual(self._worker_rows(self.ahmet).get().assigned_by_id, self.admin.id)

    def test_removing_the_slot_clears_only_the_open_plan_and_keeps_history(self):
        today = timezone.localdate()
        past = self._planned(self.ahmet, today - dt.timedelta(days=1), "3.00")
        today_row = self._planned(self.ahmet, today, "4.00")
        future = self._planned(self.ahmet, today + dt.timedelta(days=2), "5.00")
        undated = self._planned(self.ahmet, None, "0.00")
        create = self._api().post(
            f"/api/tickets/{self.ticket.id}/staff-assignments/",
            {"user_id": self.ahmet.id},
            format="json",
        )
        self.assertEqual(create.status_code, 201, create.data)
        slot_id = create.data["id"]

        resp = self._api().delete(
            f"/api/tickets/{self.ticket.id}/staff-assignments/{slot_id}/"
        )
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(self._worker_rows(self.ahmet).count(), 0)
        alive = set(
            ExtraWorkPlannedHours.objects.filter(
                extra_work_request=self.ew, user=self.ahmet
            ).values_list("pk", flat=True)
        )
        self.assertEqual(alive, {past.pk}, "past plan is history and stays")
        for gone in (today_row, future, undated):
            self.assertNotIn(gone.pk, alive)

    # ---- 3: managers --------------------------------------------------

    def test_a_manager_added_and_removed_mirrors_onto_the_plan(self):
        resp = self._api().post(
            f"/api/tickets/{self.ticket.id}/manager-assignments/",
            {"user_ids": [self.bm.id]},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(self._manager_rows(self.bm).count(), 1)

        today = timezone.localdate()
        past = self._planned(self.bm, today - dt.timedelta(days=3), "1.00")
        future = self._planned(self.bm, today + dt.timedelta(days=1), "2.00")
        resp = self._api().delete(
            f"/api/tickets/{self.ticket.id}/manager-assignments/{self.bm.id}/"
        )
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(self._manager_rows(self.bm).count(), 0)
        self.assertTrue(ExtraWorkPlannedHours.objects.filter(pk=past.pk).exists())
        self.assertFalse(ExtraWorkPlannedHours.objects.filter(pk=future.pk).exists())

    # ---- 4: a series is one plan --------------------------------------

    def test_on_a_series_the_person_stays_on_the_plan_while_another_day_names_them(self):
        second = self._ticket(self.ew, title="Crew ticket day 2")
        api = self._api()
        first_slot = api.post(
            f"/api/tickets/{self.ticket.id}/staff-assignments/",
            {"user_id": self.ahmet.id},
            format="json",
        )
        api.post(
            f"/api/tickets/{second.id}/staff-assignments/",
            {"user_id": self.ahmet.id},
            format="json",
        )
        self.assertEqual(self._worker_rows(self.ahmet).count(), 1)
        future = self._planned(self.ahmet, timezone.localdate() + dt.timedelta(days=1))

        resp = api.delete(
            f"/api/tickets/{self.ticket.id}/staff-assignments/{first_slot.data['id']}/"
        )
        self.assertEqual(resp.status_code, 204)
        # Still on day 2 -> still on the plan's crew, plan untouched.
        self.assertEqual(self._worker_rows(self.ahmet).count(), 1)
        self.assertTrue(ExtraWorkPlannedHours.objects.filter(pk=future.pk).exists())
        self.assertTrue(
            TicketStaffAssignment.objects.filter(ticket=second, user=self.ahmet).exists()
        )

    # ---- 5: no extra work, no mirror ----------------------------------

    def test_a_ticket_without_extra_work_mirrors_nothing(self):
        plain = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title="Plain ticket",
            description="desc",
            status="OPEN",
        )
        resp = self._api().post(
            f"/api/tickets/{plain.id}/staff-assignments/",
            {"user_id": self.ahmet.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(ExtraWorkAssignment.objects.filter(user=self.ahmet).count(), 0)
        resp = self._api().post(
            f"/api/tickets/{plain.id}/manager-assignments/",
            {"user_ids": [self.bm.id]},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(ExtraWorkAssignment.objects.filter(user=self.bm).count(), 0)
        self.assertEqual(
            TicketManagerAssignment.objects.filter(ticket=plain, user=self.bm).count(), 1
        )
