"""
P-11 B2/B4 — the week grid's group/child shape, pinned at the API.

The grid renders ONE group per person: standard lines (a building, no
job) and job lines (source TICKET / EXTRA_WORK) as children under them,
each line one hour type. The grid derives that shape from what
`GET /entries/` returns after `POST /entries/bulk-week/` wrote it — so
the contract this file pins is the round trip:

  * a cell posted WITH `source_type`/`source_id` comes back carrying
    both, so the job line regroups as the same child;
  * a cell posted WITHOUT them comes back as the model's default
    (`OTHER`, no id) — the standard line's identity;
  * two hour types on one job are two rows of the same (person,
    building, job) group;
  * `hours: "0"` deletes exactly that line's day and nothing else;
  * every row carries the names the week card prints
    (`employee_name`, `building_name`, `hour_type_name`).
"""
from __future__ import annotations

import datetime as dt

from .fixtures import TimesheetsFixture

BULK_URL = "/api/timesheets/entries/bulk-week/"
ENTRIES_URL = "/api/timesheets/entries/"

# ISO week 33 of 2026: Mon 10 Aug – Sun 16 Aug.
MON = dt.date(2026, 8, 10)
THU = dt.date(2026, 8, 13)
SAT = dt.date(2026, 8, 15)


class GridRowsRoundTripTests(TimesheetsFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # W-FIX1 — the source wall: a job cell must name a REAL record
        # in this company, so the fixture holds one.
        from customers.models import Customer
        from tickets.models import (
            Ticket,
            TicketPriority,
            TicketStatus,
            TicketType,
        )

        customer = Customer.objects.create(
            company=cls.company_a, name="Customer A ticketing"
        )
        cls.job_ticket = Ticket.objects.create(
            company=cls.company_a,
            building=cls.building_a,
            customer=customer,
            created_by=cls.sa,
            title="Lekkage toilet",
            description="x",
            type=TicketType.REQUEST,
            priority=TicketPriority.NORMAL,
            status=TicketStatus.IN_PROGRESS,
        )

    def _post_week(self, cells, actor=None):
        response = self.api(actor or self.ca_a).post(
            BULK_URL,
            {
                "company": self.company_a.id,
                "iso_year": 2026,
                "iso_week": 33,
                "cells": cells,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def _entries(self):
        response = self.api(self.ca_a).get(
            ENTRIES_URL,
            {
                "company": self.company_a.id,
                "iso_year": 2026,
                "iso_week": 33,
                "page_size": 200,
            },
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["results"]

    def _seed_week(self):
        return self._post_week(
            [
                # Ahmet's standard line at Building A.
                {
                    "employee": self.staff_a.id,
                    "hour_type": self.normal_a.id,
                    "building": self.building_a.id,
                    "date": MON.isoformat(),
                    "hours": "8.00",
                },
                # Ahmet on a job — two hour types, two lines, one group.
                {
                    "employee": self.staff_a.id,
                    "hour_type": self.overtime_a.id,
                    "building": self.building_a.id,
                    "date": SAT.isoformat(),
                    "hours": "4.00",
                    "source_type": "TICKET",
                    "source_id": self.job_ticket.id,
                },
                {
                    "employee": self.staff_a.id,
                    "hour_type": self.normal_a.id,
                    "building": self.building_a.id,
                    "date": THU.isoformat(),
                    "hours": "1.00",
                    "source_type": "TICKET",
                    "source_id": self.job_ticket.id,
                },
                # Gökhan on the same job.
                {
                    "employee": self.staff_a2.id,
                    "hour_type": self.overtime_a.id,
                    "building": self.building_a.id,
                    "date": SAT.isoformat(),
                    "hours": "4.00",
                    "source_type": "TICKET",
                    "source_id": self.job_ticket.id,
                },
            ]
        )

    def test_job_cells_round_trip_with_their_source(self):
        result = self._seed_week()
        self.assertEqual(result["created"], 4, result)
        rows = self._entries()
        job_rows = [r for r in rows if r["source_type"] == "TICKET"]
        self.assertEqual(len(job_rows), 3)
        self.assertTrue(all(r["source_id"] == self.job_ticket.id for r in job_rows))
        # The child group's identity: (person, building, job) with one
        # row per hour type.
        ahmet_job = {
            (r["hour_type"], r["date"])
            for r in job_rows
            if r["employee"] == self.staff_a.id
        }
        self.assertEqual(
            ahmet_job,
            {
                (self.overtime_a.id, SAT.isoformat()),
                (self.normal_a.id, THU.isoformat()),
            },
        )

    def test_a_standard_cell_comes_back_as_the_untagged_default(self):
        self._seed_week()
        rows = self._entries()
        standard = [
            r
            for r in rows
            if r["employee"] == self.staff_a.id and r["source_type"] != "TICKET"
        ]
        self.assertEqual(len(standard), 1)
        self.assertEqual(standard[0]["source_type"], "OTHER")
        self.assertIsNone(standard[0]["source_id"])

    def test_every_row_carries_the_names_the_week_card_prints(self):
        self._seed_week()
        for row in self._entries():
            self.assertTrue(row["employee_name"], row)
            self.assertTrue(row["hour_type_name"], row)
            self.assertEqual(row["building_name"], "Building A")

    def test_zero_deletes_exactly_that_lines_day(self):
        self._seed_week()
        result = self._post_week(
            [
                {
                    "employee": self.staff_a.id,
                    "hour_type": self.overtime_a.id,
                    "building": self.building_a.id,
                    "date": SAT.isoformat(),
                    "hours": "0",
                    "source_type": "TICKET",
                    "source_id": self.job_ticket.id,
                }
            ]
        )
        self.assertEqual(result["deleted"], 1, result)
        rows = self._entries()
        # The other job line, the colleague's line and the standard
        # line all stand.
        self.assertEqual(len(rows), 3)
        self.assertNotIn(
            (self.staff_a.id, self.overtime_a.id, SAT.isoformat()),
            {(r["employee"], r["hour_type"], r["date"]) for r in rows},
        )


class WeeksWithHoursFactsTests(TimesheetsFixture):
    """P-11 B1 — `weeks/with-hours/` carries the Earlier-weeks table's
    facts: how many PEOPLE hold hours in the week, and the lock (by
    whom, when) when the read is about one company."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.make_entry(cls, cls.staff_a, dt.date(2026, 8, 10), cls.normal_a, "8.00")
        cls.make_entry(cls, cls.staff_a2, dt.date(2026, 8, 11), cls.overtime_a, "4.00")
        cls.make_entry(cls, cls.staff_a, dt.date(2026, 8, 24), cls.normal_a, "3.00")
        from timesheets.models import WeekLock

        cls.lock = WeekLock.objects.create(
            company=cls.company_a,
            iso_year=2026,
            iso_week=33,
            closed_by=cls.ca_a,
        )

    def test_people_and_lock_facts_per_week(self):
        response = self.api(self.ca_a).get(
            "/api/timesheets/weeks/with-hours/",
            {"iso_year": 2026, "company": self.company_a.id},
        )
        self.assertEqual(response.status_code, 200, response.data)
        by_week = {row["iso_week"]: row for row in response.data["weeks"]}
        self.assertEqual(by_week[33]["people"], 2)
        self.assertTrue(by_week[33]["is_closed"])
        self.assertEqual(
            by_week[33]["closed_by_name"], self.ca_a.full_name or self.ca_a.email
        )
        self.assertIsNotNone(by_week[33]["closed_at"])
        self.assertEqual(by_week[35]["people"], 1)
        self.assertFalse(by_week[35]["is_closed"])
        self.assertIsNone(by_week[35]["closed_by_name"])
