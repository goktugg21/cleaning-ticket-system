"""M4 commit 2c — the Extra Work invoice run (mark-invoiced / clear-invoiced).

POST /api/extra-work/mark-invoiced and /clear-invoiced let a provider operator
mark (or un-mark) every EARNED, not-yet-invoiced EW that bills in a given
company+month. Billing month = COALESCE(invoice_date, spawned-ticket
closed_at); "earned" == the spawned operational ticket is CLOSED. The run is
provider-only, scoped via scope_extra_work_for (a company the caller cannot
see marks 0), and idempotent.

Fixture/style mirrors test_m4_billing_fields.py; the spawned operational
Ticket follows the Ticket.objects.create pattern from
test_sprint6_one_ticket_per_request.py.
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


class MarkInvoicedTests(_InvoiceRunFixture):
    def test_headline_marks_in_completion_month(self):
        # Earned (ticket CLOSED) May 31, no invoice_date override.
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 5, 31)
        )
        resp = self._api(self.admin).post(
            MARK_URL,
            {"company": self.company.id, "year": 2026, "month": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["invoiced_count"], 1)
        self.assertIn(ew.id, resp.data["ew_ids"])
        ew.refresh_from_db()
        self.assertTrue(ew.is_invoiced)
        self.assertIsNotNone(ew.invoiced_at)

    def test_does_not_mark_in_approval_month(self):
        # The run buckets by COMPLETION month (May), never the approval
        # month — a June run must not touch a May-completed EW.
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 5, 31)
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

    def test_invoice_date_override_wins(self):
        # Earned May 31 but provider set invoice_date=Jun 15: bills in June.
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED,
            closed_at=_dt(2026, 5, 31),
            invoice_date=date(2026, 6, 15),
        )
        may = self._api(self.admin).post(
            MARK_URL,
            {"company": self.company.id, "year": 2026, "month": 5},
            format="json",
        )
        self.assertEqual(may.data["invoiced_count"], 0)

        jun = self._api(self.admin).post(
            MARK_URL,
            {"company": self.company.id, "year": 2026, "month": 6},
            format="json",
        )
        self.assertEqual(jun.data["invoiced_count"], 1)
        self.assertIn(ew.id, jun.data["ew_ids"])
        ew.refresh_from_db()
        self.assertTrue(ew.is_invoiced)

    def test_not_earned_excluded(self):
        # Ticket NOT closed (OPEN) => not earned. invoice_date resolves to
        # May, but the run still excludes it because it is not earned.
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.OPEN,
            closed_at=None,
            invoice_date=date(2026, 5, 10),
        )
        resp = self._api(self.admin).post(
            MARK_URL,
            {"company": self.company.id, "year": 2026, "month": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["invoiced_count"], 0)
        ew.refresh_from_db()
        self.assertFalse(ew.is_invoiced)

    def test_idempotent(self):
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 5, 31)
        )
        first = self._api(self.admin).post(
            MARK_URL,
            {"company": self.company.id, "year": 2026, "month": 5},
            format="json",
        )
        self.assertEqual(first.data["invoiced_count"], 1)
        self.assertIn(ew.id, first.data["ew_ids"])

        second = self._api(self.admin).post(
            MARK_URL,
            {"company": self.company.id, "year": 2026, "month": 5},
            format="json",
        )
        self.assertEqual(second.data["invoiced_count"], 0)

    def test_customer_forbidden(self):
        resp = self._api(self.customer_user).post(
            MARK_URL,
            {"company": self.company.id, "year": 2026, "month": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_other_company_marks_zero(self):
        # Company B has its own earned-in-May EW. The Company-A admin asking
        # to invoice company=B marks 0 — B's EW is outside A's scope (H-1).
        ew_b = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED,
            closed_at=_dt(2026, 5, 31),
            company=self.company_b,
            building=self.building_b,
            customer=self.customer_b,
            created_by=self.admin_b,
        )
        resp = self._api(self.admin).post(
            MARK_URL,
            {"company": self.company_b.id, "year": 2026, "month": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["invoiced_count"], 0)
        ew_b.refresh_from_db()
        self.assertFalse(ew_b.is_invoiced)


class ClearInvoicedTests(_InvoiceRunFixture):
    def test_clear_reverses_mark(self):
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 5, 31)
        )
        mark = self._api(self.admin).post(
            MARK_URL,
            {"company": self.company.id, "year": 2026, "month": 5},
            format="json",
        )
        self.assertEqual(mark.data["invoiced_count"], 1)
        ew.refresh_from_db()
        self.assertTrue(ew.is_invoiced)
        self.assertIsNotNone(ew.invoiced_at)

        clear = self._api(self.admin).post(
            CLEAR_URL,
            {"company": self.company.id, "year": 2026, "month": 5},
            format="json",
        )
        self.assertEqual(clear.status_code, status.HTTP_200_OK)
        self.assertEqual(clear.data["cleared_count"], 1)
        self.assertIn(ew.id, clear.data["ew_ids"])
        ew.refresh_from_db()
        self.assertFalse(ew.is_invoiced)
        self.assertIsNone(ew.invoiced_at)


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
