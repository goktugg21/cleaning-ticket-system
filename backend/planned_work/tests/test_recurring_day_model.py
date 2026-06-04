"""Recurring day-model — weekday sets + per-day windows + per-occurrence
billing.

Extends the planned-work engine so a WEEKLY / BIWEEKLY job runs on a SET
of ISO weekdays and in 1..N time windows (Morning / Evening), materializing
one occurrence per (date x window). Each window-occurrence is independently
priced (the existing per-occurrence override still layers on top).

The crux is BACKWARD COMPATIBILITY: an unchanged single-window job must
generate byte-identically (same dates, one occurrence per date, same
snapshot, same ticket title). The `BackwardCompatTests` prove this and the
regression guard shows the assertion is meaningful.
"""
from __future__ import annotations

import datetime
import importlib
from datetime import date, time, timedelta
from decimal import Decimal

from django.apps import apps as global_apps
from django.test import SimpleTestCase
from rest_framework import status
from rest_framework.test import APITestCase

from planned_work.generation import generate_occurrences
from planned_work.models import (
    Frequency,
    PlannedOccurrence,
    PlannedOccurrenceStatus,
    PricingMode,
    RecurringJob,
    RecurringJobWindow,
)
from planned_work.recurrence import iter_occurrence_dates
from tickets.models import Ticket

from ._base import PlannedWorkFixtureMixin


JOBS_URL = "/api/planned-work/recurring-jobs/"
OCC_URL = "/api/planned-work/planned-occurrences/"

# 2026-06-01 is a Monday (ISO weekday 1) — the anchor the legacy suite uses.
MON = datetime.date(2026, 6, 1)


# ---------------------------------------------------------------------------
# Pure recurrence engine (no DB).
# ---------------------------------------------------------------------------
class RecurrenceEngineTests(SimpleTestCase):
    def test_weekly_weekday_set_yields_all_chosen_weekdays(self):
        # Mon (1) + Thu (4), three weeks from Monday 2026-06-01.
        out = list(
            iter_occurrence_dates(
                Frequency.WEEKLY,
                MON,
                MON,
                MON + timedelta(days=20),
                None,
                weekdays=[1, 4],
            )
        )
        self.assertEqual(
            out,
            [
                date(2026, 6, 1),  # Mon
                date(2026, 6, 4),  # Thu
                date(2026, 6, 8),
                date(2026, 6, 11),
                date(2026, 6, 15),
                date(2026, 6, 18),
            ],
        )

    def test_biweekly_single_weekday_anchored_on_start(self):
        out = list(
            iter_occurrence_dates(
                Frequency.BIWEEKLY,
                MON,
                MON,
                MON + timedelta(days=35),
                None,
                weekdays=[1],
            )
        )
        # Every other Monday: 6/1 (wk0), skip 6/8, 6/15 (wk2), skip 6/22,
        # 6/29 (wk4).
        self.assertEqual(
            out, [date(2026, 6, 1), date(2026, 6, 15), date(2026, 6, 29)]
        )

    def test_biweekly_thursday_start_with_mon_thu_set(self):
        thu = date(2026, 6, 4)  # Thursday
        out = list(
            iter_occurrence_dates(
                Frequency.BIWEEKLY,
                thu,
                thu,
                thu + timedelta(days=21),
                None,
                weekdays=[1, 4],
            )
        )
        # Week 0 (start_date's ISO week): Thu 6/4 is on-week + >= start;
        # Mon 6/1 of that week is BEFORE start_date so never generated.
        # Week 1 is off. Week 2: Mon 6/15 + Thu 6/18.
        self.assertEqual(
            out, [date(2026, 6, 4), date(2026, 6, 15), date(2026, 6, 18)]
        )

    def test_monthly_ignores_weekdays_and_clamps(self):
        out = list(
            iter_occurrence_dates(
                Frequency.MONTHLY,
                date(2026, 1, 31),
                date(2026, 1, 1),
                date(2026, 4, 1),
                None,
                weekdays=[2, 5],  # ignored for MONTHLY
            )
        )
        # Byte-identical to the legacy engine: MONTHLY advances from the
        # PREVIOUS (clamped) occurrence, so once Jan-31 clamps to Feb-28 the
        # series sticks to the 28th (1/31 -> 2/28 -> 3/28), it does NOT snap
        # back to the 31st. Preserving this exactly is the backward-compat
        # contract for MONTHLY.
        self.assertEqual(
            out,
            [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 28)],
        )

    def test_empty_weekdays_falls_back_to_start_weekday(self):
        # The legacy single-weekday +7 series, proving backward compat at
        # the engine level for both None and "" (empty stored CSV).
        expected = [MON, MON + timedelta(days=7), MON + timedelta(days=14)]
        self.assertEqual(
            list(
                iter_occurrence_dates(
                    Frequency.WEEKLY,
                    MON,
                    MON,
                    MON + timedelta(days=14),
                    None,
                    weekdays=None,
                )
            ),
            expected,
        )
        self.assertEqual(
            list(
                iter_occurrence_dates(
                    Frequency.WEEKLY,
                    MON,
                    MON,
                    MON + timedelta(days=14),
                    None,
                    weekdays="",
                )
            ),
            expected,
        )

    def test_biweekly_empty_weekdays_matches_legacy_plus14(self):
        # Legacy BIWEEKLY stepped +14 from start_date; the new engine with
        # an empty weekday set must reproduce that exactly.
        self.assertEqual(
            list(
                iter_occurrence_dates(
                    Frequency.BIWEEKLY,
                    MON,
                    MON,
                    MON + timedelta(days=14),
                    None,
                    weekdays=None,
                )
            ),
            [MON, MON + timedelta(days=14)],
        )


