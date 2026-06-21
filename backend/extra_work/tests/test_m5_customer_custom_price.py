"""
M5 A — per-customer custom-price CRUD tests (`CustomerCustomPrice`).

`CustomerCustomPrice` is a provider-internal, ad-hoc price line for a
non-catalog service: a free-text `custom_name` + its own `unit_type`,
with NO `service` FK. It is deliberately parallel to
`CustomerServicePrice` but lives on its own endpoint
(`/api/customers/<id>/custom-pricing/`) so the instant-ticket pricing
resolver and the cart / proposal / billing paths (all keyed on a
concrete `service`) stay untouched.

Coverage matrix:

  * SUPER_ADMIN POST → 201; row's `customer` equals the URL customer;
    a body-level `customer` is ignored.
  * COMPANY_ADMIN (own company, toggle ON) POST → 201; toggle OFF →
    403; targeting a customer in another provider company → 403.
  * CUSTOMER_USER GET/POST → 403; STAFF GET → 403 (provider-internal).
  * Scope isolation — customer A's rows never appear on customer B's
    list; an id belonging to another customer → 404.
  * Validation — `valid_to < valid_from`, negative `unit_price` /
    `vat_pct`, missing `custom_name`, invalid `unit_type` → 400.
  * Detail PATCH `unit_price` → 200; DELETE soft-archives (204) and is
    idempotent.
  * Resolver isolation — a `CustomerCustomPrice` never influences
    `resolve_price(service, customer)`.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from extra_work.models import (
    CustomerCustomPrice,
    CustomerServicePrice,
    ExtraWorkPricingUnitType,
    Service,
    ServiceCategory,
)
from extra_work.pricing import resolve_price
from test_utils import TenantFixtureMixin


def list_url(customer_id):
    return f"/api/customers/{customer_id}/custom-pricing/"


def detail_url(customer_id, custom_price_id):
    return f"/api/customers/{customer_id}/custom-pricing/{custom_price_id}/"


class CustomCustomPriceFixtureMixin(TenantFixtureMixin):
    def setUp(self):
        super().setUp()
        # A concrete catalog service used only by the resolver-isolation
        # test; the custom-price endpoint itself never references it.
        self.category = ServiceCategory.objects.create(name="Cleaning")
        self.service = Service.objects.create(
            category=self.category,
            company=self.company,
            name="Window cleaning",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("45.00"),
        )
        self.staff = self.make_user("staff-ccp@example.com", UserRole.STAFF)

    def valid_payload(self, **overrides):
        payload = {
            "custom_name": "Graffiti removal (one-off)",
            "unit_type": ExtraWorkPricingUnitType.FIXED,
            "unit_price": "250.00",
            "vat_pct": "21.00",
            "valid_from": "2026-01-01",
        }
        payload.update(overrides)
        return payload


class CustomerCustomPriceCrudTests(
    CustomCustomPriceFixtureMixin, APITestCase
):
    def test_super_admin_can_create_and_list(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            list_url(self.customer.id),
            self.valid_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["customer"], self.customer.id)
        self.assertEqual(
            response.data["custom_name"], "Graffiti removal (one-off)"
        )
        self.assertEqual(response.data["unit_price"], "250.00")
        self.assertEqual(response.data["unit_type_display"], "Fixed")

        # The persisted row is bound to the URL customer.
        row = CustomerCustomPrice.objects.get(pk=response.data["id"])
        self.assertEqual(row.customer_id, self.customer.id)

        list_resp = self.client.get(list_url(self.customer.id))
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(list_resp.data["count"], 1)

    def test_body_level_customer_is_ignored(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            list_url(self.customer.id),
            self.valid_payload(customer=self.other_customer.id),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["customer"], self.customer.id)
        row = CustomerCustomPrice.objects.get(pk=response.data["id"])
        self.assertEqual(row.customer_id, self.customer.id)

    def test_company_admin_with_toggle_can_create(self):
        # Company A toggle defaults to True in the model.
        self.assertTrue(
            self.company.provider_admin_may_manage_customer_prices
        )
        self.authenticate(self.company_admin)
        response = self.client.post(
            list_url(self.customer.id),
            self.valid_payload(unit_price="99.99"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["unit_price"], "99.99")

    def test_company_admin_without_toggle_blocked(self):
        self.company.provider_admin_may_manage_customer_prices = False
        self.company.save(
            update_fields=["provider_admin_may_manage_customer_prices"]
        )
        self.authenticate(self.company_admin)
        response = self.client.post(
            list_url(self.customer.id),
            self.valid_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            CustomerCustomPrice.objects.filter(
                customer=self.customer
            ).exists()
        )

    def test_company_admin_b_cannot_create_for_company_a_customer(self):
        self.authenticate(self.other_company_admin)
        response = self.client.post(
            list_url(self.customer.id),
            self.valid_payload(),
            format="json",
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )
        self.assertFalse(
            CustomerCustomPrice.objects.filter(
                customer=self.customer
            ).exists()
        )


class CustomerCustomPriceProviderOnlyTests(
    CustomCustomPriceFixtureMixin, APITestCase
):
    def setUp(self):
        super().setUp()
        self.row = CustomerCustomPrice.objects.create(
            customer=self.customer,
            custom_name="Deep clean (ad-hoc)",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            unit_price=Decimal("100.00"),
            valid_from=date(2026, 1, 1),
        )

    def test_customer_user_get_and_post_forbidden(self):
        self.authenticate(self.customer_user)
        list_resp = self.client.get(list_url(self.customer.id))
        self.assertEqual(list_resp.status_code, status.HTTP_403_FORBIDDEN)

        post_resp = self.client.post(
            list_url(self.customer.id),
            self.valid_payload(),
            format="json",
        )
        self.assertEqual(post_resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_get_forbidden(self):
        self.authenticate(self.staff)
        list_resp = self.client.get(list_url(self.customer.id))
        self.assertEqual(list_resp.status_code, status.HTTP_403_FORBIDDEN)


class CustomerCustomPriceScopeIsolationTests(
    CustomCustomPriceFixtureMixin, APITestCase
):
    def setUp(self):
        super().setUp()
        self.row_a = CustomerCustomPrice.objects.create(
            customer=self.customer,
            custom_name="A-only line",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            unit_price=Decimal("10.00"),
            valid_from=date(2026, 1, 1),
        )
        self.row_b = CustomerCustomPrice.objects.create(
            customer=self.other_customer,
            custom_name="B-only line",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            unit_price=Decimal("20.00"),
            valid_from=date(2026, 1, 1),
        )

    def test_list_excludes_other_customer_rows(self):
        self.authenticate(self.super_admin)
        response = self.client.get(list_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(self.row_a.id, ids)
        self.assertNotIn(self.row_b.id, ids)

    def test_id_belonging_to_other_customer_returns_404(self):
        self.authenticate(self.super_admin)
        retrieve = self.client.get(
            detail_url(self.customer.id, self.row_b.id)
        )
        self.assertEqual(retrieve.status_code, status.HTTP_404_NOT_FOUND)

        patch_resp = self.client.patch(
            detail_url(self.customer.id, self.row_b.id),
            {"unit_price": "0.01"},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, status.HTTP_404_NOT_FOUND)
        self.row_b.refresh_from_db()
        self.assertEqual(self.row_b.unit_price, Decimal("20.00"))


class CustomerCustomPriceValidationTests(
    CustomCustomPriceFixtureMixin, APITestCase
):
    def test_valid_to_before_valid_from_rejected(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            list_url(self.customer.id),
            self.valid_payload(
                valid_from="2026-06-01", valid_to="2026-01-01"
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("valid_to", response.data)

    def test_negative_unit_price_rejected(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            list_url(self.customer.id),
            self.valid_payload(unit_price="-0.01"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("unit_price", response.data)

    def test_negative_vat_pct_rejected(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            list_url(self.customer.id),
            self.valid_payload(vat_pct="-1.00"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("vat_pct", response.data)

    def test_missing_custom_name_rejected(self):
        self.authenticate(self.super_admin)
        payload = self.valid_payload()
        payload.pop("custom_name")
        response = self.client.post(
            list_url(self.customer.id), payload, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("custom_name", response.data)

    def test_invalid_unit_type_rejected(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            list_url(self.customer.id),
            self.valid_payload(unit_type="NOT_A_REAL_UNIT"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("unit_type", response.data)

    def test_open_ended_row_allowed(self):
        self.authenticate(self.super_admin)
        payload = self.valid_payload()
        payload.pop("valid_to", None)
        response = self.client.post(
            list_url(self.customer.id), payload, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data["valid_to"])


class CustomerCustomPriceDetailMutationTests(
    CustomCustomPriceFixtureMixin, APITestCase
):
    def setUp(self):
        super().setUp()
        self.row = CustomerCustomPrice.objects.create(
            customer=self.customer,
            custom_name="Editable line",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            unit_price=Decimal("100.00"),
            valid_from=date(2026, 1, 1),
        )

    def test_patch_unit_price(self):
        self.authenticate(self.super_admin)
        response = self.client.patch(
            detail_url(self.customer.id, self.row.id),
            {"unit_price": "175.50"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["unit_price"], "175.50")
        self.row.refresh_from_db()
        self.assertEqual(self.row.unit_price, Decimal("175.50"))

    def test_delete_soft_archives_and_is_idempotent(self):
        self.authenticate(self.super_admin)
        first = self.client.delete(detail_url(self.customer.id, self.row.id))
        self.assertEqual(first.status_code, status.HTTP_204_NO_CONTENT)
        # Row is kept; only is_active flips.
        self.assertTrue(
            CustomerCustomPrice.objects.filter(pk=self.row.id).exists()
        )
        self.row.refresh_from_db()
        self.assertFalse(self.row.is_active)

        # A second DELETE on the now-inactive row is a no-op 204.
        second = self.client.delete(detail_url(self.customer.id, self.row.id))
        self.assertEqual(second.status_code, status.HTTP_204_NO_CONTENT)
        self.row.refresh_from_db()
        self.assertFalse(self.row.is_active)


class CustomerCustomPriceResolverIsolationTests(
    CustomCustomPriceFixtureMixin, APITestCase
):
    def test_custom_price_never_influences_resolver(self):
        # A custom-price row for this customer must NEVER be returned by
        # resolve_price — it carries no `service`, so the (service,
        # customer) lookup cannot see it.
        CustomerCustomPrice.objects.create(
            customer=self.customer,
            custom_name="Ad-hoc line shadowing the catalog",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            unit_price=Decimal("1.00"),
            valid_from=date(2026, 1, 1),
        )

        # No CustomerServicePrice exists → resolver still returns None.
        self.assertIsNone(
            resolve_price(
                self.service, self.customer, on=date(2026, 6, 1)
            )
        )

        # Add a real contract price → resolver returns exactly it,
        # unaffected by the custom line.
        csp = CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("42.00"),
            valid_from=date(2026, 1, 1),
        )
        resolved = resolve_price(
            self.service, self.customer, on=date(2026, 6, 1)
        )
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.id, csp.id)
        self.assertEqual(resolved.unit_price, Decimal("42.00"))
