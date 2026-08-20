"""
W4-R — the per-person hourly rate, and the promise that a raise never
re-prices the past.

W3-H shipped ONE deployment-wide rate and called it the only knob until
a real per-person rate was designed. This is that rate, and these are
the rules it has to keep. Each one is something somebody could undo
without any other test in the repo noticing:

1. **A rate is per person and it is DATED.** The rate that costs an hour
   is the row in force on the DAY OF THAT HOUR — latest `valid_from` at
   or before it — not the person's current rate.
2. **THE RAISE TEST.** Cost a January job. Give the worker a raise from
   March. Cost the same January job again. Every figure must be
   byte-identical. This is the most important assertion in the sprint:
   getting it wrong means every historical cost figure in the system
   moves the day somebody gets a raise.
3. **The deployment rate is still the FALLBACK**, for anyone with no
   personal rate — and when neither exists, every cost is NULL. A zero
   is never printed.
4. **Partial knowledge is not a total.** One priced worker and one
   unpriced worker produce no total at all, plus a count of the hours
   nobody's rate covers.
5. **A rate is per company.** The same person working for two providers
   holds two rates, and neither tenant can read the other's.
6. **Zero is not a legal wage**, at the model and at the resolver.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.test import override_settings

from extra_work.models import ExtraWorkCategory, ExtraWorkRequest, ExtraWorkStatus
from reports.labour_cost import (
    RATE_SOURCE_DEPLOYMENT,
    RATE_SOURCE_EMPLOYEE,
    RATE_SOURCE_MIXED,
    HourSegment,
    RateBook,
    labour_cost,
    resolve_deployment_hourly_rate,
    resolve_hourly_rate,
)
from reports.models import EmployeeHourlyRate
from timesheets.models import HourSource
from timesheets.tests.fixtures import TimesheetsFixture


JANUARY = date(2026, 1, 12)
MARCH = date(2026, 3, 2)
MAY = date(2026, 5, 4)


class RateFixture(TimesheetsFixture):
    """The two-company timesheets fixture plus a rate-writing helper."""

    def rate(self, employee, amount, valid_from, company=None):
        return EmployeeHourlyRate.objects.create(
            company=company or self.company_a,
            employee=employee,
            hourly_rate=Decimal(amount),
            valid_from=valid_from,
            created_by=self.ca_a,
        )

    def segment(self, employee, day, weighted):
        return HourSegment(
            employee_id=employee.id, on_date=day, weighted_hours=Decimal(weighted)
        )


class ResolutionTests(RateFixture):
    def test_the_rate_in_force_is_the_latest_one_starting_on_or_before_the_day(self):
        self.rate(self.staff_a, "20.00", JANUARY)
        self.rate(self.staff_a, "25.00", MARCH)

        book = RateBook.load(self.company_a.id, [self.staff_a.id])

        # The day the second row starts is covered BY the second row —
        # `valid_from` is the FIRST day in force, not the day after.
        self.assertEqual(book.rate_on(self.staff_a.id, MARCH), Decimal("25.00"))
        self.assertEqual(
            book.rate_on(self.staff_a.id, date(2026, 3, 1)), Decimal("20.00")
        )
        self.assertEqual(book.rate_on(self.staff_a.id, JANUARY), Decimal("20.00"))
        self.assertEqual(book.rate_on(self.staff_a.id, MAY), Decimal("25.00"))

    def test_a_day_BEFORE_the_first_rate_row_resolves_to_no_personal_rate(self):
        """Not the first row applied backwards. Nobody stated a rate for
        that day, and inventing one would be a claim nobody made."""
        self.rate(self.staff_a, "25.00", MARCH)

        book = RateBook.load(self.company_a.id, [self.staff_a.id])

        self.assertIsNone(book.rate_on(self.staff_a.id, JANUARY))

    def test_a_FUTURE_dated_rate_does_not_apply_yet(self):
        """An agreed raise can be entered before it starts. It must not
        cost today's hours at tomorrow's rate."""
        self.rate(self.staff_a, "20.00", JANUARY)
        self.rate(self.staff_a, "99.00", MAY)

        book = RateBook.load(self.company_a.id, [self.staff_a.id])

        self.assertEqual(book.rate_on(self.staff_a.id, MARCH), Decimal("20.00"))

    def test_an_unattributed_block_of_hours_resolves_to_no_personal_rate(self):
        """No person or no day means no way to say which rate applied,
        and guessing 'the current one' is the silent re-pricing this
        model exists to prevent."""
        self.rate(self.staff_a, "25.00", JANUARY)

        book = RateBook.load(self.company_a.id, [self.staff_a.id])

        self.assertIsNone(book.rate_on(self.staff_a.id, None))
        self.assertIsNone(book.rate_on(None, MARCH))

    def test_resolve_hourly_rate_prefers_the_person_then_the_deployment(self):
        self.rate(self.staff_a, "30.00", JANUARY)

        with override_settings(LABOUR_COST_HOURLY_RATE_EUR="25.00"):
            personal = resolve_hourly_rate(
                employee_id=self.staff_a.id,
                on_date=MARCH,
                company_id=self.company_a.id,
            )
            fallback = resolve_hourly_rate(
                employee_id=self.staff_a2.id,
                on_date=MARCH,
                company_id=self.company_a.id,
            )

        self.assertEqual(personal, (Decimal("30.00"), RATE_SOURCE_EMPLOYEE))
        self.assertEqual(fallback, (Decimal("25.00"), RATE_SOURCE_DEPLOYMENT))

    def test_with_neither_a_personal_nor_a_deployment_rate_the_answer_is_nothing(self):
        answer = resolve_hourly_rate(
            employee_id=self.staff_a.id, on_date=MARCH, company_id=self.company_a.id
        )

        self.assertEqual(answer, (None, None))
        self.assertIsNone(resolve_deployment_hourly_rate())

    def test_a_rate_is_PER_COMPANY_and_neither_side_reads_the_other(self):
        """Somebody who works for two providers holds two rates. Reading
        one from the other's costing would be a cross-tenant leak of the
        most sensitive field in the system."""
        shared = self.staff_a
        self.rate(shared, "20.00", JANUARY, company=self.company_a)
        self.rate(shared, "80.00", JANUARY, company=self.company_b)

        in_a = RateBook.load(self.company_a.id, [shared.id])
        in_b = RateBook.load(self.company_b.id, [shared.id])

        self.assertEqual(in_a.rate_on(shared.id, MARCH), Decimal("20.00"))
        self.assertEqual(in_b.rate_on(shared.id, MARCH), Decimal("80.00"))

    def test_the_whole_crew_is_one_query(self):
        """Costing a ten-person job must not be ten point lookups — the
        N+1 the assertNumQueries tests in this app exist to catch."""
        for person in (self.staff_a, self.staff_a2, self.bm_a):
            self.rate(person, "25.00", JANUARY)

        with self.assertNumQueries(1):
            book = RateBook.load(
                self.company_a.id,
                [self.staff_a.id, self.staff_a2.id, self.bm_a.id],
            )
            for person in (self.staff_a, self.staff_a2, self.bm_a):
                self.assertEqual(book.rate_on(person.id, MARCH), Decimal("25.00"))

    def test_no_people_means_no_query_at_all(self):
        with self.assertNumQueries(0):
            RateBook.load(self.company_a.id, [])
        with self.assertNumQueries(0):
            RateBook.load(None, [self.staff_a.id])


class TheRaiseTests(RateFixture):
    """THE test. A raise must not move a single historical figure."""

    def cost_january(self):
        return labour_cost(
            segments=[self.segment(self.staff_a, JANUARY, "8.00")],
            travel_costs=Decimal("12.50"),
            company_id=self.company_a.id,
        )

    def test_A_RAISE_IN_MARCH_DOES_NOT_REPRICE_JANUARY(self):
        self.rate(self.staff_a, "20.00", JANUARY)
        before = self.cost_january()

        # The raise, entered exactly as an operator would enter it: a
        # NEW row from a NEW date, not an edit of the old one.
        self.rate(self.staff_a, "31.75", MARCH)
        after = self.cost_january()

        self.assertEqual(before, after)
        self.assertEqual(after["hours_cost"], "160.00")
        self.assertEqual(after["hourly_rate"], "20.00")

    def test_the_raise_DOES_move_work_done_after_it(self):
        """The other half of the same promise: history is fixed, the
        present is not. A rate that changed nothing would be useless."""
        self.rate(self.staff_a, "20.00", JANUARY)
        self.rate(self.staff_a, "31.75", MARCH)

        after_raise = labour_cost(
            segments=[self.segment(self.staff_a, MAY, "8.00")],
            company_id=self.company_a.id,
        )

        self.assertEqual(after_raise["hours_cost"], "254.00")
        self.assertEqual(after_raise["hourly_rate"], "31.75")

    def test_one_job_spanning_the_raise_is_costed_at_BOTH_rates(self):
        """A job that ran across the raise costs what it actually cost:
        the January days at the January rate, the May days at the May
        one. A single 'current rate' would over-charge the whole job."""
        self.rate(self.staff_a, "20.00", JANUARY)
        self.rate(self.staff_a, "31.75", MARCH)

        cost = labour_cost(
            segments=[
                self.segment(self.staff_a, JANUARY, "8.00"),
                self.segment(self.staff_a, MAY, "8.00"),
            ],
            company_id=self.company_a.id,
        )

        # 8 x 20.00 + 8 x 31.75. Not 16 x either one.
        self.assertEqual(cost["hours_cost"], "414.00")
        # Two different rates did the work, so there is no ONE rate to
        # name — and naming either would be a wrong answer, not a
        # partial one.
        self.assertIsNone(cost["hourly_rate"])
        self.assertEqual(cost["rate_source"], RATE_SOURCE_MIXED)
        self.assertTrue(cost["rate_configured"])


class CrewCostTests(RateFixture):
    def test_two_people_on_two_rates_are_each_costed_at_their_own(self):
        self.rate(self.staff_a, "20.00", JANUARY)
        self.rate(self.staff_a2, "35.00", JANUARY)

        cost = labour_cost(
            segments=[
                self.segment(self.staff_a, MARCH, "4.00"),
                self.segment(self.staff_a2, MARCH, "2.00"),
            ],
            company_id=self.company_a.id,
        )

        # 4 x 20 + 2 x 35 = 150. An average rate would give 165.
        self.assertEqual(cost["hours_cost"], "150.00")
        self.assertIsNone(cost["hourly_rate"])
        self.assertEqual(cost["rate_source"], RATE_SOURCE_MIXED)

    @override_settings(LABOUR_COST_HOURLY_RATE_EUR="25.00")
    def test_someone_with_no_personal_rate_falls_back_to_the_deployment_one(self):
        self.rate(self.staff_a, "20.00", JANUARY)

        cost = labour_cost(
            segments=[
                self.segment(self.staff_a, MARCH, "4.00"),
                self.segment(self.staff_a2, MARCH, "4.00"),
            ],
            company_id=self.company_a.id,
        )

        # 4 x 20 (personal) + 4 x 25 (fallback).
        self.assertEqual(cost["hours_cost"], "180.00")
        self.assertEqual(cost["rate_source"], RATE_SOURCE_MIXED)
        self.assertEqual(cost["unrated_weighted_hours"], "0.00")

    @override_settings(LABOUR_COST_HOURLY_RATE_EUR="25.00")
    def test_one_rate_for_everyone_still_names_that_one_rate(self):
        """The W3-H shape survives: a deployment that set one rate and
        no personal ones reads exactly as it did before."""
        cost = labour_cost(
            segments=[
                self.segment(self.staff_a, MARCH, "4.00"),
                self.segment(self.staff_a2, MARCH, "3.00"),
            ],
            company_id=self.company_a.id,
        )

        self.assertEqual(cost["hourly_rate"], "25.00")
        self.assertEqual(cost["rate_source"], RATE_SOURCE_DEPLOYMENT)
        self.assertEqual(cost["hours_cost"], "175.00")

    def test_PARTIAL_KNOWLEDGE_IS_NOT_A_TOTAL(self):
        """One priced worker, one unpriced, no fallback. A figure
        covering half the crew is the number an operator would read as
        the job's cost and act on."""
        self.rate(self.staff_a, "20.00", JANUARY)

        cost = labour_cost(
            segments=[
                self.segment(self.staff_a, MARCH, "4.00"),
                self.segment(self.staff_a2, MARCH, "6.00"),
            ],
            travel_costs=Decimal("12.50"),
            company_id=self.company_a.id,
        )

        self.assertFalse(cost["rate_configured"])
        self.assertIsNone(cost["hours_cost"])
        self.assertIsNone(cost["total_cost"])
        self.assertIsNone(cost["hourly_rate"])
        # The absence has a reason attached rather than being a blank.
        self.assertEqual(cost["unrated_weighted_hours"], "6.00")
        # Travel is real money somebody claimed; it needs no rate.
        self.assertEqual(cost["travel_costs"], "12.50")

    def test_no_rate_anywhere_reports_zero_unrated_and_no_cost(self):
        """The other way of not knowing, and it must produce the SAME
        shape — a caller that had to tell them apart from the field set
        is a caller that gets it wrong once."""
        cost = labour_cost(
            segments=[self.segment(self.staff_a, MARCH, "4.00")],
            company_id=self.company_a.id,
        )

        self.assertFalse(cost["rate_configured"])
        self.assertIsNone(cost["total_cost"])
        self.assertEqual(cost["unrated_weighted_hours"], "4.00")

    def test_UNPAID_LEAVE_WITH_NO_RATE_IS_UNKNOWN_NOT_A_CONFIDENT_ZERO(self):
        """A 0.00 multiplier is legal — `HourType.multiplier` documents
        unpaid leave as hours worked zero times. Those segments weigh
        nothing, so keying "is anything unpriced" off the HOURS would
        call this job fully priced and print EUR 0,00 for a company that
        has never set a rate. The cost of zero weighted hours IS zero;
        whether we know a rate is a different question."""
        cost = labour_cost(
            segments=[self.segment(self.staff_a, MARCH, "0.00")],
            company_id=self.company_a.id,
        )

        self.assertFalse(cost["rate_configured"])
        self.assertIsNone(cost["hours_cost"])
        self.assertIsNone(cost["total_cost"])

    def test_unpaid_leave_WITH_a_rate_on_file_really_does_cost_nothing(self):
        """The other half: with a rate known, zero weighted hours cost
        zero, and that 0.00 is a real answer rather than a stand-in."""
        self.rate(self.staff_a, "20.00", JANUARY)

        cost = labour_cost(
            segments=[self.segment(self.staff_a, MARCH, "0.00")],
            company_id=self.company_a.id,
        )

        self.assertTrue(cost["rate_configured"])
        self.assertEqual(cost["hours_cost"], "0.00")
        self.assertEqual(cost["hourly_rate"], "20.00")

    def test_a_job_with_no_hours_and_a_rate_on_file_costs_nothing_knowably(self):
        """0.00 here is a real answer: no hours were worked. It is only
        a lie when we do not KNOW, and a company with rates on file
        knows."""
        self.rate(self.staff_a, "20.00", JANUARY)

        cost = labour_cost(segments=[], company_id=self.company_a.id)

        self.assertTrue(cost["rate_configured"])
        self.assertEqual(cost["hours_cost"], "0.00")
        self.assertEqual(cost["total_cost"], "0.00")

    def test_a_job_with_no_hours_and_no_rate_anywhere_stays_unknown(self):
        cost = labour_cost(segments=[], company_id=self.company_a.id)

        self.assertFalse(cost["rate_configured"])
        self.assertIsNone(cost["total_cost"])

    def test_rounding_happens_ONCE_at_the_end(self):
        """Two roundings on one figure is how the reference system's
        totals came to disagree by cents with themselves.

        Each quarter-hour at EUR 20.10 costs 5.025 — half a cent.
        Rounded per segment that is 5.03 + 5.03 = 10.06; rounded once
        from the unrounded sum it is 10.05, which is what the job
        actually cost.
        """
        self.rate(self.staff_a, "20.10", JANUARY)

        cost = labour_cost(
            segments=[
                self.segment(self.staff_a, MARCH, "0.25"),
                self.segment(self.staff_a, MAY, "0.25"),
            ],
            company_id=self.company_a.id,
        )

        self.assertEqual(cost["hours_cost"], "10.05")


