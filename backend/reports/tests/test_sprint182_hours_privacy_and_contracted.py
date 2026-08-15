"""
Sprint 182 §1 + §2 — the hours privacy floor, and the contracted column.

Two findings from the domain audit, each pinned defect by defect.

**§1 — a BUILDING_MANAGER could read every colleague's hours.**
`timesheets/views_entries.py` applies the pair
`restrict_entries_to_self(user, filter_time_entries_for(user, qs))`.
`reports.worker_hours` and `reports.employee_hours` applied only the
second half, so the company scope held (no tenant breach) while the
privacy rule inside the company did not. A third caller,
`reports.hours_comparison`, had the same hole in its per-employee
breakdown. All three are pinned here from BOTH sides: the BM sees their
own row, and does NOT see a colleague's.

**§2 — the contracted column was wrong four ways.** Each defect gets its
own test against its own fixture. A single end-to-end test over one
elaborate fixture would pass again the moment any ONE of the four came
back, because the other three would still be masking it — which is
exactly how four defects accumulated in twelve lines.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from rest_framework import status

from timesheets.models import ContractHours, ContractHoursStatus
from timesheets.tests.fixtures import TimesheetsFixture


URL = "/api/reports/worker-hours/"
COMPARISON_URL = "/api/reports/hours-comparison/"

# 2026-03-02 is the Monday of ISO week 10; 2026-03-09 opens week 11.
W10_MONDAY = date(2026, 3, 2)
W10_TUESDAY = date(2026, 3, 3)
W11_MONDAY = date(2026, 3, 9)
W12_MONDAY = date(2026, 3, 16)


class _HoursBase(TimesheetsFixture):
    def entry(self, employee, day, hours, building=None, hour_type=None):
        return self.make_entry(
            employee,
            day,
            hour_type or self.normal_a,
            hours=hours,
            building=building,
            company=self.company_a,
            created_by=self.ca_a,
        )

    def agreement(
        self,
        employee,
        *,
        building=None,
        hour_type=None,
        valid_from=W10_MONDAY,
        valid_to=None,
        monday="0.00",
        status_value=ContractHoursStatus.APPROVED,
        work_type=None,
    ):
        return ContractHours.objects.create(
            company=self.company_a,
            employee=employee,
            building=building,
            hour_type=hour_type or self.normal_a,
            work_type=work_type,
            valid_from=valid_from,
            valid_to=valid_to,
            monday=Decimal(monday),
            status=status_value,
            created_by=self.ca_a,
        )

    def report(self, user, **params):
        query = {"year": 2026, "week": 10, "weeks": 1, **params}
        return self.api(user).get(URL, query)

    @staticmethod
    def employee_ids(response):
        return {row["employee_id"] for row in response.data["rows"]}

    @staticmethod
    def contracted_for(response, *, iso_week, employee_id, hour_type_id=None):
        for row in response.data["rows"]:
            if row["iso_week"] != iso_week or row["employee_id"] != employee_id:
                continue
            if hour_type_id is not None and row["hour_type_id"] != hour_type_id:
                continue
            return row["contracted_hours"]
        return "NO SUCH ROW"


# ---------------------------------------------------------------------------
# §1 — the privacy floor
# ---------------------------------------------------------------------------


class BuildingManagerSeesOnlyTheirOwnHoursTests(_HoursBase):
    """THE DECISION: a BUILDING_MANAGER sees their OWN hours, not their
    buildings'.

    Chosen because it is the decision this codebase had already made and
    written down — `timesheets.scope.is_timesheet_manager` says "a BM
    manages BUILDINGS, not payroll-adjacent personnel records, so they
    get the same own-entries-only surface STAFF does". The reports simply
    were not applying it. The alternative, "their buildings' hours",
    would have invented a third scoping tier that exists nowhere in the
    module, and these rows carry personnel numbers, travel-cost claims
    and wage-adjacent multipliers — none of which are building-management
    facts.
    """

    def setUp(self):
        super().setUp()
        # The BM's own hours, and a colleague's, in the same company and
        # the same building the BM manages.
        self.entry(self.bm_a, W10_MONDAY, "4.00", building=self.building_a)
        self.entry(self.staff_a, W10_MONDAY, "7.00", building=self.building_a)

    def test_worker_report_shows_the_bm_their_own_row(self):
        response = self.report(self.bm_a)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(self.bm_a.id, self.employee_ids(response))

    def test_worker_report_hides_a_colleague_from_the_bm(self):
        """The finding, stated as an assertion. Same company, same
        building, still not theirs to read."""
        response = self.report(self.bm_a)
        self.assertNotIn(self.staff_a.id, self.employee_ids(response))

    def test_a_company_admin_still_sees_the_whole_company(self):
        """The other side — the fix must not turn the report off for the
        people it is for."""
        response = self.report(self.ca_a)
        ids = self.employee_ids(response)
        self.assertIn(self.bm_a.id, ids)
        self.assertIn(self.staff_a.id, ids)

    def test_a_staff_member_sees_only_their_own_too(self):
        self.entry(self.staff_a2, W10_MONDAY, "5.00", building=self.building_a)
        response = self.report(self.staff_a)
        # STAFF is refused the report outright by the permission class;
        # if that ever widens, the row filter is the second line.
        if response.status_code == status.HTTP_200_OK:
            self.assertEqual(self.employee_ids(response), {self.staff_a.id})
        else:
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_contracted_hours_of_a_colleague_are_not_readable_either(self):
        """A `ContractHours` row says what a named person is contracted
        for. Same class of fact, same floor."""
        self.agreement(self.staff_a, building=self.building_a, monday="9.00")
        response = self.report(self.bm_a)
        for row in response.data["rows"]:
            self.assertNotEqual(row["employee_id"], self.staff_a.id)


class EmployeeHoursReportPrivacyTests(_HoursBase):
    """The same hole, in the three Sprint 178 reports and the summary
    cards that share `employee_hours._base`."""

    URLS = (
        "/api/reports/employee-hours-by-building/",
        "/api/reports/employee-hours-weekly/",
    )

    def setUp(self):
        super().setUp()
        self.entry(self.bm_a, W10_MONDAY, "4.00", building=self.building_a)
        self.entry(self.staff_a, W10_MONDAY, "7.00", building=self.building_a)

    def _names(self, payload):
        """Every employee name anywhere in a report payload, whatever
        its shape — these three reports nest differently and the claim
        is about all of them."""
        found = set()

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in ("employee_name", "name") and isinstance(value, str):
                        found.add(value)
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)
        return found

    def test_no_report_names_a_colleague_to_a_building_manager(self):
        for url in self.URLS:
            with self.subTest(url=url):
                response = self.api(self.bm_a).get(
                    url, {"from": "2026-03-01", "to": "2026-03-31"}
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertNotIn(
                    self.staff_a.full_name, self._names(response.data)
                )

    def test_a_company_admin_still_sees_the_colleague(self):
        for url in self.URLS:
            with self.subTest(url=url):
                response = self.api(self.ca_a).get(
                    url, {"from": "2026-03-01", "to": "2026-03-31"}
                )
                self.assertIn(self.staff_a.full_name, self._names(response.data))


class HoursComparisonPrivacyTests(_HoursBase):
    """The THIRD caller — not named in the audit finding, found by
    enumerating the callers again while fixing the other two."""

    def setUp(self):
        super().setUp()
        self.entry(self.bm_a, W10_MONDAY, "4.00", building=self.building_a)
        self.entry(self.staff_a, W10_MONDAY, "7.00", building=self.building_a)

    def _rows(self, user):
        response = self.api(user).get(
            COMPARISON_URL, {"year": 2026, "month": 3}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data["rows"]

    def test_per_employee_breakdown_hides_a_colleague_from_a_bm(self):
        for row in self._rows(self.bm_a):
            names = {e["employee_name"] for e in row.get("employees", [])}
            self.assertNotIn(self.staff_a.full_name, names)

    def test_the_building_total_is_not_restricted(self):
        """The line this sprint draws: individual rows are personnel
        data, a building's TOTAL worked hours is a building-management
        fact and a BM manages buildings. 4 + 7 = 11 either way."""
        bm_rows = {r["building"]: r["worked_hours"] for r in self._rows(self.bm_a)}
        ca_rows = {r["building"]: r["worked_hours"] for r in self._rows(self.ca_a)}
        self.assertEqual(bm_rows, ca_rows)
        self.assertEqual(bm_rows[self.building_a.id], Decimal("11.00"))


# ---------------------------------------------------------------------------
# §2 — the contracted column, one test per defect
# ---------------------------------------------------------------------------


class ContractedColumnDefect1SumsOverlappingAgreementsTests(_HoursBase):
    def test_a_superseded_agreement_is_not_added_to_the_current_one(self):
        """Defect 1. Two successive agreements both overlap the report
        window — the old one ending, the new one starting. The column
        summed them: 10 + 15 = 25 contracted for a worker who is
        contracted for 15."""
        self.entry(self.staff_a, W10_MONDAY, "4.00", building=self.building_a)
        self.agreement(
            self.staff_a,
            building=self.building_a,
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 3, 4),
            monday="10.00",
        )
        self.agreement(
            self.staff_a,
            building=self.building_a,
            valid_from=date(2026, 3, 3),
            monday="15.00",
        )
        response = self.report(self.ca_a)
        self.assertEqual(
            self.contracted_for(
                response, iso_week=10, employee_id=self.staff_a.id
            ),
            "15.00",
        )


class ContractedColumnDefect2DraftCountsTests(_HoursBase):
    def test_a_draft_agreement_is_not_an_agreement(self):
        """Defect 2. `ContractHours.objects.all()` included DRAFT rows,
        contradicting the model's own status docstring: "Nothing
        downstream reads a DRAFT row as an agreement"."""
        self.entry(self.staff_a, W10_MONDAY, "4.00", building=self.building_a)
        self.agreement(
            self.staff_a,
            building=self.building_a,
            monday="12.00",
            status_value=ContractHoursStatus.DRAFT,
        )
        response = self.report(self.ca_a)
        self.assertIsNone(
            self.contracted_for(
                response, iso_week=10, employee_id=self.staff_a.id
            ),
            "a DRAFT must leave the column empty, not fill it",
        )

    def test_a_saved_agreement_does_count(self):
        """The inverse, so the fix is a filter and not a blanket
        exclusion: SAVED is submitted for review and IS an agreement. A
        company that never uses the approve step must not see an empty
        column forever."""
        self.entry(self.staff_a, W10_MONDAY, "4.00", building=self.building_a)
        self.agreement(
            self.staff_a,
            building=self.building_a,
            monday="12.00",
            status_value=ContractHoursStatus.SAVED,
        )
        response = self.report(self.ca_a)
        self.assertEqual(
            self.contracted_for(
                response, iso_week=10, employee_id=self.staff_a.id
            ),
            "12.00",
        )


