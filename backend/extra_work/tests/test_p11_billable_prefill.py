"""
P-11 B3 — `GET /api/extra-work/<id>/timesheet-hours/`: the job's
timesheet, for the Money tab's billable-hours prefill.

Two hour concepts stay two things (payroll is not invoicing), but they
must know each other: the panel proposes the sum the crew already
reported. Pins:

  * the rows are the JOB lines of this request AND its spawned tickets
    (source EXTRA_WORK on the request's id, source TICKET on the
    spawned ticket's id) — nothing else, however near;
  * each row carries person, day, hours, hour type and its multiplier
    snapshot; `total_hours` is their sum;
  * provider-only: STAFF and customer-side users are refused at the
    door (403, before any row is looked at); a foreign tenant's admin
    is a 404 through the scoped resolution (H-1).
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from rest_framework.test import APITestCase

from accounts.models import UserRole
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketPriority, TicketStatus, TicketType
from timesheets.models import HourSource, HourType, TimeEntry


def _url(pk: int) -> str:
    return f"/api/extra-work/{pk}/timesheet-hours/"


class TimesheetHoursFixture(TenantFixtureMixin):
    def setUp(self):
        super().setUp()
        self.worker = self.make_user("p11-ts-worker@example.com", UserRole.STAFF)
        self.normal = HourType.objects.create(
            company=self.company,
            name="Normale uren",
            multiplier=Decimal("1.00"),
            sort_order=10,
        )
        self.weekend = HourType.objects.create(
            company=self.company,
            name="Weekend uren",
            multiplier=Decimal("1.50"),
            sort_order=20,
        )
        self.ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Opleverschoonmaak",
            description="x",
            status=ExtraWorkStatus.IN_PROGRESS,
        )
        self.ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Opleverschoonmaak (werk)",
            description="x",
            type=TicketType.REQUEST,
            priority=TicketPriority.NORMAL,
            status=TicketStatus.IN_PROGRESS,
            extra_work_request=self.ew,
        )

    def entry(self, *, hours, source_type, source_id, hour_type=None, day=None):
        chosen_type = hour_type or self.normal
        return TimeEntry.objects.create(
            company=self.company,
            employee=self.worker,
            date=day or dt.date(2026, 8, 29),
            hour_type=chosen_type,
            hours=Decimal(hours),
            # The serializer snapshots this on the write path; a direct
            # ORM create says it itself.
            multiplier_snapshot=chosen_type.multiplier,
            source_type=source_type,
            source_id=source_id,
            created_by=self.super_admin,
        )


class TimesheetHoursReadTests(TimesheetHoursFixture, APITestCase):
    def test_the_jobs_lines_arrive_from_both_sources_and_sum(self):
        self.entry(
            hours="4.00",
            source_type=HourSource.TICKET,
            source_id=self.ticket.id,
            hour_type=self.weekend,
        )
        self.entry(
            hours="1.00", source_type=HourSource.EXTRA_WORK, source_id=self.ew.id
        )
        # Near misses that must NOT arrive: another ticket's line, an
        # untagged line.
        self.entry(hours="9.00", source_type=HourSource.TICKET, source_id=999999)
        self.entry(hours="7.00", source_type=HourSource.OTHER, source_id=None)

        self.client.force_authenticate(self.company_admin)
        response = self.client.get(_url(self.ew.id))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["total_hours"], "5.00")
        rows = response.data["entries"]
        self.assertEqual(len(rows), 2)
        weekend_row = next(r for r in rows if r["hour_type_name"] == "Weekend uren")
        self.assertEqual(weekend_row["hours"], "4.00")
        self.assertEqual(weekend_row["hour_type_multiplier"], "1.50")
        self.assertEqual(weekend_row["source_type"], "TICKET")
        self.assertEqual(weekend_row["source_id"], self.ticket.id)
        self.assertTrue(weekend_row["employee_name"])
        self.assertEqual(weekend_row["date"], "2026-08-29")

    def test_staff_are_refused_at_the_door(self):
        self.client.force_authenticate(self.worker)
        response = self.client.get(_url(self.ew.id))
        # The role gate answers before the scoped resolution — the same
        # shape the dates endpoint uses. Nothing about the row leaks.
        self.assertEqual(response.status_code, 403, response.data)

    def test_a_customer_side_user_is_refused(self):
        self.client.force_authenticate(self.customer_user)
        response = self.client.get(_url(self.ew.id))
        self.assertEqual(response.status_code, 403, response.data)

    def test_a_foreign_admin_is_a_404(self):
        self.client.force_authenticate(self.other_company_admin)
        response = self.client.get(_url(self.ew.id))
        self.assertEqual(response.status_code, 404, response.data)
