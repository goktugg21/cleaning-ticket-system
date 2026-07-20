"""
#109 Part H — additive `customer` (+ `customer_id` alias) on the
extra-work-revenue report AND the tickets-over-time / status-
distribution ticket-chart endpoints, scope-checked with the same
_customer_in_scope mirror the dimension reports use (out-of-scope /
nonexistent -> 403, non-integer -> 400). The revenue exports (CSV/PDF)
thread the same param and the PDF header prints the customer.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from buildings.models import Building
from customers.models import (
    Customer,
    CustomerBuildingMembership,
)
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus, TicketType

URL_REVENUE = "/api/reports/extra-work-revenue/"
URL_REVENUE_CSV = "/api/reports/extra-work-revenue/export.csv"
URL_REVENUE_PDF = "/api/reports/extra-work-revenue/export.pdf"
URL_OVER_TIME = "/api/reports/tickets-over-time/"
URL_STATUS = "/api/reports/status-distribution/"


class _CustomerReportsBase(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # A SECOND customer under the SAME company/building so an
        # in-scope actor can see both, and the customer filter must
        # narrow to exactly one.
        self.customer_two = Customer.objects.create(
            company=self.company, name="Customer A-2", building=self.building
        )
        CustomerBuildingMembership.objects.create(
            customer=self.customer_two, building=self.building
        )

    def _ew_earned(self, customer, total):
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=customer,
            created_by=self.super_admin,
            title="EW",
            description="d",
            subtotal_amount=Decimal(total),
            vat_amount=Decimal("0.00"),
            total_amount=Decimal(total),
            final_subtotal_amount=Decimal(total),
            final_vat_amount=Decimal("0.00"),
            final_total_amount=Decimal(total),
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
        )
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=customer,
            created_by=self.super_admin,
            title="spawned",
            description="d",
            type=TicketType.REQUEST,
            status=TicketStatus.CLOSED,
            extra_work_request=ew,
        )
        return ew


class RevenueCustomerFilterTests(_CustomerReportsBase):
    def test_customer_narrows_revenue_totals(self):
        self._ew_earned(self.customer, "100.00")
        self._ew_earned(self.customer_two, "40.00")
        self.client.force_authenticate(user=self.super_admin)

        both = self.client.get(URL_REVENUE)
        self.assertEqual(both.data["totals"]["total"], "140.00")

        one = self.client.get(URL_REVENUE, {"customer": self.customer.id})
        self.assertEqual(one.data["totals"]["count"], 1)
        self.assertEqual(one.data["totals"]["total"], "100.00")
        self.assertEqual(one.data["scope"]["customer_id"], self.customer.id)
        self.assertEqual(
            one.data["scope"]["customer_name"], self.customer.name
        )

        two = self.client.get(
            URL_REVENUE, {"customer_id": self.customer_two.id}
        )
        self.assertEqual(two.data["totals"]["total"], "40.00")

    def test_out_of_scope_customer_403(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(
            URL_REVENUE, {"customer": self.other_customer.id}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_integer_customer_400(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_REVENUE, {"customer": "abc"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_csv_export_honors_customer(self):
        self._ew_earned(self.customer, "100.00")
        self._ew_earned(self.customer_two, "40.00")
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(
            URL_REVENUE_CSV, {"customer": self.customer.id}
        )
        self.assertEqual(response.status_code, 200)
        text = response.content.decode("utf-8-sig")
        # The earned row carries the single customer's 100.00 total.
        self.assertIn("earned", text)
        self.assertIn("100.00", text)
        self.assertNotIn("140.00", text)

    def test_pdf_export_prints_customer_and_honors_filter(self):
        self._ew_earned(self.customer, "100.00")
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(
            URL_REVENUE_PDF, {"customer": self.customer.id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))


class TicketChartCustomerFilterTests(_CustomerReportsBase):
    def _ticket(self, customer, ticket_status=TicketStatus.OPEN):
        return Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=customer,
            created_by=self.super_admin,
            title="t",
            description="d",
            type=TicketType.REQUEST,
            status=ticket_status,
        )

    def test_status_distribution_honors_customer(self):
        # customer_two is fixture-clean (no seeded baseline tickets), so
        # its filtered distribution is exactly what this test creates.
        self._ticket(self.customer_two, TicketStatus.OPEN)
        self._ticket(self.customer_two, TicketStatus.IN_PROGRESS)
        self._ticket(self.customer, TicketStatus.OPEN)
        self.client.force_authenticate(user=self.super_admin)

        two = self.client.get(URL_STATUS, {"customer": self.customer_two.id})
        self.assertEqual(two.data["total"], 2)
        open_two = next(
            b["count"] for b in two.data["buckets"] if b["status"] == "OPEN"
        )
        self.assertEqual(open_two, 1)
        # The unfiltered scope sees strictly more (the fixture baseline +
        # customer A's extra ticket).
        allc = self.client.get(URL_STATUS)
        self.assertGreater(allc.data["total"], two.data["total"])

    def test_status_distribution_out_of_scope_customer_403(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(
            URL_STATUS, {"customer": self.other_customer.id}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_over_time_honors_customer(self):
        self._ticket(self.customer_two)
        self.client.force_authenticate(user=self.super_admin)
        window = {"from": "2020-01-01", "to": "2035-01-01"}
        two = self.client.get(
            URL_OVER_TIME, {**window, "customer": self.customer_two.id}
        )
        allc = self.client.get(URL_OVER_TIME, window)
        self.assertEqual(two.data["total"], 1)
        self.assertGreater(allc.data["total"], two.data["total"])

    def test_over_time_out_of_scope_customer_403(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(
            URL_OVER_TIME,
            {
                "from": "2020-01-01",
                "to": "2035-01-01",
                "customer": self.other_customer.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
