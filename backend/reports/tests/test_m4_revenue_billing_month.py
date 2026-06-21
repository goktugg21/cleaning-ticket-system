"""M4 commit 2e — billing-month anchor + invoice-status filter on the
EW-revenue report (and its CSV/PDF exports).

GET /api/reports/extra-work-revenue/ (+ export.csv / export.pdf) gains:
  * ?billing_period=YYYY-MM — anchor revenue on COALESCE(invoice_date,
    spawned-ticket completion date) via extra_work.billing (the SAME logic
    the invoice run and the EW list filter use), restricted to EARNED EW and
    bypassing the requested_at window. The payload period reflects the month
    so the CSV/PDF exports track it.
  * ?invoice_status=completed|invoiced — narrows the billing-month set.

Absent billing_period, the report keeps its requested_at-window behaviour.

Fixture mirrors test_sprint14a_origin_and_revenue.py (_ew / _spawn + the
TenantFixtureMixin actor/scope). requested_at is auto-set, so it is forced via
a post-create .update().
"""
import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus, TicketType


URL_REVENUE = "/api/reports/extra-work-revenue/"
URL_REVENUE_CSV = "/api/reports/extra-work-revenue/export.csv"
URL_REVENUE_PDF = "/api/reports/extra-work-revenue/export.pdf"


def _dt(year: int, month: int, day: int) -> datetime:
    # Noon UTC so .date() never rolls into an adjacent day under any TZ.
    return datetime(year, month, day, 12, 0, tzinfo=timezone.utc)


class _RevenueBillingBase(TenantFixtureMixin, APITestCase):
    def _ew(
        self,
        *,
        subtotal="100.00",
        vat="21.00",
        total="121.00",
        invoice_date=None,
        is_invoiced=False,
        ew_status=ExtraWorkStatus.CUSTOMER_APPROVED,
        requested_at=None,
    ):
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="EW",
            description="d",
            subtotal_amount=Decimal(subtotal),
            vat_amount=Decimal(vat),
            total_amount=Decimal(total),
            status=ew_status,
            invoice_date=invoice_date,
            is_invoiced=is_invoiced,
        )
        if requested_at is not None:
            # requested_at is auto-set on insert; force it via .update() so
            # the billing-month tests can prove the anchor is NOT requested_at.
            ExtraWorkRequest.objects.filter(pk=ew.pk).update(
                requested_at=requested_at
            )
            ew.refresh_from_db()
        return ew

    def _spawn(self, ew, ticket_status, closed_at=None):
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
        Ticket.objects.filter(pk=ticket.pk).update(
            status=ticket_status, closed_at=closed_at
        )
        ticket.refresh_from_db()
        return ticket

    def _get(self, **params):
        self.client.force_authenticate(user=self.super_admin)
        return self.client.get(URL_REVENUE, params)


