"""
hours2 — the TICKET door into the one hours record.

    Design law for the wave: plan proposes, worked confirms; one record
    (`TimeEntry`), two doors. The admin week grid is one door; the
    operational ticket's "Book hours" is the other. Both write ORDINARY
    rows — nothing here is a second table, a second write path or a
    second lock rule.

What this module pins, and why each line is one somebody could undo
without any other test noticing:

1. **An entry booked from the ticket lands TAGGED.** `POST
   /api/timesheets/entries/` with `source_type=TICKET` and `source_id`
   stores exactly that pair, so the comparison on the ticket can find
   the row again. Before this wave `grep source_type timesheets/tests/`
   covered only the bulk-week path (Sprint 179B); the single-entry
   create — the path the ticket door uses — was never asserted.
2. **A closed week refuses the booking with 400 `week_closed`**, the
   same stable code every other write gets, so the ticket page can show
   the server's own sentence at the action instead of inventing one.
   Nothing is written.
3. **`?source_id=` narrows the list AND the summary** to one job, on
   top of `?source_type=`. Both go through `_apply_entry_filters`, so
   the totals under the ticket's comparison table are computed over
   the rows the list would show — the Sprint 152 rule that the two can
   never disagree.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from timesheets.models import HourSource, TimeEntry, WeekLock

from .fixtures import ENTRIES_URL, SUMMARY_URL, TimesheetsFixture


MONDAY = dt.date(2026, 8, 3)  # ISO 2026-W32
TUESDAY = dt.date(2026, 8, 4)
TICKET_41 = 41
TICKET_42 = 42


class TicketDoorEntryTests(TimesheetsFixture):
    def _booking(self, **overrides):
        body = {
            "employee": self.staff_a.id,
            "date": MONDAY.isoformat(),
            "hour_type": self.normal_a.id,
            "hours": "3.00",
            "building": self.building_a.id,
            "company": self.company_a.id,
            "source_type": HourSource.TICKET,
            "source_id": TICKET_41,
        }
        body.update(overrides)
        return body

    def test_a_booking_from_the_ticket_lands_tagged_to_that_ticket(self):
        response = self.api(self.ca_a).post(
            ENTRIES_URL, self._booking(), format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        entry = TimeEntry.objects.get(pk=response.data["id"])
        self.assertEqual(entry.source_type, HourSource.TICKET)
        self.assertEqual(entry.source_id, TICKET_41)
        self.assertEqual(entry.employee_id, self.staff_a.id)
        self.assertEqual(entry.building_id, self.building_a.id)
        self.assertEqual(entry.company_id, self.company_a.id)
        self.assertEqual(entry.created_by_id, self.ca_a.id)
        # The tag is echoed back, so the client can trust what it wrote.
        self.assertEqual(response.data["source_type"], HourSource.TICKET)
        self.assertEqual(response.data["source_id"], TICKET_41)

    def test_two_crew_members_are_two_ordinary_rows(self):
        for employee in (self.staff_a, self.staff_a2):
            response = self.api(self.ca_a).post(
                ENTRIES_URL,
                self._booking(employee=employee.id),
                format="json",
            )
            self.assertEqual(response.status_code, 201, response.data)
        rows = TimeEntry.objects.filter(
            source_type=HourSource.TICKET, source_id=TICKET_41
        )
        self.assertEqual(rows.count(), 2)
        self.assertEqual(
            {row.employee_id for row in rows},
            {self.staff_a.id, self.staff_a2.id},
        )

    def test_a_closed_week_refuses_the_booking_with_400_week_closed(self):
        WeekLock.objects.create(
            company=self.company_a,
            iso_year=2026,
            iso_week=32,
            closed_by=self.ca_a,
        )
        response = self.api(self.ca_a).post(
            ENTRIES_URL, self._booking(), format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("date", response.data)
        self.assertEqual(response.data["date"][0].code, "week_closed")
        self.assertFalse(
            TimeEntry.objects.filter(
                source_type=HourSource.TICKET, source_id=TICKET_41
            ).exists()
        )


class SourceIdFilterTests(TimesheetsFixture):
    def setUp(self):
        super().setUp()
        self.row(self.staff_a, MONDAY, "3.00", TICKET_41)
        self.row(self.staff_a, TUESDAY, "2.00", TICKET_42)
        self.row(self.staff_a2, MONDAY, "1.00", TICKET_41)
        # An untagged row on the same days: never part of a ticket's answer.
        TimeEntry.objects.create(
            company=self.company_a,
            employee=self.staff_a,
            date=MONDAY,
            hour_type=self.normal_a,
            hours=Decimal("8.00"),
            multiplier_snapshot=Decimal("1.00"),
            created_by=self.ca_a,
        )

    def row(self, employee, on_date, hours, ticket_id):
        return TimeEntry.objects.create(
            company=self.company_a,
            employee=employee,
            date=on_date,
            hour_type=self.normal_a,
            hours=Decimal(hours),
            multiplier_snapshot=Decimal("1.00"),
            building=self.building_a,
            source_type=HourSource.TICKET,
            source_id=ticket_id,
            created_by=self.ca_a,
        )

    def test_the_list_narrows_to_one_ticket(self):
        response = self.api(self.ca_a).get(
            ENTRIES_URL,
            {"source_type": "TICKET", "source_id": TICKET_41},
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(
            {row["source_id"] for row in response.data["results"]},
            {TICKET_41},
        )

    def test_the_summary_totals_the_same_rows(self):
        response = self.api(self.ca_a).get(
            SUMMARY_URL,
            {
                "company": self.company_a.id,
                "source_type": "TICKET",
                "source_id": TICKET_41,
            },
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["total_entries"], 2)
        self.assertEqual(response.data["total_hours"], "4.00")
        by_employee = {
            row["employee"]: row["hours"] for row in response.data["by_employee"]
        }
        self.assertEqual(
            by_employee,
            {self.staff_a.id: "3.00", self.staff_a2.id: "1.00"},
        )

    def test_a_non_manager_reads_only_their_own_line_of_the_ticket(self):
        # The privacy floor holds through the new filter exactly as it
        # does without it: `restrict_entries_to_self` is applied before
        # any query param is read.
        response = self.api(self.staff_a).get(
            SUMMARY_URL,
            {"source_type": "TICKET", "source_id": TICKET_41},
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["total_hours"], "3.00")
        self.assertEqual(
            [row["employee"] for row in response.data["by_employee"]],
            [self.staff_a.id],
        )

    def test_an_unparseable_source_id_is_absent_not_an_error(self):
        response = self.api(self.ca_a).get(
            ENTRIES_URL, {"source_type": "TICKET", "source_id": "abc"}
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 3)


class TicketDoorEveryoneAssignedTests(TimesheetsFixture):
    """W-HOURS4 Task 3 — the locked budget ruling: the ticket door
    enters hours for EVERYONE assigned to the job, managers included.

    The dialog used to offer the crew alone, and the reason was data
    shape, not policy — the ticket payload carries `assigned_staff` and
    nothing about responsible managers. The WRITE path never had that
    restriction: BUILDING_MANAGER and COMPANY_ADMIN are provider
    employees (`timesheets.scope.PROVIDER_EMPLOYEE_ROLES`). Pinned here
    so the frontend's wider picker rests on an asserted contract, and
    so the one role that is NOT an employee stays refused.
    """

    def _booking(self, employee):
        return {
            "employee": employee.id,
            "date": MONDAY.isoformat(),
            "hour_type": self.normal_a.id,
            "hours": "2.00",
            "building": self.building_a.id,
            "company": self.company_a.id,
            "source_type": HourSource.TICKET,
            "source_id": TICKET_41,
        }

    def test_a_building_manager_is_an_employee_the_door_accepts(self):
        response = self.api(self.ca_a).post(
            ENTRIES_URL, self._booking(self.bm_a), format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        entry = TimeEntry.objects.get(pk=response.data["id"])
        self.assertEqual(entry.employee_id, self.bm_a.id)
        self.assertEqual(entry.source_type, HourSource.TICKET)
        self.assertEqual(entry.source_id, TICKET_41)

    def test_a_company_admin_is_an_employee_the_door_accepts(self):
        # A SUPER_ADMIN writing for a COMPANY_ADMIN: the admin is in the
        # company through a membership, not a building grant.
        response = self.api(self.sa).post(
            ENTRIES_URL, self._booking(self.ca_a), format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        entry = TimeEntry.objects.get(pk=response.data["id"])
        self.assertEqual(entry.employee_id, self.ca_a.id)
        self.assertEqual(entry.company_id, self.company_a.id)

    def test_a_platform_admin_is_not_an_employee(self):
        # The one assigned-looking person the door must keep refusing: a
        # SUPER_ADMIN is not a provider employee and has no company to
        # anchor an entry to. The serializer says so with a field error,
        # which the dialog shows at the button.
        response = self.api(self.sa).post(
            ENTRIES_URL, self._booking(self.sa), format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("employee", response.data)
        self.assertEqual(TimeEntry.objects.filter(source_id=TICKET_41).count(), 0)

    def test_a_managers_entry_is_counted_on_the_jobs_comparison(self):
        # The comparison beside the door reads the summary narrowed to
        # the job; a manager's row must land in `by_employee` like
        # anybody else's, or the door writes a number the panel never
        # shows.
        self.api(self.ca_a).post(
            ENTRIES_URL, self._booking(self.bm_a), format="json"
        )
        response = self.api(self.ca_a).get(
            SUMMARY_URL,
            {"source_type": HourSource.TICKET, "source_id": TICKET_41},
        )
        self.assertEqual(response.status_code, 200, response.data)
        by_employee = {
            row["employee"]: row["hours"] for row in response.data["by_employee"]
        }
        self.assertEqual(by_employee.get(self.bm_a.id), "2.00")
