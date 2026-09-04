"""W-FIX1 B2 (audit F24) — the transition modal's date goes through the
FRONT door.

`POST /api/tickets/<id>/status/` with `scheduled_start_at` used to write
that one column and nothing else: no `schedule_status`, no
`rescheduled_from`, no history row. Ticket 373 on crmtest read
SCHEDULED with `schedule_planned_by_name: null`. Both doors now call
`tickets.schedule.set_schedule`, and this pins what the side door
writes, what it refuses, and what it leaves alone.
"""
from __future__ import annotations

import datetime

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from test_utils import TenantFixtureMixin
from tickets.models import TicketScheduleStatus, TicketStatus, TicketStatusHistory
from tickets.schedule_history import SCHEDULE_NOTE_PREFIX


class TransitionScheduleFrontDoorTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # A move INTO work needs somebody doing it (W13-FIX); the modal
        # answers that with `assigned_staff_ids`, so the tests do too.
        self.staff = self.make_user("staff-frontdoor@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=self.staff)
        BuildingStaffVisibility.objects.create(user=self.staff, building=self.building)

    def _move(self, to_status, **answers):
        self.authenticate(self.manager)
        body = {"to_status": to_status, **answers}
        if to_status == TicketStatus.IN_PROGRESS:
            body.setdefault("assigned_staff_ids", [self.staff.id])
        return self.client.post(
            f"/api/tickets/{self.ticket.id}/status/", body, format="json"
        )

    def _schedule_rows(self):
        return TicketStatusHistory.objects.filter(
            ticket=self.ticket, note__startswith=SCHEDULE_NOTE_PREFIX
        )

    def test_first_scheduling_from_the_modal_writes_the_whole_fact(self):
        when = timezone.now() + datetime.timedelta(days=1)
        resp = self._move(TicketStatus.ACKNOWLEDGED, scheduled_start_at=when.isoformat())
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.ACKNOWLEDGED)
        self.assertEqual(self.ticket.schedule_status, TicketScheduleStatus.SCHEDULED)
        self.assertIsNone(self.ticket.rescheduled_from)
        self.assertEqual(self._schedule_rows().count(), 1)
        row = self._schedule_rows().get()
        self.assertEqual(row.changed_by_id, self.manager.id)
        self.assertIn("set:", row.note)

        detail = self.client.get(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["schedule_status"], TicketScheduleStatus.SCHEDULED)
        self.assertIsNotNone(detail.data["schedule_planned_by_name"])
        self.assertIsNotNone(detail.data["schedule_planned_at"])

    def test_an_unchanged_instant_is_not_a_write(self):
        when = timezone.now() + datetime.timedelta(days=1)
        self._move(TicketStatus.ACKNOWLEDGED, scheduled_start_at=when.isoformat())
        self.assertEqual(self._schedule_rows().count(), 1)

        resp = self._move(TicketStatus.IN_PROGRESS, scheduled_start_at=when.isoformat())
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(self._schedule_rows().count(), 1)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.schedule_status, TicketScheduleStatus.SCHEDULED)

    def test_moving_a_scheduled_ticket_without_a_note_is_refused(self):
        first = timezone.now() + datetime.timedelta(days=1)
        self._move(TicketStatus.ACKNOWLEDGED, scheduled_start_at=first.isoformat())

        later = first + datetime.timedelta(days=2)
        resp = self._move(TicketStatus.IN_PROGRESS, scheduled_start_at=later.isoformat())
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertEqual(resp.data.get("code"), "reschedule_reason_required")
        self.ticket.refresh_from_db()
        # Nothing half-written: the status did not move either.
        self.assertEqual(self.ticket.status, TicketStatus.ACKNOWLEDGED)
        self.assertEqual(self.ticket.scheduled_start_at, first)

    def test_moving_a_scheduled_ticket_with_a_note_is_a_reschedule(self):
        first = timezone.now() + datetime.timedelta(days=1)
        self._move(TicketStatus.ACKNOWLEDGED, scheduled_start_at=first.isoformat())

        later = first + datetime.timedelta(days=2)
        resp = self._move(
            TicketStatus.IN_PROGRESS,
            scheduled_start_at=later.isoformat(),
            note="Crew only free on Thursday",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.schedule_status, TicketScheduleStatus.RESCHEDULED)
        self.assertEqual(self.ticket.rescheduled_from, first)
        self.assertEqual(self.ticket.reschedule_reason, "Crew only free on Thursday")
        self.assertEqual(self._schedule_rows().count(), 2)
        self.assertIn("rescheduled:", self._schedule_rows().order_by("-id").first().note)

    def test_the_schedule_endpoint_still_writes_the_same_row(self):
        """The refactor moved the write, not the behaviour."""
        self.authenticate(self.manager)
        when = timezone.now() + datetime.timedelta(days=3)
        resp = self.client.post(
            f"/api/tickets/{self.ticket.id}/schedule/",
            {"scheduled_start_at": when.isoformat(), "time_window_label": "Morning"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.schedule_status, TicketScheduleStatus.SCHEDULED)
        self.assertEqual(self.ticket.time_window_label, "Morning")
        self.assertEqual(self._schedule_rows().count(), 1)
        self.assertIn("window=Morning", self._schedule_rows().get().note)

        resp = self.client.post(
            f"/api/tickets/{self.ticket.id}/schedule/",
            {"scheduled_start_at": (when + datetime.timedelta(days=1)).isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "reschedule_reason_required")
