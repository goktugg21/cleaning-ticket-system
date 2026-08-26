"""W-FIX1 D8 (audit F47) — the entries endpoint checks the job.

`POST /api/timesheets/entries/` with `source_type=TICKET` took ANY
`source_id`: a nonexistent ticket, another company's ticket, a ticket
the actor could not open. The ticket door refused at the button only.
Now the pair is resolved through the same scopers every list uses, in
the entry's own company, and refused with a stable code otherwise.
"""
from __future__ import annotations

import datetime as dt

from customers.models import Customer
from tickets.models import Ticket, TicketStatus
from timesheets.models import HourSource, TimeEntry

from .fixtures import ENTRIES_URL, TimesheetsFixture

MONDAY = dt.date(2026, 8, 3)


class EntrySourceScopeTests(TimesheetsFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ticket_a = Ticket.objects.create(
            company=cls.company_a,
            building=cls.building_a,
            customer=cls.customer_a,
            created_by=cls.ca_a,
            title="Ours",
            description="x",
            status=TicketStatus.OPEN,
        )
        cls.customer_b = Customer.objects.create(
            company=cls.company_b, name="Customer B"
        )
        cls.ticket_b = Ticket.objects.create(
            company=cls.company_b,
            building=cls.building_b,
            customer=cls.customer_b,
            created_by=cls.ca_b,
            title="Theirs",
            description="x",
            status=TicketStatus.OPEN,
        )

    def _booking(self, **overrides):
        body = {
            "employee": self.staff_a.id,
            "date": MONDAY.isoformat(),
            "hour_type": self.normal_a.id,
            "hours": "1.00",
            "building": self.building_a.id,
            "company": self.company_a.id,
            "source_type": HourSource.TICKET,
            "source_id": self.ticket_a.id,
        }
        body.update(overrides)
        return body

    def test_a_ticket_in_scope_is_accepted(self):
        response = self.api(self.ca_a).post(ENTRIES_URL, self._booking(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["source_id"], self.ticket_a.id)

    def test_another_companys_ticket_is_refused(self):
        response = self.api(self.ca_a).post(
            ENTRIES_URL, self._booking(source_id=self.ticket_b.id), format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("source_id", response.data)
        self.assertEqual(response.data["source_id"][0].code, "timesheet_source_invalid")
        self.assertFalse(TimeEntry.objects.filter(source_id=self.ticket_b.id).exists())

    def test_a_ticket_that_does_not_exist_is_refused(self):
        response = self.api(self.ca_a).post(
            ENTRIES_URL, self._booking(source_id=999999), format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["source_id"][0].code, "timesheet_source_invalid")

    def test_a_staff_member_cannot_file_against_a_ticket_they_cannot_see(self):
        """Same company, but STAFF scope is by building visibility — a
        ticket at a building they may not enter is not their job."""
        response = self.api(self.staff_b).post(
            ENTRIES_URL,
            {
                "employee": self.staff_b.id,
                "date": MONDAY.isoformat(),
                "hour_type": self.normal_b.id,
                "hours": "1.00",
                "building": self.building_b.id,
                "company": self.company_b.id,
                "source_type": HourSource.TICKET,
                "source_id": self.ticket_a.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["source_id"][0].code, "timesheet_source_invalid")

    def test_an_untagged_entry_needs_no_job(self):
        body = self._booking()
        body.pop("source_type")
        body.pop("source_id")
        response = self.api(self.ca_a).post(ENTRIES_URL, body, format="json")
        self.assertEqual(response.status_code, 201, response.data)
