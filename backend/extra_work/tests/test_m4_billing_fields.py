"""
M4 commit 2a — billing-month fields on the EW detail endpoint.

`invoice_date`, `is_invoiced`, `invoiced_at` are provider-only billing
metadata (SoT A.4, monthly invoice run). They join `_PROVIDER_ONLY_FIELDS`
on `ExtraWorkRequestDetailSerializer`, so they are exposed to PROVIDER
operators (SUPER_ADMIN / COMPANY_ADMIN) but stripped for CUSTOMER_USER —
the same redaction path as `manager_note` / `internal_cost_note`
(see test_b7_note_privacy_regression.py).

This commit exposes the fields read-only; provider writability lands in
2b, so these tests assert presence/absence of the KEYS only, not
read-only-ness.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import Building
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"

_BILLING_KEYS = ("invoice_date", "is_invoiced", "invoiced_at")


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class _M4BillingFixture(TestCase):
    """One provider company, one building, one customer, and one EW that
    carries billing-month metadata so a provider response includes it and
    a customer response must not."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov M4", slug="prov-m4")
        cls.building = Building.objects.create(
            company=cls.company, name="M4-Building"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer M4", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            "super-m4@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-m4@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

        cls.customer_user = _mk(
            "cust-m4@example.com", UserRole.CUSTOMER_USER
        )
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.customer_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        cls.ew = ExtraWorkRequest.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.customer_user,
            title="M4 EW",
            description="customer-visible description",
            status=ExtraWorkStatus.PRICING_PROPOSED,
            subtotal_amount=Decimal("100.00"),
            vat_amount=Decimal("21.00"),
            total_amount=Decimal("121.00"),
            invoice_date=date(2026, 5, 31),
            is_invoiced=True,
            invoiced_at=datetime(2026, 6, 7, 9, 0, tzinfo=timezone.utc),
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c


class M4BillingFieldVisibilityTests(_M4BillingFixture):
    def test_provider_sees_billing_keys(self):
        for actor in (self.super_admin, self.admin):
            response = self._api(actor).get(
                f"/api/extra-work/{self.ew.id}/"
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            for key in _BILLING_KEYS:
                self.assertIn(
                    key,
                    response.data,
                    f"provider should see {key}",
                )

    def test_customer_does_not_see_billing_keys(self):
        response = self._api(self.customer_user).get(
            f"/api/extra-work/{self.ew.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for key in _BILLING_KEYS:
            self.assertNotIn(
                key,
                response.data,
                f"customer must not see {key}",
            )


class M4BillingPatchTests(_M4BillingFixture):
    """M4 commit 2b — PATCH /api/extra-work/<id>/billing sets or clears the
    EW's invoice_date (billing month). Provider-only: a CUSTOMER_USER gets
    403 and the value is untouched. invoice_date is decoupled from the
    customer-decision timestamps, so no EW-status gate applies."""

    def _url(self) -> str:
        return f"/api/extra-work/{self.ew.id}/billing/"

    def test_provider_sets_invoice_date(self):
        # Start from a known-clear state so the PATCH provably writes the
        # value rather than coinciding with the fixture seed.
        self.ew.invoice_date = None
        self.ew.save(update_fields=["invoice_date"])

        response = self._api(self.admin).patch(
            self._url(), {"invoice_date": "2026-05-31"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ew.refresh_from_db()
        self.assertEqual(self.ew.invoice_date, date(2026, 5, 31))

    def test_provider_clears_invoice_date(self):
        # Fixture seeds invoice_date=2026-05-31; null clears it.
        response = self._api(self.super_admin).patch(
            self._url(), {"invoice_date": None}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ew.refresh_from_db()
        self.assertIsNone(self.ew.invoice_date)

    def test_customer_cannot_set_invoice_date(self):
        response = self._api(self.customer_user).patch(
            self._url(), {"invoice_date": "2026-05-31"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.ew.refresh_from_db()
        # Unchanged from the fixture seed.
        self.assertEqual(self.ew.invoice_date, date(2026, 5, 31))

    def test_invalid_date_is_400(self):
        response = self._api(self.admin).patch(
            self._url(), {"invoice_date": "not-a-date"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_key_is_400(self):
        response = self._api(self.admin).patch(
            self._url(), {}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