# ---------------------------------------------------------------------------
# Generation with windows.
# ---------------------------------------------------------------------------
class WindowGenerationTests(PlannedWorkFixtureMixin, APITestCase):
    def _window(self, job, **kw):
        return RecurringJobWindow.objects.create(recurring_job=job, **kw)

    def test_am_pm_windows_yield_two_distinct_occurrences_per_date(self):
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY, start_date=MON, end_date=MON
        )
        self._window(job, label="Morning", start_time=time(9, 0), ordering=0)
        self._window(job, label="Evening", start_time=time(18, 0), ordering=1)

        counts = generate_occurrences(days_ahead=14, today=MON)

        occs = list(
            PlannedOccurrence.objects.filter(recurring_job=job).order_by(
                "source_window__ordering"
            )
        )
        self.assertEqual(len(occs), 2)
        self.assertEqual(counts["occurrences_created"], 2)
        self.assertEqual(counts["tickets_created"], 2)
        self.assertEqual(
            [o.time_window_label for o in occs], ["Morning", "Evening"]
        )
        self.assertEqual(
            [o.preferred_start_time for o in occs], [time(9, 0), time(18, 0)]
        )
        # Distinct windows + distinct tickets, titles disambiguated.
        self.assertEqual(len({o.source_window_id for o in occs}), 2)
        titles = set(
            Ticket.objects.filter(
                planned_occurrence__recurring_job=job
            ).values_list("title", flat=True)
        )
        self.assertEqual(
            titles, {"Weekly clean — Morning", "Weekly clean — Evening"}
        )

    def test_weekday_set_materializes_chosen_days_only(self):
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY, start_date=MON
        )
        RecurringJob.objects.filter(pk=job.pk).update(weekdays="1,4")
        self._window(job, label="day", start_time=time(9, 0), ordering=0)

        generate_occurrences(days_ahead=10, today=MON)  # 6/1 .. 6/11

        dates = sorted(
            PlannedOccurrence.objects.filter(recurring_job=job).values_list(
                "planned_date", flat=True
            )
        )
        self.assertEqual(
            dates,
            [
                date(2026, 6, 1),
                date(2026, 6, 4),
                date(2026, 6, 8),
                date(2026, 6, 11),
            ],
        )

    def test_per_window_pricing_override_snapshot(self):
        # Job default is CONTRACT_INCLUDED; the PM window overrides to a
        # fixed price. Each occurrence snapshots its own window's pricing.
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY, start_date=MON, end_date=MON
        )
        self._window(job, label="AM", start_time=time(9, 0), ordering=0)
        self._window(
            job,
            label="PM",
            start_time=time(18, 0),
            ordering=1,
            pricing_mode=PricingMode.FIXED,
            fixed_price=Decimal("80.00"),
            vat_pct=Decimal("21.00"),
        )

        generate_occurrences(days_ahead=14, today=MON)

        am = PlannedOccurrence.objects.get(recurring_job=job, time_window_label="AM")
        pm = PlannedOccurrence.objects.get(recurring_job=job, time_window_label="PM")
        self.assertEqual(am.pricing_mode, PricingMode.CONTRACT_INCLUDED)
        self.assertIsNone(am.fixed_price)
        self.assertEqual(pm.pricing_mode, PricingMode.FIXED)
        self.assertEqual(pm.fixed_price, Decimal("80.00"))
        self.assertEqual(pm.vat_pct, Decimal("21.00"))

    def test_idempotent_under_window_anchor(self):
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY, start_date=MON, end_date=MON
        )
        self._window(job, label="AM", start_time=time(9, 0), ordering=0)
        self._window(job, label="PM", start_time=time(18, 0), ordering=1)

        first = generate_occurrences(days_ahead=14, today=MON)
        self.assertEqual(first["occurrences_created"], 2)
        self.assertEqual(first["tickets_created"], 2)
        occ_count = PlannedOccurrence.objects.count()
        ticket_count = Ticket.objects.count()

        second = generate_occurrences(days_ahead=14, today=MON)
        self.assertEqual(second["occurrences_created"], 0)
        self.assertEqual(second["tickets_created"], 0)
        self.assertEqual(PlannedOccurrence.objects.count(), occ_count)
        self.assertEqual(Ticket.objects.count(), ticket_count)


