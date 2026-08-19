"""
W2-D — bulk plan, and the one trap it exists to avoid.

    POST /api/extra-work/bulk-plan/

**In the reference system the two completion flags never survive a plan
write at all.** The plan modal sends `upload_is_required` and
`notes_is_required`; the config-driven update persists only the fields in
its own allow-list and neither is in it, so both are silently discarded —
0 of 78 live records has either set to true
(`docs/reference/osius-reference-system/01-extra-work.md` §1.6, §3.6).
The gap-closing brief states the same failure from the operator's side,
as "bulk plan writes both to false on every selected work". The mechanism
differs; the consequence is the same one, and it is what these tests
exist to keep out: a plan path that accepts a flag and does not carry it.

That cannot happen here by construction — there is ONE payload
serializer and ONE writer, and both read every field by key presence —
but "by construction" is a claim, so `BulkPlanCarriesTheFlagsTests`
below is the test that makes it a fact: two works with DIFFERENT flags,
one bulk plan that does not mention them, both works unchanged.

The rest of this module pins the three properties bulk plan shares with
the bulk-assign and bulk-dates endpoints next door, because a caller
should not have to learn a third dialect: all-or-nothing, one constant
rejection body for every reason (H-1), and provider-only at the door.
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


class BulkPlanTestBase(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.worker = self.make_user("w2d-bulk-worker@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.worker, building=self.building
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

    def bulk(self, body, actor=None):
        self.authenticate(actor or self.company_admin)
        return self.client.post(BULK_PLAN_URL, body, format="json")


class BulkPlanHappyPathTests(BulkPlanTestBase):
    def test_one_plan_lands_on_every_selected_work(self):
        start = timezone.localdate() + timedelta(days=7)

        response = self.bulk(
            {
                "requests": [self.ew_a.id, self.ew_b.id],
                "budget_hours": "6.00",
                "provider_planned_date": start.isoformat(),
                "provider_planned_end_date": (
                    start + timedelta(days=1)
                ).isoformat(),
                "start": False,
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["updated"], 2)
        for ew in (self.ew_a, self.ew_b):
            ew.refresh_from_db()
            self.assertEqual(ew.budget_hours, Decimal("6.00"))
            self.assertEqual(ew.provider_planned_date, start)
            self.assertEqual(
                ew.provider_planned_end_date, start + timedelta(days=1)
            )

    def test_it_reports_which_works_started_and_which_did_not(self):
        """A bulk plan where some rows cannot start is a normal outcome,
        not a failure — but an operator who is not told which learns
        nothing from a bare "2 updated"."""
        not_approved = self.make_ew(status=ExtraWorkStatus.REQUESTED)

        response = self.bulk(
            {
                "requests": [self.ew_a.id, not_approved.id],
                "budget_hours": "2.00",
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        by_id = {row["extra_work"]: row for row in response.data["results"]}
        self.assertTrue(by_id[self.ew_a.id]["started"])
        self.assertIsNone(by_id[self.ew_a.id]["start_skipped"])
        self.assertFalse(by_id[not_approved.id]["started"])
        self.assertEqual(
            by_id[not_approved.id]["start_skipped"], "invalid_transition"
        )
        # Both were still PLANNED.
        not_approved.refresh_from_db()
        self.assertEqual(not_approved.budget_hours, Decimal("2.00"))

    def test_the_customers_dates_survive_a_bulk_plan(self):
        wish = timezone.localdate() + timedelta(days=20)
        for ew in (self.ew_a, self.ew_b):
            ew.preferred_date = wish
            ew.deadline = wish + timedelta(days=5)
            ew.save(update_fields=["preferred_date", "deadline"])

        self.bulk(
            {
                "requests": [self.ew_a.id, self.ew_b.id],
                "provider_planned_date": timezone.localdate().isoformat(),
                "start": False,
            }
        )

        for ew in (self.ew_a, self.ew_b):
            ew.refresh_from_db()
            self.assertEqual(ew.preferred_date, wish)
            self.assertEqual(ew.deadline, wish + timedelta(days=5))

    def test_an_overrun_is_warned_per_work(self):
        for ew in (self.ew_a, self.ew_b):
            ExtraWorkAssignment.objects.create(
                extra_work_request=ew,
                user=self.worker,
                role=ExtraWorkAssignmentRole.WORKER,
                assigned_by=self.super_admin,
            )

        response = self.bulk(
            {
                "requests": [self.ew_a.id, self.ew_b.id],
                "budget_hours": "4.00",
                "planned_hours": [{"user": self.worker.id, "hours": "7.00"}],
                "start": False,
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        for row in response.data["results"]:
            self.assertEqual(row["warnings"][0]["code"], "hours_overrun")
            self.assertEqual(row["warnings"][0]["over_by"], "3.00")
        # And it SAVED, on both.
        self.assertEqual(
            ExtraWorkPlannedHours.objects.filter(
                user=self.worker, hours=Decimal("7.00")
            ).count(),
            2,
        )


class BulkPlanCarriesTheFlagsTests(BulkPlanTestBase):
    """The trap. See the module docstring."""

    def test_A_BULK_PLAN_THAT_DOES_NOT_MENTION_THE_FLAGS_DOES_NOT_TOUCH_THEM(
        self,
    ):
        self.ew_a.file_upload_required = True
        self.ew_a.save(update_fields=["file_upload_required"])
        self.ew_b.completion_notes_required = True
        self.ew_b.save(update_fields=["completion_notes_required"])

        response = self.bulk(
            {
                "requests": [self.ew_a.id, self.ew_b.id],
                "provider_planned_date": timezone.localdate().isoformat(),
                "start": False,
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.ew_a.refresh_from_db()
        self.ew_b.refresh_from_db()
        self.assertTrue(self.ew_a.file_upload_required)
        self.assertFalse(self.ew_a.completion_notes_required)
        self.assertTrue(self.ew_b.completion_notes_required)
        self.assertFalse(self.ew_b.file_upload_required)

    def test_a_bulk_plan_that_DOES_mention_them_writes_them_everywhere(self):
        response = self.bulk(
            {
                "requests": [self.ew_a.id, self.ew_b.id],
                "file_upload_required": True,
                "completion_notes_required": True,
                "start": False,
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        for ew in (self.ew_a, self.ew_b):
            ew.refresh_from_db()
            self.assertTrue(ew.file_upload_required)
            self.assertTrue(ew.completion_notes_required)

    def test_A_FORM_ENCODED_PLAN_CANNOT_WIPE_THE_FLAGS(self):
        """The framework's own version of the same trap, closed.

        DRF's `BooleanField.get_value` reads a boolean that is ABSENT
        from HTML form input as `False`, because an unchecked checkbox
        sends nothing. With the default parser set, a form-encoded bulk
        plan that never mentioned the completion flags would therefore
        write both to False on every selected work — the reference
        system's defect, rebuilt in our own code by a framework default
        rather than by anybody deciding it.

        Both plan endpoints are pinned to JSON, so the form-encoded
        request is refused at the door and the flags survive.
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
                "requests": [self.ew_a.id, self.ew_b.id],
                "budget_hours": "5.00",
                "start": False,
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

    def test_turning_a_flag_OFF_in_bulk_is_a_thing_somebody_asked_for(self):
        for ew in (self.ew_a, self.ew_b):
            ew.file_upload_required = True
            ew.save(update_fields=["file_upload_required"])

        self.bulk(
            {
                "requests": [self.ew_a.id, self.ew_b.id],
                "file_upload_required": False,
                "start": False,
            }
        )

        for ew in (self.ew_a, self.ew_b):
            ew.refresh_from_db()
            self.assertFalse(ew.file_upload_required)


