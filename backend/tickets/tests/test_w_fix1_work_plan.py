"""W-FIX1 A1 + E2 (audit F1, F20) — one job, one row; today holds today.

A1. An extra work that has spawned a ticket somebody holds a live slot
    on is represented by that slot row and by nothing else: no second
    row in the undated lane, no second "Plan for today" door. And a
    slot whose TICKET is already scheduled — through its own date, the
    ticket's date, or a colleague's slot — is not "undated" work.

E2 (AMENDED by W-PLANTRUTH §1b — see the rewritten test below: today
    also holds work planned for a day that has passed and is not done,
    stamped ROLLED with the day it came from).
    Today's column holds work planned for today. Started
    work that is not planned this week lives in the strips that already
    existed, marked with why it is there, and is not copied onto today.
"""
from __future__ import annotations

import datetime

from rest_framework.test import APITestCase

from tickets.models import StaffAssignmentSlotStatus, TicketStatus
from tickets.work_plan import PLACEMENT_OVERDUE, PLACEMENT_PLANNED, STATE_IN_PROGRESS

from .test_sprint179a_work_plan import KIND_EXTRA_WORK, KIND_TICKET_SLOT, WorkPlanFixture


class OneJobOneRowTests(WorkPlanFixture, APITestCase):
    def _spawn(self, extra_work, title="Spawned"):
        ticket = self.make_ticket(title)
        ticket.extra_work_request = extra_work
        ticket.save(update_fields=["extra_work_request"])
        return ticket

    def test_a_spawned_ticket_with_a_live_slot_silences_the_extra_work_row(self):
        ew = self.make_extra_work("yy", assignee=self.worker)
        ticket = self._spawn(ew, "yy")
        slot = self.make_slot(ticket, start=None)

        payload = self.get_plan(self.worker)

        self.assertIsNone(self.entry(payload, f"ew-{ew.id}", "undated_entries"))
        self.assertIsNone(self.entry(payload, f"ew-{ew.id}"))
        self.assertIsNotNone(
            self.entry(payload, f"slot-{slot.id}", "undated_entries"),
            payload["undated_entries"],
        )
        self.assertEqual(payload["counts"]["undated"], 1)

    def test_the_same_rule_holds_for_the_team_view(self):
        ew = self.make_extra_work("yy", assignee=self.worker)
        ticket = self._spawn(ew, "yy")
        slot = self.make_slot(ticket, start=self.today)

        payload = self.get_plan(self.super_admin, scope="company")

        keys = {e["key"] for e in payload["entries"]}
        self.assertIn(f"slot-{slot.id}", keys)
        self.assertNotIn(f"ew-{ew.id}", keys)
        self.assertNotIn(f"ew-{ew.id}", {e["key"] for e in payload["undated_entries"]})

    def test_a_spawned_ticket_nobody_holds_still_shows_as_the_extra_work(self):
        """A ticket with no crew has no slot row to speak for the job, so
        the extra-work row stays — the job must not vanish."""
        ew = self.make_extra_work("Nobody on it yet", assignee=self.worker)
        self._spawn(ew)

        payload = self.get_plan(self.worker)

        self.assertIsNotNone(
            self.entry(payload, f"ew-{ew.id}", "undated_entries"),
            payload["undated_entries"],
        )

    def test_a_cancelled_slot_does_not_silence_the_extra_work_row(self):
        ew = self.make_extra_work("Taken off", assignee=self.worker)
        ticket = self._spawn(ew)
        self.make_slot(
            ticket, start=None, slot_status=StaffAssignmentSlotStatus.CANCELLED
        )

        payload = self.get_plan(self.worker)

        self.assertIsNotNone(
            self.entry(payload, f"ew-{ew.id}", "undated_entries")
        )


class UndatedIsAJobLevelFactTests(WorkPlanFixture, APITestCase):
    def test_a_slot_with_no_day_is_undated_even_when_the_ticket_has_one(self):
        """W-PLANTRUTH §1a — the ticket-level date is a DIFFERENT FACT.

        W-FIX1 A1 let a ticket's own `scheduled_start_at` take a slot out
        of this lane. The owner's ruling withdraws that: the board is
        placed by the planned day of the WORK, and a job whose people
        have no day is work nobody has planned — whatever the ticket
        header says. It belongs here until somebody gives it a day.
        A colleague's DATED slot still takes it out (the next test):
        that is a real planned day for the job.
        """
        ticket = self.make_ticket("Ticket has a date")
        ticket.scheduled_start_at = self.make_slot(
            self.make_ticket("tmp"), start=self.today
        ).scheduled_start_at
        ticket.save(update_fields=["scheduled_start_at"])
        slot = self.make_slot(ticket, start=None)

        payload = self.get_plan(self.worker)

        self.assertIsNotNone(
            self.entry(payload, f"slot-{slot.id}", "undated_entries"),
            payload["undated_entries"],
        )
        self.assertEqual(payload["counts"]["undated"], 1)

    def test_a_colleagues_dated_slot_takes_the_job_out_of_the_lane(self):
        colleague = self.make_user("colleague-fix1@example.com", "STAFF")
        ticket = self.make_ticket("Two people, one dated")
        self.make_slot(ticket, user=colleague, start=self.today)
        mine = self.make_slot(ticket, start=None)

        payload = self.get_plan(self.super_admin, scope="company")

        self.assertIsNone(self.entry(payload, f"slot-{mine.id}", "undated_entries"))
        self.assertEqual(payload["counts"]["undated"], 0)
        # The count and the rows still agree — that was Sprint 181's rule.
        self.assertEqual(len(payload["undated_entries"]), payload["counts"]["undated"])

    def test_a_truly_undated_job_is_still_in_the_lane(self):
        ticket = self.make_ticket("Nobody planned this")
        slot = self.make_slot(ticket, start=None)

        payload = self.get_plan(self.worker)

        self.assertIsNotNone(self.entry(payload, f"slot-{slot.id}", "undated_entries"))
        self.assertEqual(payload["counts"]["undated"], 1)


