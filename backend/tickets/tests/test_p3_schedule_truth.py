"""
P-3 (Addendum D §D.15) — the schedule truth pass.

Four things the board must now say honestly, each pinned here:

  1. Work waiting on the CUSTOMER is in no day column of the current
     week (rule 9): it is one row behind the "Wacht op klant" chip.
     Past weeks browsed as history keep placement.
  2. A clock time renders only when a real time exists. The server
     decides that in its own zone (`start_time` / `end_time` on every
     entry, `scheduled_start_time` / `scheduled_end_time` on the
     detail); a date-only plan (stored as local midnight) answers null.
  3. A real plan whose last day is past the deadline says so
     (`planned_after_deadline`) on the card and on the detail — nothing
     is blocked.
  4. The numbers reconcile: every count on the payload equals the list
     it describes, and the board's total is the sum of its state
     buckets.

And the owner's requested COMPLETE edge review: every TicketStatus,
every slot status and every extra-work status placed on the current
week, as one table the report prints.
"""
from __future__ import annotations

import datetime
from unittest import mock

from django.utils import timezone
from rest_framework.test import APITestCase

from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from tickets.models import (
    StaffAssignmentSlotStatus,
    Ticket,
    TicketStatus,
    TicketType,
)
from tickets.tests.test_sprint179a_work_plan import WorkPlanFixture
from tickets.work_plan import (
    PLACEMENTS_NEEDING_A_REASON,
    PLACEMENT_PLANNED,
    PLACEMENT_REVIEW,
    PLACEMENT_ROLLED,
    STATE_BLOCKED,
    STATE_DONE,
    STATE_IN_PROGRESS,
    STATE_OPEN,
)

DAY = datetime.timedelta(days=1)


def _aware(day, hour, minute=0):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, minute))
    )


class _P3Fixture(WorkPlanFixture):
    def find(self, payload, key):
        for bucket in (
            "entries",
            "undated_entries",
            "parked_entries",
            "overdue_entries",
            "upcoming_entries",
            "late_entries",
            "stuck_entries",
            "waiting_customer_entries",
            # P-10 A2 — the manager's-check strip.
            "review_entries",
        ):
            for entry in payload.get(bucket, []):
                if entry["key"] == key:
                    return entry, bucket
        return None, None

    def week_of(self, day):
        iso = day.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"

    def team(self, **params):
        return self.get_plan(self.company_admin, scope="company", **params)

    def own(self, **params):
        return self.get_plan(self.worker, **params)


