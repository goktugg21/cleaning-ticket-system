"""W-PLANTRUTH — the owner's ruling of 2026-08-27, pinned.

THE LAW IS UNCHANGED: planned dates never change by themselves. What
this wave changes is the DISPLAY.

  §1a  SUPERSEDED by W-VIEWER (owner ruling, 2026-08-27). It said one
       fact places the board for every reader — the planned day of the
       WORK (a slot's day, or a part's window). Applied to a manager
       that produced the owner's TCK-361 the other way round: a job the
       ticket scheduled for 7 September filed under 29 August, because
       one of four slots carried that day. The board is now VIEWER-AWARE
       (see `TheTicketDateIsTheJobsDateTests`): the job's scheduled date
       places a manager's card, the person's own day places theirs, and
       both facts are true.
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


class TheTicketDateIsTheJobsDateTests(_Fixture):
    """W-VIEWER (owner ruling, 2026-08-27) — SUPERSEDES §1a.

    §1a said one fact places the board for every reader, and that fact
    was the WORK's day: a slot's, or a part's. Applied to a manager it
    produced the owner's TCK-361 the other way round — a job the ticket
    schedules for 7 September filed under 29 August because one of four
    slots carried that day.

    The ruling: the job's scheduled date and one person's assigned
    working date are DIFFERENT FACTS AND BOTH ARE TRUE, so the reader
    decides which one places their board.

        SA / PA / MANAGER  the ticket's own scheduled date. One card per
                           job, whatever its headcount.
        STAFF (own week)   their own slot and their own parts, on the
                           days they were given.
    """

    def _company_plan(self, week=None):
        self.client.force_authenticate(self.company_admin)
        params = {"scope": "company"}
        if week:
            params["week"] = week
        response = self.client.get(URL, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_the_tickets_date_places_the_managers_card(self):
        ticket = self.make_ticket("Schedule says next week", scheduled=11)
        self.make_slot(ticket, days=2)
        scheduled = self.today + datetime.timedelta(days=11)

        card = self.entry(
            self._company_plan(week=self.week_of(11)), f"ticket-{ticket.id}"
        )

        self.assertIsNotNone(card, "the job belongs in its scheduled week")
        self.assertEqual(card["day"], scheduled.isoformat())
        self.assertEqual(card["planned_start"], scheduled.isoformat())
        self.assertEqual(card["kind"], "TICKET")

    def test_a_staff_members_day_does_not_pull_the_managers_card_to_it(self):
        """The exact defect: the slot's week must not hold the job."""
        ticket = self.make_ticket("Schedule says next week", scheduled=11)
        self.make_slot(ticket, days=2)

        payload = self._company_plan(week=self.week_of(2))

        self.assertIsNone(
            self.entry(payload, f"ticket-{ticket.id}"),
            [e["key"] for e in payload["entries"]],
        )

    def test_the_staff_members_own_day_still_places_THEIR_card(self):
        """And the other half of the ruling: their day is real too."""
        ticket = self.make_ticket("Schedule says next week", scheduled=11)
        slot = self.make_slot(ticket, days=2)
        planned = self.today + datetime.timedelta(days=2)

        card = self.entry(self.plan(week=self.week_of(2)), f"slot-{slot.id}")

        self.assertIsNotNone(card)
        self.assertEqual(card["day"], planned.isoformat())
        self.assertEqual(card["kind"], "TICKET_SLOT")

    def test_one_job_is_one_card_however_many_people_are_on_it(self):
        ticket = self.make_ticket("Five on this", scheduled=1)
        for index in range(3):
            mate = self.make_user(
                f"plantruth-crew{index}@example.com", UserRole.STAFF
            )
            BuildingStaffVisibility.objects.create(
                user=mate, building=self.building
            )
            self.make_slot(ticket, days=index, user=mate)

        payload = self._company_plan()
        rows = [e for e in payload["entries"] if e["ticket_id"] == ticket.id]

        self.assertEqual(len(rows), 1, [e["key"] for e in rows])
        self.assertEqual(rows[0]["assignee_count"], 3)

    def test_a_stale_slot_does_not_make_the_job_late_for_a_manager(self):
        """"Do not let a manager's unrelated staff slot make the entire
        ticket falsely late" — the ruling, verbatim."""
        ticket = self.make_ticket("Scheduled ahead", scheduled=3)
        self.make_slot(ticket, days=-5)

        payload = self._company_plan()

        self.assertEqual(payload["counts"]["late"], 0)
        self.assertEqual(payload["late_entries"], [])

    def test_but_the_person_holding_that_slot_is_late_on_their_own_day(self):
        ticket = self.make_ticket("Scheduled ahead", scheduled=3)
        slot = self.make_slot(ticket, days=-5)

        payload = self.plan()
        card = self.entry(payload, f"slot-{slot.id}")

        self.assertIsNotNone(card)
        self.assertEqual(card["placement"], "ROLLED")
        self.assertEqual(card["day"], self.today.isoformat())
        self.assertEqual(card["rolled_days"], 5)

    def test_a_dated_ticket_with_nobody_scheduled_is_on_the_managers_board(self):
        """The W-PLANTRUTH §1a case, inverted by the ruling. A job whose
        ticket carries Tuesday and whose people carry no day HAPPENS ON
        TUESDAY; it is not "not planned yet"."""
        ticket = self.make_ticket("Ticket dated, nobody scheduled", scheduled=1)
        self.make_slot(ticket, days=None)

        payload = self._company_plan()

        self.assertIsNotNone(
            self.entry(payload, f"ticket-{ticket.id}"),
            [e["key"] for e in payload["entries"]],
        )
        self.assertIsNone(
            self.entry(payload, f"ticket-{ticket.id}", "undated_entries")
        )

    def test_a_job_nobody_dated_at_all_is_undated_for_a_manager(self):
        """And when there is NO valid placement date, none is invented:
        an unrelated staff slot does not become the job's date."""
        ticket = self.make_ticket("Nobody said when")
        self.make_slot(ticket, days=2)

        payload = self._company_plan()

        self.assertIsNone(self.entry(payload, f"ticket-{ticket.id}"))
        self.assertIsNotNone(
            self.entry(payload, f"ticket-{ticket.id}", "undated_entries"),
            payload["undated_entries"],
        )

    def test_a_staff_member_sees_only_jobs_they_are_on(self):
        """Not a new rule — pinned because the ruling states it: staff
        "never see the tickets they are not assigned in the work plan
        even if they have a permission to see that ticket"."""
        ticket = self.make_ticket("Not theirs", scheduled=0)
        mate = self.make_user("plantruth-other@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(user=mate, building=self.building)
        self.make_slot(ticket, days=0, user=mate)

        payload = self.plan()

        self.assertEqual(
            [e for e in payload["entries"] if e["ticket_id"] == ticket.id], []
        )


class TheDeadlineWindowTests(_Fixture):
    """W-VIEWER §4 / §5 — "managers/PA/SA start seeing the works from the
    ticket's scheduled date", every day until it is done, with how long
    is left against the deadline rather than only whether it is late."""

    def _company_plan(self, week=None):
        self.client.force_authenticate(self.company_admin)
        params = {"scope": "company"}
        if week:
            params["week"] = week
        response = self.client.get(URL, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_a_job_scheduled_before_today_and_undone_is_on_todays_column(self):
        ticket = self.make_ticket("Started Monday, still open", scheduled=-3)
        self.make_slot(ticket, days=None)

        card = self.entry(self._company_plan(), f"ticket-{ticket.id}")

        self.assertIsNotNone(card)
        self.assertEqual(card["day"], self.today.isoformat())
        self.assertEqual(card["placement"], "ROLLED")
        self.assertEqual(
            card["rolled_from"],
            (self.today - datetime.timedelta(days=3)).isoformat(),
            "the date on the record never moved; only the display did",
        )

    def test_a_window_that_contains_today_hangs_on_today(self):
        """A job planned across a fortnight is work somebody is doing
        TODAY, not an entry parked on the day the fortnight opened."""
        ticket = Ticket.objects.create(
            company=self.company,
            customer=self.customer,
            building=self.building,
            title="A fortnight of it",
            description="x",
            type=TicketType.REQUEST,
            status=TicketStatus.OPEN,
            created_by=self.super_admin,
            scheduled_start_at=self._at(-2),
            scheduled_end_at=self._at(4, hour=17),
        )
        self.make_slot(ticket, days=None)

        card = self.entry(self._company_plan(), f"ticket-{ticket.id}")

        self.assertIsNotNone(card)
        self.assertEqual(card["day"], self.today.isoformat())
        self.assertEqual(card["placement"], "PLANNED")

    def test_a_future_job_is_not_on_todays_column_yet(self):
        """"When that scheduled day comes they start seeing it" — not
        before."""
        ticket = self.make_ticket("Next week", scheduled=3)
        self.make_slot(ticket, days=None)

        card = self.entry(self._company_plan(week=self.week_of(3)), f"ticket-{ticket.id}")

        self.assertIsNotNone(card)
        self.assertEqual(
            card["day"], (self.today + datetime.timedelta(days=3)).isoformat()
        )

    def test_the_card_counts_down_to_the_deadline(self):
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            customer=self.customer,
            building=self.building,
            title="Has a promise",
            description="x",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            created_by=self.super_admin,
            preferred_date=self.today,
            deadline=self.today + datetime.timedelta(days=8),
        )
        ticket = self.make_ticket("Spawned", scheduled=0)
        ticket.extra_work_request = ew
        ticket.save(update_fields=["extra_work_request"])
        self.make_slot(ticket, days=None)

        card = self.entry(self._company_plan(), f"ticket-{ticket.id}")

        self.assertIsNotNone(card)
        self.assertEqual(card["days_until_due"], 8)
        self.assertFalse(card["is_overdue"])

    def test_and_counts_up_once_it_has_passed(self):
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            customer=self.customer,
            building=self.building,
            title="Broken promise",
            description="x",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            created_by=self.super_admin,
            preferred_date=self.today - datetime.timedelta(days=10),
            deadline=self.today - datetime.timedelta(days=2),
        )
        ticket = self.make_ticket("Spawned late", scheduled=-10)
        ticket.extra_work_request = ew
        ticket.save(update_fields=["extra_work_request"])
        self.make_slot(ticket, days=None)

        card = self.entry(self._company_plan(), f"ticket-{ticket.id}")

        self.assertIsNotNone(card)
        self.assertEqual(card["days_until_due"], -2)
        self.assertTrue(card["is_overdue"])

    def test_a_job_sitting_with_the_customer_reads_calm(self):
        """§5 — the manager sent it and is waiting on an answer. Still on
        the board (they may withdraw it); no longer shouting."""
        ticket = self.make_ticket(
            "With the customer",
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            scheduled=-4,
        )
        self.make_slot(ticket, days=None)

        payload = self._company_plan(week=self.week_of(-4))
        card = self.entry(payload, f"ticket-{ticket.id}")

        self.assertIsNotNone(card)
        self.assertTrue(card["viewer_settled"])
        self.assertEqual(payload["counts"]["late"], 0)

    def test_a_worker_who_finished_their_own_slot_reads_calm(self):
        ticket = self.make_ticket("Half of it is mine", scheduled=-6)
        slot = self.make_slot(
            ticket,
            days=-6,
            slot_status=StaffAssignmentSlotStatus.COMPLETED,
        )

        card = self.entry(self.plan(week=self.week_of(-6)), f"slot-{slot.id}")

        self.assertIsNotNone(card)
        self.assertTrue(card["viewer_settled"])


