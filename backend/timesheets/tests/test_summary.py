"""
Sprint 152 — the summary endpoint and its CSV export: totals math
(raw, weighted, per type, per week), the 0.00-multiplier case, the
force-scoping of STAFF to themselves, and the export's role gate.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from timesheets.models import HourType, WeekLock

from .fixtures import SUMMARY_CSV_URL, SUMMARY_URL, TimesheetsFixture


W32_MONDAY = dt.date(2026, 8, 3)
W32_TUESDAY = dt.date(2026, 8, 4)
W33_MONDAY = dt.date(2026, 8, 10)


class SummaryMathTests(TimesheetsFixture):
    def setUp(self):
        super().setUp()
        self.unpaid = HourType.objects.create(
            company=self.company_a,
            name="Onbetaald verlof",
            multiplier=Decimal("0.00"),
            sort_order=30,
        )
        # W32: 8.00 normal (x1.00) + 4.00 overtime (x1.50) = 12.00 raw,
        #      14.00 weighted.
        self.make_entry(self.staff_a, W32_MONDAY, self.normal_a, "8.00")
        self.make_entry(self.staff_a, W32_TUESDAY, self.overtime_a, "4.00")
        # W33: 6.00 unpaid leave (x0.00) = 6.00 raw, 0.00 weighted.
        self.make_entry(self.staff_a2, W33_MONDAY, self.unpaid, "6.00")

    def _summary(self, user=None, **params):
        params.setdefault("company", self.company_a.id)
        return self.api(user or self.ca_a).get(SUMMARY_URL, params)

    def test_totals(self):
        data = self._summary().data
        self.assertEqual(data["total_entries"], 3)
        self.assertEqual(data["total_hours"], "18.00")
        self.assertEqual(data["total_weighted_hours"], "14.00")

    def test_zero_multiplier_counts_raw_but_not_weighted(self):
        data = self._summary().data
        unpaid = next(
            row
            for row in data["by_hour_type"]
            if row["hour_type"] == self.unpaid.id
        )
        self.assertEqual(unpaid["entries"], 1)
        self.assertEqual(unpaid["hours"], "6.00")
        self.assertEqual(unpaid["weighted_hours"], "0.00")

    def test_breakdown_per_hour_type(self):
        data = self._summary().data
        by_id = {row["hour_type"]: row for row in data["by_hour_type"]}
        self.assertEqual(by_id[self.normal_a.id]["hours"], "8.00")
        self.assertEqual(by_id[self.normal_a.id]["weighted_hours"], "8.00")
        self.assertEqual(by_id[self.overtime_a.id]["hours"], "4.00")
        self.assertEqual(by_id[self.overtime_a.id]["weighted_hours"], "6.00")

    def test_breakdown_per_iso_week(self):
        data = self._summary().data
        by_week = {(row["iso_year"], row["iso_week"]): row for row in data["by_week"]}
        self.assertEqual(by_week[(2026, 32)]["entries"], 2)
        self.assertEqual(by_week[(2026, 32)]["hours"], "12.00")
        self.assertEqual(by_week[(2026, 32)]["weighted_hours"], "14.00")
        self.assertEqual(by_week[(2026, 33)]["hours"], "6.00")
        self.assertEqual(by_week[(2026, 33)]["weighted_hours"], "0.00")
        self.assertEqual(by_week[(2026, 32)]["week_start"], "2026-08-03")
        self.assertEqual(by_week[(2026, 32)]["week_end"], "2026-08-09")

    def test_week_rows_report_their_lock_state(self):
        WeekLock.objects.create(
            company=self.company_a,
            iso_year=2026,
            iso_week=32,
            closed_by=self.ca_a,
        )
        data = self._summary().data
        by_week = {row["iso_week"]: row for row in data["by_week"]}
        self.assertTrue(by_week[32]["is_closed"])
        self.assertFalse(by_week[33]["is_closed"])

    def test_date_range_filter(self):
        data = self._summary(
            date_from="2026-08-10", date_to="2026-08-16"
        ).data
        self.assertEqual(data["total_entries"], 1)
        self.assertEqual(data["total_hours"], "6.00")

    def test_employee_filter(self):
        data = self._summary(employee=self.staff_a2.id).data
        self.assertEqual(data["total_entries"], 1)

    def test_hour_type_filter(self):
        data = self._summary(hour_type=self.overtime_a.id).data
        self.assertEqual(data["total_entries"], 1)
        self.assertEqual(data["total_weighted_hours"], "6.00")

    def test_building_filter(self):
        self.make_entry(
            self.staff_a,
            W33_MONDAY,
            self.normal_a,
            "2.00",
            building=self.building_a,
        )
        data = self._summary(building=self.building_a.id).data
        self.assertEqual(data["total_entries"], 1)
        self.assertEqual(data["total_hours"], "2.00")

    def test_empty_result_is_zeros_not_nulls(self):
        data = self._summary(date_from="2030-01-01").data
        self.assertEqual(data["total_entries"], 0)
        self.assertEqual(data["total_hours"], "0.00")
        self.assertEqual(data["total_weighted_hours"], "0.00")
        self.assertEqual(data["by_hour_type"], [])
        self.assertEqual(data["by_week"], [])


class SummaryScopeTests(TimesheetsFixture):
    def setUp(self):
        super().setUp()
        self.make_entry(self.staff_a, W32_MONDAY, self.normal_a, "8.00")
        self.make_entry(self.staff_a2, W32_MONDAY, self.normal_a, "5.00")
        self.make_entry(self.staff_b, W32_MONDAY, self.normal_b, "9.00")

    def test_staff_summary_is_force_scoped_to_self(self):
        data = self.api(self.staff_a).get(
            SUMMARY_URL, {"company": self.company_a.id}
        ).data
        self.assertEqual(data["total_entries"], 1)
        self.assertEqual(data["total_hours"], "8.00")

    def test_staff_cannot_widen_with_an_employee_filter(self):
        data = self.api(self.staff_a).get(
            SUMMARY_URL,
            {"company": self.company_a.id, "employee": self.staff_a2.id},
        ).data
        self.assertEqual(data["total_entries"], 0)

    def test_building_manager_is_force_scoped_to_self_too(self):
        data = self.api(self.bm_a).get(
            SUMMARY_URL, {"company": self.company_a.id}
        ).data
        self.assertEqual(data["total_entries"], 0)

    def test_company_admin_sees_the_whole_company(self):
        data = self.api(self.ca_a).get(
            SUMMARY_URL, {"company": self.company_a.id}
        ).data
        self.assertEqual(data["total_entries"], 2)
        self.assertEqual(data["total_hours"], "13.00")

    def test_admin_cannot_summarise_a_rival_company(self):
        response = self.api(self.ca_a).get(
            SUMMARY_URL, {"company": self.company_b.id}
        )
        self.assertEqual(response.status_code, 404)

    def test_customer_user_is_forbidden(self):
        self.assertEqual(
            self.api(self.customer_user).get(SUMMARY_URL).status_code, 403
        )

    def test_super_admin_must_pick_a_company(self):
        response = self.api(self.sa).get(SUMMARY_URL)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["company"][0].code, "timesheet_company_required"
        )

    def test_super_admin_summarises_the_named_company(self):
        data = self.api(self.sa).get(
            SUMMARY_URL, {"company": self.company_b.id}
        ).data
        self.assertEqual(data["total_entries"], 1)
        self.assertEqual(data["total_hours"], "9.00")


class SummaryCSVTests(TimesheetsFixture):
    def setUp(self):
        super().setUp()
        self.make_entry(self.staff_a, W32_MONDAY, self.normal_a, "8.00")
        self.make_entry(self.staff_a, W32_TUESDAY, self.overtime_a, "4.00")

    def test_csv_columns_and_rows(self):
        response = self.api(self.ca_a).get(
            SUMMARY_CSV_URL, {"company": self.company_a.id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("attachment;", response["Content-Disposition"])

        body = response.content.decode("utf-8").lstrip("﻿")
        lines = [line for line in body.splitlines() if line]
        self.assertEqual(
            lines[0],
            "section,key,label,entries,hours,weighted_hours,is_closed,"
            "period_from,period_to",
        )
        self.assertTrue(lines[1].startswith("TOTAL,"))
        self.assertIn("14.00", lines[1])
        self.assertTrue(any(line.startswith("HOUR_TYPE,") for line in lines))
        self.assertTrue(any(line.startswith("WEEK,2026-W32") for line in lines))

    def test_export_is_manager_only(self):
        for user in (self.staff_a, self.bm_a, self.customer_user):
            response = self.api(user).get(
                SUMMARY_CSV_URL, {"company": self.company_a.id}
            )
            self.assertEqual(response.status_code, 403, user.email)

    def test_export_cannot_reach_a_rival_company(self):
        response = self.api(self.ca_a).get(
            SUMMARY_CSV_URL, {"company": self.company_b.id}
        )
        self.assertEqual(response.status_code, 404)
