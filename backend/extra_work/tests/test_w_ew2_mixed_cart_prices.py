"""
W-EW2 §3 — an agreed price resolves whatever else is in the cart.

The owner photographed a create screen where every line read "—" and
"to be priced by the provider", including a service whose agreed price
(€31.48) was visible in the card immediately above the table. The
trigger was adding a custom line first.

The cause turned out to be in the page, not here: `previewable` was a
whole-cart gate, so one unfinished row nulled the whole preview and the
render printed dashes for every row. This module pins the half of the
contract the fixed page now leans on — that this endpoint prices each
line on its own merits:

  * an AGREED line stays AGREED next to an AD_HOC one,
  * in EITHER order,
  * and the answer is positional, one row out per row in, so the page
    can pair them up.

If any of that ever stops being true, the page's per-line pairing
breaks silently and the dashes come back. Hence the test.
"""
from __future__ import annotations

from django.test import TestCase

from .test_sprint5_extra_work_preview import (
    PREVIEW_URL,
    Sprint5PreviewFixtureMixin,
)


class MixedCartAgreedPriceTests(Sprint5PreviewFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _preview(self, lines, *, user=None, request_intent=None):
        resp = self._api(user or self.cust_user_a).post(
            PREVIEW_URL,
            self._body(
                customer=self.customer_a,
                building=self.building_a1,
                lines=lines,
                request_intent=request_intent,
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data

    def _assert_agreed(self, line):
        self.assertEqual(line["price_source"], "AGREED_CUSTOMER_PRICE")
        self.assertEqual(line["agreed_unit_price"], "48.50")
        self.assertEqual(line["agreed_vat_pct"], "21.00")

    def _assert_ad_hoc(self, line):
        self.assertEqual(line["price_source"], "AD_HOC")
        self.assertIsNone(line["agreed_unit_price"])

    def test_agreed_alone_is_priced(self):
        """The baseline the other cases are compared against."""
        data = self._preview([self._line(service=self.svc_agreed.id)])
        self.assertEqual(len(data["lines"]), 1)
        self._assert_agreed(data["lines"][0])

    def test_custom_first_then_agreed(self):
        """The owner's exact order: the custom line goes in first."""
        data = self._preview(
            [
                self._line(custom_description="Paint the hallway"),
                self._line(service=self.svc_agreed.id),
            ]
        )
        self.assertEqual(len(data["lines"]), 2)
        self._assert_ad_hoc(data["lines"][0])
        self._assert_agreed(data["lines"][1])

    def test_agreed_first_then_custom(self):
        """And the other order, so the guarantee is order-free."""
        data = self._preview(
            [
                self._line(service=self.svc_agreed.id),
                self._line(custom_description="Paint the hallway"),
            ]
        )
        self.assertEqual(len(data["lines"]), 2)
        self._assert_agreed(data["lines"][0])
        self._assert_ad_hoc(data["lines"][1])

    def test_agreed_survives_a_custom_line_on_both_sides(self):
        """Three lines, the agreed one in the middle. The page pairs
        rows to answers BY POSITION, so the position of the agreed
        answer matters as much as its value."""
        data = self._preview(
            [
                self._line(custom_description="Paint the hallway"),
                self._line(service=self.svc_agreed.id),
                self._line(custom_description="Clear the gutters"),
            ]
        )
        self.assertEqual(len(data["lines"]), 3)
        self.assertEqual([row["index"] for row in data["lines"]], [0, 1, 2])
        self._assert_ad_hoc(data["lines"][0])
        self._assert_agreed(data["lines"][1])
        self._assert_ad_hoc(data["lines"][2])

    def test_agreed_price_survives_the_intent_the_mixed_cart_forces(self):
        """A cart with an ad-hoc line leaves a customer only
        REQUEST_QUOTE, and the page re-fetches the preview with that
        intent attached. Sending it must not turn the agreed line into
        an unpriced one — pricing is a property of the line, the intent
        is a property of the cart."""
        data = self._preview(
            [
                self._line(custom_description="Paint the hallway"),
                self._line(service=self.svc_agreed.id),
            ],
            request_intent="REQUEST_QUOTE",
        )
        self.assertEqual(
            [str(i) for i in data["allowed_intents"]], ["REQUEST_QUOTE"]
        )
        self._assert_agreed(data["lines"][1])

    def test_one_row_out_per_row_in(self):
        """The pairing the page does is only sound while the endpoint
        answers one line per line, in order. Pinned explicitly."""
        for count in (1, 2, 5):
            with self.subTest(count=count):
                data = self._preview(
                    [self._line(service=self.svc_agreed.id)]
                    + [
                        self._line(custom_description=f"Extra {n}")
                        for n in range(count - 1)
                    ]
                )
                self.assertEqual(len(data["lines"]), count)
                self.assertEqual(
                    [row["index"] for row in data["lines"]],
                    list(range(count)),
                )
                self._assert_agreed(data["lines"][0])
