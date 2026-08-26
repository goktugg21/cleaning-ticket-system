"""W-LATE §3 — parts get windows.

§3a  a part may carry a day, a range or a day with a clock hint; the
     server refuses a window outside the ticket's own window with a
     stable 400 that names the field.
§3b  the Work Plan carries each part's window and STATE, and a part
     windowed into a week places its ticket in that week.
§3c  completing a ticket with open parts is never blocked.
"""
from __future__ import annotations

import datetime

from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from test_utils import TenantFixtureMixin
from tickets import part_windows
from tickets.models import (
    StaffAssignmentSlotStatus,
    SubTask,
    TicketStaffAssignment,
    TicketStatus,
)
from tickets.state_machine import apply_transition


class _Fixture(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.worker = self.make_user("late3-worker@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=self.worker)
        BuildingStaffVisibility.objects.create(user=self.worker, building=self.building)
        self.ticket.status = TicketStatus.IN_PROGRESS
        self.ticket.save(update_fields=["status"])

    def _at(self, days, hour=9):
        naive = datetime.datetime.combine(
            self.today + datetime.timedelta(days=days), datetime.time(hour, 0)
        )
        return timezone.make_aware(naive)

    def _day(self, days):
        return (self.today + datetime.timedelta(days=days)).isoformat()

    def _window(self, start_days, end_days=None):
        """The ticket's own window: planned start, optional planned end."""
        self.ticket.scheduled_start_at = self._at(start_days)
        self.ticket.scheduled_end_at = self._at(end_days) if end_days is not None else None
        self.ticket.save(update_fields=["scheduled_start_at", "scheduled_end_at"])

    def _url(self, sub_task_id=None):
        base = f"/api/tickets/{self.ticket.id}/sub-tasks/"
        return f"{base}{sub_task_id}/" if sub_task_id else base

    def _slot(self, user=None, sub_task=None, days=None, status=StaffAssignmentSlotStatus.ASSIGNED):
        return TicketStaffAssignment.objects.create(
            ticket=self.ticket,
            user=user or self.worker,
            sub_task=sub_task,
            assigned_by=self.company_admin,
            scheduled_start_at=self._at(days) if days is not None else None,
            slot_status=status,
        )


class TheWindowRulesTests(_Fixture):
    def test_a_day_inside_the_ticket_window_is_accepted(self):
        self._window(0, 4)
        self.authenticate(self.company_admin)
        response = self.client.post(
            self._url(),
            {"title": "Ramen", "planned_start_date": self._day(2), "time_window_label": "08:00-10:00"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["planned_start_date"], self._day(2))
        self.assertIsNone(response.data["planned_end_date"])
        self.assertEqual(response.data["time_window_label"], "08:00-10:00")
        self.assertEqual(response.data["window_state"], "OPEN")

    def test_a_range_inside_the_window_is_accepted(self):
        self._window(0, 6)
        self.authenticate(self.company_admin)
        response = self.client.post(
            self._url(),
            {"title": "Vloer", "planned_start_date": self._day(1), "planned_end_date": self._day(3)},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_a_window_outside_the_ticket_is_refused_at_the_field(self):
        self._window(0, 4)
        self.authenticate(self.company_admin)
        response = self.client.post(
            self._url(),
            {"title": "Ramen", "planned_start_date": self._day(2), "planned_end_date": self._day(9)},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], part_windows.ERR_OUTSIDE_TICKET)
        self.assertEqual(response.data["field"], "planned_end_date")
        self.assertIn("planned_end_date", response.data)

    def test_a_start_before_the_ticket_is_refused_at_the_start_field(self):
        self._window(0, 4)
        self.authenticate(self.company_admin)
        response = self.client.post(
            self._url(), {"title": "Ramen", "planned_start_date": self._day(-1)}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], part_windows.ERR_OUTSIDE_TICKET)
        self.assertEqual(response.data["field"], "planned_start_date")

    def test_an_end_before_the_start_is_refused(self):
        self._window(0, 6)
        self.authenticate(self.company_admin)
        response = self.client.post(
            self._url(),
            {"title": "Ramen", "planned_start_date": self._day(3), "planned_end_date": self._day(1)},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], part_windows.ERR_END_BEFORE_START)
        self.assertEqual(response.data["field"], "planned_end_date")

    def test_the_deadline_widens_the_ticket_window(self):
        # Planned Monday, owed by Friday: a part on Thursday is inside.
        self._window(0)
        ew = ExtraWorkRequest.objects.create(
            company=self.company, building=self.building, customer=self.customer,
            created_by=self.company_admin, title="x", description="x",
            deadline=self.today + datetime.timedelta(days=4),
            status=ExtraWorkStatus.IN_PROGRESS,
        )
        self.ticket.extra_work_request = ew
        self.ticket.save(update_fields=["extra_work_request"])
        self.authenticate(self.company_admin)
        response = self.client.post(
            self._url(), {"title": "Ramen", "planned_start_date": self._day(3)}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_a_ticket_without_a_window_accepts_any_part_window(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            self._url(), {"title": "Ramen", "planned_start_date": self._day(40)}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_a_patch_is_checked_against_the_existing_start(self):
        self._window(0, 6)
        part = SubTask.objects.create(
            ticket=self.ticket, title="Ramen",
            planned_start_date=self.today + datetime.timedelta(days=3),
        )
        self.authenticate(self.company_admin)
        response = self.client.patch(
            self._url(part.id), {"planned_end_date": self._day(1)}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], part_windows.ERR_END_BEFORE_START)
        response = self.client.patch(
            self._url(part.id), {"planned_end_date": self._day(5)}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["planned_end_date"], self._day(5))

    def test_a_part_without_a_window_is_unchanged(self):
        self._window(0, 2)
        self.authenticate(self.company_admin)
        response = self.client.post(self._url(), {"title": "Plain"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(response.data["planned_start_date"])
        self.assertEqual(response.data["window_state"], "NONE")


class TheStateTests(_Fixture):
    def _part(self, start_days, end_days=None):
        return SubTask.objects.create(
            ticket=self.ticket, title="Ramen",
            planned_start_date=self.today + datetime.timedelta(days=start_days),
            planned_end_date=(
                self.today + datetime.timedelta(days=end_days) if end_days is not None else None
            ),
        )

    def test_missed_last_day_done_on_the_detail(self):
        self._window(-5, 5)
        missed = self._part(-2)
        last_day = self._part(-1, 0)
        done = self._part(-3)
        self._slot(sub_task=missed, days=-2)
        self._slot(sub_task=last_day, days=0)
        self._slot(sub_task=done, days=-3, status=StaffAssignmentSlotStatus.COMPLETED)
        self.authenticate(self.company_admin)
        payload = self.client.get(f"/api/tickets/{self.ticket.id}/").data
        states = {p["id"]: p["window_state"] for p in payload["sub_tasks"]}
        self.assertEqual(states[missed.id], "MISSED")
        self.assertEqual(states[last_day.id], "LAST_DAY")
        self.assertEqual(states[done.id], "DONE")

    def test_a_missed_part_marks_its_ticket_and_escalates_nothing(self):
        from tickets import escalations
        from tickets.models import TicketEscalation

        self._window(-5, 5)
        missed = self._part(-2)
        self._slot(days=-5)
        self._slot(sub_task=missed, days=-2)
        # The chip is red on the Work Plan...
        self.authenticate(self.worker)
        payload = self.client.get("/api/tickets/work-plan/").data
        rows = payload["entries"] + payload["late_entries"] + payload["undated_entries"]
        chips = {p["id"]: p for r in rows for p in r["parts"]}
        self.assertEqual(chips[missed.id]["state"], "MISSED")
        self.assertEqual(chips[missed.id]["planned_start"], self._day(-2))
        # ...and the ticket itself (window still open) is not late, and
        # the ladder says nothing about a missed part on its own.
        self.assertEqual(payload["late_entries"], [])
        escalations.sweep()
        self.assertFalse(TicketEscalation.objects.filter(ticket=self.ticket).exists())


class TheWorkPlanPlacesThePartTests(_Fixture):
    URL = "/api/tickets/work-plan/"

    def test_a_part_windowed_next_week_places_its_ticket_there(self):
        # The job's slot is today; the ticket is owed in twelve days;
        # one of this person's parts is windowed on day nine.
        self._window(0, 12)
        part = SubTask.objects.create(
            ticket=self.ticket, title="Ramen",
            planned_start_date=self.today + datetime.timedelta(days=9),
        )
        self._slot(days=0)
        self._slot(sub_task=part, days=0)
        next_week = self.today + datetime.timedelta(days=9)
        iso = next_week.isocalendar()
        self.authenticate(self.worker)
        payload = self.client.get(self.URL, {"week": f"{iso[0]}-W{iso[1]:02d}"}).data
        cards = [e for e in payload["entries"] if e["ticket_id"] == self.ticket.id]
        self.assertGreaterEqual(len(cards), 1, "the part's week does not show its ticket")
        card = cards[0]
        self.assertEqual(card["placement"], "PLANNED")
        self.assertEqual(card["day"], next_week.isoformat())
        self.assertIn("Ramen", [p["title"] for p in card["parts"]])
        self.assertGreaterEqual(payload["counts"]["total"], 1)

    def test_a_week_without_the_part_is_untouched(self):
        self._window(0, 12)
        part = SubTask.objects.create(
            ticket=self.ticket, title="Ramen",
            planned_start_date=self.today + datetime.timedelta(days=9),
        )
        self._slot(days=0)
        self._slot(sub_task=part, days=0)
        far = self.today + datetime.timedelta(days=21)
        iso = far.isocalendar()
        self.authenticate(self.worker)
        payload = self.client.get(self.URL, {"week": f"{iso[0]}-W{iso[1]:02d}"}).data
        self.assertEqual([e for e in payload["entries"] if e["ticket_id"] == self.ticket.id], [])


class CompletionStaysFreeTests(_Fixture):
    def test_the_state_machine_moves_a_ticket_with_open_parts(self):
        self._window(-1, 3)
        part = SubTask.objects.create(ticket=self.ticket, title="Ramen")
        self._slot(days=-1)
        self._slot(sub_task=part, days=-1)
        self.assertFalse(part.is_done())
        apply_transition(
            self.ticket, self.company_admin, TicketStatus.WAITING_MANAGER_REVIEW, note="done"
        )
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.WAITING_MANAGER_REVIEW)

    def test_the_requirements_endpoint_never_names_parts(self):
        self._window(-1, 3)
        SubTask.objects.create(ticket=self.ticket, title="Ramen")
        self._slot(days=-1)
        self.authenticate(self.company_admin)
        response = self.client.get(
            f"/api/tickets/{self.ticket.id}/transition-requirements/",
            {"to_status": TicketStatus.WAITING_MANAGER_REVIEW},
        )
        self.assertEqual(response.status_code, 200, response.data)
        keys = {r["key"] for r in response.data["requirements"]}
        self.assertNotIn("parts", keys)
        self.assertNotIn("sub_tasks", keys)

    def test_the_status_door_moves_a_ticket_with_open_parts(self):
        self._window(-1, 3)
        part = SubTask.objects.create(ticket=self.ticket, title="Ramen")
        self._slot(days=-1)
        self._slot(sub_task=part, days=-1)
        self.authenticate(self.company_admin)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {"to_status": TicketStatus.WAITING_MANAGER_REVIEW, "note": "klaar, onderdeel blijft open"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.WAITING_MANAGER_REVIEW)
