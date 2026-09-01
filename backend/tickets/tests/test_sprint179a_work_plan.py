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

    def test_a_started_job_planned_for_september_stays_in_september(self):
        """W-FIX1 E2 — started work is not copied onto today; it is at
        home in its planned week and nowhere else on the board."""
        job = Job(
            planned_start=datetime.date(2026, 9, 2),
            planned_end=None,
            due=None,
            state=STATE_IN_PROGRESS,
        )
        self.assertIsNone(self.place(job))
        sep_start, sep_end = iso_week_bounds(2026, 36)
        self.assertEqual(self.place(job, sep_start, sep_end), PLACEMENT_PLANNED)
    def test_a_started_job_from_a_past_week_is_not_carried_into_now(self):
        """W-FIX1 E2 — last week's job stays in last week; if it is also
        late the overdue strip names it."""
        job = Job(
            planned_start=datetime.date(2026, 8, 4),
            planned_end=None,
            due=None,
            state=STATE_IN_PROGRESS,
        )
        self.assertIsNone(self.place(job))
        self.assertEqual(
            self.place(job, self.prev_start, self.prev_end), PLACEMENT_PLANNED
        )
    def test_a_started_job_with_no_plan_at_all_is_undated_not_today(self):
        """W-FIX1 E2 — no planned window, no day column; the undated
        lane carries it. `day_for` still hangs a strip placement on
        today when the view asks which day."""
        job = Job(
            planned_start=None, planned_end=None, due=None, state=STATE_IN_PROGRESS
        )
        self.assertIsNone(self.place(job))
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

    def test_a_job_past_its_deadline_is_late_but_not_placed_today(self):
        """W-FIX1 E2 — late is a fact the overdue strip carries; it is not
        a placement in this week."""
        job = Job(
            planned_start=None,
            planned_end=None,
            due=datetime.date(2026, 8, 3),
            state=STATE_OPEN,
        )
        self.assertIsNone(self.place(job))
        self.assertTrue(is_overdue(job, self.today))
        self.assertEqual(overdue_days(job, self.today), 10)
    def test_a_late_started_job_is_neither_placed_today(self):
        """W-FIX1 E2 — both facts are carried by the strips, not by a
        visitor card on today."""
        job = Job(
            planned_start=datetime.date(2026, 9, 2),
            planned_end=None,
            due=datetime.date(2026, 8, 3),
            state=STATE_IN_PROGRESS,
        )
        self.assertIsNone(self.place(job))
        self.assertTrue(is_overdue(job, self.today))
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

    def test_started_and_late_work_reach_no_week_at_all(self):
        """W-FIX1 E2 — planned placement is the only placement; neither
        this week nor the next shows a visitor card."""
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
                self.assertIsNone(self.place(job))
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

    def make_ticket(
        self,
        title,
        statusValue=TicketStatus.OPEN,
        *,
        foreign=False,
        scheduled=None,
        scheduled_end=None,
    ):
        """W-VIEWER — `scheduled` is the JOB's own date, and it is the
        only thing that places a manager's card. A ticket made without
        one is a job nobody has scheduled, whatever days its people
        carry, and the manager's board files it under "not planned yet"
        — which is the ruling, stated as a fixture."""

        def at(day, hour):
            if day is None:
                return None
            return timezone.make_aware(
                datetime.datetime.combine(day, datetime.time(hour, 0))
            )

        ticket = Ticket.objects.create(
            company=self.other_company if foreign else self.company,
            customer=self.other_customer if foreign else self.customer,
            building=self.other_building if foreign else self.building,
            title=title,
            description="x",
            type=TicketType.REQUEST,
            status=statusValue,
            created_by=self.super_admin,
            scheduled_start_at=at(scheduled, 8),
            scheduled_end_at=at(scheduled_end, 17),
        )
        # P-1 — a scheduled fixture is a PERSON's plan, and says so.
        if scheduled is not None:
            self.record_plan(ticket)
        return ticket

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
    # P-3 §A.3 — the clock, decided server-side in the server's zone;
    # null when the plan is a day and not a time.
    "start_time",
    "end_time",
    "time_window_label",
    "assignment_note",
    "completion_note",
    "unable_to_complete_reason",
    "day",
    "placement",
    # W-PLANTRUTH §1b — the day a ROLLED card was planned for, and how
    # far past it we are. Present on every entry (null off a rolled
    # card) for the same reason `parts` and `lateness` are: one shape,
    # whatever the source.
    "rolled_from",
    "rolled_days",
    "is_overdue",
    "overdue_days",
    # W-VIEWER §5 — how THIS reader stands against the promise (signed:
    # days left, or days over), and whether anything is being asked of
    # them right now. Both present on every kind, null / false where
    # they do not apply, for the same one-shape reason as the rest.
    "days_until_due",
    "viewer_settled",
    # WP-1 G2 — days a dateless job has waited for a plan (null on a
    # dated entry). G1 — days a stuck job has been stuck (set on the
    # stuck list's rows, null everywhere else). One shape, both kinds.
    "unplanned_age_days",
    "stuck_age_days",
    # P-4 (Part E) -- the waiting drawer acts: may THIS reader answer on the
    # customer's behalf. False on every row that is not waiting.
    "can_override_customer_decision",
    # FE-4 (Addendum D SS D.12) -- the honest-date facts: when the record
    # was created (never a plan), what kind of date placed it, what the
    # headline lateness counts against, and when settled work was over.
    "created_at",
    "plan_source",
    # P-1 -- provenance: a date is a plan only if a person made it.
    "has_real_plan",
    "planned_by_name",
    "planned_at",
    "created_by_name",
    "due_kind",
    "settled_at",
    "reported_done_at",
    "settled_days_after_due",
    # P-9 §A.3 — the one card standard's facts, on every kind: who
    # reported the work done and how long ago, when the customer
    # approved, who the finished work was sent to, the plan's hours, and
    # how many days after the plan the finish came.
    "reported_done_by_name",
    "waiting_days",
    "approved_at",
    "sent_to_name",
    "planned_hours",
    "settled_days_after_plan",
    # P-3 §A.3 — the same three moments as server-decided DAYS.
    "settled_day",
    "reported_done_day",
    "approved_day",
    # P-3 §A.5 — a real plan whose last day is past the deadline.
    "planned_after_deadline",
    "assignee_names",
    "assignee_count",
    # W-N1 §3 — the parts of this ticket the entry's person holds. This
    # constant is shared by both kinds on purpose ("a field cannot exist
    # on one and be forgotten on the other"), which is why extra work
    # emits `"parts": []` rather than omitting the key.
    "parts",
    # W-LATE §1b — the rung this job stands on, from `tickets/lateness.py`.
    # Shared by both kinds for the same reason `parts` is: an extra work
    # answers `level: null` rather than omitting the key.
    "lateness",
    "can_complete",
}

