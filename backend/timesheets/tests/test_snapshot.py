"""
Sprint 152 — the multiplier-snapshot immutability rule.

The one behaviour this module exists to guarantee: editing an hour
type's multiplier refreshes the snapshot on its entries in OPEN weeks,
and PROVABLY does not touch entries in CLOSED ones. A closed week's
weighted totals must be byte-identical before and after the edit.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from timesheets.models import TimeEntry, WeekLock

from .fixtures import (
    SUMMARY_URL,
    TimesheetsFixture,
    hour_type_detail_url,
)


W32_MONDAY = dt.date(2026, 8, 3)   # closed in these tests
W33_MONDAY = dt.date(2026, 8, 10)  # left open


class SnapshotRefreshTests(TimesheetsFixture):
    def setUp(self):
        super().setUp()
        self.closed_entry = self.make_entry(
            self.staff_a, W32_MONDAY, self.overtime_a, hours="10.00"
        )
        self.open_entry = self.make_entry(
            self.staff_a, W33_MONDAY, self.overtime_a, hours="10.00"
        )
        # An entry of a DIFFERENT type in the same open week — it must
        # not move when `overtime_a`'s multiplier changes.
        self.other_type_entry = self.make_entry(
            self.staff_a, W33_MONDAY, self.normal_a, hours="10.00"
        )
        # And one in the other company, to prove the refresh does not
        # reach across the tenant boundary.
        self.foreign_entry = self.make_entry(
            self.staff_b, W33_MONDAY, self.normal_b, hours="10.00"
        )
        WeekLock.objects.create(
            company=self.company_a,
            iso_year=2026,
            iso_week=32,
            closed_by=self.ca_a,
        )

    def _edit_multiplier(self, value="2.00"):
        return self.api(self.ca_a).patch(
            hour_type_detail_url(self.overtime_a.id),
            {"multiplier": value},
            format="json",
        )

    def test_open_week_snapshot_is_refreshed(self):
        response = self._edit_multiplier("2.00")
        self.assertEqual(response.status_code, 200, response.data)
        self.open_entry.refresh_from_db()
        self.assertEqual(self.open_entry.multiplier_snapshot, Decimal("2.00"))
        self.assertEqual(self.open_entry.weighted_hours, Decimal("20.00"))

    def test_closed_week_snapshot_is_untouched(self):
        before = self.closed_entry.multiplier_snapshot
        before_weighted = self.closed_entry.weighted_hours
        self._edit_multiplier("2.00")
        self.closed_entry.refresh_from_db()
        self.assertEqual(self.closed_entry.multiplier_snapshot, before)
        self.assertEqual(self.closed_entry.multiplier_snapshot, Decimal("1.50"))
        self.assertEqual(self.closed_entry.weighted_hours, before_weighted)

    def test_closed_week_totals_are_byte_identical_across_the_edit(self):
        client = self.api(self.ca_a)
        params = {
            "company": self.company_a.id,
            "iso_year": 2026,
            "iso_week": 32,
        }
        before = client.get(SUMMARY_URL, params).data
        self._edit_multiplier("2.00")
        after = client.get(SUMMARY_URL, params).data

        self.assertEqual(before["total_hours"], after["total_hours"])
        self.assertEqual(
            before["total_weighted_hours"], after["total_weighted_hours"]
        )
        self.assertEqual(before["by_week"], after["by_week"])
        self.assertEqual(before["total_weighted_hours"], "15.00")

    def test_other_hour_types_are_untouched(self):
        before = self.other_type_entry.multiplier_snapshot
        self._edit_multiplier("2.00")
        self.other_type_entry.refresh_from_db()
        self.assertEqual(self.other_type_entry.multiplier_snapshot, before)

    def test_the_other_tenant_is_untouched(self):
        before = self.foreign_entry.multiplier_snapshot
        self._edit_multiplier("2.00")
        self.foreign_entry.refresh_from_db()
        self.assertEqual(self.foreign_entry.multiplier_snapshot, before)

    def test_a_non_multiplier_edit_refreshes_nothing(self):
        before = {
            entry.pk: entry.multiplier_snapshot
            for entry in TimeEntry.objects.all()
        }
        response = self.api(self.ca_a).patch(
            hour_type_detail_url(self.overtime_a.id),
            {"name": "Overuren", "sort_order": 99},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        for entry in TimeEntry.objects.all():
            self.assertEqual(entry.multiplier_snapshot, before[entry.pk])

    def test_a_new_entry_after_the_edit_uses_the_new_multiplier(self):
        self._edit_multiplier("2.00")
        # Re-read BEFORE creating: `self.overtime_a` is the fixture's
        # in-memory copy and still holds 1.50, so snapshotting off it
        # would test the stale object rather than the rule.
        self.overtime_a.refresh_from_db()
        self.assertEqual(self.overtime_a.multiplier, Decimal("2.00"))
        entry = self.make_entry(
            self.staff_a, W33_MONDAY, self.overtime_a, hours="2.00"
        )
        self.assertEqual(entry.multiplier_snapshot, Decimal("2.00"))

    def test_lowering_a_multiplier_also_refreshes_only_open_weeks(self):
        self._edit_multiplier("0.00")
        self.open_entry.refresh_from_db()
        self.closed_entry.refresh_from_db()
        self.assertEqual(self.open_entry.multiplier_snapshot, Decimal("0.00"))
        self.assertEqual(self.closed_entry.multiplier_snapshot, Decimal("1.50"))
