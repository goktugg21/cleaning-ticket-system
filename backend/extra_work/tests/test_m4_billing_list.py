"""M4 commit 2d — EW list billing-month + invoice-status filters, and the
billing fields on the list serializer (redacted from customers).

GET /api/extra-work/ gains:
  * ?billing_period=YYYY-MM  — bucket by COALESCE(invoice_date, completion
    date), the same logic the invoice run uses.
  * ?invoice_status=completed|invoiced — earned-not-invoiced vs invoiced.
Both reuse extra_work.billing and return a queryset, so they compose with
each other and with pagination.

The list rows now carry invoice_date / is_invoiced / invoiced_at, stripped
for a CUSTOMER_USER exactly like the detail serializer.

Fixture + spawned-ticket helper are reused from test_m4_billing_run.py.
"""
from __future__ import annotations

from datetime import date

from rest_framework import status

from tickets.models import TicketStatus

from extra_work.tests.test_m4_billing_run import _InvoiceRunFixture, _dt


LIST_URL = "/api/extra-work/"
_BILLING_KEYS = ("invoice_date", "is_invoiced", "invoiced_at")


class BillingPeriodFilterTests(_InvoiceRunFixture):
    def test_billing_period_buckets_by_completion_month(self):
        may_ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 5, 31)
        )
        jun_ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 6, 15)
        )

        may = self._api(self.admin).get(LIST_URL, {"billing_period": "2026-05"})
        self.assertEqual(may.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {r["id"] for r in may.data["results"]}, {may_ew.id}
        )

        jun = self._api(self.admin).get(LIST_URL, {"billing_period": "2026-06"})
        self.assertEqual(
            {r["id"] for r in jun.data["results"]}, {jun_ew.id}
        )

    def test_invoice_date_override_changes_bucket(self):
        # Earned May 31 but provider set invoice_date=Jun 15 -> bills in June
        # (consistent with the invoice run).
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED,
            closed_at=_dt(2026, 5, 31),
            invoice_date=date(2026, 6, 15),
        )
        may = self._api(self.admin).get(LIST_URL, {"billing_period": "2026-05"})
        self.assertEqual([r["id"] for r in may.data["results"]], [])

        jun = self._api(self.admin).get(LIST_URL, {"billing_period": "2026-06"})
        self.assertEqual(
            {r["id"] for r in jun.data["results"]}, {ew.id}
        )

    def test_malformed_period_fails_closed(self):
        # A garbage period returns an empty set, never the full list.
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 5, 31)
        )
        resp = self._api(self.admin).get(LIST_URL, {"billing_period": "garbage"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["results"], [])


class InvoiceStatusFilterTests(_InvoiceRunFixture):
    def test_invoice_status_invoiced(self):
        invoiced = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED,
            closed_at=_dt(2026, 5, 31),
            is_invoiced=True,
        )
        # Not-invoiced EW must be excluded.
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 5, 31)
        )

        resp = self._api(self.admin).get(LIST_URL, {"invoice_status": "invoiced"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {r["id"] for r in resp.data["results"]}, {invoiced.id}
        )

    def test_invoice_status_completed(self):
        completed = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 5, 31)
        )
        # Already invoiced -> excluded.
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED,
            closed_at=_dt(2026, 5, 31),
            is_invoiced=True,
        )
        # Not earned (spawned ticket OPEN) -> excluded.
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.OPEN, closed_at=None
        )

        resp = self._api(self.admin).get(LIST_URL, {"invoice_status": "completed"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {r["id"] for r in resp.data["results"]}, {completed.id}
        )

    def test_compose_period_and_status(self):
        may_completed = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 5, 31)
        )
        # June earned-not-invoiced: matches status, wrong period.
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 6, 15)
        )
        # May invoiced: matches period, wrong status.
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED,
            closed_at=_dt(2026, 5, 20),
            is_invoiced=True,
        )

        resp = self._api(self.admin).get(
            LIST_URL,
            {"billing_period": "2026-05", "invoice_status": "completed"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {r["id"] for r in resp.data["results"]}, {may_completed.id}
        )


class ListBillingFieldVisibilityTests(_InvoiceRunFixture):
    def test_pagination_envelope_intact(self):
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 5, 31)
        )
        resp = self._api(self.admin).get(LIST_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("count", resp.data)
        self.assertIn("results", resp.data)

    def test_provider_sees_billing_keys(self):
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED,
            closed_at=_dt(2026, 5, 31),
            invoice_date=date(2026, 5, 31),
            is_invoiced=True,
        )
        resp = self._api(self.admin).get(LIST_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.data["results"]
        self.assertGreaterEqual(len(results), 1)
        for row in results:
            for key in _BILLING_KEYS:
                self.assertIn(key, row, f"provider should see {key}")

    def test_list_rows_carry_final_amounts_for_both_audiences(self):
        # RF-13 (#106) — the invoices overview computes month totals from
        # the LIST shape with the final-with-quoted-fallback rule, so the
        # three final_* keys must be present on list rows. They are NOT
        # provider-only (parity with the detail serializer: the final
        # amount is the customer's own invoice amount).
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED,
            closed_at=_dt(2026, 5, 31),
            created_by=self.customer_user,
        )
        final_keys = (
            "final_subtotal_amount",
            "final_vat_amount",
            "final_total_amount",
        )
        for actor, label in (
            (self.admin, "provider"),
            (self.customer_user, "customer"),
        ):
            resp = self._api(actor).get(LIST_URL)
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
            results = resp.data["results"]
            self.assertGreaterEqual(len(results), 1)
            for row in results:
                for key in final_keys:
                    self.assertIn(key, row, f"{label} should see {key}")

    def test_customer_does_not_see_billing_keys(self):
        # The customer sees EW they CREATED (view_own scope); seed one with
        # billing metadata so the redaction assertion is meaningful.
        self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED,
            closed_at=_dt(2026, 5, 31),
            invoice_date=date(2026, 5, 31),
            is_invoiced=True,
            created_by=self.customer_user,
        )
        resp = self._api(self.customer_user).get(LIST_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.data["results"]
        self.assertGreaterEqual(
            len(results), 1, "customer should see the EW they created"
        )
        for row in results:
            for key in _BILLING_KEYS:
                self.assertNotIn(key, row, f"customer must not see {key}")
