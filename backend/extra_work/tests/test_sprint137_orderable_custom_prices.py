"""
Sprint 137 item 6 — `CustomerCustomPrice` rows are orderable.

The reported defect, in the owner's words: he added his customer's real
work types through the custom-price path and was then baffled they never
appeared when creating an Extra Work request. They could not: a
`CustomerCustomPrice` deliberately has NO `service` FK, and every cart
line was `service` XOR `custom_description`, so a custom price had no way
into a cart at all. Three things sat in one table on the pricing page
looking identical, and exactly one of them was unorderable.

What item 6 adds: a third mutually-exclusive way to describe a cart line,
`custom_price`. The backend snapshots the row's name / unit / amount onto
the line the same way a catalog line snapshots its contract row, and
records the source row in the new
`ExtraWorkRequestItem.snapshot_customer_custom_price` FK (SET_NULL —
archiving a price must never delete operational history).

What item 6 deliberately does NOT change — the load-bearing decision:

    A custom-price line still classifies as AD_HOC, so the cart still
    routes PROPOSAL and `all_agreed` is unaffected.

That is not timidity, it is the only correct answer given the code.
"INSTANT" has a hard contract enforced at spawn time:
`instant_tickets.spawn_instant_ticket` re-resolves EVERY line through
`resolve_price(item.service, customer, ...)` and aborts the whole
submission with `instant_spawn_price_lost` when any line fails to
resolve. `resolve_price` only ever returns a `CustomerServicePrice`, and
a custom price has no `service` to resolve, so a custom-price line
classified as "agreed" would route INSTANT and then be rejected by the
spawn guard — turning a working order into a hard failure. Keeping the
line AD_HOC means the provider confirms it in the pricing step, but now
with the agreed amount already filled in instead of retyped.

Covered here:
  * a custom-price line persists with the snapshot + FK + unit type
  * routing stays PROPOSAL and the line source stays AD_HOC
  * tenant scoping: another customer's price row is rejected (H-1/H-2)
  * an archived / out-of-window price row is not orderable
  * the three line kinds stay mutually exclusive
  * the preview returns the known amount without lying about the source
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.test import TestCase

from extra_work.models import (
    CustomerCustomPrice,
    ExtraWorkLinePriceSource,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkRoutingDecision,
)

from .test_sprint28_cart_request import CartFixtureMixin


URL = "/api/extra-work/"
PREVIEW_URL = "/api/extra-work/preview/"


class OrderableCustomPriceFixtureMixin(CartFixtureMixin):
    """CartFixtureMixin + a set of custom price rows on customer_a."""

    @classmethod
    def _setup_custom_prices(cls):
        cls.custom_price = CustomerCustomPrice.objects.create(
            customer=cls.customer_a,
            custom_name="Graffiti removal",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            unit_price=Decimal("250.00"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            valid_to=None,
            is_active=True,
        )
        cls.custom_price_archived = CustomerCustomPrice.objects.create(
            customer=cls.customer_a,
            custom_name="Retired one-off",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            unit_price=Decimal("99.00"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            is_active=False,
        )
        cls.custom_price_expired = CustomerCustomPrice.objects.create(
            customer=cls.customer_a,
            custom_name="Winter surcharge",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            unit_price=Decimal("12.00"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 3, 1),
            is_active=True,
        )
        # Belongs to a DIFFERENT customer under the same provider — the
        # tenant-scoping case that matters most here.
        cls.custom_price_foreign = CustomerCustomPrice.objects.create(
            customer=cls.customer_a_alt,
            custom_name="Not yours",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            unit_price=Decimal("500.00"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            is_active=True,
        )

    def _custom_line(self, custom_price=None, **extra):
        # W-EW1 §2 — no per-line date. The window a custom price is
        # checked against comes from the cart's `preferred_date`, which
        # `_base_payload` sets to 2026-06-15.
        line = {
            "custom_price": (custom_price or self.custom_price).id,
            "quantity": "1.00",
        }
        line.update(extra)
        return line


class CustomPriceOrderingTests(OrderableCustomPriceFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()
        cls._setup_custom_prices()

    def test_custom_price_line_persists_snapshot_and_link(self):
        payload = self._base_payload()
        payload["line_items"] = [self._custom_line()]

        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)

        ew = ExtraWorkRequest.objects.get(pk=response.data["id"])
        item = ExtraWorkRequestItem.objects.get(extra_work_request=ew)

        # No catalog service — that is the whole point of a custom price.
        self.assertIsNone(item.service_id)
        # The durable link back to the row that produced the line.
        self.assertEqual(
            item.snapshot_customer_custom_price_id, self.custom_price.id
        )
        # Name / unit / amount snapshotted exactly as a catalog line's
        # contract price is.
        self.assertEqual(item.custom_description, "Graffiti removal")
        self.assertEqual(item.snapshot_service_name, "Graffiti removal")
        self.assertEqual(item.unit_type, ExtraWorkPricingUnitType.FIXED)
        self.assertEqual(item.snapshot_unit_price, Decimal("250.00"))
        self.assertEqual(item.snapshot_vat_pct, Decimal("21.00"))

    def test_custom_price_line_stays_ad_hoc_and_routes_proposal(self):
        """The load-bearing invariant — see the module docstring."""
        payload = self._base_payload()
        payload["line_items"] = [self._custom_line()]

        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)

        ew = ExtraWorkRequest.objects.get(pk=response.data["id"])
        item = ExtraWorkRequestItem.objects.get(extra_work_request=ew)

        self.assertEqual(
            item.line_price_source, ExtraWorkLinePriceSource.AD_HOC
        )
        self.assertEqual(
            ew.routing_decision, ExtraWorkRoutingDecision.PROPOSAL
        )

    def test_mixed_cart_with_contract_line_still_routes_proposal(self):
        """A contract line alone would route INSTANT; adding a custom
        price line must pull the whole cart back to PROPOSAL rather than
        letting a service-less line reach the instant spawn guard."""
        payload = self._base_payload()
        payload["line_items"] = [
            {
                "service": self.service_priced.id,
                "quantity": "2.00",
            },
            self._custom_line(),
        ]

        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)

        ew = ExtraWorkRequest.objects.get(pk=response.data["id"])
        self.assertEqual(
            ew.routing_decision, ExtraWorkRoutingDecision.PROPOSAL
        )

    def test_archiving_the_price_row_keeps_the_line(self):
        """SET_NULL, not CASCADE: archiving is the normal delete on the
        pricing page (Sprint 137 item 2), and even a hard delete must
        never take operational history with it."""
        payload = self._base_payload()
        payload["line_items"] = [self._custom_line()]
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        item = ExtraWorkRequestItem.objects.get(
            extra_work_request_id=response.data["id"]
        )

        CustomerCustomPrice.objects.filter(pk=self.custom_price.pk).delete()

        item.refresh_from_db()
        self.assertIsNone(item.snapshot_customer_custom_price_id)
        # The amount survives on the snapshot columns.
        self.assertEqual(item.snapshot_unit_price, Decimal("250.00"))
        self.assertEqual(item.snapshot_service_name, "Graffiti removal")


class CustomPriceScopeTests(OrderableCustomPriceFixtureMixin, TestCase):
    """RBAC H-1/H-2 — a custom price is orderable only by the customer
    it belongs to. The serializer field's queryset spans every tenant's
    rows, so without the explicit guard a caller could name another
    customer's price row by id."""

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()
        cls._setup_custom_prices()

    def test_another_customers_price_is_rejected(self):
        payload = self._base_payload()
        payload["line_items"] = [
            self._custom_line(custom_price=self.custom_price_foreign)
        ]

        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(ExtraWorkRequest.objects.count(), 0)

    def test_another_customers_price_is_rejected_on_preview(self):
        """The preview leaks the amount back to the caller, so it needs
        the same guard as create — not just create."""
        response = self._api(self.cust_basic_a).post(
            PREVIEW_URL,
            {
                "customer": self.customer_a.id,
                "building": self.building_a1.id,
                "line_items": [
                    self._custom_line(custom_price=self.custom_price_foreign)
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)


class CustomPriceOrderabilityTests(
    OrderableCustomPriceFixtureMixin, TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()
        cls._setup_custom_prices()

    def test_archived_price_cannot_be_ordered(self):
        payload = self._base_payload()
        payload["line_items"] = [
            self._custom_line(custom_price=self.custom_price_archived)
        ]
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_out_of_window_price_cannot_be_ordered(self):
        payload = self._base_payload()
        payload["line_items"] = [
            self._custom_line(custom_price=self.custom_price_expired)
        ]
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_in_window_price_is_orderable(self):
        """Same row as the expired case, inside its window this time —
        proves the rejection above is the window and not the row."""
        # W-EW1 §2 — the window is chosen by the CART's date now, so
        # this is the same test with the date moved up one level.
        payload = self._base_payload(preferred_date="2026-02-01")
        payload["line_items"] = [
            self._custom_line(custom_price=self.custom_price_expired)
        ]
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)


class CustomPriceLineExclusivityTests(
    OrderableCustomPriceFixtureMixin, TestCase
):
    """A line carries exactly ONE of service / custom_description /
    custom_price. Sprint 2A's XOR became a three-way rule."""

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()
        cls._setup_custom_prices()

    def test_service_and_custom_price_together_rejected(self):
        payload = self._base_payload()
        payload["line_items"] = [
            self._custom_line(service=self.service_priced.id)
        ]
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_custom_description_and_custom_price_together_rejected(self):
        payload = self._base_payload()
        payload["line_items"] = [
            self._custom_line(custom_description="free text")
        ]
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_empty_line_still_rejected(self):
        """Regression guard on the pre-existing none-supplied case."""
        payload = self._base_payload()
        payload["line_items"] = [{"quantity": "1.00"}]
        response = self._api(self.cust_basic_a).post(
            URL, payload, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)


class CustomPricePreviewTests(OrderableCustomPriceFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()
        cls._setup_custom_prices()

    def test_preview_returns_the_known_amount_without_faking_the_source(self):
        response = self._api(self.cust_basic_a).post(
            PREVIEW_URL,
            {
                "customer": self.customer_a.id,
                "building": self.building_a1.id,
                "line_items": [self._custom_line()],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        line = response.data["lines"][0]
        # The source is NOT dressed up as an agreed contract price...
        self.assertEqual(line["price_source"], "AD_HOC")
        self.assertIsNone(line["agreed_unit_price"])
        self.assertIsNone(line["agreed_vat_pct"])
        # ...but the amount we DO know is returned, on its own keys.
        self.assertEqual(line["custom_price"], self.custom_price.id)
        self.assertEqual(line["custom_price_unit_price"], "250.00")
        self.assertEqual(line["custom_price_vat_pct"], "21.00")
        self.assertEqual(line["service_name"], "Graffiti removal")

        # And the cart is still a non-agreed cart for intent purposes.
        self.assertTrue(response.data["cart"]["has_non_agreed"])
        self.assertTrue(response.data["cart"]["has_ad_hoc"])
        self.assertFalse(response.data["cart"]["all_agreed"])

    def test_catalog_line_preview_keys_are_null_for_custom_price(self):
        """A plain catalog line must be byte-identical to pre-137 apart
        from the three new always-null keys."""
        response = self._api(self.cust_basic_a).post(
            PREVIEW_URL,
            {
                "customer": self.customer_a.id,
                "building": self.building_a1.id,
                "preferred_date": "2026-06-15",
                "line_items": [
                    {
                        "service": self.service_priced.id,
                        "quantity": "2.00",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        line = response.data["lines"][0]
        self.assertEqual(line["price_source"], "AGREED_CUSTOMER_PRICE")
        self.assertEqual(line["agreed_unit_price"], "48.50")
        self.assertIsNone(line["custom_price"])
        self.assertIsNone(line["custom_price_unit_price"])
        self.assertIsNone(line["custom_price_vat_pct"])
