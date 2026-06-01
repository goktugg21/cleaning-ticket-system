"""Sprint 11B Batch 4 — occurrence generation + ticket spawning.

Covers brief scenarios 8-14. `generate_occurrences` is always called
with an explicit `today` so the 14-day horizon is deterministic and not
clock-dependent.
"""
from __future__ import annotations

import datetime

from rest_framework.test import APITestCase

from planned_work.generation import generate_occurrences
from planned_work.models import (
    Frequency,
    PlannedOccurrence,
    PlannedOccurrenceStatus,
    RecurringJob,
    RecurringJobDefaultManager,
    RecurringJobDefaultStaff,
)
from planned_work.recurrence import add_months
from tickets.models import (
    Ticket,
    TicketManagerAssignment,
    TicketScheduleStatus,
    TicketStaffAssignment,
    TicketStatus,
    TicketStatusHistory,
)

from ._base import PlannedWorkFixtureMixin


TODAY = datetime.date(2026, 6, 1)


class WeeklyGenerationTests(PlannedWorkFixtureMixin, APITestCase):
    def test_weekly_three_occurrences_in_horizon(self):
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY, start_date=TODAY
        )
        counts = generate_occurrences(days_ahead=14, today=TODAY)

        dates = set(
            PlannedOccurrence.objects.filter(recurring_job=job).values_list(
                "planned_date", flat=True
            )
        )
        self.assertEqual(
            dates,
            {
                TODAY,
                TODAY + datetime.timedelta(days=7),
                TODAY + datetime.timedelta(days=14),
            },
        )
        self.assertEqual(counts["occurrences_created"], 3)
        self.assertEqual(counts["tickets_created"], 3)
        self.assertEqual(
            Ticket.objects.filter(planned_occurrence__recurring_job=job).count(),
            3,
        )


class BiweeklyGenerationTests(PlannedWorkFixtureMixin, APITestCase):
    def test_biweekly_two_occurrences_in_horizon(self):
        job = self.make_recurring_job(
            frequency=Frequency.BIWEEKLY, start_date=TODAY
        )
        counts = generate_occurrences(days_ahead=14, today=TODAY)
        dates = set(
            PlannedOccurrence.objects.filter(recurring_job=job).values_list(
                "planned_date", flat=True
            )
        )
        self.assertEqual(
            dates, {TODAY, TODAY + datetime.timedelta(days=14)}
        )
        self.assertEqual(counts["occurrences_created"], 2)


class MonthlyGenerationTests(PlannedWorkFixtureMixin, APITestCase):
    def test_add_months_clamps_to_month_end(self):
        # Jan 31 + 1 month -> Feb 28 (2026 is not a leap year).
        self.assertEqual(
            add_months(datetime.date(2026, 1, 31), 1),
            datetime.date(2026, 2, 28),
        )

    def test_monthly_generate_produces_clamped_date(self):
        anchor = datetime.date(2026, 1, 31)
        job = self.make_recurring_job(
            frequency=Frequency.MONTHLY, start_date=anchor
        )
        # Horizon must reach Feb 28; generate from Feb 1 with a 30-day
        # look-ahead so the clamped Feb-28 occurrence lands in-range.
        generate_occurrences(
            days_ahead=30, today=datetime.date(2026, 2, 1)
        )
        dates = set(
            PlannedOccurrence.objects.filter(recurring_job=job).values_list(
                "planned_date", flat=True
            )
        )
        self.assertIn(datetime.date(2026, 2, 28), dates)


class HorizonBoundaryTests(PlannedWorkFixtureMixin, APITestCase):
    def test_start_beyond_horizon_yields_nothing(self):
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY,
            start_date=TODAY + datetime.timedelta(days=30),
        )
        counts = generate_occurrences(days_ahead=14, today=TODAY)
        self.assertEqual(counts["occurrences_created"], 0)
        self.assertEqual(
            PlannedOccurrence.objects.filter(recurring_job=job).count(), 0
        )

    def test_end_date_before_today_yields_nothing(self):
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY,
            start_date=datetime.date(2026, 5, 1),
            end_date=datetime.date(2026, 5, 20),
        )
        counts = generate_occurrences(days_ahead=14, today=TODAY)
        self.assertEqual(counts["occurrences_created"], 0)
        self.assertEqual(
            PlannedOccurrence.objects.filter(recurring_job=job).count(), 0
        )

    def test_end_date_mid_horizon_caps_series(self):
        # WEEKLY from today, but end_date sits between +7 and +14, so the
        # +14 occurrence is excluded.
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY,
            start_date=TODAY,
            end_date=TODAY + datetime.timedelta(days=10),
        )
        generate_occurrences(days_ahead=14, today=TODAY)
        dates = set(
            PlannedOccurrence.objects.filter(recurring_job=job).values_list(
                "planned_date", flat=True
            )
        )
        self.assertEqual(
            dates, {TODAY, TODAY + datetime.timedelta(days=7)}
        )


