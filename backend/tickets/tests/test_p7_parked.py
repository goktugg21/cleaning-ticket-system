"""P-7 S8 — parked work leaves the "Not planned yet" nag.

The owner's ruling on P-6's open decision: a ticket parked through
triage (ON_HOLD, with a reason) is not "not planned yet" — somebody
decided about it. It leaves `undated_entries` and `counts.undated`,
and lives in its own quiet list, `parked_entries` / `counts.parked`,
carrying the reason it was parked for (the note on the ON_HOLD leg of
its history).

P-11 A10 amends the second half of the ruling: a parked job WITH a day
no longer keeps its board placement. The owner's ticket 460 was on hold
and still rolled onto his today as late; now an on-hold job, dated or
not, lives ONLY in the On hold fold until someone takes it off hold
(`ParkedIsOffTheBoardTests`; the §D.15 matrix in
`test_p3_schedule_truth.py` says the same).
"""
from __future__ import annotations

import datetime

from rest_framework import status
from rest_framework.test import APITestCase

from tickets.models import TicketStatus
from tickets.tests.test_sprint179a_work_plan import WorkPlanFixture

TRIAGE_URL = "/api/tickets/bulk-triage/"


class ParkedLeavesTheNagTests(WorkPlanFixture, APITestCase):
    def _park(self, ticket, reason):
        self.client.force_authenticate(self.company_admin)
        response = self.client.post(
            TRIAGE_URL,
            {"ticket_ids": [ticket.id], "action": "park", "reason": reason},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["succeeded"], 1, response.data)

    def _board(self):
        return self.get_plan(self.company_admin, scope="company")

    def _keys(self, payload, bucket):
        return {entry["key"] for entry in payload[bucket]}

    def test_a_parked_undated_ticket_moves_to_the_parked_list_with_its_reason(self):
        waiting = self.make_ticket("still waiting", TicketStatus.OPEN)
        parked = self.make_ticket("junk from June", TicketStatus.OPEN)
        self.make_slot(waiting)
        self.make_slot(parked)
        before = self._board()
        self.assertEqual(
            self._keys(before, "undated_entries"),
            {f"ticket-{waiting.id}", f"ticket-{parked.id}"},
        )
        self.assertEqual(before["counts"]["undated"], 2)
        self.assertEqual(before["counts"]["parked"], 0)
        self.assertEqual(before["parked_entries"], [])

        self._park(parked, "test entry — owner's junk")

        after = self._board()
        self.assertEqual(self._keys(after, "undated_entries"), {f"ticket-{waiting.id}"})
        self.assertEqual(after["counts"]["undated"], 1)
        self.assertEqual(self._keys(after, "parked_entries"), {f"ticket-{parked.id}"})
        self.assertEqual(after["counts"]["parked"], 1)
        row = after["parked_entries"][0]
        self.assertEqual(row["ticket_status"], TicketStatus.ON_HOLD)
        self.assertEqual(row["parked_reason"], "test entry — owner's junk")
        # The nag's rows carry no reason; only the parked list does.
        self.assertIsNone(after["undated_entries"][0]["parked_reason"])
        # Limits and truncation flags name the new list like every other.
        self.assertIn("parked_entries", after["limits"])
        self.assertFalse(after["truncated"]["parked_entries"])

    def test_the_latest_parking_reason_wins(self):
        ticket = self.make_ticket("parked twice", TicketStatus.OPEN)
        self.make_slot(ticket)
        self._park(ticket, "first reason")
        # A later leg into ON_HOLD (written the way `apply_transition`
        # writes one) carries the reason the drawer shows.
        from tickets.models import TicketStatusHistory

        TicketStatusHistory.objects.create(
            ticket=ticket,
            old_status=TicketStatus.ACKNOWLEDGED,
            new_status=TicketStatus.ON_HOLD,
            note="second reason",
            changed_by=self.company_admin,
        )
        row = self._board()["parked_entries"][0]
        self.assertEqual(row["parked_reason"], "second reason")

    def test_a_parked_job_with_a_day_is_in_the_fold_too(self):
        # P-11 A10 — REVERSES this test's earlier assertion ("a parked
        # job with a day stays on the board"): the owner's ticket 460
        # was deliberately paused and still rolled onto his today as
        # late. Dated or not, an on-hold job lives ONLY in the fold.
        ticket = self.make_ticket("parked but planned", TicketStatus.OPEN, scheduled=self.today)
        self.make_slot(ticket, start=self.today)
        self._park(ticket, "on hold, keeps its day")
        payload = self._board()
        self.assertNotIn(f"ticket-{ticket.id}", {e["key"] for e in payload["entries"]})
        self.assertEqual(payload["counts"]["parked"], 1)
        self.assertEqual(
            payload["parked_entries"][0]["parked_reason"], "on hold, keeps its day"
        )

    def test_a_parked_job_planned_last_week_does_not_roll_onto_today_or_the_late_strip(self):
        # The owner's ticket 460, reproduced: on hold with a past
        # planned day. Before P-11 A10 it rolled onto today as late.
        last_week = self.today - datetime.timedelta(days=7)
        ticket = self.make_ticket(
            "parked last week", TicketStatus.OPEN, scheduled=last_week
        )
        self.make_slot(ticket, start=last_week)
        self._park(ticket, "paused on purpose")
        payload = self._board()
        self.assertNotIn(f"ticket-{ticket.id}", {e["key"] for e in payload["entries"]})
        self.assertNotIn(
            f"ticket-{ticket.id}", {e["key"] for e in payload["late_entries"]}
        )
        self.assertNotIn(
            f"ticket-{ticket.id}", {e["key"] for e in payload["overdue_entries"]}
        )
        self.assertEqual(
            {e["key"] for e in payload["parked_entries"]}, {f"ticket-{ticket.id}"}
        )
        self.assertEqual(payload["counts"]["parked"], 1)

    def test_the_workers_dated_parked_slot_is_in_the_fold_not_a_column(self):
        last_week = self.today - datetime.timedelta(days=7)
        ticket = self.make_ticket(
            "parked, mine, dated", TicketStatus.OPEN, scheduled=last_week
        )
        slot = self.make_slot(ticket, user=self.worker, start=last_week)
        self._park(ticket, "paused")
        own = self.get_plan(self.worker)
        board_tickets = {e["ticket_id"] for e in own["entries"]}
        self.assertNotIn(ticket.id, board_tickets)
        self.assertNotIn(
            ticket.id, {e["ticket_id"] for e in own["late_entries"]}
        )
        parked = [e for e in own["parked_entries"] if e["ticket_id"] == ticket.id]
        self.assertEqual(len(parked), 1, own["parked_entries"])
        self.assertEqual(parked[0]["parked_reason"], "paused")
        self.assertEqual(parked[0]["source_id"], slot.id)

    def test_the_workers_own_week_mirrors_the_rule(self):
        ticket = self.make_ticket("parked, mine", TicketStatus.OPEN)
        self.make_slot(ticket, user=self.worker)
        self._park(ticket, "later")
        own = self.get_plan(self.worker)
        self.assertEqual(own["counts"]["undated"], 0)
        self.assertEqual(own["counts"]["parked"], 1)
        self.assertEqual(len(own["parked_entries"]), 1)
        self.assertEqual(own["parked_entries"][0]["parked_reason"], "later")