class WaitingCustomerLeavesTheColumnsTests(_P3Fixture, APITestCase):
    """Rule 9 — the chip, not the column."""

    def _waiting(self, planned, *, title="Sent to the customer"):
        ticket = self.make_ticket(
            title, TicketStatus.WAITING_CUSTOMER_APPROVAL, scheduled=planned
        )
        self.make_slot(
            ticket,
            start=planned,
            slot_status=StaffAssignmentSlotStatus.COMPLETED,
        )
        return ticket

    def test_in_the_current_week_it_is_behind_the_chip_not_in_a_column(self):
        ticket = self._waiting(self.today)
        payload = self.team()
        card, bucket = self.find(payload, f"ticket-{ticket.id}")
        self.assertEqual(bucket, "waiting_customer_entries")
        self.assertEqual(card["ticket_status"], TicketStatus.WAITING_CUSTOMER_APPROVAL)
        self.assertTrue(card["viewer_settled"])
        self.assertEqual(payload["counts"]["waiting_customer"], 1)
        # The board's own numbers do not count it: it is not on the board.
        self.assertEqual(payload["counts"]["total"], 0)
        self.assertEqual(payload["entries"], [])

    def test_a_past_week_browsed_shows_it_behind_the_chip_not_in_a_column(self):
        # P-9 §A.2a (owner ruling): "when it goes to customer approval it
        # leaves the dates" — in EVERY week, not only the current one.
        # Until P-9 a past week kept the calm card in its planned column
        # as history.
        planned = self.today - 10 * DAY
        ticket = self._waiting(planned)
        payload = self.team(week=self.week_of(planned))
        card, bucket = self.find(payload, f"ticket-{ticket.id}")
        self.assertEqual(bucket, "waiting_customer_entries")
        self.assertTrue(card["viewer_settled"])
        self.assertEqual(payload["entries"], [])
        self.assertEqual(payload["counts"]["total"], 0)
        # Still counted behind the chip, whole scope, on any week.
        self.assertEqual(payload["counts"]["waiting_customer"], 1)

    def test_the_workers_own_week_follows_the_same_rule(self):
        ticket = self._waiting(self.today)
        slot = ticket.staff_assignments.get()
        payload = self.own()
        card, bucket = self.find(payload, f"slot-{slot.id}")
        self.assertEqual(bucket, "waiting_customer_entries")
        self.assertEqual(payload["counts"]["waiting_customer"], 1)
        self.assertEqual(payload["entries"], [])

    def test_the_customers_answer_takes_it_out_of_the_chip(self):
        ticket = self._waiting(self.today)
        ticket.status = TicketStatus.APPROVED
        ticket.approved_at = timezone.now()
        ticket.save(update_fields=["status", "approved_at", "updated_at"])
        payload = self.team()
        card, bucket = self.find(payload, f"ticket-{ticket.id}")
        self.assertEqual(bucket, "entries")
        self.assertEqual(card["day"], self.today.isoformat())
        self.assertEqual(payload["counts"]["waiting_customer"], 0)

    def test_the_chip_count_equals_its_rows(self):
        for n in range(3):
            self._waiting(self.today - n * DAY, title=f"Waiting {n}")
        payload = self.team()
        self.assertEqual(payload["counts"]["waiting_customer"], 3)
        self.assertEqual(len(payload["waiting_customer_entries"]), 3)
        self.assertFalse(payload["truncated"]["waiting_customer_entries"])


class PhantomClockTests(_P3Fixture, APITestCase):
    """A clock renders only when a real time exists — decided by the
    server, in the server's zone."""

    def _ticket_at(self, moment, end=None, *, title="Timed?"):
        ticket = self.make_ticket(title)
        ticket.scheduled_start_at = moment
        ticket.scheduled_end_at = end
        ticket.save(update_fields=["scheduled_start_at", "scheduled_end_at"])
        self.record_plan(ticket)
        self.make_slot(ticket, start=self.today)
        return ticket

    def test_a_day_only_plan_has_no_clock_on_card_or_detail(self):
        # THE UGLY SHAPE: local midnight, which is `2026-08-26 22:00Z`
        # for 27 August in Amsterdam — the instant the owner's browser
        # printed as "01:00 AM".
        ticket = self._ticket_at(_aware(self.today, 0))
        card, _bucket = self.find(self.team(), f"ticket-{ticket.id}")
        self.assertIsNone(card["start_time"])
        self.assertIsNone(card["end_time"])
        # ...and the DAY is the server's local day, not the UTC day.
        self.assertEqual(card["planned_start"], self.today.isoformat())
        self.client.force_authenticate(self.company_admin)
        detail = self.client.get(f"/api/tickets/{ticket.id}/").data
        self.assertIsNone(detail["scheduled_start_time"])
        self.assertIsNone(detail["scheduled_end_time"])
        self.assertEqual(detail["scheduled_start_day"], self.today.isoformat())

    def test_a_real_time_is_stated_as_a_clock(self):
        ticket = self._ticket_at(
            _aware(self.today, 9, 30), _aware(self.today, 12)
        )
        card, _bucket = self.find(self.team(), f"ticket-{ticket.id}")
        self.assertEqual(card["start_time"], "09:30")
        self.assertEqual(card["end_time"], "12:00")
        self.client.force_authenticate(self.company_admin)
        detail = self.client.get(f"/api/tickets/{ticket.id}/").data
        self.assertEqual(detail["scheduled_start_time"], "09:30")
        self.assertEqual(detail["scheduled_end_time"], "12:00")

    def test_a_slot_and_an_extra_work_answer_the_same_keys(self):
        ticket = self.make_ticket("Slot clock")
        slot = self.make_slot(ticket, start=self.today, end=self.today)
        ew = self.make_extra_work(
            "EW clock", preferred=self.today, assignee=self.worker
        )
        payload = self.own()
        slot_card, _ = self.find(payload, f"slot-{slot.id}")
        self.assertEqual(slot_card["start_time"], "09:00")
        self.assertEqual(slot_card["end_time"], "17:00")
        ew_card, _ = self.find(payload, f"ew-{ew.id}")
        self.assertIsNone(ew_card["start_time"])
        self.assertIsNone(ew_card["end_time"])