class ModelRuleTests(RateFixture):
    def test_ZERO_IS_NOT_A_LEGAL_WAGE(self):
        """Zero is a legal PRICE — Sprint 188 argues that at length for
        what we charge. It is not a legal wage: nobody works for
        nothing, and a 0 in this column is a placeholder somebody
        typed."""
        row = EmployeeHourlyRate(
            company=self.company_a,
            employee=self.staff_a,
            hourly_rate=Decimal("0.00"),
            valid_from=JANUARY,
            created_by=self.ca_a,
        )

        with self.assertRaises(DjangoValidationError):
            row.full_clean()

    @override_settings(LABOUR_COST_HOURLY_RATE_EUR="0")
    def test_a_deployment_rate_of_zero_is_read_as_NOT_CONFIGURED(self):
        """The same rule on the other rate, so the two agree."""
        self.assertIsNone(resolve_deployment_hourly_rate())

    def test_one_rate_per_person_per_company_per_START_DATE(self):
        """Two rows on one date make 'the row in force' a coin flip
        decided by insertion order, and the same job would cost two
        different amounts on two page loads."""
        self.rate(self.staff_a, "20.00", JANUARY)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.rate(self.staff_a, "25.00", JANUARY)

    def test_the_same_date_in_two_companies_is_fine(self):
        self.rate(self.staff_a, "20.00", JANUARY, company=self.company_a)
        self.rate(self.staff_a, "80.00", JANUARY, company=self.company_b)

        self.assertEqual(
            EmployeeHourlyRate.objects.filter(employee=self.staff_a).count(), 2
        )

    def test_history_reads_newest_first(self):
        self.rate(self.staff_a, "20.00", JANUARY)
        self.rate(self.staff_a, "25.00", MARCH)
        self.rate(self.staff_a, "31.75", MAY)

        rows = list(EmployeeHourlyRate.objects.filter(employee=self.staff_a))

        self.assertEqual(
            [str(row.hourly_rate) for row in rows], ["31.75", "25.00", "20.00"]
        )


