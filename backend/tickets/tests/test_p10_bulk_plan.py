"""
P-10 A5 / A6 — planning from the "Not planned yet" strip, pinned.

A6 (reproduced on crmtest, 2026-09-01): the strip's "Plan it" on an
EXTRA-WORK row writes `provider_planned_date` (`POST /extra-work/bulk-
dates/`, 200), the request's own `display_phase` turns SCHEDULED — and
the board kept the row in "Not planned yet" with the count unmoved,
because every extra-work predicate read `preferred_date` (the customer's
wish) and nothing else. The board now reads the provider's plan first
(`_with_ew_dates`), so a saved row leaves the strip on the next read,
whichever door planned it.

A5 — "Plan N" is the same two doors, once per row: a refusal on one row
is that row's, and the other rows land.
"""
from __future__ import annotations

import datetime

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from extra_work.models import ExtraWorkStatus
from tickets.tests.test_sprint179a_work_plan import WorkPlanFixture

DAY = datetime.timedelta(days=1)


BUCKETS = (
    "entries",
    "undated_entries",
    "parked_entries",
    "waiting_customer_entries",
    "review_entries",
    "stuck_entries",
    "overdue_entries",
    "upcoming_entries",
    "late_entries",
)


class ExtraWorkPlanLeavesTheStripTests(WorkPlanFixture, APITestCase):
    def _undated_keys(self, payload):
        return {e["key"] for e in payload["undated_entries"]}

    def _card(self, payload, key):
        """The entry on the BOARD, or a failure that says where it is."""
        for entry in payload["entries"]:
            if entry["key"] == key:
                return entry
        elsewhere = [b for b in BUCKETS if any(e["key"] == key for e in payload.get(b, []))]
        self.fail(f"{key} not on the board; found in {elsewhere}; counts={payload['counts']}")

    def test_the_provider_plan_takes_an_extra_work_out_of_not_planned_yet(self):
        extra_work = self.make_extra_work(
            "Agreed, nobody said when",
            ew_status=ExtraWorkStatus.CUSTOMER_APPROVED,
            assignee=self.worker,
        )
        before = self.get_plan(self.company_admin, scope="company")
        self.assertIn(f"ew-{extra_work.id}", self._undated_keys(before))
        undated_before = before["counts"]["undated"]

        # The strip's own door.
        self.client.force_authenticate(self.company_admin)
        response = self.client.post(
            "/api/extra-work/bulk-dates/",
            {"requests": [extra_work.id], "provider_planned_date": self.today.isoformat()},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        after = self.get_plan(self.company_admin, scope="company")
        self.assertNotIn(f"ew-{extra_work.id}", self._undated_keys(after))
        self.assertEqual(after["counts"]["undated"], undated_before - 1)
        card = self._card(after, f"ew-{extra_work.id}")
        self.assertEqual(card["day"], self.today.isoformat())
        self.assertEqual(card["planned_start"], self.today.isoformat())
        # A plan a PERSON made, not the customer's wish.
        self.assertEqual(card["plan_source"], "PROVIDER_PLAN")
        self.assertTrue(card["has_real_plan"])
        # The counts describe the board that shows it.
        self.assertEqual(after["counts"]["total"], len(after["entries"]))

    def test_the_provider_plan_wins_over_the_customers_wish_on_the_board(self):
        extra_work = self.make_extra_work(
            "Wished Monday, planned Thursday",
            preferred=self.today - 3 * DAY,
            ew_status=ExtraWorkStatus.CUSTOMER_APPROVED,
            assignee=self.worker,
        )
        extra_work.provider_planned_date = self.today + 2 * DAY
        extra_work.save(update_fields=["provider_planned_date"])
        payload = self.get_plan(self.company_admin, scope="company")
        card = self._card(payload, f"ew-{extra_work.id}")
        self.assertEqual(card["day"], (self.today + 2 * DAY).isoformat())
        self.assertEqual(card["placement"], "PLANNED")
        self.assertEqual(card["plan_source"], "PROVIDER_PLAN")
        # Not rolled: the plan is ahead, whatever the wish said.
        self.assertIsNone(card["rolled_from"])
        self.assertEqual(payload["counts"]["total"], len(payload["entries"]))


class PlanManyIsOneDoorPerRowTests(WorkPlanFixture, APITestCase):
    """A5 — the dialog writes each row through the single-row door."""

    def test_each_row_answers_for_itself(self):
        first = self.make_ticket("Row one")
        self.make_slot(first, start=None)
        second = self.make_ticket("Row two")
        self.make_slot(second, start=None)
        self.client.force_authenticate(self.company_admin)
        ok = self.client.post(
            f"/api/tickets/{first.id}/schedule/",
            {"scheduled_start_at": f"{self.today.isoformat()}T00:00:00"},
            format="json",
        )
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.data)
        refused = self.client.post(
            f"/api/tickets/{second.id}/schedule/",
            {"scheduled_start_at": "not-a-moment"},
            format="json",
        )
        self.assertEqual(refused.status_code, status.HTTP_400_BAD_REQUEST)
        payload = self.get_plan(self.company_admin, scope="company")
        keys = {e["key"] for e in payload["undated_entries"]}
        self.assertNotIn(f"ticket-{first.id}", keys)
        self.assertIn(f"ticket-{second.id}", keys)
        on_board = {e["key"] for e in payload["entries"]}
        self.assertIn(f"ticket-{first.id}", on_board)
        # The people moved with the job (ruling 12(e), the default).
        slot = first.staff_assignments.get()
        self.assertEqual(timezone.localtime(slot.scheduled_start_at).date(), self.today)


class LatenessReadsTheProviderPlanTests(WorkPlanFixture, APITestCase):
    """P-11 A11 — the LADDER reads the provider's plan too.

    The P-10 leftover: A6 moved every board predicate onto
    `provider_planned_date`, but `lateness_index` still assessed the
    customer's wish — a provider-planned-and-missed job was never late,
    and a wish-dated one was measured against a date nobody promised.
    """

    def test_a_provider_planned_extra_work_past_its_day_is_late(self):
        extra_work = self.make_extra_work(
            "promised last week", assignee=self.worker
        )
        extra_work.provider_planned_date = self.today - 3 * DAY
        extra_work.save(update_fields=["provider_planned_date"])
        payload = self.get_plan(self.company_admin, scope="company")
        rows = [
            r
            for r in payload["late_entries"]
            if r["extra_work_id"] == extra_work.id
        ]
        self.assertEqual(len(rows), 1, payload["late_entries"])
        self.assertEqual(rows[0]["lateness"]["level"], 1)
        self.assertEqual(rows[0]["lateness"]["planned_days_late"], 3)

    def test_a_future_provider_plan_clears_a_past_wish(self):
        # The plan wins over the wish in the ladder exactly as it does
        # on the board: a job promised for the day after tomorrow is
        # not late, however old the customer's original wish.
        extra_work = self.make_extra_work(
            "old wish, fresh promise",
            preferred=self.today - 30 * DAY,
            assignee=self.worker,
        )
        extra_work.provider_planned_date = self.today + 2 * DAY
        extra_work.save(update_fields=["provider_planned_date"])
        payload = self.get_plan(self.company_admin, scope="company")
        self.assertEqual(
            [
                r
                for r in payload["late_entries"]
                if r["extra_work_id"] == extra_work.id
            ],
            [],
        )
