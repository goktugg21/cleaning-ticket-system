"""
Sprint 171 §4 — the Worker Hour Report.

What these pin:

  * the grain: one row per (ISO week, worker, building, hour type),
    with the seven weekday columns and a total that adds up;
  * the scope: provider-management only, and never an hour the actor
    could not already read;
  * the query count: ONE aggregate for the whole period. The reference
    shows four weeks at a time and a company can have fifty workers,
    so a per-week or per-worker query is 200 queries for one table.
  * both exports render the payload the screen shows.
"""
from __future__ import annotations

from datetime import date

from django.test import TestCase
from rest_framework import status

from timesheets.tests.fixtures import TimesheetsFixture
from reports.worker_hours import week_span


URL = "/api/reports/worker-hours/"
CSV_URL = "/api/reports/worker-hours/export.csv"
PDF_URL = "/api/reports/worker-hours/export.pdf"

# A Monday and the Tuesday after it, inside one ISO week.
MONDAY = date(2026, 3, 2)
TUESDAY = date(2026, 3, 3)


class WorkerHoursFixture(TimesheetsFixture):
    def entry(self, employee, day, hours, building=None, hour_type=None):
        # The fixture's own helper, which snapshots the multiplier the
        # way the view layer does — `TimeEntry.multiplier_snapshot` is
        # NOT NULL and a hand-rolled create misses it.
        return self.make_entry(
            employee,
            day,
            hour_type or self.normal_a,
            hours=hours,
            building=building,
            company=self.company_a,
            created_by=self.ca_a,
        )

    def payload(self, user=None, **params):
        client = self.api(user or self.ca_a)
        query = {"year": 2026, "week": 10, "weeks": 1, **params}
        return client.get(URL, query)


class ShapeTests(WorkerHoursFixture):
    def test_one_row_per_week_worker_building_and_hour_type(self):
        self.entry(self.staff_a, MONDAY, "4.00", building=self.building_a)
        self.entry(self.staff_a, TUESDAY, "3.50", building=self.building_a)
        # Same worker and week, DIFFERENT building — a second row.
        self.entry(self.staff_a, MONDAY, "2.00", building=None)

        response = self.payload()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.data["rows"]
        self.assertEqual(len(rows), 2)
        by_building = {row["building_name"]: row for row in rows}
        both = by_building["Building A"]
        self.assertEqual(both["monday"], "4.00")
        self.assertEqual(both["tuesday"], "3.50")
        self.assertEqual(both["total"], "7.50")
        # A row with no building is KEPT and reads as null, not dropped:
        # hours not tied to a location are still somebody's hours.
        self.assertIn(None, by_building)
        self.assertEqual(by_building[None]["total"], "2.00")

    def test_the_weekday_columns_land_on_the_right_days(self):
        self.entry(self.staff_a, MONDAY, "1.00")
        self.entry(self.staff_a, TUESDAY, "2.00")
        row = self.payload().data["rows"][0]
        self.assertEqual(row["monday"], "1.00")
        self.assertEqual(row["tuesday"], "2.00")
        self.assertEqual(row["wednesday"], "0.00")
        self.assertEqual(row["sunday"], "0.00")

    def test_the_tiles_are_the_four_the_reference_shows(self):
        self.entry(self.staff_a, MONDAY, "4.00", building=self.building_a)
        self.entry(self.staff_a2, MONDAY, "2.00", building=self.building_a)
        totals = self.payload().data["totals"]
        self.assertEqual(totals["rows"], 2)
        self.assertEqual(totals["hours"], "6.00")
        self.assertEqual(totals["weeks"], 1)
        self.assertEqual(totals["workers"], 2)

    def test_the_span_includes_the_last_weeks_sunday(self):
        """An exclusive end silently drops one day per period, which only
        ever shows up as "the last week is short"."""
        sunday = date(2026, 3, 8)
        self.entry(self.staff_a, sunday, "5.00")
        rows = self.payload().data["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sunday"], "5.00")


