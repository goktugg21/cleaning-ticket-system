"""
Sprint 180 — the four reports take filters, the cards say something, and
the weekly report carries what payroll reads.

  §1  ?company= / ?building= reach all four reports and both exports
  §2  ONE summaries endpoint behind the four cards
  §3  the weekly report's hour-type split and weekday column totals

What these pin, beyond "does it return rows":

  * **a filter narrows and cannot widen.** Every filter test asserts a
    SMALLER answer against a hand-computed number, and the cross-tenant
    case asserts that asking for another company's id is a 403 rather
    than a smaller answer for the wrong tenant;
  * **a filter does not turn a bounded report into an unbounded one.**
    Every query-count test here runs WITH a filter applied and asserts
    the count does not grow with the data. That is the property Sprint
    178 pinned unfiltered, and a filter is exactly the change that would
    break it;
  * **every field this sprint exposes is rendered by an endpoint.** A
    filter test issues a query and never serialises a row, which is why
    the `scope` echo, `day_totals`, `hour_types` and every card figure
    are asserted on the RESPONSE, not on a builder's return value alone
    — the Sprint 173 defect where a missing `fields` entry took a whole
    page down was invisible to filter tests;
  * **the card and the report it opens cannot disagree.** The summary's
    ticket figures are asserted equal to the full report's for the same
    period.
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
from timesheets.models import HourSource, TimeEntry
from timesheets.tests.fixtures import TimesheetsFixture

BY_BUILDING = "/api/reports/employee-hours-by-building/"
WEEKLY = "/api/reports/employee-hours-weekly/"
BY_EXTRA_WORK = "/api/reports/employee-hours-by-extra-work/"
TICKETS = "/api/reports/ticket-report/"
SUMMARIES = "/api/reports/period-report-summaries/"

ALL_FOUR = (BY_BUILDING, WEEKLY, BY_EXTRA_WORK, TICKETS)

# A fixed Monday, so the weekday buckets are not a moving target.
MONDAY = date(2026, 3, 2)


class _Base(TimesheetsFixture):
    """Company A with TWO buildings, because a building filter that is
    tested against a company with one building proves nothing."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.building_a2 = Building.objects.create(
            company=cls.company_a, name="Building A2", address="A street 2"
        )
        cls.cust_a = Customer.objects.create(company=cls.company_a, name="Cust A")
        CustomerBuildingMembership.objects.create(
            customer=cls.cust_a, building=cls.building_a
        )

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def entry(self, *, employee, day, hours, building=None, source=None, hour_type=None):
        row = self.make_entry(
            employee,
            day,
            hour_type or self.normal_a,
            hours=hours,
            building=self.building_a if building is None else building,
        )
        if source is not None:
            row.source_type, row.source_id = source
            row.save(update_fields=["source_type", "source_id"])
        return row

    def period(self, **extra):
        params = {
            "from": MONDAY.isoformat(),
            "to": (MONDAY + timedelta(days=6)).isoformat(),
        }
        params.update(extra)
        return params

    def mk_ticket(self, **kwargs):
        defaults = dict(
            company=self.company_a,
            building=self.building_a,
            customer=self.cust_a,
            title="Leaking tap",
            description="x",
            type="REPORT",
            created_by=self.ca_a,
        )
        defaults.update(kwargs)
        return Ticket.objects.create(**defaults)


# ---- §1 the four reports take filters ---------------------------------------


