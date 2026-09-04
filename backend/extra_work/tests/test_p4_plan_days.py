"""
P-4 — the plan's days are the ONLY days hours can sit on.

THE DOUBLE-COUNT THE OWNER HIT (crmtest, 2026-08-30, EW 90): typed 4 in
the "no day yet" box and 4 on one day, and the total read 12. The
phantom 4 was a day that had dropped out of the window: the old dialog
kept hours on a day no longer between first and last work day IN STATE,
IN THE TOTAL and IN THE PAYLOAD ("paging is display only", W7), and the
server accepted them. EW 83 on crmtest holds rows dated 26 Aug under a
27–29 Aug window for the same reason.

WHAT THESE TESTS PIN:
  * Undated hours plus dated hours read as their plain sum — never more.
  * A NEW or CHANGED row dated outside the committed window is refused,
    and the refusal names the days and the field, so the dialog can put
    the message at the field.
  * An UNCHANGED row outside a window that moved is kept: "people's days
    stayed on the old dates — adjust them below" is a state the save
    must be able to express, and resubmitting history unchanged is free
    (the past-day rule's own reading).
  * Moving everyone's days along with the window is ONE save of the
    existing endpoint: the shifted rows land, the old ones go.
  * A plan without an end date is a one-day window.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import BuildingStaffVisibility
from extra_work.models import (
    ExtraWorkAssignment,
    ExtraWorkAssignmentRole,
    ExtraWorkCategory,
    ExtraWorkPlannedHours,
    ExtraWorkRequest,
    ExtraWorkStatus,
)
from extra_work.planning import ERR_PLANNED_HOURS_OUTSIDE_WINDOW
from test_utils import TenantFixtureMixin


def plan_url(pk):
    return f"/api/extra-work/{pk}/plan/"


class PlanDaysTestBase(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.worker = self.make_user("p4-a@example.com", UserRole.STAFF)
        self.worker_2 = self.make_user("p4-b@example.com", UserRole.STAFF)
        for user in (self.worker, self.worker_2):
            BuildingStaffVisibility.objects.create(
                user=user, building=self.building
            )
        self.ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Plan days",
            description="x",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
        )
        for user in (self.worker, self.worker_2):
            ExtraWorkAssignment.objects.create(
                extra_work_request=self.ew,
                user=user,
                role=ExtraWorkAssignmentRole.WORKER,
                assigned_by=self.super_admin,
            )
        # Next week, so nothing here is a past day.
        self.day1 = timezone.localdate() + timedelta(days=7)
        self.day2 = self.day1 + timedelta(days=1)
        self.day3 = self.day1 + timedelta(days=2)
        self.day5 = self.day1 + timedelta(days=4)
        self.day6 = self.day1 + timedelta(days=5)

    def plan(self, body, actor=None):
        self.authenticate(actor or self.company_admin)
        return self.client.post(plan_url(self.ew.id), body, format="json")

    def row(self, user, day, hours="4.00"):
        return {
            "user": user.id,
            "date": day.isoformat() if day is not None else None,
            "hours": hours,
        }

    def stored(self, user):
        return [
            (row.date, row.hours)
            for row in ExtraWorkPlannedHours.objects.filter(
                extra_work_request=self.ew, user=user
            ).order_by("date")
        ]


class TheTotalIsThePlainSumTests(PlanDaysTestBase):
    def test_four_without_a_day_plus_four_on_a_day_is_eight(self):
        """The owner's exact entry. Never 12."""
        response = self.plan(
            {
                "provider_planned_date": self.day1.isoformat(),
                "provider_planned_end_date": self.day3.isoformat(),
                "planned_hours": [
                    self.row(self.worker, None),
                    self.row(self.worker, self.day2),
                ],
                "start": False,
            }
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["planned_hours_total"], "8.00")
        rows = response.data["planned_hours"]
        self.assertEqual(
            sorted(((str(r["date"]), r["hours"]) for r in rows)),
            sorted([("None", "4.00"), (self.day2.isoformat(), "4.00")]),
        )

    def test_any_day_combination_reads_exactly_what_was_chosen(self):
        """Days 1+3 for one person, day 2 only for the other."""
        response = self.plan(
            {
                "provider_planned_date": self.day1.isoformat(),
                "provider_planned_end_date": self.day3.isoformat(),
                "planned_hours": [
                    self.row(self.worker, self.day1, "2.00"),
                    self.row(self.worker, self.day3, "3.00"),
                    self.row(self.worker_2, self.day2, "4.00"),
                ],
                "start": False,
            }
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["planned_hours_total"], "9.00")
        self.assertEqual(
            self.stored(self.worker),
            [(self.day1, Decimal("2.00")), (self.day3, Decimal("3.00"))],
        )
        self.assertEqual(self.stored(self.worker_2), [(self.day2, Decimal("4.00"))])