class ExtraWorkRevenueBillingMonthTests(_RevenueBillingBase):
    def test_anchors_on_completion_not_requested_at(self):
        # Earned (ticket CLOSED) May 31, requested_at forced to March: the
        # billing-month anchor must place it in May, NOT March.
        ew = self._ew(total="121.00", requested_at=_dt(2026, 3, 15))
        self._spawn(ew, TicketStatus.CLOSED, closed_at=_dt(2026, 5, 31))

        resp = self._get(billing_period="2026-05")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        earned = resp.data["states"]["earned"]
        self.assertEqual(earned["count"], 1)
        self.assertEqual(earned["total"], "121.00")
        self.assertEqual(resp.data["totals"]["count"], 1)

    def test_wrong_month_excludes(self):
        ew = self._ew(requested_at=_dt(2026, 3, 15))
        self._spawn(ew, TicketStatus.CLOSED, closed_at=_dt(2026, 5, 31))

        resp = self._get(billing_period="2026-06")
        self.assertEqual(resp.data["states"]["earned"]["count"], 0)
        self.assertEqual(resp.data["totals"]["count"], 0)

    def test_invoice_date_override_changes_bucket(self):
        # Earned May 31 but provider set invoice_date=Jun 15 -> bills in June.
        ew = self._ew(invoice_date=date(2026, 6, 15))
        self._spawn(ew, TicketStatus.CLOSED, closed_at=_dt(2026, 5, 31))

        may = self._get(billing_period="2026-05")
        self.assertEqual(may.data["states"]["earned"]["count"], 0)

        jun = self._get(billing_period="2026-06")
        self.assertEqual(jun.data["states"]["earned"]["count"], 1)

    def test_not_earned_excluded(self):
        # Spawned ticket OPEN (not earned); invoice_date resolves to May but
        # the billing-month report only counts EARNED EW.
        ew = self._ew(invoice_date=date(2026, 5, 10))
        self._spawn(ew, TicketStatus.OPEN)

        resp = self._get(billing_period="2026-05")
        self.assertEqual(resp.data["states"]["earned"]["count"], 0)
        self.assertEqual(resp.data["totals"]["count"], 0)

    def test_invoice_status_completed(self):
        completed = self._ew(total="121.00", is_invoiced=False)
        self._spawn(completed, TicketStatus.CLOSED, closed_at=_dt(2026, 5, 31))
        invoiced = self._ew(total="200.00", is_invoiced=True)
        self._spawn(invoiced, TicketStatus.CLOSED, closed_at=_dt(2026, 5, 31))

        resp = self._get(billing_period="2026-05", invoice_status="completed")
        self.assertEqual(resp.data["states"]["earned"]["count"], 1)
        self.assertEqual(resp.data["states"]["earned"]["total"], "121.00")

    def test_invoice_status_invoiced(self):
        completed = self._ew(total="121.00", is_invoiced=False)
        self._spawn(completed, TicketStatus.CLOSED, closed_at=_dt(2026, 5, 31))
        invoiced = self._ew(total="200.00", is_invoiced=True)
        self._spawn(invoiced, TicketStatus.CLOSED, closed_at=_dt(2026, 5, 31))

        resp = self._get(billing_period="2026-05", invoice_status="invoiced")
        self.assertEqual(resp.data["states"]["earned"]["count"], 1)
        self.assertEqual(resp.data["states"]["earned"]["total"], "200.00")

    def test_period_reflects_billing_month(self):
        resp = self._get(billing_period="2026-05")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["from"], "2026-05-01")
        self.assertEqual(resp.data["to"], "2026-05-31")

    def test_garbage_period_is_400(self):
        resp = self._get(billing_period="garbage")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_month_out_of_range_is_400(self):
        resp = self._get(billing_period="2026-13")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_out_of_range_year_is_400_not_500(self):
        # Parseable YYYY-MM but the year is outside date's 1..9999 range —
        # must fail closed (400), not raise an uncaught ValueError (500).
        for period in ("0000-05", "10000-05"):
            resp = self._get(billing_period=period)
            self.assertEqual(
                resp.status_code,
                status.HTTP_400_BAD_REQUEST,
                f"{period} should be 400",
            )

    def test_unknown_invoice_status_is_400(self):
        # A typo'd status (valid period) must fail closed rather than silently
        # dropping the filter and mixing invoiced + not-yet-invoiced totals.
        resp = self._get(billing_period="2026-05", invoice_status="complete")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_csv_honors_billing_period(self):
        ew = self._ew(total="121.00", requested_at=_dt(2026, 3, 15))
        self._spawn(ew, TicketStatus.CLOSED, closed_at=_dt(2026, 5, 31))

        self.client.force_authenticate(user=self.super_admin)
        resp = self.client.get(URL_REVENUE_CSV, {"billing_period": "2026-05"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp["Content-Type"].startswith("text/csv"))

        text = resp.content.decode("utf-8")
        if text.startswith("﻿"):
            text = text[1:]
        # Period columns reflect May.
        self.assertIn("2026-05-01", text)
        self.assertIn("2026-05-31", text)
        # The earned row counts the single May-completed EW.
        rows = list(csv.DictReader(io.StringIO(text)))
        earned_row = next(r for r in rows if r["state"] == "earned")
        self.assertEqual(earned_row["count"], "1")

    def test_pdf_honors_billing_period(self):
        ew = self._ew(requested_at=_dt(2026, 3, 15))
        self._spawn(ew, TicketStatus.CLOSED, closed_at=_dt(2026, 5, 31))

        self.client.force_authenticate(user=self.super_admin)
        resp = self.client.get(URL_REVENUE_PDF, {"billing_period": "2026-05"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("application/pdf", resp["Content-Type"])

    def test_back_compat_without_billing_period(self):
        # No billing_period -> requested_at-window behaviour. The four states
        # are present and a PRICING_PROPOSED-no-ticket EW lands in pipeline.
        self._ew(total="121.00", ew_status=ExtraWorkStatus.PRICING_PROPOSED)

        resp = self._get()
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            set(resp.data["states"].keys()),
            {"earned", "in_progress", "quoted_pipeline", "lost"},
        )
        self.assertEqual(resp.data["states"]["quoted_pipeline"]["count"], 1)