class ContractedColumnDefect3IgnoresHourTypeTests(_HoursBase):
    def test_each_hour_type_row_shows_its_own_agreement(self):
        """Defect 3. The key was (employee, building) while the report
        row's grain is (week, employee, building, hour type). Every
        hour-type row therefore showed the same figure — the sum across
        all hour types — so the overtime row claimed the normal-hours
        contract as its own."""
        self.entry(
            self.staff_a, W10_MONDAY, "4.00",
            building=self.building_a, hour_type=self.normal_a,
        )
        self.entry(
            self.staff_a, W10_MONDAY, "2.00",
            building=self.building_a, hour_type=self.overtime_a,
        )
        self.agreement(
            self.staff_a, building=self.building_a,
            hour_type=self.normal_a, monday="20.00",
        )
        self.agreement(
            self.staff_a, building=self.building_a,
            hour_type=self.overtime_a, monday="5.00",
        )
        response = self.report(self.ca_a)
        self.assertEqual(
            self.contracted_for(
                response, iso_week=10, employee_id=self.staff_a.id,
                hour_type_id=self.normal_a.id,
            ),
            "20.00",
        )
        self.assertEqual(
            self.contracted_for(
                response, iso_week=10, employee_id=self.staff_a.id,
                hour_type_id=self.overtime_a.id,
            ),
            "5.00",
        )


