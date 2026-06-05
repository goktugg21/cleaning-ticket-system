"""Sprint 6 — recurring explicit-date control (skip-date / add-date /
clear-date) + the read-only calendar projection.

Anchored on `timezone.localdate()` with relative dates so the horizon cap +
generator runs are deterministic regardless of the wall clock. The job is
WEEKLY on today's weekday, so today, +7, +14, ... are rule dates and +3 is
off-rule.
"""
import datetime

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from audit.models import AuditLog
from tickets.models import Ticket

from planned_work.generation import generate_occurrences
from planned_work.models import (
    Frequency,
    PlannedOccurrence,
    PlannedOccurrenceStatus,
    PlannedOccurrenceStatusHistory,
    RecurringJob,
)

from ._base import PlannedWorkFixtureMixin

JOBS_URL = "/api/planned-work/recurring-jobs/"


class Sprint6CalendarBase(PlannedWorkFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.authenticate(self.super_admin)
        self.today = timezone.localdate()
        self.job = self.make_recurring_job(
            frequency=Frequency.WEEKLY, start_date=self.today
        )
        self.window = self.default_window(self.job)
        self.rule_date = self.today + datetime.timedelta(days=7)  # future rule date
        self.off_date = self.today + datetime.timedelta(days=3)  # off-rule

    def _occ(self, d):
        return PlannedOccurrence.objects.filter(
            recurring_job=self.job, planned_date=d, source_window=self.window
        ).first()

    def _generate(self, days_ahead=14):
        return generate_occurrences(
            days_ahead=days_ahead,
            today=self.today,
            actor=self.super_admin,
            jobs=RecurringJob.objects.filter(pk=self.job.pk),
        )

    def _find_date(self, data, d):
        for entry in data["dates"]:
            if entry["date"] == d.isoformat():
                return entry
        return None


class SkipDateTests(Sprint6CalendarBase):
    def test_skip_future_rule_persists_and_blocks_generation(self):
        resp = self.client.post(
            f"{JOBS_URL}{self.job.id}/skip-date/",
            {"date": self.rule_date.isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        occ = self._occ(self.rule_date)
        self.assertIsNotNone(occ)
        self.assertEqual(str(occ.status), str(PlannedOccurrenceStatus.SKIPPED))
        self.assertIsNotNone(occ.skipped_at)
        # The status-history row is the H-11 audit trail.
        self.assertTrue(
            PlannedOccurrenceStatusHistory.objects.filter(
                occurrence=occ, new_status=PlannedOccurrenceStatus.SKIPPED
            ).exists()
        )

        # A later generate run must NOT spawn or reset the skipped date.
        self._generate()
        occ.refresh_from_db()
        self.assertEqual(str(occ.status), str(PlannedOccurrenceStatus.SKIPPED))
        self.assertFalse(Ticket.objects.filter(planned_occurrence=occ).exists())

    def test_skip_is_idempotent(self):
        for _ in range(2):
            resp = self.client.post(
                f"{JOBS_URL}{self.job.id}/skip-date/",
                {"date": self.rule_date.isoformat()},
                format="json",
            )
            self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        occ = self._occ(self.rule_date)
        self.assertEqual(
            PlannedOccurrence.objects.filter(
                recurring_job=self.job, planned_date=self.rule_date
            ).count(),
            1,
        )
        # No duplicate SKIPPED history row.
        self.assertEqual(
            PlannedOccurrenceStatusHistory.objects.filter(
                occurrence=occ, new_status=PlannedOccurrenceStatus.SKIPPED
            ).count(),
            1,
        )

    def test_skip_refused_when_date_has_spawned_ticket(self):
        # Materialize + spawn the `today` rule date, then try to skip it.
        self._generate(days_ahead=1)
        occ = self._occ(self.today)
        self.assertEqual(
            str(occ.status), str(PlannedOccurrenceStatus.TICKET_CREATED)
        )
        resp = self.client.post(
            f"{JOBS_URL}{self.job.id}/skip-date/",
            {"date": self.today.isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertEqual(resp.data["code"], "skip_date_has_ticket")
        occ.refresh_from_db()
        self.assertEqual(
            str(occ.status), str(PlannedOccurrenceStatus.TICKET_CREATED)
        )

    def test_skip_requires_date(self):
        resp = self.client.post(
            f"{JOBS_URL}{self.job.id}/skip-date/", {}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertEqual(resp.data["code"], "date_required")

    def test_skip_no_generic_audit(self):
        AuditLog.objects.all().delete()
        self.client.post(
            f"{JOBS_URL}{self.job.id}/skip-date/",
            {"date": self.rule_date.isoformat()},
            format="json",
        )
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


class ClearDateTests(Sprint6CalendarBase):
    def test_clear_skipped_rule_reverts_on_generate(self):
        self.client.post(
            f"{JOBS_URL}{self.job.id}/skip-date/",
            {"date": self.rule_date.isoformat()},
            format="json",
        )
        self.assertEqual(
            str(self._occ(self.rule_date).status),
            str(PlannedOccurrenceStatus.SKIPPED),
        )

        resp = self.client.post(
            f"{JOBS_URL}{self.job.id}/clear-date/",
            {"date": self.rule_date.isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertIsNone(self._occ(self.rule_date))

        # Regenerated next run -> re-ticked (PLANNED, then spawned within
        # the horizon -> TICKET_CREATED). Either way: no longer SKIPPED.
        self._generate()
        occ = self._occ(self.rule_date)
        self.assertIsNotNone(occ)
        self.assertNotEqual(
            str(occ.status), str(PlannedOccurrenceStatus.SKIPPED)
        )

    def test_clear_removes_ad_hoc(self):
        self.client.post(
            f"{JOBS_URL}{self.job.id}/add-date/",
            {"date": self.off_date.isoformat()},
            format="json",
        )
        self.assertIsNotNone(self._occ(self.off_date))
        resp = self.client.post(
            f"{JOBS_URL}{self.job.id}/clear-date/",
            {"date": self.off_date.isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertIsNone(self._occ(self.off_date))

    def test_clear_never_deletes_spawned(self):
        self._generate(days_ahead=1)  # today -> TICKET_CREATED
        occ = self._occ(self.today)
        self.assertEqual(
            str(occ.status), str(PlannedOccurrenceStatus.TICKET_CREATED)
        )
        resp = self.client.post(
            f"{JOBS_URL}{self.job.id}/clear-date/",
            {"date": self.today.isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        # The spawned occurrence is untouched.
        self.assertIsNotNone(self._occ(self.today))

    def test_clear_idempotent(self):
        self.client.post(
            f"{JOBS_URL}{self.job.id}/skip-date/",
            {"date": self.rule_date.isoformat()},
            format="json",
        )
        for _ in range(2):
            resp = self.client.post(
                f"{JOBS_URL}{self.job.id}/clear-date/",
                {"date": self.rule_date.isoformat()},
                format="json",
            )
            self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertIsNone(self._occ(self.rule_date))


class AddDateTests(Sprint6CalendarBase):
    def test_add_creates_ad_hoc_and_spawns(self):
        resp = self.client.post(
            f"{JOBS_URL}{self.job.id}/add-date/",
            {"date": self.off_date.isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        occ = self._occ(self.off_date)
        self.assertIsNotNone(occ)
        self.assertTrue(occ.is_ad_hoc)
        self.assertEqual(str(occ.status), str(PlannedOccurrenceStatus.PLANNED))
        # An ad-hoc PLANNED occurrence spawns when due, exactly like a rule one.
        self._generate(days_ahead=10)
        occ.refresh_from_db()
        self.assertTrue(occ.is_ad_hoc)
        self.assertTrue(Ticket.objects.filter(planned_occurrence=occ).exists())
        self.assertEqual(
            str(occ.status), str(PlannedOccurrenceStatus.TICKET_CREATED)
        )

    def test_add_is_idempotent(self):
        for _ in range(2):
            resp = self.client.post(
                f"{JOBS_URL}{self.job.id}/add-date/",
                {"date": self.off_date.isoformat()},
                format="json",
            )
            self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(
            PlannedOccurrence.objects.filter(
                recurring_job=self.job, planned_date=self.off_date
            ).count(),
            1,
        )
        occ = self._occ(self.off_date)
        self.assertEqual(
            PlannedOccurrenceStatusHistory.objects.filter(
                occurrence=occ
            ).count(),
            1,
        )


class CalendarProjectionTests(Sprint6CalendarBase):
    def test_calendar_merges_rule_skipped_and_adhoc(self):
        self.client.post(
            f"{JOBS_URL}{self.job.id}/skip-date/",
            {"date": self.rule_date.isoformat()},
            format="json",
        )
        self.client.post(
            f"{JOBS_URL}{self.job.id}/add-date/",
            {"date": self.off_date.isoformat()},
            format="json",
        )
        resp = self.client.get(
            f"{JOBS_URL}{self.job.id}/calendar/",
            {
                "from": self.today.isoformat(),
                "to": (self.today + datetime.timedelta(days=14)).isoformat(),
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        # today: rule-projected (unmaterialized) PLANNED.
        today_entry = self._find_date(resp.data, self.today)
        self.assertIsNotNone(today_entry)
        tw = today_entry["windows"][0]
        self.assertEqual(tw["status"], str(PlannedOccurrenceStatus.PLANNED))
        self.assertIsNone(tw["occurrence_id"])
        self.assertFalse(tw["is_ad_hoc"])

        # off-rule ad-hoc: persisted, flagged.
        adhoc_entry = self._find_date(resp.data, self.off_date)
        self.assertIsNotNone(adhoc_entry)
        aw = adhoc_entry["windows"][0]
        self.assertEqual(aw["status"], str(PlannedOccurrenceStatus.PLANNED))
        self.assertTrue(aw["is_ad_hoc"])
        self.assertIsNotNone(aw["occurrence_id"])

        # skipped rule date: persisted SKIPPED.
        skip_entry = self._find_date(resp.data, self.rule_date)
        self.assertIsNotNone(skip_entry)
        sw = skip_entry["windows"][0]
        self.assertEqual(sw["status"], str(PlannedOccurrenceStatus.SKIPPED))
        self.assertIsNotNone(sw["occurrence_id"])

    def test_calendar_respects_hard_max_horizon(self):
        resp = self.client.get(
            f"{JOBS_URL}{self.job.id}/calendar/",
            {"to": (self.today + datetime.timedelta(days=400)).isoformat()},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(
            resp.data["to"],
            (self.today + datetime.timedelta(days=366)).isoformat(),
        )

    def test_calendar_respects_end_date_cap(self):
        capped = self.make_recurring_job(
            frequency=Frequency.WEEKLY,
            start_date=self.today,
            end_date=self.today + datetime.timedelta(days=10),
        )
        self.default_window(capped)
        resp = self.client.get(
            f"{JOBS_URL}{capped.id}/calendar/",
            {
                "from": self.today.isoformat(),
                "to": (self.today + datetime.timedelta(days=30)).isoformat(),
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(
            resp.data["to"],
            (self.today + datetime.timedelta(days=10)).isoformat(),
        )

    def test_calendar_default_horizon(self):
        resp = self.client.get(f"{JOBS_URL}{self.job.id}/calendar/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["from"], self.today.isoformat())
        self.assertEqual(
            resp.data["to"],
            (self.today + datetime.timedelta(days=90)).isoformat(),
        )


class CalendarRbacTests(Sprint6CalendarBase):
    def _assert_forbidden(self, user):
        self.authenticate(user)
        for action_path, method in (
            ("skip-date", "post"),
            ("add-date", "post"),
            ("clear-date", "post"),
            ("calendar", "get"),
        ):
            url = f"{JOBS_URL}{self.job.id}/{action_path}/"
            if method == "post":
                resp = self.client.post(
                    url, {"date": self.rule_date.isoformat()}, format="json"
                )
            else:
                resp = self.client.get(url)
            self.assertIn(
                resp.status_code,
                (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
                f"{action_path} via {user}: {resp.status_code}",
            )

    def test_staff_forbidden(self):
        self._assert_forbidden(self.staff)

    def test_other_company_admin_out_of_scope(self):
        # A provider admin of another company passes the role gate but
        # get_object() runs through the scoped queryset, so a cross-company
        # job 404s on every calendar action (never a 403 leak; H-1/H-2).
        self._assert_forbidden(self.other_company_admin)