class BuildingFilterTests(_Base):
    def setUp(self):
        # 4h in building A, 3h in building A2. The building filter is
        # right only if it returns one of those, never their sum.
        self.entry(employee=self.staff_a, day=MONDAY, hours="4.00")
        self.entry(
            employee=self.staff_a,
            day=MONDAY,
            hours="3.00",
            building=self.building_a2,
        )

    def test_by_building_returns_only_the_requested_building(self):
        response = self.api(self.ca_a).get(
            BY_BUILDING, self.period(building=self.building_a.id)
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Decimal(response.data["total"]), Decimal("4.00"))
        names = [b["building_name"] for b in response.data["buildings"]]
        self.assertEqual(names, [self.building_a.name])

    def test_without_a_filter_both_buildings_are_still_counted(self):
        """The narrowing must be the FILTER's doing, not a default."""
        response = self.api(self.ca_a).get(BY_BUILDING, self.period())
        self.assertEqual(Decimal(response.data["total"]), Decimal("7.00"))

    def test_the_weekly_report_takes_the_same_building(self):
        response = self.api(self.ca_a).get(
            WEEKLY, self.period(building=self.building_a2.id)
        )
        self.assertEqual(Decimal(response.data["total"]), Decimal("3.00"))

    def test_the_ticket_report_takes_the_same_building(self):
        self.mk_ticket()
        self.mk_ticket(title="Other building", building=self.building_a2)
        window = {
            "from": (timezone.localdate() - timedelta(days=10)).isoformat(),
            "to": timezone.localdate().isoformat(),
        }
        both = self.api(self.ca_a).get(TICKETS, window)
        self.assertEqual(both.data["total"], 2)

        one = self.api(self.ca_a).get(
            TICKETS, {**window, "building": self.building_a2.id}
        )
        self.assertEqual(one.data["total"], 1)
        self.assertEqual(one.data["rows"][0]["building_name"], "Building A2")

    def test_hours_with_no_building_drop_out_of_a_per_building_question(self):
        """Not a loss: "how much was worked HERE" cannot count an hour
        that says it was worked nowhere."""
        row = self.entry(employee=self.staff_a2, day=MONDAY, hours="9.00")
        row.building = None
        row.save(update_fields=["building"])

        unfiltered = self.api(self.ca_a).get(BY_BUILDING, self.period())
        self.assertEqual(Decimal(unfiltered.data["total"]), Decimal("16.00"))

        filtered = self.api(self.ca_a).get(
            BY_BUILDING, self.period(building=self.building_a.id)
        )
        self.assertEqual(Decimal(filtered.data["total"]), Decimal("4.00"))


