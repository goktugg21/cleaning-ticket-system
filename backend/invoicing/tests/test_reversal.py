"""Phase 2b — reversal (negated counter-invoice + EW release)."""
from __future__ import annotations

from decimal import Decimal

from rest_framework.exceptions import PermissionDenied

from invoicing.models import Invoice
from invoicing.selectors import unbilled_extra_work
from invoicing.services import generate_draft_invoices
from invoicing.state_machine import (
    InvoiceTransitionError,
    issue_invoice,
    reverse_invoice,
    send_invoice,
)

from ._helpers import InvoicingFixture, dt

YEAR, MONTH = 2026, 5


class ReversalTests(InvoicingFixture):
    def _sent_with_ew(self):
        ew = self.make_ew(closed_at=dt(2026, 5, 31))
        inv = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )[0]
        inv = send_invoice(self.admin, issue_invoice(self.admin, inv))
        return ew, inv

    def test_reverse_creates_negated_mirror(self):
        _ew, original = self._sent_with_ew()
        reversal = reverse_invoice(self.admin, original)

        self.assertTrue(reversal.is_reversal)
        self.assertEqual(reversal.reverses_id, original.id)
        self.assertEqual(reversal.status, Invoice.Status.ISSUED)
        self.assertIsNotNone(reversal.number)
        self.assertNotEqual(reversal.number, original.number)
        # Negated invoice totals.
        self.assertEqual(reversal.subtotal_amount, -original.subtotal_amount)
        self.assertEqual(reversal.vat_amount, -original.vat_amount)
        self.assertEqual(reversal.total_amount, -original.total_amount)
        self.assertEqual(reversal.total_amount, Decimal("-121.00"))
        # Negated mirror lines that do NOT re-claim EW.
        self.assertEqual(reversal.lines.count(), original.lines.count())
        for orig_line, rev_line in zip(
            original.lines.order_by("ordering", "id"),
            reversal.lines.order_by("ordering", "id"),
        ):
            self.assertEqual(rev_line.line_total, -orig_line.line_total)
            self.assertEqual(rev_line.line_subtotal, -orig_line.line_subtotal)
            self.assertEqual(rev_line.line_vat, -orig_line.line_vat)
            self.assertIsNone(rev_line.extra_work_id)

    def test_reversal_number_from_same_sequence(self):
        _ew, original = self._sent_with_ew()
        reversal = reverse_invoice(self.admin, original)
        # Original 0001, reversal consumes the next number 0002.
        self.assertTrue(original.number.endswith("-0001"))
        self.assertTrue(reversal.number.endswith("-0002"))
        self.assertEqual(original.number[:5], reversal.number[:5])  # same year

    def test_reverse_releases_original_ew(self):
        ew, original = self._sent_with_ew()
        ew.refresh_from_db()
        self.assertTrue(ew.is_invoiced)

        reverse_invoice(self.admin, original)

        ew.refresh_from_db()
        self.assertFalse(ew.is_invoiced)
        self.assertIsNone(ew.invoiced_at)
        self.assertIn(
            ew.id,
            [
                e.id
                for e in unbilled_extra_work(
                    self.admin, self.company.id, self.customer.id, YEAR, MONTH
                )
            ],
        )

    def test_original_stays_sent_not_soft_deleted(self):
        _ew, original = self._sent_with_ew()
        reverse_invoice(self.admin, original)
        original.refresh_from_db()
        self.assertEqual(original.status, Invoice.Status.SENT)
        self.assertIsNone(original.deleted_at)

    def test_released_ew_can_be_regenerated(self):
        ew, original = self._sent_with_ew()
        reverse_invoice(self.admin, original)
        created = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )
        self.assertEqual(len(created), 1)
        ew.refresh_from_db()
        self.assertTrue(ew.is_invoiced)  # re-claimed by the fresh draft

    def test_reverse_draft_rejected(self):
        self.make_ew(closed_at=dt(2026, 5, 31))
        draft = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )[0]
        with self.assertRaises(InvoiceTransitionError):
            reverse_invoice(self.admin, draft)

    def test_reverse_issued_rejected(self):
        self.make_ew(closed_at=dt(2026, 5, 31))
        issued = issue_invoice(
            self.admin,
            generate_draft_invoices(
                self.admin, self.company.id, self.customer.id, YEAR, MONTH
            )[0],
        )
        with self.assertRaises(InvoiceTransitionError):
            reverse_invoice(self.admin, issued)

    def test_reverse_a_reversal_rejected(self):
        _ew, original = self._sent_with_ew()
        reversal = reverse_invoice(self.admin, original)
        # Even once SENT, a reversal is TERMINAL.
        reversal = send_invoice(self.admin, reversal)
        with self.assertRaises(InvoiceTransitionError):
            reverse_invoice(self.admin, reversal)

    def test_reverse_non_operator_rejected(self):
        _ew, original = self._sent_with_ew()
        with self.assertRaises(PermissionDenied):
            reverse_invoice(self.customer_user, original)
