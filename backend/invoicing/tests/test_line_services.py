"""Phase 4a Part B — editable-draft line + meta services (DRAFT-only).

Covers: add/edit/remove a hand line recompute totals; edit an EW-linked
line's amount in place (claim survives); remove an EW-linked line RELEASES
its EW back to unbilled + recomputes; summary_text + fee edits recompute +
persist (fee treated VAT-free); every mutation rejected on ISSUED/SENT;
non-operator rejected; the release-on-remove touches ONLY the target EW.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from rest_framework.exceptions import PermissionDenied

from customers.models import Customer

from invoicing.line_services import (
    add_invoice_line,
    remove_invoice_line,
    update_invoice_line,
    update_invoice_meta,
)
from invoicing.models import Invoice, InvoiceLine
from invoicing.selectors import unbilled_extra_work
from invoicing.services import generate_draft_invoices

from ._helpers import InvoicingFixture, dt

YEAR, MONTH = 2026, 5


class _DraftMixin:
    def _draft(self):
        return Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=Invoice.Status.DRAFT,
            created_by=self.admin,
        )

    def _non_draft(self, status):
        return Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=status,
            created_by=self.admin,
        )


class AddInvoiceLineTests(_DraftMixin, InvoicingFixture):
    def test_add_hand_line_recomputes_totals(self):
        inv = self._draft()
        line = add_invoice_line(
            self.admin,
            inv,
            description="Extra materiaal",
            quantity=Decimal("2"),
            unit_price=Decimal("50.00"),
            vat_pct=Decimal("21.00"),
        )
        self.assertIsNone(line.extra_work_id)  # hand-added claims nothing
        self.assertEqual(line.line_subtotal, Decimal("100.00"))
        self.assertEqual(line.line_vat, Decimal("21.00"))
        self.assertEqual(line.line_total, Decimal("121.00"))
        inv.refresh_from_db()
        self.assertEqual(inv.subtotal_amount, Decimal("100.00"))
        self.assertEqual(inv.vat_amount, Decimal("21.00"))
        self.assertEqual(inv.total_amount, Decimal("121.00"))

    def test_add_appends_at_next_ordering(self):
        inv = self._draft()
        l1 = add_invoice_line(self.admin, inv, unit_price=Decimal("10.00"))
        l2 = add_invoice_line(self.admin, inv, unit_price=Decimal("10.00"))
        self.assertLess(l1.ordering, l2.ordering)

    def test_add_rejected_non_operator(self):
        inv = self._draft()
        with self.assertRaises(PermissionDenied):
            add_invoice_line(
                self.customer_user, inv, unit_price=Decimal("10.00")
            )

    def test_add_rejected_on_issued(self):
        inv = self._non_draft(Invoice.Status.ISSUED)
        with self.assertRaises(ValidationError):
            add_invoice_line(self.admin, inv, unit_price=Decimal("10.00"))

    def test_add_rejected_on_sent(self):
        inv = self._non_draft(Invoice.Status.SENT)
        with self.assertRaises(ValidationError):
            add_invoice_line(self.admin, inv, unit_price=Decimal("10.00"))


class UpdateInvoiceLineTests(_DraftMixin, InvoicingFixture):
    def test_edit_hand_line_recomputes(self):
        inv = self._draft()
        line = add_invoice_line(
            self.admin,
            inv,
            quantity=Decimal("1"),
            unit_price=Decimal("50.00"),
            vat_pct=Decimal("21.00"),
        )
        update_invoice_line(
            self.admin,
            line,
            quantity=Decimal("3"),
            unit_price=Decimal("100.00"),
        )
        line.refresh_from_db()
        self.assertEqual(line.line_subtotal, Decimal("300.00"))
        self.assertEqual(line.line_total, Decimal("363.00"))
        inv.refresh_from_db()
        self.assertEqual(inv.subtotal_amount, Decimal("300.00"))
        self.assertEqual(inv.total_amount, Decimal("363.00"))

    def test_edit_ew_linked_line_amount_in_place_keeps_claim(self):
        self.make_ew(closed_at=dt(2026, 5, 31))
        inv = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )[0]
        line = inv.lines.get()
        self.assertIsNotNone(line.extra_work_id)

        update_invoice_line(
            self.admin,
            line,
            quantity=Decimal("1"),
            unit_price=Decimal("500.00"),
            vat_pct=Decimal("21.00"),
        )
        line.refresh_from_db()
        self.assertIsNotNone(line.extra_work_id)  # claim link survives an edit
        self.assertEqual(line.line_subtotal, Decimal("500.00"))
        self.assertEqual(line.line_total, Decimal("605.00"))
        inv.refresh_from_db()
        self.assertEqual(inv.total_amount, Decimal("605.00"))
        # An in-place edit does NOT release the EW.
        ew = line.extra_work
        ew.refresh_from_db()
        self.assertTrue(ew.is_invoiced)

    def test_edit_description_only_keeps_money(self):
        inv = self._draft()
        line = add_invoice_line(
            self.admin, inv, quantity=Decimal("1"), unit_price=Decimal("80.00")
        )
        update_invoice_line(self.admin, line, description="Nieuwe omschrijving")
        line.refresh_from_db()
        self.assertEqual(line.description, "Nieuwe omschrijving")
        self.assertEqual(line.line_subtotal, Decimal("80.00"))

    def test_edit_rejected_non_operator(self):
        inv = self._draft()
        line = add_invoice_line(self.admin, inv, unit_price=Decimal("10.00"))
        with self.assertRaises(PermissionDenied):
            update_invoice_line(
                self.customer_user, line, unit_price=Decimal("20.00")
            )

    def test_edit_rejected_on_issued(self):
        inv = self._non_draft(Invoice.Status.ISSUED)
        line = InvoiceLine.objects.create(
            invoice=inv, ordering=0, unit_price=Decimal("10.00")
        )
        with self.assertRaises(ValidationError):
            update_invoice_line(self.admin, line, unit_price=Decimal("20.00"))

    def test_edit_rejected_on_sent(self):
        inv = self._non_draft(Invoice.Status.SENT)
        line = InvoiceLine.objects.create(
            invoice=inv, ordering=0, unit_price=Decimal("10.00")
        )
        with self.assertRaises(ValidationError):
            update_invoice_line(self.admin, line, unit_price=Decimal("20.00"))


class RemoveInvoiceLineTests(_DraftMixin, InvoicingFixture):
    def test_remove_hand_line_recomputes(self):
        inv = self._draft()
        add_invoice_line(self.admin, inv, unit_price=Decimal("100.00"))
        l2 = add_invoice_line(self.admin, inv, unit_price=Decimal("50.00"))
        remove_invoice_line(self.admin, l2)
        self.assertFalse(InvoiceLine.objects.filter(id=l2.id).exists())
        inv.refresh_from_db()
        self.assertEqual(inv.subtotal_amount, Decimal("100.00"))
        self.assertEqual(inv.total_amount, Decimal("121.00"))

    def test_remove_ew_linked_line_releases_ew_and_recomputes(self):
        ew = self.make_ew(closed_at=dt(2026, 5, 31))
        inv = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )[0]
        line = inv.lines.get()
        remove_invoice_line(self.admin, line)

        ew.refresh_from_db()
        self.assertFalse(ew.is_invoiced)
        self.assertIsNone(ew.invoiced_at)
        # Reappears in the unbilled pool -> re-invoiceable.
        self.assertIn(
            ew.id,
            [
                e.id
                for e in unbilled_extra_work(
                    self.admin, self.company.id, self.customer.id, YEAR, MONTH
                )
            ],
        )
        inv.refresh_from_db()
        self.assertFalse(inv.lines.exists())
        self.assertEqual(inv.total_amount, Decimal("0.00"))

    def test_remove_hand_line_releases_no_ew(self):
        inv = self._draft()
        line = add_invoice_line(self.admin, inv, unit_price=Decimal("10.00"))
        # No EW to touch; simply removes + recomputes to zero.
        remove_invoice_line(self.admin, line)
        inv.refresh_from_db()
        self.assertEqual(inv.total_amount, Decimal("0.00"))

    def test_remove_releases_only_the_target_ew(self):
        # Two EW-linked lines on one customer-level draft; removing one
        # releases ONLY that EW, the other stays claimed.
        ew1 = self.make_ew(closed_at=dt(2026, 5, 31), building=self.building)
        ew2 = self.make_ew(closed_at=dt(2026, 5, 31), building=self.building2)
        inv = generate_draft_invoices(
            self.admin,
            self.company.id,
            self.customer.id,
            YEAR,
            MONTH,
            granularity=Customer.InvoiceGranularity.CUSTOMER,
        )[0]
        line1 = inv.lines.get(extra_work=ew1)
        remove_invoice_line(self.admin, line1)
        ew1.refresh_from_db()
        ew2.refresh_from_db()
        self.assertFalse(ew1.is_invoiced)  # released
        self.assertTrue(ew2.is_invoiced)  # untouched
        inv.refresh_from_db()
        self.assertEqual(inv.lines.count(), 1)
        self.assertEqual(inv.total_amount, Decimal("121.00"))

    def test_remove_rejected_non_operator(self):
        inv = self._draft()
        line = add_invoice_line(self.admin, inv, unit_price=Decimal("10.00"))
        with self.assertRaises(PermissionDenied):
            remove_invoice_line(self.customer_user, line)

    def test_remove_rejected_on_issued(self):
        inv = self._non_draft(Invoice.Status.ISSUED)
        line = InvoiceLine.objects.create(
            invoice=inv, ordering=0, unit_price=Decimal("10.00")
        )
        with self.assertRaises(ValidationError):
            remove_invoice_line(self.admin, line)

    def test_remove_rejected_on_sent(self):
        inv = self._non_draft(Invoice.Status.SENT)
        line = InvoiceLine.objects.create(
            invoice=inv, ordering=0, unit_price=Decimal("10.00")
        )
        with self.assertRaises(ValidationError):
            remove_invoice_line(self.admin, line)


class UpdateInvoiceMetaTests(_DraftMixin, InvoicingFixture):
    def test_summary_text_persists(self):
        inv = self._draft()
        update_invoice_meta(
            self.admin, inv, summary_text="Handmatige samenvatting"
        )
        inv.refresh_from_db()
        self.assertEqual(inv.summary_text, "Handmatige samenvatting")

    def test_fee_recomputes_totals_vat_free(self):
        inv = self._draft()
        add_invoice_line(
            self.admin,
            inv,
            quantity=Decimal("1"),
            unit_price=Decimal("100.00"),
            vat_pct=Decimal("21.00"),
        )
        # Lines: subtotal 100 / vat 21 / total 121.
        update_invoice_meta(
            self.admin,
            inv,
            optional_fee_label="Spoedtoeslag",
            optional_fee_amount=Decimal("30.00"),
        )
        inv.refresh_from_db()
        self.assertEqual(inv.optional_fee_label, "Spoedtoeslag")
        self.assertEqual(inv.optional_fee_amount, Decimal("30.00"))
        # Fee is VAT-free: it adds to subtotal + total, leaves vat untouched.
        self.assertEqual(inv.subtotal_amount, Decimal("130.00"))
        self.assertEqual(inv.vat_amount, Decimal("21.00"))
        self.assertEqual(inv.total_amount, Decimal("151.00"))
        # Invariant subtotal + vat == total holds under the fee rule.
        self.assertEqual(
            inv.subtotal_amount + inv.vat_amount, inv.total_amount
        )

    def test_partial_update_leaves_other_fields(self):
        inv = self._draft()
        update_invoice_meta(
            self.admin,
            inv,
            optional_fee_label="Toeslag",
            optional_fee_amount=Decimal("10.00"),
        )
        # A summary-only edit must NOT wipe the fee.
        update_invoice_meta(self.admin, inv, summary_text="Alleen samenvatting")
        inv.refresh_from_db()
        self.assertEqual(inv.summary_text, "Alleen samenvatting")
        self.assertEqual(inv.optional_fee_label, "Toeslag")
        self.assertEqual(inv.optional_fee_amount, Decimal("10.00"))

    def test_meta_rejected_non_operator(self):
        inv = self._draft()
        with self.assertRaises(PermissionDenied):
            update_invoice_meta(
                self.customer_user, inv, summary_text="x"
            )

    def test_meta_rejected_on_issued(self):
        inv = self._non_draft(Invoice.Status.ISSUED)
        with self.assertRaises(ValidationError):
            update_invoice_meta(self.admin, inv, summary_text="x")

    def test_meta_rejected_on_sent(self):
        inv = self._non_draft(Invoice.Status.SENT)
        with self.assertRaises(ValidationError):
            update_invoice_meta(self.admin, inv, summary_text="x")
