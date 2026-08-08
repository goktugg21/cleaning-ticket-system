"""
Sprint 154 §M — the week grid.

`POST /api/timesheets/entries/bulk-week/` takes a whole week at once.
The two things these tests exist to guarantee are the two the module
cannot survive losing:

  1. Every row goes through the NORMAL save path, so
     `multiplier_snapshot` and the derived `iso_year` / `iso_week` are
     written. A bulk insert that bypassed `save()` would leave the
     snapshot null and silently break every weighted total.
  2. All-or-nothing. A week that half-saved is worse than one that did
     not save at all.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from timesheets.models import TimeEntry, WeekLock

from .fixtures import TimesheetsFixture


BULK_WEEK_URL = "/api/timesheets/entries/bulk-week/"

# ISO 2026-W32 runs Mon 2026-08-03 .. Sun 2026-08-09.
MONDAY = dt.date(2026, 8, 3)
TUESDAY = dt.date(2026, 8, 4)
SUNDAY = dt.date(2026, 8, 9)
ISO_YEAR, ISO_WEEK = 2026, 32


class WeekGridSaveTests(TimesheetsFixture):
    def _body(self, cells, **extra):
        body = {"iso_year": ISO_YEAR, "iso_week": ISO_WEEK, "cells": cells}
        body.update(extra)
        return body

    def _cell(self, date, hour_type, hours, building=None):
        cell = {
            "date": date.isoformat(),
            "hour_type": hour_type.id,
            "hours": hours,
        }
        if building is not None:
            cell["building"] = building.id
        return cell

    def test_staff_saves_a_whole_week_in_one_request(self):
        response = self.api(self.staff_a).post(
            BULK_WEEK_URL,
            self._body(
                [
                    self._cell(MONDAY, self.normal_a, "8.00", self.building_a),
                    self._cell(TUESDAY, self.normal_a, "7.50", self.building_a),
                    self._cell(TUESDAY, self.overtime_a, "2.00", self.building_a),
                ]
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["created"], 3)
        self.assertEqual(TimeEntry.objects.filter(employee=self.staff_a).count(), 3)

    def test_every_row_carries_the_snapshot_and_the_derived_week(self):
        """The immutability core. If this ever fails, weighted totals are
        wrong everywhere and the week lock no longer governs the rows it
        should."""
        self.api(self.staff_a).post(
            BULK_WEEK_URL,
            self._body([self._cell(MONDAY, self.overtime_a, "6.00")]),
            format="json",
        )
        entry = TimeEntry.objects.get(employee=self.staff_a, date=MONDAY)
        self.assertEqual(entry.multiplier_snapshot, Decimal("1.50"))
        self.assertEqual((entry.iso_year, entry.iso_week), (ISO_YEAR, ISO_WEEK))
        self.assertEqual(entry.company_id, self.company_a.id)
        self.assertEqual(entry.created_by_id, self.staff_a.id)
        self.assertEqual(entry.weighted_hours, Decimal("9.00"))

    def test_resaving_the_same_cell_updates_rather_than_duplicating(self):
        cells = [self._cell(MONDAY, self.normal_a, "8.00", self.building_a)]
        self.api(self.staff_a).post(BULK_WEEK_URL, self._body(cells), format="json")

        cells = [self._cell(MONDAY, self.normal_a, "6.00", self.building_a)]
        response = self.api(self.staff_a).post(
            BULK_WEEK_URL, self._body(cells), format="json"
        )
        self.assertEqual(response.data["updated"], 1)
        self.assertEqual(response.data["created"], 0)
        self.assertEqual(TimeEntry.objects.filter(employee=self.staff_a).count(), 1)
        self.assertEqual(
            TimeEntry.objects.get(employee=self.staff_a).hours, Decimal("6.00")
        )

    def test_zero_clears_a_cell(self):
        self.api(self.staff_a).post(
            BULK_WEEK_URL,
            self._body([self._cell(MONDAY, self.normal_a, "8.00")]),
            format="json",
        )
        response = self.api(self.staff_a).post(
            BULK_WEEK_URL,
            self._body([self._cell(MONDAY, self.normal_a, "0")]),
            format="json",
        )
        self.assertEqual(response.data["deleted"], 1)
        self.assertFalse(TimeEntry.objects.filter(employee=self.staff_a).exists())

    def test_a_cell_the_grid_does_not_send_is_left_alone(self):
        """The grid is the authority for the cells it sends, and only
        those — otherwise saving a filtered view would wipe rows the
        operator could not see."""
        self.api(self.staff_a).post(
            BULK_WEEK_URL,
            self._body(
                [
                    self._cell(MONDAY, self.normal_a, "8.00"),
                    self._cell(TUESDAY, self.normal_a, "8.00"),
                ]
            ),
            format="json",
        )
        self.api(self.staff_a).post(
            BULK_WEEK_URL,
            self._body([self._cell(MONDAY, self.normal_a, "4.00")]),
            format="json",
        )
        self.assertEqual(TimeEntry.objects.filter(employee=self.staff_a).count(), 2)
        self.assertEqual(
            TimeEntry.objects.get(employee=self.staff_a, date=TUESDAY).hours,
            Decimal("8.00"),
        )

    def test_a_manager_files_for_an_employee(self):
        response = self.api(self.ca_a).post(
            BULK_WEEK_URL,
            self._body(
                [self._cell(MONDAY, self.normal_a, "8.00")],
                employee=self.staff_a.id,
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            TimeEntry.objects.get(date=MONDAY).employee_id, self.staff_a.id
        )


class WeekGridRefusalTests(TimesheetsFixture):
    def _body(self, cells, **extra):
        body = {"iso_year": ISO_YEAR, "iso_week": ISO_WEEK, "cells": cells}
        body.update(extra)
        return body

    def _cell(self, date, hour_type, hours):
        return {
            "date": date.isoformat(),
            "hour_type": hour_type.id,
            "hours": hours,
        }

    def test_a_closed_week_refuses_the_whole_grid(self):
        WeekLock.objects.create(
            company=self.company_a,
            iso_year=ISO_YEAR,
            iso_week=ISO_WEEK,
            closed_by=self.ca_a,
        )
        response = self.api(self.staff_a).post(
            BULK_WEEK_URL,
            self._body(
                [
                    self._cell(MONDAY, self.normal_a, "8.00"),
                    self._cell(TUESDAY, self.normal_a, "8.00"),
                ]
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(TimeEntry.objects.filter(employee=self.staff_a).exists())

    def test_one_bad_cell_rolls_the_whole_week_back(self):
        """All-or-nothing. The first cell is perfectly valid; the second
        names another company's hour type. Nothing may persist."""
        response = self.api(self.staff_a).post(
            BULK_WEEK_URL,
            self._body(
                [
                    self._cell(MONDAY, self.normal_a, "8.00"),
                    self._cell(TUESDAY, self.normal_b, "8.00"),
                ]
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            TimeEntry.objects.filter(employee=self.staff_a).count(),
            0,
            "a half-saved week leaked past the atomic block",
        )

    def test_a_date_outside_the_named_week_is_rejected(self):
        """Otherwise a grid could file Monday's hours into last week and
        the row would still be internally consistent — its derived week
        would just disagree with the grid the operator was reading."""
        response = self.api(self.staff_a).post(
            BULK_WEEK_URL,
            self._body([self._cell(SUNDAY + dt.timedelta(days=1), self.normal_a, "8.00")]),
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("cells", response.data)

    def test_sunday_is_inside_the_week(self):
        """The boundary the ISO week actually has. A grid that stopped at
        Saturday would silently drop weekend work."""
        response = self.api(self.staff_a).post(
            BULK_WEEK_URL,
            self._body([self._cell(SUNDAY, self.normal_a, "4.00")]),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        entry = TimeEntry.objects.get(employee=self.staff_a)
        self.assertEqual((entry.iso_year, entry.iso_week), (ISO_YEAR, ISO_WEEK))

    def test_staff_cannot_file_for_someone_else(self):
        response = self.api(self.staff_a).post(
            BULK_WEEK_URL,
            self._body(
                [self._cell(MONDAY, self.normal_a, "8.00")],
                employee=self.staff_b.id,
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(TimeEntry.objects.exists())

    def test_a_customer_user_is_forbidden(self):
        response = self.api(self.customer_user).post(
            BULK_WEEK_URL,
            self._body([self._cell(MONDAY, self.normal_a, "8.00")]),
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_another_companys_hour_type_is_rejected(self):
        response = self.api(self.staff_a).post(
            BULK_WEEK_URL,
            self._body([self._cell(MONDAY, self.normal_b, "8.00")]),
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_an_empty_grid_is_rejected(self):
        response = self.api(self.staff_a).post(
            BULK_WEEK_URL, self._body([]), format="json"
        )
        self.assertEqual(response.status_code, 400)
