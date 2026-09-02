"""
P-10 Part A (Addendum D §D.21, amended) — review placement is PERSONAL.

A1 — the bug. `WAITING_MANAGER_REVIEW` is not live, so the board read it
as DONE, `settled_day` became the worker's report day, and rule 10 hung
the card in the week of that report and nowhere else. Rule 8 (review
sits on today) was dead code for any report older than today: the
owner saw unapproved work in past columns where nobody looks — the
oldest problem, back on the board. A job in review is NOT finished:
`settled_day` is set only once the chain is over (approved, closed, the
blocked endings), never for WAITING_MANAGER_REVIEW and never for
WAITING_CUSTOMER_APPROVAL, in SQL and in Python alike.

A2 — where it lives. The owner: "everyone's schedule is their own; the
manager sees it on their day, the owner sees it in a section."

    responsible manager   a card on TODAY (placement REVIEW) until checked
    everybody else        the "Waiting for a manager's check" strip
    the worker            the "Reported done, waiting for the check" strip

Every fixture here is reported done LAST week (Step 0.2: a matrix whose
fixtures all stamp "today" proves nothing about the past).
"""
from __future__ import annotations

import datetime
from unittest import mock

from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import BuildingManagerAssignment
from tickets.models import (
    StaffAssignmentSlotStatus,
    TicketManagerAssignment,
    TicketStatus,
    TicketStatusHistory,
)
from tickets.tests.test_sprint179a_work_plan import WorkPlanFixture
from tickets.work_plan import PLACEMENT_PLANNED, PLACEMENT_REVIEW, STATE_BLOCKED

DAY = datetime.timedelta(days=1)
BUCKETS = (
    "entries",
    "undated_entries",
    "parked_entries",
    "waiting_customer_entries",
    "review_entries",
    "stuck_entries",
)


def _aware(day, hour, minute=0):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, minute))
    )


