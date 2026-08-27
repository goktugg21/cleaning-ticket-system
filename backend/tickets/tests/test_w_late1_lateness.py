"""W-LATE §1 — the late ladder, and the strip it feeds.

Two halves. The first pins `tickets/lateness.py` as a pure rule: five
facts in, a rung out, with the LAW of the wave written as assertions —
a planned date never moves, a job that is not done stays on the ladder
every day. The second pins the endpoint: `late_entries` is one row per
JOB, sorted orange-to-bordeaux, carrying the same `lateness` the week
cards carry, and it never reaches across a tenant.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from test_utils import TenantFixtureMixin
from tickets import lateness
from tickets.models import (
    StaffAssignmentSlotStatus,
    SubTask,
    TicketStaffAssignment,
    TicketStatus,
)

TODAY = datetime.date(2026, 8, 26)


def _d(days: int) -> datetime.date:
    return TODAY + datetime.timedelta(days=days)


class TheLadderTests(SimpleTestCase):
    """`assess` — the one helper, one owner."""

    def _assess(self, **kwargs):
        base = dict(
            planned_start=None,
            planned_end=None,
            deadline=None,
            done=False,
            hours_booked=Decimal("0"),
            today=TODAY,
        )
        base.update(kwargs)
        return lateness.assess(**base)

    def test_nothing_dated_is_never_late(self):
        self.assertIsNone(self._assess().level)

    def test_planned_today_is_not_late_yet(self):
        self.assertIsNone(self._assess(planned_start=TODAY).level)

    def test_planned_yesterday_is_l1(self):
        result = self._assess(planned_start=_d(-1))
        self.assertEqual(result.level, lateness.LEVEL_PLANNED_PASSED)
        self.assertEqual(result.planned_days_late, 1)
        self.assertEqual(result.days_late, 1)
        self.assertEqual(result.planned_date, _d(-1))

    def test_the_window_end_is_the_planned_date(self):
        # Planned Monday-Wednesday, today Thursday: one day late, against
        # the END of the window, not its start.
        result = self._assess(planned_start=_d(-3), planned_end=_d(-1))
        self.assertEqual(result.level, lateness.LEVEL_PLANNED_PASSED)
        self.assertEqual(result.planned_days_late, 1)
        self.assertEqual(result.planned_date, _d(-1))

    def test_a_plan_in_the_past_with_a_deadline_ahead_is_still_l1(self):
        # The plan is broken even though the promise is not — the rung
        # the overdue list could not name.
        result = self._assess(planned_start=_d(-2), deadline=_d(+5))
        self.assertEqual(result.level, lateness.LEVEL_PLANNED_PASSED)
        self.assertIsNone(result.deadline_days_late)

    def test_deadline_passed_is_l2(self):
        result = self._assess(planned_start=_d(-6), deadline=_d(-2))
        self.assertEqual(result.level, lateness.LEVEL_DEADLINE_PASSED)
        self.assertEqual(result.deadline_days_late, 2)
        self.assertEqual(result.planned_days_late, 6)

    def test_deadline_passed_with_no_plan_is_l2_and_days_late_is_the_deadlines(self):
        result = self._assess(deadline=_d(-4))
        self.assertEqual(result.level, lateness.LEVEL_DEADLINE_PASSED)
        self.assertIsNone(result.planned_days_late)
        self.assertEqual(result.days_late, 4)

    def test_thirty_days_past_the_deadline_with_no_hours_is_l3(self):
        result = self._assess(planned_start=_d(-40), deadline=_d(-30))
        self.assertEqual(result.level, lateness.LEVEL_NEVER_DONE)
        self.assertEqual(result.anchor, _d(-30))
        self.assertEqual(result.anchor_days, 30)

    def test_twenty_nine_days_is_not_yet_never_done(self):
        result = self._assess(planned_start=_d(-40), deadline=_d(-29))
        self.assertEqual(result.level, lateness.LEVEL_DEADLINE_PASSED)

    def test_the_anchor_is_the_planned_date_when_there_is_no_deadline(self):
        result = self._assess(planned_start=_d(-31))
        self.assertEqual(result.level, lateness.LEVEL_NEVER_DONE)
        self.assertEqual(result.anchor, _d(-31))

    def test_one_booked_hour_keeps_a_job_out_of_never_done(self):
        result = self._assess(
            planned_start=_d(-45), deadline=_d(-40), hours_booked=Decimal("0.5")
        )
        self.assertEqual(result.level, lateness.LEVEL_DEADLINE_PASSED)
        self.assertEqual(result.hours_booked, Decimal("0.5"))

    def test_done_work_is_never_late(self):
        result = self._assess(planned_start=_d(-90), deadline=_d(-60), done=True)
        self.assertIsNone(result.level)
        # The dates are still reported — a finished card may still say
        # when it was planned — but no rung is claimed.
        self.assertEqual(result.planned_date, _d(-90))

    def test_the_law_a_planned_date_never_moves(self):
        """Ask on three consecutive days; the planned date is the same
        value each time and the job climbs by exactly one day."""
        planned = _d(-1)
        seen = [
            lateness.assess(
                planned_start=planned,
                planned_end=None,
                deadline=None,
                done=False,
                hours_booked=Decimal("0"),
                today=_d(offset),
            )
            for offset in (0, 1, 2)
        ]
        self.assertEqual([r.planned_date for r in seen], [planned] * 3)
        self.assertEqual([r.planned_days_late for r in seen], [1, 2, 3])

    def test_sort_key_reads_orange_to_bordeaux(self):
        l1_fresh = self._assess(planned_start=_d(-1))
        l1_old = self._assess(planned_start=_d(-10))
        l2 = self._assess(planned_start=_d(-3), deadline=_d(-1))
        l3 = self._assess(deadline=_d(-45))
        cards = [l3, l2, l1_old, l1_fresh]
        ordered = sorted(cards, key=lateness.sort_key)
        self.assertEqual(ordered, [l1_fresh, l1_old, l2, l3])

    def test_as_dict_is_json_safe(self):
        data = self._assess(planned_start=_d(-1), hours_booked=Decimal("1.25")).as_dict()
        self.assertEqual(data["level"], 1)
        self.assertEqual(data["planned_date"], _d(-1).isoformat())
        self.assertEqual(data["hours_booked"], "1.25")
        self.assertEqual(data["days_late"], 1)


class ThePartStateTests(SimpleTestCase):
    def _state(self, **kwargs):
        base = dict(planned_start=None, planned_end=None, is_done=False, today=TODAY)
        base.update(kwargs)
        return lateness.part_state(**base)

    def test_no_window_is_none(self):
        self.assertEqual(self._state(), lateness.PART_STATE_NONE)

    def test_done_wins_whatever_the_window_says(self):
        self.assertEqual(
            self._state(planned_start=_d(-5), is_done=True), lateness.PART_STATE_DONE
        )

    def test_today_is_the_last_day(self):
        self.assertEqual(self._state(planned_start=_d(-2), planned_end=TODAY), lateness.PART_STATE_LAST_DAY)
        self.assertEqual(self._state(planned_start=TODAY), lateness.PART_STATE_LAST_DAY)

    def test_window_closed_and_not_done_is_missed(self):
        self.assertEqual(self._state(planned_start=_d(-1)), lateness.PART_STATE_MISSED)

    def test_window_still_ahead_is_open(self):
        self.assertEqual(self._state(planned_start=_d(+1)), lateness.PART_STATE_OPEN)
        self.assertEqual(self._state(planned_start=_d(-1), planned_end=_d(+1)), lateness.PART_STATE_OPEN)


class _StripFixture(TenantFixtureMixin, APITestCase):
    URL = "/api/tickets/work-plan/"

    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.worker = self._staff("late-worker@example.com")
        self.mate = self._staff("late-mate@example.com")
        self.ticket.status = TicketStatus.IN_PROGRESS
        self.ticket.save(update_fields=["status"])

    def _staff(self, email):
        user = self.make_user(email, UserRole.STAFF)
        StaffProfile.objects.create(user=user)
        BuildingStaffVisibility.objects.create(user=user, building=self.building)
        return user

    def _at(self, days, hour=9):
        naive = datetime.datetime.combine(
            self.today + datetime.timedelta(days=days), datetime.time(hour, 0)
        )
        return timezone.make_aware(naive)

    def _slot(self, ticket, user, *, days, status=StaffAssignmentSlotStatus.ASSIGNED, sub_task=None):
        return TicketStaffAssignment.objects.create(
            ticket=ticket,
            user=user,
            assigned_by=self.company_admin,
            scheduled_start_at=self._at(days) if days is not None else None,
            slot_status=status,
            sub_task=sub_task,
        )

    def _plan(self, user, *, team=False):
        self.authenticate(user)
        params = {"scope": "company"} if team else {}
        response = self.client.get(self.URL, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data


class TheStripTests(_StripFixture):
    def test_a_job_planned_yesterday_is_in_the_strip_at_l1(self):
        self._slot(self.ticket, self.worker, days=-1)
        payload = self._plan(self.worker)
        self.assertEqual(payload["counts"]["late"], 1)
        [row] = payload["late_entries"]
        self.assertEqual(row["ticket_id"], self.ticket.id)
        self.assertEqual(row["lateness"]["level"], 1)
        self.assertEqual(row["lateness"]["planned_days_late"], 1)
        self.assertEqual(row["lateness"]["days_late"], 1)
        self.assertFalse(row["can_complete"], "the strip is a read")

    def test_a_job_planned_today_is_not_in_the_strip(self):
        self._slot(self.ticket, self.worker, days=0)
        payload = self._plan(self.worker)
        self.assertEqual(payload["late_entries"], [])
        self.assertEqual(payload["counts"]["late"], 0)
        # ...and the week card says the same thing through the same field.
        [card] = payload["entries"]
        self.assertIsNone(card["lateness"]["level"])

    def test_one_job_one_row_with_the_whole_crew(self):
        self._slot(self.ticket, self.worker, days=-2)
        self._slot(self.ticket, self.mate, days=-2)
        payload = self._plan(self.company_admin, team=True)
        rows = [r for r in payload["late_entries"] if r["ticket_id"] == self.ticket.id]
        self.assertEqual(len(rows), 1, "a two-person job became two cards")
        self.assertEqual(rows[0]["assignee_count"], 2)
        self.assertEqual(
            set(rows[0]["assignee_names"]),
            {self.worker.full_name or self.worker.email, self.mate.full_name or self.mate.email},
        )

    def test_the_crews_parts_ride_on_the_one_row(self):
        windows = SubTask.objects.create(ticket=self.ticket, title="Windows")
        kitchen = SubTask.objects.create(ticket=self.ticket, title="Kitchen")
        self._slot(self.ticket, self.worker, days=-2)
        self._slot(self.ticket, self.worker, days=-2, sub_task=windows)
        self._slot(self.ticket, self.mate, days=-2)
        self._slot(self.ticket, self.mate, days=-2, sub_task=kitchen)
        payload = self._plan(self.company_admin, team=True)
        [row] = [r for r in payload["late_entries"] if r["ticket_id"] == self.ticket.id]
        self.assertEqual({p["title"] for p in row["parts"]}, {"Windows", "Kitchen"})

    def test_the_widest_window_decides(self):
        # One slot two days ago, a colleague's slot tomorrow: the JOB is
        # not late, whatever the first slot's own date says.
        self._slot(self.ticket, self.worker, days=-2)
        self._slot(self.ticket, self.mate, days=+1)
        payload = self._plan(self.company_admin, team=True)
        self.assertEqual(
            [r for r in payload["late_entries"] if r["ticket_id"] == self.ticket.id], []
        )

    def test_work_in_review_is_not_late(self):
        self._slot(self.ticket, self.worker, days=-5)
        self.ticket.status = TicketStatus.WAITING_MANAGER_REVIEW
        self.ticket.save(update_fields=["status"])
        payload = self._plan(self.worker)
        self.assertEqual(payload["late_entries"], [])

    def test_a_completed_slot_leaves_the_strip(self):
        self._slot(
            self.ticket, self.worker, days=-5,
            status=StaffAssignmentSlotStatus.COMPLETED,
        )
        payload = self._plan(self.worker)
        self.assertEqual(payload["late_entries"], [])

    def test_the_law_a_late_job_stays_on_its_planned_date(self):
        slot = self._slot(self.ticket, self.worker, days=-3)
        payload = self._plan(self.worker)
        [row] = payload["late_entries"]
        self.assertEqual(
            row["lateness"]["planned_date"],
            timezone.localtime(slot.scheduled_start_at).date().isoformat(),
        )
        self.assertEqual(row["planned_start"], row["lateness"]["planned_date"])

    def test_thirty_one_days_with_no_hours_is_never_done(self):
        self._slot(self.ticket, self.worker, days=-31)
        payload = self._plan(self.worker)
        [row] = payload["late_entries"]
        self.assertEqual(row["lateness"]["level"], 3)
        self.assertEqual(row["lateness"]["anchor_days"], 31)
        self.assertEqual(row["lateness"]["hours_booked"], "0")

    def test_a_booked_hour_lifts_the_never_done_rung(self):
        from timesheets.models import HourSource, HourType, TimeEntry

        self._slot(self.ticket, self.worker, days=-31)
        hour_type = HourType.objects.create(
            company=self.company, name="Normal", multiplier=Decimal("1.00")
        )
        TimeEntry.objects.create(
            company=self.company,
            employee=self.worker,
            hour_type=hour_type,
            date=self.today,
            hours=Decimal("2.00"),
            multiplier_snapshot=Decimal("1.00"),
            source_type=HourSource.TICKET,
            source_id=self.ticket.id,
            created_by=self.company_admin,
        )
        payload = self._plan(self.worker)
        [row] = payload["late_entries"]
        self.assertEqual(row["lateness"]["level"], 1)
        self.assertEqual(row["lateness"]["hours_booked"], "2.00")

    def test_orange_left_bordeaux_right(self):
        # Three tickets on the same tenant, at three rungs.
        from tickets.models import Ticket

        def ticket(title):
            return Ticket.objects.create(
                company=self.company,
                building=self.building,
                customer=self.customer,
                created_by=self.company_admin,
                title=title,
                description=title,
                status=TicketStatus.IN_PROGRESS,
            )

        old = ticket("Old plan")        # L1, ten days
        recent = ticket("Recent plan")  # L1, one day
        stale = ticket("Stale")         # L3
        self._slot(old, self.worker, days=-10)
        self._slot(recent, self.worker, days=-1)
        self._slot(stale, self.worker, days=-40)
        self.ticket.delete()
        payload = self._plan(self.worker)
        self.assertEqual(
            [r["title"] for r in payload["late_entries"]],
            ["Recent plan", "Old plan", "Stale"],
        )
        self.assertEqual(
            [r["lateness"]["level"] for r in payload["late_entries"]], [1, 1, 3]
        )

    def test_a_staff_member_sees_only_their_own_late_work(self):
        self._slot(self.ticket, self.mate, days=-3)
        payload = self._plan(self.worker)
        self.assertEqual(payload["late_entries"], [])
        self.assertEqual(payload["counts"]["late"], 0)

    def test_another_tenants_late_work_never_crosses(self):
        self.other_ticket.status = TicketStatus.IN_PROGRESS
        self.other_ticket.save(update_fields=["status"])
        foreign = self.make_user("late-foreign@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=foreign)
        BuildingStaffVisibility.objects.create(user=foreign, building=self.other_building)
        self._slot(self.other_ticket, foreign, days=-9)
        self._slot(self.ticket, self.worker, days=-1)
        payload = self._plan(self.company_admin, team=True)
        ids = {r["ticket_id"] for r in payload["late_entries"]}
        self.assertIn(self.ticket.id, ids)
        self.assertNotIn(self.other_ticket.id, ids, "H-1: a foreign tenant's job leaked")

    def test_the_envelope_names_the_strip(self):
        self._slot(self.ticket, self.worker, days=-1)
        payload = self._plan(self.worker)
        self.assertIn("late_entries", payload)
        self.assertIn("late_entries", payload["limits"])
        self.assertIn("late_entries", payload["truncated"])
        self.assertFalse(payload["truncated"]["late_entries"])
