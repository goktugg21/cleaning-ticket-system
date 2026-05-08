"""
Sprint 5 — CSV / PDF export coverage for tickets-by-{type,customer,building}.

For each dimension we assert:
- Content-Type header.
- Content-Disposition contains a sane filename.
- CSV header row matches the exact documented column list.
- CSV row count equals the equivalent JSON endpoint's bucket count
  (the export reuses the same `compute_*` payload, so the CSV cannot
  drift away from the JSON unless someone removes columns by hand).
- PDF body is non-empty and starts with `%PDF-`.
"""
import csv
import io

from rest_framework import status
from rest_framework.test import APITestCase

from buildings.models import Building, BuildingManagerAssignment
from customers.models import Customer, CustomerUserMembership
from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketType


URL_TYPE_JSON = "/api/reports/tickets-by-type/"
URL_TYPE_CSV = "/api/reports/tickets-by-type/export.csv"
URL_TYPE_PDF = "/api/reports/tickets-by-type/export.pdf"

URL_CUSTOMER_JSON = "/api/reports/tickets-by-customer/"
URL_CUSTOMER_CSV = "/api/reports/tickets-by-customer/export.csv"
URL_CUSTOMER_PDF = "/api/reports/tickets-by-customer/export.pdf"

URL_BUILDING_JSON = "/api/reports/tickets-by-building/"
URL_BUILDING_CSV = "/api/reports/tickets-by-building/export.csv"
URL_BUILDING_PDF = "/api/reports/tickets-by-building/export.pdf"


class _ExportBase(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="A complaint",
            description="d",
            type=TicketType.COMPLAINT,
        )
        Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="A request",
            description="d",
            type=TicketType.REQUEST,
        )
        # Second building so by-building / by-customer have multiple
        # rows to compare against.
        self.second_building = Building.objects.create(
            company=self.company, name="Second Building", address="x"
        )
        BuildingManagerAssignment.objects.create(
            building=self.second_building, user=self.manager
        )
        self.customer_at_second_building = Customer.objects.create(
            company=self.company,
            building=self.second_building,
            name=self.customer.name,
            contact_email="x@example.com",
        )
        CustomerUserMembership.objects.create(
            customer=self.customer_at_second_building, user=self.customer_user
        )
        Ticket.objects.create(
            company=self.company,
            building=self.second_building,
            customer=self.customer_at_second_building,
            created_by=self.customer_user,
            title="At second building",
            description="d",
            type=TicketType.REQUEST,
        )

    def _csv_rows(self, response):
        # Strip the BOM and parse.
        text = response.content.decode("utf-8")
        if text.startswith("﻿"):
            text = text[1:]
        reader = csv.DictReader(io.StringIO(text))
        return reader.fieldnames, list(reader)


# ===========================================================================
# tickets-by-type CSV / PDF
# ===========================================================================


class TicketsByTypeExportTests(_ExportBase):
    EXPECTED_HEADERS = [
        "ticket_type",
        "ticket_type_label",
        "count",
        "period_from",
        "period_to",
    ]

    def test_csv_unauthenticated_returns_401(self):
        response = self.client.get(URL_TYPE_CSV)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_csv_customer_user_returns_403(self):
        self.client.force_authenticate(user=self.customer_user)
        response = self.client.get(URL_TYPE_CSV)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_csv_response_shape(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_TYPE_CSV)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        self.assertIn("filename=", response["Content-Disposition"])
        self.assertIn("tickets-by-type", response["Content-Disposition"])
        headers, rows = self._csv_rows(response)
        self.assertEqual(headers, self.EXPECTED_HEADERS)

        # Compare row count to the JSON endpoint that ran from the same
        # filters (no filters here, so the default last-30-days window).
        json_response = self.client.get(URL_TYPE_JSON)
        self.assertEqual(len(rows), len(json_response.data["buckets"]))

    def test_pdf_response_shape(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_TYPE_PDF)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("filename=", response["Content-Disposition"])
        self.assertGreater(len(response.content), 0)
        self.assertTrue(response.content.startswith(b"%PDF-"))


# ===========================================================================
# tickets-by-customer CSV / PDF
# ===========================================================================


class TicketsByCustomerExportTests(_ExportBase):
    EXPECTED_HEADERS = [
        "customer_id",
        "customer_name",
        "building_id",
        "building_name",
        "company_id",
        "company_name",
        "count",
        "period_from",
        "period_to",
    ]

    def test_csv_response_shape(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_CUSTOMER_CSV)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        self.assertIn("filename=", response["Content-Disposition"])
        headers, rows = self._csv_rows(response)
        self.assertEqual(headers, self.EXPECTED_HEADERS)
        # Row count matches JSON.
        json_response = self.client.get(URL_CUSTOMER_JSON)
        self.assertEqual(len(rows), len(json_response.data["buckets"]))

    def test_csv_includes_building_name_for_disambiguation(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_CUSTOMER_CSV)
        _, rows = self._csv_rows(response)
        same_name = [r for r in rows if r["customer_name"] == self.customer.name]
        # Two customer-locations share the name; the building_name
        # column keeps them visibly distinct.
        self.assertEqual(len(same_name), 2)
        building_names = {r["building_name"] for r in same_name}
        self.assertEqual(
            building_names, {self.building.name, self.second_building.name}
        )

    def test_pdf_response_shape(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_CUSTOMER_PDF)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertGreater(len(response.content), 0)
        self.assertTrue(response.content.startswith(b"%PDF-"))


# ===========================================================================
# tickets-by-building CSV / PDF
# ===========================================================================


class TicketsByBuildingExportTests(_ExportBase):
    EXPECTED_HEADERS = [
        "building_id",
        "building_name",
        "company_id",
        "company_name",
        "count",
        "period_from",
        "period_to",
    ]

    def test_csv_response_shape(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_BUILDING_CSV)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        headers, rows = self._csv_rows(response)
        self.assertEqual(headers, self.EXPECTED_HEADERS)
        json_response = self.client.get(URL_BUILDING_JSON)
        self.assertEqual(len(rows), len(json_response.data["buckets"]))

    def test_csv_company_admin_scope_isolation(self):
        # Company admin must not see Company B's building bucket.
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL_BUILDING_CSV)
        _, rows = self._csv_rows(response)
        ids = {int(r["building_id"]) for r in rows}
        self.assertNotIn(self.other_building.id, ids)

    def test_pdf_response_shape(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_BUILDING_PDF)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertGreater(len(response.content), 0)
        self.assertTrue(response.content.startswith(b"%PDF-"))
