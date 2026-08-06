"""
Sprint 152.2 — the per-employee and per-building breakdowns.

The question the payload could not answer before: "in this period, who
worked in which buildings?" Both keys are additive; the pre-existing
totals / `by_hour_type` / `by_week` keep their names and shapes, which
`test_pre_existing_keys_are_unchanged` pins.
"""
from __future__ import annotations

import datetime as dt

from buildings.models import Building

from timesheets.summary import NO_BUILDING_MARKER

from .fixtures import SUMMARY_CSV_URL, SUMMARY_URL, TimesheetsFixture


MONDAY = dt.date(2026, 8, 3)
TUESDAY = dt.date(2026, 8, 4)


class SummaryBreakdownTests(TimesheetsFixture):
    """A deliberately MIXED set: two employees, two buildings, and an
    entry with no building at all.
    """

    def setUp(self):
        super().setUp()
        self.building_a2 = Building.objects.create(
            company=self.company_a, name="Building A2", address="A street 2"
        )
        # staff_a: 8h normal in building A, 4h overtime with NO building.
        self.make_entry(
            self.staff_a, MONDAY, self.normal_a, "8.00",
            building=self.building_a,
        )
        self.make_entry(
            self.staff_a, TUESDAY, self.overtime_a, "4.00",
        )
        # staff_a2: 5h normal in building A2.
        self.make_entry(
            self.staff_a2, MONDAY, self.normal_a, "5.00",
            building=self.building_a2,
        )
        # The other tenant, so isolation is asserted against real data.
        self.make_entry(
            self.staff_b, MONDAY, self.normal_b, "9.00",
            building=self.building_b,
        )

    def _summary(self, user=None, **params):
        params.setdefault("company", self.company_a.id)
        return self.api(user or self.ca_a).get(SUMMARY_URL, params).data

    def test_by_employee_totals(self):
        data = self._summary()
        by_id = {row["employee"]: row for row in data["by_employee"]}
        self.assertEqual(set(by_id), {self.staff_a.id, self.staff_a2.id})

        self.assertEqual(by_id[self.staff_a.id]["entries"], 2)
        self.assertEqual(by_id[self.staff_a.id]["hours"], "12.00")
        # 8.00 x1.00 + 4.00 x1.50 = 14.00
        self.assertEqual(by_id[self.staff_a.id]["weighted_hours"], "14.00")

        self.assertEqual(by_id[self.staff_a2.id]["entries"], 1)
        self.assertEqual(by_id[self.staff_a2.id]["hours"], "5.00")
        self.assertEqual(by_id[self.staff_a2.id]["weighted_hours"], "5.00")

    def test_by_employee_is_ordered_by_weighted_hours_desc(self):
        data = self._summary()
        self.assertEqual(
            [row["employee"] for row in data["by_employee"]],
            [self.staff_a.id, self.staff_a2.id],
        )

    def test_by_employee_carries_a_name(self):
        data = self._summary()
        row = next(
            r for r in data["by_employee"] if r["employee"] == self.staff_a.id
        )
        self.assertEqual(row["employee_name"], self.staff_a.full_name)

    def test_by_building_totals(self):
        data = self._summary()
        by_id = {row["building"]: row for row in data["by_building"]}
        self.assertEqual(
            set(by_id), {self.building_a.id, self.building_a2.id, None}
        )
        self.assertEqual(by_id[self.building_a.id]["hours"], "8.00")
        self.assertEqual(by_id[self.building_a2.id]["hours"], "5.00")

    def test_entries_without_a_building_get_their_own_bucket(self):
        """Never silently dropped: hours with no location recorded are
        exactly the ones an operator needs to notice.
        """
        data = self._summary()
        none_bucket = next(
            row for row in data["by_building"] if row["building"] is None
        )
        self.assertEqual(none_bucket["entries"], 1)
        self.assertEqual(none_bucket["hours"], "4.00")
        self.assertEqual(none_bucket["weighted_hours"], "6.00")
        # A stable SENTINEL the frontend translates — not a Dutch string
        # baked into the API.
        self.assertEqual(none_bucket["building_name"], NO_BUILDING_MARKER)

    def test_building_buckets_sum_to_the_grand_total(self):
        # The proof that nothing is dropped, independent of which bucket
        # anything landed in.
        data = self._summary()
        total = sum(float(row["hours"]) for row in data["by_building"])
        self.assertEqual(f"{total:.2f}", data["total_hours"])

    def test_employee_buckets_sum_to_the_grand_total(self):
        data = self._summary()
        total = sum(float(row["hours"]) for row in data["by_employee"])
        self.assertEqual(f"{total:.2f}", data["total_hours"])

    def test_pre_existing_keys_are_unchanged(self):
        data = self._summary()
        self.assertEqual(data["total_entries"], 3)
        self.assertEqual(data["total_hours"], "17.00")
        self.assertEqual(data["total_weighted_hours"], "19.00")
        self.assertTrue(data["by_hour_type"])
        self.assertTrue(data["by_week"])
        self.assertIn("current_multiplier", data["by_hour_type"][0])

    def test_the_period_filter_applies_to_the_new_breakdowns(self):
        data = self._summary(
            date_from=TUESDAY.isoformat(), date_to=TUESDAY.isoformat()
        )
        self.assertEqual(
            [row["employee"] for row in data["by_employee"]], [self.staff_a.id]
        )
        self.assertEqual(
            [row["building"] for row in data["by_building"]], [None]
        )


