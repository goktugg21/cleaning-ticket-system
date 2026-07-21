"""Phase 4a Part C — the Invoice REST surface (HTTP).

Covers: list scoping + filters; generate -> issue -> send -> reverse over
HTTP; line add / edit / remove over HTTP (incl. EW release on remove);
meta/fee/summary PATCH (DRAFT-only); the due list returns scoped data;
customer users get 403 on every endpoint; cross-tenant ids are 404.
"""
from __future__ import annotations

from decimal import Decimal

from django.urls import reverse
from rest_framework.test import APIClient

from customers.models import Customer

from invoicing.line_services import add_invoice_line
from invoicing.models import Invoice, InvoiceLine
from invoicing.services import generate_draft_invoices

from ._helpers import InvoicingFixture, dt

YEAR, MONTH = 2026, 5


class InvoiceApiBase(InvoicingFixture):
    def setUp(self):
        self.client = APIClient()

    def _draft(self, *, company=None, customer=None, created_by=None):
        return Invoice.objects.create(
            company=company or self.company,
            customer=customer or self.customer,
            status=Invoice.Status.DRAFT,
            created_by=created_by or self.admin,
        )

    def _lines_url(self, inv_id):
        return f"/api/invoices/{inv_id}/lines/"

    def _line_detail_url(self, inv_id, line_id):
        return f"/api/invoices/{inv_id}/lines/{line_id}/"


class InvoiceListApiTests(InvoiceApiBase):
    def test_list_scoped_to_operator_tenant(self):
        inv_a = self._draft()
        inv_b = Invoice.objects.create(
            company=self.company_b,
            customer=self.customer_b,
            status=Invoice.Status.DRAFT,
            created_by=self.admin_b,
        )
        self.client.force_authenticate(self.admin)
        resp = self.client.get(reverse("invoice-list"))
        self.assertEqual(resp.status_code, 200)
        ids = [row["id"] for row in resp.data["results"]]
        self.assertIn(inv_a.id, ids)
        self.assertNotIn(inv_b.id, ids)

    def test_list_filter_by_status(self):
        draft = self._draft()
        issued = Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=Invoice.Status.ISSUED,
            created_by=self.admin,
        )
        self.client.force_authenticate(self.admin)
        resp = self.client.get(reverse("invoice-list"), {"status": "DRAFT"})
        self.assertEqual(resp.status_code, 200)
        ids = [row["id"] for row in resp.data["results"]]
        self.assertIn(draft.id, ids)
        self.assertNotIn(issued.id, ids)

    def test_list_filter_by_period(self):
        may = Invoice.objects.create(
            company=self.company, customer=self.customer,
            status=Invoice.Status.DRAFT, created_by=self.admin,
            period_year=2026, period_month=5,
        )
        jun = Invoice.objects.create(
            company=self.company, customer=self.customer,
            status=Invoice.Status.DRAFT, created_by=self.admin,
            period_year=2026, period_month=6,
        )
        self.client.force_authenticate(self.admin)
        resp = self.client.get(
            reverse("invoice-list"),
            {"period_year": 2026, "period_month": 5},
        )
        ids = [row["id"] for row in resp.data["results"]]
        self.assertIn(may.id, ids)
        self.assertNotIn(jun.id, ids)

    def test_list_customer_user_forbidden(self):
        self._draft()
        self.client.force_authenticate(self.customer_user)
        resp = self.client.get(reverse("invoice-list"))
        self.assertEqual(resp.status_code, 403)


