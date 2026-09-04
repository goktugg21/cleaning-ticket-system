"""P-7 S2.1 — removing a person from the plan, from the Extra Work page.

The plan modal on the Extra Work detail page never rendered its X: the
page passed no remove handler, so a person once added could not be
taken off again (root cause: `ExtraWorkDetailPage` omitted
`onRemovePerson` / `onRemoveManager`). The page now wires the X to the
EXISTING unassign door, `POST /api/extra-work/bulk-assign/` with
`mode: "unassign"` — and that door, unlike the ticket-side ones that
run `tickets.crew_sync`, deleted the assignment and left the person's
open plan behind. These tests pin the ruling on this door too: the
person's today-and-future planned rows go with them, past rows are
history and stay, and a manager's removal touches no planned hours.
"""
import datetime as dt
from decimal import Decimal

from django.utils import timezone
from rest_framework import status

from extra_work.models import (
    ExtraWorkAssignment,
    ExtraWorkAssignmentRole,
    ExtraWorkPlannedHours,
)
from extra_work.tests.test_sprint157_assignments import (
    BULK_URL,
    ExtraWorkAssignmentTestBase,
)


class UnassignClearsTheOpenPlanTests(ExtraWorkAssignmentTestBase):
    def _planned(self, user, date, hours="2.00"):
        return ExtraWorkPlannedHours.objects.create(
            extra_work_request=self.request_a,
            user=user,
            date=date,
            hours=Decimal(hours),
            set_by=self.super_admin,
        )

    def test_unassigning_a_worker_clears_today_and_future_and_keeps_the_past(self):
        ExtraWorkAssignment.objects.create(
            extra_work_request=self.request_a,
            user=self.staff,
            role=ExtraWorkAssignmentRole.WORKER,
            assigned_by=self.super_admin,
        )
        today = timezone.localdate()
        past = self._planned(self.staff, today - dt.timedelta(days=3), "3.00")
        today_row = self._planned(self.staff, today, "1.00")
        future = self._planned(self.staff, today + dt.timedelta(days=2))
        undated = self._planned(self.staff, None, "0.00")

        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_URL,
            self._body([self.request_a], [self.staff], mode="unassign"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["removed"], 1)
        self.assertFalse(
            ExtraWorkAssignment.objects.filter(
                extra_work_request=self.request_a, user=self.staff
            ).exists()
        )
        remaining = set(
            ExtraWorkPlannedHours.objects.filter(
                extra_work_request=self.request_a, user=self.staff
            ).values_list("pk", flat=True)
        )
        self.assertEqual(remaining, {past.pk})
        for gone in (today_row, future, undated):
            self.assertNotIn(gone.pk, remaining)

    def test_unassigning_leaves_the_other_crew_members_plan_alone(self):
        second = self.make_user("ew-staff-2@example.com", self.staff.role)
        from buildings.models import BuildingStaffVisibility

        BuildingStaffVisibility.objects.create(user=second, building=self.building)
        for user in (self.staff, second):
            ExtraWorkAssignment.objects.create(
                extra_work_request=self.request_a,
                user=user,
                role=ExtraWorkAssignmentRole.WORKER,
                assigned_by=self.super_admin,
            )
        future = timezone.localdate() + dt.timedelta(days=1)
        self._planned(self.staff, future)
        kept = self._planned(second, future)

        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_URL,
            self._body([self.request_a], [self.staff], mode="unassign"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(ExtraWorkPlannedHours.objects.filter(pk=kept.pk).exists())
        self.assertTrue(
            ExtraWorkAssignment.objects.filter(
                extra_work_request=self.request_a, user=second
            ).exists()
        )

    def test_unassigning_a_manager_touches_no_planned_hours(self):
        ExtraWorkAssignment.objects.create(
            extra_work_request=self.request_a,
            user=self.staff,
            role=ExtraWorkAssignmentRole.WORKER,
            assigned_by=self.super_admin,
        )
        ExtraWorkAssignment.objects.create(
            extra_work_request=self.request_a,
            user=self.manager,
            role=ExtraWorkAssignmentRole.MANAGER,
            assigned_by=self.super_admin,
        )
        future = timezone.localdate() + dt.timedelta(days=1)
        worker_row = self._planned(self.staff, future)

        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_URL,
            self._body([self.request_a], [self.manager], role="MANAGER", mode="unassign"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["removed"], 1)
        self.assertTrue(ExtraWorkPlannedHours.objects.filter(pk=worker_row.pk).exists())