class BulkPlanAllOrNothingTests(BulkPlanTestBase):
    def test_one_unresolvable_id_rejects_the_whole_batch(self):
        response = self.bulk(
            {
                "requests": [self.ew_a.id, self.foreign_ew.id],
                "budget_hours": "9.00",
                "start": False,
            }
        )

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.ew_a.refresh_from_db()
        self.assertIsNone(self.ew_a.budget_hours)

    def test_H1_a_foreign_id_and_a_fictional_id_answer_identically(self):
        foreign = self.bulk(
            {"requests": [self.foreign_ew.id], "budget_hours": "1.00"}
        )
        fictional = self.bulk({"requests": [98765432], "budget_hours": "1.00"})

        self.assertEqual(foreign.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(fictional.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(foreign.data, fictional.data)

    def test_a_person_missing_from_ONE_work_rejects_the_batch(self):
        ExtraWorkAssignment.objects.create(
            extra_work_request=self.ew_a,
            user=self.worker,
            role=ExtraWorkAssignmentRole.WORKER,
            assigned_by=self.super_admin,
        )

        response = self.bulk(
            {
                "requests": [self.ew_a.id, self.ew_b.id],
                "planned_hours": [{"user": self.worker.id, "hours": "3.00"}],
                "start": False,
            }
        )

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data["code"], "planned_hours_invalid")
        # Zero writes — not even on the work where the person IS assigned.
        self.assertEqual(ExtraWorkPlannedHours.objects.count(), 0)


class BulkPlanPermissionTests(BulkPlanTestBase):
    def test_a_customer_is_refused_at_the_door(self):
        response = self.bulk(
            {"requests": [self.ew_a.id], "budget_hours": "1.00"},
            actor=self.customer_user,
        )

        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN, response.data
        )
        self.assertEqual(response.data["code"], "plan_provider_only")

    def test_staff_are_refused_at_the_door(self):
        response = self.bulk(
            {"requests": [self.ew_a.id], "budget_hours": "1.00"},
            actor=self.worker,
        )

        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN, response.data
        )

    def test_a_building_manager_may_plan_their_own_building_only(self):
        mine = self.bulk(
            {"requests": [self.ew_a.id], "budget_hours": "2.00", "start": False},
            actor=self.manager,
        )
        self.assertEqual(mine.status_code, status.HTTP_200_OK, mine.data)

        elsewhere = Building.objects.create(
            company=self.company, name="Building A2", address="Side Street 2"
        )
        other_building_ew = self.make_ew(building=elsewhere)
        theirs = self.bulk(
            {
                "requests": [other_building_ew.id],
                "budget_hours": "2.00",
                "start": False,
            },
            actor=self.manager,
        )

        self.assertEqual(
            theirs.status_code, status.HTTP_400_BAD_REQUEST, theirs.data
        )
        other_building_ew.refresh_from_db()
        self.assertIsNone(other_building_ew.budget_hours)
