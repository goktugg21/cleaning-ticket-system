"""M4 invoice run — mark-invoiced / clear-invoiced.

Sprint history: these provider-only bulk endpoints once marked/un-marked
`is_invoiced` on earned EW by company+month. Invoicing Phase 2a (Option 1)
made the INVOICE the single source of "invoiced" (a row is invoiced iff a
live InvoiceLine claims it), so these two endpoints are now DEPRECATED
NO-OPS: the routes, the provider-operator gate, the param validation, and
the response SHAPE are kept ONLY so the deployed Facturen page keeps working
— but they no longer mutate is_invoiced/invoiced_at. Endpoint + old Facturen
page are removed together in Phase 4.

These tests therefore assert the NO-OP contract: a provider gets HTTP 200
with a zero count and NOTHING changes; a non-operator still gets 403; bad
params still 400.
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
from tickets.models import Ticket, TicketStatus


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"

MARK_URL = "/api/extra-work/mark-invoiced/"
CLEAR_URL = "/api/extra-work/clear-invoiced/"


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
    spawned operational ticket so the run has something earned to bucket."""

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


class MarkInvoicedNoOpTests(_InvoiceRunFixture):
    def test_mark_is_noop_returns_zero(self):
        # Earned May 31: pre-Option-1 this marked 1. Now it is a no-op —
        # HTTP 200, zero count, and is_invoiced is NOT set.
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 5, 31)
        )
        resp = self._api(self.admin).post(
            MARK_URL,
            {"company": self.company.id, "year": 2026, "month": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["invoiced_count"], 0)
        self.assertEqual(resp.data["ew_ids"], [])
        ew.refresh_from_db()
        self.assertFalse(ew.is_invoiced)
        self.assertIsNone(ew.invoiced_at)

    def test_mark_noop_ignores_invoice_date(self):
        # Even with an invoice_date override that would once have bucketed to
        # June, the no-op mutates nothing.
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED,
            closed_at=_dt(2026, 5, 31),
            invoice_date=date(2026, 6, 15),
        )
        resp = self._api(self.admin).post(
            MARK_URL,
            {"company": self.company.id, "year": 2026, "month": 6},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["invoiced_count"], 0)
        ew.refresh_from_db()
        self.assertFalse(ew.is_invoiced)

    def test_mark_does_not_clear_a_preset_invoiced_row(self):
        # A legacy-settled row (is_invoiced=True) is untouched by the no-op.
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED,
            closed_at=_dt(2026, 5, 31),
            is_invoiced=True,
        )
        resp = self._api(self.admin).post(
            MARK_URL,
            {"company": self.company.id, "year": 2026, "month": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["invoiced_count"], 0)
        ew.refresh_from_db()
        self.assertTrue(ew.is_invoiced)  # unchanged

    def test_customer_forbidden(self):
        # Provider gate is retained.
        resp = self._api(self.customer_user).post(
            MARK_URL,
            {"company": self.company.id, "year": 2026, "month": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class ClearInvoicedNoOpTests(_InvoiceRunFixture):
    def test_clear_is_noop_leaves_invoiced_state(self):
        # Seed an already-invoiced row; clear-invoiced no longer un-marks it.
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED,
            closed_at=_dt(2026, 5, 31),
            is_invoiced=True,
        )
        resp = self._api(self.admin).post(
            CLEAR_URL,
            {"company": self.company.id, "year": 2026, "month": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["cleared_count"], 0)
        self.assertEqual(resp.data["ew_ids"], [])
        ew.refresh_from_db()
        self.assertTrue(ew.is_invoiced)  # unchanged

    def test_customer_forbidden(self):
        resp = self._api(self.customer_user).post(
            CLEAR_URL,
            {"company": self.company.id, "year": 2026, "month": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class InvoiceRunParamTests(_InvoiceRunFixture):
    def test_missing_company_is_400(self):
        resp = self._api(self.admin).post(
            MARK_URL,
            {"year": 2026, "month": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_month_out_of_range_is_400(self):
        resp = self._api(self.admin).post(
            MARK_URL,
            {"company": self.company.id, "year": 2026, "month": 13},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
