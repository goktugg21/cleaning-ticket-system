"""
Sprint 179A — the Work Plan endpoint and the §12B week-placement rule.

Three things are pinned here, and they are different kinds of claim:

1. **The rule itself**, as pure functions over dates. No database, no
   request — `WeekPlacementRuleTests`. The product docs recorded the
   rule as DECIDED for five sprints; this is the executable form of it.
2. **The endpoint**, including the exact key set of both entry shapes.
   Sprint 173 took the whole Extra Work page down with a missing
   `fields` entry that a filter test could never have caught, so every
   field this exposes is asserted on a rendered response.
3. **The privacy and tenancy floor.** Extra work is the sensitive half:
   `scope_extra_work_for` returns `.none()` for STAFF on purpose, so
   the caller-scoped read this endpoint adds is pinned from both sides —
   a worker sees the job they were put on, and nothing commercial about
   it, and nothing at all about another tenant's (H-1).

The parity class at the end exists because the rule is expressed twice:
as Python in `work_plan.py` and as querysets in `views_work_plan.py`
(the counts have to be answered without loading the scope). Two
expressions of one rule is exactly the drift §12A warns about, so the
test asserts they agree over a fixture built to hit every branch.
"""
from __future__ import annotations

import datetime

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import BuildingStaffVisibility
from extra_work.models import (
    ExtraWorkAssignment,
    ExtraWorkAssignmentRole,
    ExtraWorkRequest,
    ExtraWorkStatus,
)
from tickets.models import (
    StaffAssignmentSlotStatus,
    Ticket,
    TicketStaffAssignment,
    TicketStatus,
    TicketType,
)
from tickets.views_work_plan import (
    KIND_EXTRA_WORK,
    KIND_TICKET_SLOT,
)
from tickets.work_plan import (
    PLACEMENT_OVERDUE,
    PLACEMENT_PLANNED,
    PLACEMENT_STARTED,
    PLACEMENT_STARTED_EARLY,
    STATE_BLOCKED,
    STATE_DONE,
    STATE_IN_PROGRESS,
    STATE_OPEN,
    Job,
    day_for,
    is_overdue,
    is_upcoming,
    iso_week_bounds,
    overdue_days,
    placement_for,
)
from test_utils import TenantFixtureMixin


URL = "/api/tickets/work-plan/"


# ---------------------------------------------------------------------
# 1. The rule, on its own
# ---------------------------------------------------------------------


