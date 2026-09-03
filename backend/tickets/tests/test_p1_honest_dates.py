"""
P-1 — honest dates on REAL data.

FE-4's tests passed on fixtures whose planned dates were all real. On
crmtest, 43 of 54 extra-work tickets carried a `scheduled_start_at`
nobody had set: the Sprint 9B spawn seed copied the cart's
`requested_date` (which defaults to the day of entry) into the schedule
column, and the board read TCK-2026-000209 — created 3 June, never
planned — as "Planned 3 Jun, 87 days late".

Every fixture here builds the UGLY shape: a date in the column with no
schedule row behind it. The card (`GET /api/tickets/work-plan/`) and the
detail (`GET /api/tickets/<id>/`) must both read it as "created on ...,
not planned yet, N days now", never as a plan and never as late.
"""
from __future__ import annotations

import datetime

from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import BuildingStaffVisibility
from extra_work.models import (
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkStatus,
)
from extra_work.proposal_tickets import spawn_tickets_for_extra_work_request
from planned_work.models import (
    Frequency,
    PlannedOccurrence,
    PlannedOccurrenceStatus,
    RecurringJob,
    RecurringJobWindow,
)
from test_utils import TenantFixtureMixin
from tickets.models import (
    StaffAssignmentSlotStatus,
    Ticket,
    TicketScheduleStatus,
    TicketStaffAssignment,
    TicketStatus,
    TicketStatusHistory,
    TicketType,
)
from tickets.schedule import set_schedule
from tickets.work_plan import PLACEMENT_PLANNED, PLACEMENT_REVIEW

PLAN = "/api/tickets/work-plan/"


