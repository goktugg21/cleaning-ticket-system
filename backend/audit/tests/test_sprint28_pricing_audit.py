"""
Sprint 28 Batch 5 — audit-coverage tests for the new service catalog
and per-customer pricing models.

`ServiceCategory`, `Service` and `CustomerServicePrice` are
registered with the full-CRUD signal trio
(`_on_pre_save` / `_on_post_save` / `_on_post_delete`) in
`backend/audit/signals.py`. The tests below exercise the API
entrypoints end-to-end and assert that exactly one AuditLog row
lands per mutation, with the actor, action, target_model, target_id
and changes shape we expect.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from audit.models import AuditAction, AuditLog
from extra_work.models import (
    CustomerServicePrice,
    ExtraWorkPricingUnitType,
    Service,
    ServiceCategory,
)
from test_utils import TenantFixtureMixin


CATEGORY_LIST_URL = "/api/services/categories/"
CATEGORY_DETAIL_URL = "/api/services/categories/{cat_id}/"
SERVICE_LIST_URL = "/api/services/"
SERVICE_DETAIL_URL = "/api/services/{svc_id}/"


def price_list_url(customer_id):
    return f"/api/customers/{customer_id}/pricing/"


def price_detail_url(customer_id, price_id):
    return f"/api/customers/{customer_id}/pricing/{price_id}/"


class ServiceCategoryAuditTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        AuditLog.objects.all().delete()

    def test_create_via_api_writes_create_audit_log(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            CATEGORY_LIST_URL,
            {"name": "Audit Cat", "description": "for audit"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        logs = AuditLog.objects.filter(
            target_model="extra_work.ServiceCategory"
        )
        self.assertEqual(logs.count(), 1)
        log = logs.first()
        self.assertEqual(log.action, AuditAction.CREATE)
        self.assertEqual(log.actor, self.super_admin)
        self.assertEqual(log.target_id, response.data["id"])
        self.assertEqual(log.changes["name"]["after"], "Audit Cat")
        self.assertIsNone(log.changes["name"]["before"])

    def test_update_via_api_writes_update_audit_log(self):
        cat = ServiceCategory.objects.create(name="Before Name")
        AuditLog.objects.all().delete()  # drop the CREATE row

        self.authenticate(self.super_admin)
        response = self.client.patch(
            CATEGORY_DETAIL_URL.format(cat_id=cat.id),
            {"name": "After Name"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        log = AuditLog.objects.filter(
            target_model="extra_work.ServiceCategory",
            target_id=cat.id,
            action=AuditAction.UPDATE,
        ).get()
        self.assertEqual(log.actor, self.super_admin)
        self.assertEqual(set(log.changes.keys()), {"name"})
        self.assertEqual(log.changes["name"]["before"], "Before Name")
        self.assertEqual(log.changes["name"]["after"], "After Name")

    def test_delete_via_api_writes_delete_audit_log(self):
        cat = ServiceCategory.objects.create(name="To Delete")
        cat_id = cat.id
        AuditLog.objects.all().delete()

        self.authenticate(self.super_admin)
        response = self.client.delete(
            CATEGORY_DETAIL_URL.format(cat_id=cat_id)
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        log = AuditLog.objects.filter(
            target_model="extra_work.ServiceCategory",
            target_id=cat_id,
            action=AuditAction.DELETE,
        ).get()
        self.assertEqual(log.actor, self.super_admin)
        self.assertEqual(log.changes["name"]["before"], "To Delete")
        self.assertIsNone(log.changes["name"]["after"])


class ServiceAuditTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.category = ServiceCategory.objects.create(name="Cleaning")
        AuditLog.objects.all().delete()

    def test_create_via_api_writes_create_audit_log(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            SERVICE_LIST_URL,
            {
                "category": self.category.id,
                "name": "Window cleaning",
                "unit_type": ExtraWorkPricingUnitType.HOURS,
                "default_unit_price": "40.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        log = AuditLog.objects.filter(
            target_model="extra_work.Service"
        ).get()
        self.assertEqual(log.action, AuditAction.CREATE)
        self.assertEqual(log.actor, self.super_admin)
        self.assertEqual(log.target_id, response.data["id"])
        self.assertEqual(log.changes["name"]["after"], "Window cleaning")
        # FK pk lands in `category`.
        self.assertEqual(
            log.changes["category"]["after"], self.category.id
        )

    def test_update_via_api_writes_update_audit_log(self):
        svc = Service.objects.create(
            category=self.category,
            name="Floor polishing",
            unit_type=ExtraWorkPricingUnitType.SQUARE_METERS,
            default_unit_price=Decimal("12.50"),
        )
        AuditLog.objects.all().delete()

        self.authenticate(self.super_admin)
        response = self.client.patch(
            SERVICE_DETAIL_URL.format(svc_id=svc.id),
            {"default_unit_price": "15.00"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        log = AuditLog.objects.filter(
            target_model="extra_work.Service",
            target_id=svc.id,
            action=AuditAction.UPDATE,
        ).get()
        self.assertEqual(set(log.changes.keys()), {"default_unit_price"})
        # Decimal is serialized as string in the audit diff.
        self.assertEqual(
            log.changes["default_unit_price"]["before"], "12.50"
        )
        self.assertEqual(
            log.changes["default_unit_price"]["after"], "15.00"
        )

    def test_delete_via_api_writes_delete_audit_log(self):
        svc = Service.objects.create(
            category=self.category,
            name="To Delete Svc",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            default_unit_price=Decimal("100.00"),
        )
        svc_id = svc.id
        AuditLog.objects.all().delete()

        self.authenticate(self.super_admin)
        response = self.client.delete(SERVICE_DETAIL_URL.format(svc_id=svc_id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        log = AuditLog.objects.filter(
            target_model="extra_work.Service",
            target_id=svc_id,
            action=AuditAction.DELETE,
        ).get()
        self.assertEqual(log.changes["name"]["before"], "To Delete Svc")
        self.assertIsNone(log.changes["name"]["after"])


class CustomerServicePriceAuditTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.category = ServiceCategory.objects.create(name="Cleaning")
        self.service = Service.objects.create(
            category=self.category,
            name="Window cleaning",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("45.00"),
        )
        AuditLog.objects.all().delete()

    def test_create_via_api_writes_create_audit_log(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            price_list_url(self.customer.id),
            {
                "service": self.service.id,
                "unit_price": "40.00",
                "valid_from": "2026-01-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        log = AuditLog.objects.filter(
            target_model="extra_work.CustomerServicePrice"
        ).get()
        self.assertEqual(log.action, AuditAction.CREATE)
        self.assertEqual(log.actor, self.super_admin)
        self.assertEqual(log.target_id, response.data["id"])
        # Customer and service FKs land as their pks.
        self.assertEqual(
            log.changes["customer"]["after"], self.customer.id
        )
        self.assertEqual(
            log.changes["service"]["after"], self.service.id
        )
        # Decimal -> str
        self.assertEqual(log.changes["unit_price"]["after"], "40.00")
        # Date -> ISO string
        self.assertEqual(log.changes["valid_from"]["after"], "2026-01-01")

    def test_update_via_api_writes_update_audit_log(self):
        price = CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("40.00"),
            valid_from=date(2026, 1, 1),
        )
        AuditLog.objects.all().delete()

        self.authenticate(self.super_admin)
        response = self.client.patch(
            price_detail_url(self.customer.id, price.id),
            {"unit_price": "42.50"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        log = AuditLog.objects.filter(
            target_model="extra_work.CustomerServicePrice",
            target_id=price.id,
            action=AuditAction.UPDATE,
        ).get()
        self.assertEqual(set(log.changes.keys()), {"unit_price"})
        self.assertEqual(log.changes["unit_price"]["before"], "40.00")
        self.assertEqual(log.changes["unit_price"]["after"], "42.50")

    def test_delete_via_api_writes_delete_audit_log(self):
        price = CustomerServicePrice.objects.create(
            service=self.service,
            customer=self.customer,
            unit_price=Decimal("40.00"),
            valid_from=date(2026, 1, 1),
        )
        price_id = price.id
        AuditLog.objects.all().delete()

        self.authenticate(self.super_admin)
        response = self.client.delete(
            price_detail_url(self.customer.id, price_id)
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        log = AuditLog.objects.filter(
            target_model="extra_work.CustomerServicePrice",
            target_id=price_id,
            action=AuditAction.DELETE,
        ).get()
        self.assertEqual(log.changes["unit_price"]["before"], "40.00")
        self.assertIsNone(log.changes["unit_price"]["after"])
