"""W7 — planned hours beside worked hours, per person, for one job.

    GET /api/reports/extra-work/<id>/planned-vs-actual/

Seven rules are pinned here, and each is one somebody could undo without
any other test in this repo noticing:

1. **The three numbers agree.** Planned, worked, and worked-minus-planned,
   per person and for the job.
2. **No row is ever a zero it did not earn.** Somebody who worked without
   being planned reads "not planned" (null), never 0.00 — and a job with
   no plan at all returns a null planned total rather than zeros, because
   0.00 would state that we planned nobody for no hours, which is a
   decision rather than the absence of one.
3. **An actual of zero IS reported as zero.** A person on the plan who has
   booked nothing is exactly what a manager opens this panel to find.
4. **The privacy pair.** SA/CA read the crew; BUILDING_MANAGER and STAFF
   read their OWN line and nothing else, and the response says which of
   the two answers it is.
5. **STAFF get in through the ticket, not through the extra work.**
   `scope_extra_work_for` returns nothing for them by the P0
   staff-privacy decision, so a worker with no ticket into the job is
   refused and a worker with one sees only themselves.
6. **Nobody customer-side gets in at all**, and another tenant's job
   answers 404 — the same answer a fictional id gives (H-1).
7. **No money passes through.** Planned hours reach no price anywhere;
   the response carries no rate, cost or amount under any key.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from rest_framework import status

from extra_work.models import (
    ExtraWorkCategory,
    ExtraWorkPlannedHours,
    ExtraWorkRequest,
    ExtraWorkStatus,
)
from timesheets.models import HourSource
from timesheets.tests.fixtures import TimesheetsFixture

from tickets.models import Ticket


def url(extra_work_id: int) -> str:
    return f"/api/reports/extra-work/{extra_work_id}/planned-vs-actual/"


MONDAY = date(2026, 3, 2)
TUESDAY = date(2026, 3, 3)


class PlannedVsActualBase(TimesheetsFixture):
    """The timesheets two-company fixture plus one extra work per side.

    Company B is populated on purpose: an isolation test that passes
    because the other tenant is empty proves nothing.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from customers.models import Customer

        cls.customer_b_org = Customer.objects.create(
            company=cls.company_b, name="Customer B"
        )

    def setUp(self):
        super().setUp()
        self.ew_a = self.make_ew(self.company_a, self.building_a, self.customer_a)
        self.ew_b = self.make_ew(
            self.company_b, self.building_b, self.customer_b_org
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

    def plan(self, employee, extra_work, hours, day=None):
        return ExtraWorkPlannedHours.objects.create(
            extra_work_request=extra_work,
            user=employee,
            date=day,
            hours=Decimal(hours),
            set_by=self.ca_a,
        )

    def hours_on(self, employee, extra_work, day, hours, hour_type=None):
        return self.make_entry(
            employee,
            day,
            hour_type or self.normal_a,
            hours=hours,
            company=extra_work.company,
            created_by=self.ca_a,
            source_type=HourSource.EXTRA_WORK,
            source_id=extra_work.id,
        )

    def spawn_ticket(self, extra_work, **kwargs):
        """The operational ticket the extra work spawned — the door a
        STAFF user reaches this job through."""
        defaults = dict(
            company=extra_work.company,
            building=extra_work.building,
            customer=extra_work.customer,
            created_by=self.ca_a,
            title="Corridor",
            description="x",
            extra_work_request=extra_work,
        )
        defaults.update(kwargs)
        return Ticket.objects.create(**defaults)

    def rows_by_name(self, payload):
        return {row["employee_name"]: row for row in payload["people"]}


class TheThreeNumbers(PlannedVsActualBase):
    def test_planned_worked_and_the_difference_per_person_and_for_the_job(self):
        self.plan(self.staff_a, self.ew_a, "8.00", MONDAY)
        self.plan(self.staff_a2, self.ew_a, "6.00", MONDAY)
        self.hours_on(self.staff_a, self.ew_a, MONDAY, "10.50")
        self.hours_on(self.staff_a2, self.ew_a, MONDAY, "4.00")

        response = self.api(self.sa).get(url(self.ew_a.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()

        self.assertTrue(body["has_plan"])
        self.assertEqual(body["visibility"], "company")

        rows = self.rows_by_name(body)
        first = rows[self.staff_a.full_name or self.staff_a.email]
        self.assertEqual(first["planned_hours"], "8.00")
        self.assertEqual(first["actual_hours"], "10.50")
        self.assertEqual(first["difference_hours"], "2.50")

        second = rows[self.staff_a2.full_name or self.staff_a2.email]
        self.assertEqual(second["planned_hours"], "6.00")
        self.assertEqual(second["actual_hours"], "4.00")
        # Worked less than planned: the difference is negative, and the
        # SIGN is the whole answer.
        self.assertEqual(second["difference_hours"], "-2.00")

        self.assertEqual(body["totals"]["planned_hours"], "14.00")
        self.assertEqual(body["totals"]["actual_hours"], "14.50")
        self.assertEqual(body["totals"]["difference_hours"], "0.50")

    def test_undated_plan_counts_as_planned(self):
        """A plan nobody has placed on a day is still a plan."""
        self.plan(self.staff_a, self.ew_a, "5.00", None)
        self.hours_on(self.staff_a, self.ew_a, MONDAY, "5.00")

        body = self.api(self.sa).get(url(self.ew_a.id)).json()
        row = self.rows_by_name(body)[self.staff_a.full_name or self.staff_a.email]
        self.assertEqual(row["planned_hours"], "5.00")
        self.assertEqual(row["difference_hours"], "0.00")

    def test_hours_are_raw_not_weighted(self):
        """An overtime hour is one hour worked, not one and a half.

        `multiplier_snapshot` is a payroll weight. Letting it reach this
        panel would make a night shift read as more time than anybody
        spent on site.
        """
        self.plan(self.staff_a, self.ew_a, "2.00", MONDAY)
        self.hours_on(
            self.staff_a, self.ew_a, MONDAY, "2.00", hour_type=self.overtime_a
        )

        body = self.api(self.sa).get(url(self.ew_a.id)).json()
        row = self.rows_by_name(body)[self.staff_a.full_name or self.staff_a.email]
        self.assertEqual(row["actual_hours"], "2.00")
        self.assertEqual(row["difference_hours"], "0.00")


class ZerosItDidNotEarn(PlannedVsActualBase):
    def test_worked_without_being_planned_reads_as_not_planned(self):
        self.plan(self.staff_a, self.ew_a, "8.00", MONDAY)
        self.hours_on(self.staff_a, self.ew_a, MONDAY, "8.00")
        # staff_a2 turned up and worked; nobody ever planned them.
        self.hours_on(self.staff_a2, self.ew_a, MONDAY, "3.00")

        body = self.api(self.sa).get(url(self.ew_a.id)).json()
        row = self.rows_by_name(body)[
            self.staff_a2.full_name or self.staff_a2.email
        ]
        self.assertIsNone(row["planned_hours"])
        self.assertIsNone(row["difference_hours"])
        self.assertEqual(row["actual_hours"], "3.00")

    def test_a_job_with_no_plan_says_so_instead_of_showing_zeros(self):
        self.hours_on(self.staff_a, self.ew_a, MONDAY, "4.00")

        body = self.api(self.sa).get(url(self.ew_a.id)).json()
        self.assertFalse(body["has_plan"])
        self.assertIsNone(body["totals"]["planned_hours"])
        self.assertIsNone(body["totals"]["difference_hours"])
        # The worked side is still real and still reported.
        self.assertEqual(body["totals"]["actual_hours"], "4.00")

    def test_an_empty_job_is_empty_not_zeroed(self):
        body = self.api(self.sa).get(url(self.ew_a.id)).json()
        self.assertFalse(body["has_plan"])
        self.assertEqual(body["people"], [])
        self.assertIsNone(body["totals"]["planned_hours"])

    def test_planned_but_nothing_booked_yet_is_a_real_zero(self):
        """Zero WORKED is a fact. Zero PLANNED would be a fiction."""
        self.plan(self.staff_a, self.ew_a, "8.00", MONDAY)

        body = self.api(self.sa).get(url(self.ew_a.id)).json()
        row = self.rows_by_name(body)[self.staff_a.full_name or self.staff_a.email]
        self.assertEqual(row["planned_hours"], "8.00")
        self.assertEqual(row["actual_hours"], "0.00")
        self.assertEqual(row["difference_hours"], "-8.00")


class WhoSeesWhat(PlannedVsActualBase):
    def test_company_admin_reads_the_crew(self):
        self.plan(self.staff_a, self.ew_a, "8.00", MONDAY)
        self.plan(self.staff_a2, self.ew_a, "6.00", MONDAY)

        body = self.api(self.ca_a).get(url(self.ew_a.id)).json()
        self.assertEqual(body["visibility"], "company")
        self.assertEqual(len(body["people"]), 2)

    def test_building_manager_reads_only_their_own_line(self):
        self.plan(self.staff_a, self.ew_a, "8.00", MONDAY)
        self.plan(self.bm_a, self.ew_a, "2.00", MONDAY)
        self.hours_on(self.staff_a, self.ew_a, MONDAY, "8.00")
        self.hours_on(self.bm_a, self.ew_a, MONDAY, "1.00")

        body = self.api(self.bm_a).get(url(self.ew_a.id)).json()
        self.assertEqual(body["visibility"], "self")
        names = [row["employee_name"] for row in body["people"]]
        self.assertEqual(names, [self.bm_a.full_name or self.bm_a.email])
        # Totals cover what the caller may see and nothing else, so one
        # person's line can never be read as the whole job.
        self.assertEqual(body["totals"]["planned_hours"], "2.00")
        self.assertEqual(body["totals"]["actual_hours"], "1.00")

    def test_staff_reach_the_job_through_their_ticket_and_see_themselves(self):
        self.spawn_ticket(self.ew_a)
        self.plan(self.staff_a, self.ew_a, "8.00", MONDAY)
        self.plan(self.staff_a2, self.ew_a, "6.00", MONDAY)
        self.hours_on(self.staff_a, self.ew_a, MONDAY, "9.00")
        self.hours_on(self.staff_a2, self.ew_a, MONDAY, "5.00")

        response = self.api(self.staff_a).get(url(self.ew_a.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["visibility"], "self")
        names = [row["employee_name"] for row in body["people"]]
        self.assertEqual(names, [self.staff_a.full_name or self.staff_a.email])
        self.assertEqual(body["people"][0]["planned_hours"], "8.00")
        self.assertEqual(body["people"][0]["actual_hours"], "9.00")
        self.assertEqual(body["people"][0]["difference_hours"], "1.00")

    def test_staff_with_no_ticket_into_the_job_are_refused(self):
        """`scope_extra_work_for` returns nothing for STAFF by the P0
        staff-privacy decision, and no ticket means no other door."""
        self.plan(self.staff_a, self.ew_a, "8.00", MONDAY)

        response = self.api(self.staff_a).get(url(self.ew_a.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_a_ticket_door_admits_the_caller_but_not_the_crews_rows(self):
        """Getting in buys the panel, not other people's hours.

        `staff_a` holds building-wide visibility, so the ticket is in
        scope even though they never worked this job. The rows still
        narrow to them, so the panel is empty rather than a roster.
        """
        self.spawn_ticket(self.ew_a)
        self.plan(self.staff_a2, self.ew_a, "6.00", MONDAY)
        self.hours_on(self.staff_a2, self.ew_a, MONDAY, "5.00")

        body = self.api(self.staff_a).get(url(self.ew_a.id)).json()
        self.assertEqual(body["visibility"], "self")
        self.assertEqual(body["people"], [])
        self.assertFalse(body["has_plan"])

    def test_customer_side_is_refused_outright(self):
        self.spawn_ticket(self.ew_a)
        self.plan(self.staff_a, self.ew_a, "8.00", MONDAY)

        response = self.api(self.customer_user).get(url(self.ew_a.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_another_tenants_job_is_a_404_like_a_fictional_id(self):
        self.plan(self.staff_b, self.ew_b, "8.00", MONDAY)

        for target in (url(self.ew_b.id), url(99999999)):
            with self.subTest(target=target):
                response = self.api(self.ca_a).get(target)
                self.assertEqual(
                    response.status_code, status.HTTP_404_NOT_FOUND
                )


class NoMoneyPassesThrough(PlannedVsActualBase):
    #: Every money-ish key this repo uses on an hours surface. The panel
    #: must carry none of them under any nesting.
    FORBIDDEN_KEYS = {
        "cost",
        "hourly_rate",
        "rate_source",
        "rate_configured",
        "hours_cost",
        "total_cost",
        "travel_costs",
        "amount",
        "final_total_amount",
        "price",
        "budget_hours",
    }

    def test_the_response_carries_no_money_under_any_key(self):
        self.plan(self.staff_a, self.ew_a, "8.00", MONDAY)
        self.hours_on(self.staff_a, self.ew_a, MONDAY, "9.00")

        body = self.api(self.sa).get(url(self.ew_a.id)).json()

        found: set[str] = set()

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in self.FORBIDDEN_KEYS:
                        found.add(key)
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(body)
        self.assertEqual(
            found,
            set(),
            f"planned hours reach no price anywhere; found {sorted(found)}",
        )
