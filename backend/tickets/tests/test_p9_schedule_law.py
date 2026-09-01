"""
P-9 Part A (Addendum D §D.21) — the placement law, pinned.

The owner's model in plain words: "Today shows what is planned for
today and what I didn't do yesterday. The past shows only what I
finished. The future shows what I will do. Not-planned and
waiting-for-the-customer are outside the dates." Four things the board
now does that it did not before P-9, each pinned here:

  * a job waiting on the customer is absent from EVERY week's columns
    (rule 9 in every week — it used to keep its past column as history);
  * a finished job hangs on the day it was FINISHED (rule 10), not on its
    planned day, and in no other week; a finished job with no known
    finish moment keeps its planned day (nothing is invented);
  * a rolled job is on today and absent from the past week it was
    planned in (ruling 12(d), closed by the owner's words);
  * `POST /tickets/<id>/schedule/` moves the people's days with the
    job's day unless told not to (ruling 12(e): `apply_to_slots`
    defaults to true).

And the parity the whole module rests on: the SQL counts equal the rows
the Python rule places, over a fixture with finished-elsewhere rows.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
from unittest import mock

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from tickets.models import StaffAssignmentSlotStatus, TicketStatus
from tickets.tests.test_sprint179a_work_plan import WorkPlanFixture
from tickets.work_plan import PLACEMENT_PLANNED, PLACEMENT_ROLLED

DAY = datetime.timedelta(days=1)


def _aware(day, hour, minute=0):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, minute))
    )


class _LawFixture(WorkPlanFixture):
    """Today is pinned to a WEDNESDAY so "last week" and "this week" are
    fixed shapes whatever weekday the suite runs on."""

    def setUp(self):
        super().setUp()
        real = timezone.localdate()
        self.wed = datetime.date.fromisocalendar(*real.isocalendar()[:2], 3)
        self.last_mon = self.wed - 9 * DAY
        self.last_wed = self.wed - 7 * DAY
        self.last_fri = self.wed - 5 * DAY

    def week_of(self, day):
        iso = day.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"

    def board(self, user=None, **params):
        with mock.patch("django.utils.timezone.localdate", return_value=self.wed):
            return self.get_plan(
                user or self.company_admin,
                **({"scope": "company"} if user is None else {}),
                **params,
            )

    def find(self, payload, key):
        for bucket in (
            "entries",
            "undated_entries",
            "parked_entries",
            "waiting_customer_entries",
            "stuck_entries",
        ):
            for entry in payload.get(bucket, []):
                if entry["key"] == key:
                    return entry, bucket
        return None, None

    def _stamp(self, ticket, **stamps):
        for field, value in stamps.items():
            setattr(ticket, field, value)
        ticket.save(update_fields=[*stamps, "updated_at"])


class WaitingCustomerLeavesEveryWeekTests(_LawFixture, APITestCase):
    """Rule 9 in EVERY week (§A.2a): outside the dates."""

    def _waiting(self):
        ticket = self.make_ticket(
            "Sent to the customer",
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            scheduled=self.last_mon,
        )
        self._stamp(ticket, sent_for_approval_at=_aware(self.last_wed, 16))
        from tickets.models import TicketStatusHistory

        # Creating the ticket in this status already wrote a history leg
        # into it (dated now); the report moment is the LATEST leg into a
        # reported-done status, so every such leg is backdated and given
        # its reporter. `created_at` is auto_now_add: update, not create.
        legs = TicketStatusHistory.objects.filter(
            ticket=ticket, new_status=TicketStatus.WAITING_CUSTOMER_APPROVAL
        )
        if not legs.exists():
            TicketStatusHistory.objects.create(
                ticket=ticket,
                old_status=TicketStatus.IN_PROGRESS,
                new_status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
                changed_by=self.worker,
            )
        legs.update(created_at=_aware(self.last_wed, 16), changed_by=self.worker)
        self.make_slot(
            ticket,
            start=self.last_mon,
            slot_status=StaffAssignmentSlotStatus.COMPLETED,
        )
        return ticket

    def test_absent_from_the_past_week_it_was_planned_in(self):
        ticket = self._waiting()
        payload = self.board(week=self.week_of(self.last_mon))
        card, bucket = self.find(payload, f"ticket-{ticket.id}")
        self.assertEqual(bucket, "waiting_customer_entries")
        self.assertEqual(payload["entries"], [])
        self.assertEqual(payload["counts"]["total"], 0)
        self.assertEqual(payload["counts"]["waiting_customer"], 1)

    def test_the_waiting_row_states_the_report_the_wait_and_the_recipient(self):
        ticket = self._waiting()
        payload = self.board()
        card, _bucket = self.find(payload, f"ticket-{ticket.id}")
        self.assertEqual(card["reported_done_day"], self.last_wed.isoformat())
        # `make_user` names the person after the local part of the email.
        self.assertEqual(card["reported_done_by_name"], "worker-179a")
        self.assertEqual(card["waiting_days"], 7)
        # Opened by a provider user, so the recipient is the organisation.
        self.assertEqual(card["sent_to_name"], self.customer.name)
        self.assertIsNone(card["settled_at"])

    def test_the_workers_own_week_follows_the_same_rule_in_the_past(self):
        ticket = self._waiting()
        slot = ticket.staff_assignments.get()
        payload = self.board(user=self.worker, week=self.week_of(self.last_mon))
        card, bucket = self.find(payload, f"slot-{slot.id}")
        self.assertEqual(bucket, "waiting_customer_entries")
        self.assertEqual(payload["entries"], [])
        self.assertEqual(payload["counts"]["total"], 0)


class FinishedWorkHangsOnItsFinishedDayTests(_LawFixture, APITestCase):
    """Rule 10 (§A.2b): the past shows what was finished, on the day it
    was finished."""

    def _finished(self, *, stamped=True):
        ticket = self.make_ticket(
            "Planned Monday, finished Wednesday",
            TicketStatus.CLOSED,
            scheduled=self.last_mon,
        )
        if stamped:
            self._stamp(
                ticket,
                manager_review_at=_aware(self.last_wed, 15),
                approved_at=_aware(self.last_fri, 10),
                closed_at=_aware(self.last_fri, 10),
            )
        self.make_slot(
            ticket,
            start=self.last_mon,
            slot_status=StaffAssignmentSlotStatus.COMPLETED,
        )
        return ticket

    def test_the_managers_card_is_on_the_finished_day_with_the_plan_beside_it(self):
        ticket = self._finished()
        payload = self.board(week=self.week_of(self.last_mon))
        card, bucket = self.find(payload, f"ticket-{ticket.id}")
        self.assertEqual((bucket, card["placement"]), ("entries", PLACEMENT_PLANNED))
        self.assertEqual(card["day"], self.last_wed.isoformat())
        self.assertEqual(card["planned_start"], self.last_mon.isoformat())
        self.assertEqual(card["settled_day"], self.last_wed.isoformat())
        self.assertEqual(card["settled_days_after_plan"], 2)
        self.assertEqual(card["approved_day"], self.last_fri.isoformat())
        self.assertTrue(card["viewer_settled"])
        # The chips describe the board: one finished job in last week.
        self.assertEqual(payload["counts"]["total"], 1)
        self.assertEqual(payload["counts"]["done"], 1)

    def test_it_is_in_no_other_week(self):
        ticket = self._finished()
        this_week = self.board()
        self.assertIsNone(self.find(this_week, f"ticket-{ticket.id}")[0])
        self.assertEqual(this_week["counts"]["total"], 0)

    def test_a_finish_after_the_planned_week_moves_the_card_to_the_finish_week(self):
        ticket = self._finished()
        # Reported done THIS Monday: the card leaves last week entirely.
        self._stamp(ticket, manager_review_at=_aware(self.wed - 2 * DAY, 15))
        last_week = self.board(week=self.week_of(self.last_mon))
        self.assertIsNone(self.find(last_week, f"ticket-{ticket.id}")[0])
        self.assertEqual(last_week["counts"]["total"], 0)
        this_week = self.board()
        card, _bucket = self.find(this_week, f"ticket-{ticket.id}")
        self.assertEqual(card["day"], (self.wed - 2 * DAY).isoformat())
        self.assertEqual(card["settled_days_after_plan"], 7)
        self.assertEqual(this_week["counts"]["total"], 1)

    def test_without_a_finish_moment_the_planned_day_still_places_it(self):
        ticket = self._finished(stamped=False)
        payload = self.board(week=self.week_of(self.last_mon))
        card, bucket = self.find(payload, f"ticket-{ticket.id}")
        self.assertEqual((bucket, card["day"]), ("entries", self.last_mon.isoformat()))
        self.assertIsNone(card["settled_at"])
        self.assertIsNone(card["settled_days_after_plan"])
        self.assertEqual(payload["counts"]["total"], 1)

    def test_the_workers_completed_slot_hangs_on_the_day_they_completed_it(self):
        ticket = self.make_ticket("Two people", TicketStatus.IN_PROGRESS, scheduled=self.last_mon)
        mine = self.make_slot(
            ticket,
            start=self.last_mon,
            slot_status=StaffAssignmentSlotStatus.COMPLETED,
        )
        mine.completed_at = _aware(self.last_fri, 12)
        mine.save(update_fields=["completed_at"])
        # A colleague still works it: the ticket is live, and a stale
        # report stamp on the ticket must not place MY finished slot.
        self._stamp(ticket, manager_review_at=_aware(self.last_wed, 15))
        payload = self.board(user=self.worker, week=self.week_of(self.last_mon))
        card, bucket = self.find(payload, f"slot-{mine.id}")
        self.assertEqual((bucket, card["day"]), ("entries", self.last_fri.isoformat()))
        self.assertEqual(card["settled_days_after_plan"], 4)
        self.assertEqual(payload["counts"]["total"], 1)


class RolledWorkIsOnTodayOnlyTests(_LawFixture, APITestCase):
    """Ruling 12(d), closed: an unfinished job planned in a past week is
    NOT in that week — it is on today."""

    def test_absent_from_its_planned_past_week_and_present_on_today(self):
        ticket = self.make_ticket("Still not done", scheduled=self.last_mon)
        self.make_slot(ticket, start=self.last_mon)
        past = self.board(week=self.week_of(self.last_mon))
        self.assertIsNone(self.find(past, f"ticket-{ticket.id}")[0])
        self.assertEqual(past["counts"]["total"], 0)
        now = self.board()
        card, bucket = self.find(now, f"ticket-{ticket.id}")
        self.assertEqual((bucket, card["placement"]), ("entries", PLACEMENT_ROLLED))
        self.assertEqual(card["day"], self.wed.isoformat())
        self.assertEqual(card["rolled_from"], self.last_mon.isoformat())
        self.assertEqual(card["rolled_days"], 9)
        self.assertEqual(now["counts"]["total"], 1)


class ApplyToSlotsDefaultsTrueTests(_LawFixture, APITestCase):
    """Ruling 12(e): one plan, one date — the people move with the job."""

    def _post(self, ticket, body):
        self.client.force_authenticate(self.company_admin)
        return self.client.post(f"/api/tickets/{ticket.id}/schedule/", body, format="json")

    def test_the_people_move_with_the_job_unless_told_not_to(self):
        ticket = self.make_ticket("Moves with the job")
        slot = self.make_slot(ticket, start=self.last_mon)
        response = self._post(
            ticket, {"scheduled_start_at": _aware(self.wed + 3 * DAY, 9).isoformat()}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        slot.refresh_from_db()
        self.assertEqual(timezone.localtime(slot.scheduled_start_at).date(), self.wed + 3 * DAY)

    def test_apply_to_slots_false_moves_the_job_only(self):
        ticket = self.make_ticket("Job only")
        slot = self.make_slot(ticket, start=self.last_mon)
        response = self._post(
            ticket,
            {
                "scheduled_start_at": _aware(self.wed + 3 * DAY, 9).isoformat(),
                "apply_to_slots": False,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        slot.refresh_from_db()
        self.assertEqual(timezone.localtime(slot.scheduled_start_at).date(), self.last_mon)


class PlannedHoursOnTheCardTests(_LawFixture, APITestCase):
    def test_a_meerwerk_jobs_card_carries_the_plans_hours(self):
        extra_work = self.make_extra_work(
            "Priced job", preferred=self.wed + 2 * DAY, assignee=self.worker
        )
        extra_work.budget_hours = Decimal("4.50")
        extra_work.save(update_fields=["budget_hours"])
        ticket = self.make_ticket("Spawned", scheduled=self.wed + 2 * DAY)
        ticket.extra_work_request = extra_work
        ticket.save(update_fields=["extra_work_request"])
        self.make_slot(ticket, start=self.wed + 2 * DAY)
        card, _bucket = self.find(self.board(), f"ticket-{ticket.id}")
        self.assertEqual(card["planned_hours"], "4.50")
        plain = self.make_ticket("Plain", scheduled=self.wed + 2 * DAY)
        self.make_slot(plain, start=self.wed + 2 * DAY)
        plain_card, _bucket = self.find(self.board(), f"ticket-{plain.id}")
        self.assertIsNone(plain_card["planned_hours"])


class CountsAgreeWithTheLawTests(_LawFixture, APITestCase):
    """The parity the module rests on, over the rows this law moves."""

    def setUp(self):
        super().setUp()
        finished = self.make_ticket("Finished later", TicketStatus.CLOSED, scheduled=self.last_mon)
        self._stamp(finished, manager_review_at=_aware(self.last_fri, 15), closed_at=_aware(self.last_fri, 16))
        self.make_slot(finished, start=self.last_mon, slot_status=StaffAssignmentSlotStatus.COMPLETED)
        waiting = self.make_ticket("Waiting", TicketStatus.WAITING_CUSTOMER_APPROVAL, scheduled=self.last_mon)
        self._stamp(waiting, sent_for_approval_at=_aware(self.last_wed, 15))
        self.make_slot(waiting, start=self.last_mon, slot_status=StaffAssignmentSlotStatus.COMPLETED)
        rolled = self.make_ticket("Rolled", scheduled=self.last_mon)
        self.make_slot(rolled, start=self.last_mon)
        legacy = self.make_ticket("Legacy closed", TicketStatus.CLOSED, scheduled=self.last_wed)
        self.make_slot(legacy, start=self.last_wed, slot_status=StaffAssignmentSlotStatus.COMPLETED)
        rejected = self.make_ticket("Rejected", TicketStatus.REJECTED, scheduled=self.last_wed)
        self._stamp(rejected, rejected_at=_aware(self.last_fri, 9))
        self.make_slot(rejected, start=self.last_wed)

    def test_every_week_and_both_readers(self):
        for user, params in ((None, {}), (self.worker, {})):
            for offset in (-14, -7, 0, 7):
                target = self.wed + offset * DAY
                with self.subTest(user=user, week=self.week_of(target)):
                    payload = self.board(user=user, week=self.week_of(target), **params)
                    entries = payload["entries"]
                    counts = payload["counts"]
                    self.assertEqual(counts["total"], len(entries))
                    self.assertEqual(counts["done"], sum(1 for e in entries if e["state"] == "DONE"))
                    self.assertEqual(counts["open"], sum(1 for e in entries if e["state"] == "OPEN"))
                    self.assertEqual(counts["blocked"], sum(1 for e in entries if e["state"] == "BLOCKED"))
                    for entry in entries:
                        self.assertNotEqual(entry["ticket_status"], TicketStatus.WAITING_CUSTOMER_APPROVAL)
