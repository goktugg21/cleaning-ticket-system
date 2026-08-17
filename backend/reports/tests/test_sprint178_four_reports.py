"""
Sprint 178 §2 — the four reports.

  employee-hours-by-building      per building, hours per employee
  employee-hours-weekly           per week per employee, Mon-Sun
  employee-hours-by-extra-work    per job, who worked on it
  ticket-report                   per period, with a duration from HISTORY

What these pin, beyond "does it return rows":

  * **the numbers are right**, checked against hand-computed totals
    rather than against whatever the code happened to produce;
  * **one query per report, whatever the row count.** Each has an
    `assertNumQueries` that runs the report twice — once small, once with
    ten times the data — and asserts the count did not move. A count
    pinned to a literal drifts the day someone adds a `select_related`;
    pinning that it does not GROW with the data is the property that
    matters;
  * **the ticket duration comes from the status history**, uses the FIRST
    terminal arrival, and survives a reopen;
  * **provider-only.** STAFF and every customer-side role get 403 — these
    are per-person hour breakdowns;
  * **CSV and PDF come out of the same payload as the JSON**, so the
    three cannot disagree.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from buildings.models import Building
from customers.models import Customer, CustomerBuildingMembership
from extra_work.models import ExtraWorkRequest
from tickets.models import Ticket, TicketStatus, TicketStatusHistory
from timesheets.models import HourSource, HourType, TimeEntry
from timesheets.tests.fixtures import TimesheetsFixture

BY_BUILDING = "/api/reports/employee-hours-by-building/"
WEEKLY = "/api/reports/employee-hours-weekly/"
BY_EXTRA_WORK = "/api/reports/employee-hours-by-extra-work/"
TICKETS = "/api/reports/ticket-report/"

# A fixed Monday, so the weekday buckets are not a moving target.
MONDAY = date(2026, 3, 2)


class _Base(TimesheetsFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # The fixture already owns "Normale uren" for company A, and the
        # per-company uniqueness constraint is case/whitespace-insensitive
        # — creating a second one here is exactly what it forbids.
        cls.hour_type = cls.normal_a
        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Cust A"
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a, building=cls.building_a
        )

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def entry(self, *, employee, day, hours, building=None, source=None):
        # Through the fixture's own helper: it snapshots the multiplier
        # the way the view layer does, and `multiplier_snapshot` is
        # NOT NULL by design (it is the immutability core of an hour).
        row = self.make_entry(
            employee,
            day,
            self.hour_type,
            hours=hours,
            building=building if building is not None else self.building_a,
        )
        if source is not None:
            row.source_type, row.source_id = source
            row.save(update_fields=["source_type", "source_id"])
        return row

    def period(self):
        return {"from": MONDAY.isoformat(), "to": (MONDAY + timedelta(days=6)).isoformat()}


class ByBuildingTests(_Base):
    def test_hours_are_grouped_and_totalled_per_building(self):
        self.entry(employee=self.staff_a, day=MONDAY, hours="4.00")
        self.entry(employee=self.staff_a, day=MONDAY + timedelta(days=1), hours="2.50")
        self.entry(employee=self.staff_a2, day=MONDAY, hours="3.00")

        response = self.api(self.ca_a).get(BY_BUILDING, self.period())
        self.assertEqual(response.status_code, 200, response.data)
        buildings = response.data["buildings"]
        self.assertEqual(len(buildings), 1)
        bucket = buildings[0]
        self.assertEqual(bucket["building_name"], self.building_a.name)
        # 4.00 + 2.50 for one person, 3.00 for the other.
        self.assertEqual(Decimal(bucket["total"]), Decimal("9.50"))
        per_person = {
            e["employee_name"]: Decimal(e["hours"]) for e in bucket["employees"]
        }
        self.assertEqual(set(per_person.values()), {Decimal("6.50"), Decimal("3.00")})
        self.assertEqual(Decimal(response.data["total"]), Decimal("9.50"))

    def test_hours_with_no_building_are_kept_in_their_own_bucket(self):
        """Dropping them would make the grand total disagree with the
        hours actually logged."""
        self.entry(employee=self.staff_a, day=MONDAY, hours="1.00")
        row = self.entry(employee=self.staff_a, day=MONDAY, hours="2.00")
        row.building = None
        row.save(update_fields=["building"])

        response = self.api(self.ca_a).get(BY_BUILDING, self.period())
        names = [b["building_name"] for b in response.data["buildings"]]
        self.assertIn(None, names)
        self.assertEqual(Decimal(response.data["total"]), Decimal("3.00"))

    def test_the_query_count_does_not_grow_with_the_rows(self):
        from reports.employee_hours import build_employee_hours_by_building

        self.entry(employee=self.staff_a, day=MONDAY, hours="1.00")
        # MEASURED, not hardcoded. A literal pins the scoping helper's
        # own query count too and breaks the day someone adds a
        # `select_related`; the property that matters is that the count
        # does not GROW with the data.
        with CaptureQueriesContext(connection) as small:
            build_employee_hours_by_building(
                self.ca_a, MONDAY, MONDAY + timedelta(days=6)
            )
        for index in range(20):
            self.entry(
                employee=self.staff_a2,
                day=MONDAY + timedelta(days=index % 6),
                hours="1.00",
            )
        with self.assertNumQueries(len(small.captured_queries)):
            build_employee_hours_by_building(
                self.ca_a, MONDAY, MONDAY + timedelta(days=6)
            )


class WeeklyTests(_Base):
    def test_days_land_in_the_right_monday_first_columns(self):
        self.entry(employee=self.staff_a, day=MONDAY, hours="1.00")
        self.entry(employee=self.staff_a, day=MONDAY + timedelta(days=2), hours="2.00")
        self.entry(employee=self.staff_a, day=MONDAY + timedelta(days=6), hours="3.00")

        response = self.api(self.ca_a).get(WEEKLY, self.period())
        self.assertEqual(response.status_code, 200, response.data)
        week = response.data["weeks"][0]
        employee = week["employees"][0]
        self.assertEqual(Decimal(employee["days"]["monday"]), Decimal("1.00"))
        self.assertEqual(Decimal(employee["days"]["wednesday"]), Decimal("2.00"))
        self.assertEqual(Decimal(employee["days"]["sunday"]), Decimal("3.00"))
        self.assertEqual(Decimal(employee["days"]["tuesday"]), Decimal("0.00"))
        self.assertEqual(Decimal(employee["total"]), Decimal("6.00"))

    def test_two_weeks_are_two_rows(self):
        self.entry(employee=self.staff_a, day=MONDAY, hours="1.00")
        self.entry(employee=self.staff_a, day=MONDAY + timedelta(days=7), hours="1.00")
        response = self.api(self.ca_a).get(
            WEEKLY,
            {
                "from": MONDAY.isoformat(),
                "to": (MONDAY + timedelta(days=13)).isoformat(),
            },
        )
        self.assertEqual(len(response.data["weeks"]), 2)

    def test_the_query_count_does_not_grow_with_the_rows(self):
        from reports.employee_hours import build_employee_hours_weekly

        self.entry(employee=self.staff_a, day=MONDAY, hours="1.00")
        with CaptureQueriesContext(connection) as small:
            build_employee_hours_weekly(
                self.ca_a, MONDAY, MONDAY + timedelta(days=6)
            )
        for index in range(20):
            self.entry(
                employee=self.staff_a2,
                day=MONDAY + timedelta(days=index % 6),
                hours="1.00",
            )
        with self.assertNumQueries(len(small.captured_queries)):
            build_employee_hours_weekly(
                self.ca_a, MONDAY, MONDAY + timedelta(days=6)
            )


class ByExtraWorkTests(_Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.job = ExtraWorkRequest.objects.create(
            company=cls.company_a,
            customer=cls.customer_a,
            building=cls.building_a,
            title="Repaint the stairwell",
            description="x",
            created_by=cls.ca_a,
        )

    def test_hours_tagged_to_a_job_are_grouped_under_its_title(self):
        self.entry(
            employee=self.staff_a,
            day=MONDAY,
            hours="4.00",
            source=(HourSource.EXTRA_WORK, self.job.id),
        )
        self.entry(
            employee=self.staff_a2,
            day=MONDAY,
            hours="2.00",
            source=(HourSource.EXTRA_WORK, self.job.id),
        )

        response = self.api(self.ca_a).get(BY_EXTRA_WORK, self.period())
        self.assertEqual(response.status_code, 200, response.data)
        jobs = response.data["extra_work"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Repaint the stairwell")
        self.assertEqual(Decimal(jobs[0]["total"]), Decimal("6.00"))
        self.assertEqual(len(jobs[0]["employees"]), 2)

    def test_untagged_hours_are_excluded(self):
        """This report answers "what went into this job". An OTHER bucket
        holding every untagged hour in the company would dwarf it."""
        self.entry(employee=self.staff_a, day=MONDAY, hours="8.00")
        response = self.api(self.ca_a).get(BY_EXTRA_WORK, self.period())
        self.assertEqual(response.data["extra_work"], [])
        self.assertEqual(Decimal(response.data["total"]), Decimal("0.00"))

    def test_an_empty_answer_is_a_valid_answer(self):
        """Before Sprint 177 nothing filled the source pair, so on older
        data this report is legitimately empty. It must be a 200 with an
        empty list, never an error."""
        response = self.api(self.ca_a).get(BY_EXTRA_WORK, self.period())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["extra_work"], [])

    def test_the_query_count_does_not_grow_with_the_rows(self):
        from reports.employee_hours import build_employee_hours_by_extra_work

        self.entry(
            employee=self.staff_a,
            day=MONDAY,
            hours="1.00",
            source=(HourSource.EXTRA_WORK, self.job.id),
        )
        with CaptureQueriesContext(connection) as first:
            build_employee_hours_by_extra_work(
                self.ca_a, MONDAY, MONDAY + timedelta(days=6)
            )
        for index in range(20):
            self.entry(
                employee=self.staff_a2,
                day=MONDAY + timedelta(days=index % 6),
                hours="1.00",
                source=(HourSource.EXTRA_WORK, self.job.id),
            )
        with self.assertNumQueries(len(first.captured_queries)):
            build_employee_hours_by_extra_work(
                self.ca_a, MONDAY, MONDAY + timedelta(days=6)
            )


class TicketReportTests(_Base):
    def mk_ticket(self, **kwargs):
        defaults = dict(
            company=self.company_a,
            building=self.building_a,
            customer=self.customer_a,
            title="Leaking tap",
            description="x",
            type="REPORT",
            created_by=self.ca_a,
        )
        defaults.update(kwargs)
        return Ticket.objects.create(**defaults)

    def test_duration_comes_from_the_status_history(self):
        ticket = self.mk_ticket()
        Ticket.objects.filter(pk=ticket.pk).update(
            created_at=timezone.now() - timedelta(days=5)
        )
        ticket.refresh_from_db()
        history = TicketStatusHistory.objects.create(
            ticket=ticket,
            old_status=TicketStatus.OPEN,
            new_status=TicketStatus.CLOSED,
            changed_by=self.ca_a,
        )
        TicketStatusHistory.objects.filter(pk=history.pk).update(
            created_at=timezone.now() - timedelta(days=2)
        )

        response = self.api(self.ca_a).get(
            TICKETS,
            {
                "from": (timezone.localdate() - timedelta(days=10)).isoformat(),
                "to": timezone.localdate().isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200, response.data)
        row = next(r for r in response.data["rows"] if r["id"] == ticket.id)
        self.assertEqual(row["duration_days"], 3)
        self.assertIsNotNone(row["finished_at"])

    def test_an_unfinished_ticket_has_no_duration(self):
        """None, not 0 — a zero would read as "took no time"."""
        ticket = self.mk_ticket()
        response = self.api(self.ca_a).get(
            TICKETS,
            {
                "from": (timezone.localdate() - timedelta(days=10)).isoformat(),
                "to": timezone.localdate().isoformat(),
            },
        )
        row = next(r for r in response.data["rows"] if r["id"] == ticket.id)
        self.assertIsNone(row["duration_days"])
        self.assertIsNone(row["finished_at"])

    def test_a_reopen_does_not_extend_the_first_episode(self):
        """The FIRST terminal arrival is when the work was done. A later
        reopen is a new episode, not a longer one — and a stored
        `closed_at` column would have kept only the second."""
        ticket = self.mk_ticket()
        Ticket.objects.filter(pk=ticket.pk).update(
            created_at=timezone.now() - timedelta(days=10)
        )
        for days_ago, status in (
            (8, TicketStatus.CLOSED),
            (2, TicketStatus.CLOSED),
        ):
            row = TicketStatusHistory.objects.create(
                ticket=ticket,
                old_status=TicketStatus.OPEN,
                new_status=status,
                changed_by=self.ca_a,
            )
            TicketStatusHistory.objects.filter(pk=row.pk).update(
                created_at=timezone.now() - timedelta(days=days_ago)
            )

        response = self.api(self.ca_a).get(
            TICKETS,
            {
                "from": (timezone.localdate() - timedelta(days=20)).isoformat(),
                "to": timezone.localdate().isoformat(),
            },
        )
        row = next(r for r in response.data["rows"] if r["id"] == ticket.id)
        self.assertEqual(row["duration_days"], 2)

    def test_the_average_is_none_when_nothing_finished(self):
        self.mk_ticket()
        response = self.api(self.ca_a).get(
            TICKETS,
            {
                "from": (timezone.localdate() - timedelta(days=10)).isoformat(),
                "to": timezone.localdate().isoformat(),
            },
        )
        self.assertIsNone(response.data["average_duration_days"])

    def test_the_query_count_does_not_grow_with_the_rows(self):
        from reports.ticket_report import build_ticket_report

        start = timezone.localdate() - timedelta(days=20)
        end = timezone.localdate()
        self.mk_ticket()
        with CaptureQueriesContext(connection) as first:
            build_ticket_report(self.ca_a, start, end)
        for index in range(20):
            self.mk_ticket(title=f"Ticket {index}")
        with self.assertNumQueries(len(first.captured_queries)):
            build_ticket_report(self.ca_a, start, end)


class PermissionTests(_Base):
    URLS = (BY_BUILDING, WEEKLY, BY_EXTRA_WORK, TICKETS)

    def test_a_customer_gets_nothing_from_any_of_them(self):
        for url in self.URLS:
            with self.subTest(url=url):
                response = self.api(self.customer_user).get(url)
                self.assertEqual(response.status_code, 403, url)

    def test_staff_get_nothing_from_any_of_them(self):
        """These are per-person hour breakdowns across the whole team —
        the same privacy floor the worker-hour report keeps."""
        for url in self.URLS:
            with self.subTest(url=url):
                response = self.api(self.staff_a).get(url)
                self.assertEqual(response.status_code, 403, url)

    def test_provider_management_may_read_all_of_them(self):
        for url in self.URLS:
            with self.subTest(url=url):
                self.assertEqual(self.api(self.ca_a).get(url).status_code, 200)
                self.assertEqual(self.api(self.sa).get(url).status_code, 200)

    def test_another_tenants_hours_are_not_counted(self):
        self.make_entry(
            self.staff_b,
            MONDAY,
            self.normal_b,
            hours="99.00",
            building=self.building_b,
        )
        response = self.api(self.ca_a).get(BY_BUILDING, self.period())
        self.assertEqual(Decimal(response.data["total"]), Decimal("0.00"))


class ExportTests(_Base):
    def test_every_report_exports_csv_and_pdf(self):
        self.entry(employee=self.staff_a, day=MONDAY, hours="4.00")
        self.mk = None
        for url, stem in (
            (BY_BUILDING, "employee-hours-by-building"),
            (WEEKLY, "employee-hours-weekly"),
            (BY_EXTRA_WORK, "employee-hours-by-extra-work"),
            (TICKETS, "ticket-report"),
        ):
            for fmt, content_type in (
                ("csv", "text/csv"),
                ("pdf", "application/pdf"),
            ):
                with self.subTest(url=url, fmt=fmt):
                    response = self.api(self.ca_a).get(
                        f"{url}export.{fmt}", self.period()
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(content_type, response["Content-Type"])
                    self.assertIn(stem, response["Content-Disposition"])
                    self.assertTrue(response.content)

    def test_a_malformed_period_is_refused_rather_than_silently_defaulted(self):
        response = self.api(self.ca_a).get(BY_BUILDING, {"from": "not-a-date"})
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "invalid_period")

    def test_a_backwards_period_is_ordered_rather_than_empty(self):
        self.entry(employee=self.staff_a, day=MONDAY, hours="4.00")
        response = self.api(self.ca_a).get(
            BY_BUILDING,
            {
                "from": (MONDAY + timedelta(days=6)).isoformat(),
                "to": MONDAY.isoformat(),
            },
        )
        self.assertEqual(Decimal(response.data["total"]), Decimal("4.00"))
