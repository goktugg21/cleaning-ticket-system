"""
W3-H — the hours booked to one extra work, and what they cost.

Six things are pinned, and each is a rule somebody could undo without
any other test noticing:

1. **The grid is worker x day x hour type** and its totals cover every
   entry, whatever the grid window shows.
2. **Planned and actual sit side by side.** `budget_hours` (W2-D) is
   READ into the roll-up and is NEVER multiplied by anything. The
   reference system cannot make this comparison at all — over there
   `hours_planed` is written by six paths and read by nothing that
   decides.
3. **BUDGET HOURS NEVER TOUCHES MONEY.** Doubling the budget must not
   move a single cost figure. This is the sprint's hard rule and it is
   the test that would catch it being wired up.
4. **`timesheets` computes no money.** Cost comes from
   `reports.labour_cost` and from nowhere else, and with no rate
   configured every cost figure is NULL rather than 0.00 — "we do not
   know" is not "it was free".
5. **The privacy pair.** SA/CA see the company's rows and the cost; a
   BUILDING_MANAGER sees only their OWN rows and NO cost, and the
   response says which of the two it is (`visibility`).
6. **Nobody else gets in.** STAFF and every customer-side role are
   refused, and another tenant's job answers 404 — the same answer a
   fictional id gives (H-1).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.test import override_settings
from rest_framework import status

from extra_work.models import ExtraWorkCategory, ExtraWorkRequest, ExtraWorkStatus
from timesheets.models import HourSource
from timesheets.tests.fixtures import TimesheetsFixture


def url(extra_work_id: int) -> str:
    return f"/api/reports/extra-work/{extra_work_id}/hours/"


MONDAY = date(2026, 3, 2)
TUESDAY = date(2026, 3, 3)


class ExtraWorkHoursBase(TimesheetsFixture):
    """The timesheets two-company fixture, plus one extra work per side.

    Company B is populated on purpose: an isolation test that passes
    because the other tenant is empty proves nothing.
    """

    def setUp(self):
        super().setUp()
        self.ew_a = self.make_ew(
            self.company_a, self.building_a, self.customer_a
        )
        self.ew_b = self.make_ew(
            self.company_b, self.building_b, self.customer_b_org
        )

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from customers.models import Customer

        cls.customer_b_org = Customer.objects.create(
            company=cls.company_b, name="Customer B"
        )

    def make_ew(self, company, building, customer, **kwargs):
        defaults = dict(
            company=company,
            building=building,
            customer=customer,
            created_by=self.sa,
            title="Strip and seal the corridor",
            description="x",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.IN_PROGRESS,
        )
        defaults.update(kwargs)
        return ExtraWorkRequest.objects.create(**defaults)

    def hours_on(self, employee, extra_work, day, hours, hour_type=None, **extra):
        """One entry booked TO an extra work — the pair Sprint 173 added."""
        return self.make_entry(
            employee,
            day,
            hour_type or self.normal_a,
            hours=hours,
            company=extra.pop("company", None) or extra_work.company,
            created_by=self.ca_a,
            source_type=HourSource.EXTRA_WORK,
            source_id=extra_work.id,
            **extra,
        )


class GridTests(ExtraWorkHoursBase):
    def test_the_grid_is_worker_by_day_by_hour_type(self):
        self.hours_on(self.staff_a, self.ew_a, MONDAY, "4.00")
        self.hours_on(self.staff_a, self.ew_a, TUESDAY, "2.50")
        self.hours_on(
            self.staff_a, self.ew_a, MONDAY, "1.50", hour_type=self.overtime_a
        )
        self.hours_on(self.staff_a2, self.ew_a, MONDAY, "8.00")

        response = self.api(self.ca_a).get(url(self.ew_a.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        rows = response.data["rows"]
        # Three rows: two hour types for staff_a, one for staff_a2. The
        # hour type is part of the row identity, not a decoration.
        self.assertEqual(len(rows), 3)
        by_key = {
            (row["employee_id"], row["hour_type_name"]): row for row in rows
        }
        normal = by_key[(self.staff_a.id, "Normale uren")]
        self.assertEqual(normal["days"][MONDAY.isoformat()], "4.00")
        self.assertEqual(normal["days"][TUESDAY.isoformat()], "2.50")
        self.assertEqual(normal["hours"], "6.50")
        overtime = by_key[(self.staff_a.id, "Overwerk")]
        self.assertEqual(overtime["hours"], "1.50")
        # 1.50 hours at a 1.50 multiplier. The WEIGHT comes from the
        # snapshot on the row, never from the live hour type.
        self.assertEqual(overtime["weighted_hours"], "2.25")
        self.assertEqual(response.data["days"], [MONDAY.isoformat(), TUESDAY.isoformat()])

    def test_only_hours_booked_to_THIS_job_are_counted(self):
        other = self.make_ew(self.company_a, self.building_a, self.customer_a)
        self.hours_on(self.staff_a, self.ew_a, MONDAY, "3.00")
        self.hours_on(self.staff_a, other, MONDAY, "5.00")
        # An untagged entry, and one tagged to a TICKET with the same id
        # as our extra work — the pair is (type, id) and reading the id
        # alone would sweep this in.
        self.make_entry(
            self.staff_a,
            MONDAY,
            self.normal_a,
            hours="7.00",
            company=self.company_a,
            created_by=self.ca_a,
        )
        self.make_entry(
            self.staff_a,
            MONDAY,
            self.normal_a,
            hours="9.00",
            company=self.company_a,
            created_by=self.ca_a,
            source_type=HourSource.TICKET,
            source_id=self.ew_a.id,
        )

        response = self.api(self.ca_a).get(url(self.ew_a.id))

        self.assertEqual(response.data["totals"]["hours"], "3.00")

    def test_an_empty_job_is_an_empty_answer_not_a_broken_screen(self):
        response = self.api(self.ca_a).get(url(self.ew_a.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["rows"], [])
        self.assertEqual(response.data["days"], [])
        self.assertEqual(response.data["totals"]["hours"], "0.00")
        self.assertEqual(response.data["rollup"]["entered_hours"], "0.00")


class RollupTests(ExtraWorkHoursBase):
    def test_PLANNED_AND_ACTUAL_SIDE_BY_SIDE(self):
        """The thing the reference system cannot do."""
        self.ew_a.budget_hours = Decimal("8.00")
        self.ew_a.save(update_fields=["budget_hours"])
        self.hours_on(self.staff_a, self.ew_a, MONDAY, "5.00")
        self.hours_on(self.staff_a2, self.ew_a, MONDAY, "8.50")

        rollup = self.api(self.ca_a).get(url(self.ew_a.id)).data["rollup"]

        self.assertEqual(rollup["budget_hours"], "8.00")
        self.assertEqual(rollup["entered_hours"], "13.50")
        # Positive means over. Hours, never money.
        self.assertEqual(rollup["variance_hours"], "5.50")

    def test_an_unbudgeted_job_reports_no_budget_and_no_variance(self):
        """NULL is "nobody budgeted this", which is not 0.00."""
        self.hours_on(self.staff_a, self.ew_a, MONDAY, "5.00")

        rollup = self.api(self.ca_a).get(url(self.ew_a.id)).data["rollup"]

        self.assertIsNone(rollup["budget_hours"])
        self.assertIsNone(rollup["variance_hours"])
        self.assertEqual(rollup["entered_hours"], "5.00")

    def test_a_zero_budget_is_a_budget(self):
        self.ew_a.budget_hours = Decimal("0.00")
        self.ew_a.save(update_fields=["budget_hours"])
        self.hours_on(self.staff_a, self.ew_a, MONDAY, "2.00")

        rollup = self.api(self.ca_a).get(url(self.ew_a.id)).data["rollup"]

        self.assertEqual(rollup["budget_hours"], "0.00")
        self.assertEqual(rollup["variance_hours"], "2.00")


class LabourCostTests(ExtraWorkHoursBase):
    def test_with_NO_rate_configured_every_cost_is_NULL_never_zero(self):
        """"We do not know what this cost" is not "it was free"."""
        self.hours_on(self.staff_a, self.ew_a, MONDAY, "5.00")

        cost = self.api(self.ca_a).get(url(self.ew_a.id)).data["cost"]

        self.assertFalse(cost["rate_configured"])
        self.assertIsNone(cost["hourly_rate"])
        self.assertIsNone(cost["hours_cost"])
        self.assertIsNone(cost["total_cost"])

    @override_settings(LABOUR_COST_HOURLY_RATE_EUR="25.00")
    def test_a_configured_rate_costs_WEIGHTED_hours(self):
        self.hours_on(self.staff_a, self.ew_a, MONDAY, "4.00")
        self.hours_on(
            self.staff_a, self.ew_a, MONDAY, "2.00", hour_type=self.overtime_a
        )

        body = self.api(self.ca_a).get(url(self.ew_a.id)).data

        # 4.00 x 1.00 + 2.00 x 1.50 = 7.00 weighted hours.
        self.assertEqual(body["totals"]["hours"], "6.00")
        self.assertEqual(body["totals"]["weighted_hours"], "7.00")
        self.assertEqual(body["cost"]["hourly_rate"], "25.00")
        self.assertEqual(body["cost"]["hours_cost"], "175.00")
        self.assertEqual(body["cost"]["total_cost"], "175.00")
        self.assertEqual(body["cost"]["rate_source"], "deployment_setting")

    @override_settings(LABOUR_COST_HOURLY_RATE_EUR="25.00")
    def test_travel_costs_are_reported_and_added_but_never_folded_in(self):
        self.hours_on(
            self.staff_a, self.ew_a, MONDAY, "4.00", travel_costs=Decimal("12.50")
        )

        cost = self.api(self.ca_a).get(url(self.ew_a.id)).data["cost"]

        self.assertEqual(cost["hours_cost"], "100.00")
        self.assertEqual(cost["travel_costs"], "12.50")
        self.assertEqual(cost["total_cost"], "112.50")

    def test_travel_costs_show_even_with_no_rate_but_the_total_does_not(self):
        """Travel is real money somebody claimed; it needs no rate. A
        "total" that silently meant travel-only would be read as the
        job's cost."""
        self.hours_on(
            self.staff_a, self.ew_a, MONDAY, "4.00", travel_costs=Decimal("12.50")
        )

        cost = self.api(self.ca_a).get(url(self.ew_a.id)).data["cost"]

        self.assertEqual(cost["travel_costs"], "12.50")
        self.assertIsNone(cost["total_cost"])

    @override_settings(LABOUR_COST_HOURLY_RATE_EUR="0")
    def test_a_rate_of_zero_is_read_as_NOT_CONFIGURED(self):
        """Zero is a legal PRICE (Sprint 188). It is not a legal WAGE —
        a deployment that typed 0 typed a placeholder."""
        self.hours_on(self.staff_a, self.ew_a, MONDAY, "4.00")

        cost = self.api(self.ca_a).get(url(self.ew_a.id)).data["cost"]

        self.assertFalse(cost["rate_configured"])
        self.assertIsNone(cost["total_cost"])

    @override_settings(LABOUR_COST_HOURLY_RATE_EUR="25.00")
    def test_BUDGET_HOURS_NEVER_TOUCHES_MONEY(self):
        """The sprint's hard rule, as an experiment: change ONLY the
        budget and every cost figure must be byte-identical."""
        self.hours_on(self.staff_a, self.ew_a, MONDAY, "4.00")
        self.ew_a.budget_hours = Decimal("4.00")
        self.ew_a.save(update_fields=["budget_hours"])
        before = self.api(self.ca_a).get(url(self.ew_a.id)).data["cost"]

        self.ew_a.budget_hours = Decimal("400.00")
        self.ew_a.save(update_fields=["budget_hours"])
        after = self.api(self.ca_a).get(url(self.ew_a.id)).data["cost"]

        self.assertEqual(before, after)
        self.assertEqual(after["hours_cost"], "100.00")

    def test_the_timesheets_module_computes_no_money(self):
        """The rule this sprint exists to keep, asserted against the
        source rather than trusted: no rate, wage or cost multiplication
        anywhere in `timesheets/`."""
        import pathlib

        import timesheets

        offenders = []
        root = pathlib.Path(timesheets.__file__).parent
        for path in sorted(root.rglob("*.py")):
            if "tests" in path.parts or "migrations" in path.parts:
                continue
            text = path.read_text(encoding="utf-8").lower()
            for needle in ("hourly_rate", "labour_cost", "labor_cost"):
                if needle in text:
                    offenders.append(f"{path.name}: {needle}")
        self.assertEqual(offenders, [])


