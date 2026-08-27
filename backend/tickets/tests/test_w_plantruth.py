"""W-PLANTRUTH — the owner's ruling of 2026-08-27, pinned.

THE LAW IS UNCHANGED: planned dates never change by themselves. What
this wave changes is the DISPLAY.

  §1a  ONE FACT PLACES THE BOARD — the planned day of the WORK (a slot's
       day, or a part's window). The ticket-level `scheduled_start_at`
       is a different fact: it places nothing, it takes nothing out of
       the "not planned yet" lane, and it is not a reason to be late.
  §1b  ROLL-FORWARD DISPLAY — pending work whose planned day has passed
       leaves that past column and appears on TODAY's, marked with the
       day it was planned for and how late it is. A PAST column holds
       only work that was actually finished.
  §2   Plan and hours belong to CHARGEABLE work only.
  §3b  Proceeding past the open-parts warning CLOSES those parts.
  §3c  Managers/PA/SA can mark a part done, and undone.

Every date here is relative to `timezone.localdate()`, never a literal:
a test that passes only in August is a test that fails in September.
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
    SubTask,
    Ticket,
    TicketStaffAssignment,
    TicketStatus,
    TicketType,
)

from test_utils import TenantFixtureMixin

URL = "/api/tickets/work-plan/"


class _Fixture(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.worker = self.make_user("plantruth-worker@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.worker, building=self.building
        )

    # -- builders -----------------------------------------------------

    def make_ticket(self, title, ticket_status=TicketStatus.OPEN, *, scheduled=None):
        return Ticket.objects.create(
            company=self.company,
            customer=self.customer,
            building=self.building,
            title=title,
            description="x",
            type=TicketType.REQUEST,
            status=ticket_status,
            created_by=self.super_admin,
            scheduled_start_at=self._at(scheduled) if scheduled is not None else None,
        )

    def _at(self, offset_days, hour=9):
        if offset_days is None:
            return None
        return timezone.make_aware(
            datetime.datetime.combine(
                self.today + datetime.timedelta(days=offset_days),
                datetime.time(hour, 0),
            )
        )

    def make_slot(
        self,
        ticket,
        *,
        days=None,
        user=None,
        slot_status=StaffAssignmentSlotStatus.ASSIGNED,
        sub_task=None,
    ):
        return TicketStaffAssignment.objects.create(
            ticket=ticket,
            user=user or self.worker,
            assigned_by=self.super_admin,
            scheduled_start_at=self._at(days),
            slot_status=slot_status,
            sub_task=sub_task,
        )

    def plan(self, user=None, week=None):
        self.client.force_authenticate(user or self.worker)
        params = {"week": week} if week else {}
        response = self.client.get(URL, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def week_of(self, offset_days):
        day = self.today + datetime.timedelta(days=offset_days)
        iso = day.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"

    @staticmethod
    def entry(payload, key, bucket="entries"):
        for candidate in payload[bucket]:
            if candidate["key"] == key:
                return candidate
        return None


class TheRollForwardMatrixTests(_Fixture):
    """§1b — the matrix, as the report prints it.

    yesterday-done / yesterday-undone / today-planned / future-planned,
    and where each one renders.
    """

    def test_yesterday_undone_is_on_todays_column_with_its_planned_day(self):
        ticket = self.make_ticket("Undone since yesterday")
        slot = self.make_slot(ticket, days=-1)

        card = self.entry(self.plan(), f"slot-{slot.id}")

        self.assertIsNotNone(card, "an unfinished job left the board entirely")
        self.assertEqual(card["day"], self.today.isoformat())
        self.assertEqual(card["placement"], "ROLLED")
        # THE LAW: the planned date did not move. The card says which day
        # put it here and how far past that day we now are.
        self.assertEqual(
            card["rolled_from"],
            (self.today - datetime.timedelta(days=1)).isoformat(),
        )
        self.assertEqual(card["rolled_days"], 1)
        self.assertEqual(
            card["planned_start"],
            (self.today - datetime.timedelta(days=1)).isoformat(),
            "the stored planned date is untouched",
        )

    def test_yesterday_undone_is_no_longer_in_yesterdays_column(self):
        """A past column shows what was DONE that day, nothing else."""
        ticket = self.make_ticket("Undone since yesterday")
        slot = self.make_slot(ticket, days=-1)

        payload = self.plan()
        yesterday = (self.today - datetime.timedelta(days=1)).isoformat()
        days = [e["day"] for e in payload["entries"] if e["key"] == f"slot-{slot.id}"]
        self.assertNotIn(yesterday, days)

    def test_yesterday_done_stays_in_yesterdays_column(self):
        ticket = self.make_ticket("Finished yesterday")
        slot = self.make_slot(
            ticket, days=-1, slot_status=StaffAssignmentSlotStatus.COMPLETED
        )

        card = self.entry(self.plan(), f"slot-{slot.id}")

        self.assertIsNotNone(card)
        self.assertEqual(
            card["day"], (self.today - datetime.timedelta(days=1)).isoformat()
        )
        self.assertEqual(card["placement"], "PLANNED")
        self.assertIsNone(card["rolled_from"])
        self.assertEqual(card["state"], "DONE")

    def test_today_planned_is_on_today_and_does_not_roll(self):
        ticket = self.make_ticket("Today's job")
        slot = self.make_slot(ticket, days=0)

        card = self.entry(self.plan(), f"slot-{slot.id}")

        self.assertEqual(card["day"], self.today.isoformat())
        self.assertEqual(card["placement"], "PLANNED")
        self.assertIsNone(card["rolled_days"])

    def test_future_planned_stays_on_its_own_future_day(self):
        # +1 can fall in next week (a Sunday today); +0..+1 is still the
        # right assertion because the DAY is what is asserted, and the
        # week asked for is the day's own week.
        ticket = self.make_ticket("Tomorrow's job")
        slot = self.make_slot(ticket, days=1)
        tomorrow = self.today + datetime.timedelta(days=1)

        card = self.entry(self.plan(week=self.week_of(1)), f"slot-{slot.id}")

        self.assertIsNotNone(card)
        self.assertEqual(card["day"], tomorrow.isoformat())
        self.assertEqual(card["placement"], "PLANNED")

    def test_a_rolled_card_is_not_left_behind_in_its_old_week(self):
        """It lives on today's column of the CURRENT week and nowhere
        else — not in the past week it was planned in."""
        ticket = self.make_ticket("Planned last week, never done")
        slot = self.make_slot(ticket, days=-8)

        last_week = self.plan(week=self.week_of(-8))
        self.assertIsNone(
            self.entry(last_week, f"slot-{slot.id}"),
            "undone work lingered in a past week's column",
        )

        this_week = self.entry(self.plan(), f"slot-{slot.id}")
        self.assertIsNotNone(this_week)
        self.assertEqual(this_week["day"], self.today.isoformat())
        self.assertEqual(this_week["rolled_days"], 8)

    def test_a_job_still_inside_its_window_does_not_roll(self):
        """Yesterday to tomorrow is not late on any of those days: the
        rule compares against the window END."""
        ticket = self.make_ticket("Three-day job")
        slot = TicketStaffAssignment.objects.create(
            ticket=ticket,
            user=self.worker,
            assigned_by=self.super_admin,
            scheduled_start_at=self._at(-1),
            scheduled_end_at=self._at(1, hour=17),
        )

        card = self.entry(self.plan(), f"slot-{slot.id}")

        self.assertEqual(card["placement"], "PLANNED")
        self.assertIsNone(card["rolled_from"])

    def test_an_extra_work_rolls_the_same_way(self):
        """Both sources answer to one rule."""
        request = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Gutters, still not cleared",
            description="x",
            preferred_date=self.today - datetime.timedelta(days=3),
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
        )
        ExtraWorkAssignment.objects.create(
            extra_work_request=request,
            user=self.worker,
            role=ExtraWorkAssignmentRole.WORKER,
            assigned_by=self.super_admin,
        )

        card = self.entry(self.plan(), f"ew-{request.id}")

        self.assertIsNotNone(card)
        self.assertEqual(card["day"], self.today.isoformat())
        self.assertEqual(card["placement"], "ROLLED")
        self.assertEqual(card["rolled_days"], 3)


class ASlotOnAFinishedTicketIsOverTests(_Fixture):
    """§1b — an ASSIGNED slot on a ticket whose work is finished is not
    pending. It does not roll, and it does not read OPEN."""

    def test_a_stale_slot_on_a_closed_ticket_does_not_roll(self):
        ticket = self.make_ticket("Closed with a slot left open", TicketStatus.CLOSED)
        slot = self.make_slot(ticket, days=-5)

        # Its OWN week — five days back can be the previous ISO week,
        # which is the point: it stayed where it was planned.
        card = self.entry(self.plan(week=self.week_of(-5)), f"slot-{slot.id}")

        self.assertIsNotNone(card, "it belongs in its own past week")
        self.assertEqual(
            card["day"], (self.today - datetime.timedelta(days=5)).isoformat()
        )
        self.assertEqual(card["placement"], "PLANNED")
        self.assertEqual(card["state"], "DONE")

    def test_a_stale_slot_on_a_rejected_ticket_reads_blocked(self):
        ticket = self.make_ticket("Rejected", TicketStatus.REJECTED)
        slot = self.make_slot(ticket, days=-5)

        card = self.entry(self.plan(week=self.week_of(-5)), f"slot-{slot.id}")

        self.assertEqual(card["state"], "BLOCKED")


class TheTicketDateIsADifferentFactTests(_Fixture):
    """§1a — the ticket-level schedule places nothing and excuses
    nothing. The owner's TCK-361: a ticket whose schedule read Sep 7
    rendering under Aug 29, because the board read the SLOT's day while
    the late ladder read the TICKET's."""

    def test_the_slots_day_places_the_card_not_the_tickets_date(self):
        ticket = self.make_ticket(
            "Schedule says next week", scheduled=11
        )
        slot = self.make_slot(ticket, days=2)
        planned = self.today + datetime.timedelta(days=2)

        card = self.entry(self.plan(week=self.week_of(2)), f"slot-{slot.id}")

        self.assertIsNotNone(card)
        self.assertEqual(card["day"], planned.isoformat())
        self.assertEqual(
            card["planned_start"],
            planned.isoformat(),
            "the card must show the date that placed it",
        )

    def test_the_tickets_own_past_date_does_not_make_a_job_late(self):
        """The ladder reads the WORK's window. A ticket dated in the
        past whose slot is dated ahead is not late."""
        ticket = self.make_ticket("Ticket date stale", scheduled=-20)
        self.make_slot(ticket, days=3)

        payload = self.plan()

        self.assertEqual(payload["counts"]["late"], 0)
        self.assertEqual(payload["late_entries"], [])

    def test_a_ticket_date_does_not_take_a_job_out_of_the_unplanned_lane(self):
        """Nobody has a day for this work, so it is not planned yet —
        whatever the ticket's own header says."""
        ticket = self.make_ticket("Ticket dated, nobody scheduled", scheduled=1)
        slot = self.make_slot(ticket, days=None)

        payload = self.plan()

        self.assertIsNotNone(
            self.entry(payload, f"slot-{slot.id}", "undated_entries"),
            payload["undated_entries"],
        )
        self.assertGreaterEqual(payload["counts"]["undated"], 1)

    def test_a_dated_sibling_still_takes_the_job_out_of_the_lane(self):
        """W-FIX1 A1's real guard survives: the JOB has a day through a
        colleague's slot, so it is planned."""
        ticket = self.make_ticket("One of two has a day")
        mate = self.make_user("plantruth-mate@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(user=mate, building=self.building)
        undated = self.make_slot(ticket, days=None)
        self.make_slot(ticket, days=2, user=mate)

        payload = self._company_plan()

        self.assertIsNone(
            self.entry(payload, f"slot-{undated.id}", "undated_entries"),
            payload["undated_entries"],
        )

    def _company_plan(self):
        self.client.force_authenticate(self.company_admin)
        response = self.client.get(URL, {"scope": "company"})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data


class PartWindowsAreAPlannedDayTests(_Fixture):
    """§1a — "slot/plan days" includes a PART's own window, which the
    board has placed on since W-LATE §3b. It counts for lateness too."""

    def test_a_part_window_in_the_past_makes_the_job_late(self):
        ticket = self.make_ticket("Part missed")
        part = SubTask.objects.create(
            ticket=ticket,
            title="Ramen",
            planned_start_date=self.today - datetime.timedelta(days=4),
        )
        self.make_slot(ticket, days=None, sub_task=part)
        self.make_slot(ticket, days=None)

        payload = self._company_plan()

        late = [
            row
            for row in payload["late_entries"]
            if row["ticket_id"] == ticket.id
        ]
        self.assertEqual(len(late), 1, payload["late_entries"])
        self.assertEqual(late[0]["lateness"]["level"], 1)
        self.assertEqual(late[0]["lateness"]["planned_days_late"], 4)

    def _company_plan(self):
        self.client.force_authenticate(self.company_admin)
        response = self.client.get(URL, {"scope": "company"})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data


class ManagerMarksAPartDoneTests(_Fixture):
    """§3c — the door the people running the job did not have."""

    def setUp(self):
        super().setUp()
        self.ticket = self.make_ticket("Job with parts", TicketStatus.IN_PROGRESS)
        self.part = SubTask.objects.create(ticket=self.ticket, title="Ramen")
        self.slot = self.make_slot(self.ticket, days=0, sub_task=self.part)
        self.url = (
            f"/api/tickets/{self.ticket.id}/sub-tasks/{self.part.id}/done/"
        )

    def test_a_company_admin_marks_a_part_done(self):
        self.client.force_authenticate(self.company_admin)
        response = self.client.post(self.url, {"done": True}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["is_done"])
        self.slot.refresh_from_db()
        self.assertEqual(
            self.slot.slot_status, StaffAssignmentSlotStatus.COMPLETED
        )
        self.assertEqual(self.slot.completed_by_id, self.company_admin.id)
        self.assertIsNotNone(self.slot.completed_at)

    def test_and_undoes_it(self):
        self.client.force_authenticate(self.company_admin)
        self.client.post(self.url, {"done": True}, format="json")
        response = self.client.post(self.url, {"done": False}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["is_done"])
        self.slot.refresh_from_db()
        self.assertEqual(
            self.slot.slot_status, StaffAssignmentSlotStatus.ASSIGNED
        )
        self.assertIsNone(self.slot.completed_at)
        self.assertIsNone(self.slot.completed_by_id)

    def test_a_super_admin_may_too(self):
        self.client.force_authenticate(self.super_admin)
        response = self.client.post(self.url, {"done": True}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

    def test_a_part_nobody_is_on_is_refused_with_its_own_code(self):
        empty = SubTask.objects.create(ticket=self.ticket, title="Nobody")
        self.client.force_authenticate(self.company_admin)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/sub-tasks/{empty.id}/done/",
            {"done": True},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "part_has_nobody")

    def test_staff_are_refused_at_this_door(self):
        """A worker finishes their OWN slot; this is the manager door
        and STAFF never pass `_gate_actor`."""
        self.client.force_authenticate(self.worker)
        response = self.client.post(self.url, {"done": True}, format="json")
        self.assertEqual(response.status_code, 403, response.data)

    def test_another_tenants_ticket_is_a_404_not_a_403(self):
        """H-1 — out of scope is indistinguishable from nonexistent."""
        outsider = self.make_user(
            "plantruth-outsider@example.com", UserRole.COMPANY_ADMIN
        )
        self.client.force_authenticate(outsider)
        response = self.client.post(self.url, {"done": True}, format="json")
        self.assertEqual(response.status_code, 404, response.data)


class ProceedingClosesTheOpenPartsTests(_Fixture):
    """§3b — the warning stays; proceeding marks them done."""

    def setUp(self):
        super().setUp()
        self.ticket = self.make_ticket("Job with parts", TicketStatus.IN_PROGRESS)
        self.part = SubTask.objects.create(ticket=self.ticket, title="Ramen")
        self.slot = self.make_slot(self.ticket, days=0, sub_task=self.part)

    def _move(self, to_status=TicketStatus.WAITING_MANAGER_REVIEW):
        self.client.force_authenticate(self.company_admin)
        return self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {"to_status": to_status, "note": "klaar"},
            format="json",
        )

    def test_a_completion_move_closes_the_open_part(self):
        response = self._move()

        self.assertEqual(response.status_code, 200, response.data)
        self.slot.refresh_from_db()
        self.assertEqual(
            self.slot.slot_status, StaffAssignmentSlotStatus.COMPLETED
        )
        self.assertEqual(self.slot.completed_by_id, self.company_admin.id)
        self.part.refresh_from_db()
        self.assertTrue(self.part.is_done())

    def test_the_timeline_says_which_parts_it_closed(self):
        self._move()

        notes = [
            row.note
            for row in self.ticket.status_history.all()
            if "Ramen" in (row.note or "")
        ]
        self.assertTrue(notes, "the close left no line on the timeline")
        self.assertIn("closed with the step", notes[0].lower())

    def test_the_move_is_never_blocked_by_an_open_part(self):
        """Completion stays free — W-LATE §3c's rule, unchanged."""
        response = self._move()
        self.assertEqual(response.status_code, 200, response.data)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.WAITING_MANAGER_REVIEW)

    def test_a_non_completion_move_closes_nothing(self):
        # Starting work needs a schedule (W13-FIX's transition
        # requirements); this test is about the PARTS, so the
        # requirement is met rather than argued with.
        self.ticket.status = TicketStatus.OPEN
        self.ticket.scheduled_start_at = self._at(0)
        self.ticket.save(update_fields=["status", "scheduled_start_at"])

        response = self._move(TicketStatus.IN_PROGRESS)

        self.assertEqual(response.status_code, 200, response.data)
        self.slot.refresh_from_db()
        self.assertEqual(
            self.slot.slot_status, StaffAssignmentSlotStatus.ASSIGNED
        )

    def test_a_part_nobody_is_on_is_named_and_left_alone(self):
        SubTask.objects.create(ticket=self.ticket, title="Nobody")

        response = self._move()

        self.assertEqual(response.status_code, 200, response.data)
        notes = [
            row.note
            for row in self.ticket.status_history.all()
            if "Nobody" in (row.note or "")
        ]
        self.assertTrue(notes, "a part nobody is on was closed silently")
        self.assertIn("left as they are", notes[0])