class TodayHoldsTodayTests(WorkPlanFixture, APITestCase):
    def test_overdue_work_rolls_onto_today_and_is_still_in_the_strip(self):
        """W-PLANTRUTH §1b REVERSES HALF OF W-FIX1 E2, deliberately.

        E2 was right that today's column must not be a catch-all of
        every started and late job — that column read "20 jobs" and held
        June's work. It was wrong about where UNFINISHED work planned
        for a day that has passed should go: nowhere is not an answer,
        and leaving it in its old column is the "it just sits in the
        past" the owner objected to. It rolls onto today, marked with
        the day it was planned for.

        The overdue STRIP is untouched: "past its deadline" is a
        different question from "its planned day has gone", and both
        still get their own answer.
        """
        late = self.make_extra_work(
            "Gutter clearing",
            preferred=self.today - datetime.timedelta(days=14),
            deadline=self.today - datetime.timedelta(days=3),
            assignee=self.worker,
        )
        payload = self.get_plan(self.worker)

        card = self.entry(payload, f"ew-{late.id}")
        self.assertIsNotNone(card, payload["entries"])
        self.assertEqual(card["day"], self.today.isoformat())
        self.assertEqual(card["placement"], "ROLLED")
        self.assertEqual(
            card["rolled_from"],
            (self.today - datetime.timedelta(days=14)).isoformat(),
            "the card must name the day that placed it",
        )
        self.assertEqual(card["rolled_days"], 14)

        strip = self.entry(payload, f"ew-{late.id}", "overdue_entries")
        self.assertIsNotNone(strip, payload["overdue_entries"])
        self.assertEqual(strip["placement"], PLACEMENT_OVERDUE)
        self.assertTrue(strip["is_overdue"])
        self.assertEqual(strip["overdue_days"], 3)
        self.assertEqual(payload["counts"]["overdue_all"], 1)

    def test_a_started_job_planned_for_later_stays_in_its_own_week(self):
        planned_day = self.today + datetime.timedelta(days=21)
        ticket = self.make_ticket("Deep clean", TicketStatus.IN_PROGRESS)
        slot = self.make_slot(ticket, start=planned_day)

        this_week = self.get_plan(self.worker)
        self.assertIsNone(self.entry(this_week, f"slot-{slot.id}"), this_week["entries"])

        iso = planned_day.isocalendar()
        its_week = self.get_plan(self.worker, week=f"{iso[0]}-W{iso[1]:02d}")
        entry = self.entry(its_week, f"slot-{slot.id}")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["placement"], PLACEMENT_PLANNED)
        self.assertEqual(entry["state"], STATE_IN_PROGRESS)
        self.assertEqual(entry["day"], planned_day.isoformat())

    def test_work_planned_for_today_is_on_today(self):
        ticket = self.make_ticket("Today's job")
        slot = self.make_slot(ticket, start=self.today)

        payload = self.get_plan(self.worker)
        entry = self.entry(payload, f"slot-{slot.id}")

        self.assertIsNotNone(entry)
        self.assertEqual(entry["placement"], PLACEMENT_PLANNED)
        self.assertEqual(entry["day"], self.today.isoformat())
        self.assertEqual(payload["counts"]["total"], 1)

    def test_a_job_planned_this_week_that_is_also_late_is_marked_where_it_sits(self):
        """Planned placement is the job's home; being late is a flag on
        the card, not a second placement."""
        late = self.make_extra_work(
            "Planned and late",
            preferred=self.today,
            deadline=self.today - datetime.timedelta(days=1),
            assignee=self.worker,
        )
        payload = self.get_plan(self.worker)
        entry = self.entry(payload, f"ew-{late.id}")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["placement"], PLACEMENT_PLANNED)
        self.assertTrue(entry["is_overdue"])
        self.assertEqual(payload["counts"]["overdue"], 1)

    def test_both_kinds_answer_the_same_key_set(self):
        """The entry shape did not change — only who is placed where."""
        ticket = self.make_ticket("A")
        slot = self.make_slot(ticket, start=self.today)
        ew = self.make_extra_work("B", preferred=self.today, assignee=self.worker)
        payload = self.get_plan(self.worker)
        slot_entry = self.entry(payload, f"slot-{slot.id}")
        ew_entry = self.entry(payload, f"ew-{ew.id}")
        self.assertEqual(slot_entry["kind"], KIND_TICKET_SLOT)
        self.assertEqual(ew_entry["kind"], KIND_EXTRA_WORK)
        self.assertEqual(set(slot_entry), set(ew_entry))
