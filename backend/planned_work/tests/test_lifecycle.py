"""Sprint 11B Batch 4 — planned-occurrence lifecycle.

Covers brief scenarios 15-19: completion via ticket transition,
reschedule via the ticket schedule endpoint, missed sweep, skip before
spawn, and cancel after spawn (with linked-ticket soft-delete).
"""
from __future__ import annotations

import datetime

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from planned_work.generation import generate_occurrences
from planned_work.lifecycle import mark_missed_occurrences
from planned_work.models import (
    Frequency,
    PlannedOccurrence,
    PlannedOccurrenceStatus,
    PlannedOccurrenceStatusHistory,
)
from tickets.models import Ticket, TicketScheduleStatus, TicketStatus
from tickets.state_machine import apply_transition

from ._base import PlannedWorkFixtureMixin


TODAY = datetime.date(2026, 6, 1)
OCC_URL = "/api/planned-work/planned-occurrences/"


class CompletionTests(PlannedWorkFixtureMixin, APITestCase):
    def test_ticket_approved_completes_occurrence(self):
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY, start_date=TODAY, end_date=TODAY
        )
        generate_occurrences(days_ahead=14, today=TODAY)
        occ = PlannedOccurrence.objects.get(recurring_job=job)
        ticket = Ticket.objects.get(planned_occurrence=occ)

        # SA can jump straight to APPROVED (SUPER_ADMIN_CAN_TRANSITION_ANY).
        apply_transition(ticket, self.super_admin, TicketStatus.APPROVED)

        occ.refresh_from_db()
        ticket.refresh_from_db()
        self.assertEqual(
            str(occ.status), str(PlannedOccurrenceStatus.COMPLETED)
        )
        self.assertIsNotNone(occ.completed_at)
        # actual_date must be the LOCAL calendar date of the work. This job
        # has no preferred_start_time, so the ticket is scheduled at local
        # midnight on the planned date; the (UTC-stored) datetime's bare
        # .date() would be the prior day, so we pin against the LOCAL date
        # (== planned_date here) to guard the off-by-one regression.
        self.assertEqual(
            occ.actual_date,
            timezone.localtime(ticket.scheduled_start_at).date(),
        )
        self.assertEqual(occ.actual_date, occ.planned_date)
        self.assertTrue(
            PlannedOccurrenceStatusHistory.objects.filter(
                occurrence=occ,
                new_status=PlannedOccurrenceStatus.COMPLETED,
            ).exists()
        )


class RescheduleTests(PlannedWorkFixtureMixin, APITestCase):
    def test_reschedule_moves_actual_date_only(self):
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY,
            start_date=TODAY,
            end_date=TODAY,
            preferred_start_time=datetime.time(9, 0),
        )
        generate_occurrences(days_ahead=14, today=TODAY)
        occ = PlannedOccurrence.objects.get(recurring_job=job)
        ticket = Ticket.objects.get(planned_occurrence=occ)
        original_planned = occ.planned_date

        new_start = timezone.make_aware(
            datetime.datetime(2026, 6, 5, 14, 0)
        )
        self.authenticate(self.super_admin)
        resp = self.client.post(
            f"/api/tickets/{ticket.id}/schedule/",
            {
                "scheduled_start_at": new_start.isoformat(),
                "reschedule_reason": "moved",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        occ.refresh_from_db()
        self.assertEqual(
            str(occ.status), str(PlannedOccurrenceStatus.RESCHEDULED)
        )
        self.assertEqual(occ.actual_date, datetime.date(2026, 6, 5))
        # planned_date is the immutable plan-of-record.
        self.assertEqual(occ.planned_date, original_planned)
        self.assertTrue(
            PlannedOccurrenceStatusHistory.objects.filter(
                occurrence=occ,
                new_status=PlannedOccurrenceStatus.RESCHEDULED,
            ).exists()
        )


class MissedSweepTests(PlannedWorkFixtureMixin, APITestCase):
    def _make_occurrence(self, *, planned_date, status_value):
        return PlannedOccurrence.objects.create(
            recurring_job=self.make_recurring_job(start_date=planned_date),
            company=self.company,
            building=self.building,
            customer=self.customer,
            planned_date=planned_date,
            status=status_value,
        )

    def test_past_due_open_ticket_is_marked_missed(self):
        occ = self._make_occurrence(
            planned_date=TODAY - datetime.timedelta(days=5),
            status_value=PlannedOccurrenceStatus.TICKET_CREATED,
        )
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Planned",
            status=TicketStatus.OPEN,
            planned_occurrence=occ,
        )

        count = mark_missed_occurrences(today=TODAY, grace_days=1)
        self.assertEqual(count, 1)
        occ.refresh_from_db()
        self.assertEqual(
            str(occ.status), str(PlannedOccurrenceStatus.MISSED)
        )
        self.assertIsNotNone(occ.missed_at)

    def test_terminal_linked_ticket_not_marked_missed(self):
        occ = self._make_occurrence(
            planned_date=TODAY - datetime.timedelta(days=5),
            status_value=PlannedOccurrenceStatus.TICKET_CREATED,
        )
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Planned done",
            status=TicketStatus.APPROVED,
            planned_occurrence=occ,
        )
        # Linking a terminal ticket auto-completes the occurrence via the
        # ticket post_save sync signal. Reset the occurrence to
        # TICKET_CREATED via .update() (bypassing the signal) so we
        # exercise the missed-sweep's defensive guard directly: an
        # occurrence still in TICKET_CREATED whose linked ticket is
        # terminal must NOT be flipped to MISSED.
        PlannedOccurrence.objects.filter(pk=occ.pk).update(
            status=PlannedOccurrenceStatus.TICKET_CREATED,
            completed_at=None,
        )

        count = mark_missed_occurrences(today=TODAY, grace_days=1)
        self.assertEqual(count, 0)
        occ.refresh_from_db()
        self.assertEqual(
            str(occ.status), str(PlannedOccurrenceStatus.TICKET_CREATED)
        )


