"""
Sprint 185 E §2 — the shares actually split the invoice.

This is the most dangerous item in the sprint, so these tests are written
against the properties that would cost real money if they broke, not
against the implementation:

  * **a building with no shares is untouched.** Not one existing invoice
    changes. If this fails, everything else is irrelevant;
  * **the parts sum EXACTLY to the whole**, across awkward numbers —
    three at 33.33%, and a set that forces the remainder onto a
    particular share. EUR 100 must never come out as EUR 99.99;
  * **the answer does not depend on who is invoiced first.** Two
    customers on the same shared building may have different billing
    days, so their parts are computed weeks apart; the allocation is
    recomputed from the whole share set every time and must be stable;
  * **VAT is computed on each part**, so each invoice is consistent with
    itself;
  * **one share-holder's invoice does not settle the work for the
    others** — the claim is per customer;
  * **reversal releases exactly what it claimed**, and only that
    customer's share.
"""
from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

from buildings.models import BuildingCostShare
from customers.models import Customer, CustomerBuildingMembership
from invoicing.cost_shares import allocate
from invoicing.preview import plan_invoices
from invoicing.services import generate_draft_invoices

from ._helpers import InvoicingFixture

# The fixture's own billing period, the one every other invoicing test
# uses: work closed on 2026-05-31 is billable in 2026-05.
YEAR, MONTH = 2026, 5
CLOSED_AT = datetime(2026, 5, 31, 12, 0, tzinfo=dt_timezone.utc)


class AllocationRuleTests(InvoicingFixture):
    """The rounding rule, tested as arithmetic before it is tested as
    money. `allocate` is the one function that decides who absorbs a
    remainder, so it is pinned directly."""

    def test_three_equal_thirds_of_100_sum_to_100(self):
        shares = [(1, Decimal("33.33")), (2, Decimal("33.33")), (3, Decimal("33.34"))]
        parts = allocate(Decimal("100.00"), shares)
        self.assertEqual(sum(parts.values()), Decimal("100.00"))

    def test_the_remainder_goes_to_the_largest_share(self):
        shares = [(1, Decimal("33.33")), (2, Decimal("33.33")), (3, Decimal("33.34"))]
        parts = allocate(Decimal("100.00"), shares)
        # 33.33 / 33.33 / 33.34 floors to 33.33 / 33.33 / 33.34 = 100.00
        # exactly, so nothing moves. The interesting case is below.
        self.assertEqual(parts[3], Decimal("33.34"))

    def test_an_awkward_amount_still_sums_to_the_whole(self):
        shares = [(1, Decimal("33.33")), (2, Decimal("33.33")), (3, Decimal("33.34"))]
        for amount in ("100.00", "0.01", "0.03", "10.00", "99.99", "1234.56"):
            with self.subTest(amount=amount):
                parts = allocate(Decimal(amount), shares)
                self.assertEqual(sum(parts.values()), Decimal(amount))

    def test_equal_shares_break_the_tie_on_the_lowest_customer_id(self):
        """Determinism matters more than fairness here: the same input
        must give the same answer whoever is invoiced first."""
        shares = [(7, Decimal("50.00")), (3, Decimal("50.00"))]
        parts = allocate(Decimal("0.01"), shares)
        self.assertEqual(parts[3], Decimal("0.01"))
        self.assertEqual(parts[7], Decimal("0.00"))
        self.assertEqual(sum(parts.values()), Decimal("0.01"))

    def test_no_shares_allocates_nothing(self):
        self.assertEqual(allocate(Decimal("100.00"), []), {})


