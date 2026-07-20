"""Change 2 — provider-specific PDF branding (behaviour, not pixels).

Covers `config.pdf_branding` (the single source of truth) + the invoice
renderer's use of it. The OSIUS designed branding (osius_logo.png + pink) is
used ONLY for the platform company; any other single-company PDF uses that
company's own logo (or a name-only header) with a NEUTRAL accent.
"""
from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from fpdf import FPDF
from PIL import Image

from companies.models import Company
from config.pdf_branding import (
    ACCENT_RGB,
    ACCENT_TINT_RGB,
    NEUTRAL_ACCENT_RGB,
    NEUTRAL_TINT_RGB,
    accent_rgb_for,
    accent_tint_for,
    draw_logo,
    is_platform_brand,
    register_fonts,
)
from customers.models import Customer
from invoicing.invoice_pdf import render_invoice_pdf
from invoicing.models import Invoice, InvoiceLine

User = get_user_model()

PLATFORM_SLUG = "osius"


def _png_bytes() -> bytes:
    bio = BytesIO()
    # A landscape logo so the aspect differs from the OSIUS logo's.
    Image.new("RGB", (40, 12), (0, 120, 200)).save(bio, "PNG")
    return bio.getvalue()


@override_settings(PLATFORM_BRAND_SLUG=PLATFORM_SLUG)
class PdfBrandingFunctionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.platform = Company.objects.create(name="Osius", slug=PLATFORM_SLUG)
        cls.other = Company.objects.create(name="Bright", slug="bright-brand")

    def test_is_platform_brand(self):
        self.assertTrue(is_platform_brand(self.platform))
        self.assertFalse(is_platform_brand(self.other))
        self.assertFalse(is_platform_brand(None))

    def test_accent_rgb_for(self):
        self.assertEqual(accent_rgb_for(self.platform), ACCENT_RGB)
        self.assertEqual(accent_rgb_for(self.other), NEUTRAL_ACCENT_RGB)
        self.assertEqual(accent_rgb_for(None), NEUTRAL_ACCENT_RGB)

    def test_accent_tint_for(self):
        self.assertEqual(accent_tint_for(self.platform), ACCENT_TINT_RGB)
        self.assertEqual(accent_tint_for(self.other), NEUTRAL_TINT_RGB)
        self.assertEqual(accent_tint_for(None), NEUTRAL_TINT_RGB)

    def _fresh_pdf(self):
        pdf = FPDF(unit="mm", format="A4")
        register_fonts(pdf)
        pdf.add_page()
        return pdf

    def test_draw_logo_platform_returns_y(self):
        y = draw_logo(self._fresh_pdf(), self.platform, y=10.0)
        self.assertGreater(y, 10.0)

    def test_draw_logo_name_only_returns_y(self):
        # Non-platform, no logo -> name-only header, no crash.
        y = draw_logo(self._fresh_pdf(), self.other, y=10.0)
        self.assertGreater(y, 10.0)

    def test_draw_logo_none_returns_same_y(self):
        # Cross-company report -> nothing drawn.
        y = draw_logo(self._fresh_pdf(), None, y=10.0)
        self.assertEqual(y, 10.0)

    def test_draw_logo_company_logo_path(self):
        # Non-platform WITH a set logo -> that logo, own aspect, no crash.
        withlogo = Company.objects.create(name="Logo Co", slug="logo-co")
        withlogo.logo = SimpleUploadedFile(
            "logo.png", _png_bytes(), content_type="image/png"
        )
        withlogo.save()
        y = draw_logo(self._fresh_pdf(), withlogo, y=10.0)
        self.assertGreater(y, 10.0)


@override_settings(PLATFORM_BRAND_SLUG=PLATFORM_SLUG)
class InvoicePdfBrandingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            email="brand-admin@example.com",
            password="StrongerTestPassword123!",
            role="COMPANY_ADMIN",
            full_name="Brand Admin",
        )

    def _invoice(self, company):
        customer = Customer.objects.create(company=company, name="Cust")
        inv = Invoice.objects.create(
            company=company,
            customer=customer,
            status=Invoice.Status.SENT,
            number="2026-0001",
            year=2026,
            period_year=2026,
            period_month=5,
            subtotal_amount=Decimal("100.00"),
            vat_amount=Decimal("21.00"),
            total_amount=Decimal("121.00"),
            created_by=self.admin,
        )
        InvoiceLine.objects.create(
            invoice=inv,
            ordering=0,
            description="Werk",
            quantity=Decimal("1.00"),
            unit_price=Decimal("100.00"),
            vat_pct=Decimal("21.00"),
            line_subtotal=Decimal("100.00"),
            line_vat=Decimal("21.00"),
            line_total=Decimal("121.00"),
        )
        return inv

    def test_render_osius_invoice_is_pdf(self):
        company = Company.objects.create(name="Osius", slug=PLATFORM_SLUG)
        pdf = render_invoice_pdf(self._invoice(company))
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1000)

    def test_render_non_osius_name_only_invoice_is_pdf(self):
        company = Company.objects.create(name="Bright", slug="bright-inv")
        pdf = render_invoice_pdf(self._invoice(company))
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_render_non_osius_company_logo_invoice_is_pdf(self):
        company = Company.objects.create(name="Logo Co", slug="logo-inv")
        company.logo = SimpleUploadedFile(
            "logo.png", _png_bytes(), content_type="image/png"
        )
        company.save()
        pdf = render_invoice_pdf(self._invoice(company))
        self.assertTrue(pdf.startswith(b"%PDF"))