class WeekPlacementRuleTests(APITestCase):
    """§12B points 1-4, each as its own assertion.

    A Monday-to-Sunday current week, a week before it and a week after
    it, so "the current week" and "some other week" are both real
    positions rather than an implicit today.
    """

    def setUp(self):
        # 2026-W33 is Mon 10 Aug - Sun 16 Aug 2026.
        self.week_start, self.week_end = iso_week_bounds(2026, 33)
        self.today = datetime.date(2026, 8, 13)  # a Thursday inside it
        self.next_start, self.next_end = iso_week_bounds(2026, 34)
        self.prev_start, self.prev_end = iso_week_bounds(2026, 32)

    def place(self, job, start=None, end=None):
        return placement_for(
            job,
            start or self.week_start,
            end or self.week_end,
            self.today,
        )

    # -- point 1: planned placement -----------------------------------

    def test_a_job_appears_in_the_week_its_window_covers(self):
        job = Job(
            planned_start=datetime.date(2026, 8, 12),
            planned_end=None,
            due=None,
            state=STATE_OPEN,
        )
        self.assertEqual(self.place(job), PLACEMENT_PLANNED)

    def test_a_window_spanning_two_weeks_appears_in_both(self):
        """Friday to Tuesday is in this week AND the next, on the first
        of its own days that falls inside each."""
        job = Job(
            planned_start=datetime.date(2026, 8, 14),  # Friday
            planned_end=datetime.date(2026, 8, 18),  # next Tuesday
            due=None,
            state=STATE_OPEN,
        )
        self.assertEqual(self.place(job), PLACEMENT_PLANNED)
        self.assertEqual(
            self.place(job, self.next_start, self.next_end), PLACEMENT_PLANNED
        )
        self.assertEqual(
            day_for(
                job, PLACEMENT_PLANNED, self.week_start, self.week_end, self.today
            ),
            datetime.date(2026, 8, 14),
        )
        self.assertEqual(
            day_for(
                job, PLACEMENT_PLANNED, self.next_start, self.next_end, self.today
            ),
            self.next_start,
        )

    def test_planned_placement_holds_whatever_the_status(self):
        """"That is its home and it stays there whatever its status" —
        a finished job still shows in the week it was planned for."""
        for state in (STATE_OPEN, STATE_IN_PROGRESS, STATE_DONE, STATE_BLOCKED):
            with self.subTest(state=state):
                job = Job(
                    planned_start=datetime.date(2026, 8, 12),
                    planned_end=None,
                    due=None,
                    state=state,
                )
                self.assertEqual(self.place(job), PLACEMENT_PLANNED)

    # -- point 2: active placement ------------------------------------

    def test_a_started_job_planned_for_september_shows_today_as_early(self):
        """The father's own example, and the reason the rule exists."""
        job = Job(
            planned_start=datetime.date(2026, 9, 2),
            planned_end=None,
            due=None,
            state=STATE_IN_PROGRESS,
        )
        self.assertEqual(self.place(job), PLACEMENT_STARTED_EARLY)
        # And it is STILL in September — that is the half his father
        # objected to losing.
        sep_start, sep_end = iso_week_bounds(2026, 36)
        self.assertEqual(self.place(job, sep_start, sep_end), PLACEMENT_PLANNED)

    def test_a_started_job_from_a_past_week_is_carried_into_now(self):
        job = Job(
            planned_start=datetime.date(2026, 8, 4),
            planned_end=None,
            due=None,
            state=STATE_IN_PROGRESS,
        )
        self.assertEqual(self.place(job), PLACEMENT_STARTED)
        self.assertEqual(
            self.place(job, self.prev_start, self.prev_end), PLACEMENT_PLANNED
        )

    def test_a_started_job_with_no_plan_at_all_still_shows_today(self):
        job = Job(
            planned_start=None, planned_end=None, due=None, state=STATE_IN_PROGRESS
        )
        self.assertEqual(self.place(job), PLACEMENT_STARTED)
        self.assertEqual(
            day_for(
                job, PLACEMENT_STARTED, self.week_start, self.week_end, self.today
            ),
            self.today,
        )

    def test_a_finished_job_is_not_dragged_into_the_current_week(self):
        job = Job(
            planned_start=datetime.date(2026, 8, 4),
            planned_end=None,
            due=None,
            state=STATE_DONE,
        )
        self.assertIsNone(self.place(job))

    # -- point 3: overdue placement -----------------------------------

    def test_a_job_past_its_deadline_and_unfinished_shows_today(self):
        job = Job(
            planned_start=None,
            planned_end=None,
            due=datetime.date(2026, 8, 3),
            state=STATE_OPEN,
        )
        self.assertEqual(self.place(job), PLACEMENT_OVERDUE)
        self.assertTrue(is_overdue(job, self.today))
        self.assertEqual(overdue_days(job, self.today), 10)

    def test_overdue_beats_started(self):
        """A job that is both is more usefully described as late."""
        job = Job(
            planned_start=datetime.date(2026, 9, 2),
            planned_end=None,
            due=datetime.date(2026, 8, 3),
            state=STATE_IN_PROGRESS,
        )
        self.assertEqual(self.place(job), PLACEMENT_OVERDUE)

    def test_a_finished_job_is_never_late(self):
        for state in (STATE_DONE, STATE_BLOCKED):
            with self.subTest(state=state):
                job = Job(
                    planned_start=None,
                    planned_end=None,
                    due=datetime.date(2026, 8, 3),
                    state=state,
                )
                self.assertFalse(is_overdue(job, self.today))
                self.assertIsNone(self.place(job))

    def test_no_due_date_is_never_late(self):
        job = Job(
            planned_start=None, planned_end=None, due=None, state=STATE_OPEN
        )
        self.assertFalse(is_overdue(job, self.today))
        self.assertIsNone(overdue_days(job, self.today))

    # -- point 4: untouched future work does not clutter today --------

    def test_untouched_future_work_stays_in_its_own_week(self):
        job = Job(
            planned_start=datetime.date(2026, 9, 2),
            planned_end=None,
            due=None,
            state=STATE_OPEN,
        )
        self.assertIsNone(self.place(job))
        self.assertTrue(is_upcoming(job, self.week_end, self.today))
        sep_start, sep_end = iso_week_bounds(2026, 36)
        self.assertEqual(self.place(job, sep_start, sep_end), PLACEMENT_PLANNED)

    def test_started_or_late_work_is_not_also_listed_as_upcoming(self):
        """It is already on the week; counting it twice would make the
        number the operator is meant to trust wrong."""
        started = Job(
            planned_start=datetime.date(2026, 9, 2),
            planned_end=None,
            due=None,
            state=STATE_IN_PROGRESS,
        )
        self.assertFalse(is_upcoming(started, self.week_end, self.today))

    def test_rules_two_and_three_do_not_reach_other_weeks(self):
        """Looking at next week shows planned placement and nothing
        else — today does not clutter September either."""
        started = Job(
            planned_start=None, planned_end=None, due=None, state=STATE_IN_PROGRESS
        )
        late = Job(
            planned_start=None,
            planned_end=None,
            due=datetime.date(2026, 8, 3),
            state=STATE_OPEN,
        )
        for job in (started, late):
            with self.subTest(job=job):
                self.assertIsNone(
                    self.place(job, self.next_start, self.next_end)
                )

    def test_iso_week_bounds_is_monday_to_sunday(self):
        start, end = iso_week_bounds(2026, 33)
        self.assertEqual(start, datetime.date(2026, 8, 10))
        self.assertEqual(end, datetime.date(2026, 8, 16))
        self.assertEqual(start.isoweekday(), 1)
        self.assertEqual(end.isoweekday(), 7)


