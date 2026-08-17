"""
Sprint 177 §7 — offering the job, so the source stops being empty.

Sprint 173 put `(source_type, source_id)` on `TimeEntry`. Sprint 174
added the list filter and taught the week-grid endpoint to ACCEPT a
source per cell. **Nothing ever supplied one.** Verified by scanning
every writer in the backend: the pair is read, filtered, serialised and
accepted as an explicit input — and never derived from the job the hours
were logged against. So every row read as untagged, and "employee hours
by extra work" was a report over a column nobody fills.

`GET /api/reports/hour-sources/` is the missing half: the list direction
of `resolve_sources`, in the same module for the same reason —
`timesheets` imports nothing from `tickets` or `extra_work`, so a
cross-module read lives in `reports/`.

What these pin:

  * the picker OFFERS open work, both kinds, with a usable title;
  * finished / cancelled / rejected work is not offered — nobody logs
    hours against a job that is over;
  * **a job the actor cannot see is absent, exactly as if it did not
    exist.** This endpoint ENUMERATES, so that equivalence matters more
    here than on the resolve path: a distinguishable answer would let
    one tenant count another tenant's work (H-1);
  * STAFF can reach it. They log their own hours and must be able to say
    which job they worked on — which is why the gate is
    `IsTimesheetUser` and not one of the reports classes that
    deliberately exclude STAFF;
  * a customer-side role gets nothing at all.
"""
from __future__ import annotations

from datetime import date

from rest_framework.test import APIClient

from buildings.models import Building
from customers.models import Customer, CustomerBuildingMembership
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from tickets.models import Ticket, TicketType
from timesheets.tests.fixtures import TimesheetsFixture

URL = "/api/reports/hour-sources/"


class HourSourcePickerTests(TimesheetsFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # One customer per company, linked to that company's building, so
        # extra work can be created on both sides of the tenant line.
        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Cust A"
        )
        cls.customer_b = Customer.objects.create(
            company=cls.company_b, name="Cust B"
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a, building=cls.building_a
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_b, building=cls.building_b
        )

        cls.open_ew = ExtraWorkRequest.objects.create(
            company=cls.company_a,
            customer=cls.customer_a,
            building=cls.building_a,
            title="Repaint the stairwell",
            description="x",
            created_by=cls.ca_a,
        )
        cls.done_ew = ExtraWorkRequest.objects.create(
            company=cls.company_a,
            customer=cls.customer_a,
            building=cls.building_a,
            title="Finished last month",
            description="x",
            created_by=cls.ca_a,
            status=ExtraWorkStatus.COMPLETED,
        )
        # The other tenant's work — the thing that must never be offered.
        cls.foreign_ew = ExtraWorkRequest.objects.create(
            company=cls.company_b,
            customer=cls.customer_b,
            building=cls.building_b,
            title="Company B private job",
            description="x",
            created_by=cls.ca_b,
        )

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def titles(self, response):
        return [row["title"] for row in response.data["results"]]

    def pairs(self, response):
        return {
            (row["source_type"], row["source_id"])
            for row in response.data["results"]
        }

    # ------------------------------------------------------------------
    # What it offers
    # ------------------------------------------------------------------
    def test_open_extra_work_is_offered_with_a_readable_title(self):
        response = self.api(self.ca_a).get(URL)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("Repaint the stairwell", self.titles(response))

    def test_every_row_carries_the_pair_the_hours_will_store(self):
        """The picker's whole job: hand back something that can travel
        onto a `TimeEntry` without the operator retyping it."""
        response = self.api(self.ca_a).get(URL)
        row = next(
            r
            for r in response.data["results"]
            if r["title"] == "Repaint the stairwell"
        )
        for key in ("source_type", "source_id", "title", "building"):
            with self.subTest(key=key):
                self.assertIn(key, row)
        self.assertEqual(row["source_type"], "EXTRA_WORK")
        self.assertEqual(row["source_id"], self.open_ew.id)
        self.assertEqual(row["building"], self.building_a.id)

    def test_finished_work_is_not_offered(self):
        response = self.api(self.ca_a).get(URL)
        self.assertNotIn("Finished last month", self.titles(response))

    def test_the_search_narrows_it(self):
        response = self.api(self.ca_a).get(URL, {"q": "stairwell"})
        self.assertIn("Repaint the stairwell", self.titles(response))
        response = self.api(self.ca_a).get(URL, {"q": "zzz-no-such-job"})
        self.assertEqual(self.titles(response), [])

    # ------------------------------------------------------------------
    # H-1 — the reason the scoping is not optional
    # ------------------------------------------------------------------
    def test_another_tenants_work_is_never_offered(self):
        response = self.api(self.ca_a).get(URL)
        self.assertNotIn("Company B private job", self.titles(response))
        self.assertNotIn(
            ("EXTRA_WORK", self.foreign_ew.id), self.pairs(response)
        )

    def test_searching_for_it_by_name_still_finds_nothing(self):
        """An enumerating endpoint must not become an oracle: asking for
        the exact title of another tenant's job answers the same as
        asking for a job nobody has."""
        named = self.api(self.ca_a).get(URL, {"q": "Company B private job"})
        absent = self.api(self.ca_a).get(URL, {"q": "zzz-no-such-job"})
        self.assertEqual(named.status_code, absent.status_code)
        self.assertEqual(named.data["results"], absent.data["results"])

    def test_the_other_tenant_sees_their_own_and_only_their_own(self):
        """The isolation assertion is worthless if B is empty."""
        response = self.api(self.ca_b).get(URL)
        self.assertIn("Company B private job", self.titles(response))
        self.assertNotIn("Repaint the stairwell", self.titles(response))

    # ------------------------------------------------------------------
    # Who may reach it
    # ------------------------------------------------------------------
    def test_staff_may_reach_it(self):
        """The point of the gate choice. STAFF log their own hours, so a
        reports-class gate would lock the picker away from most of the
        people who need it."""
        response = self.api(self.staff_a).get(URL)
        self.assertEqual(response.status_code, 200, response.data)

    def test_a_customer_gets_nothing(self):
        response = self.api(self.customer_user).get(URL)
        self.assertEqual(response.status_code, 403, response.data)

    def test_anonymous_is_refused(self):
        self.assertIn(APIClient().get(URL).status_code, (401, 403))