class _Fixture(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.worker = self.make_user("p1-worker@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.worker, building=self.building
        )
        self.company_admin.full_name = "Ramazan Admin"
        self.company_admin.save(update_fields=["full_name"])
        self.super_admin.full_name = "Sam Super"
        self.super_admin.save(update_fields=["full_name"])

    def _at(self, offset_days, hour=9):
        return timezone.make_aware(
            datetime.datetime.combine(
                self.today + datetime.timedelta(days=offset_days),
                datetime.time(hour, 0),
            )
        )

    def make_ticket(self, title, status=TicketStatus.OPEN, **extra):
        extra.setdefault("created_by", self.super_admin)
        return Ticket.objects.create(
            company=self.company,
            customer=self.customer,
            building=self.building,
            title=title,
            description="x",
            type=TicketType.REQUEST,
            status=status,
            **extra,
        )

    def make_phantom(self, title, *, created_days_ago, **extra):
        """THE UGLY SHAPE: `scheduled_start_at` == the creation day,
        `SCHEDULED`, and no schedule row anywhere — exactly what the
        Sprint 9B seed left on crmtest."""
        ticket = self.make_ticket(
            title,
            scheduled_start_at=self._at(-created_days_ago, 0),
            schedule_status=TicketScheduleStatus.SCHEDULED,
            **extra,
        )
        Ticket.objects.filter(pk=ticket.pk).update(
            created_at=self._at(-created_days_ago, 12)
        )
        ticket.refresh_from_db()
        return ticket

    def make_slot(
        self,
        ticket,
        *,
        days=None,
        slot_status=StaffAssignmentSlotStatus.ASSIGNED,
        completed_at=None,
    ):
        return TicketStaffAssignment.objects.create(
            ticket=ticket,
            user=self.worker,
            assigned_by=self.company_admin,
            scheduled_start_at=self._at(days) if days is not None else None,
            slot_status=slot_status,
            completed_at=completed_at,
        )

    def board(self, user=None, *, scope="company", week=None):
        self.client.force_authenticate(user or self.company_admin)
        params = {"scope": scope} if scope else {}
        if week:
            params["week"] = week
        response = self.client.get(PLAN, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def detail(self, ticket, user=None):
        self.client.force_authenticate(user or self.company_admin)
        response = self.client.get(f"/api/tickets/{ticket.id}/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    @staticmethod
    def find(payload, key):
        for bucket in (
            "entries",
            "undated_entries",
            "overdue_entries",
            "upcoming_entries",
            "late_entries",
        ):
            for entry in payload.get(bucket, []):
                if entry["key"] == key:
                    return entry, bucket
        return None, None

    def week_of(self, offset_days):
        iso = (self.today + datetime.timedelta(days=offset_days)).isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"


class PhantomPlanTests(_Fixture):
    """A date is a plan only if a person made it."""

    def test_a_seeded_date_is_created_not_planned_on_card_and_detail(self):
        ticket = self.make_phantom("ggtg", created_days_ago=87)
        self.make_slot(ticket, days=None)

        detail = self.detail(ticket)
        self.assertFalse(detail["has_real_plan"])
        self.assertIsNone(detail["plan_source"])
        self.assertIsNone(detail["planned_by_name"])
        self.assertIsNone(detail["planned_at"])
        # Never late against a plan that does not exist.
        self.assertIsNone(detail["due_date"])
        self.assertIsNone(detail["due_kind"])
        self.assertIsNone(detail["days_until_due"])
        self.assertEqual(detail["unplanned_age_days"], 87)
        # Nobody guesses who opened a ticket.
        self.assertEqual(detail["created_by_name"], "Sam Super")
        # The column itself is untouched: no migration, no rewrite.
        self.assertIsNotNone(detail["scheduled_start_at"])

        card, bucket = self.find(self.board(), f"ticket-{ticket.id}")
        self.assertIsNotNone(card)
        self.assertEqual(bucket, "undated_entries")
        self.assertFalse(card["has_real_plan"])
        self.assertIsNone(card["plan_source"])
        self.assertIsNone(card["planned_start"])
        self.assertIsNone(card["due_kind"])
        self.assertIsNone(card["days_until_due"])
        self.assertFalse(card["is_overdue"])
        self.assertEqual(card["unplanned_age_days"], 87)
        self.assertEqual(card["created_by_name"], "Sam Super")

    def test_a_phantom_never_reaches_the_late_or_overdue_lists(self):
        ticket = self.make_phantom("old and seeded", created_days_ago=60)
        self.make_slot(ticket, days=None)
        payload = self.board()
        keys = {e["key"] for e in payload["overdue_entries"]}
        keys |= {e["key"] for e in payload["late_entries"]}
        keys |= {e["key"] for e in payload["entries"]}
        self.assertNotIn(f"ticket-{ticket.id}", keys)
        self.assertEqual(payload["counts"]["undated"], 1)
        self.assertEqual(payload["counts"]["overdue_all"], 0)

    def test_a_person_planned_date_is_a_plan_with_a_name_on_both(self):
        ticket = self.make_ticket("Planned by Ramazan")
        set_schedule(
            ticket,
            actor=self.company_admin,
            scheduled_start_at=self._at(0),
        )
        self.make_slot(ticket, days=0)

        detail = self.detail(ticket)
        self.assertTrue(detail["has_real_plan"])
        self.assertEqual(detail["plan_source"], "TICKET")
        self.assertEqual(detail["planned_by_name"], "Ramazan Admin")
        self.assertIsNotNone(detail["planned_at"])
        self.assertEqual(detail["due_kind"], "PLANNED_DAY")
        self.assertEqual(detail["days_until_due"], 0)
        self.assertIsNone(detail["unplanned_age_days"])

        card, bucket = self.find(self.board(), f"ticket-{ticket.id}")
        self.assertEqual(bucket, "entries")
        self.assertTrue(card["has_real_plan"])
        self.assertEqual(card["planned_by_name"], "Ramazan Admin")
        self.assertEqual(card["days_until_due"], detail["days_until_due"])

    def test_a_customer_user_sees_the_plan_but_not_the_planner(self):
        ticket = self.make_ticket("Planned", created_by=self.customer_user)
        set_schedule(
            ticket, actor=self.company_admin, scheduled_start_at=self._at(2)
        )
        detail = self.detail(ticket, user=self.customer_user)
        self.assertTrue(detail["has_real_plan"])
        self.assertIsNone(detail["planned_by_name"])
        self.assertIsNotNone(detail["planned_at"])

    def test_the_wish_behind_a_phantom_is_still_a_wish(self):
        """P-15 §0.4 — the wish stays a WISH all the way down: it never
        places the board (the row lives in the Not-planned strip) and it
        is stated as its own fact, `wished_day`, on card and detail
        alike. Rewritten from the P-1 captioned-phantom pin, which
        asserted `planned_start` == the wish."""
        wished = self.today + datetime.timedelta(days=4)
        extra_work = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Windows",
            description="",
            status=ExtraWorkStatus.IN_PROGRESS,
            preferred_date=wished,
        )
        ticket = self.make_phantom(
            "Execution", created_days_ago=3, extra_work_request=extra_work
        )
        self.make_slot(ticket, days=None)
        detail = self.detail(ticket)
        self.assertFalse(detail["has_real_plan"])
        self.assertEqual(detail["plan_source"], "CUSTOMER_WISH")
        self.assertEqual(detail["wished_day"], wished.isoformat())
        card, bucket = self.find(self.board(), f"ticket-{ticket.id}")
        self.assertEqual(bucket, "undated_entries")
        self.assertEqual(card["plan_source"], "CUSTOMER_WISH")
        self.assertFalse(card["has_real_plan"])
        self.assertIsNone(card["planned_start"])
        self.assertEqual(card["wished_day"], wished.isoformat())

    def test_the_providers_commitment_is_a_plan_with_a_name(self):
        extra_work = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Carpets",
            description="",
            status=ExtraWorkStatus.IN_PROGRESS,
        )
        from extra_work.models import ExtraWorkStatusHistory

        extra_work.provider_planned_date = self.today + datetime.timedelta(days=5)
        extra_work.save(update_fields=["provider_planned_date"])
        ExtraWorkStatusHistory.objects.create(
            extra_work=extra_work,
            old_status=extra_work.status,
            new_status=extra_work.status,
            changed_by=self.company_admin,
            note="Planned by admin-a@example.com: committed window "
            f"{extra_work.provider_planned_date} -> -.",
        )
        ticket = self.make_ticket("Execution", extra_work_request=extra_work)
        self.make_slot(ticket, days=None)
        detail = self.detail(ticket)
        self.assertTrue(detail["has_real_plan"])
        self.assertEqual(detail["plan_source"], "PROVIDER_PLAN")
        self.assertEqual(detail["planned_by_name"], "Ramazan Admin")
        card, _bucket = self.find(self.board(), f"ticket-{ticket.id}")
        self.assertTrue(card["has_real_plan"])
        self.assertEqual(card["planned_by_name"], "Ramazan Admin")

    def test_a_recurring_occurrence_is_a_real_plan(self):
        job = RecurringJob.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            title="VERIFY simple",
            frequency=Frequency.WEEKLY,
            start_date=self.today - datetime.timedelta(days=30),
            created_by=self.company_admin,
        )
        window = RecurringJobWindow.objects.create(
            recurring_job=job, label="", start_time=None, ordering=0
        )
        occurrence = PlannedOccurrence.objects.create(
            recurring_job=job,
            company=self.company,
            building=self.building,
            customer=self.customer,
            planned_date=self.today,
            status=PlannedOccurrenceStatus.TICKET_CREATED,
            source_window=window,
        )
        ticket = self.make_ticket(
            "VERIFY simple",
            planned_occurrence=occurrence,
            scheduled_start_at=self._at(0, 6),
            schedule_status=TicketScheduleStatus.SCHEDULED,
        )
        self.make_slot(ticket, days=0)
        detail = self.detail(ticket)
        self.assertTrue(detail["has_real_plan"])
        self.assertEqual(detail["plan_source"], "TICKET")
        self.assertEqual(detail["planned_by_name"], "Ramazan Admin")
        self.assertEqual(detail["days_until_due"], 0)
        card, bucket = self.find(self.board(), f"ticket-{ticket.id}")
        self.assertEqual(bucket, "entries")
        self.assertTrue(card["has_real_plan"])


