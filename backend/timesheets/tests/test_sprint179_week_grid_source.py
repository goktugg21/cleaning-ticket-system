"""
Sprint 179B §2 — the week grid's row identity, on BOTH sides of the wire.

Sprint 177 §7 taught the week wizard to seed one row per JOB, and the
grid keys its rows on `(hour_type, building, source_type, source_id)`
for a stated reason: hours on a stairwell repaint and hours on nothing
in particular are two facts and must not be summed onto one line.

`bulk-week` did not agree. `_existing_row` looked a cell up by
`(employee, date, hour_type, building)` and ignored the source, so the
two sides disagreed about what a row IS — and the disagreement lost
data rather than raising: pick two jobs at one building, put hours on
each, press Save, and the second cell UPDATED the row the first one
created. One entry survived, carrying the second job's hours and the
second job's source. Nothing said so.

Sprint 179B added the Job column that makes those rows readable, which
is precisely why the write path had to start agreeing with them first: a
column that shows two jobs over a store that keeps one is worse than no
column.

These tests are also the first coverage of the source pair anywhere in
`timesheets/` — before this, `grep -r source_type timesheets/tests/`
returned nothing, and the whole pair was tested only from `reports/`.
"""
from __future__ import annotations

import datetime as dt

from timesheets.models import HourSource, TimeEntry

from .fixtures import ENTRIES_URL, TimesheetsFixture


BULK_WEEK_URL = "/api/timesheets/entries/bulk-week/"

# ISO 2026-W32 runs Mon 2026-08-03 .. Sun 2026-08-09.
MONDAY = dt.date(2026, 8, 3)
ISO_YEAR, ISO_WEEK = 2026, 32


