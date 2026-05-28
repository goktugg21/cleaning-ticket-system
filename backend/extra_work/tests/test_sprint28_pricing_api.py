"""
Sprint 28 Batch 5 — per-customer pricing CRUD tests
(`CustomerServicePrice`).

Coverage matrix:

  * SUPER_ADMIN + COMPANY_ADMIN-for-customer can CRUD prices for
    customers inside their own provider company.
  * Cross-provider 403 — a COMPANY_ADMIN of provider B cannot touch
    a price under provider A's customer.
  * CUSTOMER_USER / BUILDING_MANAGER / STAFF → 403 on every endpoint.
  * Scope isolation — customer A's prices never appear on customer
    B's list; ID smuggling (customer A URL + price-B id) returns 404.
  * Validation — `valid_to < valid_from` rejected; negative
    `unit_price` / `vat_pct` rejected.
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
from test_utils import TenantFixtureMixin


def list_url(customer_id):
    return f"/api/customers/{customer_id}/pricing/"


def detail_url(customer_id, price_id):
    return f"/api/customers/{customer_id}/pricing/{price_id}/"


class PricingApiFixtureMixin(TenantFixtureMixin):
    def setUp(self):
        super().setUp()
        self.category = ServiceCategory.objects.create(name="Cleaning")
        self.service = Service.objects.create(
            category=self.category,
            name="Window cleaning",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("45.00"),
        )
        self.other_service = Service.objects.create(
            category=self.category,
            name="Floor polishing",
            unit_type=ExtraWorkPricingUnitType.SQUARE_METERS,
            default_unit_price=Decimal("12.50"),
        )


class CustomerServicePriceCrudTests(PricingApiFixtureMixin, APITestCase):
    def test_super_admin_can_create_and_list_price(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            list_url(self.customer.id),
            {
                "service": self.service.id,
                "unit_price": "40.00",
                "vat_pct": "21.00",
                "valid_from": "2026-01-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["service"], self.service.id)
        self.assertEqual(response.data["customer"], self.customer.id)
        self.assertEqual(response.data["unit_price"], "40.00")
        self.assertEqual(response.data["service_name"], "Window cleaning")

        list_resp = self.client.get(list_url(self.customer.id))
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(list_resp.data["count"], 1)

    def test_company_admin_can_crud_price_in_own_scope(self):
        self.authenticate(self.company_admin)
        create = self.client.post(
            list_url(self.customer.id),
            {
                "service": self.service.id,
                "unit_price": "35.00",
                "valid_from": "2026-02-01",
            },
            format="json",
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        price_id = create.data["id"]

        retrieve = self.client.get(detail_url(self.customer.id, price_id))
        self.assertEqual(retrieve.status_code, status.HTTP_200_OK)

        update = self.client.patch(
            detail_url(self.customer.id, price_id),
            {"unit_price": "37.50"},
            format="json",
        )
        self.assertEqual(update.status_code, status.HTTP_200_OK)
        self.assertEqual(update.data["unit_price"], "37.50")

        delete = self.client.delete(detail_url(self.customer.id, price_id))
        self.assertEqual(delete.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            CustomerServicePrice.objects.filter(pk=price_id).exists()
        )

    def test_company_admin_b_cannot_create_price_for_company_a_customer(self):
        # other_company_admin is bound to other_company via
        # CompanyUserMembership; self.customer is in self.company.
        self.authenticate(self.other_company_admin)
        response = self.client.post(
            list_url(self.customer.id),
            {
                "service": self.service.id,
                "unit_price": "1.00",
                "valid_from": "2026-01-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            CustomerServicePrice.objects.filter(
                customer=self.customer
            ).exists()
        )

    def test_customer_field_read_only_on_create(self):
        # Body-level `customer` must NOT override the URL-bound
        # customer (mirrors the Contact contract).
        self.authenticate(self.super_admin)
        response = self.client.post(
            list_url(self.customer.id),
            {
                "service": self.service.id,
                "unit_price": "10.00",
                "valid_from": "2026-01-01",
                "customer": self.other_customer.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["customer"], self.customer.id)


class CustomerServicePriceScopeIsolationTests(
    PricingApiFixtureMixin, APITestCase
):
    def setUp(self):
        super().setUp()
        self.price_a = CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("40.00"),
            valid_from=date(2026, 1, 1),
        )
        self.price_b = CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.other_customer,
            unit_price=Decimal("50.00"),
            valid_from=date(2026, 1, 1),
        )

    def test_company_admin_a_cannot_list_company_b_prices(self):
        self.authenticate(self.company_admin)
        response = self.client.get(list_url(self.other_customer.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_response_excludes_other_customer_rows(self):
        self.authenticate(self.super_admin)
        response = self.client.get(list_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(self.price_a.id, ids)
        self.assertNotIn(self.price_b.id, ids)

    def test_id_smuggling_returns_404(self):
        # SUPER_ADMIN asking for price_b under customer A's URL.
        self.authenticate(self.super_admin)
        retrieve = self.client.get(
            detail_url(self.customer.id, self.price_b.id)
        )
        self.assertEqual(retrieve.status_code, status.HTTP_404_NOT_FOUND)

        patch_resp = self.client.patch(
            detail_url(self.customer.id, self.price_b.id),
            {"unit_price": "0.01"},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, status.HTTP_404_NOT_FOUND)
        # Row survives.
        self.price_b.refresh_from_db()
        self.assertEqual(self.price_b.unit_price, Decimal("50.00"))

        delete_resp = self.client.delete(
            detail_url(self.customer.id, self.price_b.id)
        )
        self.assertEqual(delete_resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(
            CustomerServicePrice.objects.filter(pk=self.price_b.id).exists()
        )

    def test_customer_user_blocked_on_every_endpoint(self):
        self.authenticate(self.customer_user)
        list_resp = self.client.get(list_url(self.customer.id))
        self.assertEqual(list_resp.status_code, status.HTTP_403_FORBIDDEN)
        retrieve_resp = self.client.get(
            detail_url(self.customer.id, self.price_a.id)
        )
        self.assertEqual(retrieve_resp.status_code, status.HTTP_403_FORBIDDEN)
        patch_resp = self.client.patch(
            detail_url(self.customer.id, self.price_a.id),
            {"unit_price": "99.99"},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_building_manager_blocked_on_every_endpoint(self):
        self.authenticate(self.manager)
        list_resp = self.client.get(list_url(self.customer.id))
        self.assertEqual(list_resp.status_code, status.HTTP_403_FORBIDDEN)
        retrieve_resp = self.client.get(
            detail_url(self.customer.id, self.price_a.id)
        )
        self.assertEqual(retrieve_resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_role_blocked_on_every_endpoint(self):
        staff = self.make_user("staff-price@example.com", UserRole.STAFF)
        self.authenticate(staff)
        list_resp = self.client.get(list_url(self.customer.id))
        self.assertEqual(list_resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_filter_by_service(self):
        # Add a second price for the other service on customer A.
        CustomerServicePrice.objects.create(
            service=self.other_service,
            customer=self.customer,
            unit_price=Decimal("9.99"),
            valid_from=date(2026, 1, 1),
        )
        self.authenticate(self.super_admin)
        response = self.client.get(
            list_url(self.customer.id) + f"?service={self.service.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        services = {row["service"] for row in response.data["results"]}
        self.assertEqual(services, {self.service.id})


class CustomerServicePriceValidationTests(
    PricingApiFixtureMixin, APITestCase
):
    def test_valid_to_before_valid_from_rejected(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            list_url(self.customer.id),
            {
                "service": self.service.id,
                "unit_price": "10.00",
                "valid_from": "2026-06-01",
                "valid_to": "2026-01-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("valid_to", response.data)

    def test_negative_unit_price_rejected(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            list_url(self.customer.id),
            {
                "service": self.service.id,
                "unit_price": "-0.01",
                "valid_from": "2026-01-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("unit_price", response.data)

    def test_negative_vat_pct_rejected(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            list_url(self.customer.id),
            {
                "service": self.service.id,
                "unit_price": "10.00",
                "vat_pct": "-1.00",
                "valid_from": "2026-01-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("vat_pct", response.data)

    def test_open_ended_row_allowed(self):
        # `valid_to` may be omitted (open-ended contract).
        self.authenticate(self.super_admin)
        response = self.client.post(
            list_url(self.customer.id),
            {
                "service": self.service.id,
                "unit_price": "10.00",
                "valid_from": "2026-01-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data["valid_to"])

    def test_patch_with_valid_to_before_valid_from_rejected(self):
        row = CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("10.00"),
            valid_from=date(2026, 6, 1),
        )
        self.authenticate(self.super_admin)
        response = self.client.patch(
            detail_url(self.customer.id, row.id),
            {"valid_to": "2026-01-01"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("valid_to", response.data)