# ---------------------------------------------------------------------
# Shared endpoint fixture
# ---------------------------------------------------------------------


class WorkPlanFixture(TenantFixtureMixin):
    """One worker in company A, one in company B, and jobs of every
    shape the rule branches on."""

    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.worker = self.make_user("worker-179a@example.com", UserRole.STAFF)
        self.foreign_worker = self.make_user(
            "worker-179b@example.com", UserRole.STAFF
        )
        BuildingStaffVisibility.objects.create(
            user=self.worker, building=self.building
        )
        BuildingStaffVisibility.objects.create(
            user=self.foreign_worker, building=self.other_building
        )

    # -- builders -----------------------------------------------------

    def make_ticket(self, title, statusValue=TicketStatus.OPEN, *, foreign=False):
        return Ticket.objects.create(
            company=self.other_company if foreign else self.company,
            customer=self.other_customer if foreign else self.customer,
            building=self.other_building if foreign else self.building,
            title=title,
            description="x",
            type=TicketType.REQUEST,
            status=statusValue,
            created_by=self.super_admin,
        )

    def make_slot(
        self,
        ticket,
        *,
        user=None,
        start=None,
        end=None,
        slot_status=StaffAssignmentSlotStatus.ASSIGNED,
    ):
        def at(day, hour):
            if day is None:
                return None
            return timezone.make_aware(
                datetime.datetime.combine(day, datetime.time(hour, 0))
            )

        return TicketStaffAssignment.objects.create(
            ticket=ticket,
            user=user or self.worker,
            assigned_by=self.super_admin,
            scheduled_start_at=at(start, 9),
            scheduled_end_at=at(end, 17),
            slot_status=slot_status,
            time_window_label="Morning" if start else "",
        )

    def make_extra_work(
        self,
        title,
        *,
        preferred=None,
        planned_end=None,
        deadline=None,
        ew_status=ExtraWorkStatus.CUSTOMER_APPROVED,
        assignee=None,
        role=ExtraWorkAssignmentRole.WORKER,
        foreign=False,
    ):
        request = ExtraWorkRequest.objects.create(
            company=self.other_company if foreign else self.company,
            building=self.other_building if foreign else self.building,
            customer=self.other_customer if foreign else self.customer,
            created_by=self.super_admin,
            title=title,
            description="x",
            preferred_date=preferred,
            planned_end_date=planned_end,
            deadline=deadline,
            status=ew_status,
        )
        if assignee is not None:
            ExtraWorkAssignment.objects.create(
                extra_work_request=request,
                user=assignee,
                role=role,
                assigned_by=self.super_admin,
            )
        return request

    # -- helpers ------------------------------------------------------

    def get_plan(self, user, **params):
        self.client.force_authenticate(user)
        response = self.client.get(URL, params)
        self.assertEqual(
            response.status_code, status.HTTP_200_OK, response.data
        )
        return response.data

    @staticmethod
    def keys_of(payload, kind):
        return {e["key"] for e in payload["entries"] if e["kind"] == kind}

    @staticmethod
    def entry(payload, key, bucket="entries"):
        for candidate in payload[bucket]:
            if candidate["key"] == key:
                return candidate
        return None


# ---------------------------------------------------------------------
# 2. The endpoint's shape — every field, on a rendered response
# ---------------------------------------------------------------------


#: The whole entry contract. Both kinds answer with the SAME key set —
#: one shape whatever the source — so the page needs no per-kind
#: narrowing and a field cannot exist on one and be forgotten on the
#: other.
ENTRY_KEYS = {
    "kind",
    "key",
    "source_id",
    "ticket_id",
    "ticket_no",
    "extra_work_id",
    "title",
    "status",
    "state",
    "ticket_status",
    "ticket_type",
    "urgency",
    "customer_name",
    "building_id",
    "building_name",
    "planned_start",
    "planned_end",
    "due_date",
    "scheduled_start_at",
    "scheduled_end_at",
    "time_window_label",
    "assignment_note",
    "completion_note",
    "unable_to_complete_reason",
    "day",
    "placement",
    "is_overdue",
    "overdue_days",
    "assignee_names",
    "assignee_count",
    "can_complete",
}

#: Commercial and internal extra-work fields that must never reach this
#: surface. Named individually rather than checked as "not in ENTRY_KEYS"
#: because the point is the NAMES: these are the exact fields the
#: post-2026-05-20 privacy fix found leaking to STAFF.
FORBIDDEN_KEYS = {
    "description",
    "internal_cost_note",
    "manager_note",
    "override_reason",
    "routing_decision",
    "pricing_items",
    "proposals",
    "total_amount",
    "final_amount",
}


