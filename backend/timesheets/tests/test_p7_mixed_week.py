"""P-7 S1.5 — the Enter-hours modal's save math, verified server-side.

The owner suspected the weekly save. The modal posts ONE `bulk-week`
body for every person in the grid, with only the cells that changed,
and a row in the grid is (person, building, hour type, job). These
tests post the mixed week the modal produces — the same person on a
plain row, a ticket row and an extra-work row at one building, a
second person, an overtime type, a zero to clear a saved cell — and
read the stored entries back, so "what the grid shows is what the
store keeps" is asserted rather than believed.

Findings recorded by the round (see the P-7 report):
  - by design: a cell is keyed on the job too, so the same person can
    have three rows at one building (plain / ticket / extra work);
    they are three facts and stay three entries;
  - by design: "0" deletes; an untouched cell is not sent and not
    touched; the multiplier is snapshotted per entry at write time;
  - by design: a manager posts for several people in ONE request and
    it is all-or-nothing — one bad cell writes nothing.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from extra_work.models import ExtraWorkCategory, ExtraWorkRequest, ExtraWorkStatus
from tickets.models import Ticket, TicketStatus
from timesheets.models import HourSource, TimeEntry

from .fixtures import TimesheetsFixture


BULK_WEEK_URL = "/api/timesheets/entries/bulk-week/"

# ISO 2026-W32 runs Mon 2026-08-03 .. Sun 2026-08-09.
MON = dt.date(2026, 8, 3)
TUE = dt.date(2026, 8, 4)
WED = dt.date(2026, 8, 5)
ISO_YEAR, ISO_WEEK = 2026, 32


class MixedWeekSaveTests(TimesheetsFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # A job is only bookable when it is REAL and in the company
        # (`timesheet_source_invalid` otherwise — W-FIX1's scope rule),
        # so the ticket row and the extra-work row point at real records.
        cls.ticket = Ticket.objects.create(
            company=cls.company_a,
            building=cls.building_a,
            customer=cls.customer_a,
            created_by=cls.ca_a,
            title="final test",
            description="x",
            status=TicketStatus.OPEN,
        )
        cls.ew = ExtraWorkRequest.objects.create(
            company=cls.company_a,
            building=cls.building_a,
            customer=cls.customer_a,
            created_by=cls.ca_a,
            title="Extra werk regie uren +1",
            description="x",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.IN_PROGRESS,
        )

    def _cell(self, employee, date, hours, *, hour_type=None, building=None,
              source_type=None, source_id=None):
        cell = {
            "employee": employee.id,
            "date": date.isoformat(),
            "hour_type": (hour_type or self.normal_a).id,
            "hours": hours,
            "building": (building or self.building_a).id,
        }
        if source_type is not None:
            cell["source_type"] = source_type
            cell["source_id"] = source_id
        return cell

    def _post(self, cells, *, as_user=None):
        return self.api(as_user or self.ca_a).post(
            BULK_WEEK_URL,
            {
                "company": self.company_a.id,
                "iso_year": ISO_YEAR,
                "iso_week": ISO_WEEK,
                "cells": cells,
            },
            format="json",
        )

    def _stored(self, employee):
        return [
            (row.date, row.hour_type_id, row.source_type, row.source_id, str(row.hours),
             str(row.multiplier_snapshot))
            for row in TimeEntry.objects.filter(employee=employee).order_by(
                "date", "source_type", "source_id", "hour_type__sort_order"
            )
        ]

    def test_one_person_three_rows_at_one_building_store_three_facts(self):
        response = self._post(
            [
                # the plain row (no job)
                self._cell(self.staff_a, MON, "4.00"),
                self._cell(self.staff_a, TUE, "2.50"),
                # the ticket row, same building, same hour type
                self._cell(self.staff_a, MON, "3.00",
                           source_type=HourSource.TICKET, source_id=self.ticket.id),
                # the extra-work row
                self._cell(self.staff_a, MON, "1.00",
                           source_type=HourSource.EXTRA_WORK, source_id=self.ew.id),
                # overtime on the ticket row, its own hour type
                self._cell(self.staff_a, WED, "1.50", hour_type=self.overtime_a,
                           source_type=HourSource.TICKET, source_id=self.ticket.id),
            ]
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"created": 5, "updated": 0, "deleted": 0})
        self.assertEqual(
            self._stored(self.staff_a),
            [
                (MON, self.normal_a.id, HourSource.EXTRA_WORK, self.ew.id, "1.00", "1.00"),
                (MON, self.normal_a.id, HourSource.OTHER, None, "4.00", "1.00"),
                (MON, self.normal_a.id, HourSource.TICKET, self.ticket.id, "3.00", "1.00"),
                (TUE, self.normal_a.id, HourSource.OTHER, None, "2.50", "1.00"),
                (WED, self.overtime_a.id, HourSource.TICKET, self.ticket.id, "1.50", "1.50"),
            ],
        )
        # The person's Monday is 8.00 across three rows — three facts,
        # never summed onto one line.
        monday = TimeEntry.objects.filter(employee=self.staff_a, date=MON)
        self.assertEqual(sum(row.hours for row in monday), Decimal("8.00"))

    def test_a_second_save_changes_only_the_cells_it_names(self):
        self._post(
            [
                self._cell(self.staff_a, MON, "4.00"),
                self._cell(self.staff_a, TUE, "2.50"),
                self._cell(self.staff_a, MON, "3.00",
                           source_type=HourSource.TICKET, source_id=self.ticket.id),
            ]
        )
        # The modal resends only what changed: Monday plain becomes 5,
        # the ticket Monday is cleared with "0", Tuesday is not sent.
        response = self._post(
            [
                self._cell(self.staff_a, MON, "5.00"),
                self._cell(self.staff_a, MON, "0",
                           source_type=HourSource.TICKET, source_id=self.ticket.id),
            ]
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"created": 0, "updated": 1, "deleted": 1})
        self.assertEqual(
            self._stored(self.staff_a),
            [
                (MON, self.normal_a.id, HourSource.OTHER, None, "5.00", "1.00"),
                (TUE, self.normal_a.id, HourSource.OTHER, None, "2.50", "1.00"),
            ],
        )

    def test_two_people_in_one_request_land_on_their_own_rows(self):
        response = self._post(
            [
                self._cell(self.staff_a, MON, "8.00"),
                self._cell(self.staff_a2, MON, "6.00"),
                self._cell(self.staff_a2, MON, "2.00",
                           source_type=HourSource.TICKET, source_id=self.ticket.id),
            ]
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["created"], 3)
        self.assertEqual(
            [r[4] for r in self._stored(self.staff_a)], ["8.00"]
        )
        self.assertEqual(
            [(r[2], r[3], r[4]) for r in self._stored(self.staff_a2)],
            [(HourSource.OTHER, None, "6.00"), (HourSource.TICKET, self.ticket.id, "2.00")],
        )

    def test_one_bad_cell_writes_nothing_for_anybody(self):
        response = self._post(
            [
                self._cell(self.staff_a, MON, "8.00"),
                # a day outside the named week
                self._cell(self.staff_a2, MON + dt.timedelta(days=7), "6.00"),
            ]
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(TimeEntry.objects.count(), 0)

    def test_the_same_cell_twice_in_one_body_is_the_last_one_not_a_sum(self):
        # What a double-keyed row would look like if the grid ever
        # produced one: the store must not add the two up.
        response = self._post(
            [
                self._cell(self.staff_a, MON, "4.00"),
                self._cell(self.staff_a, MON, "3.00"),
            ]
        )
        self.assertEqual(response.status_code, 200, response.data)
        rows = TimeEntry.objects.filter(employee=self.staff_a, date=MON)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(str(rows.get().hours), "3.00")
