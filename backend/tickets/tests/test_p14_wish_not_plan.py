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
