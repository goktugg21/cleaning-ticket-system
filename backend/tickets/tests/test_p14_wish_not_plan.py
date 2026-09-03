"""
P-14 A5 — A WISH DATE IS NOT A PLAN, pinned.

P-1 found phantom plans; P-10 A6 put the provider's committed day first
but kept the customer's `preferred_date` as a placement fallback — and
web-Claude's first P-14 pass found the reopened defect: an extra work
with only the customer's wished date and no provider plan sat in
today's column wearing the badge "Not planned yet" (the card and the
badge disagreed about the same fact).

The ruling: no provider plan → the "Not planned yet" strip, full stop.
The wish may seed a card's details, never its column. These tests pin
the board for exactly the fixture the finding names: a wish date, no
plan.
"""
from __future__ import annotations

import datetime

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


class WishDateIsNotAPlanTests(WorkPlanFixture, APITestCase):
    def _buckets_holding(self, payload, key):
        return [
            b for b in BUCKETS if any(e["key"] == key for e in payload.get(b, []))
        ]

    def test_a_wish_for_today_is_in_the_strip_not_in_todays_column(self):
        extra_work = self.make_extra_work(
            "Wished for today, planned by nobody",
            preferred=self.today,
            ew_status=ExtraWorkStatus.CUSTOMER_APPROVED,
            assignee=self.worker,
        )
        payload = self.get_plan(self.company_admin, scope="company")
        key = f"ew-{extra_work.id}"
        # Not in any column of the week.
        self.assertNotIn(
            key,
            {e["key"] for e in payload["entries"]},
            "a wished-but-unplanned request must not sit in a column",
        )
        # In the "Not planned yet" strip, and nowhere else.
        self.assertEqual(self._buckets_holding(payload, key), ["undated_entries"])
        row = next(e for e in payload["undated_entries"] if e["key"] == key)
        self.assertFalse(row["has_real_plan"])
        # The counts describe what is shown.
        self.assertEqual(payload["counts"]["total"], len(payload["entries"]))

    def test_a_future_wish_is_not_upcoming_either(self):
        extra_work = self.make_extra_work(
            "Wished for next week, planned by nobody",
            preferred=self.today + 9 * DAY,
            ew_status=ExtraWorkStatus.CUSTOMER_APPROVED,
            assignee=self.worker,
        )
        payload = self.get_plan(self.company_admin, scope="company")
        key = f"ew-{extra_work.id}"
        self.assertEqual(self._buckets_holding(payload, key), ["undated_entries"])

    def test_the_workers_own_board_files_the_wish_in_the_strip_too(self):
        extra_work = self.make_extra_work(
            "The worker's wished-only request",
            preferred=self.today,
            ew_status=ExtraWorkStatus.CUSTOMER_APPROVED,
            assignee=self.worker,
        )
        payload = self.get_plan(self.worker)
        key = f"ew-{extra_work.id}"
        self.assertNotIn(key, {e["key"] for e in payload["entries"]})
        self.assertIn(
            key, {e["key"] for e in payload["undated_entries"]}
        )

    def test_a_provider_plan_still_places_the_board(self):
        extra_work = self.make_extra_work(
            "Wished Monday, planned Thursday",
            preferred=self.today - 3 * DAY,
            ew_status=ExtraWorkStatus.CUSTOMER_APPROVED,
            assignee=self.worker,
        )
        extra_work.provider_planned_date = self.today
        extra_work.save(update_fields=["provider_planned_date"])
        payload = self.get_plan(self.company_admin, scope="company")
        key = f"ew-{extra_work.id}"
        card = next(e for e in payload["entries"] if e["key"] == key)
        self.assertEqual(card["day"], self.today.isoformat())
        self.assertEqual(card["plan_source"], "PROVIDER_PLAN")
        self.assertEqual(self._buckets_holding(payload, key), ["entries"])


class SpawnedTicketWishTests(WorkPlanFixture, APITestCase):
    """P-15 §0.4 — the same law for the TICKET the extra work spawned.

    P-14 A5 stopped the wish placing EXTRA-WORK rows; a spawned ticket
    with only a `preferred_date` was still placed by it through
    `tickets/job_dates.py`. One placement law, no exceptions: the
    wish-only ticket sits in the Not-planned strip wearing the wish as
    a fact ("Wished for {date}" — `wished_day`).
    """

    def _buckets_holding(self, payload, key):
        return [
            b for b in BUCKETS if any(e["key"] == key for e in payload.get(b, []))
        ]

    def _spawned_wish_ticket(self, *, wished):
        extra_work = self.make_extra_work(
            "The wish behind the spawn",
            preferred=wished,
            ew_status=ExtraWorkStatus.IN_PROGRESS,
        )
        ticket = self.make_ticket("Spawned execution")
        ticket.extra_work_request = extra_work
        ticket.save(update_fields=["extra_work_request"])
        # The company board lists staffed tickets (`_ticket_source`).
        self.make_slot(ticket)
        return ticket

    def test_a_spawned_ticket_is_not_placed_by_the_wish(self):
        wished = self.today + 2 * DAY
        ticket = self._spawned_wish_ticket(wished=wished)
        payload = self.get_plan(self.company_admin, scope="company")
        key = f"ticket-{ticket.id}"
        self.assertEqual(self._buckets_holding(payload, key), ["undated_entries"])
        row = next(e for e in payload["undated_entries"] if e["key"] == key)
        self.assertIsNone(row["planned_start"])
        self.assertFalse(row["has_real_plan"])
        self.assertEqual(row["plan_source"], "CUSTOMER_WISH")
        self.assertEqual(row["wished_day"], wished.isoformat())

    def test_the_workers_own_slot_states_the_wish_too(self):
        wished = self.today + 2 * DAY
        ticket = self._spawned_wish_ticket(wished=wished)
        payload = self.get_plan(self.worker)
        key = f"slot-{ticket.staff_assignments.get().id}"
        row = next(e for e in payload["undated_entries"] if e["key"] == key)
        self.assertEqual(row["wished_day"], wished.isoformat())

    def test_a_provider_plan_on_the_extra_work_still_places_the_ticket(self):
        wished = self.today - 3 * DAY
        ticket = self._spawned_wish_ticket(wished=wished)
        extra_work = ticket.extra_work_request
        extra_work.provider_planned_date = self.today
        extra_work.save(update_fields=["provider_planned_date"])
        payload = self.get_plan(self.company_admin, scope="company")
        key = f"ticket-{ticket.id}"
        card = next(e for e in payload["entries"] if e["key"] == key)
        self.assertEqual(card["day"], self.today.isoformat())
        self.assertEqual(card["plan_source"], "PROVIDER_PLAN")
        # A planned job wears no wish fact — the plan outranks it.
        self.assertIsNone(card["wished_day"])
