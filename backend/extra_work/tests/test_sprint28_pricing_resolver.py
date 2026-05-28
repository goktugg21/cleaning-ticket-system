"""
Sprint 28 Batch 5 — pricing resolver tests
(`extra_work.pricing.resolve_price`).

The resolver semantics are locked by the master plan §5 rule #9 and
the 2026-05-15 decision log: it returns a `CustomerServicePrice`
row when an ACTIVE row exists for `(service, customer)` on the
given date, and `None` otherwise. It MUST NOT fall back to
`Service.default_unit_price` — that field is a catalog-UI reference,
not a trigger for the instant-ticket path.

Coverage matrix:

  * Happy path — active row returned; absent row → None; date filter
    selects the right historical row.
  * The "no contract → None" rule even when the Service carries a
    non-zero `default_unit_price`. This is the master-plan rule lock.
  * Multiple active rows — latest `valid_from` wins, ties broken by
    `id desc`.
  * Inactive / expired rows are correctly excluded.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase

from extra_work.models import (
    CustomerServicePrice,
    ExtraWorkPricingUnitType,
    Service,
    ServiceCategory,
)
from extra_work.pricing import resolve_price
from test_utils import TenantFixtureMixin


class PricingResolverFixtureMixin(TenantFixtureMixin):
    """Tenant fixture + a single ServiceCategory / Service so every
    resolver test starts with the same catalog scaffold."""

    def setUp(self):
        super().setUp()
        self.category = ServiceCategory.objects.create(name="Cleaning")
        self.service = Service.objects.create(
            category=self.category,
            name="Window cleaning",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("45.00"),
        )


class ResolvePriceHappyPathTests(PricingResolverFixtureMixin, TestCase):
    def test_active_row_returns_the_row(self):
        row = CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("38.50"),
            valid_from=date(2026, 1, 1),
        )
        result = resolve_price(
            self.service, self.customer, on=date(2026, 5, 16)
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.id, row.id)
        self.assertEqual(result.unit_price, Decimal("38.50"))

    def test_no_row_returns_none(self):
        # No CustomerServicePrice exists at all.
        result = resolve_price(
            self.service, self.customer, on=date(2026, 5, 16)
        )
        self.assertIsNone(result)

    def test_on_parameter_selects_correct_historical_row(self):
        # An older row that expired before `on`, and a newer one that
        # is current. Resolver must pick the current one.
        CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("30.00"),
            valid_from=date(2025, 1, 1),
            valid_to=date(2025, 12, 31),
        )
        new_row = CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("40.00"),
            valid_from=date(2026, 1, 1),
        )
        result = resolve_price(
            self.service, self.customer, on=date(2026, 6, 1)
        )
        self.assertEqual(result.id, new_row.id)

        # Asking for a date inside the old window picks the old row.
        result_old = resolve_price(
            self.service, self.customer, on=date(2025, 6, 1)
        )
        self.assertEqual(result_old.unit_price, Decimal("30.00"))

    def test_on_defaults_to_today(self):
        # An always-on row from a year ago — `today` falls inside it.
        row = CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("12.34"),
            valid_from=date.today() - timedelta(days=365),
        )
        result = resolve_price(self.service, self.customer)
        self.assertIsNotNone(result)
        self.assertEqual(result.id, row.id)


class ResolvePriceReturnsNoneWithoutCustomerSpecificTests(
    PricingResolverFixtureMixin, TestCase
):
    """The master-plan rule #9 lock: the global `Service.default_unit_price`
    NEVER triggers the instant-ticket path. The resolver returns None
    whenever there is no active customer-specific row, regardless of
    the catalog default."""

    def test_no_fallback_to_default_unit_price(self):
        # Service has a non-zero default; but no CustomerServicePrice
        # row exists for this customer.
        self.assertEqual(self.service.default_unit_price, Decimal("45.00"))
        result = resolve_price(
            self.service, self.customer, on=date(2026, 5, 16)
        )
        self.assertIsNone(result)

    def test_other_customer_has_price_does_not_leak(self):
        # A different customer DOES have a row, but the queried
        # customer does not. The resolver must still return None
        # for the queried customer — never another customer's row.
        CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.other_customer,
            unit_price=Decimal("99.99"),
            valid_from=date(2026, 1, 1),
        )
        result = resolve_price(
            self.service, self.customer, on=date(2026, 5, 16)
        )
        self.assertIsNone(result)


class ResolvePriceMultipleActiveTests(
    PricingResolverFixtureMixin, TestCase
):
    def test_latest_valid_from_wins(self):
        # Two open-ended rows. Newer valid_from must win.
        CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("10.00"),
            valid_from=date(2025, 1, 1),
        )
        newer = CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("20.00"),
            valid_from=date(2026, 1, 1),
        )
        result = resolve_price(
            self.service, self.customer, on=date(2026, 5, 16)
        )
        self.assertEqual(result.id, newer.id)
        self.assertEqual(result.unit_price, Decimal("20.00"))

    def test_same_valid_from_breaks_tie_by_id_desc(self):
        first = CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("11.11"),
            valid_from=date(2026, 1, 1),
        )
        second = CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("22.22"),
            valid_from=date(2026, 1, 1),
        )
        # Sanity: the second row has the higher id.
        self.assertGreater(second.id, first.id)
        result = resolve_price(
            self.service, self.customer, on=date(2026, 5, 16)
        )
        self.assertEqual(result.id, second.id)


class ResolvePriceInactiveAndExpiredTests(
    PricingResolverFixtureMixin, TestCase
):
    def test_is_active_false_excluded(self):
        CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("50.00"),
            valid_from=date(2026, 1, 1),
            is_active=False,
        )
        result = resolve_price(
            self.service, self.customer, on=date(2026, 5, 16)
        )
        self.assertIsNone(result)

    def test_valid_to_before_on_excluded(self):
        CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("50.00"),
            valid_from=date(2025, 1, 1),
            valid_to=date(2025, 12, 31),
        )
        result = resolve_price(
            self.service, self.customer, on=date(2026, 5, 16)
        )
        self.assertIsNone(result)

    def test_valid_from_after_on_excluded(self):
        # Row's window starts in the future relative to `on`.
        CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("50.00"),
            valid_from=date(2027, 1, 1),
        )
        result = resolve_price(
            self.service, self.customer, on=date(2026, 5, 16)
        )
        self.assertIsNone(result)

    def test_valid_to_equal_to_on_is_included(self):
        # Boundary: valid_to == on should still match (inclusive).
        row = CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("19.99"),
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 5, 16),
        )
        result = resolve_price(
            self.service, self.customer, on=date(2026, 5, 16)
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.id, row.id)

    def test_valid_from_equal_to_on_is_included(self):
        row = CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("19.99"),
            valid_from=date(2026, 5, 16),
        )
        result = resolve_price(
            self.service, self.customer, on=date(2026, 5, 16)
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.id, row.id)

    def test_mix_inactive_and_active_picks_active(self):
        # Newer row is inactive; older row is active. Resolver must
        # ignore the inactive one and return the older active one.
        CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("50.00"),
            valid_from=date(2026, 3, 1),
            is_active=False,
        )
        older_active = CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("33.33"),
            valid_from=date(2026, 1, 1),
            is_active=True,
        )
        result = resolve_price(
            self.service, self.customer, on=date(2026, 5, 16)
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.id, older_active.id)
