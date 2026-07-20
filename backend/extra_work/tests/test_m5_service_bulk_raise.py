"""
M5 C — catalog default-price bulk-raise tests.

`POST /api/services/bulk-raise/` raises the catalog
`Service.default_unit_price` of a set of Services by a percentage or a
fixed amount, IN PLACE. Catalog defaults are quoting-reference numbers
(no validity window); the raise updates the baseline only and must NOT
touch any `CustomerServicePrice` (what customers are billed).

Coverage matrix:

  * Percent raise — old*(1+amount/100), HALF_UP to 2dp.
  * Fixed raise — old + amount.
  * In-place — no new Service rows; the same ids are mutated.
  * Billing isolation — a seeded CustomerServicePrice and the resolver
    are unaffected by the catalog raise.
  * Validation (400, zero writes) — empty services, bad mode, amount<=0
    (code service_bulk_raise_amount_invalid), a cross-company / inactive
    service (code service_bulk_raise_invalid), mixed valid+invalid.
  * RBAC — CA with the catalog toggle 200; CA without 403; CA targeting
    another company's service 400/403; CUSTOMER_USER / STAFF 403.
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


BULK_RAISE_URL = "/api/services/bulk-raise/"


class ServiceBulkRaiseFixtureMixin(TenantFixtureMixin):
    def setUp(self):
        super().setUp()
        self.category = ServiceCategory.objects.create(name="Cleaning")
        self.service_a = Service.objects.create(
            category=self.category,
            company=self.company,
            name="Window cleaning",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("100.00"),
            is_active=True,
        )
        self.service_b = Service.objects.create(
            category=self.category,
            company=self.company,
            name="Floor polishing",
            unit_type=ExtraWorkPricingUnitType.SQUARE_METERS,
            default_unit_price=Decimal("33.33"),
            is_active=True,
        )
        self.inactive_service = Service.objects.create(
            category=self.category,
            company=self.company,
            name="Retired service",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            default_unit_price=Decimal("80.00"),
            is_active=False,
        )
        self.other_service = Service.objects.create(
            category=self.category,
            company=self.other_company,
            name="Other-company service",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("99.00"),
            is_active=True,
        )
        self.staff = self.make_user("staff-svc-bulk@example.com", UserRole.STAFF)


class ServiceBulkRaiseMathTests(ServiceBulkRaiseFixtureMixin, APITestCase):
    def test_percent_raise_updates_in_place(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            BULK_RAISE_URL,
            {
                "services": [self.service_a.id, self.service_b.id],
                "mode": "percent",
                "amount": "10",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["updated_count"], 2)

        self.service_a.refresh_from_db()
        self.service_b.refresh_from_db()
        # 100.00 * 1.1 = 110.00
        self.assertEqual(self.service_a.default_unit_price, Decimal("110.00"))
        # 33.33 * 1.1 = 36.663 -> HALF_UP 36.66
        self.assertEqual(self.service_b.default_unit_price, Decimal("36.66"))

    def test_fixed_raise_updates_in_place(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            BULK_RAISE_URL,
            {
                "services": [self.service_a.id, self.service_b.id],
                "mode": "fixed",
                "amount": "5.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["updated_count"], 2)

        self.service_a.refresh_from_db()
        self.service_b.refresh_from_db()
        self.assertEqual(self.service_a.default_unit_price, Decimal("105.00"))
        self.assertEqual(self.service_b.default_unit_price, Decimal("38.33"))

    def test_raise_is_in_place_no_new_rows(self):
        before_count = Service.objects.count()
        before_ids = set(Service.objects.values_list("id", flat=True))
        self.authenticate(self.super_admin)
        response = self.client.post(
            BULK_RAISE_URL,
            {
                "services": [self.service_a.id, self.service_b.id],
                "mode": "percent",
                "amount": "10",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Service.objects.count(), before_count)
        self.assertEqual(
            set(Service.objects.values_list("id", flat=True)), before_ids
        )
        # The response reports the same ids that were mutated.
        raised_ids = {row["service"] for row in response.data["results"]}
        self.assertEqual(raised_ids, {self.service_a.id, self.service_b.id})

    def test_catalog_raise_does_not_touch_billing(self):
        # Seed a customer contract price on service_a — billing.
        csp = CustomerServicePrice.objects.create(
            service=self.service_a,
            customer=self.customer,
            unit_price=Decimal("42.00"),
            vat_pct=Decimal("21.00"),
            valid_from=date(2026, 1, 1),
            is_active=True,
        )
        self.authenticate(self.super_admin)
        response = self.client.post(
            BULK_RAISE_URL,
            {
                "services": [self.service_a.id],
                "mode": "percent",
                "amount": "50",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Catalog default moved...
        self.service_a.refresh_from_db()
        self.assertEqual(self.service_a.default_unit_price, Decimal("150.00"))

        # ...but the contract price (what the customer is billed) did not.
        csp.refresh_from_db()
        self.assertEqual(csp.unit_price, Decimal("42.00"))
        resolved = resolve_price(
            self.service_a, self.customer, on=date(2026, 6, 1)
        )
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.id, csp.id)
        self.assertEqual(resolved.unit_price, Decimal("42.00"))


class ServiceBulkRaiseValidationTests(
    ServiceBulkRaiseFixtureMixin, APITestCase
):
    def _defaults_snapshot(self):
        return {
            s.id: s.default_unit_price
            for s in Service.objects.all()
        }

    def test_empty_services_rejected(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            BULK_RAISE_URL,
            {"services": [], "mode": "percent", "amount": "10"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("services", response.data)

    def test_invalid_mode_rejected(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            BULK_RAISE_URL,
            {
                "services": [self.service_a.id],
                "mode": "multiply",
                "amount": "10",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("mode", response.data)

    def test_zero_amount_rejected_with_no_writes(self):
        self.authenticate(self.super_admin)
        before = self._defaults_snapshot()
        response = self.client.post(
            BULK_RAISE_URL,
            {
                "services": [self.service_a.id],
                "mode": "percent",
                "amount": "0",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        codes = [
            getattr(err, "code", None)
            for err in response.data.get("amount", [])
        ]
        self.assertIn("service_bulk_raise_amount_invalid", codes)
        self.assertEqual(self._defaults_snapshot(), before)

    def test_negative_amount_rejected(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            BULK_RAISE_URL,
            {
                "services": [self.service_a.id],
                "mode": "fixed",
                "amount": "-5.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        codes = [
            getattr(err, "code", None)
            for err in response.data.get("amount", [])
        ]
        self.assertIn("service_bulk_raise_amount_invalid", codes)

    def test_inactive_service_rejected_with_no_writes(self):
        self.authenticate(self.super_admin)
        before = self._defaults_snapshot()
        response = self.client.post(
            BULK_RAISE_URL,
            {
                "services": [self.inactive_service.id],
                "mode": "percent",
                "amount": "10",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        codes = [
            getattr(err, "code", None)
            for err in response.data.get("services", [])
        ]
        self.assertIn("service_bulk_raise_invalid", codes)
        self.assertEqual(self._defaults_snapshot(), before)

    def test_cross_company_service_rejected_for_company_admin(self):
        # A CA of company A cannot see (and so cannot raise) a company B
        # service: out of scope -> service_bulk_raise_invalid.
        self.authenticate(self.company_admin)
        before = self._defaults_snapshot()
        response = self.client.post(
            BULK_RAISE_URL,
            {
                "services": [self.other_service.id],
                "mode": "percent",
                "amount": "10",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        codes = [
            getattr(err, "code", None)
            for err in response.data.get("services", [])
        ]
        self.assertIn("service_bulk_raise_invalid", codes)
        self.assertEqual(self._defaults_snapshot(), before)

    def test_mixed_valid_and_invalid_is_all_or_nothing(self):
        self.authenticate(self.super_admin)
        before = self._defaults_snapshot()
        response = self.client.post(
            BULK_RAISE_URL,
            {
                # service_a is valid; the inactive one is not.
                "services": [self.service_a.id, self.inactive_service.id],
                "mode": "percent",
                "amount": "10",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Zero writes: the valid service was NOT raised either.
        self.assertEqual(self._defaults_snapshot(), before)
        self.service_a.refresh_from_db()
        self.assertEqual(self.service_a.default_unit_price, Decimal("100.00"))


class ServiceBulkRaiseRbacTests(ServiceBulkRaiseFixtureMixin, APITestCase):
    def _payload(self):
        return {
            "services": [self.service_a.id],
            "mode": "percent",
            "amount": "10",
        }

    def test_company_admin_with_toggle_allowed(self):
        self.assertTrue(self.company.provider_admin_may_manage_catalog)
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_RAISE_URL, self._payload(), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.service_a.refresh_from_db()
        self.assertEqual(self.service_a.default_unit_price, Decimal("110.00"))

    def test_company_admin_without_toggle_blocked(self):
        self.company.provider_admin_may_manage_catalog = False
        self.company.save(
            update_fields=["provider_admin_may_manage_catalog"]
        )
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_RAISE_URL, self._payload(), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.service_a.refresh_from_db()
        self.assertEqual(self.service_a.default_unit_price, Decimal("100.00"))

    def test_company_admin_other_company_service_blocked(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_RAISE_URL,
            {
                "services": [self.other_service.id],
                "mode": "percent",
                "amount": "10",
            },
            format="json",
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN),
        )

    def test_customer_user_blocked(self):
        self.authenticate(self.customer_user)
        response = self.client.post(
            BULK_RAISE_URL, self._payload(), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_blocked(self):
        self.authenticate(self.staff)
        response = self.client.post(
            BULK_RAISE_URL, self._payload(), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class ServiceBulkAdjustLowerTests(ServiceBulkRaiseFixtureMixin, APITestCase):
    """#108 Part C — `direction: lower` on the catalog endpoint (raise
    stays the default). Lowering updates default_unit_price in place
    exactly like raising; guards: percent lower must be < 100, and a
    result at or below zero rejects the whole batch (zero writes)."""

    def test_percent_lower_updates_in_place(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            BULK_RAISE_URL,
            {
                "services": [self.service_a.id, self.service_b.id],
                "mode": "percent",
                "amount": "10",
                "direction": "lower",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["updated_count"], 2)
        self.service_a.refresh_from_db()
        self.service_b.refresh_from_db()
        # 100.00 * 0.9 = 90.00; 33.33 * 0.9 = 29.997 -> HALF_UP 30.00.
        self.assertEqual(self.service_a.default_unit_price, Decimal("90.00"))
        self.assertEqual(self.service_b.default_unit_price, Decimal("30.00"))

    def test_fixed_lower_updates_in_place(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            BULK_RAISE_URL,
            {
                "services": [self.service_a.id],
                "mode": "fixed",
                "amount": "5.00",
                "direction": "lower",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.service_a.refresh_from_db()
        self.assertEqual(self.service_a.default_unit_price, Decimal("95.00"))

    def test_percent_lower_at_or_above_100_rejected(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            BULK_RAISE_URL,
            {
                "services": [self.service_a.id],
                "mode": "percent",
                "amount": "100",
                "direction": "lower",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["amount"][0].code,
            "service_bulk_raise_amount_invalid",
        )
        self.service_a.refresh_from_db()
        self.assertEqual(self.service_a.default_unit_price, Decimal("100.00"))

    def test_zero_floor_rejects_whole_batch(self):
        # 33.33 - 50.00 goes negative -> the WHOLE batch (incl. the
        # still-positive 100.00 row) is rejected with zero writes.
        self.authenticate(self.super_admin)
        response = self.client.post(
            BULK_RAISE_URL,
            {
                "services": [self.service_a.id, self.service_b.id],
                "mode": "fixed",
                "amount": "50.00",
                "direction": "lower",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["amount"][0].code,
            "service_bulk_raise_result_invalid",
        )
        self.service_a.refresh_from_db()
        self.service_b.refresh_from_db()
        self.assertEqual(self.service_a.default_unit_price, Decimal("100.00"))
        self.assertEqual(self.service_b.default_unit_price, Decimal("33.33"))

    def test_explicit_raise_direction_matches_default(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            BULK_RAISE_URL,
            {
                "services": [self.service_a.id],
                "mode": "percent",
                "amount": "10",
                "direction": "raise",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.service_a.refresh_from_db()
        self.assertEqual(self.service_a.default_unit_price, Decimal("110.00"))