class SkippedTemplateTests(PlannedWorkFixtureMixin, APITestCase):
    def test_inactive_template_generates_nothing(self):
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY, start_date=TODAY, is_active=False
        )
        counts = generate_occurrences(days_ahead=14, today=TODAY)
        self.assertEqual(counts["occurrences_created"], 0)
        self.assertEqual(
            PlannedOccurrence.objects.filter(recurring_job=job).count(), 0
        )

    def test_archived_template_generates_nothing(self):
        from django.utils import timezone

        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY,
            start_date=TODAY,
            archived_at=timezone.now(),
        )
        counts = generate_occurrences(days_ahead=14, today=TODAY)
        self.assertEqual(counts["occurrences_created"], 0)
        self.assertEqual(
            PlannedOccurrence.objects.filter(recurring_job=job).count(), 0
        )


class IdempotencyTests(PlannedWorkFixtureMixin, APITestCase):
    def test_second_run_creates_nothing(self):
        self.make_recurring_job(frequency=Frequency.WEEKLY, start_date=TODAY)

        first = generate_occurrences(days_ahead=14, today=TODAY)
        occ_count = PlannedOccurrence.objects.count()
        ticket_count = Ticket.objects.count()
        self.assertEqual(first["occurrences_created"], 3)
        self.assertEqual(first["tickets_created"], 3)

        second = generate_occurrences(days_ahead=14, today=TODAY)
        self.assertEqual(second["occurrences_created"], 0)
        self.assertEqual(second["tickets_created"], 0)
        self.assertEqual(PlannedOccurrence.objects.count(), occ_count)
        self.assertEqual(Ticket.objects.count(), ticket_count)


class GeneratedTicketCorrectnessTests(PlannedWorkFixtureMixin, APITestCase):
    def test_single_weekly_occurrence_ticket_fields(self):
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY,
            start_date=TODAY,
            end_date=TODAY,  # cap to a single occurrence
            preferred_start_time=datetime.time(9, 0),
        )
        RecurringJobDefaultStaff.objects.create(
            recurring_job=job, user=self.staff
        )
        RecurringJobDefaultManager.objects.create(
            recurring_job=job, user=self.manager
        )

        counts = generate_occurrences(days_ahead=14, today=TODAY)
        self.assertEqual(counts["occurrences_created"], 1)
        self.assertEqual(counts["tickets_created"], 1)

        occ = PlannedOccurrence.objects.get(recurring_job=job)
        ticket = Ticket.objects.get(planned_occurrence=occ)

        # Schedule seeded from planned_date + preferred_start_time (09:00
        # in TIME_ZONE).
        from django.utils import timezone

        local_start = timezone.localtime(ticket.scheduled_start_at)
        self.assertEqual(local_start.date(), TODAY)
        self.assertEqual((local_start.hour, local_start.minute), (9, 0))
        self.assertEqual(
            str(ticket.schedule_status), str(TicketScheduleStatus.SCHEDULED)
        )
        self.assertEqual(ticket.planned_occurrence_id, occ.id)
        self.assertEqual(str(ticket.status), str(TicketStatus.OPEN))

        # Initial OPEN history row with the generated-from note.
        history = TicketStatusHistory.objects.filter(
            ticket=ticket, new_status=TicketStatus.OPEN
        )
        self.assertTrue(history.exists())
        self.assertIn(
            "Generated from recurring/planned job",
            history.first().note,
        )

        # Occurrence flipped + generated_at stamped.
        self.assertEqual(
            str(occ.status), str(PlannedOccurrenceStatus.TICKET_CREATED)
        )
        self.assertIsNotNone(occ.generated_at)

        # Default crew copied onto the ticket.
        self.assertTrue(
            TicketStaffAssignment.objects.filter(
                ticket=ticket, user=self.staff
            ).exists()
        )
        self.assertTrue(
            TicketManagerAssignment.objects.filter(
                ticket=ticket, user=self.manager
            ).exists()
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to_id, self.manager.id)

        # SLA-exempt.
        self.assertEqual(ticket.sla_status, "HISTORICAL")
        self.assertIsNone(ticket.sla_due_at)

    def test_ineligible_default_crew_is_skipped(self):
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY,
            start_date=TODAY,
            end_date=TODAY,
        )
        # Insert an INELIGIBLE default manager DIRECTLY (bypassing the
        # serializer's eligibility check): other_manager is assigned to
        # other_building, NOT self.building.
        RecurringJobDefaultManager.objects.create(
            recurring_job=job, user=self.other_manager
        )

        counts = generate_occurrences(days_ahead=14, today=TODAY)
        self.assertEqual(counts["tickets_created"], 1)

        ticket = Ticket.objects.get(planned_occurrence__recurring_job=job)
        # Ineligible default manager is skipped — no crash, no assignment.
        self.assertFalse(
            TicketManagerAssignment.objects.filter(
                ticket=ticket, user=self.other_manager
            ).exists()
        )
        self.assertIsNone(ticket.assigned_to_id)
