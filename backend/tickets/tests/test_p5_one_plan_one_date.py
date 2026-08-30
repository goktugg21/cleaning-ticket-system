"""P-5 S1 — ONE PLAN, ONE DATE, ONE WORLD.

The owner planned the meerwerk, started the work, and the ticket then
asked him to plan AGAIN, showed its own "starts 10 Sep 04:14", and the
Plan tab displayed three date families (ticket start · requested ·
"committed on the extra work 11–25 Oct"). He closed the laptop.

The truth, and how the two records now stay one:

  * `Ticket.scheduled_start_at` is the job's date when a person set it
    on the ticket; else the meerwerk's committed window
    (`provider_planned_date`) is — `tickets/job_dates.job_window`. The
    detail now exposes the RESOLVED window (`job_start_day`,
    `job_end_day`) so the page never reads "unplanned" off a ticket
    whose meerwerk is planned.
  * A plan written on the meerwerk pushes its first AND last day onto
    the ticket (`extra_work/planned_date.py`).
  * A start set on the ticket — the transition modal, the schedule
    card — mirrors onto the meerwerk (`tickets/schedule.py`).
"""
from __future__ import annotations

from datetime import date, datetime

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from extra_work.models import (
    ExtraWorkCategory,
    ExtraWorkRequest,
    ExtraWorkRoutingDecision,
    ExtraWorkStatus,
)
from extra_work.planned_date import apply_planned_date_to_tickets
from test_utils import TenantFixtureMixin
from tickets.models import TicketStatus


class OnePlanOneDateTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Gevel reinigen",
            description="",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            routing_decision=ExtraWorkRoutingDecision.INSTANT,
            preferred_date=date(2026, 9, 10),
            deadline=date(2026, 9, 10),
        )
        self.ticket.extra_work_request = self.ew
        self.ticket.save(update_fields=["extra_work_request", "updated_at"])

    def _detail(self):
        self.authenticate(self.manager)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data

    def test_the_detail_reads_the_meerwerk_window_when_the_ticket_has_none(self):
        self.ew.provider_planned_date = date(2026, 10, 11)
        self.ew.provider_planned_end_date = date(2026, 10, 25)
        self.ew.save(update_fields=["provider_planned_date", "provider_planned_end_date"])

        data = self._detail()
        self.assertIsNone(data["scheduled_start_day"])
        self.assertEqual(data["job_start_day"], "2026-10-11")
        self.assertEqual(data["job_end_day"], "2026-10-25")
        self.assertEqual(data["plan_source"], "PROVIDER_PLAN")

    def test_the_plan_pushes_first_and_last_day_onto_the_ticket(self):
        self.ew.provider_planned_date = date(2026, 10, 11)
        self.ew.provider_planned_end_date = date(2026, 10, 25)
        self.ew.save(update_fields=["provider_planned_date", "provider_planned_end_date"])

        result = apply_planned_date_to_tickets(self.ew)
        self.assertEqual(result["moved"], [self.ticket.id])
        self.ticket.refresh_from_db()
        self.assertEqual(timezone.localtime(self.ticket.scheduled_start_at).date(), date(2026, 10, 11))
        self.assertEqual(timezone.localtime(self.ticket.scheduled_end_at).date(), date(2026, 10, 25))

        # A one-day plan clears the end again.
        self.ew.provider_planned_end_date = None
        self.ew.save(update_fields=["provider_planned_end_date"])
        apply_planned_date_to_tickets(self.ew)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.scheduled_end_at)

    def test_a_start_set_on_the_ticket_lands_on_the_meerwerk(self):
        self.authenticate(self.manager)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/schedule/",
            {
                "scheduled_start_at": "2026-09-10T00:00:00",
                "scheduled_end_at": "2026-09-12T00:00:00",
                "time_window_label": "",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.ew.refresh_from_db()
        self.assertEqual(self.ew.provider_planned_date, date(2026, 9, 10))
        self.assertEqual(self.ew.provider_planned_end_date, date(2026, 9, 12))

        data = self._detail()
        self.assertEqual(data["job_start_day"], "2026-09-10")
        self.assertEqual(data["job_end_day"], "2026-09-12")
        # Date-only: no phantom clock.
        self.assertIsNone(data["scheduled_start_time"])

    def test_the_transition_modals_start_lands_on_the_meerwerk_too(self):
        self.authenticate(self.manager)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/status/",
            {
                "to_status": TicketStatus.ACKNOWLEDGED,
                "scheduled_start_at": "2026-09-10T00:00:00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.ew.refresh_from_db()
        self.assertEqual(self.ew.provider_planned_date, date(2026, 9, 10))
        self.assertIsNone(self.ew.provider_planned_end_date)
        self.assertIsNone(response.data["scheduled_start_time"])
        self.assertEqual(response.data["job_start_day"], "2026-09-10")

    def test_moving_the_start_keeps_a_later_last_work_day(self):
        """P-4 (2): moving a plan never shifts the last work day."""
        self.ew.provider_planned_date = date(2026, 10, 11)
        self.ew.provider_planned_end_date = date(2026, 10, 25)
        self.ew.save(update_fields=["provider_planned_date", "provider_planned_end_date"])
        self.authenticate(self.manager)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/schedule/",
            {"scheduled_start_at": "2026-10-13T00:00:00", "time_window_label": ""},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.ew.refresh_from_db()
        self.assertEqual(self.ew.provider_planned_date, date(2026, 10, 13))
        self.assertEqual(self.ew.provider_planned_end_date, date(2026, 10, 25))

    def test_a_plain_ticket_has_no_meerwerk_to_mirror_onto(self):
        self.ticket.extra_work_request = None
        self.ticket.save(update_fields=["extra_work_request"])
        self.authenticate(self.manager)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/schedule/",
            {"scheduled_start_at": "2026-09-10T00:00:00", "time_window_label": ""},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        data = self._detail()
        self.assertEqual(data["job_start_day"], "2026-09-10")
        self.assertIsNone(data["job_end_day"])
        self.assertIsInstance(datetime.fromisoformat(data["scheduled_start_at"]), datetime)
