"""Phase 4a Part C — the Invoice REST surface (HTTP).

Covers: list scoping + filters; generate -> issue -> send -> reverse over
HTTP; line add / edit / remove over HTTP (incl. EW release on remove);
meta/fee/summary PATCH (DRAFT-only); the due list returns scoped data;
customer users get 403 on every endpoint; cross-tenant ids are 404.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APIClient

from customers.models import Customer, CustomerUserMembership

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

    def test_credited_by_number_on_original_after_reverse(self):
        """Sprint 122 (B2) — the provider-side GET on the ORIGINAL shows the
        reversal's number as soon as it exists, even before the reversal is
        itself sent (the provider already sees ISSUED rows directly)."""
        self.make_ew(closed_at=dt(2026, 5, 31))
        self.client.force_authenticate(self.admin)
        inv_id = self.client.post(
            reverse("invoice-generate"),
            {"customer": self.customer.id, "year": YEAR, "month": MONTH},
            format="json",
        ).data[0]["id"]
        self.client.post(reverse("invoice-issue", args=[inv_id]))
        self.client.post(reverse("invoice-send", args=[inv_id]))

        resp = self.client.get(reverse("invoice-detail", args=[inv_id]))
        self.assertIsNone(resp.data["credited_by_number"])

        reversal_resp = self.client.post(reverse("invoice-reverse", args=[inv_id]))
        reversal_number = reversal_resp.data["number"]
        self.assertIsNotNone(reversal_number)
        # A reversal can never itself be credited (cannot reverse a reversal).
        self.assertIsNone(reversal_resp.data["credited_by_number"])

        resp = self.client.get(reverse("invoice-detail", args=[inv_id]))
        self.assertEqual(resp.data["credited_by_number"], reversal_number)

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

    # -- SoT Addendum B §B.10: unbilled work carries forward across months -

    def test_due_includes_unbilled_work_from_a_prior_month(self):
        # EW earned in April 2026 (a PRIOR month); "today" is mocked to
        # 2026-05-20. Pre-Sprint-119 this dropped off the due panel the
        # instant May began (the view hard-matched year/month == today's);
        # now it must still be counted as outstanding.
        self.make_ew(closed_at=dt(2026, 4, 15))
        self.customer.invoice_day_rule = Customer.InvoiceDayRule.FIRST_OF_MONTH
        self.customer.save(update_fields=["invoice_day_rule"])
        self.client.force_authenticate(self.admin)
        with patch(
            "invoicing.views.timezone.localdate", return_value=date(2026, 5, 20)
        ):
            resp = self.client.get(reverse("invoice-due"))
        row = self._row_for(resp, self.customer)
        self.assertIsNotNone(row)
        self.assertEqual(row["unbilled_count"], 1)
        self.assertEqual(row["unbilled_total"], "121.00")
        # The response shape is unchanged: period_year/period_month still
        # report the CURRENT (cutoff) period, not the EW's own billing month.
        self.assertEqual(row["period_year"], 2026)
        self.assertEqual(row["period_month"], 5)

    def test_due_still_excludes_work_billable_after_the_cutoff_month(self):
        # EW earned in a FUTURE month (June) relative to "today" (May 20)
        # must NOT be counted yet — only THROUGH the current month.
        self.make_ew(closed_at=dt(2026, 6, 5))
        self.customer.invoice_day_rule = Customer.InvoiceDayRule.FIRST_OF_MONTH
        self.customer.save(update_fields=["invoice_day_rule"])
        self.client.force_authenticate(self.admin)
        with patch(
            "invoicing.views.timezone.localdate", return_value=date(2026, 5, 20)
        ):
            resp = self.client.get(reverse("invoice-due"))
        row = self._row_for(resp, self.customer)
        self.assertIsNotNone(row)
        self.assertEqual(row["unbilled_count"], 0)
        self.assertEqual(row["unbilled_total"], "0.00")

    def test_due_unresolvable_billing_month_excluded_not_500(self):
        # Sprint 120 — an earned EW (ticket CLOSED — is_earned() checks
        # only status) with NO closed_at and NO invoice_date has an
        # unresolvable billing_month() (returns None). Pre-fix,
        # unbilled_extra_work_through's `billing_month(...) <= (year,
        # month)` raised TypeError on None, 500ing this endpoint. It must
        # instead be EXCLUDED — not billable, not crashed on.
        self.make_ew(closed_at=None)
        self.customer.invoice_day_rule = Customer.InvoiceDayRule.FIRST_OF_MONTH
        self.customer.save(update_fields=["invoice_day_rule"])
        self.client.force_authenticate(self.admin)
        resp = self.client.get(reverse("invoice-due"))
        self.assertEqual(resp.status_code, 200)
        row = self._row_for(resp, self.customer)
        self.assertIsNotNone(row)
        self.assertEqual(row["unbilled_count"], 0)
        self.assertEqual(row["unbilled_total"], "0.00")

    # -- arbitrary billing day (invoice_day_of_month) ---------------------

    def _row_for(self, resp, customer):
        return next(
            (r for r in resp.data if r["customer"] == customer.id), None
        )

    def test_specific_day_makes_customer_scheduled_and_in_payload(self):
        # A specific day alone (no first/last rule) schedules the customer.
        self.customer.invoice_day_of_month = 15
        self.customer.save(update_fields=["invoice_day_of_month"])
        self.client.force_authenticate(self.admin)
        resp = self.client.get(reverse("invoice-due"))
        self.assertEqual(resp.status_code, 200)
        row = self._row_for(resp, self.customer)
        self.assertIsNotNone(row)
        self.assertEqual(row["invoice_day_of_month"], 15)

    def test_specific_day_is_due_once_today_reaches_it(self):
        # EW earned in May 2026; today mocked to 2026-05-20 (>= day 15).
        self.make_ew(closed_at=dt(2026, 5, 31))
        self.customer.invoice_day_of_month = 15
        self.customer.save(update_fields=["invoice_day_of_month"])
        self.client.force_authenticate(self.admin)
        with patch(
            "invoicing.views.timezone.localdate", return_value=date(2026, 5, 20)
        ):
            resp = self.client.get(reverse("invoice-due"))
        row = self._row_for(resp, self.customer)
        self.assertEqual(row["unbilled_count"], 1)
        self.assertTrue(row["is_due"])  # 20 >= 15 -> reached

    def test_specific_day_not_due_before_the_day(self):
        # Same EW, but the billing day (25) is AFTER today (2026-05-20).
        self.make_ew(closed_at=dt(2026, 5, 31))
        self.customer.invoice_day_of_month = 25
        self.customer.save(update_fields=["invoice_day_of_month"])
        self.client.force_authenticate(self.admin)
        with patch(
            "invoicing.views.timezone.localdate", return_value=date(2026, 5, 20)
        ):
            resp = self.client.get(reverse("invoice-due"))
        row = self._row_for(resp, self.customer)
        # Still listed (scheduled) with the unbilled count, but not due yet.
        self.assertEqual(row["unbilled_count"], 1)
        self.assertFalse(row["is_due"])  # 20 < 25 -> not reached

    def test_specific_day_takes_precedence_over_rule(self):
        # Day 25 set alongside FIRST_OF_MONTH: the specific day wins, so on the
        # 20th it is NOT yet due (FIRST alone would have been due all month).
        self.make_ew(closed_at=dt(2026, 5, 31))
        self.customer.invoice_day_rule = Customer.InvoiceDayRule.FIRST_OF_MONTH
        self.customer.invoice_day_of_month = 25
        self.customer.save(
            update_fields=["invoice_day_rule", "invoice_day_of_month"]
        )
        self.client.force_authenticate(self.admin)
        with patch(
            "invoicing.views.timezone.localdate", return_value=date(2026, 5, 20)
        ):
            resp = self.client.get(reverse("invoice-due"))
        row = self._row_for(resp, self.customer)
        self.assertFalse(row["is_due"])


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


class InvoiceCompanyNameFieldTests(InvoiceApiBase):
    """Sprint 187 §6a — WHICH provider company issued this invoice.

    Numbering is gapless per company per YEAR, so two different invoices
    legitimately both display `2026-0001` and the list had nothing at all
    to tell them apart. Live on crmtest: one Osius Demo, one Bright
    Facilities.

    These tests are the Sprint 173 rule applied: a field that is exposed
    gets a test that RENDERS the endpoint carrying it. A missing `fields`
    entry took the whole Extra Work page down once, and no filter or
    serializer-unit test would have caught it, because neither
    serialises a row through the real view.
    """

    def test_list_rows_carry_company_name(self):
        inv = self._draft()
        self.client.force_authenticate(self.admin)
        resp = self.client.get(reverse("invoice-list"))
        self.assertEqual(resp.status_code, 200)
        row = next(r for r in resp.data["results"] if r["id"] == inv.id)
        self.assertIn("company_name", row)
        self.assertEqual(row["company_name"], self.company.name)

    def test_detail_carries_company_name(self):
        inv = self._draft()
        self.client.force_authenticate(self.admin)
        resp = self.client.get(f"/api/invoices/{inv.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["company_name"], self.company.name)

    def test_the_same_number_in_two_companies_is_distinguishable(self):
        """The defect, stated as a test.

        Numbering is per company per year, so `2026-0001` exists twice
        and legitimately so. Before this field the two rows were
        identical on screen; now the company name separates them.
        """
        inv_a = Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=Invoice.Status.SENT,
            created_by=self.admin,
            year=2026,
            number="2026-0001",
        )
        inv_b = Invoice.objects.create(
            company=self.company_b,
            customer=self.customer_b,
            status=Invoice.Status.SENT,
            created_by=self.admin_b,
            year=2026,
            number="2026-0001",
        )

        self.client.force_authenticate(self.admin)
        row_a = self.client.get(f"/api/invoices/{inv_a.id}/").data
        self.client.force_authenticate(self.admin_b)
        row_b = self.client.get(f"/api/invoices/{inv_b.id}/").data

        self.assertEqual(row_a["number"], row_b["number"])
        self.assertNotEqual(row_a["company_name"], row_b["company_name"])
        self.assertEqual(row_a["company_name"], self.company.name)
        self.assertEqual(row_b["company_name"], self.company_b.name)

    def test_the_customer_read_shape_does_NOT_leak_company_name(self):
        """A customer has no business learning the provider's internal
        company structure. `CustomerInvoiceSerializer` is deliberately
        untouched and this is what keeps it that way."""
        inv = Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=Invoice.Status.SENT,
            created_by=self.admin,
            year=2026,
            number="2026-0002",
        )
        # The shared fixture's `customer_user` carries no membership (it
        # exists to prove 403 on the PROVIDER endpoints), and the customer
        # scope is membership-based — without this the read is a 404 and
        # the test would pass for the wrong reason.
        CustomerUserMembership.objects.create(
            customer=self.customer, user=self.customer_user
        )

        self.client.force_authenticate(self.customer_user)
        resp = self.client.get(f"/api/invoices/my/{inv.id}/")
        self.assertEqual(resp.status_code, 200, getattr(resp, "data", None))
        self.assertNotIn("company_name", resp.data)
        self.assertNotIn("company", resp.data)
        # ...and the provider shape for the SAME invoice does carry it,
        # so this is a redaction and not an absent field on both sides.
        self.client.force_authenticate(self.admin)
        provider = self.client.get(f"/api/invoices/{inv.id}/")
        self.assertEqual(provider.data["company_name"], self.company.name)