class SpawnBornUnplannedTests(_Fixture):
    """The live seed path is stopped: a spawned ticket has no plan."""

    def test_a_spawned_ticket_carries_no_schedule(self):
        extra_work = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Cart",
            description="",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
        )
        ExtraWorkRequestItem.objects.create(
            extra_work_request=extra_work,
            requested_date=self.today,
            quantity=1,
            custom_description="Something",
        )
        tickets = spawn_tickets_for_extra_work_request(
            extra_work, actor=self.company_admin
        )
        self.assertEqual(len(tickets), 1)
        ticket = tickets[0]
        self.assertIsNone(ticket.scheduled_start_at)
        self.assertEqual(ticket.schedule_status, TicketScheduleStatus.UNSCHEDULED)
        detail = self.detail(ticket)
        self.assertFalse(detail["has_real_plan"])
        self.assertEqual(detail["unplanned_age_days"], 0)


class ReviewCarryTests(_Fixture):
    """Work waiting for a manager does not rot in the past."""

    def _reviewed(self, *, planned_days_ago, waiting_days):
        ticket = self.make_ticket("Done, unconfirmed")
        set_schedule(
            ticket,
            actor=self.company_admin,
            scheduled_start_at=self._at(-planned_days_ago),
        )
        self.make_slot(
            ticket,
            days=-planned_days_ago,
            slot_status=StaffAssignmentSlotStatus.COMPLETED,
            completed_at=self._at(-planned_days_ago, 15),
        )
        ticket.status = TicketStatus.WAITING_MANAGER_REVIEW
        ticket.manager_review_at = self._at(-waiting_days, 15)
        ticket.save(update_fields=["status", "manager_review_at", "updated_at"])
        # P-14 — the strip's `waiting_days` reads the HISTORY leg into
        # the review state (P-8R E), which a bare `.save()` never
        # writes; `created_at` is auto_now_add, so backdate with
        # update() (the `test_p10_review_placement` fixture's recipe).
        TicketStatusHistory.objects.create(
            ticket=ticket,
            old_status=TicketStatus.IN_PROGRESS,
            new_status=TicketStatus.WAITING_MANAGER_REVIEW,
            changed_by=self.worker,
        )
        TicketStatusHistory.objects.filter(
            ticket=ticket, new_status=TicketStatus.WAITING_MANAGER_REVIEW
        ).update(created_at=self._at(-waiting_days, 15))
        return ticket

    def test_a_manager_sees_it_on_today_with_its_waiting_age(self):
        # P-14 repaired a stale pin: P-10 A2 made review placement
        # PERSONAL after this test was written (red from P-10 to P-14,
        # found by the P-14 sweep). A company admin who is not the
        # job's named manager reads the review STRIP with the waiting
        # age; the named manager's today-card is pinned in
        # `test_p10_review_placement`.
        ticket = self._reviewed(planned_days_ago=10, waiting_days=5)
        payload = self.board()
        self.assertEqual(payload["counts"]["review"], 1)
        self.assertEqual(payload["counts"]["total"], 0)
        rows = [
            e
            for e in payload.get("review_entries", [])
            if e["key"] == f"ticket-{ticket.id}"
        ]
        self.assertEqual(len(rows), 1, payload.get("review_entries"))
        self.assertEqual(rows[0]["waiting_days"], 5)

    def test_it_hangs_on_the_day_it_was_reported_done_not_its_planned_day(self):
        # P-9 §A.2b (rule 10), amended by P-10 A1 (the stale pin was
        # red from P-10 to P-14): while the check is PENDING the past
        # shows nothing — reported done is not finished. Once approved,
        # the card settles on the day it was REPORTED done (day -12),
        # not the day it was planned (day -20).
        ticket = self._reviewed(planned_days_ago=20, waiting_days=12)
        planned_week = self.board(week=self.week_of(-20))
        self.assertIsNone(self.find(planned_week, f"ticket-{ticket.id}")[0])
        report_week = self.board(week=self.week_of(-12))
        self.assertIsNone(self.find(report_week, f"ticket-{ticket.id}")[0])
        ticket.status = TicketStatus.APPROVED
        ticket.approved_at = timezone.now()
        ticket.save(update_fields=["status", "approved_at", "updated_at"])
        payload = self.board(week=self.week_of(-12))
        card, bucket = self.find(payload, f"ticket-{ticket.id}")
        self.assertEqual(bucket, "entries")
        self.assertEqual(card["placement"], PLACEMENT_PLANNED)
        self.assertEqual(card["day"], (self.today - datetime.timedelta(days=12)).isoformat())
        self.assertTrue(card["viewer_settled"])
        self.assertIsNone(card["stuck_age_days"])

    def test_the_workers_completed_slot_stays_on_its_own_day(self):
        # P-10 A2 (repaired stale pin, red P-10 → P-14): for the worker
        # a reported-done job is the review STRIP, never a column — not
        # their day any more, not finished either. It returns to a
        # column (the report day's) only once the check is over.
        ticket = self._reviewed(planned_days_ago=10, waiting_days=5)
        this_week = self.board(user=self.worker, scope=None)
        self.assertEqual(
            [e for e in this_week["entries"] if e["ticket_id"] == ticket.id], []
        )
        home = self.board(user=self.worker, scope=None, week=self.week_of(-10))
        self.assertEqual(
            [e for e in home["entries"] if e["ticket_id"] == ticket.id], []
        )
        strip = [
            e
            for e in this_week.get("review_entries", [])
            if e["ticket_id"] == ticket.id
        ]
        self.assertEqual(len(strip), 1, this_week.get("review_entries"))

    def test_confirming_takes_it_off_today(self):
        ticket = self._reviewed(planned_days_ago=10, waiting_days=5)
        ticket.status = TicketStatus.WAITING_CUSTOMER_APPROVAL
        ticket.save(update_fields=["status", "updated_at"])
        card, _bucket = self.find(self.board(), f"ticket-{ticket.id}")
        self.assertIsNone(card)
