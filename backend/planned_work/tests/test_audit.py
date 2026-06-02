"""Sprint 11B Batch 4 — audit coverage for planned work.

Covers brief scenarios 20-21:
  20. RecurringJob CREATE / UPDATE / archive produce generic AuditLog rows
      with the right actor + diffs (H-10).
  21. PlannedOccurrence + PlannedOccurrenceStatusHistory are NEVER written
      to the generic AuditLog — the status-history row IS the H-11 audit
      trail and a generic row would double-write the same fact.
"""
from __future__ import annotations

import datetime

from rest_framework import status
from rest_framework.test import APITestCase

from audit.models import AuditAction, AuditLog
from planned_work.generation import generate_occurrences
from planned_work.lifecycle import skip_occurrence
from planned_work.models import (
    Frequency,
    PlannedOccurrence,
    PlannedOccurrenceStatus,
    RecurringJob,
)

from ._base import PlannedWorkFixtureMixin


JOBS_URL = "/api/planned-work/recurring-jobs/"
TODAY = datetime.date(2026, 6, 1)


class RecurringJobAuditTests(PlannedWorkFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # Wipe baseline audit rows the tenant fixture produced.
        AuditLog.objects.all().delete()
        self.authenticate(self.super_admin)

    def test_create_update_archive_audit_rows(self):
        # CREATE via the API.
        resp = self.client.post(
            JOBS_URL, self.recurring_job_payload(), format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        job_id = RecurringJob.objects.latest("id").id

        create_rows = AuditLog.objects.filter(
            target_model="planned_work.RecurringJob",
            action=AuditAction.CREATE,
            target_id=job_id,
        )
        self.assertGreaterEqual(create_rows.count(), 1)
        self.assertEqual(create_rows.first().actor_id, self.super_admin.id)

        # PATCH the title -> UPDATE row with the title diff.
        resp = self.client.patch(
            f"{JOBS_URL}{job_id}/",
            {"title": "Renamed clean"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        update_rows = AuditLog.objects.filter(
            target_model="planned_work.RecurringJob",
            action=AuditAction.UPDATE,
            target_id=job_id,
        )
        self.assertGreaterEqual(update_rows.count(), 1)
        latest = update_rows.order_by("-created_at").first()
        self.assertIn("title", latest.changes)
        self.assertEqual(latest.changes["title"]["after"], "Renamed clean")

        # Archive -> UPDATE row carrying the is_active / archived_at diff.
        AuditLog.objects.filter(
            target_model="planned_work.RecurringJob"
        ).exclude(pk__in=list(update_rows.values_list("pk", flat=True))).delete()
        resp = self.client.post(f"{JOBS_URL}{job_id}/archive/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        archive_rows = AuditLog.objects.filter(
            target_model="planned_work.RecurringJob",
            action=AuditAction.UPDATE,
            target_id=job_id,
        ).order_by("-created_at")
        self.assertTrue(archive_rows.exists())
        archive_changes = archive_rows.first().changes
        self.assertIn("is_active", archive_changes)


class PlannedOccurrenceNoDoubleWriteTests(PlannedWorkFixtureMixin, APITestCase):
    def test_h11_no_generic_audit_for_occurrence_or_history(self):
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY, start_date=TODAY, end_date=TODAY
        )
        AuditLog.objects.all().delete()

        # Generate (spawns the occurrence + ticket + flips to TICKET_CREATED)
        # then drive a lifecycle transition (skip is blocked once TICKET_
        # CREATED, so build a fresh PLANNED occurrence to skip).
        generate_occurrences(days_ahead=14, today=TODAY, actor=self.super_admin)

        planned = PlannedOccurrence.objects.create(
            recurring_job=job,
            company=self.company,
            building=self.building,
            customer=self.customer,
            planned_date=TODAY + datetime.timedelta(days=1),
            status=PlannedOccurrenceStatus.PLANNED,
        )
        skip_occurrence(planned, actor=self.super_admin, reason="holiday")

        self.assertEqual(
            AuditLog.objects.filter(
                target_model="planned_work.PlannedOccurrence"
            ).count(),
            0,
        )
        self.assertEqual(
            AuditLog.objects.filter(
                target_model="planned_work.PlannedOccurrenceStatusHistory"
            ).count(),
            0,
        )