class PlannedAfterDeadlineTests(_P3Fixture, APITestCase):
    def _spawned(self, *, deadline, planned):
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Deadline job",
            description="x",
            deadline=deadline,
            status=ExtraWorkStatus.IN_PROGRESS,
        )
        ticket = self.make_ticket("Deadline job", scheduled=planned)
        ticket.extra_work_request = ew
        ticket.save(update_fields=["extra_work_request"])
        self.make_slot(ticket, start=planned)
        return ticket

    def test_a_plan_past_the_deadline_says_so_on_card_and_detail(self):
        ticket = self._spawned(
            deadline=self.today + 2 * DAY, planned=self.today + 5 * DAY
        )
        card, _ = self.find(self.team(), f"ticket-{ticket.id}")
        self.assertTrue(card["planned_after_deadline"])
        self.assertEqual(card["due_kind"], "DEADLINE")
        self.client.force_authenticate(self.company_admin)
        detail = self.client.get(f"/api/tickets/{ticket.id}/").data
        self.assertTrue(detail["planned_after_deadline"])

    def test_a_plan_inside_the_deadline_does_not(self):
        ticket = self._spawned(
            deadline=self.today + 5 * DAY, planned=self.today + 2 * DAY
        )
        card, _ = self.find(self.team(), f"ticket-{ticket.id}")
        self.assertFalse(card["planned_after_deadline"])
        self.client.force_authenticate(self.company_admin)
        detail = self.client.get(f"/api/tickets/{ticket.id}/").data
        self.assertFalse(detail["planned_after_deadline"])

    def test_a_phantom_date_is_no_plan_and_cannot_be_after_anything(self):
        ticket = self._spawned(
            deadline=self.today + 2 * DAY, planned=self.today + 5 * DAY
        )
        # Strip the person from behind the date: the P-1 phantom shape.
        ticket.status_history.filter(note__startswith="Schedule set:").delete()
        card, _ = self.find(self.team(), f"ticket-{ticket.id}")
        self.assertFalse(card["has_real_plan"])
        self.assertFalse(card["planned_after_deadline"])


