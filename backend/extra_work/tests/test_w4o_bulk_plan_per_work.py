"""
W4-O — per-work values in one atomic bulk plan.

    POST /api/extra-work/bulk-plan/   {"items": [{"request": ..., ...}]}
    GET  /api/extra-work/bulk-plan/?requests=1,2,3

THE GAP THIS CLOSES. The endpoint took ONE payload and copied it onto
every selected id, so work A could not be given four hours while work B
got six — and it carried no per-person distribution at all, because
hours validate against the crew of EACH work and a shared distribution
is only ever valid when the identical crew is on every selected job.

WHAT THESE TESTS PIN, beyond "the new shape works":

  * The old shared shape still means exactly what it meant. It is
    NORMALISED into the per-work list it is shorthand for, and
    `test_w2d_bulk_plan.py` (untouched) is the proof that nothing about
    it moved.
  * All-or-nothing survives per-work values. A bad ninth row rolls back
    the eight before it — including their hours rows, which are written
    through a different path than the columns.
  * The two completion flags stay independent PER ROW: a row that sets
    the photo flag cannot touch its own notes flag, and cannot touch its
    neighbour's either. This is the reference system's live defect
    (0 of 78 records carries either flag) and the one the wave-3 dialog
    nearly rebuilt with a single shared "touched" flag.
  * JSON stays pinned. A form-encoded body is refused at the door on the
    per-work shape too — and the nested `items` list has no form-data
    spelling at all, so the pin protects more than two booleans now.
  * An unassigned person names the ROW and the PERSON, and still answers
    identically for all three causes (not assigned / not visible / not
    real). The oracle property is tested as a property, by holding the
    request constant and varying only WHY it fails.
  * Overrun WARNS. Per row, on the response, with the save landing.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import Building, BuildingStaffVisibility
from extra_work.models import (
    ExtraWorkAssignment,
    ExtraWorkAssignmentRole,
    ExtraWorkCategory,
    ExtraWorkPlannedHours,
    ExtraWorkRequest,
    ExtraWorkStatus,
)
from test_utils import TenantFixtureMixin


BULK_PLAN_URL = "/api/extra-work/bulk-plan/"


class PerWorkPlanTestBase(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.worker = self.make_user("w4o-worker-a@example.com", UserRole.STAFF)
        self.worker_2 = self.make_user("w4o-worker-b@example.com", UserRole.STAFF)
        for user in (self.worker, self.worker_2):
            BuildingStaffVisibility.objects.create(
                user=user, building=self.building
            )
        # Somebody real, at another company's building. Used to prove
        # that "not assigned here" and "not yours" answer identically.
        self.foreign_worker = self.make_user(
            "w4o-foreign@example.com", UserRole.STAFF
        )
        BuildingStaffVisibility.objects.create(
            user=self.foreign_worker, building=self.other_building
        )
        self.ew_a = self.make_ew(title="Job A")
        self.ew_b = self.make_ew(title="Job B")
        self.foreign_ew = self.make_ew(
            title="Job elsewhere",
            company=self.other_company,
            building=self.other_building,
            customer=self.other_customer,
        )

    def make_ew(self, **kwargs) -> ExtraWorkRequest:
        defaults = dict(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Job",
            description="x",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
        )
        defaults.update(kwargs)
        return ExtraWorkRequest.objects.create(**defaults)

    def assign(self, extra_work, user):
        return ExtraWorkAssignment.objects.create(
            extra_work_request=extra_work,
            user=user,
            role=ExtraWorkAssignmentRole.WORKER,
            assigned_by=self.super_admin,
        )

    def bulk(self, body, actor=None):
        self.authenticate(actor or self.company_admin)
        return self.client.post(BULK_PLAN_URL, body, format="json")

    def context(self, ids, actor=None):
        self.authenticate(actor or self.company_admin)
        return self.client.get(
            BULK_PLAN_URL,
            {"requests": ",".join(str(i) for i in ids)},
        )


class PerWorkValuesTests(PerWorkPlanTestBase):
    """Requirement 1 — each id carries its own values, in ONE call."""

    def test_FOUR_HOURS_ON_ONE_WORK_AND_SIX_ON_THE_OTHER(self):
        """The gap, stated as a test. This was not expressible before."""
        start_a = timezone.localdate() + timedelta(days=3)
        start_b = timezone.localdate() + timedelta(days=9)

        response = self.bulk(
            {
                "items": [
                    {
                        "request": self.ew_a.id,
                        "budget_hours": "4.00",
                        "provider_planned_date": start_a.isoformat(),
                        "start": False,
                    },
                    {
                        "request": self.ew_b.id,
                        "budget_hours": "6.00",
                        "provider_planned_date": start_b.isoformat(),
                        "start": False,
                    },
                ]
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["updated"], 2)
        self.ew_a.refresh_from_db()
        self.ew_b.refresh_from_db()
        self.assertEqual(self.ew_a.budget_hours, Decimal("4.00"))
        self.assertEqual(self.ew_b.budget_hours, Decimal("6.00"))
        self.assertEqual(self.ew_a.provider_planned_date, start_a)
        self.assertEqual(self.ew_b.provider_planned_date, start_b)

    def test_a_row_that_says_nothing_about_a_field_leaves_it_alone(self):
        """KEY PRESENCE, per row. Row A sets a budget and says nothing
        about the window; row B sets the window and says nothing about
        the budget. Neither may bleed into the other."""
        existing = timezone.localdate() + timedelta(days=40)
        self.ew_a.provider_planned_date = existing
        self.ew_a.save(update_fields=["provider_planned_date"])
        self.ew_b.budget_hours = Decimal("11.00")
        self.ew_b.save(update_fields=["budget_hours"])

        new_window = timezone.localdate() + timedelta(days=2)
        response = self.bulk(
            {
                "items": [
                    {
                        "request": self.ew_a.id,
                        "budget_hours": "3.00",
                        "start": False,
                    },
                    {
                        "request": self.ew_b.id,
                        "provider_planned_date": new_window.isoformat(),
                        "start": False,
                    },
                ]
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.ew_a.refresh_from_db()
        self.ew_b.refresh_from_db()
        self.assertEqual(self.ew_a.budget_hours, Decimal("3.00"))
        self.assertEqual(self.ew_a.provider_planned_date, existing)
        self.assertEqual(self.ew_b.budget_hours, Decimal("11.00"))
        self.assertEqual(self.ew_b.provider_planned_date, new_window)

    def test_a_row_may_clear_what_its_neighbour_sets(self):
        """`null` clears, absent leaves alone — and the two states stay
        distinguishable INSIDE one batch, which is the whole point of
        reading by presence rather than by truthiness."""
        for ew in (self.ew_a, self.ew_b):
            ew.budget_hours = Decimal("5.00")
            ew.save(update_fields=["budget_hours"])

        response = self.bulk(
            {
                "items": [
                    {
                        "request": self.ew_a.id,
                        "budget_hours": None,
                        "start": False,
                    },
                    {
                        "request": self.ew_b.id,
                        "budget_hours": "8.00",
                        "start": False,
                    },
                ]
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.ew_a.refresh_from_db()
        self.ew_b.refresh_from_db()
        self.assertIsNone(self.ew_a.budget_hours)
        self.assertEqual(self.ew_b.budget_hours, Decimal("8.00"))

    def test_ZERO_BUDGET_IS_NOT_NO_BUDGET(self):
        """Zero is a legal value and it is not the same as unset. A row
        that budgets zero hours has been planned; a row with no budget
        has not, and `hours_overrun` treats them differently on purpose
        (no budget means nothing to overrun)."""
        response = self.bulk(
            {
                "items": [
                    {
                        "request": self.ew_a.id,
                        "budget_hours": "0.00",
                        "start": False,
                    },
                    {"request": self.ew_b.id, "start": False},
                ]
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.ew_a.refresh_from_db()
        self.ew_b.refresh_from_db()
        self.assertEqual(self.ew_a.budget_hours, Decimal("0.00"))
        self.assertIsNone(self.ew_b.budget_hours)

    def test_a_row_may_start_while_its_neighbour_does_not(self):
        response = self.bulk(
            {
                "items": [
                    {
                        "request": self.ew_a.id,
                        "budget_hours": "1.00",
                        "start": True,
                    },
                    {
                        "request": self.ew_b.id,
                        "budget_hours": "1.00",
                        "start": False,
                    },
                ]
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        by_id = {row["extra_work"]: row for row in response.data["results"]}
        self.assertTrue(by_id[self.ew_a.id]["started"])
        self.assertFalse(by_id[self.ew_b.id]["started"])
        self.assertEqual(
            by_id[self.ew_b.id]["start_skipped"], "start_not_requested"
        )

    def test_a_row_carrying_only_start_is_not_nothing_to_plan(self):
        """The dialog's untouched rows. Selecting twelve works and
        editing three must still START all twelve — that is what bulk
        plan did before per-work values existed, and it must not become
        an error just because the other nine carry no fields."""
        response = self.bulk(
            {
                "items": [
                    {"request": self.ew_a.id, "budget_hours": "2.00"},
                    {"request": self.ew_b.id, "start": True},
                ]
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.ew_b.refresh_from_db()
        self.assertEqual(self.ew_b.status, ExtraWorkStatus.IN_PROGRESS)
        self.assertIsNone(self.ew_b.budget_hours)

    def test_a_row_that_says_nothing_at_all_rejects_the_batch(self):
        response = self.bulk(
            {
                "items": [
                    {"request": self.ew_a.id, "budget_hours": "2.00"},
                    {"request": self.ew_b.id},
                ]
            }
        )

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data["code"], "nothing_to_plan")
        self.assertEqual(response.data["extra_work"], self.ew_b.id)
        # Zero writes — not even on the row that was fine.
        self.ew_a.refresh_from_db()
        self.assertIsNone(self.ew_a.budget_hours)


class PerWorkHoursTests(PerWorkPlanTestBase):
    """Requirement 2 — each work's hours go to the crew on THAT work."""

    def test_TWO_WORKS_WITH_DIFFERENT_CREWS_IN_ONE_CALL(self):
        """The thing a shared payload could never express. Worker A is on
        job A only, worker B on job B only, and both are budgeted in one
        atomic call."""
        self.assign(self.ew_a, self.worker)
        self.assign(self.ew_b, self.worker_2)

        response = self.bulk(
            {
                "items": [
                    {
                        "request": self.ew_a.id,
                        "budget_hours": "4.00",
                        "planned_hours": [
                            {"user": self.worker.id, "hours": "4.00"}
                        ],
                        "start": False,
                    },
                    {
                        "request": self.ew_b.id,
                        "budget_hours": "6.00",
                        "planned_hours": [
                            {"user": self.worker_2.id, "hours": "6.00"}
                        ],
                        "start": False,
                    },
                ]
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(
            ExtraWorkPlannedHours.objects.get(
                extra_work_request=self.ew_a
            ).user_id,
            self.worker.id,
        )
        self.assertEqual(
            ExtraWorkPlannedHours.objects.get(
                extra_work_request=self.ew_b
            ).hours,
            Decimal("6.00"),
        )

    def test_the_same_person_may_get_different_hours_on_each_work(self):
        self.assign(self.ew_a, self.worker)
        self.assign(self.ew_b, self.worker)

        self.bulk(
            {
                "items": [
                    {
                        "request": self.ew_a.id,
                        "planned_hours": [
                            {"user": self.worker.id, "hours": "2.50"}
                        ],
                        "start": False,
                    },
                    {
                        "request": self.ew_b.id,
                        "planned_hours": [
                            {"user": self.worker.id, "hours": "7.25"}
                        ],
                        "start": False,
                    },
                ]
            }
        )

        self.assertEqual(
            ExtraWorkPlannedHours.objects.get(
                extra_work_request=self.ew_a, user=self.worker
            ).hours,
            Decimal("2.50"),
        )
        self.assertEqual(
            ExtraWorkPlannedHours.objects.get(
                extra_work_request=self.ew_b, user=self.worker
            ).hours,
            Decimal("7.25"),
        )

    def test_AN_UNASSIGNED_PERSON_NAMES_THE_WORK_AND_THE_PERSON(self):
        """Requirement 2's other half. A generic 400 over a twelve-row
        table reads as a broken dialog; the operator cannot tell which
        row to fix."""
        self.assign(self.ew_a, self.worker)

        response = self.bulk(
            {
                "items": [
                    {
                        "request": self.ew_a.id,
                        "planned_hours": [
                            {"user": self.worker.id, "hours": "3.00"}
                        ],
                        "start": False,
                    },
                    {
                        "request": self.ew_b.id,
                        "planned_hours": [
                            {"user": self.worker_2.id, "hours": "3.00"}
                        ],
                        "start": False,
                    },
                ]
            }
        )

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data["code"], "planned_hours_invalid")
        self.assertEqual(response.data["extra_work"], self.ew_b.id)
        self.assertEqual(response.data["user"], self.worker_2.id)
        self.assertIn("Job B", response.data["detail"])
        self.assertIn(str(self.worker_2.id), response.data["detail"])
        # And zero writes, including on the row that WAS valid.
        self.assertEqual(ExtraWorkPlannedHours.objects.count(), 0)

    def test_H1_THE_NAMED_ROW_IS_STILL_NOT_AN_ORACLE(self):
        """Naming the row is safe; naming the CAUSE would not be.

        The property is not "two bodies are byte-equal" — the bodies
        echo ids the caller sent, so different ids give different bytes
        and that is information the caller already had. The property is
        that the body is a PURE FUNCTION OF THE REQUEST: hold the
        request constant, vary only why it fails, and nothing moves.

        Here that is done by sending the same shape three times with
        three different user ids and comparing the bodies with the
        echoed id substituted out. A response that distinguished "not
        assigned" from "no such account" would fail this even though
        every individual body looks innocent.
        """
        bodies = []
        probes = [
            self.other_customer_user.id,  # exists, not assigned here
            self.foreign_worker.id,  # exists, another tenant's building
            98765432,  # does not exist at all
        ]
        for user_id in probes:
            response = self.bulk(
                {
                    "items": [
                        {
                            "request": self.ew_a.id,
                            "planned_hours": [
                                {"user": user_id, "hours": "1.00"}
                            ],
                            "start": False,
                        }
                    ]
                }
            )
            self.assertEqual(
                response.status_code, status.HTTP_400_BAD_REQUEST, response.data
            )
            body = dict(response.data)
            # Substitute the caller's own id back out — everything that
            # remains is server-derived and must be identical.
            body["detail"] = str(body["detail"]).replace(
                f"#{user_id}", "#<echoed>"
            )
            body["user"] = "<echoed>"
            bodies.append(body)

        self.assertEqual(bodies[0], bodies[1])
        self.assertEqual(bodies[1], bodies[2])

    def test_the_same_person_twice_in_one_row_names_that_row(self):
        self.assign(self.ew_a, self.worker)

        response = self.bulk(
            {
                "items": [
                    {
                        "request": self.ew_a.id,
                        "planned_hours": [
                            {"user": self.worker.id, "hours": "1.00"},
                            {"user": self.worker.id, "hours": "2.00"},
                        ],
                        "start": False,
                    }
                ]
            }
        )

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            response.data["code"], "planned_hours_duplicate_user"
        )
        self.assertEqual(response.data["extra_work"], self.ew_a.id)
        self.assertEqual(response.data["user"], self.worker.id)

    def test_ZERO_HOURS_FOR_A_PERSON_IS_NOT_NO_LINE_FOR_THEM(self):
        """On the crew with nothing budgeted yet is a state. Dropping the
        line to say so would lose the fact that they are on the job."""
        self.assign(self.ew_a, self.worker)

        self.bulk(
            {
                "items": [
                    {
                        "request": self.ew_a.id,
                        "planned_hours": [
                            {"user": self.worker.id, "hours": "0.00"}
                        ],
                        "start": False,
                    }
                ]
            }
        )

        row = ExtraWorkPlannedHours.objects.get(
            extra_work_request=self.ew_a, user=self.worker
        )
        self.assertEqual(row.hours, Decimal("0.00"))

    def test_AN_INVALID_LAST_ROW_ROLLS_BACK_THE_HOURS_OF_THE_FIRST(self):
        """All-or-nothing across the OTHER write path. Columns and hours
        rows are written by different code; a rollback that only covered
        one of them would leave the batch half-applied in the way an
        operator is least able to see."""
        self.assign(self.ew_a, self.worker)
        ew_c = self.make_ew(title="Job C")

        response = self.bulk(
            {
                "items": [
                    {
                        "request": self.ew_a.id,
                        "budget_hours": "5.00",
                        "planned_hours": [
                            {"user": self.worker.id, "hours": "5.00"}
                        ],
                        "start": False,
                    },
                    {
                        "request": ew_c.id,
                        "planned_hours": [
                            {"user": self.worker.id, "hours": "1.00"}
                        ],
                        "start": False,
                    },
                ]
            }
        )

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.ew_a.refresh_from_db()
        self.assertIsNone(self.ew_a.budget_hours)
        self.assertEqual(ExtraWorkPlannedHours.objects.count(), 0)