class SummaryBreakdownScopeTests(TimesheetsFixture):
    def setUp(self):
        super().setUp()
        self.make_entry(
            self.staff_a, MONDAY, self.normal_a, "8.00",
            building=self.building_a,
        )
        self.make_entry(self.staff_a2, MONDAY, self.normal_a, "5.00")
        self.make_entry(
            self.staff_b, MONDAY, self.normal_b, "9.00",
            building=self.building_b,
        )

    def test_staff_sees_only_their_own_employee_row(self):
        """`restrict_entries_to_self` still applies, so a STAFF actor's
        `by_employee` is exactly themselves. Correct, not a bug.
        """
        data = self.api(self.staff_a).get(
            SUMMARY_URL, {"company": self.company_a.id}
        ).data
        self.assertEqual(
            [row["employee"] for row in data["by_employee"]], [self.staff_a.id]
        )
        self.assertNotIn(
            self.staff_a2.full_name,
            str(data["by_employee"]),
        )

    def test_cross_company_isolation_on_the_new_keys(self):
        data = self.api(self.ca_a).get(
            SUMMARY_URL, {"company": self.company_a.id}
        ).data
        employee_ids = {row["employee"] for row in data["by_employee"]}
        building_ids = {row["building"] for row in data["by_building"]}
        self.assertNotIn(self.staff_b.id, employee_ids)
        self.assertNotIn(self.building_b.id, building_ids)

    def test_super_admin_scoped_to_the_named_company(self):
        data = self.api(self.sa).get(
            SUMMARY_URL, {"company": self.company_b.id}
        ).data
        self.assertEqual(
            [row["employee"] for row in data["by_employee"]], [self.staff_b.id]
        )
        self.assertEqual(
            [row["building"] for row in data["by_building"]],
            [self.building_b.id],
        )


class SummaryCsvBreakdownTests(TimesheetsFixture):
    def setUp(self):
        super().setUp()
        self.make_entry(
            self.staff_a, MONDAY, self.normal_a, "8.00",
            building=self.building_a,
        )
        self.make_entry(self.staff_a, TUESDAY, self.overtime_a, "4.00")

    def _csv_lines(self):
        response = self.api(self.ca_a).get(
            SUMMARY_CSV_URL, {"company": self.company_a.id}
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8").lstrip("﻿")
        return [line for line in body.splitlines() if line]

    def test_columns_are_unchanged(self):
        # The column tuple is a contract; the new sections APPEND rows,
        # they do not add or reorder columns.
        self.assertEqual(
            self._csv_lines()[0],
            "section,key,label,entries,hours,weighted_hours,is_closed,"
            "period_from,period_to",
        )

    def test_employee_and_building_sections_present(self):
        lines = self._csv_lines()
        self.assertTrue(any(line.startswith("EMPLOYEE,") for line in lines))
        self.assertTrue(any(line.startswith("BUILDING,") for line in lines))
        # And the pre-existing sections survive.
        self.assertTrue(any(line.startswith("TOTAL,") for line in lines))
        self.assertTrue(any(line.startswith("HOUR_TYPE,") for line in lines))
        self.assertTrue(any(line.startswith("WEEK,") for line in lines))

    def test_no_building_row_has_an_empty_key_and_the_marker_label(self):
        row = next(
            line
            for line in self._csv_lines()
            if line.startswith("BUILDING,") and NO_BUILDING_MARKER in line
        )
        self.assertTrue(row.startswith(f"BUILDING,,{NO_BUILDING_MARKER},"))
