"""
M5 C — customer contract-price bulk-raise tests.

`POST /api/customers/<customer_id>/pricing/bulk-raise/` raises a set of
the customer's active `CustomerServicePrice` rows by a percentage or a
fixed amount, writing NEW validity-window rows (history preserved) and
never mutating the source rows.

Coverage matrix:

  * Percent raise — new rows at old*(1+amount/100), HALF_UP to 2dp,
    vat_pct carried over, valid_from = effective date, valid_to null.
  * Fixed raise — new rows at old + amount.
  * History preserved — source rows untouched (is_active + unit_price).
  * Resolver pickup — the raised row resolves from the effective date;
    the old row still resolves before it.
  * Validation (400, zero writes) — empty prices, bad mode, amount<=0
    (code bulk_raise_amount_invalid), missing valid_from, a price id
    from another customer / an inactive id (code bulk_raise_price_invalid),
    and a mixed valid+invalid batch (all-or-nothing).
  * RBAC — CUSTOMER_USER / STAFF 403; CA without the toggle 403; CA
    targeting another company's customer 403/404.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from extra_work.models import (
    CustomerServicePrice,
    ExtraWorkPricingUnitType,
    Service,
    ServiceCategory,
)
from extra_work.pricing import resolve_price
from test_utils import TenantFixtureMixin


def bulk_raise_url(customer_id):
    return f"/api/customers/{customer_id}/pricing/bulk-raise/"


class BulkRaiseFixtureMixin(TenantFixtureMixin):
    def setUp(self):
        super().setUp()
        self.category = ServiceCategory.objects.create(name="Cleaning")
        self.service_a = Service.objects.create(
            category=self.category,
            company=self.company,
            name="Window cleaning",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("45.00"),
        )
        self.service_b = Service.objects.create(
            category=self.category,
            company=self.company,
            name="Floor polishing",
            unit_type=ExtraWorkPricingUnitType.SQUARE_METERS,
            default_unit_price=Decimal("12.50"),
        )
        self.service_c = Service.objects.create(
            category=self.category,
            company=self.company,
            name="Deep clean",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            default_unit_price=Decimal("80.00"),
        )
        self.other_service = Service.objects.create(
            category=self.category,
            company=self.other_company,
            name="Other-company service",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("99.00"),
        )

        # Two active source rows on distinct services; distinct VAT so
        # carry-over is observable. valid_from well before the raise.
        self.price_a = CustomerServicePrice.objects.create(
            service=self.service_a,
            customer=self.customer,
            unit_price=Decimal("100.00"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            is_active=True,
        )
        self.price_b = CustomerServicePrice.objects.create(
            service=self.service_b,
            customer=self.customer,
            unit_price=Decimal("33.33"),
            vat_pct=Decimal("9.00"),
            valid_from=date(2026, 1, 1),
            is_active=True,
        )
        # An inactive row (must be rejected by bulk-raise).
        self.inactive_price = CustomerServicePrice.objects.create(
            service=self.service_c,
            customer=self.customer,
            unit_price=Decimal("50.00"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            is_active=False,
        )
        # A row owned by another customer (must be rejected).
        self.other_price = CustomerServicePrice.objects.create(
            service=self.other_service,
            customer=self.other_customer,
            unit_price=Decimal("70.00"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            is_active=True,
        )


class BulkRaiseMathTests(BulkRaiseFixtureMixin, APITestCase):
    def test_percent_raise_creates_new_rows(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            bulk_raise_url(self.customer.id),
            {
                "prices": [self.price_a.id, self.price_b.id],
                "mode": "percent",
                "amount": "10",
                "valid_from": "2026-07-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["created_count"], 2)
        self.assertEqual(response.data["valid_from"], "2026-07-01")

        # New row on service_a: 100.00 * 1.1 = 110.00, vat carried (21.00).
        new_a = CustomerServicePrice.objects.get(
            service=self.service_a,
            customer=self.customer,
            valid_from=date(2026, 7, 1),
        )
        self.assertEqual(new_a.unit_price, Decimal("110.00"))
        self.assertEqual(new_a.vat_pct, Decimal("21.00"))
        self.assertIsNone(new_a.valid_to)
        self.assertTrue(new_a.is_active)

        # New row on service_b: 33.33 * 1.1 = 36.663 -> HALF_UP 36.66,
        # vat carried over from the source (9.00, not the 21.00 default).
        new_b = CustomerServicePrice.objects.get(
            service=self.service_b,
            customer=self.customer,
            valid_from=date(2026, 7, 1),
        )
        self.assertEqual(new_b.unit_price, Decimal("36.66"))
        self.assertEqual(new_b.vat_pct, Decimal("9.00"))
        self.assertIsNone(new_b.valid_to)
        self.assertTrue(new_b.is_active)

    def test_fixed_raise_creates_new_rows(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            bulk_raise_url(self.customer.id),
            {
                "prices": [self.price_a.id, self.price_b.id],
                "mode": "fixed",
                "amount": "5.00",
                "valid_from": "2026-07-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["created_count"], 2)

        new_a = CustomerServicePrice.objects.get(
            service=self.service_a,
            customer=self.customer,
            valid_from=date(2026, 7, 1),
        )
        self.assertEqual(new_a.unit_price, Decimal("105.00"))
        new_b = CustomerServicePrice.objects.get(
            service=self.service_b,
            customer=self.customer,
            valid_from=date(2026, 7, 1),
        )
        self.assertEqual(new_b.unit_price, Decimal("38.33"))

    def test_source_rows_are_not_mutated(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            bulk_raise_url(self.customer.id),
            {
                "prices": [self.price_a.id, self.price_b.id],
                "mode": "percent",
                "amount": "10",
                "valid_from": "2026-07-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.price_a.refresh_from_db()
        self.price_b.refresh_from_db()
        self.assertEqual(self.price_a.unit_price, Decimal("100.00"))
        self.assertTrue(self.price_a.is_active)
        self.assertEqual(self.price_a.valid_from, date(2026, 1, 1))
        self.assertEqual(self.price_b.unit_price, Decimal("33.33"))
        self.assertTrue(self.price_b.is_active)

    def test_resolver_picks_raised_row_from_effective_date(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            bulk_raise_url(self.customer.id),
            {
                "prices": [self.price_a.id],
                "mode": "percent",
                "amount": "10",
                "valid_from": "2026-07-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # On/after the effective date -> the raised row.
        on_after = resolve_price(
            self.service_a, self.customer, on=date(2026, 7, 1)
        )
        self.assertIsNotNone(on_after)
        self.assertEqual(on_after.unit_price, Decimal("110.00"))
        self.assertEqual(on_after.valid_from, date(2026, 7, 1))

        # Before the effective date -> the original row still wins.
        before = resolve_price(
            self.service_a, self.customer, on=date(2026, 6, 1)
        )
        self.assertIsNotNone(before)
        self.assertEqual(before.id, self.price_a.id)
        self.assertEqual(before.unit_price, Decimal("100.00"))


class BulkRaiseValidationTests(BulkRaiseFixtureMixin, APITestCase):
    def _count_for_customer(self):
        return CustomerServicePrice.objects.filter(
            customer=self.customer
        ).count()

    def test_empty_prices_rejected(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            bulk_raise_url(self.customer.id),
            {
                "prices": [],
                "mode": "percent",
                "amount": "10",
                "valid_from": "2026-07-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("prices", response.data)

    def test_invalid_mode_rejected(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            bulk_raise_url(self.customer.id),
            {
                "prices": [self.price_a.id],
                "mode": "multiply",
                "amount": "10",
                "valid_from": "2026-07-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("mode", response.data)

    def test_zero_amount_rejected(self):
        self.authenticate(self.super_admin)
        before = self._count_for_customer()
        response = self.client.post(
            bulk_raise_url(self.customer.id),
            {
                "prices": [self.price_a.id],
                "mode": "percent",
                "amount": "0",
                "valid_from": "2026-07-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("amount", response.data)
        self.assertEqual(self._count_for_customer(), before)

    def test_negative_amount_rejected(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            bulk_raise_url(self.customer.id),
            {
                "prices": [self.price_a.id],
                "mode": "fixed",
                "amount": "-5.00",
                "valid_from": "2026-07-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        codes = [
            getattr(err, "code", None)
            for err in response.data.get("amount", [])
        ]
        self.assertIn("bulk_raise_amount_invalid", codes)

    def test_missing_valid_from_rejected(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            bulk_raise_url(self.customer.id),
            {
                "prices": [self.price_a.id],
                "mode": "percent",
                "amount": "10",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("valid_from", response.data)

    def test_other_customer_price_rejected_with_no_writes(self):
        self.authenticate(self.super_admin)
        before = self._count_for_customer()
        response = self.client.post(
            bulk_raise_url(self.customer.id),
            {
                "prices": [self.other_price.id],
                "mode": "percent",
                "amount": "10",
                "valid_from": "2026-07-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        codes = [
            getattr(err, "code", None)
            for err in response.data.get("prices", [])
        ]
        self.assertIn("bulk_raise_price_invalid", codes)
        self.assertEqual(self._count_for_customer(), before)

    def test_inactive_price_rejected_with_no_writes(self):
        self.authenticate(self.super_admin)
        before = self._count_for_customer()
        response = self.client.post(
            bulk_raise_url(self.customer.id),
            {
                "prices": [self.inactive_price.id],
                "mode": "percent",
                "amount": "10",
                "valid_from": "2026-07-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        codes = [
            getattr(err, "code", None)
            for err in response.data.get("prices", [])
        ]
        self.assertIn("bulk_raise_price_invalid", codes)
        self.assertEqual(self._count_for_customer(), before)

    def test_mixed_valid_and_invalid_is_all_or_nothing(self):
        self.authenticate(self.super_admin)
        before = self._count_for_customer()
        response = self.client.post(
            bulk_raise_url(self.customer.id),
            {
                # First id is valid, second belongs to another customer.
                "prices": [self.price_a.id, self.other_price.id],
                "mode": "percent",
                "amount": "10",
                "valid_from": "2026-07-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Zero new rows: the valid id must NOT have been raised.
        self.assertEqual(self._count_for_customer(), before)
        self.assertFalse(
            CustomerServicePrice.objects.filter(
                service=self.service_a,
                customer=self.customer,
                valid_from=date(2026, 7, 1),
            ).exists()
        )


class BulkRaiseRbacTests(BulkRaiseFixtureMixin, APITestCase):
    def _payload(self):
        return {
            "prices": [self.price_a.id],
            "mode": "percent",
            "amount": "10",
            "valid_from": "2026-07-01",
        }

    def test_company_admin_with_toggle_allowed(self):
        self.assertTrue(
            self.company.provider_admin_may_manage_customer_prices
        )
        self.authenticate(self.company_admin)
        response = self.client.post(
            bulk_raise_url(self.customer.id), self._payload(), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_company_admin_without_toggle_blocked(self):
        self.company.provider_admin_may_manage_customer_prices = False
        self.company.save(
            update_fields=["provider_admin_may_manage_customer_prices"]
        )
        self.authenticate(self.company_admin)
        response = self.client.post(
            bulk_raise_url(self.customer.id), self._payload(), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_company_admin_other_company_blocked(self):
        self.authenticate(self.other_company_admin)
        response = self.client.post(
            bulk_raise_url(self.customer.id), self._payload(), format="json"
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )

    def test_customer_user_blocked(self):
        self.authenticate(self.customer_user)
        response = self.client.post(
            bulk_raise_url(self.customer.id), self._payload(), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_blocked(self):
        staff = self.make_user("staff-bulk@example.com", UserRole.STAFF)
        self.authenticate(staff)
        response = self.client.post(
            bulk_raise_url(self.customer.id), self._payload(), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class BulkRaiseServiceDedupTests(BulkRaiseFixtureMixin, APITestCase):
    """P1 (PR review) — a service can have several active CSP rows (each
    raise keeps the source open). When the select-all UI sends them all,
    bulk-raise must collapse to ONE new row per service, derived from the
    latest-effective source (max valid_from, then max id), so the result
    is deterministic and order-independent.
    """

    def setUp(self):
        super().setUp()
        # row1 = the fixture's price_a on service_a (100.00, 2026-01-01).
        self.row1 = self.price_a
        # row2 = a later active row on the SAME service (110.00).
        self.row2 = CustomerServicePrice.objects.create(
            service=self.service_a,
            customer=self.customer,
            unit_price=Decimal("110.00"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 3, 1),
            is_active=True,
        )

    def _new_rows_for_service_a(self):
        return CustomerServicePrice.objects.filter(
            service=self.service_a,
            customer=self.customer,
            valid_from=date(2026, 6, 1),
        )

    def test_both_rows_collapse_to_one_new_row_from_latest_source(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            bulk_raise_url(self.customer.id),
            {
                "prices": [self.row1.id, self.row2.id],
                "mode": "percent",
                "amount": "10",
                "valid_from": "2026-06-01",
            },
            format="json",
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_200_OK, status.HTTP_201_CREATED),
        )
        self.assertEqual(response.data["created_count"], 1)

        new_rows = self._new_rows_for_service_a()
        self.assertEqual(new_rows.count(), 1)
        # Raised from the latest source (row2's 110.00), not row1's 100.00.
        self.assertEqual(new_rows.first().unit_price, Decimal("121.00"))

    def test_resolver_picks_the_single_raised_row(self):
        self.authenticate(self.super_admin)
        self.client.post(
            bulk_raise_url(self.customer.id),
            {
                "prices": [self.row1.id, self.row2.id],
                "mode": "percent",
                "amount": "10",
                "valid_from": "2026-06-01",
            },
            format="json",
        )
        resolved = resolve_price(
            self.service_a, self.customer, on=date(2026, 6, 15)
        )
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.unit_price, Decimal("121.00"))
        self.assertEqual(resolved.valid_from, date(2026, 6, 1))

    def test_order_independent(self):
        # Reversed payload yields the same single 121.00 row.
        self.authenticate(self.super_admin)
        response = self.client.post(
            bulk_raise_url(self.customer.id),
            {
                "prices": [self.row2.id, self.row1.id],
                "mode": "percent",
                "amount": "10",
                "valid_from": "2026-06-01",
            },
            format="json",
        )
        self.assertEqual(response.data["created_count"], 1)
        new_rows = self._new_rows_for_service_a()
        self.assertEqual(new_rows.count(), 1)
        self.assertEqual(new_rows.first().unit_price, Decimal("121.00"))

    def test_source_rows_preserved(self):
        self.authenticate(self.super_admin)
        self.client.post(
            bulk_raise_url(self.customer.id),
            {
                "prices": [self.row1.id, self.row2.id],
                "mode": "percent",
                "amount": "10",
                "valid_from": "2026-06-01",
            },
            format="json",
        )
        self.row1.refresh_from_db()
        self.row2.refresh_from_db()
        self.assertEqual(self.row1.unit_price, Decimal("100.00"))
        self.assertEqual(self.row2.unit_price, Decimal("110.00"))
        self.assertTrue(self.row1.is_active)
        self.assertTrue(self.row2.is_active)

    def test_dedup_only_collapses_within_a_service(self):
        # Two different services (one active row each, via the fixture)
        # selected together still raise BOTH — de-dup is per-service.
        self.authenticate(self.super_admin)
        response = self.client.post(
            bulk_raise_url(self.customer.id),
            {
                "prices": [self.price_a.id, self.price_b.id],
                "mode": "percent",
                "amount": "10",
                "valid_from": "2026-06-01",
            },
            format="json",
        )
        self.assertEqual(response.data["created_count"], 2)