class _ReviewFixture(WorkPlanFixture):
    """Today is pinned to a WEDNESDAY; the report happened LAST Wednesday."""

    def setUp(self):
        super().setUp()
        real = timezone.localdate()
        self.wed = datetime.date.fromisocalendar(*real.isocalendar()[:2], 3)
        self.last_mon = self.wed - 9 * DAY
        self.last_wed = self.wed - 7 * DAY
        self.last_fri = self.wed - 5 * DAY
        # A second manager on the SAME building: in scope, but not the
        # one named on the ticket. `self.manager` (test_utils) already
        # holds a BuildingManagerAssignment on `self.building`.
        self.bystander = self.make_user("manager-c@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(user=self.bystander, building=self.building)
        # P-11 F — the OTHER in-scope not-responsible case, noted rather
        # than tested (the owner's call): a manager like sophie-admin
        # (bright-facilities) is a COMPANY_ADMIN whose scope admits the
        # ticket but who sits in no responsibility tier — named, legacy
        # or building ring. She reads the strip, exactly as `bystander`
        # does here when another manager is named; the predicate
        # (`_ticket_responsible_q`) never asks about her at all, so a
        # test would re-prove the bystander rows above with a different
        # role string.

    def week_of(self, day):
        iso = day.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"

    def board(self, user, **params):
        with mock.patch("django.utils.timezone.localdate", return_value=self.wed):
            return self.get_plan(user, **params)

    def team(self, user, **params):
        return self.board(user, scope="company", **params)

    def find(self, payload, key):
        for bucket in BUCKETS:
            for entry in payload.get(bucket, []):
                if entry["key"] == key:
                    return entry, bucket
        return None, None

    def _stamp(self, ticket, **stamps):
        for field, value in stamps.items():
            setattr(ticket, field, value)
        ticket.save(update_fields=[*stamps, "updated_at"])

    def _reported(self, *, name_manager=True, planned=None, title="Reported done last week"):
        """Planned last Wednesday, reported done last Wednesday 15:00 by
        the worker, still waiting for the manager's check."""
        planned = planned or self.last_wed
        ticket = self.make_ticket(title, TicketStatus.WAITING_MANAGER_REVIEW, scheduled=planned)
        self._stamp(ticket, manager_review_at=_aware(self.last_wed, 15))
        legs = TicketStatusHistory.objects.filter(
            ticket=ticket, new_status=TicketStatus.WAITING_MANAGER_REVIEW
        )
        if not legs.exists():
            TicketStatusHistory.objects.create(
                ticket=ticket,
                old_status=TicketStatus.IN_PROGRESS,
                new_status=TicketStatus.WAITING_MANAGER_REVIEW,
                changed_by=self.worker,
            )
        # `created_at` is auto_now_add: backdate with update().
        legs.update(created_at=_aware(self.last_wed, 15), changed_by=self.worker)
        slot = self.make_slot(
            ticket, start=planned, slot_status=StaffAssignmentSlotStatus.COMPLETED
        )
        if name_manager:
            TicketManagerAssignment.objects.create(
                ticket=ticket, user=self.manager, assigned_by=self.company_admin
            )
        return ticket, slot

    def viewers(self, ticket, slot):
        """(label, user, params, the key this viewer's card carries)."""
        return (
            ("company_admin", self.company_admin, {"scope": "company"}, f"ticket-{ticket.id}"),
            ("responsible manager", self.manager, {"scope": "company"}, f"ticket-{ticket.id}"),
            ("bystander manager", self.bystander, {"scope": "company"}, f"ticket-{ticket.id}"),
            ("worker", self.worker, {}, f"slot-{slot.id}"),
        )


class ReviewIsNotFinishedTests(_ReviewFixture, APITestCase):
    """A1 — absent from the week of its report, for EVERY viewer."""

    def test_absent_from_the_past_week_for_every_viewer(self):
        ticket, slot = self._reported()
        for label, user, params, key in self.viewers(ticket, slot):
            with self.subTest(viewer=label):
                payload = self.board(user, week=self.week_of(self.last_wed), **params)
                self.assertEqual(payload["entries"], [], label)
                self.assertEqual(payload["counts"]["total"], 0, label)
                self.assertEqual(payload["counts"]["done"], 0, label)
                card, bucket = self.find(payload, key)
                if user is self.manager:
                    # The responsible manager's card is on THEIR TODAY
                    # (A2) — not in a past week's columns, and not in the
                    # strip either, because it is theirs to check.
                    self.assertIsNone(card, label)
                    self.assertEqual(payload["counts"]["review_mine"], 1, label)
                    self.assertEqual(payload["counts"]["review"], 0, label)
                    continue
                # Whole scope, whichever week is browsed: the strip.
                self.assertEqual(bucket, "review_entries", label)
                self.assertIsNone(card["settled_day"], label)
                self.assertIsNone(card["settled_at"], label)
                self.assertEqual(card["reported_done_day"], self.last_wed.isoformat(), label)
                self.assertEqual(card["waiting_days"], 7, label)

    def test_after_approval_it_hangs_on_the_day_it_was_reported_done(self):
        ticket, slot = self._reported()
        self._stamp(
            ticket,
            status=TicketStatus.APPROVED,
            approved_at=_aware(self.wed, 10),
        )
        last_week = self.team(self.company_admin, week=self.week_of(self.last_wed))
        card, bucket = self.find(last_week, f"ticket-{ticket.id}")
        self.assertEqual((bucket, card["placement"]), ("entries", PLACEMENT_PLANNED))
        self.assertEqual(card["day"], self.last_wed.isoformat())
        self.assertEqual(card["settled_day"], self.last_wed.isoformat())
        self.assertEqual(card["approved_day"], self.wed.isoformat())
        self.assertEqual(last_week["counts"]["done"], 1)
        this_week = self.team(self.company_admin)
        self.assertIsNone(self.find(this_week, f"ticket-{ticket.id}")[0])
        self.assertEqual(this_week["counts"]["review"], 0)
        # The worker's completed slot follows the same finish.
        own = self.board(self.worker, week=self.week_of(self.last_wed))
        card, bucket = self.find(own, f"slot-{slot.id}")
        self.assertEqual((bucket, card["day"]), ("entries", self.last_wed.isoformat()))

    def test_a_blocked_ending_hangs_on_the_day_it_left_the_board(self):
        ticket = self.make_ticket("Rejected this week", TicketStatus.REJECTED, scheduled=self.last_mon)
        self._stamp(ticket, rejected_at=_aware(self.wed - 2 * DAY, 9))
        self.make_slot(ticket, start=self.last_mon)
        last_week = self.team(self.company_admin, week=self.week_of(self.last_mon))
        self.assertIsNone(self.find(last_week, f"ticket-{ticket.id}")[0])
        self.assertEqual(last_week["counts"]["total"], 0)
        this_week = self.team(self.company_admin)
        card, bucket = self.find(this_week, f"ticket-{ticket.id}")
        self.assertEqual((bucket, card["day"]), ("entries", (self.wed - 2 * DAY).isoformat()))
        self.assertEqual(card["state"], STATE_BLOCKED)
        self.assertEqual(this_week["counts"]["blocked"], 1)


class ReviewIsPersonalTests(_ReviewFixture, APITestCase):
    """A2 — the manager on their day, everybody else in a section."""

    def test_the_named_manager_has_it_on_today(self):
        ticket, _slot = self._reported()
        payload = self.team(self.manager)
        card, bucket = self.find(payload, f"ticket-{ticket.id}")
        self.assertEqual((bucket, card["placement"]), ("entries", PLACEMENT_REVIEW))
        self.assertEqual(card["day"], self.wed.isoformat())
        self.assertEqual(card["stuck_age_days"], 7)
        self.assertEqual(card["waiting_days"], 7)
        self.assertEqual(card["reported_done_by_name"], "worker-179a")
        self.assertFalse(card["viewer_settled"])
        self.assertEqual(payload["counts"]["review_mine"], 1)
        self.assertEqual(payload["counts"]["review"], 0)
        self.assertEqual(payload["review_entries"], [])
        self.assertEqual(payload["counts"]["total"], 1)

    def test_everybody_else_reads_the_strip(self):
        ticket, slot = self._reported()
        for label, user, params, key in (
            ("company_admin", self.company_admin, {"scope": "company"}, f"ticket-{ticket.id}"),
            ("bystander manager", self.bystander, {"scope": "company"}, f"ticket-{ticket.id}"),
            ("worker", self.worker, {}, f"slot-{slot.id}"),
        ):
            with self.subTest(viewer=label):
                payload = self.board(user, **params)
                self.assertEqual(payload["entries"], [], label)
                self.assertEqual(payload["counts"]["total"], 0, label)
                self.assertEqual(payload["counts"]["review"], 1, label)
                self.assertEqual(payload["counts"]["review_mine"], 0, label)
                card, bucket = self.find(payload, key)
                self.assertEqual(bucket, "review_entries", label)
                # The strip's summary names the manager it waits on.
                self.assertEqual(card["manager_names"], ["manager-a"], label)
                self.assertEqual(card["waiting_days"], 7, label)
                self.assertEqual(card["reported_done_by_name"], "worker-179a", label)

    def test_the_building_ring_answers_when_nobody_is_named(self):
        ticket, _slot = self._reported(name_manager=False)
        for manager in (self.manager, self.bystander):
            with self.subTest(manager=manager.email):
                payload = self.team(manager)
                card, bucket = self.find(payload, f"ticket-{ticket.id}")
                self.assertEqual((bucket, card["placement"]), ("entries", PLACEMENT_REVIEW))
                self.assertEqual(payload["counts"]["review_mine"], 1)
        admin = self.team(self.company_admin)
        card, bucket = self.find(admin, f"ticket-{ticket.id}")
        self.assertEqual(bucket, "review_entries")
        self.assertEqual(card["manager_names"], ["manager-a", "manager-c"])

    def test_the_legacy_primary_manager_counts_when_nobody_is_named(self):
        ticket, _slot = self._reported(name_manager=False)
        self._stamp(ticket, assigned_to=self.bystander)
        mine = self.team(self.bystander)
        card, bucket = self.find(mine, f"ticket-{ticket.id}")
        self.assertEqual((bucket, card["placement"]), ("entries", PLACEMENT_REVIEW))
        other = self.team(self.manager)
        card, bucket = self.find(other, f"ticket-{ticket.id}")
        self.assertEqual(bucket, "review_entries")
        self.assertEqual(card["manager_names"], ["manager-c"])

    def test_the_counts_agree_for_every_viewer_and_both_weeks(self):
        ticket, slot = self._reported()
        self._reported(name_manager=False, title="Ring job")
        for label, user, params, _key in self.viewers(ticket, slot):
            for target in (self.last_wed, self.wed, self.wed + 7 * DAY):
                with self.subTest(viewer=label, week=self.week_of(target)):
                    payload = self.board(user, week=self.week_of(target), **params)
                    entries = payload["entries"]
                    counts = payload["counts"]
                    self.assertEqual(counts["total"], len(entries))
                    self.assertEqual(counts["done"], sum(1 for e in entries if e["state"] == "DONE"))
                    self.assertEqual(counts["review"], len(payload["review_entries"]))
                    on_today = [e for e in entries if e["placement"] == PLACEMENT_REVIEW]
                    self.assertEqual(counts["review_mine"], len(on_today) if target == self.wed else counts["review_mine"])
                    for entry in entries:
                        if entry["ticket_status"] == TicketStatus.WAITING_MANAGER_REVIEW:
                            self.assertEqual(entry["placement"], PLACEMENT_REVIEW)
                            self.assertEqual(entry["day"], self.wed.isoformat())
                    strip_keys = {e["key"] for e in payload["review_entries"]}
                    self.assertEqual(strip_keys & {e["key"] for e in entries}, set())
