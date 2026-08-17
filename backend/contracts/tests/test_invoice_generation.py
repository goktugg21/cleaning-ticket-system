"""
Sprint 164 §8 — a due forecast row becomes a real DRAFT invoice.

The cases the brief names are each their own test: run twice, a period
not yet due, a mid-year revision change, and a deleted invoice. Plus the
one that matters most for a money path — that existing invoicing
behaviour is untouched.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.test import TestCase

from companies.models import Company
from customers.models import Customer
from invoicing.models import Invoice, InvoiceLine

from contracts.invoice_generation import (
    generate_invoices,
    generate_invoices_for_contract,
)
from contracts.models import (
    ContractInvoice,
    ContractLifecycle,
    ContractLine,
    ContractRevision,
)

from .fixtures import make_contract


class GenerationTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov", slug="prov-164")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer"
        )
        # `Invoice.created_by` is NOT NULL, so a generator run names the
        # user it acts as — see `generate_invoices_for_contract`.
        from django.contrib.auth import get_user_model

        cls.actor = get_user_model().objects.create_user(
            email="s164-generator@example.com",
            password="StrongerTestPassword164!",
            role="SUPER_ADMIN",
            full_name="Generator",
        )

    def contract(self, *, no="CNT-2026-8001", **kwargs):
        kwargs.setdefault("lines", [("Schoonmaak", "1000.00", "10.00")])
        kwargs.setdefault("start_date", date(2026, 1, 1))
        kwargs.setdefault("billing_day", 1)
        return make_contract(
            company=self.company,
            customer=self.customer,
            contract_no=no,
            **kwargs,
        )


class DraftOnlyTests(GenerationTestBase):
    def test_it_creates_a_draft_with_no_number(self):
        """Numbering is assigned at SEND, gapless per company per year.
        A generator that allocated numbers would be numbering documents
        nobody has approved."""
        contract = self.contract()
        result = generate_invoices_for_contract(contract, actor=self.actor, on=date(2026, 3, 15))

        self.assertGreater(result.created_count, 0)
        for invoice in result.created:
            self.assertEqual(invoice.status, Invoice.Status.DRAFT)
            self.assertIsNone(invoice.number)
            self.assertIsNone(invoice.year)
            self.assertIsNone(invoice.issued_at)
            self.assertIsNone(invoice.sent_at)

    def test_the_lines_carry_the_contract_lines_money(self):
        contract = self.contract(
            lines=[("Dagelijks", "1000.00", "10.00"), ("Glas", "250.00", "2.00")]
        )
        result = generate_invoices_for_contract(contract, actor=self.actor, on=date(2026, 1, 31))
        invoice = result.created[0]

        lines = list(invoice.lines.order_by("ordering"))
        self.assertEqual([line.description for line in lines],
                         ["Dagelijks", "Glas"])
        self.assertEqual(lines[0].unit_price, Decimal("1000.00"))
        # 21% VAT is the model default.
        self.assertEqual(lines[0].line_vat, Decimal("210.00"))
        self.assertEqual(lines[0].line_total, Decimal("1210.00"))
        # `extra_work` is NULL: this line came from a contract, which is
        # the hand-added free-text shape the column already allowed.
        self.assertTrue(all(line.extra_work_id is None for line in lines))
        invoice.refresh_from_db()
        self.assertEqual(invoice.subtotal_amount, Decimal("1250.00"))
        self.assertEqual(invoice.total_amount, Decimal("1512.50"))


class IdempotencyTests(GenerationTestBase):
    def test_running_it_twice_invoices_each_period_once(self):
        contract = self.contract()
        first = generate_invoices_for_contract(contract, actor=self.actor, on=date(2026, 4, 10))
        second = generate_invoices_for_contract(contract, actor=self.actor, on=date(2026, 4, 10))

        self.assertGreater(first.created_count, 0)
        self.assertEqual(second.created_count, 0)
        self.assertEqual(
            ContractInvoice.objects.filter(contract=contract).count(),
            first.created_count,
        )
        self.assertEqual(Invoice.objects.count(), first.created_count)

    def test_the_claim_is_a_database_constraint_not_a_code_check(self):
        """The property that survives concurrency: the SECOND insert is
        refused by Postgres, not by an `if` that two processes could
        both pass."""
        from django.db import IntegrityError, transaction

        contract = self.contract()
        generate_invoices_for_contract(contract, actor=self.actor, on=date(2026, 2, 10))
        claim = ContractInvoice.objects.filter(contract=contract).first()

        other = Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=Invoice.Status.DRAFT,
            created_by=self.actor,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ContractInvoice.objects.create(
                    contract=contract,
                    invoice=other,
                    revision=claim.revision,
                    period_start=claim.period_start,
                    period_end=claim.period_end,
                    invoice_date=claim.invoice_date,
                )

    def test_a_later_run_picks_up_only_the_newly_due_periods(self):
        contract = self.contract()
        january = generate_invoices_for_contract(contract, actor=self.actor, on=date(2026, 1, 15))
        february = generate_invoices_for_contract(contract, actor=self.actor, on=date(2026, 2, 15))

        self.assertEqual(january.created_count, 1)
        self.assertEqual(february.created_count, 1)
        # February re-walks January's period and finds it claimed. That
        # is the design: every run considers every due period and the
        # DATABASE decides which are new, so the skip is counted rather
        # than avoided by remembering where the last run stopped.
        self.assertEqual(february.skipped_existing, 1)
        self.assertEqual(
            ContractInvoice.objects.filter(contract=contract).count(), 2
        )


class NotYetDueTests(GenerationTestBase):
    def test_a_period_whose_date_has_not_arrived_is_not_invoiced(self):
        contract = self.contract(start_date=date(2026, 6, 1))
        result = generate_invoices_for_contract(contract, actor=self.actor, on=date(2026, 5, 31))

        self.assertEqual(result.created_count, 0)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_only_the_periods_up_to_today_are_invoiced(self):
        contract = self.contract(start_date=date(2026, 1, 1))
        result = generate_invoices_for_contract(contract, actor=self.actor, on=date(2026, 3, 1))

        # January, February, March have all reached their billing day.
        self.assertEqual(result.created_count, 3)
        starts = sorted(
            ContractInvoice.objects.filter(contract=contract).values_list(
                "period_start", flat=True
            )
        )
        self.assertEqual(
            starts, [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
        )

    def test_a_draft_contract_bills_nothing(self):
        contract = self.contract(lifecycle=ContractLifecycle.DRAFT)
        self.assertEqual(
            generate_invoices_for_contract(
                contract, actor=self.actor, on=date(2026, 6, 1)
            ).created_count,
            0,
        )

    def test_a_cancelled_contract_bills_nothing(self):
        contract = self.contract(lifecycle=ContractLifecycle.CANCELLED)
        self.assertEqual(
            generate_invoices_for_contract(
                contract, actor=self.actor, on=date(2026, 6, 1)
            ).created_count,
            0,
        )


class RevisionPricingTests(GenerationTestBase):
    def test_each_period_bills_its_OWN_revisions_prices(self):
        """The whole point of revisions. A price that rose in July must
        not retroactively re-price June when the run catches up in
        August."""
        contract = self.contract(lines=[("Schoonmaak", "1000.00", "10.00")])
        raise_ = ContractRevision.objects.create(
            contract=contract,
            label="Prijsverhoging",
            effective_from=date(2026, 7, 1),
        )
        ContractLine.objects.create(
            revision=raise_,
            name="Schoonmaak",
            amount=Decimal("1500.00"),
            hours=Decimal("10.00"),
        )

        generate_invoices_for_contract(contract, actor=self.actor, on=date(2026, 8, 15))

        by_period = {
            claim.period_start: claim
            for claim in ContractInvoice.objects.filter(contract=contract)
        }
        june = by_period[date(2026, 6, 1)]
        july = by_period[date(2026, 7, 1)]

        self.assertEqual(june.invoice.subtotal_amount, Decimal("1000.00"))
        self.assertEqual(july.invoice.subtotal_amount, Decimal("1500.00"))
        # And the claim records WHICH scope priced it, so the answer does
        # not have to be re-derived from dates later.
        self.assertNotEqual(june.revision_id, july.revision_id)
        self.assertEqual(july.revision_id, raise_.id)

    def test_a_period_before_any_revision_is_skipped_not_zero_invoiced(self):
        contract = self.contract(start_date=date(2026, 1, 1))
        contract.revisions.update(effective_from=date(2026, 4, 1))

        result = generate_invoices_for_contract(contract, actor=self.actor, on=date(2026, 2, 15))

        self.assertEqual(result.created_count, 0)
        self.assertGreater(result.skipped_no_revision, 0)
        self.assertEqual(Invoice.objects.count(), 0)


class DeletedInvoiceTests(GenerationTestBase):
    def test_deleting_the_invoice_releases_the_period(self):
        """The choice, stated: `ContractInvoice.invoice` is CASCADE, so
        a hard-deleted invoice takes its claim with it and the period
        becomes generatable again.

        That is the behaviour a hard delete SHOULD have — the invoice is
        gone, so the period is genuinely unbilled, and leaving a claim
        behind would make it permanently unbillable with nothing on
        screen to explain why.

        Note this is about a DELETE, not a reversal: a reversed invoice
        still EXISTS (reversal is a negative counter-document, see
        Addendum B), so its claim stands and the period is not
        regenerated. That is also correct — the period was invoiced, and
        the correction is the reversal pair, not a silent re-issue.
        """
        contract = self.contract()
        generate_invoices_for_contract(contract, actor=self.actor, on=date(2026, 1, 15))
        claim = ContractInvoice.objects.get(contract=contract)
        invoice_id = claim.invoice_id

        Invoice.objects.filter(pk=invoice_id).delete()

        self.assertFalse(ContractInvoice.objects.filter(pk=claim.pk).exists())
        again = generate_invoices_for_contract(contract, actor=self.actor, on=date(2026, 1, 15))
        self.assertEqual(again.created_count, 1)

    def test_soft_deleting_a_draft_also_releases_the_period(self):
        """Sprint 188 §CI — the gap between the CASCADE above and what
        the app actually does.

        `delete_draft_invoice` is the ONLY way an operator removes an
        invoice, and it SOFT-deletes: it stamps `deleted_at` so the
        extra-work claims release and the row stays auditable. A soft
        delete does not fire the FK's CASCADE, so the contract claim
        outlived the invoice it describes and the period was blocked
        forever — the next run found the row, skipped the period, and
        nothing on any screen said why.

        The release is now explicit, and this is the test the hard-delete
        one above could never be: it goes through the real operator path.
        """
        from invoicing.services import delete_draft_invoice

        contract = self.contract()
        generate_invoices_for_contract(
            contract, actor=self.actor, on=date(2026, 1, 15)
        )
        claim = ContractInvoice.objects.get(contract=contract)
        invoice = claim.invoice

        delete_draft_invoice(self.actor, invoice)

        invoice.refresh_from_db()
        self.assertIsNotNone(invoice.deleted_at, "still a SOFT delete")
        self.assertFalse(ContractInvoice.objects.filter(pk=claim.pk).exists())

        again = generate_invoices_for_contract(
            contract, actor=self.actor, on=date(2026, 1, 15)
        )
        self.assertEqual(again.created_count, 1)

    def test_deleting_a_draft_with_no_contract_behind_it_is_unaffected(self):
        """The other half: an ordinary extra-work invoice has no claim,
        and the release path must not care."""
        from invoicing.services import delete_draft_invoice

        invoice = Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=Invoice.Status.DRAFT,
            created_by=self.actor,
        )
        delete_draft_invoice(self.actor, invoice)
        invoice.refresh_from_db()
        self.assertIsNotNone(invoice.deleted_at)

    def test_a_reversed_invoice_keeps_its_claim(self):
        contract = self.contract()
        generate_invoices_for_contract(contract, actor=self.actor, on=date(2026, 1, 15))
        claim = ContractInvoice.objects.get(contract=contract)

        Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=Invoice.Status.DRAFT,
            created_by=self.actor,
            is_reversal=True,
            reverses=claim.invoice,
        )

        again = generate_invoices_for_contract(contract, actor=self.actor, on=date(2026, 1, 15))
        self.assertEqual(again.created_count, 0)
        # Skipped BECAUSE the claim still stands — which is the point of
        # this test. A reversed invoice still exists, so its period is
        # still invoiced and must not be silently re-issued.
        self.assertEqual(again.skipped_existing, 1)


class ExistingInvoicingUnchangedTests(GenerationTestBase):
    def test_invoicing_gained_no_contract_column(self):
        """The dependency runs ONE WAY. `invoicing` knows nothing about
        contracts: the claim lives in `contracts`, so no existing
        invoicing caller sees a new field."""
        field_names = {f.name for f in Invoice._meta.get_fields()}
        self.assertNotIn("contract", field_names)
        self.assertNotIn("contract_id", field_names)
        line_fields = {f.name for f in InvoiceLine._meta.get_fields()}
        self.assertNotIn("contract_line", line_fields)

        # The reverse accessor exists, because a OneToOne from contracts
        # creates one — but it is contracts' relation, not a column on
        # invoicing's table.
        self.assertIn("contract_period", field_names)

    def test_an_extra_work_invoice_is_built_exactly_as_before(self):
        """A hand-built invoice with no contract behind it carries no
        claim and is untouched by the generator."""
        invoice = Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=Invoice.Status.DRAFT,
            created_by=self.actor,
        )
        InvoiceLine.objects.create(
            invoice=invoice,
            ordering=0,
            description="Ad hoc",
            quantity=Decimal("2.00"),
            unit_price=Decimal("50.00"),
            vat_pct=Decimal("21.00"),
            line_subtotal=Decimal("100.00"),
            line_vat=Decimal("21.00"),
            line_total=Decimal("121.00"),
        )
        contract = self.contract()
        generate_invoices_for_contract(contract, actor=self.actor, on=date(2026, 1, 15))

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.DRAFT)
        self.assertEqual(invoice.lines.count(), 1)
        self.assertFalse(
            ContractInvoice.objects.filter(invoice=invoice).exists()
        )


class WholeRunTests(GenerationTestBase):
    def test_generate_invoices_walks_every_active_contract(self):
        a = self.contract(no="CNT-2026-8101")
        b = self.contract(no="CNT-2026-8102")
        self.contract(no="CNT-2026-8103", lifecycle=ContractLifecycle.DRAFT)

        result = generate_invoices(actor=self.actor, on=date(2026, 1, 15))

        self.assertEqual(result.created_count, 2)
        self.assertEqual(
            set(
                ContractInvoice.objects.values_list("contract_id", flat=True)
            ),
            {a.id, b.id},
        )

    def test_it_can_be_limited_to_one_company(self):
        other_company = Company.objects.create(name="Other", slug="other-164")
        other_customer = Customer.objects.create(
            company=other_company, name="Other customer"
        )
        self.contract(no="CNT-2026-8201")
        make_contract(
            company=other_company,
            customer=other_customer,
            contract_no="CNT-2026-8202",
            start_date=date(2026, 1, 1),
            lines=[("X", "100.00", "1.00")],
        )

        result = generate_invoices(actor=self.actor, company=self.company, on=date(2026, 1, 15))

        self.assertEqual(result.created_count, 1)
        self.assertEqual(result.created[0].company_id, self.company.id)