class ReconciliationTests(_P3Fixture, APITestCase):
    """THE NUMBERS MUST RECONCILE. Every count equals the list it
    describes; the board's total is the sum of its parts; late is the
    sum of its three rungs; nothing is in two places at once."""

    def setUp(self):
        super().setUp()
        t = self.today
        self.make_slot(self.make_ticket("Planned today"), start=t)
        self.make_slot(
            self.make_ticket("Started later", TicketStatus.IN_PROGRESS),
            start=t + 30 * DAY,
        )
        self.make_slot(self.make_ticket("Rolled"), start=t - 5 * DAY)
        self.make_slot(
            self.make_ticket("Done", TicketStatus.CLOSED, scheduled=t - 2 * DAY),
            start=t - 2 * DAY,
            slot_status=StaffAssignmentSlotStatus.COMPLETED,
        )
        self.make_slot(
            self.make_ticket("Stuck", scheduled=t - 3 * DAY),
            start=t - 3 * DAY,
            slot_status=StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE,
        )
        self.make_slot(self.make_ticket("Undated"), start=None)
        self.make_slot(
            self.make_ticket("Spanning", scheduled=t - DAY, scheduled_end=t + DAY),
            start=t - DAY,
            end=t + DAY,
        )
        review = self.make_ticket(
            "Review", TicketStatus.WAITING_MANAGER_REVIEW, scheduled=t - 4 * DAY
        )
        review.manager_review_at = _aware(t - 4 * DAY, 15)
        review.save(update_fields=["manager_review_at"])
        self.make_slot(
            review, start=t - 4 * DAY, slot_status=StaffAssignmentSlotStatus.COMPLETED
        )
        waiting = self.make_ticket(
            "Waiting", TicketStatus.WAITING_CUSTOMER_APPROVAL, scheduled=t - DAY
        )
        self.make_slot(
            waiting, start=t - DAY, slot_status=StaffAssignmentSlotStatus.COMPLETED
        )
        # Job-level dates for the manager's board too.
        for title, days in (("Job today", 0), ("Job late", -6), ("Job upcoming", 20)):
            job = self.make_ticket(title, scheduled=t + days * DAY)
            self.make_slot(job, start=t + days * DAY)
        self.make_extra_work("EW now", preferred=t, assignee=self.worker)
        self.make_extra_work(
            "EW late",
            preferred=t - 20 * DAY,
            deadline=t - 4 * DAY,
            assignee=self.worker,
        )
        self.make_extra_work(
            "EW done",
            preferred=t - 2 * DAY,
            ew_status=ExtraWorkStatus.COMPLETED,
            assignee=self.worker,
        )
        self.make_extra_work(
            "EW cancelled",
            preferred=t,
            ew_status=ExtraWorkStatus.CANCELLED,
            assignee=self.worker,
        )
        self.make_extra_work("EW upcoming", preferred=t + 40 * DAY, assignee=self.worker)
        self.make_extra_work("EW undated", assignee=self.worker)

    def _reconcile(self, payload):
        counts = payload["counts"]
        self.assertFalse(any(payload["truncated"].values()))
        entries = payload["entries"]
        by_state = {
            STATE_OPEN: counts["open"],
            STATE_IN_PROGRESS: counts["in_progress"],
            STATE_DONE: counts["done"],
            STATE_BLOCKED: counts["blocked"],
        }
        # total = the sum of its parts, and = the cards on the board.
        self.assertEqual(counts["total"], sum(by_state.values()))
        self.assertEqual(counts["total"], len(entries))
        for state, number in by_state.items():
            self.assertEqual(
                number, sum(1 for e in entries if e["state"] == state), state
            )
        self.assertEqual(
            counts["overdue"], sum(1 for e in entries if e["is_overdue"])
        )
        # Every "elsewhere" number is exactly its list.
        for count_key, list_key in (
            ("overdue_all", "overdue_entries"),
            ("upcoming", "upcoming_entries"),
            ("undated", "undated_entries"),
            # P-7 S8 — parked work has its own list and number.
            ("parked", "parked_entries"),
            ("late", "late_entries"),
            ("stuck", "stuck_entries"),
            ("waiting_customer", "waiting_customer_entries"),
            # P-10 A2 — the manager's-check strip has its own number.
            ("review", "review_entries"),
        ):
            self.assertEqual(
                counts[count_key], len(payload[list_key]), count_key
            )
        # late = its three rungs.
        late = payload["late_entries"]
        levels = {1: 0, 2: 0, 3: 0}
        for e in late:
            self.assertIn(e["lateness"]["level"], levels)
            levels[e["lateness"]["level"]] += 1
        self.assertEqual(counts["late"], sum(levels.values()))
        # Every card is on a day of the week, and a visitor is on today.
        week = payload["week"]
        for e in entries:
            self.assertTrue(week["start"] <= e["day"] <= week["end"], e["key"])
            if e["placement"] in PLACEMENTS_NEEDING_A_REASON:
                self.assertEqual(e["day"], payload["today"], e["key"])
        # Nothing is in two places at once.
        on_board = {e["key"] for e in entries}
        for list_key in (
            "undated_entries",
            "parked_entries",
            "waiting_customer_entries",
            "review_entries",
        ):
            self.assertEqual(
                on_board & {e["key"] for e in payload[list_key]}, set(), list_key
            )
        # P-10 A2 — the review job is in the strip for a viewer who is
        # not responsible for it (both readers here), never in a column.
        self.assertGreater(counts["review"], 0)
        self.assertEqual(counts["review_mine"], 0)
        for e in entries:
            self.assertNotEqual(e["ticket_status"], TicketStatus.WAITING_MANAGER_REVIEW)
        self.assertGreater(counts["total"], 0)
        self.assertGreater(counts["late"], 0)
        self.assertGreater(counts["waiting_customer"], 0)
        self.assertGreater(counts["stuck"], 0)
        self.assertGreater(counts["undated"], 0)
        self.assertGreater(counts["upcoming"], 0)

    def test_the_managers_board_reconciles(self):
        self._reconcile(self.team())

    def test_the_workers_own_week_reconciles(self):
        self._reconcile(self.own())


