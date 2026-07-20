"""Shared fixture for the M4 billing tests.

Sprint history: this module once tested the provider-only bulk
mark-/clear-invoiced run (mark/un-mark `is_invoiced` by company+month).
Invoicing Phase 2a (Option 1) made the INVOICE the single source of
"invoiced", so those endpoints became DEPRECATED NO-OPS; Phase 4b (the
Facturen UI) REMOVED them entirely along with their tests.

The `_InvoiceRunFixture` (+ `_mk` / `_dt` helpers) is retained here because
the billing-LIST tests (`test_m4_billing_list`) and the billing-audit tests
(`audit.tests.test_sprint109_billing_audit`) still build on it — both import
it from this module. It carries no test cases of its own.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
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
from tickets.models import Ticket


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


def _dt(year: int, month: int, day: int) -> datetime:
    # Noon UTC so .date() never rolls into an adjacent day under any TZ.
    return datetime(year, month, day, 12, 0, tzinfo=timezone.utc)


class _InvoiceRunFixture(TestCase):
    """Two provider companies (A + B), each with a building/customer/admin,
    plus a customer user on A. `_make_ew_with_ticket` builds an EW and its
    spawned operational ticket so a test has something earned to bucket."""

    @classmethod
    def setUpTestData(cls):
        # --- Company A ---
        cls.company = Company.objects.create(name="Prov A", slug="prov-a-m4c")
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
            "super-m4c@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-m4c@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )
        cls.customer_user = _mk("cust-m4c@example.com", UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.customer_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        # --- Company B (separate tenant + admin) ---
        cls.company_b = Company.objects.create(name="Prov B", slug="prov-b-m4c")
        cls.building_b = Building.objects.create(
            company=cls.company_b, name="B-Building"
        )
        cls.customer_b = Customer.objects.create(
            company=cls.company_b, name="Customer B", building=cls.building_b
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_b, building=cls.building_b
        )
        cls.admin_b = _mk("admin-b-m4c@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin_b, company=cls.company_b
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _make_ew_with_ticket(
        self,
        *,
        ticket_status,
        closed_at,
        invoice_date=None,
        is_invoiced=False,
        company=None,
        building=None,
        customer=None,
        created_by=None,
    ):
        """Create an EW plus its spawned operational Ticket
        (Ticket.extra_work_request=ew). Defaults to Company A."""
        company = company or self.company
        building = building or self.building
        customer = customer or self.customer
        created_by = created_by or self.admin
        ew = ExtraWorkRequest.objects.create(
            company=company,
            building=building,
            customer=customer,
            created_by=created_by,
            title="Run EW",
            description="customer-visible description",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            subtotal_amount=Decimal("100.00"),
            vat_amount=Decimal("21.00"),
            total_amount=Decimal("121.00"),
            invoice_date=invoice_date,
            is_invoiced=is_invoiced,
        )
        Ticket.objects.create(
            company=company,
            building=building,
            customer=customer,
            created_by=created_by,
            title="Spawned operational ticket",
            description="op ticket",
            status=ticket_status,
            closed_at=closed_at,
            extra_work_request=ew,
        )
        return ew