class PerWorkFlagIndependenceTests(PerWorkPlanTestBase):
    """Regression (b) — one flag per switch, proven on the wire.

    Wave 3 caught its own version of this in the dialog: a single shared
    "touched" flag meant flipping "photo required" also sent
    `completion_notes_required: false`. On a bulk table the switches
    start unseeded, so one flip would have cleared the notes flag on
    every work in the batch. These tests prove the SERVER cannot be
    talked into that, whichever row does the talking.
    """

    def test_a_row_setting_ONE_flag_does_not_touch_the_other(self):
        self.ew_a.completion_notes_required = True
        self.ew_a.save(update_fields=["completion_notes_required"])

        response = self.bulk(
            {
                "items": [
                    {
                        "request": self.ew_a.id,
                        "file_upload_required": True,
                        "start": False,
                    }
                ]
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.ew_a.refresh_from_db()
        self.assertTrue(self.ew_a.file_upload_required)
        self.assertTrue(self.ew_a.completion_notes_required)

    def test_a_row_setting_a_flag_does_not_touch_its_NEIGHBOURS_flags(self):
        self.ew_b.file_upload_required = True
        self.ew_b.completion_notes_required = True
        self.ew_b.save(
            update_fields=[
                "file_upload_required",
                "completion_notes_required",
            ]
        )

        response = self.bulk(
            {
                "items": [
                    {
                        "request": self.ew_a.id,
                        "file_upload_required": True,
                        "completion_notes_required": False,
                        "start": False,
                    },
                    {
                        "request": self.ew_b.id,
                        "budget_hours": "2.00",
                        "start": False,
                    },
                ]
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.ew_a.refresh_from_db()
        self.ew_b.refresh_from_db()
        self.assertTrue(self.ew_a.file_upload_required)
        self.assertFalse(self.ew_a.completion_notes_required)
        # Untouched by a row that never mentioned them.
        self.assertTrue(self.ew_b.file_upload_required)
        self.assertTrue(self.ew_b.completion_notes_required)

    def test_TURNING_A_FLAG_OFF_ON_ONE_ROW_ONLY(self):
        for ew in (self.ew_a, self.ew_b):
            ew.file_upload_required = True
            ew.save(update_fields=["file_upload_required"])

        self.bulk(
            {
                "items": [
                    {
                        "request": self.ew_a.id,
                        "file_upload_required": False,
                        "start": False,
                    },
                    {
                        "request": self.ew_b.id,
                        "budget_hours": "1.00",
                        "start": False,
                    },
                ]
            }
        )

        self.ew_a.refresh_from_db()
        self.ew_b.refresh_from_db()
        self.assertFalse(self.ew_a.file_upload_required)
        self.assertTrue(self.ew_b.file_upload_required)

    def test_A_FORM_ENCODED_PER_WORK_PLAN_IS_REFUSED_AT_THE_DOOR(self):
        """Regression (a), on the new shape.

        DRF reads a boolean ABSENT from form input as `False`, so a
        form-encoded plan would write both flags to false on every
        selected work. The per-work shape raises the stakes: a nested
        `items` list has no form-data spelling at all, so the same
        request would also lose the structure. Pinned to JSON, and
        answered 415 before a parser ever sees it.
        """
        for ew in (self.ew_a, self.ew_b):
            ew.file_upload_required = True
            ew.completion_notes_required = True
            ew.save(
                update_fields=[
                    "file_upload_required",
                    "completion_notes_required",
                ]
            )

        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_PLAN_URL,
            {
                "items[0]request": self.ew_a.id,
                "items[0]budget_hours": "5.00",
            },
            format="multipart",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            response.data,
        )
        for ew in (self.ew_a, self.ew_b):
            ew.refresh_from_db()
            self.assertTrue(ew.file_upload_required)
            self.assertTrue(ew.completion_notes_required)
            self.assertIsNone(ew.budget_hours)


class OverrunWarnsNeverBlocksTests(PerWorkPlanTestBase):
    """Regression (c). The reference system built the hard cap, and the
    business had it removed — `validateTotalHours()` still exists there,
    uncalled, next to `// Hours validation removed per user request`.
    """

    def test_AN_OVERRUN_SAVES_AND_WARNS_PER_ROW(self):
        self.assign(self.ew_a, self.worker)
        self.assign(self.ew_b, self.worker_2)

        response = self.bulk(
            {
                "items": [
                    {
                        "request": self.ew_a.id,
                        "budget_hours": "4.00",
                        "planned_hours": [
                            {"user": self.worker.id, "hours": "9.00"}
                        ],
                        "start": False,
                    },
                    {
                        "request": self.ew_b.id,
                        "budget_hours": "10.00",
                        "planned_hours": [
                            {"user": self.worker_2.id, "hours": "2.00"}
                        ],
                        "start": False,
                    },
                ]
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        by_id = {row["extra_work"]: row for row in response.data["results"]}
        self.assertEqual(
            by_id[self.ew_a.id]["warnings"][0]["code"], "hours_overrun"
        )
        self.assertEqual(by_id[self.ew_a.id]["warnings"][0]["over_by"], "5.00")
        # The row that is under budget carries no warning at all.
        self.assertEqual(by_id[self.ew_b.id]["warnings"], [])
        # AND IT SAVED. This is the assertion that matters.
        self.assertEqual(
            ExtraWorkPlannedHours.objects.get(
                extra_work_request=self.ew_a
            ).hours,
            Decimal("9.00"),
        )
        self.ew_a.refresh_from_db()
        self.assertEqual(self.ew_a.budget_hours, Decimal("4.00"))


class ShapeTests(PerWorkPlanTestBase):
    """One endpoint, two spellings, no mixture and no precedence rule."""

    def test_the_shared_spelling_still_works_unchanged(self):
        response = self.bulk(
            {
                "requests": [self.ew_a.id, self.ew_b.id],
                "budget_hours": "3.00",
                "start": False,
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        for ew in (self.ew_a, self.ew_b):
            ew.refresh_from_db()
            self.assertEqual(ew.budget_hours, Decimal("3.00"))

    def test_BOTH_SPELLINGS_AT_ONCE_IS_REFUSED(self):
        response = self.bulk(
            {
                "requests": [self.ew_a.id],
                "items": [{"request": self.ew_b.id, "budget_hours": "1.00"}],
            }
        )

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            response.data["code"], "extra_work_bulk_plan_shape_invalid"
        )
        self.ew_a.refresh_from_db()
        self.assertIsNone(self.ew_a.budget_hours)

    def test_a_shared_field_beside_items_is_refused_rather_than_ranked(self):
        """There is no precedence rule, on purpose: a rule about which
        value wins is a thing an operator has to learn and a client can
        get wrong in silence."""
        response = self.bulk(
            {
                "budget_hours": "3.00",
                "items": [{"request": self.ew_a.id, "budget_hours": "1.00"}],
            }
        )

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            response.data["code"], "extra_work_bulk_plan_shape_invalid"
        )
        self.assertIn("budget_hours", str(response.data["detail"]))

    def test_neither_spelling_is_refused(self):
        response = self.bulk({"budget_hours": "3.00"})
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            response.data["code"], "extra_work_bulk_plan_shape_invalid"
        )

    def test_the_same_work_twice_in_items_is_refused(self):
        response = self.bulk(
            {
                "items": [
                    {"request": self.ew_a.id, "budget_hours": "1.00"},
                    {"request": self.ew_a.id, "budget_hours": "2.00"},
                ]
            }
        )

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            response.data["code"], "extra_work_bulk_plan_shape_invalid"
        )
        self.ew_a.refresh_from_db()
        self.assertIsNone(self.ew_a.budget_hours)


class PerWorkScopeTests(PerWorkPlanTestBase):
    """Property (2) is unchanged by per-work values: a WORK that does not
    resolve still gets the constant body, whichever spelling asked."""

    def test_a_foreign_id_in_items_rejects_the_batch(self):
        response = self.bulk(
            {
                "items": [
                    {
                        "request": self.ew_a.id,
                        "budget_hours": "1.00",
                        "start": False,
                    },
                    {
                        "request": self.foreign_ew.id,
                        "budget_hours": "2.00",
                        "start": False,
                    },
                ]
            }
        )

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.ew_a.refresh_from_db()
        self.assertIsNone(self.ew_a.budget_hours)

    def test_H1_a_foreign_work_and_a_fictional_work_answer_identically(self):
        foreign = self.bulk(
            {"items": [{"request": self.foreign_ew.id, "budget_hours": "1.00"}]}
        )
        fictional = self.bulk(
            {"items": [{"request": 98765432, "budget_hours": "1.00"}]}
        )

        self.assertEqual(foreign.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(fictional.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(foreign.data, fictional.data)

    def test_a_building_manager_may_plan_their_own_building_only(self):
        elsewhere = Building.objects.create(
            company=self.company, name="Building W4O", address="Side Street 9"
        )
        other_building_ew = self.make_ew(building=elsewhere)

        theirs = self.bulk(
            {
                "items": [
                    {
                        "request": other_building_ew.id,
                        "budget_hours": "2.00",
                        "start": False,
                    }
                ]
            },
            actor=self.manager,
        )

        self.assertEqual(
            theirs.status_code, status.HTTP_400_BAD_REQUEST, theirs.data
        )
        other_building_ew.refresh_from_db()
        self.assertIsNone(other_building_ew.budget_hours)

    def test_a_customer_is_refused_at_the_door(self):
        response = self.bulk(
            {"items": [{"request": self.ew_a.id, "budget_hours": "1.00"}]},
            actor=self.customer_user,
        )

        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN, response.data
        )
        self.assertEqual(response.data["code"], "plan_provider_only")


class PlanningContextReadTests(PerWorkPlanTestBase):
    """The GET the per-work table is seeded from.

    Without it every row opens blank and saving looks like it wiped what
    was there — the list payload carries none of the planning fields
    (they are provider-only) and none of the crew.
    """

    def test_it_answers_the_whole_selection_with_what_each_work_plans_now(self):
        self.ew_a.budget_hours = Decimal("4.00")
        self.ew_a.file_upload_required = True
        self.ew_a.save(
            update_fields=["budget_hours", "file_upload_required"]
        )
        self.assign(self.ew_a, self.worker)
        ExtraWorkPlannedHours.objects.create(
            extra_work_request=self.ew_a,
            user=self.worker,
            hours=Decimal("4.00"),
            set_by=self.super_admin,
        )

        response = self.context([self.ew_a.id, self.ew_b.id])

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        by_id = {row["extra_work"]: row for row in response.data["works"]}
        self.assertEqual(by_id[self.ew_a.id]["budget_hours"], "4.00")
        self.assertTrue(by_id[self.ew_a.id]["file_upload_required"])
        self.assertFalse(by_id[self.ew_a.id]["completion_notes_required"])
        self.assertEqual(by_id[self.ew_a.id]["planned_hours_total"], "4.00")
        self.assertEqual(
            by_id[self.ew_a.id]["crew"][0]["user_id"], self.worker.id
        )
        # And the untouched work reports "nothing planned" rather than a
        # zero, because those are not the same fact.
        self.assertIsNone(by_id[self.ew_b.id]["budget_hours"])
        self.assertEqual(by_id[self.ew_b.id]["planned_hours"], [])

    def test_HOURS_OF_SOMEONE_NO_LONGER_ASSIGNED_STAY_VISIBLE(self):
        """The reference system's §4.4 defect, refused on this surface
        too: over there the grid is built from the assignment list, so a
        removed worker's hours vanish from the screen while staying in
        every total."""
        self.assign(self.ew_a, self.worker)
        ExtraWorkPlannedHours.objects.create(
            extra_work_request=self.ew_a,
            user=self.worker,
            hours=Decimal("6.00"),
            set_by=self.super_admin,
        )
        ExtraWorkAssignment.objects.filter(
            extra_work_request=self.ew_a, user=self.worker
        ).delete()

        response = self.context([self.ew_a.id])

        row = response.data["works"][0]
        self.assertEqual(row["crew"], [])
        self.assertEqual(len(row["planned_hours"]), 1)
        self.assertFalse(row["planned_hours"][0]["is_assigned"])
        self.assertEqual(row["planned_hours_total"], "6.00")

    def test_the_overrun_is_reported_on_the_read_as_well(self):
        self.assign(self.ew_a, self.worker)
        self.ew_a.budget_hours = Decimal("2.00")
        self.ew_a.save(update_fields=["budget_hours"])
        ExtraWorkPlannedHours.objects.create(
            extra_work_request=self.ew_a,
            user=self.worker,
            hours=Decimal("5.00"),
            set_by=self.super_admin,
        )

        row = self.context([self.ew_a.id]).data["works"][0]

        self.assertEqual(row["planned_hours_overrun"]["over_by"], "3.00")

    def test_the_read_is_gated_exactly_like_the_write(self):
        """A read that could see a work the write could not touch would
        be a second, weaker gate on the same data."""
        customer = self.context([self.ew_a.id], actor=self.customer_user)
        self.assertEqual(customer.status_code, status.HTTP_403_FORBIDDEN)

        staff = self.context([self.ew_a.id], actor=self.worker)
        self.assertEqual(staff.status_code, status.HTTP_403_FORBIDDEN)

        foreign = self.context([self.foreign_ew.id])
        self.assertEqual(foreign.status_code, status.HTTP_400_BAD_REQUEST)

    def test_H1_a_foreign_work_and_a_fiction_read_identically(self):
        foreign = self.context([self.foreign_ew.id])
        fictional = self.context([98765432])

        self.assertEqual(foreign.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(foreign.data, fictional.data)

    def test_it_takes_repeated_keys_as_well_as_a_comma_list(self):
        """axios serialises an array as repeated keys; a hand-built URL
        uses the comma. Accepting one and ignoring the other is how a
        selection of twelve becomes a context fetch for one."""
        self.authenticate(self.company_admin)
        response = self.client.get(
            BULK_PLAN_URL + f"?requests={self.ew_a.id}&requests={self.ew_b.id}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(len(response.data["works"]), 2)

    def test_a_malformed_id_is_the_shape_error(self):
        self.authenticate(self.company_admin)
        response = self.client.get(BULK_PLAN_URL + "?requests=abc")

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            response.data["code"], "extra_work_bulk_plan_shape_invalid"
        )

    def test_no_ids_at_all_is_the_shape_error(self):
        self.authenticate(self.company_admin)
        response = self.client.get(BULK_PLAN_URL)

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            response.data["code"], "extra_work_bulk_plan_shape_invalid"
        )

    def test_the_read_cost_does_not_grow_with_the_selection(self):
        """A per-work table opens on a selection that can be a whole page
        of results. The obvious implementation calls the detail
        serializer's helper per work — two queries EACH — so a selection
        of forty would be eighty round trips to open a dialog.

        Run as SUPER_ADMIN deliberately. The per-row BUILDING check that
        every other provider role goes through is a per-work question by
        definition (property 3), so including it would measure that
        instead of the thing this test is about. What is pinned here is
        that READING the plans is batched.
        """
        extra = [self.make_ew(title=f"Job {n}") for n in range(6)]
        for ew in extra:
            self.assign(ew, self.worker)
            ExtraWorkPlannedHours.objects.create(
                extra_work_request=ew,
                user=self.worker,
                hours=Decimal("1.00"),
                set_by=self.super_admin,
            )

        self.authenticate(self.super_admin)
        two = [self.ew_a.id, self.ew_b.id]
        eight = two + [ew.id for ew in extra]

        with CaptureQueries(self) as small:
            self.client.get(
                BULK_PLAN_URL,
                {"requests": ",".join(str(i) for i in two)},
            )
        with CaptureQueries(self) as large:
            self.client.get(
                BULK_PLAN_URL,
                {"requests": ",".join(str(i) for i in eight)},
            )

        self.assertEqual(
            small.count,
            large.count,
            "the planning-context read must cost the same for 2 works and "
            "for 8 — it grew, so something in it is per-work",
        )


class CaptureQueries:
    """`assertNumQueries` compares against a literal; this compares two
    runs against each other, which is the actual claim (constant cost),
    and does not have to be re-tuned every time an unrelated middleware
    adds a query."""

    def __init__(self, case):
        self.case = case
        self.count = 0

    def __enter__(self):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        self._ctx = CaptureQueriesContext(connection)
        self._ctx.__enter__()
        return self

    def __exit__(self, *exc):
        result = self._ctx.__exit__(*exc)
        self.count = len(self._ctx.captured_queries)
        return result