class WorkPlanResponseShapeTests(WorkPlanFixture, APITestCase):
    def setUp(self):
        super().setUp()
        self.ticket = self.make_ticket("Lobby floor")
        self.slot = self.make_slot(self.ticket, start=self.today)
        self.extra_work = self.make_extra_work(
            "Window frames",
            preferred=self.today,
            assignee=self.worker,
        )

    def test_the_envelope_carries_the_week_the_counts_and_the_bounds(self):
        payload = self.get_plan(self.worker)
        self.assertEqual(
            set(payload),
            {
                "week",
                "today",
                "scope",
                "counts",
                "entries",
                "overdue_entries",
                "upcoming_entries",
                # Sprint 181 §8 — the undated work, as ROWS. The page
                # could previously only say how much of it existed
                # (`counts.undated`), which is how two thirds of the
                # work on crmtest came to live in one muted sentence.
                "undated_entries",
                "limits",
                "truncated",
            },
        )
        self.assertEqual(
            set(payload["week"]),
            {"iso_year", "iso_week", "label", "start", "end", "is_current"},
        )
        self.assertTrue(payload["week"]["is_current"])
        self.assertEqual(
            set(payload["counts"]),
            {
                "total",
                "overdue",
                "open",
                "in_progress",
                "done",
                "blocked",
                "overdue_all",
                "upcoming",
                "undated",
            },
        )
        # Every list is bounded, and the response says by how much and
        # whether it hit the bound — a list that silently stops is the
        # same defect as a count that describes one page.
        # Sprint 181 §8 — the undated lane is bounded and says so on the
        # same terms as its two siblings.
        self.assertEqual(
            set(payload["limits"]),
            {
                "entries",
                "overdue_entries",
                "upcoming_entries",
                "undated_entries",
            },
        )
        self.assertEqual(
            set(payload["truncated"]),
            {
                "entries",
                "overdue_entries",
                "upcoming_entries",
                "undated_entries",
            },
        )
        self.assertFalse(any(payload["truncated"].values()))

    def test_a_ticket_slot_entry_carries_exactly_these_fields(self):
        payload = self.get_plan(self.worker)
        entry = self.entry(payload, f"slot-{self.slot.id}")
        self.assertIsNotNone(entry)
        self.assertEqual(set(entry), ENTRY_KEYS)
        self.assertEqual(entry["kind"], KIND_TICKET_SLOT)
        self.assertEqual(entry["ticket_id"], self.ticket.id)
        self.assertEqual(entry["ticket_no"], self.ticket.ticket_no)
        self.assertEqual(entry["title"], "Lobby floor")
        self.assertEqual(entry["building_name"], self.building.name)
        self.assertEqual(entry["customer_name"], self.customer.name)
        self.assertEqual(entry["ticket_type"], TicketType.REQUEST)
        self.assertEqual(entry["placement"], PLACEMENT_PLANNED)
        self.assertEqual(entry["day"], self.today.isoformat())
        self.assertIsNotNone(entry["scheduled_start_at"])
        self.assertEqual(entry["time_window_label"], "Morning")
        self.assertTrue(entry["can_complete"])

    def test_an_extra_work_entry_carries_exactly_the_same_fields(self):
        payload = self.get_plan(self.worker)
        entry = self.entry(payload, f"ew-{self.extra_work.id}")
        self.assertIsNotNone(entry)
        self.assertEqual(set(entry), ENTRY_KEYS)
        self.assertEqual(entry["kind"], KIND_EXTRA_WORK)
        self.assertEqual(entry["extra_work_id"], self.extra_work.id)
        self.assertIsNone(entry["ticket_id"])
        self.assertEqual(entry["title"], "Window frames")
        self.assertEqual(entry["status"], ExtraWorkStatus.CUSTOMER_APPROVED)
        self.assertEqual(entry["state"], STATE_OPEN)
        self.assertEqual(entry["urgency"], "NORMAL")
        self.assertEqual(entry["planned_start"], self.today.isoformat())
        # Extra work has no dated slot, and says so with nulls rather
        # than by omitting the keys.
        self.assertIsNone(entry["scheduled_start_at"])
        self.assertFalse(entry["can_complete"])

    def test_no_commercial_extra_work_field_reaches_a_worker(self):
        payload = self.get_plan(self.worker)
        for entry in payload["entries"]:
            with self.subTest(key=entry["key"]):
                self.assertEqual(set(entry) & FORBIDDEN_KEYS, set())

    def test_a_customer_user_is_refused_at_the_door(self):
        self.client.force_authenticate(self.customer_user)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_a_bad_week_is_a_400_not_a_silent_week_one(self):
        self.client.force_authenticate(self.worker)
        # 2025 has 52 ISO weeks, so W53 of it is a real input mistake —
        # 2026 genuinely HAS a week 53 and must not be rejected.
        for raw in ("bogus", "2026-33", "2026-W99", "2025-W53"):
            with self.subTest(raw=raw):
                response = self.client.get(URL, {"week": raw})
                self.assertEqual(
                    response.status_code, status.HTTP_400_BAD_REQUEST
                )

    def test_the_week_param_selects_that_week(self):
        payload = self.get_plan(self.worker, week="2026-W33")
        self.assertEqual(payload["week"]["iso_year"], 2026)
        self.assertEqual(payload["week"]["iso_week"], 33)
        self.assertEqual(payload["week"]["start"], "2026-08-10")
        self.assertEqual(payload["week"]["end"], "2026-08-16")