class ContractedColumnDefect4NoWeekInTheKeyTests(_HoursBase):
    def test_an_agreement_does_not_leak_into_weeks_it_had_ended_before(self):
        """Defect 4 — the one I had to read from the code.

        The report is PER ISO WEEK and can span many, but the contracted
        map had no week in its key: `in_force_between` was asked once for
        the whole span and its answer written onto every week's rows. An
        agreement that ended in week 10 was still reported as contracted
        in weeks 11 and 12.
        """
        for day in (W10_MONDAY, W11_MONDAY, W12_MONDAY):
            self.entry(self.staff_a, day, "4.00", building=self.building_a)
        self.agreement(
            self.staff_a,
            building=self.building_a,
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 3, 8),  # the Sunday that ends week 10
            monday="11.00",
        )
        response = self.report(self.ca_a, weeks=3)
        self.assertEqual(
            self.contracted_for(
                response, iso_week=10, employee_id=self.staff_a.id
            ),
            "11.00",
        )
        for week in (11, 12):
            with self.subTest(week=week):
                self.assertIsNone(
                    self.contracted_for(
                        response, iso_week=week, employee_id=self.staff_a.id
                    ),
                    f"the agreement ended in week 10; week {week} must be empty",
                )

    def test_an_agreement_starting_mid_report_fills_only_its_own_weeks(self):
        """The same defect from the other end."""
        for day in (W10_MONDAY, W11_MONDAY):
            self.entry(self.staff_a, day, "4.00", building=self.building_a)
        self.agreement(
            self.staff_a,
            building=self.building_a,
            valid_from=W11_MONDAY,
            monday="7.00",
        )
        response = self.report(self.ca_a, weeks=2)
        self.assertIsNone(
            self.contracted_for(
                response, iso_week=10, employee_id=self.staff_a.id
            )
        )
        self.assertEqual(
            self.contracted_for(
                response, iso_week=11, employee_id=self.staff_a.id
            ),
            "7.00",
        )

    def test_an_agreement_starting_midweek_still_counts_for_that_week(self):
        """Sprint 168 §2's rule is preserved by the fix: the week test is
        an OVERLAP, not `in_force_on(monday)`. An agreement starting on
        the Tuesday is part of that week's picture."""
        self.entry(self.staff_a, W10_MONDAY, "4.00", building=self.building_a)
        self.agreement(
            self.staff_a,
            building=self.building_a,
            valid_from=W10_TUESDAY,
            monday="6.00",
        )
        response = self.report(self.ca_a)
        self.assertEqual(
            self.contracted_for(
                response, iso_week=10, employee_id=self.staff_a.id
            ),
            "6.00",
        )


