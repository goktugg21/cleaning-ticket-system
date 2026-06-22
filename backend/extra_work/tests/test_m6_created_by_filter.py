"""M6.3 — Extra Work list `?created_by=` filter.

The dashboard "my work" summary fetches the signed-in user's own
extra-work and quote-requests, e.g.
`GET /api/extra-work/?created_by=<me>` and
`GET /api/extra-work/?created_by=<me>&request_intent=REQUEST_QUOTE`.
`created_by` is a FK on ExtraWorkRequest, exposed via
ExtraWorkRequestFilter (exact), so django-filter validates the value
and 400s on a non-integer — consistent with the other filterset
fields. Scope is enforced server-side by `scope_extra_work_for`
before the filter narrows.

Fixture style mirrors test_m6_request_intent_filter.py.
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


class CreatedByFilterTests(TestCase):
    """One provider company A with two staff creators; a SUPER_ADMIN
    (sees everything) drives the list so the created_by filter is
    exercised in isolation from scope narrowing."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov A", slug="prov-a-m63")
        cls.building = Building.objects.create(
            company=cls.company, name="A-Building"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer A", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.super_admin = _mk(
            "super-m63@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.creator1 = _mk("creator1-m63@example.com", UserRole.COMPANY_ADMIN)
        cls.creator2 = _mk("creator2-m63@example.com", UserRole.COMPANY_ADMIN)
        for u in (cls.creator1, cls.creator2):
            CompanyUserMembership.objects.create(user=u, company=cls.company)

        # creator1: one quote-intent + one order-intent request.
        cls.quote_c1 = cls._mk_ew(
            cls.creator1, ExtraWorkRequestIntent.REQUEST_QUOTE, "Quote C1"
        )
        cls.order_c1 = cls._mk_ew(
            cls.creator1,
            ExtraWorkRequestIntent.DIRECT_AGREED_PRICE_ORDER,
            "Order C1",
        )
        # creator2: one quote-intent request.
        cls.quote_c2 = cls._mk_ew(
            cls.creator2, ExtraWorkRequestIntent.REQUEST_QUOTE, "Quote C2"
        )

    @classmethod
    def _mk_ew(cls, created_by, intent, title):
        return ExtraWorkRequest.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=created_by,
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

    def test_created_by_returns_only_that_users_requests(self):
        resp = self._api(self.super_admin).get(
            LIST_URL, {"created_by": self.creator1.id}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = {r["id"] for r in resp.data["results"]}
        self.assertEqual(ids, {self.quote_c1.id, self.order_c1.id})
        self.assertNotIn(self.quote_c2.id, ids)

    def test_created_by_and_request_intent_compose(self):
        resp = self._api(self.super_admin).get(
            LIST_URL,
            {
                "created_by": self.creator1.id,
                "request_intent": "REQUEST_QUOTE",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = {r["id"] for r in resp.data["results"]}
        # Only creator1's quote request — creator1's order and
        # creator2's quote excluded.
        self.assertEqual(ids, {self.quote_c1.id})
        self.assertNotIn(self.order_c1.id, ids)
        self.assertNotIn(self.quote_c2.id, ids)

    def test_bad_created_by_is_rejected_cleanly_not_500(self):
        resp = self._api(self.super_admin).get(
            LIST_URL, {"created_by": "NONSENSE"}
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotEqual(resp.status_code, 500)