# ---------------------------------------------------------------------
# 3. Placement, end to end — including the owner's acceptance test
# ---------------------------------------------------------------------


class WorkPlanPlacementTests(WorkPlanFixture, APITestCase):
    def test_an_overdue_extra_work_shows_as_overdue_in_the_workers_week(self):
        """THE acceptance test.

        An extra work assigned to a worker, past its deadline, appears
        as overdue in that worker's Work Plan — with a reason on the
        card and its planned date, because a card that turns up outside
        its planned week without explaining itself is worse than one
        that does not turn up at all.
        """
        late = self.make_extra_work(
            "Gutter clearing",
            preferred=self.today - datetime.timedelta(days=14),
            deadline=self.today - datetime.timedelta(days=3),
            assignee=self.worker,
        )
        payload = self.get_plan(self.worker)
        entry = self.entry(payload, f"ew-{late.id}")
        self.assertIsNotNone(entry, payload["entries"])
        self.assertTrue(entry["is_overdue"])
        self.assertEqual(entry["placement"], PLACEMENT_OVERDUE)
        self.assertEqual(entry["overdue_days"], 3)
        self.assertEqual(entry["day"], self.today.isoformat())
        # The planned date travels with the card so the reason is
        # readable without opening anything.
        self.assertEqual(
            entry["planned_start"],
            (self.today - datetime.timedelta(days=14)).isoformat(),
        )
        self.assertEqual(
            entry["due_date"],
            (self.today - datetime.timedelta(days=3)).isoformat(),
        )
        self.assertEqual(payload["counts"]["overdue"], 1)
        self.assertEqual(payload["counts"]["overdue_all"], 1)
        # And it is in the Overdue list behind the button, too.
        self.assertIsNotNone(
            self.entry(payload, f"ew-{late.id}", "overdue_entries")
        )

    def test_the_acceptance_test_holds_through_the_real_assign_endpoint(self):
        """The same claim, but the assignment is written the way an
        operator writes it — through `POST /api/extra-work/bulk-assign/`
        — so the eligibility gate and this read are proven to line up."""
        late = self.make_extra_work(
            "Roof inspection",
            preferred=self.today - datetime.timedelta(days=10),
            deadline=self.today - datetime.timedelta(days=1),
        )
        self.client.force_authenticate(self.super_admin)
        assign = self.client.post(
            "/api/extra-work/bulk-assign/",
            {
                "requests": [late.id],
                "workers": [self.worker.id],
            },
            format="json",
        )
        self.assertEqual(assign.status_code, status.HTTP_200_OK, assign.data)
        self.assertEqual(assign.data["created"], 1)

        payload = self.get_plan(self.worker)
        entry = self.entry(payload, f"ew-{late.id}")
        self.assertIsNotNone(entry, payload["entries"])
        self.assertTrue(entry["is_overdue"])
        self.assertEqual(entry["overdue_days"], 1)

    def test_a_started_job_planned_for_later_is_marked_started_early(self):
        ticket = self.make_ticket("Deep clean", TicketStatus.IN_PROGRESS)
        slot = self.make_slot(
            ticket, start=self.today + datetime.timedelta(days=21)
        )
        payload = self.get_plan(self.worker)
        entry = self.entry(payload, f"slot-{slot.id}")
        self.assertIsNotNone(entry, payload["entries"])
        self.assertEqual(entry["placement"], PLACEMENT_STARTED_EARLY)
        self.assertEqual(entry["state"], STATE_IN_PROGRESS)
        self.assertEqual(entry["day"], self.today.isoformat())

    def test_the_same_job_is_still_in_its_planned_week(self):
        planned_day = self.today + datetime.timedelta(days=21)
        ticket = self.make_ticket("Deep clean", TicketStatus.IN_PROGRESS)
        slot = self.make_slot(ticket, start=planned_day)
        iso = planned_day.isocalendar()
        payload = self.get_plan(
            self.worker, week=f"{iso[0]}-W{iso[1]:02d}"
        )
        entry = self.entry(payload, f"slot-{slot.id}")
        self.assertIsNotNone(entry, payload["entries"])
        self.assertEqual(entry["placement"], PLACEMENT_PLANNED)
        self.assertEqual(entry["day"], planned_day.isoformat())

    def test_untouched_future_work_is_upcoming_not_in_this_week(self):
        future = self.make_extra_work(
            "Autumn window round",
            preferred=self.today + datetime.timedelta(days=30),
            assignee=self.worker,
        )
        payload = self.get_plan(self.worker)
        self.assertIsNone(self.entry(payload, f"ew-{future.id}"))
        self.assertIsNotNone(
            self.entry(payload, f"ew-{future.id}", "upcoming_entries")
        )
        self.assertEqual(payload["counts"]["upcoming"], 1)

    def test_a_finished_slot_stays_in_its_own_past_week(self):
        past = self.today - datetime.timedelta(days=10)
        ticket = self.make_ticket("Done work")
        slot = self.make_slot(
            ticket, start=past, slot_status=StaffAssignmentSlotStatus.COMPLETED
        )
        this_week = self.get_plan(self.worker)
        self.assertIsNone(self.entry(this_week, f"slot-{slot.id}"))
        iso = past.isocalendar()
        its_week = self.get_plan(self.worker, week=f"{iso[0]}-W{iso[1]:02d}")
        entry = self.entry(its_week, f"slot-{slot.id}")
        self.assertIsNotNone(entry, its_week["entries"])
        self.assertEqual(entry["placement"], PLACEMENT_PLANNED)
        self.assertEqual(entry["state"], STATE_DONE)

    def test_an_unscheduled_live_job_is_counted_not_dropped(self):
        ticket = self.make_ticket("No date yet")
        self.make_slot(ticket, start=None)
        payload = self.get_plan(self.worker)
        self.assertEqual(payload["counts"]["undated"], 1)


