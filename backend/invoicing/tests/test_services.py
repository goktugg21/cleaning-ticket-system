"""Phase 2a Parts B + C — draft generation (claim) + release on delete."""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from rest_framework.exceptions import PermissionDenied

from customers.models import Customer

from invoicing.models import Invoice, InvoiceLine
from invoicing.selectors import unbilled_extra_work
from invoicing.services import delete_draft_invoice, generate_draft_invoices

from ._helpers import InvoicingFixture, dt

YEAR, MONTH = 2026, 5


class GenerateDraftInvoicesTests(InvoicingFixture):
    def test_per_customer_one_draft_sums_all_buildings(self):
        self.make_ew(closed_at=dt(2026, 5, 31), building=self.building)
        self.make_ew(closed_at=dt(2026, 5, 31), building=self.building2)
        created = generate_draft_invoices(
            self.admin,
            self.company.id,
            self.customer.id,
            YEAR,
            MONTH,
            granularity=Customer.InvoiceGranularity.CUSTOMER,
        )
        self.assertEqual(len(created), 1)
        inv = created[0]
        self.assertIsNone(inv.building_id)  # customer-level
        self.assertEqual(inv.lines.count(), 2)
        # Totals = sum of the two EW earned amounts (100/21/121 each).
        self.assertEqual(inv.subtotal_amount, Decimal("200.00"))
        self.assertEqual(inv.vat_amount, Decimal("42.00"))
        self.assertEqual(inv.total_amount, Decimal("242.00"))

    def test_per_building_one_draft_per_building(self):
        self.make_ew(closed_at=dt(2026, 5, 31), building=self.building)
        self.make_ew(closed_at=dt(2026, 5, 31), building=self.building2)
        created = generate_draft_invoices(
            self.admin,
            self.company.id,
            self.customer.id,
            YEAR,
            MONTH,
            granularity=Customer.InvoiceGranularity.PER_BUILDING,
        )
        self.assertEqual(len(created), 2)
        building_ids = {inv.building_id for inv in created}
        self.assertEqual(building_ids, {self.building.id, self.building2.id})
        for inv in created:
            self.assertEqual(inv.lines.count(), 1)
            self.assertEqual(inv.total_amount, Decimal("121.00"))

    def test_granularity_defaults_from_customer(self):
        self.customer.invoice_granularity_default = (
            Customer.InvoiceGranularity.PER_BUILDING
        )
        self.customer.save(update_fields=["invoice_granularity_default"])
        self.make_ew(closed_at=dt(2026, 5, 31), building=self.building)
        self.make_ew(closed_at=dt(2026, 5, 31), building=self.building2)
        created = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )
        self.assertEqual(len(created), 2)  # per-building default applied

    def test_generation_claims_ew_second_call_finds_nothing(self):
        ew = self.make_ew(closed_at=dt(2026, 5, 31))
        first = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )
        self.assertEqual(len(first), 1)
        ew.refresh_from_db()
        self.assertTrue(ew.is_invoiced)
        self.assertIsNotNone(ew.invoiced_at)
        # No longer unbilled.
        self.assertEqual(
            unbilled_extra_work(
                self.admin, self.company.id, self.customer.id, YEAR, MONTH
            ),
            [],
        )
        # Idempotent: second call finds nothing -> no draft (no double-claim).
        second = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )
        self.assertEqual(second, [])

    def test_totals_use_final_amounts_when_present(self):
        # Earned rule: final_* preferred over quoted when final_total set.
        self.make_ew(
            closed_at=dt(2026, 5, 31),
            subtotal=Decimal("100.00"),
            vat=Decimal("21.00"),
            total=Decimal("121.00"),
            final_subtotal=Decimal("200.00"),
            final_vat=Decimal("42.00"),
            final_total=Decimal("242.00"),
        )
        created = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )
        inv = created[0]
        line = inv.lines.get()
        self.assertEqual(line.line_subtotal, Decimal("200.00"))
        self.assertEqual(line.line_vat, Decimal("42.00"))
        self.assertEqual(line.line_total, Decimal("242.00"))
        self.assertEqual(inv.total_amount, Decimal("242.00"))

    def test_draft_number_year_null_invariant(self):
        self.make_ew(closed_at=dt(2026, 5, 31))
        inv = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )[0]
        self.assertEqual(inv.status, Invoice.Status.DRAFT)
        self.assertIsNone(inv.number)  # numbering is Phase 2b
        self.assertIsNone(inv.year)
        self.assertEqual(inv.period_year, YEAR)
        self.assertEqual(inv.period_month, MONTH)

    def test_line_metadata_from_ew(self):
        self.make_ew(closed_at=dt(2026, 5, 31))
        inv = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )[0]
        line = inv.lines.get()
        self.assertEqual(line.description, "Work performed")
        self.assertEqual((line.period_year, line.period_month), (YEAR, MONTH))
        self.assertEqual(line.performed_on.isoformat(), "2026-05-31")
        self.assertIsNotNone(line.extra_work_id)

    def test_non_operator_forbidden(self):
        self.make_ew(closed_at=dt(2026, 5, 31))
        with self.assertRaises(PermissionDenied):
            generate_draft_invoices(
                self.customer_user,
                self.company.id,
                self.customer.id,
                YEAR,
                MONTH,
            )

    def test_tenant_isolation_actor_a_cannot_generate_for_b(self):
        # Company-B EW; Company-A admin (an operator) generating for B finds
        # nothing in scope -> [] and no invoice, no claim.
        ew_b = self.make_ew(
            closed_at=dt(2026, 5, 31),
            company=self.company_b,
            building=self.building_b,
            customer=self.customer_b,
            created_by=self.admin_b,
        )
        created = generate_draft_invoices(
            self.admin, self.company_b.id, self.customer_b.id, YEAR, MONTH
        )
        self.assertEqual(created, [])
        ew_b.refresh_from_db()
        self.assertFalse(ew_b.is_invoiced)