class TheThreeExamplesFromTheRulingTests(_Fixture):
    """W-VIEWER §2 / §18 — the owner's own three tickets, rebuilt from
    the values measured on crmtest on 2026-08-27, and asserted from both
    sides. This is the proof the ruling asks for, in executable form.
    """

    def _company_plan(self, week=None):
        self.client.force_authenticate(self.company_admin)
        params = {"scope": "company"}
        if week:
            params["week"] = week
        response = self.client.get(URL, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_example_1_verify_simple(self):
        """TCK-2026-000342. Ticket scheduled +3; Ahmet's window ended
        yesterday. BEFORE: one card, on today, "Planned <yesterday> —
        1 day late", for everybody. AFTER: the job is on +3 for a
        manager and Ahmet's own slot rolls onto today for Ahmet."""
        ticket = self.make_ticket("VERIFY simple", scheduled=3)
        slot = TicketStaffAssignment.objects.create(
            ticket=ticket,
            user=self.worker,
            assigned_by=self.super_admin,
            scheduled_start_at=self._at(-19),
            scheduled_end_at=self._at(-1, hour=7),
            slot_status=StaffAssignmentSlotStatus.ASSIGNED,
        )

        job = self.entry(
            self._company_plan(week=self.week_of(3)), f"ticket-{ticket.id}"
        )
        self.assertIsNotNone(job)
        self.assertEqual(
            job["day"], (self.today + datetime.timedelta(days=3)).isoformat()
        )
        self.assertEqual(job["placement"], "PLANNED")
        self.assertIsNone(job["lateness"]["level"], "the job is not late")

        mine = self.entry(self.plan(), f"slot-{slot.id}")
        self.assertIsNotNone(mine)
        self.assertEqual(mine["day"], self.today.isoformat())
        self.assertEqual(mine["placement"], "ROLLED")
        self.assertEqual(
            mine["rolled_from"],
            (self.today - datetime.timedelta(days=1)).isoformat(),
        )
        self.assertEqual(mine["rolled_days"], 1)

    def test_example_2_verify_day_model_evening(self):
        """TCK-2026-000361. Ticket scheduled +11 (7 September); Ahmet's
        slot on -2 (29 August). BEFORE: the whole job sat on 29 August.
        AFTER: 7 September for a manager, 29 August for Ahmet."""
        ticket = self.make_ticket(
            "VERIFY day-model — Evening", TicketStatus.IN_PROGRESS, scheduled=11
        )
        slot = self.make_slot(ticket, days=-2)

        scheduled_week = self._company_plan(week=self.week_of(11))
        job = self.entry(scheduled_week, f"ticket-{ticket.id}")
        self.assertIsNotNone(job, "the job belongs in its scheduled week")
        self.assertEqual(
            job["day"], (self.today + datetime.timedelta(days=11)).isoformat()
        )

        slot_week = self._company_plan(week=self.week_of(-2))
        self.assertIsNone(
            self.entry(slot_week, f"ticket-{ticket.id}"),
            "a slot's day must not pull the job into that week",
        )

        mine = self.entry(self.plan(), f"slot-{slot.id}")
        self.assertIsNotNone(mine)
        self.assertEqual(mine["day"], self.today.isoformat())
        self.assertEqual(mine["placement"], "ROLLED")
        self.assertEqual(mine["rolled_days"], 2)

    def test_example_3_the_sara(self):
        """TCK-2026-000364. The ticket and every slot on the same day —
        naturally consistent, and it must STAY consistent: both readers
        see it on that one day."""
        ticket = self.make_ticket("The Sara", scheduled=0)
        mate = self.make_user("plantruth-sara@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(user=mate, building=self.building)
        mine = self.make_slot(ticket, days=0)
        self.make_slot(ticket, days=0, user=mate)

        job = self.entry(self._company_plan(), f"ticket-{ticket.id}")
        self.assertIsNotNone(job)
        self.assertEqual(job["day"], self.today.isoformat())
        self.assertEqual(job["placement"], "PLANNED")
        self.assertEqual(job["assignee_count"], 2, "one card, two names")

        card = self.entry(self.plan(), f"slot-{mine.id}")
        self.assertIsNotNone(card)
        self.assertEqual(card["day"], self.today.isoformat())


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
    """§3c — the door the people running the job did not have.

    W-VIEWER §10 — and it now asks WHY, in both directions, because this
    door closes work on somebody else's behalf."""

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
        response = self.client.post(
            self.url, {"done": True, "reason": "Confirmed on site"}, format="json"
        )

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
        self.client.post(
            self.url, {"done": True, "reason": "Confirmed on site"}, format="json"
        )
        response = self.client.post(
            self.url, {"done": False, "reason": "Was not finished after all"},
            format="json",
        )

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
        response = self.client.post(
            self.url, {"done": True, "reason": "Confirmed on site"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_a_part_nobody_is_on_is_refused_with_its_own_code(self):
        empty = SubTask.objects.create(ticket=self.ticket, title="Nobody")
        self.client.force_authenticate(self.company_admin)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/sub-tasks/{empty.id}/done/",
            {"done": True, "reason": "Confirmed on site"},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "part_has_nobody")

    def test_staff_are_refused_at_this_door(self):
        """A worker finishes their OWN slot; this is the manager door
        and STAFF never pass `_gate_actor`."""
        self.client.force_authenticate(self.worker)
        response = self.client.post(
            self.url, {"done": True, "reason": "Confirmed on site"}, format="json"
        )
        self.assertEqual(response.status_code, 403, response.data)

    def test_another_tenants_ticket_is_a_404_not_a_403(self):
        """H-1 — out of scope is indistinguishable from nonexistent."""
        outsider = self.make_user(
            "plantruth-outsider@example.com", UserRole.COMPANY_ADMIN
        )
        self.client.force_authenticate(outsider)
        response = self.client.post(
            self.url, {"done": True, "reason": "Confirmed on site"}, format="json"
        )
        self.assertEqual(response.status_code, 404, response.data)

    # -- W-VIEWER §10 — the reason ------------------------------------

    def test_no_reason_is_refused_with_its_own_code(self):
        self.client.force_authenticate(self.company_admin)
        response = self.client.post(self.url, {"done": True}, format="json")

        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "part_reason_required")
        self.slot.refresh_from_db()
        self.assertEqual(
            self.slot.slot_status,
            StaffAssignmentSlotStatus.ASSIGNED,
            "a refused call writes nothing",
        )

    def test_a_blank_reason_is_refused_too(self):
        self.client.force_authenticate(self.company_admin)
        response = self.client.post(
            self.url, {"done": True, "reason": "   "}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "part_reason_required")

    def test_reopening_needs_one_as_well(self):
        self.client.force_authenticate(self.company_admin)
        self.client.post(
            self.url, {"done": True, "reason": "Confirmed on site"}, format="json"
        )
        response = self.client.post(self.url, {"done": False}, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "part_reason_required")

    def test_the_reason_lands_beside_the_completion_state(self):
        self.client.force_authenticate(self.company_admin)
        self.client.post(
            self.url,
            {"done": True, "reason": "Ahmet confirmed it by phone"},
            format="json",
        )

        self.slot.refresh_from_db()
        self.assertEqual(
            self.slot.completed_on_behalf_reason, "Ahmet confirmed it by phone"
        )
        self.assertEqual(self.slot.completed_by_id, self.company_admin.id)

    def test_the_reason_is_read_back_on_the_part(self):
        """The chip on the row reads it from here, so the API has to
        carry it — not just the database."""
        self.client.force_authenticate(self.company_admin)
        response = self.client.post(
            self.url,
            {"done": True, "reason": "Ahmet confirmed it by phone"},
            format="json",
        )
        slot = response.data["staff_assignments"][0]
        self.assertEqual(
            slot["completed_on_behalf_reason"], "Ahmet confirmed it by phone"
        )
        self.assertEqual(slot["completed_by_id"], self.company_admin.id)
        self.assertTrue(slot["completed_by_name"])

    def test_the_timeline_records_who_why_and_on_whose_behalf(self):
        from tickets.models import TicketStatusHistory

        self.client.force_authenticate(self.company_admin)
        self.client.post(
            self.url,
            {"done": True, "reason": "Ahmet confirmed it by phone"},
            format="json",
        )

        row = (
            TicketStatusHistory.objects.filter(ticket=self.ticket)
            .order_by("-id")
            .first()
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.changed_by_id, self.company_admin.id)
        self.assertIn("Ramen", row.note)
        self.assertIn("on behalf of", row.note)
        self.assertIn("Ahmet confirmed it by phone", row.note)
        self.assertEqual(
            row.old_status, row.new_status, "an annotation, not a move"
        )

    def test_the_audit_log_carries_the_reason(self):
        """H-10's shape: the field is tracked, so the write is a
        TicketStaffAssignment UPDATE row carrying before/after."""
        from audit.models import AuditLog

        self.client.force_authenticate(self.company_admin)
        self.client.post(
            self.url,
            {"done": True, "reason": "Ahmet confirmed it by phone"},
            format="json",
        )

        rows = AuditLog.objects.filter(
            target_model="tickets.TicketStaffAssignment", target_id=self.slot.id
        )
        self.assertTrue(
            any(
                "completed_on_behalf_reason" in (row.changes or {})
                for row in rows
            ),
            [row.changes for row in rows],
        )


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
