"""
Sprint 124 — Extra Work revenue grouped by building.

`compute_extra_work_revenue_by_building` shares
`_resolve_extra_work_revenue_rows` (scope/customer/date-window
resolution + the in-scope ExtraWorkRequest queryset + ticket map) and the
per-row `_classify_extra_work` / `_amounts_for_state` functions with the
flat `compute_extra_work_revenue` — the only difference is the
accumulator key (building_id instead of revenue state). The tests below
exist to PROVE that sharing actually holds: the by-building buckets must
sum to exactly the flat report's total for the same filters.

Reuses the TenantFixtureMixin + the `_ew` / `_spawn` fixture-builder
conventions from test_sprint14a_origin_and_revenue.py.
"""
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import Building, BuildingManagerAssignment
from customers.models import CustomerBuildingMembership
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus, TicketType

URL_REVENUE = "/api/reports/extra-work-revenue/"
URL_BY_BUILDING = "/api/reports/extra-work-revenue-by-building/"
URL_BY_BUILDING_CSV = "/api/reports/extra-work-revenue-by-building/export.csv"
URL_BY_BUILDING_PDF = "/api/reports/extra-work-revenue-by-building/export.pdf"


class _RevenueByBuildingBase(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # A second building under the SAME company/customer so a
        # customer's revenue can genuinely split across >1 building.
        # NOT assigned to `self.manager` (only `self.building` is) so
        # the manager-scope test has a real building to be denied.
        self.building_2 = Building.objects.create(
            company=self.company, name="Building A-2", address="Second Street 1"
        )
        CustomerBuildingMembership.objects.create(
            customer=self.customer, building=self.building_2
        )

    def _ew(
        self,
        company,
        building,
        customer,
        *,
        subtotal,
        vat,
        total,
        final_subtotal=None,
        final_vat=None,
        final_total=None,
        ew_status=ExtraWorkStatus.REQUESTED,
    ):
        return ExtraWorkRequest.objects.create(
            company=company,
            building=building,
            customer=customer,
            created_by=self.super_admin,
            title="EW",
            description="d",
            subtotal_amount=Decimal(subtotal),
            vat_amount=Decimal(vat),
            total_amount=Decimal(total),
            final_subtotal_amount=(
                Decimal(final_subtotal) if final_subtotal is not None else None
            ),
            final_vat_amount=(
                Decimal(final_vat) if final_vat is not None else None
            ),
            final_total_amount=(
                Decimal(final_total) if final_total is not None else None
            ),
            status=ew_status,
        )

    def _spawn(self, ew, ticket_status):
        ticket = Ticket.objects.create(
            company=ew.company,
            building=ew.building,
            customer=ew.customer,
            created_by=self.super_admin,
            title="EW spawned",
            description="d",
            type=TicketType.REQUEST,
            extra_work_request=ew,
        )
        Ticket.objects.filter(pk=ticket.pk).update(status=ticket_status)
        ticket.refresh_from_db()
        return ticket

    def _earned(self, building, customer, total, company=None):
        ew = self._ew(
            company or self.company,
            building,
            customer,
            subtotal=total,
            vat="0.00",
            total=total,
            final_subtotal=total,
            final_vat="0.00",
            final_total=total,
            ew_status=ExtraWorkStatus.CUSTOMER_APPROVED,
        )
        self._spawn(ew, TicketStatus.CLOSED)
        return ew


class ExtraWorkRevenueByBuildingPermissionTests(_RevenueByBuildingBase):
    def test_unauthenticated_returns_401(self):
        response = self.client.get(URL_BY_BUILDING)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_customer_user_returns_403(self):
        self.client.force_authenticate(user=self.customer_user)
        response = self.client.get(URL_BY_BUILDING)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_returns_403_commercial(self):
        staff = self.make_user("staff-124@example.com", UserRole.STAFF)
        self.client.force_authenticate(user=staff)
        response = self.client.get(URL_BY_BUILDING)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class ExtraWorkRevenueByBuildingSumTests(_RevenueByBuildingBase):
    """The core invariant: per-building buckets sum to the flat total,
    for the SAME filters, in both date-range and billing_period mode."""

    def setUp(self):
        super().setUp()
        # Mixed states across BOTH buildings so the sum has to cross
        # revenue-state boundaries to line up, not just add up trivially.
        self._earned(self.building, self.customer, "100.00")
        self._earned(self.building_2, self.customer, "40.00")
        # in_progress: spawned ticket exists, not terminal.
        ew_ip = self._ew(
            self.company,
            self.building,
            self.customer,
            subtotal="50.00",
            vat="0.00",
            total="50.00",
            ew_status=ExtraWorkStatus.CUSTOMER_APPROVED,
        )
        self._spawn(ew_ip, TicketStatus.IN_PROGRESS)
        # quoted_pipeline: no spawned ticket, still requested.
        self._ew(
            self.company,
            self.building_2,
            self.customer,
            subtotal="30.00",
            vat="0.00",
            total="30.00",
            ew_status=ExtraWorkStatus.PRICING_PROPOSED,
        )
        # lost: no spawned ticket, customer rejected.
        self._ew(
            self.company,
            self.building,
            self.customer,
            subtotal="20.00",
            vat="0.00",
            total="20.00",
            ew_status=ExtraWorkStatus.CUSTOMER_REJECTED,
        )
        # A second customer's EW on the SAME buildings — must not bleed
        # into the first customer's by-building split.
        from customers.models import Customer

        self.customer_two = Customer.objects.create(
            company=self.company, name="Customer A-2", building=self.building
        )
        CustomerBuildingMembership.objects.create(
            customer=self.customer_two, building=self.building
        )
        self._earned(self.building, self.customer_two, "999.00")

    def test_buckets_sum_to_flat_total_date_range_mode(self):
        self.client.force_authenticate(user=self.super_admin)
        params = {"customer": self.customer.id, "from": "2020-01-01", "to": "2035-01-01"}

        flat = self.client.get(URL_REVENUE, params)
        by_building = self.client.get(URL_BY_BUILDING, params)

        self.assertEqual(flat.status_code, status.HTTP_200_OK)
        self.assertEqual(by_building.status_code, status.HTTP_200_OK)

        flat_total = Decimal(flat.data["totals"]["total"])
        bucket_sum = sum(
            (Decimal(b["total"]) for b in by_building.data["buckets"]),
            Decimal("0.00"),
        )
        self.assertEqual(bucket_sum, flat_total)
        self.assertEqual(
            Decimal(by_building.data["totals"]["total"]), flat_total
        )
        # 100 + 50 (building) + 40 + 30 (building_2); the 20.00 LOST row
        # IS counted (lost still contributes its estimate to totals.total,
        # exactly like the flat report), customer_two's 999.00 is NOT.
        self.assertEqual(flat_total, Decimal("240.00"))
        # Exactly the two buildings that have this customer's EW rows —
        # customer_two's building never appears as a THIRD bucket even
        # though it is the same building id as one of these two.
        self.assertEqual(
            {b["building_id"] for b in by_building.data["buckets"]},
            {self.building.id, self.building_2.id},
        )

    def test_buckets_sum_to_flat_total_billing_period_mode(self):
        # The actual mode CustomerReportsPage uses. billing_month() for
        # an EARNED row with no invoice_date override anchors on the
        # spawned ticket's closed_at; freeze it to a known month via
        # .update() (bypasses auto_now, the same trick used elsewhere).
        import datetime

        month = "2026-03"
        Ticket.objects.filter(
            extra_work_request__customer=self.customer
        ).update(closed_at=datetime.datetime(2026, 3, 15, tzinfo=datetime.timezone.utc))

        self.client.force_authenticate(user=self.super_admin)
        params = {"customer": self.customer.id, "billing_period": month}

        flat = self.client.get(URL_REVENUE, params)
        by_building = self.client.get(URL_BY_BUILDING, params)

        self.assertEqual(flat.status_code, status.HTTP_200_OK)
        self.assertEqual(by_building.status_code, status.HTTP_200_OK)

        flat_total = Decimal(flat.data["totals"]["total"])
        bucket_sum = sum(
            (Decimal(b["total"]) for b in by_building.data["buckets"]),
            Decimal("0.00"),
        )
        self.assertEqual(bucket_sum, flat_total)


class ExtraWorkRevenueByBuildingCrossTenantTests(_RevenueByBuildingBase):
    def test_out_of_scope_customer_403(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(
            URL_BY_BUILDING, {"customer": self.other_customer.id}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_foreign_building_param_403(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(
            URL_BY_BUILDING, {"building": self.other_building.id}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_company_admin_never_sees_other_company_building(self):
        self._earned(self.building, self.customer, "100.00")
        self._earned(
            self.other_building,
            self.other_customer,
            "500.00",
            company=self.other_company,
        )
        self.client.force_authenticate(user=self.company_admin)

        response = self.client.get(URL_BY_BUILDING)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        seen_ids = {b["building_id"] for b in response.data["buckets"]}
        self.assertIn(self.building.id, seen_ids)
        self.assertNotIn(self.other_building.id, seen_ids)

    def test_manager_scoped_to_own_building_only(self):
        # self.manager is assigned to self.building only (see
        # TenantFixtureMixin); self.building_2 is a DIFFERENT building
        # under the SAME company the manager is not assigned to.
        self._earned(self.building, self.customer, "100.00")
        self._earned(self.building_2, self.customer, "40.00")
        self.client.force_authenticate(user=self.manager)

        response = self.client.get(URL_BY_BUILDING)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        seen_ids = {b["building_id"] for b in response.data["buckets"]}
        self.assertEqual(seen_ids, {self.building.id})
        self.assertEqual(response.data["totals"]["total"], "100.00")


class ExtraWorkRevenueByBuildingZeroTests(_RevenueByBuildingBase):
    def test_building_with_no_revenue_is_omitted(self):
        # building_2 has a CustomerBuildingMembership row (setUp) but NO
        # ExtraWorkRequest at all in the period — it must not appear as
        # a padded zero bucket.
        self._earned(self.building, self.customer, "100.00")
        self.client.force_authenticate(user=self.super_admin)

        response = self.client.get(URL_BY_BUILDING, {"customer": self.customer.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        seen_ids = {b["building_id"] for b in response.data["buckets"]}
        self.assertEqual(seen_ids, {self.building.id})
        self.assertNotIn(self.building_2.id, seen_ids)
        self.assertEqual(len(response.data["buckets"]), 1)


class ExtraWorkRevenueByBuildingOrderingTests(_RevenueByBuildingBase):
    def test_highest_revenue_building_first(self):
        self._earned(self.building, self.customer, "40.00")
        self._earned(self.building_2, self.customer, "100.00")
        self.client.force_authenticate(user=self.super_admin)

        response = self.client.get(URL_BY_BUILDING, {"customer": self.customer.id})
        buckets = response.data["buckets"]
        self.assertEqual(buckets[0]["building_id"], self.building_2.id)
        self.assertEqual(buckets[1]["building_id"], self.building.id)


class ExtraWorkRevenueByBuildingExportTests(_RevenueByBuildingBase):
    EXPECTED_HEADERS = [
        "building_id",
        "building_name",
        "company_id",
        "company_name",
        "count",
        "subtotal",
        "vat",
        "total",
        "period_from",
        "period_to",
    ]

    def setUp(self):
        super().setUp()
        self._earned(self.building, self.customer, "100.00")
        self._earned(self.building_2, self.customer, "40.00")

    def _csv_rows(self, response):
        import csv
        import io

        text = response.content.decode("utf-8")
        if text.startswith("﻿"):
            text = text[1:]
        reader = csv.DictReader(io.StringIO(text))
        return reader.fieldnames, list(reader)

    def test_csv_response_shape(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_BY_BUILDING_CSV, {"customer": self.customer.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        self.assertIn("extra-work-revenue-by-building", response["Content-Disposition"])
        headers, rows = self._csv_rows(response)
        self.assertEqual(headers, self.EXPECTED_HEADERS)
        self.assertEqual(len(rows), 2)
        totals = {r["building_id"]: r["total"] for r in rows}
        self.assertEqual(totals[str(self.building.id)], "100.00")
        self.assertEqual(totals[str(self.building_2.id)], "40.00")

    def test_csv_staff_returns_403(self):
        staff = self.make_user("staff-124-csv@example.com", UserRole.STAFF)
        self.client.force_authenticate(user=staff)
        response = self.client.get(URL_BY_BUILDING_CSV)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_pdf_export(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_BY_BUILDING_PDF, {"customer": self.customer.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