# ---------------------------------------------------------------------------
# Backward compatibility — the load-bearing proof.
# ---------------------------------------------------------------------------
class BackwardCompatTests(PlannedWorkFixtureMixin, APITestCase):
    def test_single_window_job_generates_identically(self):
        # An existing-style job: no explicit windows / weekdays. The
        # generator's lazy default-window + the empty-weekday fallback must
        # reproduce the legacy WEEKLY-from-Monday series exactly.
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY,
            start_date=MON,
            preferred_start_time=time(9, 0),
        )

        counts = generate_occurrences(days_ahead=14, today=MON)

        dates = sorted(
            PlannedOccurrence.objects.filter(recurring_job=job).values_list(
                "planned_date", flat=True
            )
        )
        self.assertEqual(
            dates, [MON, MON + timedelta(days=7), MON + timedelta(days=14)]
        )
        self.assertEqual(counts["occurrences_created"], 3)
        self.assertEqual(counts["tickets_created"], 3)
        # Exactly one occurrence per date (no window explosion).
        for d in dates:
            self.assertEqual(
                PlannedOccurrence.objects.filter(
                    recurring_job=job, planned_date=d
                ).count(),
                1,
            )
        # Lazy default window created from the legacy schedule fields.
        self.assertEqual(job.windows.count(), 1)
        window = job.windows.first()
        self.assertEqual(window.start_time, time(9, 0))
        self.assertIsNone(window.pricing_mode)
        # Ticket title UNCHANGED (single window => no label append).
        titles = set(
            Ticket.objects.filter(
                planned_occurrence__recurring_job=job
            ).values_list("title", flat=True)
        )
        self.assertEqual(titles, {"Weekly clean"})
        # Occurrence schedule snapshot matches the legacy preferred time.
        occ = PlannedOccurrence.objects.filter(
            recurring_job=job, planned_date=MON
        ).first()
        self.assertEqual(occ.preferred_start_time, time(9, 0))

    def test_regression_guard_second_window_breaks_single_count(self):
        # Proves the backward-compat assertion above is meaningful: with a
        # second ACTIVE window the per-date count would be 2, not 1 — so a
        # regression that materialized extra windows would fail the proof.
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY,
            start_date=MON,
            end_date=MON,
            preferred_start_time=time(9, 0),
        )
        RecurringJobWindow.objects.create(
            recurring_job=job, label="AM", start_time=time(9, 0), ordering=0
        )
        RecurringJobWindow.objects.create(
            recurring_job=job, label="PM", start_time=time(18, 0), ordering=1
        )
        generate_occurrences(days_ahead=14, today=MON)
        self.assertEqual(
            PlannedOccurrence.objects.filter(
                recurring_job=job, planned_date=MON
            ).count(),
            2,
        )

    def test_all_windows_archived_generates_nothing(self):
        # A job whose windows were ALL soft-archived intentionally generates
        # nothing — the lazy default-window only fires for window-less jobs.
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY, start_date=MON
        )
        RecurringJobWindow.objects.create(
            recurring_job=job, ordering=0, is_active=False
        )
        counts = generate_occurrences(days_ahead=14, today=MON)
        self.assertEqual(counts["occurrences_created"], 0)
        self.assertEqual(
            PlannedOccurrence.objects.filter(recurring_job=job).count(), 0
        )