#: Commercial and internal extra-work fields that must never reach this
#: P-7 S8 / P-8R — keys an entry carries only on ONE list: `parked_reason`
#: is stamped on `parked_entries` (the reason it was parked for) and on
#: nothing else, so it is not part of the exact shape above.
OPTIONAL_ENTRY_KEYS = {"parked_reason"}

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
                "parked_entries",
                # W-LATE §1a — the late strip's rows.
                "late_entries",
                # WP-1 G1 — the "Vastgelopen — actie nodig" rows.
                "stuck_entries",
                # P-3 §A.1 — the "Wacht op klant" chip's rows.
                "waiting_customer_entries",
                # FE-5 step 0 — whether this viewer may plan undated work.
                # (On the wire since FE-5; this set had drifted — P-1.)
                "can_plan",
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
                # W-LATE §1a — late JOBS, deduped, any week.
                "late",
                # WP-1 G1 — stuck jobs, whole scope.
                "stuck",
                # P-3 §A.1 — jobs waiting on the customer, whole scope.
                "waiting_customer",
                "parked",
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
                "parked_entries",
                "late_entries",
                "stuck_entries",
                "waiting_customer_entries",
            },
        )
        self.assertEqual(
            set(payload["truncated"]),
            {
                "entries",
                "overdue_entries",
                "upcoming_entries",
                "undated_entries",
                "parked_entries",
                "late_entries",
                "stuck_entries",
                "waiting_customer_entries",
            },
        )
        self.assertFalse(any(payload["truncated"].values()))

    def test_a_ticket_slot_entry_carries_exactly_these_fields(self):
        payload = self.get_plan(self.worker)
        entry = self.entry(payload, f"slot-{self.slot.id}")
        self.assertIsNotNone(entry)
        self.assertEqual(set(entry) - OPTIONAL_ENTRY_KEYS, ENTRY_KEYS)
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
        self.assertEqual(set(entry) - OPTIONAL_ENTRY_KEYS, ENTRY_KEYS)
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
    def test_an_overdue_extra_work_shows_as_overdue_in_the_workers_strip(self):
        """THE acceptance test, after W-PLANTRUTH §1b.

        An extra work assigned to a worker, past its deadline, appears
        in that worker's OVERDUE strip — with a reason on the row and
        its planned date. Since the ruling it ALSO appears on today's
        column, stamped ROLLED, because its planned day has passed and
        the work is not done: undone work does not sit in the past. The
        two are different questions ("past its deadline" / "its planned
        day has gone") and both keep their own answer.
        """
        late = self.make_extra_work(
            "Gutter clearing",
            preferred=self.today - datetime.timedelta(days=14),
            deadline=self.today - datetime.timedelta(days=3),
            assignee=self.worker,
        )
        payload = self.get_plan(self.worker)
        rolled = self.entry(payload, f"ew-{late.id}")
        self.assertIsNotNone(rolled, payload["entries"])
        self.assertEqual(rolled["placement"], "ROLLED")
        self.assertEqual(rolled["day"], self.today.isoformat())
        entry = self.entry(payload, f"ew-{late.id}", "overdue_entries")
        self.assertIsNotNone(entry, payload["overdue_entries"])
        self.assertTrue(entry["is_overdue"])
        self.assertEqual(entry["placement"], PLACEMENT_OVERDUE)
        self.assertEqual(entry["overdue_days"], 3)
        self.assertEqual(
            entry["planned_start"],
            (self.today - datetime.timedelta(days=14)).isoformat(),
        )
        self.assertEqual(
            entry["due_date"],
            (self.today - datetime.timedelta(days=3)).isoformat(),
        )
        self.assertEqual(payload["counts"]["overdue_all"], 1)
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
        entry = self.entry(payload, f"ew-{late.id}", "overdue_entries")
        self.assertIsNotNone(entry, payload["overdue_entries"])
        self.assertTrue(entry["is_overdue"])
        self.assertEqual(entry["overdue_days"], 1)
    def test_a_started_job_planned_for_later_is_not_on_this_week(self):
        """W-FIX1 E2 — the job is at home in its own week (next test)
        and nowhere on this one."""
        ticket = self.make_ticket("Deep clean", TicketStatus.IN_PROGRESS)
        slot = self.make_slot(
            ticket, start=self.today + datetime.timedelta(days=21)
        )
        payload = self.get_plan(self.worker)
        self.assertIsNone(self.entry(payload, f"slot-{slot.id}"), payload["entries"])
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
        self.mine_ticket = self.make_ticket("Mine", scheduled=self.today)
        self.mine_slot = self.make_slot(self.mine_ticket, start=self.today)
        self.mine_ew = self.make_extra_work(
            "My extra work", preferred=self.today, assignee=self.worker
        )
        # Same company, somebody else's work.
        self.colleague = self.make_user("colleague-179@example.com", UserRole.STAFF)
        self.their_ticket = self.make_ticket("Theirs", scheduled=self.today)
        self.their_slot = self.make_slot(
            self.their_ticket, user=self.colleague, start=self.today
        )
        self.their_ew = self.make_extra_work(
            "Their extra work", preferred=self.today, assignee=self.colleague
        )
        # A different tenant entirely.
        self.foreign_ticket = self.make_ticket(
            "Foreign", foreign=True, scheduled=self.today
        )
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
        """W-VIEWER — and sees JOBS. The team board answers one row per
        TICKET (`ticket-<id>`), not one per assigned person."""
        payload = self.get_plan(self.company_admin, scope="company")
        self.assertEqual(payload["scope"], "company")
        self.assertIn(f"ticket-{self.mine_ticket.id}", self.all_keys(payload))
        self.assertIn(f"ticket-{self.their_ticket.id}", self.all_keys(payload))
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
        self.assertIn(f"ticket-{self.mine_ticket.id}", keys)
        self.assertIn(f"ticket-{self.foreign_ticket.id}", keys)

    def test_a_building_manager_gets_the_team_view_through_the_same_scope(self):
        """Sprint 170 §1 already admitted BUILDING_MANAGER to
        `?scope=company` through `scope_tickets_for`. Pinned here
        because Sprint 179A's whole extra-work half rides on the same
        widening and a regression would be silent."""
        payload = self.get_plan(self.manager, scope="company")
        self.assertEqual(payload["scope"], "company")
        self.assertIn(f"ticket-{self.mine_ticket.id}", self.all_keys(payload))
        self.assertNotIn(
            f"ticket-{self.foreign_ticket.id}", self.all_keys(payload)
        )

    def test_a_manager_of_another_building_sees_none_of_this_building(self):
        payload = self.get_plan(self.other_manager, scope="company")
        self.assertNotIn(f"ticket-{self.mine_ticket.id}", self.all_keys(payload))
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
                    self.assertNotIn(
                        f"ticket-{self.foreign_ticket.id}", keys
                    )
                    self.assertNotIn(f"ew-{self.foreign_ew.id}", keys)

    def test_a_foreign_admin_sees_only_their_own_tenant(self):
        payload = self.get_plan(self.other_company_admin, scope="company")
        keys = self.all_keys(payload)
        self.assertIn(f"ticket-{self.foreign_ticket.id}", keys)
        self.assertNotIn(f"ticket-{self.mine_ticket.id}", keys)
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

    def test_the_sql_counts_equal_the_rule_for_the_TEAM_board_too(self):
        """W-VIEWER — the team board is a second source with a second
        family of predicates. Two expressions of one rule again, so the
        same equality is asserted over it: the chip counts JOBS and the
        rule places JOBS, or the page reports a number nobody can
        reconcile with what is on screen."""
        day = datetime.timedelta(days=1)
        # Give the jobs of this fixture their own dates, which is what a
        # manager's board is placed by. Spread across every branch: this
        # week, a past week (rolls), a future week (upcoming), and one
        # with no date at all (undated).
        scheduled = [0, -6, 20, None, -1, 3, None]
        for ticket, offset in zip(
            Ticket.objects.filter(company=self.company).order_by("id"),
            scheduled + [None] * 20,
        ):
            if offset is None:
                continue
            ticket.scheduled_start_at = timezone.make_aware(
                datetime.datetime.combine(
                    self.today + offset * day, datetime.time(8, 0)
                )
            )
            ticket.save(update_fields=["scheduled_start_at"])

        for week_offset in (-1, 0, 1, 4):
            target = self.today + datetime.timedelta(weeks=week_offset)
            iso = target.isocalendar()
            with self.subTest(week=f"{iso[0]}-W{iso[1]:02d}"):
                payload = self.get_plan(
                    self.company_admin,
                    week=f"{iso[0]}-W{iso[1]:02d}",
                    scope="company",
                )
                self.assertEqual(payload["scope"], "company")
                self.assertFalse(payload["truncated"]["entries"])
                counts = payload["counts"]
                for key, value in self.python_counts(payload).items():
                    self.assertEqual(
                        counts[key],
                        value,
                        f"{key}: chip says {counts[key]}, rule places {value}",
                    )

    def test_the_team_board_answers_one_row_per_job(self):
        """However many people are on a ticket — the ruling's own
        sentence, asserted as a shape rather than a count."""
        payload = self.get_plan(self.company_admin, scope="company")
        for bucket in (
            "entries",
            "overdue_entries",
            "upcoming_entries",
            "undated_entries",
            "parked_entries",
            "late_entries",
        ):
            with self.subTest(bucket=bucket):
                ticket_ids = [
                    row["ticket_id"]
                    for row in payload[bucket]
                    if row["ticket_id"] is not None
                ]
                self.assertEqual(
                    len(ticket_ids),
                    len(set(ticket_ids)),
                    f"{bucket} repeats a job: {ticket_ids}",
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

    def test_every_card_is_at_home_or_says_why_it_rolled(self):
        """§12B — "a card shown outside its planned week must say why".

        W-FIX1 E2 answered that by never showing one; W-PLANTRUTH §1b
        shows exactly one kind of visitor again, and it says why. So the
        week holds PLANNED cards and ROLLED ones, nothing else — and
        every ROLLED card sits on today carrying the day it came from
        and how late that makes it. The strips still carry the rest and
        stamp their own reason; this asserts both halves."""
        payload = self.get_plan(self.worker)
        for entry in payload["entries"]:
            with self.subTest(key=entry["key"]):
                # WP-1 G0 — a third visitor: overdue-and-open in the
                # current week, hung on today with the overdue marker.
                self.assertIn(
                    entry["placement"],
                    (PLACEMENT_PLANNED, "ROLLED", PLACEMENT_OVERDUE),
                )
                if entry["placement"] == "ROLLED":
                    self.assertEqual(entry["day"], payload["today"])
                    self.assertIsNotNone(entry["rolled_from"])
                    self.assertGreaterEqual(entry["rolled_days"], 1)
                elif entry["placement"] == PLACEMENT_OVERDUE:
                    self.assertEqual(entry["day"], payload["today"])
                    self.assertTrue(entry["is_overdue"])
                else:
                    self.assertIsNone(entry["rolled_from"])
        self.assertTrue(payload["overdue_entries"], payload)
        for entry in payload["overdue_entries"]:
            with self.subTest(key=entry["key"]):
                self.assertIn(entry["placement"], (PLACEMENT_OVERDUE, PLACEMENT_PLANNED))
                self.assertTrue(
                    entry["planned_start"] or entry["due_date"],
                    "a strip row with neither a planned date nor a "
                    "deadline cannot explain itself",
                )


# ---------------------------------------------------------------------
# WP-1 (Addendum D §D.11.3) — carry-forward, the stuck list, the chip
# ---------------------------------------------------------------------


class Wp1SameWeekCarryRuleTests(APITestCase):
    """G0, on the pure rule. Frozen dates: 2026-W33 is Mon 10 Aug –
    Sun 16 Aug 2026, today is Thursday 13 Aug."""

    def setUp(self):
        self.week_start, self.week_end = iso_week_bounds(2026, 33)
        self.today = datetime.date(2026, 8, 13)

    def test_overdue_and_open_beats_planned_in_the_current_week(self):
        """Acceptance test 1a — the same-week carry. Planned Monday to
        Sunday of THIS week, deadline Tuesday, read on Thursday: the
        card is a marked visitor on today, not quietly at home."""
        job = Job(
            planned_start=datetime.date(2026, 8, 10),
            planned_end=datetime.date(2026, 8, 16),
            due=datetime.date(2026, 8, 11),
            state=STATE_OPEN,
        )
        placement = placement_for(
            job, self.week_start, self.week_end, self.today
        )
        self.assertEqual(placement, PLACEMENT_OVERDUE)
        self.assertEqual(
            day_for(job, placement, self.week_start, self.week_end, self.today),
            self.today,
        )

    def test_past_and_future_weeks_keep_planned_placement(self):
        """September still shows September's work — and last week shows
        last week's, as history, unmarked."""
        prev_start, prev_end = iso_week_bounds(2026, 32)
        next_start, next_end = iso_week_bounds(2026, 34)
        last_week = Job(
            planned_start=datetime.date(2026, 8, 4),
            planned_end=datetime.date(2026, 8, 5),
            due=datetime.date(2026, 8, 4),
            state=STATE_OPEN,
        )
        self.assertEqual(
            placement_for(last_week, prev_start, prev_end, self.today),
            PLACEMENT_PLANNED,
        )
        next_week = Job(
            planned_start=datetime.date(2026, 8, 18),
            planned_end=None,
            due=datetime.date(2026, 8, 3),
            state=STATE_OPEN,
        )
        self.assertEqual(
            placement_for(next_week, next_start, next_end, self.today),
            PLACEMENT_PLANNED,
        )

    def test_closed_work_in_the_current_week_stays_planned(self):
        """Finished or cancelled work is never late, so it is never a
        visitor — whatever its due date says."""
        for state in (STATE_DONE, STATE_BLOCKED):
            with self.subTest(state=state):
                job = Job(
                    planned_start=datetime.date(2026, 8, 10),
                    planned_end=datetime.date(2026, 8, 16),
                    due=datetime.date(2026, 8, 11),
                    state=state,
                )
                self.assertEqual(
                    placement_for(
                        job, self.week_start, self.week_end, self.today
                    ),
                    PLACEMENT_PLANNED,
                )

    def test_a_job_due_later_this_week_is_at_home(self):
        """Not yet overdue: planned placement, no marker."""
        job = Job(
            planned_start=datetime.date(2026, 8, 10),
            planned_end=datetime.date(2026, 8, 16),
            due=datetime.date(2026, 8, 15),
            state=STATE_OPEN,
        )
        self.assertEqual(
            placement_for(job, self.week_start, self.week_end, self.today),
            PLACEMENT_PLANNED,
        )


class Wp1CarryForwardEndpointTests(WorkPlanFixture, APITestCase):
    """G0 on rendered responses — acceptance tests 1 and 1a."""

    def test_1_rolled_slot_appears_today_and_leaves_when_completed(self):
        """Test 1 — slot planned last week, still ASSIGNED: on today's
        column marked with the planned day and the late count. Completed:
        off today, at home in its own week as done work."""
        planned = self.today - datetime.timedelta(days=7)
        ticket = self.make_ticket("Hall carpet")
        slot = self.make_slot(ticket, start=planned)

        payload = self.get_plan(self.worker)
        entry = self.entry(payload, f"slot-{slot.id}")
        self.assertIsNotNone(entry, payload["entries"])
        self.assertEqual(entry["placement"], "ROLLED")
        self.assertEqual(entry["day"], self.today.isoformat())
        self.assertEqual(entry["rolled_from"], planned.isoformat())
        self.assertEqual(entry["rolled_days"], 7)

        slot.slot_status = StaffAssignmentSlotStatus.COMPLETED
        slot.save(update_fields=["slot_status"])
        payload = self.get_plan(self.worker)
        self.assertIsNone(self.entry(payload, f"slot-{slot.id}"))
        iso = planned.isocalendar()
        home = self.get_plan(self.worker, week=f"{iso[0]}-W{iso[1]:02d}")
        entry = self.entry(home, f"slot-{slot.id}")
        self.assertIsNotNone(entry, home["entries"])
        self.assertEqual(entry["placement"], PLACEMENT_PLANNED)
        self.assertEqual(entry["state"], STATE_DONE)

    def test_1a_overdue_work_planned_this_week_is_marked_on_today(self):
        """Test 1a — the same-week carry: the planned window still
        covers this week, but the deadline has passed. Before G0 the
        card sat at home with only a flag; now it is stamped OVERDUE on
        today's column. Only a real deadline can produce this state — a
        slot with no deadline is due on its last planned day, so its
        window is always gone before it is late (and rule 5 rolls it)."""
        week_start = self.today - datetime.timedelta(
            days=self.today.isoweekday() - 1
        )
        week_end = week_start + datetime.timedelta(days=6)
        late = self.make_extra_work(
            "Facade wash",
            preferred=week_start,
            planned_end=week_end,
            deadline=self.today - datetime.timedelta(days=1),
            assignee=self.worker,
        )
        payload = self.get_plan(self.worker)
        entry = self.entry(payload, f"ew-{late.id}")
        self.assertIsNotNone(entry, payload["entries"])
        self.assertEqual(entry["placement"], PLACEMENT_OVERDUE)
        self.assertEqual(entry["day"], self.today.isoformat())
        self.assertTrue(entry["is_overdue"])
        self.assertEqual(entry["overdue_days"], 1)
        # The planned day the marker prints is on the entry.
        self.assertEqual(entry["planned_start"], week_start.isoformat())

    def test_1a_the_same_card_is_planned_in_a_past_week_view(self):
        """A past week keeps planned placement for the week it covers —
        the carry marks the CURRENT week only."""
        prev_monday = self.today - datetime.timedelta(
            days=self.today.isoweekday() + 6
        )
        prev_sunday = prev_monday + datetime.timedelta(days=6)
        late = self.make_extra_work(
            "Old week work",
            preferred=prev_monday,
            planned_end=prev_sunday,
            deadline=prev_monday,
            assignee=self.worker,
        )
        iso = prev_monday.isocalendar()
        payload = self.get_plan(self.worker, week=f"{iso[0]}-W{iso[1]:02d}")
        entry = self.entry(payload, f"ew-{late.id}")
        # Its planned week is a PAST week: rule 5 has taken the card to
        # today's column of the CURRENT week, so the past week shows it
        # only if the work were finished. Pending work never lingers in
        # yesterday (W-PLANTRUTH §1b) — so the row is absent here...
        self.assertIsNone(entry, payload["entries"])
        # ...and rolled onto today in the current week.
        current = self.get_plan(self.worker)
        entry = self.entry(current, f"ew-{late.id}")
        self.assertIsNotNone(entry, current["entries"])
        self.assertEqual(entry["placement"], "ROLLED")


class Wp1StuckListTests(WorkPlanFixture, APITestCase):
    """G1 — acceptance test 2: a blocked job enters the follow-up list
    and leaves it only through a human's reschedule / reassign /
    cancel."""

    def block(self, slot, reason="Door locked"):
        slot.slot_status = StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE
        slot.unable_to_complete_reason = reason
        slot.save(update_fields=["slot_status", "unable_to_complete_reason"])

    def test_2_unable_slot_enters_the_stuck_list_with_age(self):
        planned = self.today - datetime.timedelta(days=4)
        ticket = self.make_ticket("Blocked work", scheduled=planned)
        slot = self.make_slot(ticket, start=planned)
        self.block(slot)

        team = self.get_plan(self.company_admin, scope="company")
        entry = self.entry(team, f"ticket-{ticket.id}", "stuck_entries")
        self.assertIsNotNone(entry, team["stuck_entries"])
        # No notification row was written (the block above bypassed the
        # API), so the age falls back to the slot's planned day.
        self.assertEqual(entry["stuck_age_days"], 4)
        self.assertEqual(team["counts"]["stuck"], 1)

        own = self.get_plan(self.worker)
        mine = self.entry(own, f"slot-{slot.id}", "stuck_entries")
        self.assertIsNotNone(mine, own["stuck_entries"])
        self.assertEqual(own["counts"]["stuck"], 1)

    def test_2_reschedule_reassign_and_cancel_each_empty_the_list(self):
        ticket = self.make_ticket("Blocked work")
        slot = self.make_slot(ticket, start=self.today)
        self.block(slot)
        self.assertEqual(
            self.get_plan(self.company_admin, scope="company")["counts"][
                "stuck"
            ],
            1,
        )

        # RESCHEDULE — the unable slot back to ASSIGNED with a new day.
        slot.slot_status = StaffAssignmentSlotStatus.ASSIGNED
        slot.scheduled_start_at = timezone.now() + datetime.timedelta(days=2)
        slot.save(update_fields=["slot_status", "scheduled_start_at"])
        team = self.get_plan(self.company_admin, scope="company")
        self.assertEqual(team["counts"]["stuck"], 0)
        self.assertEqual(team["stuck_entries"], [])

        # REASSIGN — block again, then put somebody else on the job.
        self.block(slot)
        colleague = self.make_user(
            "colleague-wp1@example.com", UserRole.STAFF
        )
        replacement = self.make_slot(ticket, user=colleague, start=self.today)
        team = self.get_plan(self.company_admin, scope="company")
        self.assertEqual(team["counts"]["stuck"], 0)

        # CANCEL — the replacement leaves too and the work is called off.
        replacement.slot_status = StaffAssignmentSlotStatus.CANCELLED
        replacement.save(update_fields=["slot_status"])
        self.assertEqual(
            self.get_plan(self.company_admin, scope="company")["counts"][
                "stuck"
            ],
            1,
        )
        ticket.status = TicketStatus.REJECTED
        ticket.save(update_fields=["status"])
        team = self.get_plan(self.company_admin, scope="company")
        self.assertEqual(team["counts"]["stuck"], 0)

    def test_2_a_colleague_still_assigned_means_not_stuck(self):
        """While somebody is still expected to work the job, it has not
        silently left the system's attention — their slot still rolls."""
        ticket = self.make_ticket("Half blocked")
        mine = self.make_slot(ticket, start=self.today)
        colleague = self.make_user("colleague-wp2@example.com", UserRole.STAFF)
        self.make_slot(ticket, user=colleague, start=self.today)
        self.block(mine)
        team = self.get_plan(self.company_admin, scope="company")
        self.assertEqual(team["counts"]["stuck"], 0)

    def test_2_extra_work_with_a_blocked_ticket_is_stuck(self):
        """The extra-work half: the request is live, its operational
        ticket ended blocked — the work stopped with nobody deciding
        about the request."""
        ew = self.make_extra_work(
            "Stuck request",
            preferred=self.today - datetime.timedelta(days=2),
            assignee=self.worker,
        )
        spawned = self.make_ticket("Spawned", TicketStatus.REJECTED)
        spawned.extra_work_request = ew
        spawned.save(update_fields=["extra_work_request"])
        team = self.get_plan(self.company_admin, scope="company")
        entry = self.entry(team, f"ew-{ew.id}", "stuck_entries")
        self.assertIsNotNone(entry, team["stuck_entries"])
        self.assertIsNotNone(entry["stuck_age_days"])

    def test_2_tenancy_holds_on_the_stuck_list(self):
        """H-1 — another tenant's stuck work is invisible in both
        scopes."""
        foreign_ticket = self.make_ticket("Foreign stuck", foreign=True)
        foreign_slot = self.make_slot(
            foreign_ticket, user=self.foreign_worker, start=self.today
        )
        self.block(foreign_slot)
        team = self.get_plan(self.company_admin, scope="company")
        self.assertEqual(team["counts"]["stuck"], 0)
        self.assertEqual(team["stuck_entries"], [])


class Wp1DateChipTests(WorkPlanFixture, APITestCase):
    """G3 — acceptance test 3: the signed day count, and the wording
    driver that keeps "deadline" off a plain planned day."""

    def test_3_a_future_deadline_counts_down(self):
        ew = self.make_extra_work(
            "Window wax",
            preferred=self.today,
            deadline=self.today + datetime.timedelta(days=10),
            assignee=self.worker,
        )
        payload = self.get_plan(self.worker)
        entry = self.entry(payload, f"ew-{ew.id}")
        self.assertIsNotNone(entry, payload["entries"])
        self.assertEqual(entry["days_until_due"], 10)
        # A real deadline exists, so the chip may say the word: the
        # driver the frontend forks its wording on.
        self.assertIsNotNone(entry["lateness"]["deadline"])

    def test_3_the_count_is_stable_across_week_boundaries(self):
        """The chip counts from TODAY, whatever week is on screen."""
        planned = self.today + datetime.timedelta(days=9)
        ticket = self.make_ticket("Next-week job")
        slot = self.make_slot(ticket, start=planned)
        iso = planned.isocalendar()
        its_week = self.get_plan(self.worker, week=f"{iso[0]}-W{iso[1]:02d}")
        entry = self.entry(its_week, f"slot-{slot.id}")
        self.assertIsNotNone(entry, its_week["entries"])
        self.assertEqual(entry["days_until_due"], 9)
        current = self.get_plan(self.worker)
        upcoming = self.entry(current, f"slot-{slot.id}", "upcoming_entries")
        self.assertIsNotNone(upcoming, current["upcoming_entries"])
        self.assertEqual(upcoming["days_until_due"], 9)

    def test_3_a_slot_without_a_deadline_never_claims_one(self):
        """A plain slot's date is its geplande dag: `days_until_due`
        counts to it, and `lateness.deadline` stays null — the fact the
        chip's copy rule keys on (§D.11.2-G3)."""
        planned = self.today + datetime.timedelta(days=3)
        ticket = self.make_ticket("Plain job")
        slot = self.make_slot(ticket, start=planned)
        # Read the week the slot is planned IN — three days out may
        # cross an ISO week boundary depending on today's weekday.
        iso = planned.isocalendar()
        payload = self.get_plan(self.worker, week=f"{iso[0]}-W{iso[1]:02d}")
        entry = self.entry(payload, f"slot-{slot.id}")
        self.assertIsNotNone(entry, payload["entries"])
        self.assertEqual(entry["days_until_due"], 3)
        self.assertIsNone(entry["lateness"]["deadline"])

    def test_g2_unplanned_age_counts_only_dateless_work(self):
        undated = self.make_extra_work("No date", assignee=self.worker)
        dated = self.make_extra_work(
            "Dated", preferred=self.today, assignee=self.worker
        )
        payload = self.get_plan(self.worker)
        row = self.entry(payload, f"ew-{undated.id}", "undated_entries")
        self.assertIsNotNone(row, payload["undated_entries"])
        self.assertEqual(row["unplanned_age_days"], 0)
        entry = self.entry(payload, f"ew-{dated.id}")
        self.assertIsNone(entry["unplanned_age_days"])