class InvoiceLifecycleApiTests(InvoiceApiBase):
    def test_generate_issue_send_reverse(self):
        self.make_ew(closed_at=dt(2026, 5, 31))
        self.client.force_authenticate(self.admin)

        resp = self.client.post(
            reverse("invoice-generate"),
            {"customer": self.customer.id, "year": YEAR, "month": MONTH},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(len(resp.data), 1)
        inv_id = resp.data[0]["id"]
        self.assertEqual(resp.data[0]["status"], "DRAFT")

        resp = self.client.post(reverse("invoice-issue", args=[inv_id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "ISSUED")
        # Number-at-send: issue does NOT assign a number yet.
        self.assertIsNone(resp.data["number"])

        resp = self.client.post(reverse("invoice-send", args=[inv_id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "SENT")
        # The gapless number is born at send.
        self.assertIsNotNone(resp.data["number"])

        resp = self.client.post(reverse("invoice-reverse", args=[inv_id]))
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.data["is_reversal"])
        self.assertEqual(resp.data["reverses"], inv_id)

    def test_unissue_returns_issued_invoice_to_draft(self):
        draft = self._draft()
        self.client.force_authenticate(self.admin)
        self.client.post(reverse("invoice-issue", args=[draft.id]))
        resp = self.client.post(reverse("invoice-unissue", args=[draft.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "DRAFT")
        self.assertIsNone(resp.data["number"])

    def test_unissue_draft_400(self):
        draft = self._draft()
        self.client.force_authenticate(self.admin)
        resp = self.client.post(reverse("invoice-unissue", args=[draft.id]))
        self.assertEqual(resp.status_code, 400)

    def test_unissue_customer_user_403(self):
        draft = self._draft()
        self.client.force_authenticate(self.admin)
        self.client.post(reverse("invoice-issue", args=[draft.id]))
        self.client.force_authenticate(self.customer_user)
        resp = self.client.post(reverse("invoice-unissue", args=[draft.id]))
        self.assertEqual(resp.status_code, 403)

    def test_generate_cross_tenant_404(self):
        # Company-A admin generating for a company-B customer -> 404 (the
        # customer is outside the actor's customer scope).
        self.client.force_authenticate(self.admin)
        resp = self.client.post(
            reverse("invoice-generate"),
            {"customer": self.customer_b.id, "year": YEAR, "month": MONTH},
            format="json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_generate_bad_month_400(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post(
            reverse("invoice-generate"),
            {"customer": self.customer.id, "year": YEAR, "month": 13},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_send_before_issue_400(self):
        draft = self._draft()
        self.client.force_authenticate(self.admin)
        resp = self.client.post(reverse("invoice-send", args=[draft.id]))
        self.assertEqual(resp.status_code, 400)

    def test_delete_draft_releases_ew(self):
        ew = self.make_ew(closed_at=dt(2026, 5, 31))
        inv = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )[0]
        self.client.force_authenticate(self.admin)
        resp = self.client.delete(reverse("invoice-detail", args=[inv.id]))
        self.assertEqual(resp.status_code, 204)
        ew.refresh_from_db()
        self.assertFalse(ew.is_invoiced)

    def test_delete_issued_400(self):
        issued = Invoice.objects.create(
            company=self.company, customer=self.customer,
            status=Invoice.Status.ISSUED, created_by=self.admin,
        )
        self.client.force_authenticate(self.admin)
        resp = self.client.delete(reverse("invoice-detail", args=[issued.id]))
        self.assertEqual(resp.status_code, 400)

    def test_generate_customer_user_forbidden(self):
        self.client.force_authenticate(self.customer_user)
        resp = self.client.post(
            reverse("invoice-generate"),
            {"customer": self.customer.id, "year": YEAR, "month": MONTH},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)


class InvoiceLineApiTests(InvoiceApiBase):
    def test_add_line_over_http(self):
        inv = self._draft()
        self.client.force_authenticate(self.admin)
        resp = self.client.post(
            self._lines_url(inv.id),
            {
                "description": "Handmatige regel",
                "quantity": "2",
                "unit_price": "50.00",
                "vat_pct": "21.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertIsNone(resp.data["extra_work"])
        self.assertEqual(resp.data["line_total"], "121.00")
        inv.refresh_from_db()
        self.assertEqual(inv.total_amount, Decimal("121.00"))

    def test_patch_line_over_http(self):
        inv = self._draft()
        line = add_invoice_line(
            self.admin, inv, quantity=Decimal("1"), unit_price=Decimal("50.00")
        )
        self.client.force_authenticate(self.admin)
        resp = self.client.patch(
            self._line_detail_url(inv.id, line.id),
            {"quantity": "3", "unit_price": "100.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["line_subtotal"], "300.00")
        inv.refresh_from_db()
        self.assertEqual(inv.subtotal_amount, Decimal("300.00"))

    def test_delete_ew_line_releases_ew_over_http(self):
        ew = self.make_ew(closed_at=dt(2026, 5, 31))
        inv = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )[0]
        line = inv.lines.get()
        self.client.force_authenticate(self.admin)
        resp = self.client.delete(self._line_detail_url(inv.id, line.id))
        self.assertEqual(resp.status_code, 204)
        ew.refresh_from_db()
        self.assertFalse(ew.is_invoiced)
        self.assertIsNone(ew.invoiced_at)
        inv.refresh_from_db()
        self.assertEqual(inv.total_amount, Decimal("0.00"))

    def test_add_line_customer_user_forbidden(self):
        inv = self._draft()
        self.client.force_authenticate(self.customer_user)
        resp = self.client.post(
            self._lines_url(inv.id),
            {"unit_price": "10.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_add_line_on_issued_400(self):
        issued = Invoice.objects.create(
            company=self.company, customer=self.customer,
            status=Invoice.Status.ISSUED, created_by=self.admin,
        )
        self.client.force_authenticate(self.admin)
        resp = self.client.post(
            self._lines_url(issued.id),
            {"unit_price": "10.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)


class InvoiceMetaApiTests(InvoiceApiBase):
    def test_patch_meta_summary_and_fee(self):
        inv = self._draft()
        add_invoice_line(
            self.admin, inv, quantity=Decimal("1"), unit_price=Decimal("100.00")
        )
        self.client.force_authenticate(self.admin)
        resp = self.client.patch(
            reverse("invoice-detail", args=[inv.id]),
            {
                "summary_text": "Handmatige samenvatting",
                "optional_fee_label": "Spoedtoeslag",
                "optional_fee_amount": "30.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["summary_text"], "Handmatige samenvatting")
        self.assertEqual(resp.data["optional_fee_amount"], "30.00")
        # Fee is VAT-free: subtotal + total include it, vat unchanged.
        self.assertEqual(resp.data["subtotal_amount"], "130.00")
        self.assertEqual(resp.data["vat_amount"], "21.00")
        self.assertEqual(resp.data["total_amount"], "151.00")

    def test_patch_meta_on_issued_400(self):
        issued = Invoice.objects.create(
            company=self.company, customer=self.customer,
            status=Invoice.Status.ISSUED, created_by=self.admin,
        )
        self.client.force_authenticate(self.admin)
        resp = self.client.patch(
            reverse("invoice-detail", args=[issued.id]),
            {"summary_text": "x"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_meta_customer_user_forbidden(self):
        inv = self._draft()
        self.client.force_authenticate(self.customer_user)
        resp = self.client.patch(
            reverse("invoice-detail", args=[inv.id]),
            {"summary_text": "x"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)


class InvoiceDueApiTests(InvoiceApiBase):
    def test_due_lists_scoped_customers_with_schedule(self):
        self.customer.invoice_day_rule = (
            Customer.InvoiceDayRule.FIRST_OF_MONTH
        )
        self.customer.save(update_fields=["invoice_day_rule"])
        # A cross-tenant customer WITH a schedule must NOT appear.
        self.customer_b.invoice_day_rule = (
            Customer.InvoiceDayRule.FIRST_OF_MONTH
        )
        self.customer_b.save(update_fields=["invoice_day_rule"])

        self.client.force_authenticate(self.admin)
        resp = self.client.get(reverse("invoice-due"))
        self.assertEqual(resp.status_code, 200)
        customer_ids = [row["customer"] for row in resp.data]
        self.assertIn(self.customer.id, customer_ids)
        self.assertNotIn(self.customer_b.id, customer_ids)
        row = next(r for r in resp.data if r["customer"] == self.customer.id)
        self.assertIn("unbilled_count", row)
        self.assertIn("unbilled_total", row)
        self.assertIn("is_due", row)

    def test_due_excludes_customers_without_schedule(self):
        # self.customer has no invoice_day_rule set (default "") -> excluded.
        self.client.force_authenticate(self.admin)
        resp = self.client.get(reverse("invoice-due"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(
            self.customer.id, [row["customer"] for row in resp.data]
        )

    def test_due_customer_user_forbidden(self):
        self.client.force_authenticate(self.customer_user)
        resp = self.client.get(reverse("invoice-due"))
        self.assertEqual(resp.status_code, 403)


class InvoiceCrossTenantApiTests(InvoiceApiBase):
    def _invoice_b(self):
        return Invoice.objects.create(
            company=self.company_b,
            customer=self.customer_b,
            status=Invoice.Status.DRAFT,
            created_by=self.admin_b,
        )

    def test_retrieve_cross_tenant_404(self):
        inv_b = self._invoice_b()
        self.client.force_authenticate(self.admin)
        resp = self.client.get(reverse("invoice-detail", args=[inv_b.id]))
        self.assertEqual(resp.status_code, 404)

    def test_issue_cross_tenant_404(self):
        inv_b = self._invoice_b()
        self.client.force_authenticate(self.admin)
        resp = self.client.post(reverse("invoice-issue", args=[inv_b.id]))
        self.assertEqual(resp.status_code, 404)

    def test_add_line_cross_tenant_404(self):
        inv_b = self._invoice_b()
        self.client.force_authenticate(self.admin)
        resp = self.client.post(
            self._lines_url(inv_b.id), {"unit_price": "10.00"}, format="json"
        )
        self.assertEqual(resp.status_code, 404)
