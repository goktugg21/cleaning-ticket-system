"""
Sprint 183 §2 + §3 — the empty answer, and who created the invoice.

§2  "I cannot generate anything in Due now." Investigated: correct
    behaviour with no explanation, which reads as broken software. These
    tests pin that each KIND of nothing is named, with the count behind
    it, and that the Due panel and the preview say the SAME thing.

§3  The month-end job used to attribute its drafts to "the company's
    longest-serving active COMPANY_ADMIN" because `Invoice.created_by`
    was NOT NULL. It is nullable now and a system run writes NULL. These
    tests pin that a null renders as "System" — never blank, and never
    "Unassigned", which was the wrong fallback once already this month.
"""
from __future__ import annotations

from decimal import Decimal

from rest_framework import status
from rest_framework.test import APIClient

from customers.models import Customer
from invoicing.models import Invoice
from invoicing.services import generate_draft_invoices
from invoicing.tasks import run_daily_invoice_run
from invoicing.why_nothing import (
    ALL_INVOICED,
    NONE_FINISHED,
    NO_EXTRA_WORK,
    NOTHING_TO_EXPLAIN,
    diagnose_nothing_to_invoice,
)
from tickets.models import TicketStatus

from ._helpers import InvoicingFixture, dt


PERIOD = (2026, 5)
DUE_URL = "/api/invoices/due/"
PREVIEW_URL = "/api/invoices/preview/"


class WhyNothingTests(InvoicingFixture):
    """§2 — which kind of nothing is this?"""

    def _diagnose(self, billable_count=0):
        return diagnose_nothing_to_invoice(
            self.admin,
            self.company.id,
            self.customer.id,
            billable_count=billable_count,
        )

    def test_no_extra_work_at_all(self):
        result = self._diagnose()
        self.assertEqual(result["reason"], NO_EXTRA_WORK)
        self.assertEqual(result["unbilled_count"], 0)

    def test_extra_work_exists_but_none_finished(self):
        # THE CRMTEST CASE: 61 extra works, every ticket still open. The
        # count is the whole point — "none finished" is a shrug, "3 extra
        # works, none finished" sends somebody to look at three tickets.
        for _ in range(3):
            self.make_ew(ticket_status=TicketStatus.IN_PROGRESS)

        result = self._diagnose()
        self.assertEqual(result["reason"], NONE_FINISHED)
        self.assertEqual(result["unbilled_count"], 3)
        self.assertEqual(result["finished_count"], 0)

    def test_everything_finished_is_already_invoiced(self):
        self.make_ew(closed_at=dt(2026, 5, 31))
        generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, *PERIOD
        )
        result = self._diagnose()
        self.assertEqual(result["reason"], ALL_INVOICED)
        self.assertEqual(result["invoiced_count"], 1)

    def test_nothing_to_explain_when_there_is_billable_work(self):
        self.make_ew(closed_at=dt(2026, 5, 31))
        result = self._diagnose(billable_count=1)
        self.assertEqual(result["reason"], NOTHING_TO_EXPLAIN)

    def test_the_diagnosis_is_tenant_scoped(self):
        # Company B's book must never leak into company A's explanation.
        self.make_ew(
            company=self.company_b,
            building=self.building_b,
            customer=self.customer_b,
            created_by=self.admin_b,
            ticket_status=TicketStatus.IN_PROGRESS,
        )
        result = self._diagnose()
        self.assertEqual(result["reason"], NO_EXTRA_WORK)
        self.assertEqual(result["unbilled_count"], 0)