class DeleteDraftInvoiceTests(InvoicingFixture):
    def test_delete_releases_ew_back_to_unbilled(self):
        ew = self.make_ew(closed_at=dt(2026, 5, 31))
        inv = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )[0]
        ew.refresh_from_db()
        self.assertTrue(ew.is_invoiced)

        delete_draft_invoice(self.admin, inv)

        inv.refresh_from_db()
        self.assertIsNotNone(inv.deleted_at)  # soft-deleted
        ew.refresh_from_db()
        self.assertFalse(ew.is_invoiced)
        self.assertIsNone(ew.invoiced_at)
        # Reappears in the unbilled pool.
        self.assertIn(
            ew.id,
            [
                e.id
                for e in unbilled_extra_work(
                    self.admin, self.company.id, self.customer.id, YEAR, MONTH
                )
            ],
        )

    def test_released_ew_can_be_regenerated(self):
        ew = self.make_ew(closed_at=dt(2026, 5, 31))
        inv1 = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )[0]
        delete_draft_invoice(self.admin, inv1)
        created2 = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )
        self.assertEqual(len(created2), 1)
        self.assertNotEqual(created2[0].id, inv1.id)
        ew.refresh_from_db()
        self.assertTrue(ew.is_invoiced)

    def test_delete_does_not_touch_other_invoices_ew(self):
        ew1 = self.make_ew(closed_at=dt(2026, 5, 31), building=self.building)
        ew2 = self.make_ew(closed_at=dt(2026, 5, 31), building=self.building2)
        created = generate_draft_invoices(
            self.admin,
            self.company.id,
            self.customer.id,
            YEAR,
            MONTH,
            granularity=Customer.InvoiceGranularity.PER_BUILDING,
        )
        inv_for_ew1 = next(
            inv for inv in created if inv.building_id == self.building.id
        )
        delete_draft_invoice(self.admin, inv_for_ew1)
        ew1.refresh_from_db()
        ew2.refresh_from_db()
        self.assertFalse(ew1.is_invoiced)  # released
        self.assertTrue(ew2.is_invoiced)  # untouched (other invoice)

    def test_delete_non_draft_raises(self):
        inv = Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=Invoice.Status.ISSUED,  # not a draft
            created_by=self.admin,
        )
        with self.assertRaises(ValidationError):
            delete_draft_invoice(self.admin, inv)

    def test_delete_non_operator_forbidden(self):
        inv = Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=Invoice.Status.DRAFT,
            created_by=self.admin,
        )
        with self.assertRaises(PermissionDenied):
            delete_draft_invoice(self.customer_user, inv)