class VisibilityTests(ExtraWorkHoursBase):
    @override_settings(LABOUR_COST_HOURLY_RATE_EUR="25.00")
    def test_a_company_admin_sees_the_companys_rows_and_the_cost(self):
        self.hours_on(self.staff_a, self.ew_a, MONDAY, "4.00")
        self.hours_on(self.bm_a, self.ew_a, MONDAY, "1.00")

        body = self.api(self.ca_a).get(url(self.ew_a.id)).data

        self.assertEqual(body["visibility"], "company")
        self.assertEqual(body["totals"]["hours"], "5.00")
        self.assertIsNotNone(body["cost"]["total_cost"])

    @override_settings(LABOUR_COST_HOURLY_RATE_EUR="25.00")
    def test_a_building_manager_sees_only_their_OWN_hours_and_NO_cost(self):
        """Sprint 182 §1's privacy floor, on a new consumer of TimeEntry.
        `filter_time_entries_for` alone would leak every colleague's
        hours company-wide without breaching the tenant."""
        self.hours_on(self.staff_a, self.ew_a, MONDAY, "4.00")
        self.hours_on(self.bm_a, self.ew_a, MONDAY, "1.00")

        body = self.api(self.bm_a).get(url(self.ew_a.id)).data

        self.assertEqual(body["visibility"], "self")
        self.assertEqual(body["totals"]["hours"], "1.00")
        self.assertEqual(
            [row["employee_id"] for row in body["rows"]], [self.bm_a.id]
        )
        # Labour cost is provider-management information and the rows it
        # would cover are not the rows this actor can see.
        self.assertIsNone(body["cost"])

    def test_the_budget_still_shows_for_a_building_manager(self):
        """They may not see colleagues' hours; the JOB's budget is not a
        personnel fact and the detail page already shows it to them."""
        self.ew_a.budget_hours = Decimal("8.00")
        self.ew_a.save(update_fields=["budget_hours"])

        body = self.api(self.bm_a).get(url(self.ew_a.id)).data

        self.assertEqual(body["rollup"]["budget_hours"], "8.00")


