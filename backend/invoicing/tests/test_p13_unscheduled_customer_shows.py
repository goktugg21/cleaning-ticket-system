"""P-13 A (W1) — a customer without a billing day can no longer hide
finished money from the Invoices page.

The fresh-seed finding: three finished, unbilled extra works for a
customer whose billing day was never set, and the Invoices page read
"€0.00 finished, not invoiced" — `/due/` listed only customers WITH a
billing schedule, so an unscheduled customer took every earned job
with them. This — not archiving — was the quiet way money misses
month-end.

Pins:
  * an unscheduled customer (rule "" + day None) WITH earned unbilled
    work appears on `/due/`, day fields both empty on the wire, never
    `is_due` (nobody said when to bill them — the daily job must not
    pick them up, and doesn't: `is_billing_day` stays False);
  * an unscheduled customer with NOTHING stays off the panel (no
    noise rows);
  * a scheduled customer keeps their row at zero count (their
    `nothing_reason` sentence needs the row to live on).
"""
from __future__ import annotations

from rest_framework.test import APIClient

from customers.models import Customer
from invoicing.schedule import is_billing_day

from ._helpers import InvoicingFixture

DUE_URL = "/api/invoices/due/"


class UnscheduledCustomerShowsTests(InvoicingFixture):
    def _due_rows(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        resp = client.get(DUE_URL)
        self.assertEqual(resp.status_code, 200, resp.data)
        return {row["customer"]: row for row in resp.data}

    def test_unscheduled_customer_with_earned_work_appears(self):
        # The fixture customer has NO schedule by construction.
        self.assertEqual(self.customer.invoice_day_rule, "")
        self.assertIsNone(self.customer.invoice_day_of_month)
        self.make_ew()  # earned May 2026, unbilled

        rows = self._due_rows()
        self.assertIn(self.customer.id, rows)
        row = rows[self.customer.id]
        self.assertEqual(row["invoice_day_rule"], "")
        self.assertIsNone(row["invoice_day_of_month"])
        self.assertEqual(row["unbilled_count"], 1)
        self.assertEqual(row["unbilled_total"], "121.00")
        # Visible is not auto-billed: never due, and the daily job's
        # own trigger still refuses an unscheduled customer.
        self.assertFalse(row["is_due"])
        from django.utils import timezone

        self.assertFalse(is_billing_day(self.customer, timezone.localdate()))

    def test_unscheduled_customer_with_nothing_stays_hidden(self):
        rows = self._due_rows()
        self.assertNotIn(self.customer.id, rows)

    def test_scheduled_customer_keeps_their_row_at_zero(self):
        self.customer.invoice_day_rule = Customer.InvoiceDayRule.FIRST_OF_MONTH
        self.customer.save(update_fields=["invoice_day_rule"])
        rows = self._due_rows()
        self.assertIn(self.customer.id, rows)
        row = rows[self.customer.id]
        self.assertEqual(row["unbilled_count"], 0)
        self.assertFalse(row["is_due"])
        self.assertIsNotNone(row["nothing_reason"])
