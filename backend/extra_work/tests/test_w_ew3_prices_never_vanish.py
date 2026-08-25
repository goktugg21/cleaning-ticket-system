"""
W-EW3 §3 — the money on the create screen never contradicts itself.

The owner photographed the create page showing PRICE SOURCE / UNIT
PRICE / VAT headers over lines with no money in them. W-EW2 had already
stopped ONE unfinished row from blanking its neighbours, and it did not
close the report. Two ways to reach that screen survived, and this
module pins the endpoint contract the fixed page leans on for each.

  1. THE CART'S DATE PICKS THE PRICE WINDOW.
     `ExtraWorkPreviewSerializer.validate` stamps every line with the
     cart's `preferred_date` (today when absent) and prices on it. The
     page's combobox used to filter the customer's agreed prices on
     TODAY regardless, so asking for work on a day outside a price's
     window offered "EUR 48.50 / Hours" in the picker and then answered
     "Needs provider pricing" in the table. The picker now filters on
     the cart date instead — which is only correct while the endpoint
     really does price on that same day, so that is pinned here.

  2. A QUANTITY IS NOT A PRICE.
     The page keeps rendering a line's unit price and VAT while its
     quantity field is empty mid-edit, falling back to the customer's
     own agreed-price row for the numbers. That fallback is only sound
     while the unit price and VAT a line is quoted at do not depend on
     its quantity, and while the agreed price this endpoint returns is
     the SAME number `GET /customers/<id>/pricing/` hands the picker.
     Both are pinned here.

If any of this stops being true, the page starts promising prices the
server will not honour — quietly, because both halves still return 200.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase

from ..models import CustomerServicePrice
from .test_sprint5_extra_work_preview import (
    PREVIEW_URL,
    Sprint5PreviewFixtureMixin,
)

# The fixture's agreed price: EUR 48.50 @ 21%, valid from 2026-05-02
# (2026-06-01 minus 30 days) with no end.
AGREED_UNIT = "48.50"
AGREED_VAT = "21.00"
FIXTURE_VALID_FROM = date(2026, 6, 1) - timedelta(days=30)


class CartDatePicksThePriceWindowTests(
    Sprint5PreviewFixtureMixin, TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _preview(self, *, preferred_date=None, service=None):
        body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[self._line(service=service or self.svc_agreed.id)],
        )
        if preferred_date is not None:
            body["preferred_date"] = preferred_date
        resp = self._api(self.cust_user_a).post(
            PREVIEW_URL, body, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data["lines"][0]

    def test_a_cart_date_inside_the_window_is_agreed(self):
        line = self._preview(
            preferred_date=(FIXTURE_VALID_FROM + timedelta(days=5)).isoformat()
        )
        self.assertEqual(line["price_source"], "AGREED_CUSTOMER_PRICE")
        self.assertEqual(line["agreed_unit_price"], AGREED_UNIT)
        self.assertEqual(line["agreed_vat_pct"], AGREED_VAT)

    def test_a_cart_date_before_valid_from_needs_provider_pricing(self):
        """The screen the picker used to contradict: the price exists,
        just not on the day the work is asked for."""
        line = self._preview(
            preferred_date=(FIXTURE_VALID_FROM - timedelta(days=1)).isoformat()
        )
        self.assertEqual(line["price_source"], "NEEDS_PROVIDER_PRICING")
        self.assertIsNone(line["agreed_unit_price"])
        self.assertIsNone(line["agreed_vat_pct"])

    def test_a_cart_date_after_valid_to_needs_provider_pricing(self):
        expired = CustomerServicePrice.objects.create(
            service=self.svc_needs,
            customer=self.customer_a,
            unit_price=Decimal("12.00"),
            vat_pct=Decimal("9.00"),
            valid_from=FIXTURE_VALID_FROM,
            valid_to=FIXTURE_VALID_FROM + timedelta(days=10),
            is_active=True,
        )
        inside = self._preview(
            preferred_date=expired.valid_to.isoformat(),
            service=self.svc_needs.id,
        )
        self.assertEqual(inside["price_source"], "AGREED_CUSTOMER_PRICE")
        self.assertEqual(inside["agreed_unit_price"], "12.00")

        outside = self._preview(
            preferred_date=(
                expired.valid_to + timedelta(days=1)
            ).isoformat(),
            service=self.svc_needs.id,
        )
        self.assertEqual(outside["price_source"], "NEEDS_PROVIDER_PRICING")
        self.assertIsNone(outside["agreed_unit_price"])

    def test_no_cart_date_prices_on_today(self):
        """The page falls back to today when the field is empty, and so
        must the endpoint — otherwise the two disagree on an ordinary
        cart with no date typed at all."""
        line = self._preview()
        self.assertEqual(line["price_source"], "AGREED_CUSTOMER_PRICE")
        self.assertEqual(line["agreed_unit_price"], AGREED_UNIT)


class OverlappingPriceRowsTests(Sprint5PreviewFixtureMixin, TestCase):
    """`resolve_price` picks the row with the LATEST `valid_from` on or
    before the date, tie-broken by the highest id. Overlapping active
    rows are ordinary — that is how a price rise is entered — and the
    page now mirrors this rule to decide which contract to quote while
    a preview is in flight. Two implementations of one rule only stay
    equal if the rule is written down, so it is written down here."""

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _preview(self, *, preferred_date=None):
        body = self._body(
            customer=self.customer_a,
            building=self.building_a1,
            lines=[self._line(service=self.svc_agreed.id)],
        )
        if preferred_date is not None:
            body["preferred_date"] = preferred_date
        resp = self._api(self.cust_user_a).post(
            PREVIEW_URL, body, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data["lines"][0]

    def test_the_later_valid_from_wins(self):
        """A raise entered on top of the standing contract."""
        raise_from = FIXTURE_VALID_FROM + timedelta(days=10)
        CustomerServicePrice.objects.create(
            service=self.svc_agreed,
            customer=self.customer_a,
            unit_price=Decimal("60.00"),
            vat_pct=Decimal("21.00"),
            valid_from=raise_from,
            valid_to=None,
            is_active=True,
        )
        before = self._preview(
            preferred_date=(raise_from - timedelta(days=1)).isoformat()
        )
        self.assertEqual(before["agreed_unit_price"], AGREED_UNIT)

        after = self._preview(preferred_date=raise_from.isoformat())
        self.assertEqual(after["agreed_unit_price"], "60.00")

    def test_same_valid_from_the_highest_id_wins(self):
        """A correction entered the same day as the row it replaces."""
        newer = CustomerServicePrice.objects.create(
            service=self.svc_agreed,
            customer=self.customer_a,
            unit_price=Decimal("55.00"),
            vat_pct=Decimal("21.00"),
            valid_from=FIXTURE_VALID_FROM,
            valid_to=None,
            is_active=True,
        )
        self.assertGreater(newer.id, self.csp_agreed.id)
        line = self._preview()
        self.assertEqual(line["agreed_unit_price"], "55.00")


class QuantityIsNotAPriceTests(Sprint5PreviewFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _preview_lines(self, lines, *, user=None):
        resp = self._api(user or self.cust_user_a).post(
            PREVIEW_URL,
            self._body(
                customer=self.customer_a,
                building=self.building_a1,
                lines=lines,
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data["lines"]

    def test_the_unit_price_and_vat_do_not_move_with_the_quantity(self):
        """The page renders an agreed line's unit price and VAT through
        a quantity edit, because they are a property of the AGREEMENT.
        This is the endpoint half of that claim."""
        for quantity in ("1.00", "3.00", "0.50", "999.99"):
            with self.subTest(quantity=quantity):
                line = self._preview_lines(
                    [self._line(service=self.svc_agreed.id, quantity=quantity)]
                )[0]
                self.assertEqual(line["price_source"], "AGREED_CUSTOMER_PRICE")
                self.assertEqual(line["agreed_unit_price"], AGREED_UNIT)
                self.assertEqual(line["agreed_vat_pct"], AGREED_VAT)
                self.assertEqual(line["quantity"], quantity)

    def test_a_dropped_neighbour_does_not_move_this_line_s_price(self):
        """A line whose quantity is being retyped leaves the request
        entirely (the page cannot send quantity=0). The lines that DID
        go must come back priced exactly as they were when the dropped
        one was still there."""
        both = self._preview_lines(
            [
                self._line(service=self.svc_agreed.id, quantity="2.00"),
                self._line(custom_description="Paint the hallway"),
            ]
        )
        self.assertEqual(both[0]["agreed_unit_price"], AGREED_UNIT)

        alone = self._preview_lines(
            [self._line(service=self.svc_agreed.id, quantity="2.00")]
        )
        self.assertEqual(alone[0]["agreed_unit_price"], AGREED_UNIT)
        self.assertEqual(alone[0]["agreed_vat_pct"], AGREED_VAT)
        self.assertEqual(alone[0]["price_source"], both[0]["price_source"])

    def test_zero_quantity_is_still_refused(self):
        """And the reason the page has to drop such a line at all: the
        endpoint will not price one. Pinned so the fallback in the page
        is never mistaken for something the server would have answered."""
        resp = self._api(self.cust_user_a).post(
            PREVIEW_URL,
            self._body(
                customer=self.customer_a,
                building=self.building_a1,
                lines=[
                    self._line(service=self.svc_agreed.id, quantity="0.00")
                ],
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)


class PickerAndPreviewQuoteTheSameNumberTests(
    Sprint5PreviewFixtureMixin, TestCase
):
    """The page falls back to the customer's own price list when the
    preview has no row for a line yet. That is only honest while the two
    endpoints quote the same money."""

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_pricing_list_and_preview_agree_on_the_amount(self):
        listing = self._api(self.cust_user_a).get(
            f"/api/customers/{self.customer_a.id}/pricing/"
        )
        self.assertEqual(listing.status_code, 200, listing.data)
        rows = {
            row["service"]: row for row in listing.data["results"]
        }
        self.assertIn(self.svc_agreed.id, rows)
        row = rows[self.svc_agreed.id]

        line = self._api(self.cust_user_a).post(
            PREVIEW_URL,
            self._body(
                customer=self.customer_a,
                building=self.building_a1,
                lines=[self._line(service=self.svc_agreed.id)],
            ),
            format="json",
        ).data["lines"][0]

        self.assertEqual(
            Decimal(row["unit_price"]), Decimal(line["agreed_unit_price"])
        )
        self.assertEqual(
            Decimal(row["vat_pct"]), Decimal(line["agreed_vat_pct"])
        )
