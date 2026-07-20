"""Phase 2b — invoice lifecycle (DRAFT -> ISSUED -> SENT)."""
from __future__ import annotations

from decimal import Decimal

from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from invoicing.models import Invoice
from invoicing.services import delete_draft_invoice
from invoicing.state_machine import (
    InvoiceTransitionError,
    assert_mutable,
    issue_invoice,
    send_invoice,
)

from ._helpers import InvoicingFixture


class LifecycleTests(InvoicingFixture):
    def _draft(self, *, period_year=2026, period_month=5):
        return Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=Invoice.Status.DRAFT,
            created_by=self.admin,
            period_year=period_year,
            period_month=period_month,
            subtotal_amount=Decimal("100.00"),
            vat_amount=Decimal("21.00"),
            total_amount=Decimal("121.00"),
        )

    def test_issue_assigns_number_status_and_timestamp(self):
        expected_year = timezone.localtime(timezone.now()).year
        inv = issue_invoice(self.admin, self._draft())
        self.assertEqual(inv.status, Invoice.Status.ISSUED)
        self.assertEqual(inv.number, f"{expected_year}-0001")
        self.assertEqual(inv.year, expected_year)
        self.assertIsNotNone(inv.issued_at)
        # Frozen money untouched by issue.
        self.assertEqual(inv.total_amount, Decimal("121.00"))

    def test_issue_year_is_current_calendar_year_not_period_year(self):
        expected_year = timezone.localtime(timezone.now()).year
        # Billing period in a DIFFERENT year than issue.
        inv = issue_invoice(self.admin, self._draft(period_year=expected_year - 1))
        self.assertEqual(inv.year, expected_year)
        self.assertTrue(inv.number.startswith(f"{expected_year}-"))
        self.assertEqual(inv.period_year, expected_year - 1)

    def test_second_issue_gets_next_number(self):
        expected_year = timezone.localtime(timezone.now()).year
        a = issue_invoice(self.admin, self._draft())
        b = issue_invoice(self.admin, self._draft())
        self.assertEqual(a.number, f"{expected_year}-0001")
        self.assertEqual(b.number, f"{expected_year}-0002")

    def test_issue_then_send(self):
        inv = issue_invoice(self.admin, self._draft())
        inv = send_invoice(self.admin, inv)
        self.assertEqual(inv.status, Invoice.Status.SENT)
        self.assertIsNotNone(inv.sent_at)

    def test_issue_from_issued_rejected(self):
        inv = issue_invoice(self.admin, self._draft())
        with self.assertRaises(InvoiceTransitionError):
            issue_invoice(self.admin, inv)

    def test_send_from_draft_rejected(self):
        with self.assertRaises(InvoiceTransitionError):
            send_invoice(self.admin, self._draft())

    def test_send_from_sent_rejected(self):
        inv = send_invoice(self.admin, issue_invoice(self.admin, self._draft()))
        with self.assertRaises(InvoiceTransitionError):
            send_invoice(self.admin, inv)

    def test_issue_provider_operator_gated(self):
        with self.assertRaises(PermissionDenied):
            issue_invoice(self.customer_user, self._draft())

    def test_send_provider_operator_gated(self):
        inv = issue_invoice(self.admin, self._draft())
        with self.assertRaises(PermissionDenied):
            send_invoice(self.customer_user, inv)

    def test_issued_invoice_cannot_be_deleted(self):
        inv = issue_invoice(self.admin, self._draft())
        with self.assertRaises(Exception):  # ValidationError (non-DRAFT)
            delete_draft_invoice(self.admin, inv)

    def test_sent_invoice_cannot_be_deleted(self):
        inv = send_invoice(self.admin, issue_invoice(self.admin, self._draft()))
        with self.assertRaises(Exception):  # ValidationError (non-DRAFT)
            delete_draft_invoice(self.admin, inv)

    def test_assert_mutable_blocks_sent_only(self):
        draft = self._draft()
        assert_mutable(draft)  # no raise
        issued = issue_invoice(self.admin, self._draft())
        assert_mutable(issued)  # no raise
        sent = send_invoice(self.admin, issue_invoice(self.admin, self._draft()))
        with self.assertRaises(InvoiceTransitionError):
            assert_mutable(sent)