# ---------------------------------------------------------------------
# 4. Scope, tenancy and the counts
# ---------------------------------------------------------------------


class WorkPlanScopeTests(WorkPlanFixture, APITestCase):
    def setUp(self):
        super().setUp()
        self.mine_ticket = self.make_ticket("Mine")
        self.mine_slot = self.make_slot(self.mine_ticket, start=self.today)
        self.mine_ew = self.make_extra_work(
            "My extra work", preferred=self.today, assignee=self.worker
        )
        # Same company, somebody else's work.
        self.colleague = self.make_user("colleague-179@example.com", UserRole.STAFF)
        self.their_ticket = self.make_ticket("Theirs")
        self.their_slot = self.make_slot(
            self.their_ticket, user=self.colleague, start=self.today
        )
        self.their_ew = self.make_extra_work(
            "Their extra work", preferred=self.today, assignee=self.colleague
        )
        # A different tenant entirely.
        self.foreign_ticket = self.make_ticket("Foreign", foreign=True)
        self.foreign_slot = self.make_slot(
            self.foreign_ticket, user=self.foreign_worker, start=self.today
        )
        self.foreign_ew = self.make_extra_work(
            "Foreign extra work",
            preferred=self.today,
            assignee=self.foreign_worker,
            foreign=True,
        )

    def all_keys(self, payload):
        return {entry["key"] for entry in payload["entries"]}

    def test_a_worker_sees_only_their_own_work(self):
        payload = self.get_plan(self.worker)
        self.assertEqual(
            self.all_keys(payload),
            {f"slot-{self.mine_slot.id}", f"ew-{self.mine_ew.id}"},
        )

    def test_the_company_scope_param_does_not_widen_a_worker(self):
        """H-1: the param is a scope for the roles that already hold it,
        never an escalation for the ones that do not."""
        widened = self.get_plan(self.worker, scope="company")
        plain = self.get_plan(self.worker)
        self.assertEqual(self.all_keys(widened), self.all_keys(plain))
        self.assertEqual(widened["scope"], "own")
        self.assertEqual(widened["counts"], plain["counts"])

    def test_an_admin_asking_for_the_company_scope_sees_the_team(self):
        payload = self.get_plan(self.company_admin, scope="company")
        self.assertEqual(payload["scope"], "company")
        self.assertIn(f"slot-{self.mine_slot.id}", self.all_keys(payload))
        self.assertIn(f"slot-{self.their_slot.id}", self.all_keys(payload))
        self.assertIn(f"ew-{self.their_ew.id}", self.all_keys(payload))

    def test_an_admin_without_the_param_sees_their_own_empty_week(self):
        """The reason `?scope=company` exists at all (Sprint 170 §1):
        an admin holds no assignment rows, so the default view is empty
        for them and the nav entry would lead nowhere."""
        payload = self.get_plan(self.company_admin)
        self.assertEqual(self.all_keys(payload), set())

    def test_a_super_admin_is_global_by_construction(self):
        """Not a tenant leak — the opposite. SUPER_ADMIN bypasses tenant
        scoping everywhere in this system, and `scope_tickets_for` hands
        them everything. Pinned so the H-1 test below reads as a
        deliberate exclusion rather than an oversight."""
        payload = self.get_plan(self.super_admin, scope="company")
        keys = self.all_keys(payload)
        self.assertIn(f"slot-{self.mine_slot.id}", keys)
        self.assertIn(f"slot-{self.foreign_slot.id}", keys)

    def test_a_building_manager_gets_the_team_view_through_the_same_scope(self):
        """Sprint 170 §1 already admitted BUILDING_MANAGER to
        `?scope=company` through `scope_tickets_for`. Pinned here
        because Sprint 179A's whole extra-work half rides on the same
        widening and a regression would be silent."""
        payload = self.get_plan(self.manager, scope="company")
        self.assertEqual(payload["scope"], "company")
        self.assertIn(f"slot-{self.mine_slot.id}", self.all_keys(payload))
        self.assertNotIn(f"slot-{self.foreign_slot.id}", self.all_keys(payload))

    def test_a_manager_of_another_building_sees_none_of_this_building(self):
        payload = self.get_plan(self.other_manager, scope="company")
        self.assertNotIn(f"slot-{self.mine_slot.id}", self.all_keys(payload))
        self.assertNotIn(f"ew-{self.mine_ew.id}", self.all_keys(payload))

    def test_no_tenant_crosses_in_either_scope(self):
        """H-1, both sources, both scopes.

        SUPER_ADMIN is deliberately absent: it is global by
        construction (see the test above), and every OTHER role is
        confined to its own tenant here.
        """
        for actor in (self.worker, self.company_admin, self.manager):
            for scope in ("own", "company"):
                with self.subTest(actor=actor.email, scope=scope):
                    payload = self.get_plan(
                        actor, **({"scope": "company"} if scope == "company" else {})
                    )
                    keys = self.all_keys(payload)
                    self.assertNotIn(f"slot-{self.foreign_slot.id}", keys)
                    self.assertNotIn(f"ew-{self.foreign_ew.id}", keys)

    def test_a_foreign_admin_sees_only_their_own_tenant(self):
        payload = self.get_plan(self.other_company_admin, scope="company")
        keys = self.all_keys(payload)
        self.assertIn(f"slot-{self.foreign_slot.id}", keys)
        self.assertNotIn(f"slot-{self.mine_slot.id}", keys)
        self.assertNotIn(f"ew-{self.mine_ew.id}", keys)

    def test_a_worker_only_gets_the_completion_action_on_their_own_slot(self):
        payload = self.get_plan(self.company_admin, scope="company")
        for entry in payload["entries"]:
            with self.subTest(key=entry["key"]):
                self.assertFalse(entry["can_complete"])

    def test_personal_scope_names_only_the_viewer_on_an_extra_work(self):
        """Who ELSE is on a job is a management read. A worker's own
        week does not become a roster of colleagues."""
        ExtraWorkAssignment.objects.create(
            extra_work_request=self.mine_ew,
            user=self.colleague,
            role=ExtraWorkAssignmentRole.WORKER,
            assigned_by=self.super_admin,
        )
        payload = self.get_plan(self.worker)
        entry = self.entry(payload, f"ew-{self.mine_ew.id}")
        self.assertEqual(entry["assignee_names"], [self.worker.full_name])
        team = self.get_plan(self.company_admin, scope="company")
        team_entry = self.entry(team, f"ew-{self.mine_ew.id}")
        self.assertEqual(team_entry["assignee_count"], 2)

    def test_extra_work_with_nobody_on_it_is_not_anybodys_work(self):
        unassigned = self.make_extra_work(
            "Nobody is doing this", preferred=self.today
        )
        payload = self.get_plan(self.company_admin, scope="company")
        self.assertNotIn(f"ew-{unassigned.id}", self.all_keys(payload))

    def test_the_counts_describe_the_scope_not_the_returned_page(self):
        payload = self.get_plan(self.company_admin, scope="company")
        self.assertEqual(payload["counts"]["total"], len(payload["entries"]))
        self.assertEqual(payload["counts"]["open"], 4)
        # And a worker's own counts describe only their own work.
        mine = self.get_plan(self.worker)
        self.assertEqual(mine["counts"]["total"], 2)


