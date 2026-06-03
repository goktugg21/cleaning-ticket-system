"""The per-job generate action refuses archived recurring jobs.

Codex (PR #68) flagged that `RecurringJobViewSet.generate` calls
`generate_occurrences(jobs=RecurringJob.objects.filter(pk=job.pk))`,
which bypasses the daily generator's is_active / archived_at filter (that
filter applies only when `jobs is None`). So a per-job generate on an
ARCHIVED job spawned occurrences + tickets for archived work. These tests
lock the view-level 400 guard and confirm the active path and the daily
generator (jobs=None) are unaffected.
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from planned_work.generation import generate_occurrences
from planned_work.models import PlannedOccurrence
from tickets.models import Ticket

from ._base import PlannedWorkFixtureMixin


JOBS_URL = "/api/planned-work/recurring-jobs/"


class GenerateArchivedGuardTests(PlannedWorkFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.authenticate(self.super_admin)
        # The generate action has no injectable `today`, so a same-day
        # single-occurrence window is always inside the horizon.
        self.today = timezone.localdate()

    def _generate(self, job):
        return self.client.post(
            f"{JOBS_URL}{job.id}/generate/",
            {"days_ahead": 7},
            format="json",
        )

    def test_generate_on_archived_job_is_400_and_creates_nothing(self):
        job = self.make_recurring_job(
            start_date=self.today,
            end_date=self.today,
            is_active=False,
            archived_at=timezone.now(),
        )
        resp = self._generate(job)
        self.assertEqual(
            resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data
        )
        self.assertEqual(resp.data["code"], "recurring_job_archived")
        # No occurrences and no spawned tickets for the archived job.
        self.assertEqual(
            PlannedOccurrence.objects.filter(recurring_job=job).count(), 0
        )
        self.assertEqual(
            Ticket.objects.filter(
                planned_occurrence__recurring_job=job
            ).count(),
            0,
        )

    def test_generate_on_active_job_still_works(self):
        job = self.make_recurring_job(
            start_date=self.today,
            end_date=self.today,
        )
        resp = self._generate(job)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["occurrences_created"], 1)
        self.assertEqual(resp.data["tickets_created"], 1)
        self.assertEqual(
            PlannedOccurrence.objects.filter(recurring_job=job).count(), 1
        )

    def test_daily_generator_still_skips_archived(self):
        # The daily entry point (jobs=None) keeps skipping archived jobs;
        # this guard is view-only and does not touch that path.
        job = self.make_recurring_job(
            start_date=self.today,
            end_date=self.today,
            is_active=False,
            archived_at=timezone.now(),
        )
        counts = generate_occurrences(days_ahead=7, today=self.today)
        self.assertEqual(counts["occurrences_created"], 0)
        self.assertEqual(
            PlannedOccurrence.objects.filter(recurring_job=job).count(), 0
        )
