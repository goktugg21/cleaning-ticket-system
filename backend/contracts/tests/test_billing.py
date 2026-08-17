"""
Sprint 160 — the invoice FORECAST.

These are unit tests over `contracts.billing.build_forecast`: a pure
function, so they assert exact Decimals rather than "a number appeared".

Two of them pin the load-bearing facts from the reference screenshots:

  * the preview lists the invoices STILL TO COME — the first invoice,
    already raised when the contract was signed, is excluded, so a
    contract whose first invoice is 2 January shows 11 rows for that
    year and not 12. The count is DERIVED from the contract's dates,
    never hardcoded: the same test asserts 12 for the following year,
    which would fail against any constant.
  * the yearly figure is the SUM OF ACTUAL PERIOD AMOUNTS, so with
    proration on and a mid-period start it DIFFERS from monthly x 12,
    and with proration off it does not.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.test import TestCase

from companies.models import Company
from customers.models import Customer

from contracts.billing import build_forecast
from contracts.models import BillingPeriod, BillingType

from .fixtures import make_contract


class ForecastTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov", slug="prov-160-bill")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer"
        )

    def contract(self, *, no="CNT-2026-9001", **kwargs):
        kwargs.setdefault("lines", [("Schoonmaak", "13800.00", "100.00")])
        return make_contract(
            company=self.company,
            customer=self.customer,
            contract_no=no,
            **kwargs,
        )


class MidPeriodStartTests(ForecastTestBase):
    """A contract that starts partway through a month."""

    def test_first_period_is_prorated_by_day_count(self):
        contract = self.contract(
            start_date=date(2026, 1, 12), billing_day=1, start_proration=True
        )
        forecast = build_forecast(contract, 2026)

        # January: 12th..31st inclusive = 20 of 31 days.
        expected = (
            Decimal("13800.00") * Decimal(20) / Decimal(31)
        ).quantize(Decimal("0.01"))
        self.assertEqual(forecast.first_invoice_date, date(2026, 1, 12))
        # The first invoice is excluded from the rows but included in
        # the yearly total — that is the whole distinction.
        self.assertEqual(
            forecast.yearly_amount,
            (expected + Decimal("13800.00") * 11).quantize(Decimal("0.01")),
        )

    def test_first_invoice_is_never_dated_before_the_contract_starts(self):
        """billing_day 1 on a contract starting the 12th would date the
        first invoice 1 January, before the contract exists."""
        contract = self.contract(
            start_date=date(2026, 1, 12), billing_day=1
        )
        forecast = build_forecast(contract, 2026)
        self.assertEqual(forecast.first_invoice_date, date(2026, 1, 12))
        # Later periods are unaffected — February bills on the 1st.
        self.assertEqual(forecast.rows[0].invoice_date, date(2026, 2, 1))

    def test_proration_off_bills_every_period_in_full(self):
        contract = self.contract(
            start_date=date(2026, 1, 12), billing_day=1, start_proration=False
        )
        forecast = build_forecast(contract, 2026)
        self.assertEqual(forecast.yearly_amount, Decimal("165600.00"))
        self.assertFalse(any(row.is_prorated for row in forecast.rows))


class YearlyIsNotMonthlyTimesTwelveTests(ForecastTestBase):
    """The €40 discrepancy in the reference screenshots, as a property.

    The reference showed Yearly €165,560 against Monthly x 12
    €165,600. The exact €40 is not reproducible from the figures given
    (see the sprint report), but the PROPERTY behind it is, and it is
    the one that matters: a prorated part-period makes the yearly total
    differ from twelve equal months, and turning proration off makes it
    agree.
    """

    def test_proration_on_makes_yearly_differ_from_monthly_times_twelve(self):
        contract = self.contract(
            start_date=date(2026, 1, 12), start_proration=True
        )
        forecast = build_forecast(contract, 2026)
        self.assertNotEqual(
            forecast.yearly_amount, forecast.monthly_amount * 12
        )
        self.assertLess(forecast.yearly_amount, forecast.monthly_amount * 12)

    def test_proration_off_makes_them_agree(self):
        contract = self.contract(
            start_date=date(2026, 1, 12), start_proration=False
        )
        forecast = build_forecast(contract, 2026)
        self.assertEqual(forecast.yearly_amount, forecast.monthly_amount * 12)

    def test_a_contract_starting_on_a_period_boundary_agrees_either_way(self):
        """Proration only bites on a PART period. A contract starting 1
        January has none, so the flag changes nothing."""
        on = self.contract(
            no="CNT-2026-9101", start_date=date(2026, 1, 1), start_proration=True
        )
        off = self.contract(
            no="CNT-2026-9102",
            start_date=date(2026, 1, 1),
            start_proration=False,
        )
        self.assertEqual(
            build_forecast(on, 2026).yearly_amount,
            build_forecast(off, 2026).yearly_amount,
        )


class StillToComeRuleTests(ForecastTestBase):
    """Which rows the preview shows.

    Implemented as `invoice_date > first_invoice_date` — the brief's
    "after the first invoice date" option, chosen over "on or after
    today" because it is a property of the contract's own dates and so
    gives the same answer on every run.
    """

    def test_the_first_year_shows_eleven_rows_not_twelve(self):
        contract = self.contract(
            start_date=date(2026, 1, 2), billing_day=2
        )
        forecast = build_forecast(contract, 2026)
        self.assertEqual(forecast.first_invoice_date, date(2026, 1, 2))
        self.assertEqual(len(forecast.rows), 11)
        self.assertTrue(forecast.excluded_first_invoice)
        # February is the first row shown — the reference's "Şubat 2026".
        self.assertEqual(forecast.rows[0].period_start, date(2026, 2, 1))

    def test_a_later_year_shows_all_twelve(self):
        """The 11 is DERIVED, not a constant: the year after the
        contract starts has no already-issued invoice to exclude."""
        contract = self.contract(
            start_date=date(2026, 1, 2), billing_day=2
        )
        forecast = build_forecast(contract, 2027)
        self.assertEqual(len(forecast.rows), 12)
        self.assertFalse(forecast.excluded_first_invoice)

    def test_rows_total_is_the_sum_of_the_displayed_rows(self):
        contract = self.contract(
            start_date=date(2026, 1, 2), billing_day=2
        )
        forecast = build_forecast(contract, 2026)
        self.assertEqual(forecast.rows_total, Decimal("13800.00") * 11)
        # ...and is NOT the yearly figure, which includes the excluded
        # first invoice. This is the reference's €151,800 vs €165,560.
        self.assertNotEqual(forecast.rows_total, forecast.yearly_amount)


class OpenEndedContractTests(ForecastTestBase):
    def test_an_open_ended_contract_forecasts_a_full_year(self):
        contract = self.contract(
            start_date=date(2020, 1, 1), end_date=None
        )
        forecast = build_forecast(contract, 2026)
        self.assertEqual(len(forecast.rows), 12)
        self.assertEqual(forecast.yearly_amount, Decimal("165600.00"))

    def test_a_year_before_the_contract_starts_is_empty(self):
        contract = self.contract(start_date=date(2026, 1, 1))
        forecast = build_forecast(contract, 2025)
        self.assertEqual(forecast.rows, [])
        self.assertEqual(forecast.yearly_amount, Decimal("0.00"))


class EndDateTests(ForecastTestBase):
    def test_a_contract_ending_mid_year_stops_billing(self):
        contract = self.contract(
            start_date=date(2026, 1, 1), end_date=date(2026, 6, 30)
        )
        forecast = build_forecast(contract, 2026)
        # January is the excluded first invoice; February..June remain.
        self.assertEqual(len(forecast.rows), 5)
        self.assertEqual(forecast.rows[-1].period_start, date(2026, 6, 1))
        self.assertEqual(forecast.yearly_amount, Decimal("13800.00") * 6)

    def test_a_contract_ending_mid_period_prorates_the_last_one(self):
        contract = self.contract(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 6, 15),
            start_proration=True,
        )
        forecast = build_forecast(contract, 2026)
        last = forecast.rows[-1]
        self.assertTrue(last.is_prorated)
        self.assertEqual(last.covered_days, 15)
        self.assertEqual(last.period_days, 30)
        self.assertEqual(
            last.amount,
            (Decimal("13800.00") * Decimal(15) / Decimal(30)).quantize(
                Decimal("0.01")
            ),
        )


class BillingPeriodTests(ForecastTestBase):
    def test_quarterly_bills_four_times_a_year_on_calendar_quarters(self):
        contract = self.contract(
            start_date=date(2026, 1, 1),
            billing_period=BillingPeriod.QUARTERLY,
            lines=[("Schoonmaak", "30000.00", "300.00")],
        )
        forecast = build_forecast(contract, 2026)
        self.assertEqual(forecast.invoices_per_year, 4)
        # Q1 is the excluded first invoice; Q2..Q4 remain.
        self.assertEqual(len(forecast.rows), 3)
        self.assertEqual(
            [row.period_start for row in forecast.rows],
            [date(2026, 4, 1), date(2026, 7, 1), date(2026, 10, 1)],
        )
        # A quarter's money normalised to a month.
        self.assertEqual(forecast.monthly_amount, Decimal("10000.00"))
        self.assertEqual(forecast.yearly_amount, Decimal("120000.00"))

    def test_yearly_bills_once(self):
        contract = self.contract(
            start_date=date(2026, 1, 1),
            billing_period=BillingPeriod.YEARLY,
            lines=[("Schoonmaak", "120000.00", "1200.00")],
        )
        self.assertEqual(build_forecast(contract, 2026).invoices_per_year, 1)
        # 2026 holds only the excluded first invoice.
        self.assertEqual(len(build_forecast(contract, 2026).rows), 0)
        self.assertEqual(len(build_forecast(contract, 2027).rows), 1)
        self.assertEqual(
            build_forecast(contract, 2026).monthly_amount, Decimal("10000.00")
        )


class AdvanceVsArrearsTests(ForecastTestBase):
    def test_advance_dates_the_invoice_inside_its_own_period(self):
        contract = self.contract(
            start_date=date(2026, 1, 1),
            billing_day=5,
            billing_type=BillingType.ADVANCE,
        )
        row = build_forecast(contract, 2026).rows[0]
        self.assertEqual(row.period_start, date(2026, 2, 1))
        self.assertEqual(row.invoice_date, date(2026, 2, 5))

    def test_arrears_dates_the_invoice_after_the_period_ends(self):
        contract = self.contract(
            start_date=date(2026, 1, 1),
            billing_day=5,
            billing_type=BillingType.ARREARS,
        )
        forecast = build_forecast(contract, 2026)
        # The January period bills on 5 February — the excluded first
        # invoice. The first row shown is February, billed 5 March.
        self.assertEqual(forecast.first_invoice_date, date(2026, 2, 5))
        row = forecast.rows[0]
        self.assertEqual(row.period_start, date(2026, 2, 1))
        self.assertEqual(row.invoice_date, date(2026, 3, 5))

    def test_arrears_pushes_decembers_invoice_into_the_next_year(self):
        """The December period bills in January, so it belongs to the
        NEXT year's preview. Pinned because it is the case a naive
        `period.year == year` filter gets wrong."""
        contract = self.contract(
            start_date=date(2026, 1, 1),
            billing_day=5,
            billing_type=BillingType.ARREARS,
        )
        year_2027 = build_forecast(contract, 2027)
        self.assertEqual(year_2027.rows[0].period_start, date(2026, 12, 1))
        self.assertEqual(year_2027.rows[0].invoice_date, date(2027, 1, 5))


class DueDateTests(ForecastTestBase):
    def test_due_date_is_invoice_date_plus_payment_terms(self):
        contract = self.contract(
            start_date=date(2026, 1, 1), billing_day=1, payment_terms_days=14
        )
        row = build_forecast(contract, 2026).rows[0]
        self.assertEqual(row.invoice_date, date(2026, 2, 1))
        self.assertEqual(row.due_date, date(2026, 2, 15))


class MoneyDisciplineTests(ForecastTestBase):
    def test_every_amount_is_a_two_decimal_decimal(self):
        contract = self.contract(
            start_date=date(2026, 1, 7),
            lines=[("A", "333.33", "10.00"), ("B", "666.67", "10.00")],
        )
        forecast = build_forecast(contract, 2026)
        for value in [
            forecast.rows_total,
            forecast.yearly_amount,
            forecast.monthly_amount,
        ] + [row.amount for row in forecast.rows]:
            self.assertIsInstance(value, Decimal)
            self.assertEqual(value, value.quantize(Decimal("0.01")))

    def test_the_forecast_writes_nothing(self):
        """Sprint 158 turns a due row into a real invoice; this sprint
        does not. Asserted by counting rows in the invoicing tables
        before and after — the cheapest possible proof that reading a
        forecast has no side effect."""
        from invoicing.models import Invoice, InvoiceLine

        contract = self.contract(start_date=date(2026, 1, 1))
        before = (Invoice.objects.count(), InvoiceLine.objects.count())
        build_forecast(contract, 2026)
        build_forecast(contract, 2027)
        after = (Invoice.objects.count(), InvoiceLine.objects.count())
        self.assertEqual(before, after)
        self.assertEqual(after, (0, 0))