class WeekGridSourceIdentityTests(TimesheetsFixture):
    """One cell per job, one row per job."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # P-16 repin — the write path validates the source pair against
        # REAL, in-scope jobs now (`_source_in_scope`: the ticket must
        # exist in the actor's ticket scope and the entry's company).
        # The original tests used fictional ids 41/42, which the
        # hardened door rightly refuses. Two real tickets on the
        # building staff_a holds BUILDING_READ visibility on.
        from tickets.models import Ticket

        cls.job_a = Ticket.objects.create(
            company=cls.company_a,
            building=cls.building_a,
            customer=cls.customer_a,
            created_by=cls.ca_a,
            title="Stairwell repaint",
            description="job a",
        )
        cls.job_b = Ticket.objects.create(
            company=cls.company_a,
            building=cls.building_a,
            customer=cls.customer_a,
            created_by=cls.ca_a,
            title="Window wash",
            description="job b",
        )

    def _cell(self, hours, *, source_type=None, source_id=None):
        cell = {
            "date": MONDAY.isoformat(),
            "hour_type": self.normal_a.id,
            "hours": hours,
            "building": self.building_a.id,
        }
        if source_type is not None:
            cell["source_type"] = source_type
            cell["source_id"] = source_id
        return cell

    def _post(self, cells):
        return self.api(self.staff_a).post(
            BULK_WEEK_URL,
            {"iso_year": ISO_YEAR, "iso_week": ISO_WEEK, "cells": cells},
            format="json",
        )

    def test_two_jobs_at_one_building_stay_two_rows(self):
        # The exact shape the wizard produces: same person, same day,
        # same building, same hour type — two different tickets.
        response = self._post(
            [
                self._cell("4.00", source_type=HourSource.TICKET, source_id=self.job_a.id),
                self._cell("3.00", source_type=HourSource.TICKET, source_id=self.job_b.id),
            ]
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["created"], 2)
        self.assertEqual(response.data["updated"], 0)

        rows = TimeEntry.objects.filter(
            employee=self.staff_a, date=MONDAY
        ).order_by("source_id")
        self.assertEqual(
            [(row.source_type, row.source_id, str(row.hours)) for row in rows],
            [
                (HourSource.TICKET, self.job_a.id, "4.00"),
                (HourSource.TICKET, self.job_b.id, "3.00"),
            ],
        )

    def test_a_type_only_source_is_its_own_row_too(self):
        # CONTRACT and OTHER carry no id (Sprint 178 §4b). They are still
        # two different answers to "which job", so they are two rows.
        response = self._post(
            [
                self._cell("2.00", source_type=HourSource.CONTRACT),
                self._cell("1.00", source_type=HourSource.OTHER),
            ]
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["created"], 2)
        self.assertEqual(
            set(
                TimeEntry.objects.filter(
                    employee=self.staff_a, date=MONDAY
                ).values_list("source_type", flat=True)
            ),
            {HourSource.CONTRACT, HourSource.OTHER},
        )

    def test_resending_the_same_job_updates_that_row(self):
        self._post(
            [self._cell("4.00", source_type=HourSource.TICKET, source_id=self.job_a.id)]
        )
        response = self._post(
            [self._cell("6.00", source_type=HourSource.TICKET, source_id=self.job_a.id)]
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["updated"], 1)
        self.assertEqual(response.data["created"], 0)
        row = TimeEntry.objects.get(employee=self.staff_a, date=MONDAY)
        self.assertEqual(str(row.hours), "6.00")
        self.assertEqual(row.source_id, self.job_a.id)

    def test_clearing_one_jobs_cell_leaves_the_other_alone(self):
        self._post(
            [
                self._cell("4.00", source_type=HourSource.TICKET, source_id=self.job_a.id),
                self._cell("3.00", source_type=HourSource.TICKET, source_id=self.job_b.id),
            ]
        )
        response = self._post(
            [self._cell("0", source_type=HourSource.TICKET, source_id=self.job_a.id)]
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["deleted"], 1)
        remaining = TimeEntry.objects.filter(employee=self.staff_a, date=MONDAY)
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.first().source_id, self.job_b.id)

    def test_an_untagged_cell_does_not_overwrite_a_job_tagged_row(self):
        self._post(
            [self._cell("4.00", source_type=HourSource.TICKET, source_id=self.job_a.id)]
        )
        response = self._post([self._cell("2.00")])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["created"], 1)
        rows = TimeEntry.objects.filter(
            employee=self.staff_a, date=MONDAY
        ).order_by("hours")
        self.assertEqual(
            [(row.source_type, row.source_id, str(row.hours)) for row in rows],
            [
                # The untagged row lands as OTHER with no id — the column
                # default, so it is indistinguishable from every row
                # written before the source column existed. That is the
                # point: "nobody said" is one state, not two.
                (HourSource.OTHER, None, "2.00"),
                (HourSource.TICKET, self.job_a.id, "4.00"),
            ],
        )

    def test_an_untagged_cell_still_updates_the_untagged_row(self):
        # The back-compat half: a grid that sends no source at all (every
        # caller before Sprint 177) must keep updating the row it always
        # updated, rather than stacking a new one on every save.
        self._post([self._cell("4.00")])
        response = self._post([self._cell("7.00")])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["updated"], 1)
        self.assertEqual(
            TimeEntry.objects.filter(employee=self.staff_a, date=MONDAY).count(),
            1,
        )

    def test_the_entries_list_renders_the_source_pair(self):
        # The Job column reads `source_type` / `source_id` off THIS
        # payload and resolves the title through
        # `/api/reports/hour-sources/`. A missing `fields` entry would
        # take the column out without any filter test noticing — which is
        # how Sprint 173's Extra Work page went down.
        self.make_entry(
            self.staff_a,
            MONDAY,
            self.normal_a,
            building=self.building_a,
            source_type=HourSource.EXTRA_WORK,
            source_id=7,
        )
        response = self.api(self.staff_a).get(
            ENTRIES_URL, {"iso_year": ISO_YEAR, "iso_week": ISO_WEEK}
        )
        self.assertEqual(response.status_code, 200, response.data)
        row = response.data["results"][0]
        self.assertIn("source_type", row)
        self.assertIn("source_id", row)
        self.assertEqual(row["source_type"], HourSource.EXTRA_WORK)
        self.assertEqual(row["source_id"], 7)