# ---------------------------------------------------------------------
# 5. Two expressions of one rule, pinned equal
# ---------------------------------------------------------------------


class WorkPlanRuleParityTests(WorkPlanFixture, APITestCase):
    """The counts are SQL; the placements are Python. They must agree.

    `is_overdue` and `started_before_plan` are each defined ONCE on the
    model and the list filters express the same rule in SQL — the
    product docs make that a standing requirement, and this is the same
    requirement one level up. Over a fixture that hits every branch, the
    number the chip shows equals the number of cards the rule places.
    """

    def setUp(self):
        super().setUp()
        day = datetime.timedelta(days=1)
        # Slots across every state and every position relative to now.
        planned_now = self.make_ticket("Planned this week")
        self.make_slot(planned_now, start=self.today)
        started = self.make_ticket("Started, planned later", TicketStatus.IN_PROGRESS)
        self.make_slot(started, start=self.today + 30 * day)
        late = self.make_ticket("Late")
        self.make_slot(late, start=self.today - 5 * day)
        done = self.make_ticket("Done")
        self.make_slot(
            done,
            start=self.today - 2 * day,
            slot_status=StaffAssignmentSlotStatus.COMPLETED,
        )
        blocked = self.make_ticket("Blocked")
        self.make_slot(
            blocked,
            start=self.today - 2 * day,
            slot_status=StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE,
        )
        undated = self.make_ticket("Undated")
        self.make_slot(undated, start=None)
        spanning = self.make_ticket("Spanning")
        self.make_slot(spanning, start=self.today - 1 * day, end=self.today + 1 * day)

        # Extra work, same spread.
        self.make_extra_work(
            "EW planned now", preferred=self.today, assignee=self.worker
        )
        self.make_extra_work(
            "EW started early",
            preferred=self.today + 30 * day,
            ew_status=ExtraWorkStatus.IN_PROGRESS,
            assignee=self.worker,
        )
        self.make_extra_work(
            "EW late",
            preferred=self.today - 20 * day,
            deadline=self.today - 4 * day,
            assignee=self.worker,
        )
        self.make_extra_work(
            "EW done",
            preferred=self.today - 2 * day,
            deadline=self.today - 2 * day,
            ew_status=ExtraWorkStatus.COMPLETED,
            assignee=self.worker,
        )
        self.make_extra_work(
            "EW cancelled",
            preferred=self.today,
            ew_status=ExtraWorkStatus.CANCELLED,
            assignee=self.worker,
        )
        self.make_extra_work(
            "EW upcoming", preferred=self.today + 40 * day, assignee=self.worker
        )
        self.make_extra_work("EW undated", assignee=self.worker)

    def python_counts(self, payload):
        """What the rule says, from the entries it actually placed."""
        entries = payload["entries"]
        return {
            "total": len(entries),
            "overdue": sum(1 for e in entries if e["is_overdue"]),
            "open": sum(1 for e in entries if e["state"] == STATE_OPEN),
            "in_progress": sum(
                1 for e in entries if e["state"] == STATE_IN_PROGRESS
            ),
            "done": sum(1 for e in entries if e["state"] == STATE_DONE),
            "blocked": sum(1 for e in entries if e["state"] == STATE_BLOCKED),
        }

    def test_the_sql_counts_equal_the_rule_over_the_same_rows(self):
        for week_offset in (-1, 0, 1, 4):
            target = self.today + datetime.timedelta(weeks=week_offset)
            iso = target.isocalendar()
            with self.subTest(week=f"{iso[0]}-W{iso[1]:02d}"):
                payload = self.get_plan(
                    self.worker, week=f"{iso[0]}-W{iso[1]:02d}"
                )
                self.assertFalse(payload["truncated"]["entries"])
                counts = payload["counts"]
                for key, value in self.python_counts(payload).items():
                    self.assertEqual(
                        counts[key],
                        value,
                        f"{key}: chip says {counts[key]}, rule places {value}",
                    )

    def test_the_upcoming_count_equals_the_upcoming_list(self):
        payload = self.get_plan(self.worker)
        self.assertFalse(payload["truncated"]["upcoming_entries"])
        self.assertEqual(
            payload["counts"]["upcoming"], len(payload["upcoming_entries"])
        )
        # Nothing in it is started, late or finished — the guard the SQL
        # leaves out because it is provably unreachable.
        for entry in payload["upcoming_entries"]:
            with self.subTest(key=entry["key"]):
                self.assertEqual(entry["state"], STATE_OPEN)
                self.assertFalse(entry["is_overdue"])

    def test_the_overdue_count_equals_the_overdue_list(self):
        payload = self.get_plan(self.worker)
        self.assertFalse(payload["truncated"]["overdue_entries"])
        self.assertEqual(
            payload["counts"]["overdue_all"], len(payload["overdue_entries"])
        )
        for entry in payload["overdue_entries"]:
            with self.subTest(key=entry["key"]):
                # Being LATE is the property this list selects on, and it
                # is a flag of its own on the entry.
                self.assertTrue(entry["is_overdue"])
                # Sprint 183 §4 — this used to demand `placement ==
                # OVERDUE`, and that was wrong. PLACEMENT answers a
                # different question: WHY is this card in the week on
                # screen. A job whose planned window covers the current
                # week is at HOME in it (PLACEMENT_PLANNED) and can be
                # late at the same time — planned for Monday, still not
                # done on Thursday. Both are true, which is precisely why
                # `is_overdue` is a separate field and not a placement
                # value.
                #
                # The old assertion only failed on the weekdays where a
                # fixture's overdue row happened to land inside the
                # current ISO week: `today - 5 days` is last week on a
                # Tuesday and THIS week on a Saturday. It passed for
                # months and then failed on a Saturday — the worst kind
                # of test, one whose result depends on when it is run.
                self.assertIn(
                    entry["placement"],
                    (PLACEMENT_OVERDUE, PLACEMENT_PLANNED),
                    "an overdue row is either dragged into this week by "
                    "rule 3, or already at home in it",
                )

    def test_every_card_outside_its_planned_week_carries_a_reason(self):
        """§12B: "A card shown outside its planned week must say why."

        The reason and the planned date both travel on the card, so the
        page can render the marker without a second fetch.
        """
        payload = self.get_plan(self.worker)
        visitors = [
            e for e in payload["entries"] if e["placement"] != PLACEMENT_PLANNED
        ]
        self.assertTrue(visitors, payload["entries"])
        for entry in visitors:
            with self.subTest(key=entry["key"]):
                self.assertIn(
                    entry["placement"],
                    {PLACEMENT_STARTED, PLACEMENT_STARTED_EARLY, PLACEMENT_OVERDUE},
                )
                self.assertTrue(
                    entry["planned_start"] or entry["due_date"],
                    "a visiting card with neither a planned date nor a "
                    "deadline cannot explain itself",
                )
