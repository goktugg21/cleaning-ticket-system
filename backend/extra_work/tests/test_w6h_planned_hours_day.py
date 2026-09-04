"""
W6-H — a DAY on a planned-hours row.

THE ASYMMETRY THIS CLOSES. `timesheets.TimeEntry` has carried a `date`
since it was written, so ACTUAL hours have always been per-day. The plan
was one total per person: it could say "Gokhan: 43 hours" and could not
say "Gokhan: 8 hours on Monday". You could therefore see what somebody
worked on Monday and what they were planned in total, and nothing could
tell you what Monday was supposed to be.

WHAT THESE TESTS PIN:

  * The grain moved from (work, person) to (work, person, DAY), and the
    same person may hold several days on one job.
  * NULL DATE STILL WORKS AND STILL MEANS SOMETHING. "Planned, day not
    decided" is a real state, it is what every pre-W6-H row holds, and
    no historic row was given a guessed date.
  * The undated uniqueness survived the change. Postgres treats NULLs as
    distinct in a unique index, so the partial constraint is the only
    thing standing between "one undated row per person" and five of
    them.
  * A person must still be ASSIGNED before they can take hours. Adding a
    day did not create a second way to attach somebody to a job.
  * OVERRUN STILL WARNS AND NEVER BLOCKS. The reference system has a
    complete hard-cap function that is never called and a model boot
    carrying `// Hours validation removed per user request` — somebody
    built the block and the business had it removed.
  * A WORKER SEES THEIR OWN ROWS AND NOBODY ELSE'S, and a customer sees
    none of it.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
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
from test_utils import TenantFixtureMixin


def plan_url(pk):
    return f"/api/extra-work/{pk}/plan/"


def detail_url(pk):
    return f"/api/extra-work/{pk}/"


class DayPlanTestBase(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.worker = self.make_user("w6h-a@example.com", UserRole.STAFF)
        self.worker_2 = self.make_user("w6h-b@example.com", UserRole.STAFF)
        for user in (self.worker, self.worker_2):
            BuildingStaffVisibility.objects.create(
                user=user, building=self.building
            )
        self.ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Day plan",
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
        self.monday = timezone.localdate() + timedelta(days=7)
        self.tuesday = self.monday + timedelta(days=1)

    def plan(self, body, actor=None):
        self.authenticate(actor or self.company_admin)
        return self.client.post(plan_url(self.ew.id), body, format="json")


class TheGrainMovedToTheDayTests(DayPlanTestBase):
    def test_EIGHT_HOURS_ON_MONDAY_SIX_ON_TUESDAY(self):
        """The sentence the model could not express before W6-H."""
        response = self.plan(
            {
                "planned_hours": [
                    {
                        "user": self.worker.id,
                        "date": self.monday.isoformat(),
                        "hours": "8.00",
                    },
                    {
                        "user": self.worker.id,
                        "date": self.tuesday.isoformat(),
                        "hours": "6.00",
                    },
                ],
                "start": False,
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        rows = ExtraWorkPlannedHours.objects.filter(
            extra_work_request=self.ew, user=self.worker
        ).order_by("date")
        self.assertEqual(
            [(row.date, row.hours) for row in rows],
            [(self.monday, Decimal("8.00")), (self.tuesday, Decimal("6.00"))],
        )

    def test_two_people_on_the_same_day_are_two_rows(self):
        self.plan(
            {
                "planned_hours": [
                    {
                        "user": self.worker.id,
                        "date": self.monday.isoformat(),
                        "hours": "8.00",
                    },
                    {
                        "user": self.worker_2.id,
                        "date": self.monday.isoformat(),
                        "hours": "4.00",
                    },
                ],
                "start": False,
            }
        )

        self.assertEqual(
            ExtraWorkPlannedHours.objects.filter(
                extra_work_request=self.ew, date=self.monday
            ).count(),
            2,
        )

    def test_the_same_person_TWICE_ON_ONE_DAY_is_still_refused(self):
        """The duplicate check moved to the (person, day) grain; it did
        not go away. Two rows for one person on one day is still the
        payload mistake it always was."""
        response = self.plan(
            {
                "planned_hours": [
                    {
                        "user": self.worker.id,
                        "date": self.monday.isoformat(),
                        "hours": "8.00",
                    },
                    {
                        "user": self.worker.id,
                        "date": self.monday.isoformat(),
                        "hours": "2.00",
                    },
                ],
                "start": False,
            }
        )

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            response.data["code"], "planned_hours_duplicate_user"
        )

    def test_the_total_is_the_sum_of_every_cell(self):
        self.plan(
            {
                "budget_hours": "20.00",
                "planned_hours": [
                    {
                        "user": self.worker.id,
                        "date": self.monday.isoformat(),
                        "hours": "8.00",
                    },
                    {
                        "user": self.worker.id,
                        "date": self.tuesday.isoformat(),
                        "hours": "6.00",
                    },
                    {"user": self.worker_2.id, "hours": "3.00"},
                ],
                "start": False,
            }
        )

        self.authenticate(self.company_admin)
        response = self.client.get(detail_url(self.ew.id))
        self.assertEqual(response.data["planned_hours_total"], "17.00")


class UndatedRowsStillWorkTests(DayPlanTestBase):
    def test_A_PLAN_WITH_NO_DATE_IS_A_REAL_PLAN(self):
        """"Planned, day not decided" is the only thing this model could
        say before W6-H, and it is still the right answer for a job whose
        window is not set. A payload that never mentions a date must keep
        working exactly as it did."""
        response = self.plan(
            {
                "planned_hours": [{"user": self.worker.id, "hours": "43.00"}],
                "start": False,
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        row = ExtraWorkPlannedHours.objects.get(
            extra_work_request=self.ew, user=self.worker
        )
        self.assertIsNone(row.date)
        self.assertEqual(row.hours, Decimal("43.00"))

    def test_dated_and_undated_rows_coexist_for_one_person(self):
        self.plan(
            {
                "planned_hours": [
                    {
                        "user": self.worker.id,
                        "date": self.monday.isoformat(),
                        "hours": "8.00",
                    },
                    {"user": self.worker.id, "hours": "3.00"},
                ],
                "start": False,
            }
        )

        rows = ExtraWorkPlannedHours.objects.filter(
            extra_work_request=self.ew, user=self.worker
        )
        self.assertEqual(rows.count(), 2)
        self.assertEqual(rows.filter(date__isnull=True).count(), 1)

    def test_ONE_UNDATED_ROW_PER_PERSON_SURVIVED_THE_CHANGE(self):
        """Postgres treats NULLs as DISTINCT in a unique index, so
        `UniqueConstraint(work, user, date)` alone would happily allow
        five undated rows for one person — exactly what the old
        `unique_together` existed to prevent. The partial constraint is
        the only thing standing in the way, so it is tested directly at
        the database rather than through the endpoint that happens to
        avoid it.
        """
        ExtraWorkPlannedHours.objects.create(
            extra_work_request=self.ew,
            user=self.worker,
            date=None,
            hours=Decimal("5.00"),
            set_by=self.super_admin,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ExtraWorkPlannedHours.objects.create(
                    extra_work_request=self.ew,
                    user=self.worker,
                    date=None,
                    hours=Decimal("2.00"),
                    set_by=self.super_admin,
                )

    def test_one_row_per_person_per_DAY_at_the_database(self):
        ExtraWorkPlannedHours.objects.create(
            extra_work_request=self.ew,
            user=self.worker,
            date=self.monday,
            hours=Decimal("5.00"),
            set_by=self.super_admin,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ExtraWorkPlannedHours.objects.create(
                    extra_work_request=self.ew,
                    user=self.worker,
                    date=self.monday,
                    hours=Decimal("2.00"),
                    set_by=self.super_admin,
                )

    def test_NO_HISTORIC_ROW_WAS_GIVEN_A_GUESSED_DATE(self):
        """A row written before W6-H has no date and must keep none.
        Inventing one would manufacture a plan nobody made, and every
        planned-vs-actual comparison afterwards would be against a
        fiction."""
        legacy = ExtraWorkPlannedHours.objects.create(
            extra_work_request=self.ew,
            user=self.worker,
            hours=Decimal("12.00"),
            set_by=self.super_admin,
        )

        legacy.refresh_from_db()
        self.assertIsNone(legacy.date)


class AssignmentRuleUnchangedTests(DayPlanTestBase):
    def test_an_unassigned_person_is_still_refused_WITH_a_date(self):
        """Adding a day did not create a second way to attach somebody
        to a job."""
        stranger = self.make_user("w6h-stranger@example.com", UserRole.STAFF)

        response = self.plan(
            {
                "planned_hours": [
                    {
                        "user": stranger.id,
                        "date": self.monday.isoformat(),
                        "hours": "8.00",
                    }
                ],
                "start": False,
            }
        )

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data["code"], "planned_hours_invalid")
        self.assertEqual(ExtraWorkPlannedHours.objects.count(), 0)


class OverrunWarnsNeverBlocksTests(DayPlanTestBase):
    def test_A_DAY_GRID_OVER_BUDGET_SAVES_AND_WARNS(self):
        """Not negotiable. The reference system built the hard cap and
        the business had it removed: `validateTotalHours()` is still in
        their code, uncalled, beside `// Hours validation removed per
        user request`."""
        response = self.plan(
            {
                "budget_hours": "10.00",
                "planned_hours": [
                    {
                        "user": self.worker.id,
                        "date": self.monday.isoformat(),
                        "hours": "8.00",
                    },
                    {
                        "user": self.worker.id,
                        "date": self.tuesday.isoformat(),
                        "hours": "8.00",
                    },
                ],
                "start": False,
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        warnings = response.data["plan"]["warnings"]
        self.assertEqual(warnings[0]["code"], "hours_overrun")
        self.assertEqual(warnings[0]["over_by"], "6.00")
        # AND IT SAVED. This is the assertion that matters.
        self.assertEqual(
            ExtraWorkPlannedHours.objects.filter(
                extra_work_request=self.ew
            ).count(),
            2,
        )


class ReplaceSemanticsTests(DayPlanTestBase):
    def test_submitting_days_REPLACES_an_undated_total(self):
        """The operator has just decided the days. Keeping the old
        undated total alongside them would double-count the job."""
        self.plan(
            {
                "planned_hours": [{"user": self.worker.id, "hours": "14.00"}],
                "start": False,
            }
        )
        self.plan(
            {
                "planned_hours": [
                    {
                        "user": self.worker.id,
                        "date": self.monday.isoformat(),
                        "hours": "8.00",
                    },
                    {
                        "user": self.worker.id,
                        "date": self.tuesday.isoformat(),
                        "hours": "6.00",
                    },
                ],
                "start": False,
            }
        )

        rows = ExtraWorkPlannedHours.objects.filter(
            extra_work_request=self.ew, user=self.worker
        )
        self.assertEqual(rows.count(), 2)
        self.assertEqual(rows.filter(date__isnull=True).count(), 0)

    def test_clearing_one_day_removes_only_that_cell(self):
        self.plan(
            {
                "planned_hours": [
                    {
                        "user": self.worker.id,
                        "date": self.monday.isoformat(),
                        "hours": "8.00",
                    },
                    {
                        "user": self.worker.id,
                        "date": self.tuesday.isoformat(),
                        "hours": "6.00",
                    },
                ],
                "start": False,
            }
        )
        self.plan(
            {
                "planned_hours": [
                    {
                        "user": self.worker.id,
                        "date": self.monday.isoformat(),
                        "hours": "8.00",
                    }
                ],
                "start": False,
            }
        )

        rows = ExtraWorkPlannedHours.objects.filter(
            extra_work_request=self.ew, user=self.worker
        )
        self.assertEqual([row.date for row in rows], [self.monday])


class WhoMaySeeTheDaysTests(DayPlanTestBase):
    """Who may read the days, and on WHICH SURFACE.

    The surface question is settled policy, not a W6-H choice, and this
    class exists partly to record it: `scope_extra_work_for` returns
    `none()` for STAFF — the post-2026-05-20 P0 staff-privacy fix — with
    the note "Operational visibility for STAFF lives on the spawned
    Ticket". A worker therefore cannot open the parent Extra Work at
    all, so the worker's view of their own days is on the TICKET
    (`tickets.serializers._my_planned_hours`), not here.
    """

    def setUp(self):
        super().setUp()
        self.plan(
            {
                "planned_hours": [
                    {
                        "user": self.worker.id,
                        "date": self.monday.isoformat(),
                        "hours": "8.00",
                    },
                    {
                        "user": self.worker_2.id,
                        "date": self.monday.isoformat(),
                        "hours": "4.00",
                    },
                ],
                "start": False,
            }
        )

    def test_a_manager_sees_the_whole_crew_with_their_days(self):
        self.authenticate(self.company_admin)
        response = self.client.get(detail_url(self.ew.id))

        rows = response.data["planned_hours"]
        self.assertEqual(len(rows), 2)
        # `response.data` holds Python objects; the ISO string is what
        # the JSON renderer emits. Compare against what is actually
        # there rather than against the rendered form.
        self.assertEqual({row["date"] for row in rows}, {self.monday})
        self.assertEqual(
            {row["hours"] for row in rows}, {"8.00", "4.00"}
        )

    def test_A_WORKER_CANNOT_REACH_THE_EXTRA_WORK_AT_ALL(self):
        """Not a W6-H rule — the P0 staff-privacy fix. Recorded here
        because it is the reason the worker's own view of their days had
        to be built on the ticket instead."""
        self.authenticate(self.worker)
        response = self.client.get(detail_url(self.ew.id))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_the_serializer_still_narrows_to_self_as_a_second_line(self):
        """Defence in depth, tested at the function rather than through
        an endpoint that currently refuses STAFF outright. If the
        scoping rule above is ever relaxed, this is what stops a worker
        seeing the whole crew's hours on day one."""
        from extra_work.serializers import _serialize_planned_hours

        everything = _serialize_planned_hours(self.ew, viewer=self.company_admin)
        own = _serialize_planned_hours(self.ew, viewer=self.worker)

        self.assertEqual(len(everything), 2)
        self.assertEqual(len(own), 1)
        self.assertEqual(own[0]["user_id"], self.worker.id)
        self.assertEqual(own[0]["date"], self.monday)

    def test_A_CUSTOMER_SEES_NONE_OF_IT(self):
        """The customer of THIS job — not a stranger — so the assertion
        is about redaction rather than about scoping refusing them
        first."""
        self.authenticate(self.customer_user)
        response = self.client.get(detail_url(self.ew.id))

        if response.status_code == status.HTTP_200_OK:
            self.assertNotIn("planned_hours", response.data)
            self.assertNotIn("budget_hours", response.data)
        else:
            # Refused outright is a stronger answer than redacted, and
            # either one satisfies "a customer never sees any of it".
            self.assertEqual(
                response.status_code, status.HTTP_404_NOT_FOUND
            )
