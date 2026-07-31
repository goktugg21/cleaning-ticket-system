"""Phase 2b — reversal (negated counter-invoice + EW release)."""
from __future__ import annotations

from decimal import Decimal

from django.utils import timezone
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


class DoubleReversalGuardTests(InvoicingFixture):
    """Sprint 134 — `reverse_invoice` never changes `original.status` (it
    stays SENT on the books by design), so nothing previously stopped a
    SECOND reversal of the same original: both existing guards (status ==
    SENT, not itself a reversal) still passed the second time round, and
    `Invoice.reverses` carried no uniqueness constraint. Each repeat mints
    another negated counter-invoice with a real, gapless number."""

    def _sent_with_ew(self):
        ew = self.make_ew(closed_at=dt(2026, 5, 31))
        inv = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )[0]
        inv = send_invoice(self.admin, issue_invoice(self.admin, inv))
        return ew, inv

    def test_second_reversal_rejected_naming_the_existing_credit_note(self):
        _ew, original = self._sent_with_ew()
        first_reversal = reverse_invoice(self.admin, original)

        with self.assertRaises(InvoiceTransitionError) as ctx:
            reverse_invoice(self.admin, original)
        message = str(ctx.exception)
        self.assertIn(original.number, message)
        self.assertIn(first_reversal.number, message)

        # Refusing the second attempt must not have minted or consumed a
        # number, nor created a second row in `reversed_by`.
        self.assertEqual(original.reversed_by.count(), 1)

    def test_first_reversal_still_works(self):
        _ew, original = self._sent_with_ew()
        reversal = reverse_invoice(self.admin, original)
        self.assertTrue(reversal.is_reversal)
        self.assertEqual(reversal.reverses_id, original.id)

    def test_soft_deleted_reversal_does_not_block_a_legitimate_retry(self):
        # No application code path can soft-delete a reversal today
        # (reversals are created ISSUED; delete_draft_invoice is DRAFT-
        # only) — this constructs the scenario directly, the same way a
        # future admin-side correction tool could reach it, to prove the
        # guard's `deleted_at__isnull=True` filter is not dead code.
        _ew, original = self._sent_with_ew()
        stale_reversal = reverse_invoice(self.admin, original)
        Invoice.objects.filter(pk=stale_reversal.pk).update(
            deleted_at=timezone.now()
        )

        retry_reversal = reverse_invoice(self.admin, original)
        self.assertTrue(retry_reversal.is_reversal)
        self.assertEqual(retry_reversal.reverses_id, original.id)
        self.assertNotEqual(retry_reversal.id, stale_reversal.id)

        # A third attempt, now that a LIVE reversal exists again, is
        # refused the same way the very first double-reversal was.
        with self.assertRaises(InvoiceTransitionError):
            reverse_invoice(self.admin, original)