class FullMatrixTests(_P3Fixture, APITestCase):
    """The owner's requested complete edge review: every status, placed.

    Today is pinned to a WEDNESDAY so "planned Monday" is a past day of
    the CURRENT week and "planned Friday" a future one — the two cases
    the rules distinguish — whatever day the suite runs on.
    """

    def setUp(self):
        super().setUp()
        real = timezone.localdate()
        self.wed = datetime.date.fromisocalendar(*real.isocalendar()[:2], 3)
        self.mon = self.wed - 2 * DAY
        self.fri = self.wed + 2 * DAY

    def _board(self, user, **params):
        with mock.patch("django.utils.timezone.localdate", return_value=self.wed):
            return self.get_plan(user, **params)

    def _ticket(self, status_v, planned, *, slot_status=StaffAssignmentSlotStatus.ASSIGNED):
        ticket = self.make_ticket(f"{status_v} {planned}", status_v, scheduled=planned)
        if status_v == TicketStatus.WAITING_MANAGER_REVIEW:
            ticket.manager_review_at = _aware(self.mon, 15)
            ticket.save(update_fields=["manager_review_at"])
        self.make_slot(ticket, start=planned, slot_status=slot_status)
        return ticket

    # What the manager's board says, per status: (bucket, placement, day)
    # for planned-Monday, planned-Friday, unplanned. `None` = nowhere.
    TICKET_MATRIX = {
        TicketStatus.OPEN: ("rolled", "planned_fri", "undated"),
        TicketStatus.ACKNOWLEDGED: ("rolled", "planned_fri", "undated"),
        TicketStatus.IN_PROGRESS: ("rolled", "planned_fri", "undated"),
        # P-7 S8 (owner ruling) — parked work leaves the "Not planned
        # yet" nag. P-11 A10 (owner ruling, over ticket 460 rolling
        # onto his today as late): an on-hold job lives ONLY in the On
        # hold fold, dated or not, until someone takes it off hold —
        # reverses this matrix's earlier "a parked job WITH a day keeps
        # its board placement".
        TicketStatus.ON_HOLD: ("parked", "parked", "parked"),
        TicketStatus.REOPENED_BY_ADMIN: ("rolled", "planned_fri", "undated"),
        # P-10 A1/A2 — reported done is not finished: in no column of
        # any week. A COMPANY_ADMIN is responsible for nothing by role,
        # so for this viewer every such job is a strip row; the
        # responsible manager's today card is pinned in
        # `test_p10_review_placement.py`.
        TicketStatus.WAITING_MANAGER_REVIEW: ("review_strip", "review_strip", "review_strip"),
        TicketStatus.WAITING_CUSTOMER_APPROVAL: ("waiting", "waiting", "waiting"),
        TicketStatus.APPROVED: ("settled_mon", "settled_fri", None),
        TicketStatus.CLOSED: ("settled_mon", "settled_fri", None),
        TicketStatus.REJECTED: ("blocked_mon", "blocked_fri", None),
        TicketStatus.CONVERTED_TO_EXTRA_WORK: ("blocked_mon", "blocked_fri", None),
    }

    def _assert_shape(self, shape, card, bucket, key):
        if shape is None:
            self.assertIsNone(card, f"{key}: expected nowhere, found in {bucket}")
            return
        self.assertIsNotNone(card, f"{key}: expected {shape}, found nowhere")
        if shape == "rolled":
            self.assertEqual((bucket, card["placement"]), ("entries", PLACEMENT_ROLLED), key)
            self.assertEqual(card["day"], self.wed.isoformat(), key)
            self.assertEqual(card["rolled_from"], self.mon.isoformat(), key)
            self.assertEqual(card["rolled_days"], 2, key)
            self.assertFalse(card["viewer_settled"], key)
        elif shape == "planned_fri":
            self.assertEqual((bucket, card["placement"]), ("entries", PLACEMENT_PLANNED), key)
            self.assertEqual(card["day"], self.fri.isoformat(), key)
            self.assertFalse(card["viewer_settled"], key)
        elif shape == "undated":
            self.assertEqual(bucket, "undated_entries", key)
        elif shape == "parked":
            self.assertEqual(bucket, "parked_entries", key)
            self.assertEqual(card["ticket_status"], TicketStatus.ON_HOLD, key)
        elif shape == "review":
            self.assertEqual((bucket, card["placement"]), ("entries", PLACEMENT_REVIEW), key)
            self.assertEqual(card["day"], self.wed.isoformat(), key)
            self.assertEqual(card["stuck_age_days"], 2, key)
            self.assertFalse(card["viewer_settled"], key)
        elif shape == "waiting":
            self.assertEqual(bucket, "waiting_customer_entries", key)
        elif shape == "review_strip":
            self.assertEqual(bucket, "review_entries", key)
            self.assertEqual(card["placement"], PLACEMENT_PLANNED, key)
        elif shape == "stuck":
            self.assertEqual(bucket, "stuck_entries", key)
        elif shape in ("settled_mon", "settled_fri", "blocked_mon", "blocked_fri"):
            day = self.mon if shape.endswith("_mon") else self.fri
            self.assertEqual((bucket, card["placement"]), ("entries", PLACEMENT_PLANNED), key)
            self.assertEqual(card["day"], day.isoformat(), key)
            self.assertTrue(card["viewer_settled"], key)
            self.assertEqual(
                card["state"],
                STATE_BLOCKED if shape.startswith("blocked") else STATE_DONE,
                key,
            )
            self.assertFalse(card["is_overdue"], key)
            self.assertIsNone(card["days_until_due"], key)
        else:
            self.fail(shape)

    def test_every_ticket_status_is_placed_as_the_matrix_says(self):
        # A new status fails HERE, before it renders as a blank card.
        self.assertEqual(
            set(self.TICKET_MATRIX), {c for c, _ in TicketStatus.choices}
        )
        made = {}
        for status_v in self.TICKET_MATRIX:
            made[status_v] = [
                self._ticket(status_v, self.mon),
                self._ticket(status_v, self.fri),
                self._ticket(status_v, None),
            ]
        payload = self._board(self.company_admin, scope="company")
        for status_v, shapes in self.TICKET_MATRIX.items():
            for ticket, shape in zip(made[status_v], shapes):
                key = f"ticket-{ticket.id}"
                card, bucket = self.find(payload, key)
                with self.subTest(status=status_v, shape=shape):
                    self._assert_shape(shape, card, bucket, f"{status_v}/{shape}")
        # The board's chips describe exactly what it holds.
        self.assertEqual(payload["counts"]["total"], len(payload["entries"]))
        self.assertEqual(payload["counts"]["waiting_customer"], 3)

    # The worker's own board, per SLOT status on a live ticket.
    SLOT_MATRIX = {
        StaffAssignmentSlotStatus.ASSIGNED: ("rolled", "planned_fri", "undated"),
        StaffAssignmentSlotStatus.COMPLETED: ("settled_mon", "settled_fri", None),
        # An unable slot with no day is still STUCK: the follow-up list
        # is the one place a job that stopped without a date can be seen.
        StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE: ("blocked_mon", "blocked_fri", "stuck"),
        StaffAssignmentSlotStatus.CANCELLED: ("blocked_mon", "blocked_fri", None),
    }

    def test_every_slot_status_is_placed_as_the_matrix_says(self):
        self.assertEqual(
            set(self.SLOT_MATRIX),
            {c for c, _ in StaffAssignmentSlotStatus.choices},
        )
        made = {}
        for slot_status in self.SLOT_MATRIX:
            made[slot_status] = []
            for planned in (self.mon, self.fri, None):
                ticket = self.make_ticket(f"slot {slot_status} {planned}")
                made[slot_status].append(
                    self.make_slot(ticket, start=planned, slot_status=slot_status)
                )
        payload = self._board(self.worker)
        for slot_status, shapes in self.SLOT_MATRIX.items():
            for slot, shape in zip(made[slot_status], shapes):
                card, bucket = self.find(payload, f"slot-{slot.id}")
                with self.subTest(slot_status=slot_status, shape=shape):
                    self._assert_shape(shape, card, bucket, f"{slot_status}/{shape}")
        # An unable slot with nobody else on the job is STUCK, and says so.
        stuck_keys = {e["key"] for e in payload["stuck_entries"]}
        unable = made[StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE]
        self.assertTrue(all(f"slot-{s.id}" in stuck_keys for s in unable))

    # An extra work with a crew and no spawned slot, on the manager's
    # board, per extra-work status. Placed by the customer's WISH date
    # (`preferred_date`) — a wish is captioned as one on the card.
    EW_MATRIX = {
        ExtraWorkStatus.REQUESTED: ("rolled", "planned_fri", "undated"),
        ExtraWorkStatus.UNDER_REVIEW: ("rolled", "planned_fri", "undated"),
        ExtraWorkStatus.PRICING_PROPOSED: ("rolled", "planned_fri", "undated"),
        ExtraWorkStatus.CUSTOMER_APPROVED: ("rolled", "planned_fri", "undated"),
        ExtraWorkStatus.IN_PROGRESS: ("rolled", "planned_fri", "undated"),
        ExtraWorkStatus.COMPLETED: ("settled_mon", "settled_fri", None),
        ExtraWorkStatus.CUSTOMER_REJECTED: ("blocked_mon", "blocked_fri", None),
        ExtraWorkStatus.CANCELLED: ("blocked_mon", "blocked_fri", None),
    }

    def test_every_extra_work_status_is_placed_as_the_matrix_says(self):
        self.assertEqual(
            set(self.EW_MATRIX), {c for c, _ in ExtraWorkStatus.choices}
        )
        made = {}
        for ew_status in self.EW_MATRIX:
            made[ew_status] = [
                self.make_extra_work(
                    f"ew {ew_status} {planned}",
                    preferred=planned,
                    ew_status=ew_status,
                    assignee=self.worker,
                )
                for planned in (self.mon, self.fri, None)
            ]
        payload = self._board(self.company_admin, scope="company")
        for ew_status, shapes in self.EW_MATRIX.items():
            for ew, shape in zip(made[ew_status], shapes):
                card, bucket = self.find(payload, f"ew-{ew.id}")
                with self.subTest(ew_status=ew_status, shape=shape):
                    self._assert_shape(shape, card, bucket, f"{ew_status}/{shape}")
                    # Placed by the customer's WISH, and captioned as one;
                    # an undated request has no wish to caption.
                    if card is not None and card["planned_start"]:
                        self.assertEqual(card["plan_source"], "CUSTOMER_WISH")