class ScopingTests(WorkerHoursFixture):
    def test_a_customer_user_is_refused(self):
        response = self.payload(user=self.customer_user)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_a_staff_user_is_refused(self):
        """A per-person breakdown of the whole team's hours is
        provider-internal: STAFF file their own hours and do not read
        everybody's."""
        response = self.payload(user=self.staff_a)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_another_companys_hours_never_appear(self):
        self.entry(self.staff_a, MONDAY, "4.00", building=self.building_a)
        self.make_entry(
            self.staff_b,
            MONDAY,
            self.normal_b,
            hours="9.00",
            company=self.company_b,
            created_by=self.ca_b,
        )
        rows = self.payload().data["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total"], "4.00")


class QueryCountTests(WorkerHoursFixture):
    def test_the_whole_report_is_one_aggregate(self):
        """Not one query per week and not one per worker. The reference
        shows four weeks at a time; a per-week query would be four, and
        a per-worker one is unbounded."""
        for day in (MONDAY, TUESDAY):
            for worker in (self.staff_a, self.staff_a2):
                self.entry(worker, day, "4.00", building=self.building_a)

        client = self.api(self.ca_a)
        # FIVE, and the number is not the point — CONSTANCY is.
        #
        # The actor lookup, the main aggregate, the debtor lookup, and
        # the contract-hours read with its scope check. Sprint 171 had
        # two; Sprint 172 §5 added the debtor and contracted-hours
        # columns, and both are ONE bounded query for the whole report
        # rather than one per row. A per-row lookup of the customer
        # behind a building is the N+1 this test exists to catch.
        with self.assertNumQueries(5):
            response = client.get(
                URL, {"year": 2026, "week": 10, "weeks": 4}
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Same count with twice the rows and a second building dimension: that is the property.
        for day in (MONDAY, TUESDAY):
            for worker in (self.staff_a, self.staff_a2):
                self.entry(worker, day, "1.00", building=None)
        with self.assertNumQueries(5):
            client.get(URL, {"year": 2026, "week": 10, "weeks": 4})


class ExportTests(WorkerHoursFixture):
    def test_the_csv_carries_the_rows_the_screen_shows(self):
        self.entry(self.staff_a, MONDAY, "4.00", building=self.building_a)
        client = self.api(self.ca_a)
        response = client.get(CSV_URL, {"year": 2026, "week": 10, "weeks": 1})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.content.decode("utf-8")
        self.assertIn("iso_week", body)
        self.assertIn("Building A", body)
        self.assertIn("4.00", body)

    def test_the_pdf_renders(self):
        self.entry(self.staff_a, MONDAY, "4.00", building=self.building_a)
        client = self.api(self.ca_a)
        response = client.get(PDF_URL, {"year": 2026, "week": 10, "weeks": 1})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_an_export_is_refused_for_a_customer_role(self):
        client = self.api(self.customer_user)
        for url in (CSV_URL, PDF_URL):
            with self.subTest(url=url):
                self.assertEqual(
                    client.get(url).status_code, status.HTTP_403_FORBIDDEN
                )


class WeekSpanYearEndTests(TestCase):
    """Sprint 188 §CI — a span that runs past the end of the year.

    `week_span` used to catch the ValueError from an out-of-range week
    and clamp to 52. In a 53-WEEK ISO year that silently dropped a whole
    week of hours while the response still reported the week count asked
    for. 2026 is such a year, which is why this was worth finding now.
    """

    def test_a_53_week_year_keeps_its_53rd_week(self):
        # 2026 has 53 ISO weeks (Dec 28th is always in the last one).
        self.assertEqual(date(2026, 12, 28).isocalendar()[1], 53)
        _start, end = week_span(2026, 51, 4)
        # W53 of 2026 ends on 2027-01-03; clamping to 52 would have
        # stopped at 2026-12-27 and lost the week.
        self.assertEqual(end, date(2027, 1, 3))

    def test_a_52_week_year_still_clamps_to_52(self):
        self.assertEqual(date(2025, 12, 28).isocalendar()[1], 52)
        _start, end = week_span(2025, 51, 4)
        self.assertEqual(end, date(2025, 12, 28))

    def test_an_ordinary_span_is_untouched(self):
        start, end = week_span(2026, 29, 4)
        self.assertEqual(start, date(2026, 7, 13))
        self.assertEqual(end, date(2026, 8, 9))
