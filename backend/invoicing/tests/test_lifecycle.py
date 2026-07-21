"""Phase 2b — invoice lifecycle (DRAFT -> ISSUED -> SENT)."""
from __future__ import annotations

from decimal import Decimal

from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from invoicing.models import Invoice
from invoicing.selectors import unbilled_extra_work
from invoicing.services import delete_draft_invoice, generate_draft_invoices
from invoicing.state_machine import (
    InvoiceTransitionError,
    assert_mutable,
    issue_invoice,
    reverse_invoice,
    send_invoice,
    unissue_invoice,
)

from ._helpers import InvoicingFixture, dt


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

    def test_issue_sets_status_and_timestamp_but_no_number(self):
        # Number-at-send: issue assigns NO number/year (an ISSUED-but-unsent
        # invoice is numberless so it can be cleanly un-issued).
        inv = issue_invoice(self.admin, self._draft())
        self.assertEqual(inv.status, Invoice.Status.ISSUED)
        self.assertIsNone(inv.number)
        self.assertIsNone(inv.year)
        self.assertIsNotNone(inv.issued_at)
        # Frozen money untouched by issue.
        self.assertEqual(inv.total_amount, Decimal("121.00"))

    def test_send_assigns_gapless_number_and_send_year(self):
        expected_year = timezone.localtime(timezone.now()).year
        inv = send_invoice(self.admin, issue_invoice(self.admin, self._draft()))
        self.assertEqual(inv.status, Invoice.Status.SENT)
        # The number is born at SEND, from the SAME per-company-per-year
        # sequence that ISSUE used before.
        self.assertEqual(inv.number, f"{expected_year}-0001")
        self.assertEqual(inv.year, expected_year)
        self.assertIsNotNone(inv.sent_at)

    def test_send_year_is_current_calendar_year_not_period_year(self):
        expected_year = timezone.localtime(timezone.now()).year
        # Billing period in a DIFFERENT year than the allocation (send) year.
        inv = send_invoice(
            self.admin,
            issue_invoice(self.admin, self._draft(period_year=expected_year - 1)),
        )
        self.assertEqual(inv.year, expected_year)
        self.assertTrue(inv.number.startswith(f"{expected_year}-"))
        self.assertEqual(inv.period_year, expected_year - 1)

    def test_second_send_gets_next_number(self):
        expected_year = timezone.localtime(timezone.now()).year
        a = send_invoice(self.admin, issue_invoice(self.admin, self._draft()))
        b = send_invoice(self.admin, issue_invoice(self.admin, self._draft()))
        self.assertEqual(a.number, f"{expected_year}-0001")
        self.assertEqual(b.number, f"{expected_year}-0002")

    def test_issue_then_send(self):
        inv = issue_invoice(self.admin, self._draft())
        self.assertIsNone(inv.number)  # numberless while merely ISSUED
        inv = send_invoice(self.admin, inv)
        self.assertEqual(inv.status, Invoice.Status.SENT)
        self.assertIsNotNone(inv.sent_at)
        self.assertIsNotNone(inv.number)  # number born at send

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

    # -- un-issue (ISSUED -> DRAFT) ---------------------------------------

    def test_unissue_returns_to_draft_and_clears_issued_at(self):
        inv = issue_invoice(self.admin, self._draft())
        inv = unissue_invoice(self.admin, inv)
        self.assertEqual(inv.status, Invoice.Status.DRAFT)
        self.assertIsNone(inv.number)  # never had one -> nothing consumed
        self.assertIsNone(inv.year)
        self.assertIsNone(inv.issued_at)

    def test_unissue_rejected_for_draft(self):
        with self.assertRaises(InvoiceTransitionError):
            unissue_invoice(self.admin, self._draft())

    def test_unissue_rejected_for_sent(self):
        sent = send_invoice(self.admin, issue_invoice(self.admin, self._draft()))
        with self.assertRaises(InvoiceTransitionError):
            unissue_invoice(self.admin, sent)

    def test_unissue_provider_operator_gated(self):
        inv = issue_invoice(self.admin, self._draft())
        with self.assertRaises(PermissionDenied):
            unissue_invoice(self.customer_user, inv)

    def test_issue_unissue_cycle_leaks_no_number(self):
        # Issue + un-issue consumes NO number: the later send still gets 0001.
        expected_year = timezone.localtime(timezone.now()).year
        inv = issue_invoice(self.admin, self._draft())
        inv = unissue_invoice(self.admin, inv)
        inv = send_invoice(self.admin, issue_invoice(self.admin, inv))
        self.assertEqual(inv.number, f"{expected_year}-0001")

    def test_gapless_among_sent_across_an_unissue_cycle(self):
        """A + B issued (no numbers); send A -> N; un-issue B, re-issue, send B
        -> N+1. The two SENT invoices are consecutive with NO gap."""
        expected_year = timezone.localtime(timezone.now()).year
        a = issue_invoice(self.admin, self._draft())
        b = issue_invoice(self.admin, self._draft())
        self.assertIsNone(a.number)
        self.assertIsNone(b.number)
        a = send_invoice(self.admin, a)  # -> 0001
        b = unissue_invoice(self.admin, b)  # back to draft, still numberless
        b = send_invoice(self.admin, issue_invoice(self.admin, b))  # -> 0002
        self.assertEqual(a.number, f"{expected_year}-0001")
        self.assertEqual(b.number, f"{expected_year}-0002")
        seq_a = int(a.number.split("-")[1])
        seq_b = int(b.number.split("-")[1])
        self.assertEqual(seq_b, seq_a + 1)  # consecutive, no gap

    def test_unissue_does_not_release_ew_claim(self):
        ew = self.make_ew(closed_at=dt(2026, 5, 31))
        draft = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, 2026, 5
        )[0]
        ew.refresh_from_db()
        self.assertTrue(ew.is_invoiced)  # claimed by the draft

        unissued = unissue_invoice(self.admin, issue_invoice(self.admin, draft))
        self.assertEqual(unissued.status, Invoice.Status.DRAFT)

        # The claim SURVIVES un-issue (un-issue is not delete): is_invoiced
        # stays set AND the live draft line keeps the EW out of the pool.
        ew.refresh_from_db()
        self.assertTrue(ew.is_invoiced)
        self.assertNotIn(
            ew.id,
            [
                e.id
                for e in unbilled_extra_work(
                    self.admin, self.company.id, self.customer.id, 2026, 5
                )
            ],
        )

    def test_reversal_is_numbered_and_not_unissuable(self):
        self.make_ew(closed_at=dt(2026, 5, 31))
        draft = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, 2026, 5
        )[0]
        sent = send_invoice(self.admin, issue_invoice(self.admin, draft))
        reversal = reverse_invoice(self.admin, sent)
        # Reversal is born ISSUED, numbered at creation from the SAME sequence.
        self.assertTrue(sent.number.endswith("-0001"))
        self.assertTrue(reversal.number.endswith("-0002"))
        self.assertEqual(reversal.status, Invoice.Status.ISSUED)
        # A numbered reversal must NOT be un-issuable (would strand a number).
        with self.assertRaises(InvoiceTransitionError):
            unissue_invoice(self.admin, reversal)

    def test_send_keeps_an_existing_reversal_number(self):
        # Sending a reversal (born ISSUED WITH a number) must NOT re-number it.
        self.make_ew(closed_at=dt(2026, 5, 31))
        draft = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, 2026, 5
        )[0]
        sent = send_invoice(self.admin, issue_invoice(self.admin, draft))
        reversal = reverse_invoice(self.admin, sent)
        original_number = reversal.number
        reversal = send_invoice(self.admin, reversal)
        self.assertEqual(reversal.status, Invoice.Status.SENT)
        self.assertEqual(reversal.number, original_number)