class ContractedColumnCostTests(_HoursBase):
    def test_the_fix_did_not_buy_correctness_with_a_query_per_week(self):
        """Four defects fixed at CONSTANT cost.

        The claim that matters is not an absolute number — it is that the
        cost does not grow with the report. Two queries either way: one
        to resolve the actor's companies, one for the agreements. A
        per-week or per-row lookup here is the N+1 the report's existing
        `assertNumQueries` test exists to prevent, and correctness bought
        with a table that takes a minute to draw is not a fix.
        """
        for day in (W10_MONDAY, W11_MONDAY, W12_MONDAY):
            self.entry(self.staff_a, day, "4.00", building=self.building_a)
            self.entry(self.staff_a2, day, "3.00", building=self.building_a)
        for employee in (self.staff_a, self.staff_a2):
            self.agreement(employee, building=self.building_a, monday="8.00")

        from reports.worker_hours import _contracted_by_week

        with self.assertNumQueries(2):
            one_week, _ = _contracted_by_week(
                self.ca_a, W10_MONDAY, date(2026, 3, 8)
            )
        # Six times the span, the SAME number of queries.
        with self.assertNumQueries(2):
            six_weeks, _ = _contracted_by_week(
                self.ca_a, W10_MONDAY, date(2026, 4, 12)
            )
        self.assertEqual(len(one_week), 2)  # 1 week x 2 employees
        self.assertEqual(len(six_weeks), 12)  # 6 weeks x 2 employees