class OutsideTheWindowTests(PlanDaysTestBase):
    def test_a_new_row_on_a_day_outside_the_window_is_refused_and_named(self):
        response = self.plan(
            {
                "provider_planned_date": self.day1.isoformat(),
                "provider_planned_end_date": self.day3.isoformat(),
                "planned_hours": [
                    self.row(self.worker, self.day2),
                    self.row(self.worker, self.day5),
                ],
                "start": False,
            }
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data["code"], ERR_PLANNED_HOURS_OUTSIDE_WINDOW)
        self.assertEqual(response.data["field"], "planned_hours")
        self.assertEqual(response.data["days"], [self.day5.isoformat()])
        # Nothing was written: a refusal leaves the row exactly as it was.
        self.assertEqual(self.stored(self.worker), [])

    def test_a_plan_without_an_end_date_is_a_one_day_window(self):
        response = self.plan(
            {
                "provider_planned_date": self.day1.isoformat(),
                "planned_hours": [self.row(self.worker, self.day2)],
                "start": False,
            }
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data["code"], ERR_PLANNED_HOURS_OUTSIDE_WINDOW)
        self.assertEqual(response.data["days"], [self.day2.isoformat()])

    def test_the_window_is_read_from_the_stored_plan_when_the_payload_has_none(self):
        self.ew.provider_planned_date = self.day1
        self.ew.provider_planned_end_date = self.day2
        self.ew.save(update_fields=["provider_planned_date", "provider_planned_end_date"])
        response = self.plan(
            {"planned_hours": [self.row(self.worker, self.day3)], "start": False}
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data["days"], [self.day3.isoformat()])

    def test_undated_rows_are_never_outside_a_window(self):
        response = self.plan(
            {
                "provider_planned_date": self.day1.isoformat(),
                "planned_hours": [self.row(self.worker, None, "6.00")],
                "start": False,
            }
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)


class MovingTheWindowTests(PlanDaysTestBase):
    def seed_two_days(self):
        response = self.plan(
            {
                "provider_planned_date": self.day1.isoformat(),
                "provider_planned_end_date": self.day2.isoformat(),
                "planned_hours": [
                    self.row(self.worker, self.day1),
                    self.row(self.worker, self.day2),
                    self.row(self.worker_2, self.day1),
                ],
                "start": False,
            }
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_unchanged_rows_outside_a_moved_window_are_kept(self):
        """'People's days stayed on the old dates — adjust them below.'"""
        self.seed_two_days()
        response = self.plan(
            {
                "provider_planned_date": self.day5.isoformat(),
                "provider_planned_end_date": self.day6.isoformat(),
                "planned_hours": [
                    self.row(self.worker, self.day1),
                    self.row(self.worker, self.day2),
                    self.row(self.worker_2, self.day1),
                    self.row(self.worker_2, self.day5, "2.00"),
                ],
                "start": False,
            }
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(
            self.stored(self.worker),
            [(self.day1, Decimal("4.00")), (self.day2, Decimal("4.00"))],
        )
        self.assertEqual(
            self.stored(self.worker_2),
            [(self.day1, Decimal("4.00")), (self.day5, Decimal("2.00"))],
        )

    def test_a_changed_row_outside_a_moved_window_is_refused(self):
        self.seed_two_days()
        response = self.plan(
            {
                "provider_planned_date": self.day5.isoformat(),
                "provider_planned_end_date": self.day6.isoformat(),
                "planned_hours": [
                    self.row(self.worker, self.day1, "9.00"),
                    self.row(self.worker, self.day2),
                    self.row(self.worker_2, self.day1),
                ],
                "start": False,
            }
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data["days"], [self.day1.isoformat()])

    def test_moving_everyones_days_along_is_one_save(self):
        """Shift by the same difference through the existing endpoint."""
        self.seed_two_days()
        response = self.plan(
            {
                "provider_planned_date": self.day5.isoformat(),
                "provider_planned_end_date": self.day6.isoformat(),
                "planned_hours": [
                    self.row(self.worker, self.day5),
                    self.row(self.worker, self.day6),
                    self.row(self.worker_2, self.day5),
                ],
                "start": False,
            }
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["planned_hours_total"], "12.00")
        self.assertEqual(
            self.stored(self.worker),
            [(self.day5, Decimal("4.00")), (self.day6, Decimal("4.00"))],
        )
        self.assertEqual(self.stored(self.worker_2), [(self.day5, Decimal("4.00"))])
