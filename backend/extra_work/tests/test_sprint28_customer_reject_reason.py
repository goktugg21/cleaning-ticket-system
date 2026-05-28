"""
Sprint 28 Batch 15.4 — customer reject-reason validator on the Extra
Work transition endpoint.

Locks:
  * CUSTOMER_USER POST {to_status: CUSTOMER_REJECTED} WITHOUT
    `customer_reject_reason` -> HTTP 400 with error key
    `customer_reject_reason`.
  * CUSTOMER_USER POST with a non-blank reason -> HTTP 200; the EW
    advances to CUSTOMER_REJECTED and the reason is threaded into the
    status-history `note` so it surfaces on the existing timeline UI
    (no new migration column).
  * SUPER_ADMIN provider-override path (is_override=True +
    override_reason) -> HTTP 200; the new validator does NOT require
    `customer_reject_reason` because the override path has its own
    mandatory `override_reason`.
  * Whitespace-only `customer_reject_reason` (e.g. "   ") -> HTTP 400.
    The `.strip()` rejects blank reasons.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from extra_work.models import (
    ExtraWorkCategory,
    ExtraWorkPricingLineItem,
    ExtraWorkRequest,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class CustomerRejectReasonFixtureMixin:
    @classmethod
    def _setup_fixture(cls):
        cls.company = Company.objects.create(
            name="Reject Provider", slug="reject-b154"
        )
        cls.building = Building.objects.create(
            company=cls.company, name="Building-Reject"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            name="Customer-Reject",
            building=cls.building,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            "super-reject@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-reject@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

        cls.cust_user = _mk("cust-reject@example.com", UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building,
            access_role=(
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER
            ),
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _make_priced_ew(self):
        """EW sitting in PRICING_PROPOSED so the
        customer-driven CUSTOMER_REJECTED transition is reachable."""
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title="Reject test EW",
            description="placeholder",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.UNDER_REVIEW,
        )
        ExtraWorkPricingLineItem.objects.create(
            extra_work=ew,
            description="Crew",
            unit_type="FIXED",
            quantity=Decimal("1"),
            unit_price=Decimal("100"),
            vat_rate=Decimal("21"),
        )
        # Drive into PRICING_PROPOSED via the admin transition path so
        # the EW is in the state where customer approve/reject is
        # allowed by the state machine.
        response = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/transition/",
            {"to_status": ExtraWorkStatus.PRICING_PROPOSED},
            format="json",
        )
        assert response.status_code == 200, response.content
        ew.refresh_from_db()
        return ew


class CustomerRejectReasonRequiredTests(
    CustomerRejectReasonFixtureMixin, TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def test_customer_reject_without_reason_returns_400(self):
        ew = self._make_priced_ew()
        response = self._api(self.cust_user).post(
            f"/api/extra-work/{ew.id}/transition/",
            {"to_status": ExtraWorkStatus.CUSTOMER_REJECTED},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("customer_reject_reason", response.data)
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.PRICING_PROPOSED)

    def test_customer_reject_with_whitespace_only_reason_returns_400(self):
        ew = self._make_priced_ew()
        response = self._api(self.cust_user).post(
            f"/api/extra-work/{ew.id}/transition/",
            {
                "to_status": ExtraWorkStatus.CUSTOMER_REJECTED,
                "customer_reject_reason": "   ",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("customer_reject_reason", response.data)
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.PRICING_PROPOSED)

    def test_customer_reject_with_reason_succeeds_and_persists_note(self):
        ew = self._make_priced_ew()
        reason = "Too expensive — please reduce the crew time."
        response = self._api(self.cust_user).post(
            f"/api/extra-work/{ew.id}/transition/",
            {
                "to_status": ExtraWorkStatus.CUSTOMER_REJECTED,
                "customer_reject_reason": reason,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_REJECTED)

        # Reason persisted into the status-history note so it surfaces
        # on the existing customer-visible timeline UI without a new
        # column.
        last_history = (
            ExtraWorkStatusHistory.objects.filter(
                extra_work=ew, new_status=ExtraWorkStatus.CUSTOMER_REJECTED
            )
            .order_by("-created_at")
            .first()
        )
        self.assertIsNotNone(last_history)
        self.assertIn(reason, last_history.note)

    def test_provider_override_does_not_require_customer_reject_reason(self):
        ew = self._make_priced_ew()
        response = self._api(self.super_admin).post(
            f"/api/extra-work/{ew.id}/transition/",
            {
                "to_status": ExtraWorkStatus.CUSTOMER_REJECTED,
                "is_override": True,
                "override_reason": "Customer abandoned the request",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CUSTOMER_REJECTED)
