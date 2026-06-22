"""M6.2 — Extra Work list `?request_intent=` filter.

The provider customer-detail quote-requests sub-tab fetches
`GET /api/extra-work/?customer=<id>&request_intent=REQUEST_QUOTE`.
`request_intent` is a plain CharField with choices on ExtraWorkRequest,
exposed via ExtraWorkRequestFilter (exact/in), so django-filter
validates the value and 400s on a bad one — consistent with the other
filterset fields. Scope is enforced server-side by
`scope_extra_work_for` before the filter narrows.

Fixture style mirrors test_m4_billing_run.py.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import Building
from companies.models import Company, CompanyUserMembership
from customers.models import Customer, CustomerBuildingMembership
from extra_work.models import (
    ExtraWorkRequest,
    ExtraWorkRequestIntent,
    ExtraWorkStatus,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
LIST_URL = "/api/extra-work/"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class RequestIntentFilterTests(TestCase):
    """One provider company A with two in-scope customers; a SUPER_ADMIN
    (sees everything) drives the list so the filter is exercised in
    isolation from scope narrowing."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov A", slug="prov-a-m6")
        cls.building = Building.objects.create(
            company=cls.company, name="A-Building"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer A", building=cls.building
        )
        cls.customer2 = Customer.objects.create(
            company=cls.company, name="Customer A2", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer2, building=cls.building
        )
        cls.super_admin = _mk(
            "super-m6@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-m6@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

        # customer A: one quote-intent request + one non-quote request.
        cls.quote_a = cls._mk_ew(
            cls.customer, ExtraWorkRequestIntent.REQUEST_QUOTE, "Quote A"
        )
        cls.order_a = cls._mk_ew(
            cls.customer,
            ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            "Order A",
        )
        # customer A2: one quote-intent request.
        cls.quote_a2 = cls._mk_ew(
            cls.customer2, ExtraWorkRequestIntent.REQUEST_QUOTE, "Quote A2"
        )

    @classmethod
    def _mk_ew(cls, customer, intent, title):
        return ExtraWorkRequest.objects.create(
            company=cls.company,
            building=cls.building,
            customer=customer,
            created_by=cls.super_admin,
            title=title,
            description="customer-visible description",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            request_intent=intent,
            subtotal_amount=Decimal("100.00"),
            vat_amount=Decimal("21.00"),
            total_amount=Decimal("121.00"),
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_request_intent_returns_only_quote_requests(self):
        resp = self._api(self.super_admin).get(
            LIST_URL, {"request_intent": "REQUEST_QUOTE"}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = {r["id"] for r in resp.data["results"]}
        self.assertEqual(ids, {self.quote_a.id, self.quote_a2.id})
        self.assertNotIn(self.order_a.id, ids)

    def test_customer_and_request_intent_compose(self):
        resp = self._api(self.super_admin).get(
            LIST_URL,
            {"customer": self.customer.id, "request_intent": "REQUEST_QUOTE"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = {r["id"] for r in resp.data["results"]}
        # Only customer A's quote request — A's order and A2's quote excluded.
        self.assertEqual(ids, {self.quote_a.id})
        self.assertNotIn(self.order_a.id, ids)
        self.assertNotIn(self.quote_a2.id, ids)

    def test_bad_request_intent_is_rejected_cleanly_not_500(self):
        resp = self._api(self.super_admin).get(
            LIST_URL, {"request_intent": "NONSENSE"}
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotEqual(resp.status_code, 500)