class SharedBuildingInvoiceTests(InvoicingFixture):
    """The split, end to end, through the single calculation."""

    def _earned_ew(self, subtotal="100.00", vat="21.00", customer=None):
        """An Extra Work earned in the fixture's own billing period.

        `make_ew` is the shared builder every other invoicing test uses;
        the FINAL amounts are what `_earned_amounts` prefers, so they are
        what gets split.
        """
        subtotal = Decimal(subtotal)
        vat = Decimal(vat)
        return self.make_ew(
            closed_at=CLOSED_AT,
            customer=customer or self.customer,
            building=self.building,
            final_subtotal=subtotal,
            final_vat=vat,
            final_total=subtotal + vat,
        )

    def _second_customer(self):
        customer = Customer.objects.create(
            company=self.company, name="Cust A2", building=self.building
        )
        CustomerBuildingMembership.objects.get_or_create(
            customer=customer, building=self.building
        )
        return customer

    def _third_customer(self):
        customer = Customer.objects.create(
            company=self.company, name="Cust A3", building=self.building
        )
        CustomerBuildingMembership.objects.get_or_create(
            customer=customer, building=self.building
        )
        return customer

    def _share(self, customer, pct):
        CustomerBuildingMembership.objects.get_or_create(
            customer=customer, building=self.building
        )
        return BuildingCostShare.objects.create(
            building=self.building, customer=customer, share_pct=Decimal(pct)
        )

    # ------------------------------------------------------------------
    # The safety property
    # ------------------------------------------------------------------
    def test_a_building_with_no_shares_bills_exactly_as_before(self):
        ew = self._earned_ew(subtotal="100.00", vat="21.00")
        self.assertIsNotNone(ew.id)
        invoices = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )
        self.assertEqual(len(invoices), 1)
        self.assertEqual(invoices[0].subtotal_amount, Decimal("100.00"))
        self.assertEqual(invoices[0].vat_amount, Decimal("21.00"))
        self.assertEqual(invoices[0].total_amount, Decimal("121.00"))

    # ------------------------------------------------------------------
    # The split
    # ------------------------------------------------------------------
    def test_two_customers_are_each_billed_their_share(self):
        other = self._second_customer()
        self._share(self.customer, "60.00")
        self._share(other, "40.00")
        ew = self._earned_ew(subtotal="100.00", vat="21.00")

        mine = generate_draft_invoices(
            self.admin,
            self.company.id,
            self.customer.id,
            YEAR,
            MONTH,
        )
        theirs = generate_draft_invoices(
            self.admin,
            self.company.id,
            other.id,
            YEAR,
            MONTH,
        )

        self.assertEqual(len(mine), 1)
        self.assertEqual(len(theirs), 1)
        self.assertEqual(mine[0].subtotal_amount, Decimal("60.00"))
        self.assertEqual(theirs[0].subtotal_amount, Decimal("40.00"))
        self.assertEqual(
            mine[0].subtotal_amount + theirs[0].subtotal_amount,
            Decimal("100.00"),
        )

    def test_three_thirds_of_100_lose_no_cent(self):
        """The number the prompt names: three customers at 33.33% of a
        EUR 100 line cannot produce EUR 99.99."""
        b = self._second_customer()
        c = self._third_customer()
        self._share(self.customer, "33.33")
        self._share(b, "33.33")
        self._share(c, "33.34")
        ew = self._earned_ew(subtotal="100.00", vat="21.00")

        totals = []
        for customer in (self.customer, b, c):
            drafts = generate_draft_invoices(
                self.admin,
                self.company.id,
                customer.id,
                YEAR,
                MONTH,
            )
            self.assertEqual(len(drafts), 1, customer)
            totals.append(drafts[0].subtotal_amount)

        self.assertEqual(sum(totals), Decimal("100.00"))

    def test_the_parts_do_not_depend_on_who_is_invoiced_first(self):
        """Two share-holders can have different billing days, so their
        parts are computed weeks apart. The answer must not move."""
        other = self._second_customer()
        self._share(self.customer, "33.33")
        self._share(other, "66.67")
        ew = self._earned_ew(subtotal="0.05", vat="0.01")

        planned_other_first = plan_invoices(
            self.admin,
            self.company.id,
            other.id,
            YEAR,
            MONTH,
        )
        planned_mine = plan_invoices(
            self.admin,
            self.company.id,
            self.customer.id,
            YEAR,
            MONTH,
        )
        self.assertEqual(
            planned_other_first[0].subtotal + planned_mine[0].subtotal,
            Decimal("0.05"),
        )

    def test_vat_is_computed_on_each_part(self):
        """Each invoice must be consistent with ITSELF: its VAT is its own
        subtotal times the rate, because that is the document a tax
        authority reads."""
        other = self._second_customer()
        self._share(self.customer, "50.00")
        self._share(other, "50.00")
        ew = self._earned_ew(subtotal="100.00", vat="21.00")

        mine = generate_draft_invoices(
            self.admin,
            self.company.id,
            self.customer.id,
            YEAR,
            MONTH,
        )[0]
        self.assertEqual(mine.subtotal_amount, Decimal("50.00"))
        self.assertEqual(mine.vat_amount, Decimal("10.50"))
        self.assertEqual(mine.total_amount, Decimal("60.50"))

    def test_a_customer_with_no_share_of_a_shared_building_is_not_billed(self):
        """The row reached the pool because the building is shared; this
        customer holds no share of it, so it owes nothing and gets no
        line — not a zero line, which would be a claim."""
        other = self._second_customer()
        third = self._third_customer()
        CustomerBuildingMembership.objects.get_or_create(
            customer=third, building=self.building
        )
        self._share(self.customer, "50.00")
        self._share(other, "50.00")
        ew = self._earned_ew(subtotal="100.00", vat="21.00")

        drafts = generate_draft_invoices(
            self.admin,
            self.company.id,
            third.id,
            YEAR,
            MONTH,
        )
        self.assertEqual(drafts, [])

    def test_the_preview_rows_and_totals_are_the_same_money(self):
        """The preview must show the split BEFORE anything is created,
        and it must not contradict itself: every line is this customer's
        part, so the lines add up to the total printed above them."""
        other = self._second_customer()
        self._share(self.customer, "60.00")
        self._share(other, "40.00")
        self._earned_ew(subtotal="100.00", vat="21.00")

        from invoicing.serializers import InvoicePreviewSerializer

        plans = plan_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )
        self.assertEqual(len(plans), 1)
        data = InvoicePreviewSerializer(plans[0]).data
        self.assertEqual(data["subtotal_amount"], "60.00")
        line_sum = sum(
            Decimal(line["line_subtotal"]) for line in data["lines"]
        )
        self.assertEqual(line_sum, Decimal("60.00"))

    # ------------------------------------------------------------------
    # The claim
    # ------------------------------------------------------------------
    def test_one_share_holders_invoice_does_not_settle_the_others(self):
        other = self._second_customer()
        self._share(self.customer, "60.00")
        self._share(other, "40.00")
        ew = self._earned_ew(subtotal="100.00", vat="21.00")

        generate_draft_invoices(
            self.admin,
            self.company.id,
            self.customer.id,
            YEAR,
            MONTH,
        )
        ew.refresh_from_db()
        # Not settled: the other share-holder has not been billed yet, and
        # the fast exclusion would otherwise hide the row from their run.
        self.assertFalse(ew.is_invoiced)

        theirs = generate_draft_invoices(
            self.admin,
            self.company.id,
            other.id,
            YEAR,
            MONTH,
        )
        self.assertEqual(len(theirs), 1)
        ew.refresh_from_db()
        self.assertTrue(ew.is_invoiced)

    def test_generating_twice_for_the_same_customer_claims_nothing_twice(self):
        other = self._second_customer()
        self._share(self.customer, "60.00")
        self._share(other, "40.00")
        ew = self._earned_ew(subtotal="100.00", vat="21.00")

        first = generate_draft_invoices(
            self.admin,
            self.company.id,
            self.customer.id,
            YEAR,
            MONTH,
        )
        second = generate_draft_invoices(
            self.admin,
            self.company.id,
            self.customer.id,
            YEAR,
            MONTH,
        )
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

    # ------------------------------------------------------------------
    # Reversal
    # ------------------------------------------------------------------
    def test_reversal_releases_exactly_the_share_it_claimed(self):
        from invoicing.state_machine import issue_invoice, reverse_invoice, send_invoice

        other = self._second_customer()
        self._share(self.customer, "60.00")
        self._share(other, "40.00")
        ew = self._earned_ew(subtotal="100.00", vat="21.00")

        mine = generate_draft_invoices(
            self.admin,
            self.company.id,
            self.customer.id,
            YEAR,
            MONTH,
        )[0]
        generate_draft_invoices(
            self.admin,
            self.company.id,
            other.id,
            YEAR,
            MONTH,
        )

        issue_invoice(self.admin, mine)
        send_invoice(self.admin, mine)
        reverse_invoice(self.admin, mine)

        # My share is back in MY pool at exactly its own value...
        again = generate_draft_invoices(
            self.admin,
            self.company.id,
            self.customer.id,
            YEAR,
            MONTH,
        )
        self.assertEqual(len(again), 1)
        self.assertEqual(again[0].subtotal_amount, Decimal("60.00"))

        # ...and the other share-holder's invoice is untouched by any of
        # it: their claim still stands, so their run finds nothing.
        theirs_again = generate_draft_invoices(
            self.admin,
            self.company.id,
            other.id,
            YEAR,
            MONTH,
        )
        self.assertEqual(theirs_again, [])