# ---------------------------------------------------------------------------
# API — write validation + read exposure.
# ---------------------------------------------------------------------------
class RecurringJobWindowApiTests(PlannedWorkFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.authenticate(self.super_admin)

    def test_create_with_weekdays_and_windows(self):
        payload = self.recurring_job_payload(
            frequency=Frequency.WEEKLY,
            weekdays=[1, 4],
            windows=[
                {"label": "Morning", "start_time": "09:00"},
                {"label": "Evening", "start_time": "18:00", "ordering": 1},
            ],
        )
        resp = self.client.post(JOBS_URL, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

        job = RecurringJob.objects.latest("id")
        self.assertEqual(job.weekdays, "1,4")
        self.assertEqual(
            list(job.windows.order_by("ordering").values_list("label", flat=True)),
            ["Morning", "Evening"],
        )

        detail = self.client.get(f"{JOBS_URL}{job.id}/")
        self.assertEqual(detail.data["weekdays"], [1, 4])
        self.assertEqual(len(detail.data["windows"]), 2)
        self.assertEqual(detail.data["windows"][0]["label"], "Morning")
        self.assertEqual(detail.data["windows"][1]["start_time"], "18:00:00")

    def test_legacy_payload_without_windows_or_weekdays_creates(self):
        # The existing create payload (no windows, no weekdays, WEEKLY) must
        # keep working: synthesize one window + default weekdays to
        # start_date's weekday.
        resp = self.client.post(
            JOBS_URL, self.recurring_job_payload(), format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        job = RecurringJob.objects.latest("id")
        self.assertEqual(job.windows.count(), 1)
        self.assertEqual(job.weekdays, "1")  # 2026-06-01 is Monday

    def test_weekly_empty_weekdays_rejected(self):
        payload = self.recurring_job_payload(
            frequency=Frequency.WEEKLY, weekdays=[]
        )
        resp = self.client.post(JOBS_URL, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertEqual(resp.data["weekdays"][0].code, "weekdays_required")

    def test_invalid_weekday_rejected(self):
        payload = self.recurring_job_payload(
            frequency=Frequency.WEEKLY, weekdays=[8]
        )
        resp = self.client.post(JOBS_URL, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertEqual(resp.data["weekdays"][0].code, "invalid_weekday")

    def test_empty_windows_list_rejected(self):
        payload = self.recurring_job_payload(windows=[])
        resp = self.client.post(JOBS_URL, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertEqual(resp.data["windows"][0].code, "windows_required")

    def test_window_fixed_without_price_rejected(self):
        payload = self.recurring_job_payload(
            windows=[{"label": "X", "pricing_mode": PricingMode.FIXED}]
        )
        resp = self.client.post(JOBS_URL, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertEqual(
            resp.data["windows"][0].code, "window_fixed_price_required"
        )

    def test_window_hourly_rejected(self):
        payload = self.recurring_job_payload(
            windows=[{"label": "X", "pricing_mode": PricingMode.HOURLY}]
        )
        resp = self.client.post(JOBS_URL, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertEqual(
            resp.data["windows"][0].code, "pricing_mode_not_supported"
        )

    def test_patch_removing_window_with_occurrences_soft_archives(self):
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY, start_date=MON, end_date=MON
        )
        w_am = RecurringJobWindow.objects.create(
            recurring_job=job, label="AM", start_time=time(9, 0), ordering=0
        )
        w_pm = RecurringJobWindow.objects.create(
            recurring_job=job, label="PM", start_time=time(18, 0), ordering=1
        )
        generate_occurrences(days_ahead=14, today=MON)
        self.assertEqual(
            PlannedOccurrence.objects.filter(recurring_job=job).count(), 2
        )

        resp = self.client.patch(
            f"{JOBS_URL}{job.id}/",
            {"windows": [{"id": w_am.id, "label": "AM", "start_time": "09:00"}]},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        w_pm.refresh_from_db()
        self.assertFalse(w_pm.is_active)  # soft-archived (had occurrences)
        # The PM occurrence survives (its source_window is PROTECTed).
        self.assertTrue(
            PlannedOccurrence.objects.filter(source_window=w_pm).exists()
        )
        # A re-generate does not resurrect the archived window.
        generate_occurrences(days_ahead=14, today=MON)
        self.assertEqual(
            PlannedOccurrence.objects.filter(recurring_job=job).count(), 2
        )

    def test_occurrence_serializer_exposes_source_window(self):
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY, start_date=MON, end_date=MON
        )
        RecurringJobWindow.objects.create(
            recurring_job=job, label="Morning", start_time=time(9, 0), ordering=0
        )
        generate_occurrences(days_ahead=14, today=MON)
        occ = PlannedOccurrence.objects.get(recurring_job=job)

        resp = self.client.get(f"{OCC_URL}{occ.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["source_window"], occ.source_window_id)
        self.assertEqual(resp.data["source_window_label"], "Morning")
        self.assertEqual(resp.data["source_window_start_time"], "09:00:00")


# ---------------------------------------------------------------------------
# Data migration backfill (0003).
# ---------------------------------------------------------------------------
class BackfillFunctionTests(PlannedWorkFixtureMixin, APITestCase):
    """Exercises the 0003 data migration's backfill function directly (same
    pattern as the 0002 snapshot-backfill test). On a fresh test DB the
    migration runs against zero rows, so this proves the backfill logic on
    real data: one default window per job (from the legacy schedule), the
    weekday set seeded from start_date, and every occurrence re-anchored to
    its job's default window."""

    def _backfill(self):
        module = importlib.import_module(
            "planned_work.migrations.0003_recurring_day_model"
        )
        module.backfill_windows_and_source(global_apps, None)

    def test_backfill_creates_default_window_and_weekdays(self):
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY,
            start_date=MON,
            preferred_start_time=time(8, 30),
        )
        RecurringJob.objects.filter(pk=job.pk).update(
            time_window_label="ochtend", weekdays=""
        )
        self.assertEqual(job.windows.count(), 0)

        self._backfill()

        job.refresh_from_db()
        windows = list(job.windows.all())
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].start_time, time(8, 30))
        self.assertEqual(windows[0].label, "ochtend")
        self.assertIsNone(windows[0].pricing_mode)  # job-pricing fallback
        self.assertEqual(job.weekdays, "1")  # Monday

    def test_backfill_monthly_leaves_weekdays_empty(self):
        job = self.make_recurring_job(
            frequency=Frequency.MONTHLY, start_date=date(2026, 6, 15)
        )
        self._backfill()
        job.refresh_from_db()
        self.assertEqual(job.weekdays, "")

    def test_backfill_anchors_occurrence_to_default_window(self):
        job = self.make_recurring_job(
            frequency=Frequency.WEEKLY, start_date=MON
        )
        # An occurrence anchored to a throwaway window (the schema requires
        # a non-null source_window; pre-migration rows had NULL). After the
        # backfill the job's default window (ordering=0) exists and the
        # occurrence is re-anchored to it.
        pre = RecurringJobWindow.objects.create(
            recurring_job=job, label="pre", ordering=5
        )
        occ = PlannedOccurrence.objects.create(
            recurring_job=job,
            company=job.company,
            building=job.building,
            customer=job.customer,
            planned_date=MON,
            status=PlannedOccurrenceStatus.PLANNED,
            source_window=pre,
        )

        self._backfill()

        occ.refresh_from_db()
        default = job.windows.get(ordering=0)
        self.assertEqual(occ.source_window_id, default.id)
