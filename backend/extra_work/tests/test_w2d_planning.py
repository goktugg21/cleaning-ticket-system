"""
W2-D — the planning layer: budget hours, the committed window, hours per
person, and plan-and-start as one action.

Six properties are pinned here, each because getting it wrong is a
defect somebody can point at in the reference system this work closes
the gap against (`docs/reference/osius-reference-system/`):

1. **The customer's dates are not overwritten.** Two pairs are stored:
   what they asked for (`preferred_date` -> `planned_end_date`, plus
   `deadline`) and what we committed to (`provider_planned_date` ->
   `provider_planned_end_date`). The plan action writes the second and
   never the first, which is the only way to answer later "did we do
   what we promised, or what they asked for?".

2. **Overrun warns and never blocks.** Their hard cap
   (`validateTotalHours()`) exists as a complete function and is never
   called, with `// Hours validation removed per user request` in the
   model's boot. The business had the block removed. We warn.

3. **Hours belonging to a person who has been un-assigned stay visible
   and stay counted.** Over there the grid is built from the assignment
   list, so those hours vanish from the screen and stay in every total —
   live work 474 shows 13.5 distributed hours against a budget of 1.00
   with no warning anywhere.

4. **Zero is not the same as unset.** A budget of 0.00 and an
   unbudgeted job are different facts, exactly as an unpriced work and a
   free one are (Sprint 188).

5. **A start that cannot happen is reported, not raised.** Once the work
   has an operational ticket its status follows that ticket (Sprint 181
   §1) — the plan still lands and the response says why it did not
   start.

6. **Planning is provider-only, and a customer never sees the budget or
   the distribution.** Those are numbers about our own people, and one
   of them names them.

Bulk plan has its own module (`test_w2d_bulk_plan.py`) because the trap
it avoids is a different one.
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
    ExtraWorkStatusHistory,
)
from test_utils import TenantFixtureMixin
from tickets.models import Ticket


def plan_url(request_id: int) -> str:
    return f"/api/extra-work/{request_id}/plan/"


def detail_url(request_id: int) -> str:
    return f"/api/extra-work/{request_id}/"


class PlanTestBase(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # Two WORKER-eligible people at the request's building. Worker
        # eligibility is `BuildingStaffVisibility` on that building
        # (Sprint 158 §1) — this test file does not re-derive that rule,
        # it uses the same one the assign endpoint does.
        self.worker = self.make_user("w2d-worker@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.worker, building=self.building
        )
        self.worker_2 = self.make_user("w2d-worker2@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.worker_2, building=self.building
        )
        # Somebody real, at another company's building. Used to prove
        # that "not assigned here" and "not yours" answer identically.
        self.foreign_worker = self.make_user(
            "w2d-foreign@example.com", UserRole.STAFF
        )
        BuildingStaffVisibility.objects.create(
            user=self.foreign_worker, building=self.other_building
        )

        self.ew = self.make_ew()
        self.foreign_ew = self.make_ew(
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
            title="Strip and seal the corridor",
            description="x",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
        )
        defaults.update(kwargs)
        return ExtraWorkRequest.objects.create(**defaults)

    def assign(self, extra_work, user, role=ExtraWorkAssignmentRole.WORKER):
        return ExtraWorkAssignment.objects.create(
            extra_work_request=extra_work,
            user=user,
            role=role,
            assigned_by=self.super_admin,
        )

    def plan(self, extra_work, body, actor=None):
        self.authenticate(actor or self.company_admin)
        return self.client.post(plan_url(extra_work.id), body, format="json")


# ---------------------------------------------------------------------------
# 1. Budget hours, the committed window, and the customer's dates
# ---------------------------------------------------------------------------
class BudgetAndWindowTests(PlanTestBase):
    def test_a_plan_writes_the_budget_and_the_committed_window(self):
        start = timezone.localdate() + timedelta(days=3)
        end = start + timedelta(days=2)

        response = self.plan(
            self.ew,
            {
                "budget_hours": "8.50",
                "provider_planned_date": start.isoformat(),
                "provider_planned_end_date": end.isoformat(),
                "start": False,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.ew.refresh_from_db()
        self.assertEqual(self.ew.budget_hours, Decimal("8.50"))
        self.assertEqual(self.ew.provider_planned_date, start)
        self.assertEqual(self.ew.provider_planned_end_date, end)

    def test_the_response_RENDERS_what_it_just_set(self):
        """Sprint 174 §0's rule: a field is not done until a test renders
        the endpoint carrying it. A `fields` mismatch asserts here rather
        than as a 500 on the live site."""
        start = timezone.localdate() + timedelta(days=1)

        response = self.plan(
            self.ew,
            {
                "budget_hours": "4.00",
                "provider_planned_date": start.isoformat(),
                "file_upload_required": True,
                "start": False,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        for key in (
            "budget_hours",
            "provider_planned_date",
            "provider_planned_end_date",
            "planned_hours",
            "planned_hours_total",
            "planned_hours_overrun",
            "file_upload_required",
            "completion_notes_required",
            "plan",
        ):
            with self.subTest(key=key):
                self.assertIn(key, response.data)
        self.assertEqual(str(response.data["budget_hours"]), "4.00")
        self.assertTrue(response.data["file_upload_required"])

    def test_ZERO_budget_hours_is_not_the_same_as_unbudgeted(self):
        """The Sprint 188 distinction, applied to hours: "we budgeted no
        hours" and "nobody has budgeted this" are different facts and
        must not render the same."""
        response = self.plan(self.ew, {"budget_hours": "0.00", "start": False})

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.ew.refresh_from_db()
        self.assertIsNotNone(self.ew.budget_hours)
        self.assertEqual(self.ew.budget_hours, Decimal("0.00"))
        self.assertEqual(str(response.data["budget_hours"]), "0.00")

        # ...and an explicit null is how you say "unbudgeted" again.
        response = self.plan(self.ew, {"budget_hours": None, "start": False})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.ew.refresh_from_db()
        self.assertIsNone(self.ew.budget_hours)
        self.assertIsNone(response.data["budget_hours"])

    def test_THE_PLAN_DOES_NOT_TOUCH_THE_CUSTOMERS_DATES(self):
        """The headline property. Two pairs, both stored, one writer each."""
        wish = timezone.localdate() + timedelta(days=10)
        wish_end = wish + timedelta(days=1)
        due = wish + timedelta(days=20)
        self.ew.preferred_date = wish
        self.ew.planned_end_date = wish_end
        self.ew.deadline = due
        self.ew.save(
            update_fields=["preferred_date", "planned_end_date", "deadline"]
        )

        committed = timezone.localdate() + timedelta(days=2)
        response = self.plan(
            self.ew,
            {
                "provider_planned_date": committed.isoformat(),
                "provider_planned_end_date": (
                    committed + timedelta(days=1)
                ).isoformat(),
                "start": False,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.ew.refresh_from_db()
        self.assertEqual(self.ew.preferred_date, wish)
        self.assertEqual(self.ew.planned_end_date, wish_end)
        self.assertEqual(self.ew.deadline, due)
        self.assertEqual(self.ew.provider_planned_date, committed)

    def test_the_plan_endpoint_REFUSES_the_customers_date_fields(self):
        """Not merely "does not write them" — the payload has no such
        field, so a caller cannot smuggle one in and have it silently
        ignored either. DRF drops unknown keys; this asserts the row is
        untouched, which is the property that matters."""
        wish = timezone.localdate() + timedelta(days=5)
        self.ew.preferred_date = wish
        self.ew.save(update_fields=["preferred_date"])

        response = self.plan(
            self.ew,
            {
                "preferred_date": (wish + timedelta(days=30)).isoformat(),
                "deadline": (wish + timedelta(days=30)).isoformat(),
                "budget_hours": "2.00",
                "start": False,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.ew.refresh_from_db()
        self.assertEqual(self.ew.preferred_date, wish)
        self.assertIsNone(self.ew.deadline)

    def test_a_committed_end_before_its_start_is_refused(self):
        start = timezone.localdate() + timedelta(days=5)
        response = self.plan(
            self.ew,
            {
                "provider_planned_date": start.isoformat(),
                "provider_planned_end_date": (
                    start - timedelta(days=1)
                ).isoformat(),
                "start": False,
            },
        )

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            response.data["code"], "provider_planned_end_before_start"
        )
        self.ew.refresh_from_db()
        self.assertIsNone(self.ew.provider_planned_date)
        self.assertIsNone(self.ew.provider_planned_end_date)

    def test_a_committed_end_with_no_committed_start_is_refused(self):
        response = self.plan(
            self.ew,
            {
                "provider_planned_end_date": (
                    timezone.localdate() + timedelta(days=5)
                ).isoformat(),
                "start": False,
            },
        )

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            response.data["code"], "provider_planned_end_without_start"
        )

    def test_an_empty_body_changes_nothing(self):
        response = self.plan(self.ew, {})

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data["code"], "nothing_to_plan")
        self.ew.refresh_from_db()
        self.assertEqual(self.ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)


# ---------------------------------------------------------------------------
# 2. The distribution
# ---------------------------------------------------------------------------
class PlannedHoursTests(PlanTestBase):
    def setUp(self):
        super().setUp()
        self.assign(self.ew, self.worker)
        self.assign(self.ew, self.worker_2)

    def test_hours_are_written_per_person_and_rendered_back(self):
        response = self.plan(
            self.ew,
            {
                "budget_hours": "10.00",
                "planned_hours": [
                    {"user": self.worker.id, "hours": "6.00"},
                    {"user": self.worker_2.id, "hours": "4.00"},
                ],
                "start": False,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(
            ExtraWorkPlannedHours.objects.filter(
                extra_work_request=self.ew
            ).count(),
            2,
        )
        rendered = {
            row["user_id"]: row for row in response.data["planned_hours"]
        }
        self.assertEqual(rendered[self.worker.id]["hours"], "6.00")
        self.assertTrue(rendered[self.worker.id]["is_assigned"])
        self.assertEqual(response.data["planned_hours_total"], "10.00")
        self.assertIsNone(response.data["planned_hours_overrun"])

    def test_ZERO_hours_for_a_person_is_a_real_line(self):
        """Somebody on the crew with nothing budgeted for them yet is a
        plan, not an absence. Dropping the line to say so would lose the
        fact that they are on the job."""
        response = self.plan(
            self.ew,
            {
                "planned_hours": [{"user": self.worker.id, "hours": "0.00"}],
                "start": False,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        row = ExtraWorkPlannedHours.objects.get(
            extra_work_request=self.ew, user=self.worker
        )
        self.assertEqual(row.hours, Decimal("0.00"))

    def test_the_submitted_list_IS_the_distribution(self):
        """Replace, not merge: an omitted person's line is removed, and
        an empty list clears the lot. Both are things an operator asked
        for by editing the modal."""
        self.plan(
            self.ew,
            {
                "planned_hours": [
                    {"user": self.worker.id, "hours": "6.00"},
                    {"user": self.worker_2.id, "hours": "4.00"},
                ],
                "start": False,
            },
        )

        self.plan(
            self.ew,
            {
                "planned_hours": [{"user": self.worker.id, "hours": "9.00"}],
                "start": False,
            },
        )
        rows = ExtraWorkPlannedHours.objects.filter(extra_work_request=self.ew)
        self.assertEqual([r.user_id for r in rows], [self.worker.id])
        self.assertEqual(rows[0].hours, Decimal("9.00"))

        response = self.plan(
            self.ew, {"planned_hours": [], "start": False}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(
            ExtraWorkPlannedHours.objects.filter(
                extra_work_request=self.ew
            ).count(),
            0,
        )
        self.assertEqual(response.data["planned_hours_total"], "0.00")

    def test_absent_planned_hours_leave_the_distribution_alone(self):
        self.plan(
            self.ew,
            {
                "planned_hours": [{"user": self.worker.id, "hours": "6.00"}],
                "start": False,
            },
        )
        self.plan(self.ew, {"budget_hours": "12.00", "start": False})

        self.assertEqual(
            ExtraWorkPlannedHours.objects.filter(
                extra_work_request=self.ew
            ).count(),
            1,
        )

    def test_a_person_who_is_not_on_this_job_is_refused(self):
        response = self.plan(
            self.ew,
            {
                "planned_hours": [
                    {"user": self.worker_2.id, "hours": "1.00"},
                ],
                "start": False,
            },
            actor=self.company_admin,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        ExtraWorkAssignment.objects.filter(
            extra_work_request=self.ew, user=self.worker_2
        ).delete()
        response = self.plan(
            self.ew,
            {
                "planned_hours": [
                    {"user": self.worker_2.id, "hours": "2.00"},
                ],
                "start": False,
            },
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data["code"], "planned_hours_invalid")

    def test_H1_an_unassigned_person_a_foreign_person_and_a_fiction_answer_the_same(
        self,
    ):
        """Compared for EQUALITY, not merely for both being errors: two
        400s with different wording still answer "does this id exist"
        and "does that person work there" (H-1, the Sprint 142.1 oracle
        class)."""
        bodies = []
        for user_id in (
            self.other_customer_user.id,  # exists, not assigned here
            self.foreign_worker.id,  # exists, another tenant's building
            98765432,  # does not exist at all
        ):
            response = self.plan(
                self.ew,
                {
                    "planned_hours": [{"user": user_id, "hours": "1.00"}],
                    "start": False,
                },
            )
            self.assertEqual(
                response.status_code, status.HTTP_400_BAD_REQUEST, response.data
            )
            bodies.append(response.data)

        self.assertEqual(bodies[0], bodies[1])
        self.assertEqual(bodies[1], bodies[2])

    def test_the_same_person_twice_is_refused(self):
        response = self.plan(
            self.ew,
            {
                "planned_hours": [
                    {"user": self.worker.id, "hours": "1.00"},
                    {"user": self.worker.id, "hours": "2.00"},
                ],
                "start": False,
            },
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            response.data["code"], "planned_hours_duplicate_user"
        )

    def test_HOURS_OF_AN_UNASSIGNED_PERSON_STAY_VISIBLE_AND_STAY_COUNTED(self):
        """The reference system's §4.4 defect, refused.

        Over there the grid is built from the assignment list and hours
        are matched onto it, so a removed worker's hours disappear from
        the screen while staying in every total — the screen and the
        total then disagree with nothing on screen to explain it. Here
        the line stays, stays counted, and says the person is off the
        job.
        """
        self.plan(
            self.ew,
            {
                "budget_hours": "10.00",
                "planned_hours": [
                    {"user": self.worker.id, "hours": "6.00"},
                    {"user": self.worker_2.id, "hours": "4.00"},
                ],
                "start": False,
            },
        )
        ExtraWorkAssignment.objects.filter(
            extra_work_request=self.ew, user=self.worker_2
        ).delete()

        self.authenticate(self.company_admin)
        response = self.client.get(detail_url(self.ew.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        rendered = {
            row["user_id"]: row for row in response.data["planned_hours"]
        }
        self.assertIn(self.worker_2.id, rendered)
        self.assertFalse(rendered[self.worker_2.id]["is_assigned"])
        self.assertTrue(rendered[self.worker.id]["is_assigned"])
        self.assertEqual(response.data["planned_hours_total"], "10.00")


# ---------------------------------------------------------------------------
# 3. Overrun warns. It never blocks.
# ---------------------------------------------------------------------------
class OverrunTests(PlanTestBase):
    def setUp(self):
        super().setUp()
        self.assign(self.ew, self.worker)

    def test_over_the_budget_the_save_still_succeeds_and_the_response_warns(self):
        response = self.plan(
            self.ew,
            {
                "budget_hours": "8.00",
                "planned_hours": [{"user": self.worker.id, "hours": "13.50"}],
                "start": False,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        warnings = response.data["plan"]["warnings"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["code"], "hours_overrun")
        self.assertEqual(warnings[0]["budget_hours"], "8.00")
        self.assertEqual(warnings[0]["distributed_hours"], "13.50")
        self.assertEqual(warnings[0]["over_by"], "5.50")

        # The whole point: it SAVED.
        self.ew.refresh_from_db()
        self.assertEqual(self.ew.budget_hours, Decimal("8.00"))
        self.assertEqual(
            ExtraWorkPlannedHours.objects.get(
                extra_work_request=self.ew, user=self.worker
            ).hours,
            Decimal("13.50"),
        )

    def test_the_overrun_is_on_the_READ_surface_too(self):
        """So the manager approving the work sees it on the screen they
        approve from, not only in the reply to somebody else's save."""
        self.plan(
            self.ew,
            {
                "budget_hours": "8.00",
                "planned_hours": [{"user": self.worker.id, "hours": "10.00"}],
                "start": False,
            },
        )

        self.authenticate(self.company_admin)
        response = self.client.get(detail_url(self.ew.id))

        overrun = response.data["planned_hours_overrun"]
        self.assertIsNotNone(overrun)
        self.assertEqual(overrun["over_by"], "2.00")

    def test_no_budget_means_no_warning(self):
        response = self.plan(
            self.ew,
            {
                "planned_hours": [{"user": self.worker.id, "hours": "40.00"}],
                "start": False,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["plan"]["warnings"], [])

    def test_exactly_on_budget_is_not_an_overrun(self):
        response = self.plan(
            self.ew,
            {
                "budget_hours": "8.00",
                "planned_hours": [{"user": self.worker.id, "hours": "8.00"}],
                "start": False,
            },
        )
        self.assertEqual(response.data["plan"]["warnings"], [])


# ---------------------------------------------------------------------------
# 4. Plan, then start — the start is an explicit ask (P-8R A2)
# ---------------------------------------------------------------------------
class PlanAndStartTests(PlanTestBase):
    def test_planning_with_start_true_starts_the_work(self):
        response = self.plan(self.ew, {"budget_hours": "3.00", "start": True})

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data["plan"]["started"])
        self.assertIsNone(response.data["plan"]["start_skipped"])
        self.ew.refresh_from_db()
        self.assertEqual(self.ew.status, ExtraWorkStatus.IN_PROGRESS)
        self.assertEqual(response.data["status"], ExtraWorkStatus.IN_PROGRESS)

    def test_start_false_plans_without_starting(self):
        response = self.plan(self.ew, {"budget_hours": "3.00", "start": False})

        self.assertFalse(response.data["plan"]["started"])
        self.assertEqual(
            response.data["plan"]["start_skipped"], "start_not_requested"
        )
        self.ew.refresh_from_db()
        self.assertEqual(self.ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)
        self.assertEqual(self.ew.budget_hours, Decimal("3.00"))

    def test_absent_start_plans_without_starting(self):
        """P-8R A2 — the inverted default. A caller that writes a plan
        field and says nothing about starting has planned, not started."""
        response = self.plan(self.ew, {"budget_hours": "3.00"})

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(response.data["plan"]["started"])
        self.assertEqual(
            response.data["plan"]["start_skipped"], "start_not_requested"
        )
        self.ew.refresh_from_db()
        self.assertEqual(self.ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)
        self.assertEqual(self.ew.budget_hours, Decimal("3.00"))

    def test_a_second_press_is_harmless(self):
        self.plan(self.ew, {"budget_hours": "3.00", "start": True})
        response = self.plan(self.ew, {"budget_hours": "4.00", "start": True})

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(response.data["plan"]["started"])
        self.assertEqual(
            response.data["plan"]["start_skipped"], "already_in_progress"
        )
        self.ew.refresh_from_db()
        self.assertEqual(self.ew.budget_hours, Decimal("4.00"))

    def test_THE_TICKET_IS_THE_AUTHORITY_and_the_plan_still_lands(self):
        """Sprint 181 §1. Once the work has an operational ticket, "has
        it started?" is answered by the ticket and by nothing else —
        forcing it here is how eight rows on crmtest came to read
        COMPLETED against a ticket that was still OPEN. The plan is
        written either way; the response says why it did not start."""
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Operational ticket",
            description="x",
            extra_work_request=self.ew,
        )

        response = self.plan(self.ew, {"budget_hours": "5.00", "start": True})

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(response.data["plan"]["started"])
        self.assertEqual(
            response.data["plan"]["start_skipped"],
            "operational_status_follows_ticket",
        )
        self.ew.refresh_from_db()
        self.assertEqual(self.ew.status, ExtraWorkStatus.CUSTOMER_APPROVED)
        self.assertEqual(self.ew.budget_hours, Decimal("5.00"))

    def test_work_the_customer_has_not_approved_yet_cannot_start(self):
        ew = self.make_ew(status=ExtraWorkStatus.REQUESTED)

        response = self.plan(ew, {"budget_hours": "5.00", "start": True})

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(response.data["plan"]["started"])
        self.assertEqual(
            response.data["plan"]["start_skipped"], "invalid_transition"
        )
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.REQUESTED)
        self.assertEqual(ew.budget_hours, Decimal("5.00"))

    def test_planning_a_day_moves_the_spawned_ticket_onto_it(self):
        """Sprint 184 §1, reused rather than re-implemented: the plan
        action routes its dates through `dates.apply_extra_work_dates`,
        so the ticket write that already existed there happens here for
        free and reports the same two lists."""
        ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Operational ticket",
            description="x",
            extra_work_request=self.ew,
        )
        day = timezone.localdate() + timedelta(days=4)

        response = self.plan(
            self.ew, {"provider_planned_date": day.isoformat()}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn(ticket.id, response.data["plan"]["tickets_moved"])
        ticket.refresh_from_db()
        self.assertEqual(timezone.localtime(ticket.scheduled_start_at).date(), day)


# ---------------------------------------------------------------------------
# 5. Who may plan, and who may see a plan
# ---------------------------------------------------------------------------
class PlanPermissionTests(PlanTestBase):
    def test_a_customer_cannot_plan(self):
        response = self.plan(self.ew, {"budget_hours": "1.00"}, actor=self.customer_user)

        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN, response.data
        )
        self.assertEqual(response.data["code"], "plan_provider_only")

    def test_staff_cannot_plan(self):
        response = self.plan(self.ew, {"budget_hours": "1.00"}, actor=self.worker)

        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN, response.data
        )
        self.assertEqual(response.data["code"], "plan_provider_only")

    def test_another_tenants_admin_gets_a_404_not_a_403(self):
        """H-1: the answer must not tell them the row exists."""
        response = self.plan(
            self.ew, {"budget_hours": "1.00"}, actor=self.other_company_admin
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_a_building_manager_outside_the_building_gets_a_404(self):
        response = self.plan(
            self.ew, {"budget_hours": "1.00"}, actor=self.other_manager
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_the_building_manager_of_this_building_can_plan(self):
        response = self.plan(
            self.ew, {"budget_hours": "2.00", "start": False}, actor=self.manager
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_A_CUSTOMER_NEVER_SEES_THE_BUDGET_OR_THE_DISTRIBUTION(self):
        # Created BY the customer user, so their default access role
        # (`customer.extra_work.view_own`) actually resolves the row —
        # otherwise this would pass on a 404 and prove nothing.
        ew = self.make_ew(created_by=self.customer_user)
        self.assign(ew, self.worker)
        self.plan(
            ew,
            {
                "budget_hours": "8.00",
                "planned_hours": [{"user": self.worker.id, "hours": "9.00"}],
                "file_upload_required": True,
                "start": False,
            },
        )

        self.authenticate(self.customer_user)
        response = self.client.get(detail_url(ew.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        for key in (
            "budget_hours",
            "planned_hours",
            "planned_hours_total",
            "planned_hours_overrun",
        ):
            with self.subTest(key=key):
                self.assertNotIn(key, response.data)
        # The worker's name is not in the payload by any other route.
        self.assertNotIn(self.worker.email, str(response.data))
        # The completion promise itself is not secret.
        self.assertTrue(response.data["file_upload_required"])

    def test_a_customer_never_sees_the_budget_on_the_LIST_either(self):
        ew = self.make_ew(created_by=self.customer_user)
        self.plan(ew, {"budget_hours": "8.00", "start": False})

        self.authenticate(self.customer_user)
        response = self.client.get("/api/extra-work/")

        rows = response.data.get("results", response.data)
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(row=row["id"]):
                self.assertNotIn("budget_hours", row)

    def test_can_plan_says_so_before_the_button_is_drawn(self):
        ew = self.make_ew(created_by=self.customer_user)

        self.authenticate(self.company_admin)
        provider_view = self.client.get(detail_url(ew.id))
        self.assertTrue(provider_view.data["actions"]["can_plan"])

        self.authenticate(self.customer_user)
        customer_view = self.client.get(detail_url(ew.id))
        self.assertEqual(customer_view.status_code, status.HTTP_200_OK)
        self.assertFalse(customer_view.data["actions"]["can_plan"])


# ---------------------------------------------------------------------------
# 6. The payload and the writer cannot drift apart
# ---------------------------------------------------------------------------
class OnePayloadOneWriterTests(APITestCase):
    """Two independently-maintained lists drift. This one cannot.

    `ExtraWorkPlanSerializer` says what a plan may CARRY;
    `planning.PLAN_FIELDS` says what `apply_plan` READS. A field added to
    the first and forgotten in the second would be accepted, validated,
    and silently dropped — which is a description of the exact bug this
    sprint exists to avoid, one layer up from where the reference system
    has it.

    Same lesson as Sprint 130's `PERMISSION_GROUPS`: the compiler cannot
    check two lists against each other, so a test does.
    """

    def test_every_field_the_payload_accepts_is_a_field_the_writer_reads(self):
        from extra_work.planning import PLAN_FIELDS
        from extra_work.serializers import ExtraWorkPlanSerializer

        # W-HOURS5 — `past_days_override_reason` is excluded like `start`
        # is: both are MODIFIERS of the save (start the work / record
        # why history was edited), read by `apply_plan` and stored by
        # neither the writer nor the row. It joined the serializer with
        # the past-day freeze and this list was not widened with it, so
        # the test has been red since — the two-list drift it exists
        # to catch, caught one wave late.
        declared = set(ExtraWorkPlanSerializer().fields) - {
            "start",
            "past_days_override_reason",
        }
        self.assertEqual(declared, set(PLAN_FIELDS))

    def test_the_bulk_payload_is_the_single_payload_plus_the_selection(self):
        """W4-O widened what "the selection" means, not what a plan is.

        The bulk body now has TWO spellings — `requests` (one plan for
        all of them) and `items` (a plan per work) — so the field set
        gained one name. The invariant this test exists for is
        untouched: every field the single plan action accepts is still a
        field the bulk body accepts, by construction rather than by two
        lists being kept in step.

        The second assertion is the one W4-O adds, and it is the same
        lesson one level down: a ROW is a plan payload with an id bolted
        on and NOTHING else. Re-declaring the plan fields inside the row
        serializer is all it would take for the per-work table to
        quietly stop carrying a field the single form offers — the
        payload would validate, the write would land, and the field
        would be gone.
        """
        from extra_work.serializers import ExtraWorkPlanSerializer
        from extra_work.views_planning import (
            _BulkPlanInputSerializer,
            _BulkPlanItemSerializer,
        )

        plan_fields = set(ExtraWorkPlanSerializer().fields)
        self.assertEqual(
            set(_BulkPlanInputSerializer().fields),
            plan_fields | {"requests", "items"},
        )
        self.assertEqual(
            set(_BulkPlanItemSerializer().fields),
            plan_fields | {"request"},
        )


# ---------------------------------------------------------------------------
# 7. The two completion requirements, and the trail
# ---------------------------------------------------------------------------
class CompletionFlagsAndTrailTests(PlanTestBase):
    def test_both_flags_default_off(self):
        self.assertFalse(self.ew.file_upload_required)
        self.assertFalse(self.ew.completion_notes_required)

    def test_the_single_plan_endpoint_is_JSON_only_for_the_same_reason(self):
        """See `test_w2d_bulk_plan.test_A_FORM_ENCODED_PLAN_CANNOT_WIPE_
        THE_FLAGS`. Pinned on both endpoints because a caller that finds
        one of them form-encodable will use it."""
        self.ew.file_upload_required = True
        self.ew.save(update_fields=["file_upload_required"])

        self.authenticate(self.company_admin)
        response = self.client.post(
            plan_url(self.ew.id),
            {"budget_hours": "5.00", "start": False},
            format="multipart",
        )

        self.assertEqual(
            response.status_code, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        )
        self.ew.refresh_from_db()
        self.assertTrue(self.ew.file_upload_required)

    def test_the_flags_are_stored_and_can_be_turned_back_off(self):
        self.plan(
            self.ew,
            {
                "file_upload_required": True,
                "completion_notes_required": True,
                "start": False,
            },
        )
        self.ew.refresh_from_db()
        self.assertTrue(self.ew.file_upload_required)
        self.assertTrue(self.ew.completion_notes_required)

        self.plan(self.ew, {"file_upload_required": False, "start": False})
        self.ew.refresh_from_db()
        self.assertFalse(self.ew.file_upload_required)
        # The one nobody mentioned is the one nobody changed.
        self.assertTrue(self.ew.completion_notes_required)

    def test_a_plan_writes_one_history_row_naming_what_changed(self):
        before = ExtraWorkStatusHistory.objects.filter(
            extra_work=self.ew
        ).count()

        self.plan(self.ew, {"budget_hours": "6.00", "start": False})

        rows = ExtraWorkStatusHistory.objects.filter(
            extra_work=self.ew
        ).order_by("id")
        self.assertEqual(rows.count(), before + 1)
        note = rows.last().note
        self.assertIn("Planned by", note)
        self.assertIn("6.00", note)
        self.assertFalse(rows.last().is_override)

    def test_BUDGET_HOURS_NEVER_REACHES_THE_MONEY(self):
        """`rowAmounts()` and its server-side mirror stay the only
        billing-total rule. An hours field that reached a price would be
        a second money rule, and two money rules disagree by cents on
        the same record — which is what the reference system does six
        different ways."""
        self.assign(self.ew, self.worker)
        self.authenticate(self.company_admin)
        before = self.client.get(detail_url(self.ew.id)).data
        money_keys = (
            "subtotal_amount",
            "vat_amount",
            "total_amount",
            "final_subtotal_amount",
            "final_vat_amount",
            "final_total_amount",
            "is_priced",
        )

        self.plan(
            self.ew,
            {
                "budget_hours": "40.00",
                "planned_hours": [{"user": self.worker.id, "hours": "40.00"}],
                "start": False,
            },
        )

        after = self.client.get(detail_url(self.ew.id)).data
        for key in money_keys:
            with self.subTest(key=key):
                self.assertEqual(before[key], after[key])