class AccessTests(ExtraWorkHoursBase):
    def test_a_customer_user_is_refused(self):
        response = self.api(self.customer_user).get(url(self.ew_a.id))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_are_refused(self):
        """A worker reads their own hours in the timesheets module. The
        parent Extra Work is closed to STAFF by the P0 staff-privacy
        decision (A4), and this endpoint reports on one."""
        response = self.api(self.staff_a).get(url(self.ew_a.id))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_another_tenants_job_is_a_404_and_so_is_a_fiction(self):
        """H-1: out of scope must be indistinguishable from nonexistent."""
        foreign = self.api(self.ca_a).get(url(self.ew_b.id))
        fictional = self.api(self.ca_a).get(url(98765432))

        self.assertEqual(foreign.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(fictional.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(foreign.data, fictional.data)

    def test_hours_of_another_tenant_never_reach_this_answer(self):
        """The cross-tenant assertion, with company B genuinely populated."""
        self.hours_on(
            self.staff_b,
            self.ew_b,
            MONDAY,
            "6.00",
            hour_type=self.normal_b,
            company=self.company_b,
        )
        self.hours_on(self.staff_a, self.ew_a, MONDAY, "1.00")

        body = self.api(self.ca_a).get(url(self.ew_a.id)).data

        self.assertEqual(body["totals"]["hours"], "1.00")