class TicketSourceTests(TimesheetsFixture):
    """Tickets are the other half of the picker."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Cust A"
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a, building=cls.building_a
        )
        cls.ticket = Ticket.objects.create(
            company=cls.company_a,
            building=cls.building_a,
            customer=cls.customer_a,
            type=TicketType.REPORT,
            title="Leaking tap",
            description="x",
            created_by=cls.ca_a,
        )

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_an_open_ticket_is_offered_with_its_number(self):
        response = self.api(self.ca_a).get(URL)
        self.assertEqual(response.status_code, 200, response.data)
        rows = [
            r for r in response.data["results"] if r["source_type"] == "TICKET"
        ]
        self.assertTrue(rows, "expected at least one ticket source")
        self.assertIn("Leaking tap", rows[0]["title"])
        self.assertEqual(rows[0]["source_id"], self.ticket.id)


class QueryCountTests(TimesheetsFixture):
    """One query per type, never one per row — the same discipline the
    resolve direction keeps."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Cust A"
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a, building=cls.building_a
        )
        for index in range(12):
            ExtraWorkRequest.objects.create(
                company=cls.company_a,
                customer=cls.customer_a,
                building=cls.building_a,
                title=f"Job {index}",
                description="x",
                created_by=cls.ca_a,
            )

    def test_the_row_count_does_not_change_the_query_count(self):
        from reports.hour_sources import available_sources

        with self.assertNumQueries(2):
            rows = available_sources(self.ca_a)
        self.assertGreaterEqual(len(rows), 12)


class DateSanityTests(TimesheetsFixture):
    """A guard on the fixture itself, so a future change to
    `TimesheetsFixture` cannot quietly empty these tests."""

    def test_the_fixture_has_two_populated_companies(self):
        self.assertNotEqual(self.company_a.id, self.company_b.id)
        self.assertTrue(Building.objects.filter(company=self.company_b).exists())
        self.assertIsInstance(date(2026, 3, 2), date)


class TypeOnlySourceTests(TimesheetsFixture):
    """Sprint 178 §4b — CONTRACT and OTHER, offered at last.

    `source_label` has always been able to render a source that is a TYPE
    with no id — "CONTRACT and OTHER ... render from their type alone" is
    in this module's own docstring — and `HourSource.CONTRACT` has always
    been in the enum. But nothing could ever SET one: the picker offered
    tickets and extra work, and `CONTRACT` appeared in exactly one place
    in the whole backend, its own declaration.

    That gap is what these close. Note what does NOT change: `OTHER`
    stays the default for an untouched row, so nothing existing is
    backfilled with a guess. "OTHER because nobody said" and "OTHER
    because an operator chose it" store the same value, and that is
    fine — the difference matters to nobody downstream.
    """

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_contract_and_other_are_offered(self):
        response = self.api(self.ca_a).get(URL)
        self.assertEqual(response.status_code, 200, response.data)
        types = [
            row["source_type"]
            for row in response.data["results"]
            if row["source_id"] is None
        ]
        self.assertIn("CONTRACT", types)
        self.assertIn("OTHER", types)

    def test_a_type_only_source_carries_a_null_id(self):
        """The shape the display layer already expected."""
        response = self.api(self.ca_a).get(URL)
        row = next(
            r for r in response.data["results"] if r["source_type"] == "CONTRACT"
        )
        self.assertIsNone(row["source_id"])
        self.assertTrue(row["title"])

    def test_they_come_first(self):
        """Ahead of the job list: they are the two an operator reaches
        for when the hours belong to no particular job."""
        response = self.api(self.ca_a).get(URL)
        first_two = [r["source_type"] for r in response.data["results"][:2]]
        self.assertEqual(first_two, ["CONTRACT", "OTHER"])

    def test_the_search_narrows_them_too(self):
        response = self.api(self.ca_a).get(URL, {"q": "zzz-no-such-thing"})
        self.assertEqual(response.data["results"], [])