class SkipTests(PlannedWorkFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.authenticate(self.super_admin)

    def _planned_occurrence(self):
        job = self.make_recurring_job(start_date=TODAY)
        return PlannedOccurrence.objects.create(
            recurring_job=job,
            company=self.company,
            building=self.building,
            customer=self.customer,
            planned_date=TODAY,
            status=PlannedOccurrenceStatus.PLANNED,
        )

    def test_skip_planned_occurrence(self):
        occ = self._planned_occurrence()
        resp = self.client.post(
            f"{OCC_URL}{occ.id}/skip/", {"reason": "holiday"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        occ.refresh_from_db()
        self.assertEqual(
            str(occ.status), str(PlannedOccurrenceStatus.SKIPPED)
        )
        self.assertIsNotNone(occ.skipped_at)
        self.assertFalse(
            Ticket.objects.filter(planned_occurrence=occ).exists()
        )

    def test_skip_after_ticket_created_rejected(self):
        occ = self._planned_occurrence()
        occ.status = PlannedOccurrenceStatus.TICKET_CREATED
        occ.save(update_fields=["status"])
        resp = self.client.post(
            f"{OCC_URL}{occ.id}/skip/", {"reason": "holiday"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertEqual(resp.data["code"], "skip_not_allowed")

    def test_skip_blank_reason_rejected(self):
        occ = self._planned_occurrence()
        resp = self.client.post(
            f"{OCC_URL}{occ.id}/skip/", {"reason": ""}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)


class CancelTests(PlannedWorkFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.authenticate(self.super_admin)

    def test_cancel_soft_deletes_linked_ticket(self):
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY, start_date=TODAY, end_date=TODAY
        )
        generate_occurrences(days_ahead=14, today=TODAY)
        occ = PlannedOccurrence.objects.get(recurring_job=job)
        ticket = Ticket.objects.get(planned_occurrence=occ)

        resp = self.client.post(
            f"{OCC_URL}{occ.id}/cancel/",
            {"reason": "called off"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        occ.refresh_from_db()
        ticket.refresh_from_db()
        self.assertEqual(
            str(occ.status), str(PlannedOccurrenceStatus.CANCELLED)
        )
        self.assertIsNotNone(occ.cancelled_at)
        self.assertIsNotNone(ticket.deleted_at)
        self.assertEqual(ticket.deleted_by_id, self.super_admin.id)

    def test_cancel_terminal_occurrence_rejected(self):
        job = self.make_recurring_job(start_date=TODAY)
        occ = PlannedOccurrence.objects.create(
            recurring_job=job,
            company=self.company,
            building=self.building,
            customer=self.customer,
            planned_date=TODAY,
            status=PlannedOccurrenceStatus.COMPLETED,
        )
        resp = self.client.post(
            f"{OCC_URL}{occ.id}/cancel/",
            {"reason": "called off"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertEqual(resp.data["code"], "cancel_not_allowed")