class EndToEndCostTests(RateFixture):
    """The per-person rate, through the real endpoint, on real entries."""

    URL = "/api/reports/extra-work/{}/hours/"

    def setUp(self):
        super().setUp()
        from customers.models import Customer

        self.customer_org = Customer.objects.create(
            company=self.company_a, name="Customer for W4-R"
        )
        self.ew = ExtraWorkRequest.objects.create(
            company=self.company_a,
            building=self.building_a,
            customer=self.customer_org,
            created_by=self.sa,
            title="Strip and seal the corridor",
            description="x",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.IN_PROGRESS,
        )

    def hours_on(self, employee, day, hours, hour_type=None):
        return self.make_entry(
            employee,
            day,
            hour_type or self.normal_a,
            hours=hours,
            company=self.company_a,
            created_by=self.ca_a,
            source_type=HourSource.EXTRA_WORK,
            source_id=self.ew.id,
        )

    def cost(self):
        return self.api(self.ca_a).get(self.URL.format(self.ew.id)).data["cost"]

    def test_the_endpoint_costs_each_persons_hours_at_that_persons_rate(self):
        self.rate(self.staff_a, "20.00", JANUARY)
        self.rate(self.staff_a2, "35.00", JANUARY)
        self.hours_on(self.staff_a, MARCH, "4.00")
        self.hours_on(self.staff_a2, MARCH, "2.00")

        cost = self.cost()

        self.assertEqual(cost["hours_cost"], "150.00")
        self.assertEqual(cost["rate_source"], RATE_SOURCE_MIXED)

    def test_A_RAISE_DOES_NOT_MOVE_THE_ENDPOINTS_ANSWER_FOR_OLD_WORK(self):
        """The raise test again, at the surface an operator actually
        reads. Every byte of the cost block must survive the raise."""
        self.rate(self.staff_a, "20.00", JANUARY)
        self.hours_on(self.staff_a, JANUARY, "8.00")
        before = self.cost()

        self.rate(self.staff_a, "31.75", MARCH)
        after = self.cost()

        self.assertEqual(before, after)
        self.assertEqual(after["hours_cost"], "160.00")

    def test_the_personal_rate_still_costs_WEIGHTED_hours(self):
        """The multiplier is a WEIGHT and the rate is a WAGE; the two
        multiply, and neither replaces the other."""
        self.rate(self.staff_a, "20.00", JANUARY)
        self.hours_on(self.staff_a, MARCH, "2.00", hour_type=self.overtime_a)

        cost = self.cost()

        # 2.00 hours x 1.50 weight x EUR 20.00.
        self.assertEqual(cost["hours_cost"], "60.00")
        self.assertEqual(cost["hourly_rate"], "20.00")
        self.assertEqual(cost["rate_source"], RATE_SOURCE_EMPLOYEE)

    def test_a_personal_rate_BEATS_the_deployment_fallback(self):
        self.rate(self.staff_a, "20.00", JANUARY)
        self.hours_on(self.staff_a, MARCH, "4.00")

        with override_settings(LABOUR_COST_HOURLY_RATE_EUR="99.00"):
            cost = self.cost()

        self.assertEqual(cost["hours_cost"], "80.00")
        self.assertEqual(cost["rate_source"], RATE_SOURCE_EMPLOYEE)

    def test_another_tenants_rate_for_the_same_person_never_prices_this_job(self):
        """The cross-tenant assertion on the most sensitive field there
        is, with company B genuinely populated."""
        self.rate(self.staff_a, "20.00", JANUARY, company=self.company_a)
        self.rate(self.staff_a, "999.00", JANUARY, company=self.company_b)
        self.hours_on(self.staff_a, MARCH, "1.00")

        cost = self.cost()

        self.assertEqual(cost["hours_cost"], "20.00")