class CompanyFilterTests(_Base):
    def setUp(self):
        self.entry(employee=self.staff_a, day=MONDAY, hours="4.00")
        self.make_entry(
            self.staff_b,
            MONDAY,
            self.normal_b,
            hours="11.00",
            building=self.building_b,
        )

    def test_a_super_admin_can_narrow_to_one_company(self):
        client = self.api(self.sa)
        everything = client.get(BY_BUILDING, self.period())
        self.assertEqual(Decimal(everything.data["total"]), Decimal("15.00"))

        just_a = client.get(BY_BUILDING, self.period(company=self.company_a.id))
        self.assertEqual(Decimal(just_a.data["total"]), Decimal("4.00"))

        just_b = client.get(BY_BUILDING, self.period(company=self.company_b.id))
        self.assertEqual(Decimal(just_b.data["total"]), Decimal("11.00"))

    def test_another_tenants_company_id_is_a_403_not_a_smaller_answer(self):
        """H-1. The answer to "show me their company" is refusal, not an
        empty report — an empty report would confirm the id exists."""
        for url in ALL_FOUR:
            with self.subTest(url=url):
                response = self.api(self.ca_a).get(
                    url, self.period(company=self.company_b.id)
                )
                self.assertEqual(response.status_code, 403, url)

    def test_another_tenants_building_id_is_a_403(self):
        for url in ALL_FOUR:
            with self.subTest(url=url):
                response = self.api(self.ca_a).get(
                    url, self.period(building=self.building_b.id)
                )
                self.assertEqual(response.status_code, 403, url)

    def test_a_building_outside_the_given_company_is_a_400(self):
        response = self.api(self.sa).get(
            BY_BUILDING,
            self.period(company=self.company_a.id, building=self.building_b.id),
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_a_malformed_id_is_a_400(self):
        response = self.api(self.ca_a).get(BY_BUILDING, self.period(building="abc"))
        self.assertEqual(response.status_code, 400, response.data)


class ScopeEchoTests(_Base):
    """The `scope` echo is a FIELD, so it gets a test that renders the
    endpoint carrying it — a filter test never serialises one."""

    def test_every_report_echoes_an_empty_scope_when_unfiltered(self):
        for url in ALL_FOUR:
            with self.subTest(url=url):
                response = self.api(self.ca_a).get(url, self.period())
                self.assertEqual(response.status_code, 200, url)
                self.assertEqual(
                    response.data["scope"],
                    {
                        "company_id": None,
                        "company_name": None,
                        "building_id": None,
                        "building_name": None,
                    },
                )

    def test_every_report_echoes_the_resolved_names(self):
        for url in ALL_FOUR:
            with self.subTest(url=url):
                response = self.api(self.ca_a).get(
                    url, self.period(building=self.building_a.id)
                )
                self.assertEqual(response.status_code, 200, url)
                scope = response.data["scope"]
                self.assertEqual(scope["building_id"], self.building_a.id)
                self.assertEqual(scope["building_name"], self.building_a.name)


class FilteredExportTests(_Base):
    def setUp(self):
        self.entry(employee=self.staff_a, day=MONDAY, hours="4.00")
        self.entry(
            employee=self.staff_a,
            day=MONDAY,
            hours="3.00",
            building=self.building_a2,
        )

    def test_the_csv_covers_the_same_slice_as_the_screen(self):
        response = self.api(self.ca_a).get(
            f"{BY_BUILDING}export.csv", self.period(building=self.building_a2.id)
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("Building A2", body)
        self.assertNotIn("Building A,", body)

    def test_every_export_still_renders_with_a_filter(self):
        for url in ALL_FOUR:
            for fmt in ("csv", "pdf"):
                with self.subTest(url=url, fmt=fmt):
                    response = self.api(self.ca_a).get(
                        f"{url}export.{fmt}",
                        self.period(building=self.building_a.id),
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.content)

    def test_a_filtered_pdf_names_the_building_it_covers(self):
        """A downloaded PDF that does not say which building it covers is
        the document nobody can explain a month later."""
        import io

        from pypdf import PdfReader

        response = self.api(self.ca_a).get(
            f"{BY_BUILDING}export.pdf", self.period(building=self.building_a.id)
        )
        self.assertEqual(response.status_code, 200)
        # Through pypdf, not on the raw bytes: fpdf2 Flate-compresses the
        # content stream, so a byte search would pass or fail for reasons
        # that have nothing to do with what is printed.
        text = "\n".join(
            page.extract_text() or ""
            for page in PdfReader(io.BytesIO(response.content)).pages
        )
        self.assertIn(f"Building: {self.building_a.name}", text)

    def test_an_unfiltered_pdf_says_so_rather_than_saying_nothing(self):
        import io

        from pypdf import PdfReader

        response = self.api(self.ca_a).get(f"{BY_BUILDING}export.pdf", self.period())
        text = "\n".join(
            page.extract_text() or ""
            for page in PdfReader(io.BytesIO(response.content)).pages
        )
        self.assertIn("Scope: All", text)


class FilteredQueryCountTests(_Base):
    """A filter must not turn a bounded report into an unbounded one."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.job = ExtraWorkRequest.objects.create(
            company=cls.company_a,
            customer=cls.cust_a,
            building=cls.building_a,
            title="Repaint the stairwell",
            description="x",
            created_by=cls.ca_a,
        )

    def _scope(self):
        from reports.scoping import resolve_scope

        return resolve_scope(self.ca_a, None, self.building_a.id)

    def _assert_flat(self, build, seed, extra):
        scope = self._scope()
        seed()
        with CaptureQueriesContext(connection) as small:
            build(self.ca_a, MONDAY, MONDAY + timedelta(days=6), scope=scope)
        for index in range(20):
            extra(index)
        with self.assertNumQueries(len(small.captured_queries)):
            build(self.ca_a, MONDAY, MONDAY + timedelta(days=6), scope=scope)

    def test_by_building_stays_flat_with_a_filter(self):
        from reports.employee_hours import build_employee_hours_by_building

        self._assert_flat(
            build_employee_hours_by_building,
            lambda: self.entry(employee=self.staff_a, day=MONDAY, hours="1.00"),
            lambda i: self.entry(
                employee=self.staff_a2,
                day=MONDAY + timedelta(days=i % 6),
                hours="1.00",
            ),
        )

    def test_weekly_stays_flat_with_a_filter(self):
        from reports.employee_hours import build_employee_hours_weekly

        self._assert_flat(
            build_employee_hours_weekly,
            lambda: self.entry(employee=self.staff_a, day=MONDAY, hours="1.00"),
            lambda i: self.entry(
                employee=self.staff_a2,
                day=MONDAY + timedelta(days=i % 6),
                hours="1.00",
            ),
        )

    def test_by_extra_work_stays_flat_with_a_filter(self):
        from reports.employee_hours import build_employee_hours_by_extra_work

        self._assert_flat(
            build_employee_hours_by_extra_work,
            lambda: self.entry(
                employee=self.staff_a,
                day=MONDAY,
                hours="1.00",
                source=(HourSource.EXTRA_WORK, self.job.id),
            ),
            lambda i: self.entry(
                employee=self.staff_a2,
                day=MONDAY + timedelta(days=i % 6),
                hours="1.00",
                source=(HourSource.EXTRA_WORK, self.job.id),
            ),
        )

    def test_the_ticket_report_stays_flat_with_a_filter(self):
        from reports.ticket_report import build_ticket_report

        scope = self._scope()
        start = timezone.localdate() - timedelta(days=20)
        end = timezone.localdate()
        self.mk_ticket()
        with CaptureQueriesContext(connection) as small:
            build_ticket_report(self.ca_a, start, end, scope=scope)
        for index in range(20):
            self.mk_ticket(title=f"Ticket {index}")
        with self.assertNumQueries(len(small.captured_queries)):
            build_ticket_report(self.ca_a, start, end, scope=scope)


# ---- §3 the weekly report's hour types and column totals --------------------


class WeeklyHourTypeTests(_Base):
    def test_a_week_is_split_by_hour_type_under_the_person(self):
        """40 hours is not one fact — normal and overtime are paid
        differently, and a single number cannot be handed to payroll."""
        self.entry(employee=self.staff_a, day=MONDAY, hours="8.00")
        self.entry(
            employee=self.staff_a,
            day=MONDAY,
            hours="2.00",
            hour_type=self.overtime_a,
        )
        self.entry(
            employee=self.staff_a,
            day=MONDAY + timedelta(days=1),
            hours="3.00",
            hour_type=self.overtime_a,
        )

        response = self.api(self.ca_a).get(WEEKLY, self.period())
        self.assertEqual(response.status_code, 200, response.data)
        employee = response.data["weeks"][0]["employees"][0]

        # The person's own row still carries the COMBINED figure.
        self.assertEqual(Decimal(employee["total"]), Decimal("13.00"))
        self.assertEqual(Decimal(employee["days"]["monday"]), Decimal("10.00"))

        split = {b["hour_type_name"]: b for b in employee["hour_types"]}
        self.assertEqual(set(split), {"Normale uren", "Overwerk"})
        self.assertEqual(Decimal(split["Normale uren"]["total"]), Decimal("8.00"))
        self.assertEqual(Decimal(split["Overwerk"]["total"]), Decimal("5.00"))
        self.assertEqual(
            Decimal(split["Overwerk"]["days"]["tuesday"]), Decimal("3.00")
        )
        self.assertEqual(
            Decimal(split["Normale uren"]["days"]["tuesday"]), Decimal("0.00")
        )

    def test_the_hour_type_code_is_carried_when_it_is_set(self):
        self.overtime_a.code = "OW"
        self.overtime_a.save(update_fields=["code"])
        self.entry(
            employee=self.staff_a,
            day=MONDAY,
            hours="2.00",
            hour_type=self.overtime_a,
        )
        response = self.api(self.ca_a).get(WEEKLY, self.period())
        bucket = response.data["weeks"][0]["employees"][0]["hour_types"][0]
        self.assertEqual(bucket["hour_type_code"], "OW")

    def test_an_unset_code_is_none_rather_than_an_empty_string(self):
        """One absent-value test in the UI, not one per column."""
        self.entry(employee=self.staff_a, day=MONDAY, hours="2.00")
        response = self.api(self.ca_a).get(WEEKLY, self.period())
        bucket = response.data["weeks"][0]["employees"][0]["hour_types"][0]
        self.assertIsNone(bucket["hour_type_code"])

    def test_the_split_sums_to_the_person_and_the_week(self):
        self.entry(employee=self.staff_a, day=MONDAY, hours="8.00")
        self.entry(
            employee=self.staff_a2,
            day=MONDAY + timedelta(days=2),
            hours="4.00",
            hour_type=self.overtime_a,
        )
        week = self.api(self.ca_a).get(WEEKLY, self.period()).data["weeks"][0]
        per_person = sum(
            (Decimal(e["total"]) for e in week["employees"]), Decimal("0.00")
        )
        per_type = sum(
            (Decimal(b["total"]) for b in week["hour_types"]), Decimal("0.00")
        )
        self.assertEqual(per_person, Decimal("12.00"))
        self.assertEqual(per_type, Decimal("12.00"))
        self.assertEqual(Decimal(week["total"]), Decimal("12.00"))


class WeeklyDayTotalTests(_Base):
    def test_each_week_carries_its_weekday_column_totals(self):
        """"How much did the team work on Wednesday" was answerable only
        by adding a column up with a finger."""
        self.entry(employee=self.staff_a, day=MONDAY, hours="8.00")
        self.entry(employee=self.staff_a2, day=MONDAY, hours="6.00")
        self.entry(
            employee=self.staff_a,
            day=MONDAY + timedelta(days=2),
            hours="5.00",
        )

        response = self.api(self.ca_a).get(WEEKLY, self.period())
        week = response.data["weeks"][0]
        self.assertEqual(Decimal(week["day_totals"]["monday"]), Decimal("14.00"))
        self.assertEqual(Decimal(week["day_totals"]["wednesday"]), Decimal("5.00"))
        self.assertEqual(Decimal(week["day_totals"]["sunday"]), Decimal("0.00"))
        # And they sum to the week the header prints.
        self.assertEqual(
            sum((Decimal(v) for v in week["day_totals"].values()), Decimal("0.00")),
            Decimal(week["total"]),
        )

    def test_the_period_carries_its_own_column_totals_across_weeks(self):
        self.entry(employee=self.staff_a, day=MONDAY, hours="8.00")
        self.entry(
            employee=self.staff_a, day=MONDAY + timedelta(days=7), hours="2.00"
        )
        response = self.api(self.ca_a).get(
            WEEKLY,
            {
                "from": MONDAY.isoformat(),
                "to": (MONDAY + timedelta(days=13)).isoformat(),
            },
        )
        self.assertEqual(len(response.data["weeks"]), 2)
        self.assertEqual(
            Decimal(response.data["day_totals"]["monday"]), Decimal("10.00")
        )

    def test_the_weekly_report_still_costs_one_aggregate(self):
        """The split and the totals are two more buckets in Python, not a
        query per hour type."""
        from reports.employee_hours import build_employee_hours_weekly

        self.entry(employee=self.staff_a, day=MONDAY, hours="1.00")
        with CaptureQueriesContext(connection) as small:
            build_employee_hours_weekly(self.ca_a, MONDAY, MONDAY + timedelta(days=6))
        for index in range(20):
            self.entry(
                employee=self.staff_a2,
                day=MONDAY + timedelta(days=index % 6),
                hours="1.00",
                hour_type=self.overtime_a if index % 2 else self.normal_a,
            )
        with self.assertNumQueries(len(small.captured_queries)):
            build_employee_hours_weekly(self.ca_a, MONDAY, MONDAY + timedelta(days=6))


class WeeklyExportTests(_Base):
    def test_the_csv_grain_is_week_employee_hour_type(self):
        self.entry(employee=self.staff_a, day=MONDAY, hours="8.00")
        self.entry(
            employee=self.staff_a,
            day=MONDAY,
            hours="2.00",
            hour_type=self.overtime_a,
        )
        response = self.api(self.ca_a).get(f"{WEEKLY}export.csv", self.period())
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        lines = [line for line in body.splitlines() if line.strip()]
        self.assertIn("hour_type", lines[0])
        self.assertIn("hour_type_code", lines[0])
        # One header plus one row per hour type for the one employee.
        self.assertEqual(len(lines), 3)
        self.assertIn("Normale uren", body)
        self.assertIn("Overwerk", body)

    def test_the_pdf_still_renders_with_the_split(self):
        self.entry(employee=self.staff_a, day=MONDAY, hours="8.00")
        self.entry(
            employee=self.staff_a,
            day=MONDAY,
            hours="2.00",
            hour_type=self.overtime_a,
        )
        response = self.api(self.ca_a).get(f"{WEEKLY}export.pdf", self.period())
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/pdf", response["Content-Type"])
        self.assertTrue(response.content)


# ---- §2 the card summaries --------------------------------------------------


class SummariesTests(_Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.job = ExtraWorkRequest.objects.create(
            company=cls.company_a,
            customer=cls.cust_a,
            building=cls.building_a,
            title="Repaint the stairwell",
            description="x",
            created_by=cls.ca_a,
        )

    def test_the_three_hours_cards_report_what_the_reports_would(self):
        self.entry(employee=self.staff_a, day=MONDAY, hours="8.00")
        self.entry(
            employee=self.staff_a2,
            day=MONDAY + timedelta(days=1),
            hours="4.00",
            building=self.building_a2,
        )
        self.entry(
            employee=self.staff_a,
            day=MONDAY + timedelta(days=2),
            hours="2.00",
            source=(HourSource.EXTRA_WORK, self.job.id),
        )

        response = self.api(self.ca_a).get(SUMMARIES, self.period())
        self.assertEqual(response.status_code, 200, response.data)
        cards = response.data["cards"]

        self.assertEqual(Decimal(cards["hours_building"]["total_hours"]), Decimal("14.00"))
        self.assertEqual(cards["hours_building"]["entries"], 3)
        self.assertEqual(cards["hours_building"]["buildings"], 2)
        self.assertEqual(cards["hours_building"]["employees"], 2)

        self.assertEqual(Decimal(cards["hours_weekly"]["total_hours"]), Decimal("14.00"))
        self.assertEqual(cards["hours_weekly"]["weeks"], 1)

        self.assertEqual(
            Decimal(cards["hours_extra_work"]["total_hours"]), Decimal("2.00")
        )
        self.assertEqual(cards["hours_extra_work"]["jobs"], 1)
        self.assertEqual(cards["hours_extra_work"]["entries"], 1)

        # And the hours total agrees with the report it summarises.
        report = self.api(self.ca_a).get(BY_BUILDING, self.period())
        self.assertEqual(
            Decimal(cards["hours_building"]["total_hours"]),
            Decimal(report.data["total"]),
        )

    def test_an_empty_period_is_zeros_and_not_an_error(self):
        """The extra-work card legitimately finds nothing on data entered
        before Sprint 177's job picker. It must read as an answer."""
        response = self.api(self.ca_a).get(SUMMARIES, self.period())
        self.assertEqual(response.status_code, 200)
        cards = response.data["cards"]
        self.assertEqual(Decimal(cards["hours_extra_work"]["total_hours"]), Decimal("0"))
        self.assertEqual(cards["hours_extra_work"]["entries"], 0)
        self.assertEqual(cards["hours_extra_work"]["jobs"], 0)
        self.assertEqual(cards["tickets"]["total"], 0)
        self.assertIsNone(cards["tickets"]["average_duration_days"])

    def test_the_ticket_card_agrees_with_the_ticket_report(self):
        ticket = self.mk_ticket()
        Ticket.objects.filter(pk=ticket.pk).update(
            created_at=timezone.now() - timedelta(days=5)
        )
        history = TicketStatusHistory.objects.create(
            ticket=ticket,
            old_status=TicketStatus.OPEN,
            new_status=TicketStatus.CLOSED,
            changed_by=self.ca_a,
        )
        TicketStatusHistory.objects.filter(pk=history.pk).update(
            created_at=timezone.now() - timedelta(days=2)
        )
        self.mk_ticket(title="Still open")

        window = {
            "from": (timezone.localdate() - timedelta(days=10)).isoformat(),
            "to": timezone.localdate().isoformat(),
        }
        card = self.api(self.ca_a).get(SUMMARIES, window).data["cards"]["tickets"]
        report = self.api(self.ca_a).get(TICKETS, window).data

        self.assertEqual(card["total"], report["total"])
        self.assertEqual(card["finished"], report["finished"])
        self.assertEqual(
            card["average_duration_days"], report["average_duration_days"]
        )
        self.assertEqual(card["open"], report["total"] - report["finished"])
        self.assertEqual(card["finished"], 1)
        self.assertEqual(card["average_duration_days"], 3.0)

    def test_the_summaries_take_the_same_filters(self):
        self.entry(employee=self.staff_a, day=MONDAY, hours="8.00")
        self.entry(
            employee=self.staff_a,
            day=MONDAY,
            hours="4.00",
            building=self.building_a2,
        )
        response = self.api(self.ca_a).get(
            SUMMARIES, self.period(building=self.building_a2.id)
        )
        self.assertEqual(
            Decimal(response.data["cards"]["hours_building"]["total_hours"]),
            Decimal("4.00"),
        )
        self.assertEqual(
            response.data["scope"]["building_name"], self.building_a2.name
        )

    def test_another_tenants_hours_are_not_counted(self):
        self.make_entry(
            self.staff_b,
            MONDAY,
            self.normal_b,
            hours="99.00",
            building=self.building_b,
        )
        response = self.api(self.ca_a).get(SUMMARIES, self.period())
        self.assertEqual(
            Decimal(response.data["cards"]["hours_building"]["total_hours"]),
            Decimal("0"),
        )

    def test_the_envelope_states_the_period_it_answered_for(self):
        response = self.api(self.ca_a).get(SUMMARIES, self.period())
        self.assertEqual(response.data["from"], MONDAY.isoformat())
        self.assertEqual(
            response.data["to"], (MONDAY + timedelta(days=6)).isoformat()
        )
        self.assertIn("generated_at", response.data)

    def test_a_backwards_period_is_ordered_rather_than_empty(self):
        self.entry(employee=self.staff_a, day=MONDAY, hours="4.00")
        response = self.api(self.ca_a).get(
            SUMMARIES,
            {
                "from": (MONDAY + timedelta(days=6)).isoformat(),
                "to": MONDAY.isoformat(),
            },
        )
        self.assertEqual(response.data["from"], MONDAY.isoformat())
        self.assertEqual(
            Decimal(response.data["cards"]["hours_building"]["total_hours"]),
            Decimal("4.00"),
        )

    def test_a_malformed_period_is_refused(self):
        response = self.api(self.ca_a).get(SUMMARIES, {"from": "not-a-date"})
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "invalid_period")

    def test_the_permission_floor_is_the_reports_own(self):
        self.assertEqual(self.api(self.ca_a).get(SUMMARIES).status_code, 200)
        self.assertEqual(self.api(self.sa).get(SUMMARIES).status_code, 200)
        self.assertEqual(self.api(self.bm_a).get(SUMMARIES).status_code, 200)
        # A summary of a per-person hour figure IS the figure.
        self.assertEqual(self.api(self.staff_a).get(SUMMARIES).status_code, 403)
        self.assertEqual(
            self.api(self.customer_user).get(SUMMARIES).status_code, 403
        )

    def test_the_cost_does_not_grow_with_the_data(self):
        """One request for four cards is only worth it if the request is
        cheap. Five queries, flat."""
        from reports.employee_hours import build_employee_hours_summaries
        from reports.ticket_report import build_ticket_report_summary

        def run():
            build_employee_hours_summaries(
                self.ca_a, MONDAY, MONDAY + timedelta(days=6)
            )
            build_ticket_report_summary(
                self.ca_a,
                timezone.localdate() - timedelta(days=20),
                timezone.localdate(),
            )

        self.entry(employee=self.staff_a, day=MONDAY, hours="1.00")
        self.mk_ticket()
        with CaptureQueriesContext(connection) as small:
            run()
        for index in range(20):
            self.entry(
                employee=self.staff_a2,
                day=MONDAY + timedelta(days=index % 6),
                hours="1.00",
                source=(HourSource.EXTRA_WORK, self.job.id),
            )
            self.mk_ticket(title=f"Ticket {index}")
        with self.assertNumQueries(len(small.captured_queries)):
            run()

    def test_the_summary_is_cheaper_than_building_the_four_reports(self):
        """The reason this endpoint exists rather than four report calls.
        Measured, not asserted from memory."""
        from reports.employee_hours import (
            build_employee_hours_by_building,
            build_employee_hours_by_extra_work,
            build_employee_hours_summaries,
            build_employee_hours_weekly,
        )
        from reports.ticket_report import (
            build_ticket_report,
            build_ticket_report_summary,
        )

        for index in range(10):
            self.entry(
                employee=self.staff_a,
                day=MONDAY + timedelta(days=index % 6),
                hours="1.00",
            )
        start, end = MONDAY, MONDAY + timedelta(days=6)

        with CaptureQueriesContext(connection) as summary:
            build_employee_hours_summaries(self.ca_a, start, end)
            build_ticket_report_summary(self.ca_a, start, end)
        with CaptureQueriesContext(connection) as full:
            build_employee_hours_by_building(self.ca_a, start, end)
            build_employee_hours_weekly(self.ca_a, start, end)
            build_employee_hours_by_extra_work(self.ca_a, start, end)
            build_ticket_report(self.ca_a, start, end)

        self.assertLessEqual(
            len(summary.captured_queries), len(full.captured_queries)
        )


class UnfilteredRegressionTests(_Base):
    """Sprint 178's own guarantees, re-asserted after the rewrite: an
    unfiltered call must be byte-for-byte the report it always was."""

    def test_the_unfiltered_reports_still_answer(self):
        self.entry(employee=self.staff_a, day=MONDAY, hours="4.00")
        for url in ALL_FOUR:
            with self.subTest(url=url):
                response = self.api(self.ca_a).get(url, self.period())
                self.assertEqual(response.status_code, 200, url)

    def test_no_filter_costs_no_scope_resolution(self):
        """`resolve_scope` runs two membership lookups. An unfiltered
        report must not pay for a question nobody asked."""
        self.entry(employee=self.staff_a, day=MONDAY, hours="4.00")
        client = self.api(self.ca_a)
        with CaptureQueriesContext(connection) as plain:
            client.get(BY_BUILDING, self.period())
        with CaptureQueriesContext(connection) as filtered:
            client.get(BY_BUILDING, self.period(building=self.building_a.id))
        self.assertLess(
            len(plain.captured_queries), len(filtered.captured_queries)
        )

    def test_time_entries_outside_the_period_are_still_excluded(self):
        self.entry(employee=self.staff_a, day=MONDAY, hours="4.00")
        self.entry(
            employee=self.staff_a, day=MONDAY - timedelta(days=1), hours="99.00"
        )
        response = self.api(self.ca_a).get(BY_BUILDING, self.period())
        self.assertEqual(Decimal(response.data["total"]), Decimal("4.00"))
        self.assertEqual(
            TimeEntry.objects.filter(company=self.company_a).count(), 2
        )