class WhyNothingOnBothScreensTests(InvoicingFixture):
    """§2 — the same sentence on the Due panel and the preview."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.customer.invoice_day_of_month = 15
        self.customer.save(update_fields=["invoice_day_of_month"])

    def test_due_row_carries_the_diagnosis(self):
        for _ in range(2):
            self.make_ew(ticket_status=TicketStatus.IN_PROGRESS)

        response = self.client.get(DUE_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = next(
            r for r in response.data if r["customer"] == self.customer.id
        )
        self.assertIn("nothing_reason", row)
        self.assertEqual(row["nothing_reason"]["reason"], NONE_FINISHED)
        self.assertEqual(row["nothing_reason"]["unbilled_count"], 2)

    def test_preview_carries_the_same_diagnosis(self):
        for _ in range(2):
            self.make_ew(ticket_status=TicketStatus.IN_PROGRESS)

        due = self.client.get(DUE_URL).data
        due_row = next(
            r for r in due if r["customer"] == self.customer.id
        )
        preview = self.client.get(
            PREVIEW_URL,
            {"customer": self.customer.id, "year": 2026, "month": 5},
        ).data

        self.assertIn("nothing_reason", preview)
        # Not merely "both non-empty" — the same answer, because they
        # come from the same function. Two screens explaining one
        # emptiness differently is the defect being fixed.
        self.assertEqual(
            preview["nothing_reason"]["reason"],
            due_row["nothing_reason"]["reason"],
        )
        self.assertEqual(
            preview["nothing_reason"]["unbilled_count"],
            due_row["nothing_reason"]["unbilled_count"],
        )

    def test_a_customer_with_billable_work_has_nothing_to_explain(self):
        # P-13 — the class default (day 15) made the is_due assertion
        # below DATE-DEPENDENT: `billing_day_reached` compares the real
        # `today.day >= 15`, so this test was red on the first fourteen
        # days of every month. Day 1 is reached all month.
        self.customer.invoice_day_of_month = 1
        self.customer.save(update_fields=["invoice_day_of_month"])
        self.make_ew(closed_at=dt(2026, 5, 31))
        response = self.client.get(DUE_URL)
        row = next(
            r for r in response.data if r["customer"] == self.customer.id
        )
        self.assertEqual(
            row["nothing_reason"]["reason"], NOTHING_TO_EXPLAIN
        )
        self.assertTrue(row["is_due"])


class SystemCreatedInvoiceTests(InvoicingFixture):
    """§3 — a null `created_by` means the system, and reads that way."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_the_nightly_run_creates_invoices_with_no_human_author(self):
        self.make_ew(closed_at=dt(2026, 5, 31))
        self.customer.invoice_day_of_month = 15
        self.customer.invoice_billing_target = (
            Customer.InvoiceBillingTarget.CUSTOMER
        )
        self.customer.save(
            update_fields=[
                "invoice_day_of_month",
                "invoice_billing_target",
            ]
        )

        run_daily_invoice_run(today="2026-05-15")

        invoice = Invoice.objects.get()
        self.assertIsNone(
            invoice.created_by_id,
            "the run borrowed a person's name again",
        )

    def test_a_human_generated_invoice_still_records_the_human(self):
        # The fix must not erase real authorship — only stop inventing it.
        self.make_ew(closed_at=dt(2026, 5, 31))
        created = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, *PERIOD
        )
        self.assertEqual(created[0].created_by_id, self.admin.id)

    def test_the_endpoint_renders_system_for_a_null_author(self):
        # Every field exposed gets a test that RENDERS the endpoint
        # carrying it — a filter test never serialises a row.
        self.make_ew(closed_at=dt(2026, 5, 31))
        invoice = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, *PERIOD
        )[0]
        Invoice.objects.filter(pk=invoice.pk).update(created_by=None)

        response = self.client.get(f"/api/invoices/{invoice.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["created_by"])
        self.assertEqual(response.data["created_by_label"], "System")
        # The two words this must never be. "Unassigned" names nobody and
        # still implies somebody — the mistake Sprint 180's timeline made.
        self.assertNotEqual(response.data["created_by_label"], "")
        self.assertNotEqual(response.data["created_by_label"], "Unassigned")

    def test_the_endpoint_renders_the_author_when_there_is_one(self):
        self.make_ew(closed_at=dt(2026, 5, 31))
        invoice = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, *PERIOD
        )[0]
        response = self.client.get(f"/api/invoices/{invoice.pk}/")
        self.assertEqual(
            response.data["created_by_label"], self.admin.email
        )

    def test_the_list_endpoint_carries_the_label_too(self):
        self.make_ew(closed_at=dt(2026, 5, 31))
        generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, *PERIOD
        )
        response = self.client.get("/api/invoices/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.data["results"]
        self.assertTrue(rows)
        self.assertIn("created_by_label", rows[0])


class NotificationEventTypeTests(InvoicingFixture):
    """§3's second half — the event type is a real enum member now."""

    def test_invoice_run_completed_is_in_the_enum_with_a_label(self):
        from notifications.models import NotificationEventType

        self.assertEqual(
            NotificationEventType.INVOICE_RUN_COMPLETED,
            "INVOICE_RUN_COMPLETED",
        )
        self.assertEqual(
            NotificationEventType(
                "INVOICE_RUN_COMPLETED"
            ).label,
            "Invoice run completed",
        )

    def test_the_run_writes_a_log_row_that_displays_its_label(self):
        # The actual defect: the value persisted but
        # `get_event_type_display()` returned the raw string.
        from notifications.models import NotificationLog

        self.make_ew(closed_at=dt(2026, 5, 31))
        self.customer.invoice_day_of_month = 15
        self.customer.save(update_fields=["invoice_day_of_month"])

        run_daily_invoice_run(today="2026-05-15")

        log = NotificationLog.objects.filter(
            event_type="INVOICE_RUN_COMPLETED"
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(
            log.get_event_type_display(), "Invoice run completed"
        )
