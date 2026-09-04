"""W-HOURS5 Task 2 — a former crew member's past plan is history.

The ruling: removing a person from a job clears ONLY their today-and-
future planned cells; PAST planned hours are history and stay. Deleting
past plan is possible only by hand — unlock the past days with a reason,
then zero the cells. Automatic deletion is forbidden.

Before this wave the plan save REPLACED the whole distribution and the
payload could not name a former crew member (`resolve_planned_hours`
refuses anyone not assigned), so the first save after a removal either
deleted their past rows (with the override) or was refused outright
(`plan_past_day_locked`, without). What is pinned here:

1. A former crew member's PAST row survives a save that omits it, and
   the save needs no override reason for that.
2. Their undated and future rows are gone after that same save.
3. A CURRENT crew member's past row still needs the recorded override
   to change — the rule itself is untouched.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User, UserRole
from buildings.models import Building, BuildingStaffVisibility
from companies.models import Company
from customers.models import Customer, CustomerBuildingMembership
from extra_work.models import (
    ExtraWorkAssignment,
    ExtraWorkAssignmentRole,
    ExtraWorkCategory,
    ExtraWorkPlannedHours,
    ExtraWorkRequest,
    ExtraWorkStatus,
)


class PlanHistoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="History BV", slug="history-bv-w5")
        cls.building = Building.objects.create(
            name="H Building", company=cls.company
        )
        cls.customer = Customer.objects.create(
            name="H Customer", company=cls.company
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.admin = User.objects.create_user(
            email="history-admin@osius.demo",
            password="x",
            role=UserRole.SUPER_ADMIN,
            full_name="History Admin",
        )
        cls.stayer = User.objects.create_user(
            email="history-stayer@osius.demo",
            password="x",
            role=UserRole.STAFF,
            full_name="Stays On",
        )
        cls.leaver = User.objects.create_user(
            email="history-leaver@osius.demo",
            password="x",
            role=UserRole.STAFF,
            full_name="Left The Job",
        )
        for user in (cls.stayer, cls.leaver):
            BuildingStaffVisibility.objects.create(user=user, building=cls.building)

    def _api(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        return client

    def _ew(self):
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            customer=self.customer,
            building=self.building,
            title="History EW",
            description="d",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.UNDER_REVIEW,
            created_by=self.admin,
        )
        # Only the STAYER is on the crew now; the LEAVER's rows are what
        # they planned before they were taken off.
        ExtraWorkAssignment.objects.create(
            extra_work_request=ew,
            user=self.stayer,
            role=ExtraWorkAssignmentRole.WORKER,
            assigned_by=self.admin,
        )
        return ew

    def _row(self, ew, user, on_date, hours="2.00"):
        return ExtraWorkPlannedHours.objects.create(
            extra_work_request=ew,
            user=user,
            date=on_date,
            hours=Decimal(hours),
            set_by=self.admin,
        )

    def test_a_former_crew_members_past_row_survives_a_save_without_a_reason(self):
        ew = self._ew()
        today = timezone.localdate()
        yesterday = today - dt.timedelta(days=1)
        kept = self._row(ew, self.leaver, yesterday, "3.00")
        self._row(ew, self.stayer, today, "4.00")

        # The dialog sends the crew it has: the stayer only, and no
        # override reason — nothing on a past day of the CURRENT crew
        # changed.
        resp = self._api().post(
            f"/api/extra-work/{ew.id}/plan/",
            {
                "planned_hours": [
                    {"user": self.stayer.id, "date": str(today), "hours": "4.00"}
                ],
                "start": False,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(
            ExtraWorkPlannedHours.objects.filter(pk=kept.pk).exists(),
            "the leaver's past row is history and must survive",
        )
        self.assertEqual(
            ExtraWorkPlannedHours.objects.get(pk=kept.pk).hours, Decimal("3.00")
        )

    def test_a_former_crew_members_open_rows_go_with_that_save(self):
        ew = self._ew()
        today = timezone.localdate()
        tomorrow = today + dt.timedelta(days=1)
        past = self._row(ew, self.leaver, today - dt.timedelta(days=2), "1.00")
        undated = self._row(ew, self.leaver, None, "0.00")
        future = self._row(ew, self.leaver, tomorrow, "5.00")
        today_row = self._row(ew, self.leaver, today, "2.00")

        resp = self._api().post(
            f"/api/extra-work/{ew.id}/plan/",
            {
                "planned_hours": [
                    {"user": self.stayer.id, "date": str(today), "hours": "4.00"}
                ],
                "start": False,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        alive = set(
            ExtraWorkPlannedHours.objects.filter(
                extra_work_request=ew, user=self.leaver
            ).values_list("pk", flat=True)
        )
        self.assertEqual(alive, {past.pk})
        for gone in (undated, future, today_row):
            self.assertNotIn(gone.pk, alive)

    def test_a_current_crew_members_past_row_still_needs_the_override(self):
        ew = self._ew()
        today = timezone.localdate()
        yesterday = today - dt.timedelta(days=1)
        self._row(ew, self.stayer, yesterday, "3.00")

        # Omitting the stayer's own past row is a deletion of history by
        # somebody still on the job — the recorded override is required,
        # exactly as before this wave.
        resp = self._api().post(
            f"/api/extra-work/{ew.id}/plan/",
            {
                "planned_hours": [
                    {"user": self.stayer.id, "date": str(today), "hours": "4.00"}
                ],
                "start": False,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.data.get("code"), "plan_past_day_locked")
        self.assertEqual(
            ExtraWorkPlannedHours.objects.filter(
                extra_work_request=ew, user=self.stayer, date=yesterday
            ).count(),
            1,
        )
