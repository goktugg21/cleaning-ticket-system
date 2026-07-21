"""
Invoicing subsystem — Phase 1 model-level tests (schema only).

Scope is deliberately narrow: these pin the SHAPE of the schema —
NULL-tolerant per-company numbering, the InvoiceLine <-> EW link, the
reversal self-link, and the new Customer billing-schedule + contract-PDF
fields. Generation / lifecycle / numbering-ASSIGNMENT / money-computation
logic is NOT tested here — that lands in Phase 2+.
"""

from __future__ import annotations

import shutil
import tempfile
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from accounts.models import User, UserRole
from buildings.models import Building
from companies.models import Company
from customers.models import Customer
from extra_work.models import ExtraWorkRequest
from invoicing.models import Invoice, InvoiceLine


class _InvoicingBase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Osius", slug="osius")
        self.other_company = Company.objects.create(
            name="Rivalco", slug="rivalco"
        )
        self.building = Building.objects.create(
            company=self.company, name="B1"
        )
        self.customer = Customer.objects.create(
            company=self.company, name="Cust"
        )
        self.other_customer = Customer.objects.create(
            company=self.other_company, name="CustB"
        )
        self.admin = User.objects.create_user(
            email="sa@osius.nl", password="x", role=UserRole.SUPER_ADMIN
        )

    def _invoice(self, company=None, **extra):
        return Invoice.objects.create(
            company=company or self.company,
            customer=extra.pop("customer", self.customer),
            created_by=self.admin,
            **extra,
        )


class InvoiceDraftNumberingShapeTests(_InvoicingBase):
    def test_draft_created_with_null_number(self):
        inv = self._invoice()
        self.assertEqual(inv.status, Invoice.Status.DRAFT)
        self.assertIsNone(inv.number)
        self.assertIsNone(inv.year)
        # Money caches start at zero (frozen later, Phase 2/3).
        self.assertEqual(inv.subtotal_amount, Decimal("0.00"))
        self.assertEqual(inv.total_amount, Decimal("0.00"))

    def test_two_null_number_drafts_coexist_same_company(self):
        a = self._invoice()
        b = self._invoice()
        # Postgres treats NULLs as distinct, so the (company, number)
        # unique constraint does not collapse NULL-numbered drafts.
        self.assertIsNone(a.number)
        self.assertIsNone(b.number)
        self.assertEqual(
            Invoice.objects.filter(
                company=self.company, number__isnull=True
            ).count(),
            2,
        )

    def test_duplicate_non_null_number_within_company_rejected(self):
        self._invoice(number="2026-0001", year=2026)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._invoice(number="2026-0001", year=2026)

    def test_same_number_allowed_across_companies(self):
        a = self._invoice(company=self.company, number="2026-0001", year=2026)
        b = self._invoice(
            company=self.other_company,
            customer=self.other_customer,
            number="2026-0001",
            year=2026,
        )
        # Per-company scoping: identical number string, different company.
        self.assertEqual(a.number, b.number)
        self.assertNotEqual(a.company_id, b.company_id)


class InvoiceLineTests(_InvoicingBase):
    def test_line_links_to_invoice_and_optionally_extra_work(self):
        inv = self._invoice()
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title="EW",
            description="d",
        )
        from_ew = InvoiceLine.objects.create(
            invoice=inv,
            ordering=1,
            description="Extra work April",
            extra_work=ew,
            quantity=Decimal("1.00"),
            unit_price=Decimal("100.00"),
            period_year=2026,
            period_month=4,
        )
        hand_added = InvoiceLine.objects.create(
            invoice=inv,
            ordering=2,
            description="Ad-hoc fee line",
        )
        self.assertEqual(from_ew.invoice_id, inv.id)
        self.assertEqual(from_ew.extra_work_id, ew.id)
        self.assertIsNone(hand_added.extra_work_id)
        # related_name wiring.
        self.assertEqual(inv.lines.count(), 2)
        self.assertIn(from_ew, ew.invoice_lines.all())


class InvoiceReversalLinkageTests(_InvoicingBase):
    def test_is_reversal_and_reverses_self_link_saves(self):
        original = self._invoice(number="2026-0001", year=2026)
        reversal = self._invoice(
            number="2026-0002",
            year=2026,
            is_reversal=True,
            reverses=original,
        )
        self.assertTrue(reversal.is_reversal)
        self.assertEqual(reversal.reverses_id, original.id)
        # reverse accessor.
        self.assertIn(reversal, original.reversed_by.all())
        # A plain (non-reversal) invoice defaults to not-a-reversal.
        self.assertFalse(original.is_reversal)
        self.assertIsNone(original.reverses_id)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CustomerBillingScheduleAndContractTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        # Clean the temp MEDIA_ROOT created by override_settings.
        from django.conf import settings

        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.company = Company.objects.create(name="Osius", slug="osius")

    def test_billing_schedule_fields_round_trip(self):
        c = Customer.objects.create(
            company=self.company,
            name="Cust",
            invoice_day_rule=Customer.InvoiceDayRule.LAST_OF_MONTH,
            invoice_granularity_default=(
                Customer.InvoiceGranularity.PER_BUILDING
            ),
        )
        c.refresh_from_db()
        self.assertEqual(
            c.invoice_day_rule, Customer.InvoiceDayRule.LAST_OF_MONTH
        )
        self.assertEqual(
            c.invoice_granularity_default,
            Customer.InvoiceGranularity.PER_BUILDING,
        )

    def test_billing_schedule_defaults(self):
        c = Customer.objects.create(company=self.company, name="Cust2")
        # Unset day rule = "" (informational); granularity defaults CUSTOMER.
        self.assertEqual(c.invoice_day_rule, "")
        self.assertEqual(
            c.invoice_granularity_default,
            Customer.InvoiceGranularity.CUSTOMER,
        )
        # New arbitrary-day field defaults to NULL (fall back to the rule).
        self.assertIsNone(c.invoice_day_of_month)

    def test_invoice_day_of_month_round_trip(self):
        c = Customer.objects.create(
            company=self.company, name="Cust-day", invoice_day_of_month=15
        )
        c.refresh_from_db()
        self.assertEqual(c.invoice_day_of_month, 15)

    def test_invoice_day_of_month_validator_bounds(self):
        from django.core.exceptions import ValidationError

        c = Customer(company=self.company, name="Cust-bad")
        # 28 is the max valid day (exists in every month).
        c.invoice_day_of_month = 28
        c.full_clean()  # no raise
        for bad in (0, 29, 31):
            c.invoice_day_of_month = bad
            with self.assertRaises(ValidationError):
                c.full_clean()

    def test_contract_pdf_round_trips(self):
        c = Customer.objects.create(company=self.company, name="Cust3")
        c.contract_pdf.save(
            "ignored-client-name.pdf",
            SimpleUploadedFile(
                "ignored-client-name.pdf",
                b"%PDF-1.4 fake",
                content_type="application/pdf",
            ),
            save=True,
        )
        c.refresh_from_db()
        self.assertTrue(c.contract_pdf)
        # uuid filename under customer_contracts/<pk>/, forced .pdf, never
        # the client-supplied name.
        self.assertTrue(
            c.contract_pdf.name.startswith(f"customer_contracts/{c.pk}/")
        )
        self.assertTrue(c.contract_pdf.name.endswith(".pdf"))
        self.assertNotIn("ignored-client-name", c.contract_pdf.name)
