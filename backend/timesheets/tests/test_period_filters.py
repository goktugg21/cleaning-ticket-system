"""
Sprint 152.2 — the three input-validation bugs.

(a) A malformed `date_from` / `date_to` reached `.filter(date__gte=...)`
    raw. Django raises `django.core.exceptions.ValidationError` there,
    which DRF does not translate, so it surfaced as an unhandled 500 —
    on `/entries/`, `/summary/` AND `/summary/export.csv`, since all
    three share `_apply_entry_filters`.
(b) A REVERSED range returned an empty set, which reads as "nobody
    worked in this period" rather than "your dates are the wrong way
    round".
(c) `/weeks/close/` accepted any `iso_week` in 1..53, but not every year
    HAS 53 ISO weeks — 2025 has 52. Closing 2025-W53 created a WeekLock
    no entry could ever belong to.
"""
from __future__ import annotations

import datetime as dt

from timesheets.models import WeekLock

from .fixtures import (
    ENTRIES_URL,
    SUMMARY_CSV_URL,
    SUMMARY_URL,
    TimesheetsFixture,
    WEEK_CLOSE_URL,
)


MONDAY = dt.date(2026, 8, 3)

# Every endpoint that filters on a period. All three go through
# `_apply_entry_filters`, so all three had the same 500.
DATE_FILTERED_URLS = (ENTRIES_URL, SUMMARY_URL, SUMMARY_CSV_URL)


class MalformedPeriodTests(TimesheetsFixture):
    def setUp(self):
        super().setUp()
        self.make_entry(self.staff_a, MONDAY, self.normal_a)

    def _get(self, url, params):
        params = {"company": self.company_a.id, **params}
        return self.api(self.ca_a).get(url, params)

    def test_garbage_date_from_is_400_on_every_surface(self):
        for url in DATE_FILTERED_URLS:
            response = self._get(url, {"date_from": "notadate"})
            self.assertEqual(response.status_code, 400, url)
            self.assertEqual(
                response.data["date_from"][0].code,
                "timesheet_period_invalid",
                url,
            )

    def test_garbage_date_to_is_400_on_every_surface(self):
        for url in DATE_FILTERED_URLS:
            response = self._get(url, {"date_to": "31-12-2026"})
            self.assertEqual(response.status_code, 400, url)
            self.assertEqual(
                response.data["date_to"][0].code, "timesheet_period_invalid", url
            )

    def test_a_plausible_but_impossible_date_is_400(self):
        # Correctly SHAPED and still not a date. `strptime` rejects it;
        # a naive regex would not.
        for url in DATE_FILTERED_URLS:
            response = self._get(url, {"date_from": "2026-02-30"})
            self.assertEqual(response.status_code, 400, url)

    def test_reversed_range_is_400_not_an_empty_set(self):
        for url in DATE_FILTERED_URLS:
            response = self._get(
                url, {"date_from": "2026-08-31", "date_to": "2026-08-01"}
            )
            self.assertEqual(response.status_code, 400, url)
            self.assertEqual(
                response.data["date_from"][0].code,
                "timesheet_period_invalid",
                url,
            )

    def test_equal_from_and_to_is_a_valid_single_day(self):
        response = self._get(
            SUMMARY_URL,
            {"date_from": MONDAY.isoformat(), "date_to": MONDAY.isoformat()},
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["total_entries"], 1)

    def test_absent_period_means_no_filter(self):
        # Deliberately NOT a default window: these endpoints legitimately
        # answer "everything".
        response = self._get(SUMMARY_URL, {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_entries"], 1)

    def test_empty_string_period_means_no_filter(self):
        response = self._get(SUMMARY_URL, {"date_from": "", "date_to": ""})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_entries"], 1)

    def test_a_valid_range_still_filters(self):
        response = self._get(
            SUMMARY_URL, {"date_from": "2026-09-01", "date_to": "2026-09-30"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_entries"], 0)

    def test_staff_gets_the_same_400_not_a_500(self):
        response = self.api(self.staff_a).get(
            ENTRIES_URL, {"date_from": "notadate"}
        )
        self.assertEqual(response.status_code, 400)


class NonExistentIsoWeekTests(TimesheetsFixture):
    """2025 has 52 ISO weeks; 2026 has 53. A week number inside 1..53 is
    therefore not proof the week exists.
    """

    def test_closing_a_week_that_does_not_exist_is_400(self):
        response = self.api(self.ca_a).post(
            WEEK_CLOSE_URL, {"iso_year": 2025, "iso_week": 53}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["iso_week"][0].code, "week_invalid")
        self.assertFalse(WeekLock.objects.exists())

    def test_closing_a_week_53_that_does_exist_succeeds(self):
        # The guard must reject the impossible pair, not week 53 itself.
        self.assertEqual(dt.date.fromisocalendar(2026, 53, 1).year, 2026)
        response = self.api(self.ca_a).post(
            WEEK_CLOSE_URL, {"iso_year": 2026, "iso_week": 53}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_reopen_rejects_the_same_impossible_week(self):
        response = self.api(self.ca_a).post(
            "/api/timesheets/weeks/reopen/",
            {"iso_year": 2025, "iso_week": 53},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["iso_week"][0].code, "week_invalid")

    def test_week_status_rejects_the_same_impossible_week(self):
        response = self.api(self.staff_a).get(
            "/api/timesheets/weeks/status/",
            {"iso_year": 2025, "iso_week": 53},
        )
        self.assertEqual(response.status_code, 400)

    def test_ordinary_weeks_are_unaffected(self):
        response = self.api(self.ca_a).post(
            WEEK_CLOSE_URL, {"iso_year": 2026, "iso_week": 32}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
