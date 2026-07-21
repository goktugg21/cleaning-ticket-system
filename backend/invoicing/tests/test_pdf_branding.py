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
from pypdf import PdfReader

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


def _page1_header_text(data: bytes, *, top_mm: float = 30.0) -> str:
    """Concatenated page-1 text within `top_mm` of the page top — the branded
    header band (logo slot + provider block + doc title + number/status),
    which sits ABOVE the accent rule. The 'Aanbieder:' body row (which also
    carries the company name) is below the band and excluded. Used to prove
    the name-only header emits the company name exactly ONCE (it used to be
    double-drawn into the logo slot, overprinting the provider block)."""
    reader = PdfReader(BytesIO(data))
    page = reader.pages[0]
    cutoff = float(page.mediabox.height) - top_mm * (72.0 / 25.4)
    parts: list[str] = []

    def _visit(text, cm, tm, font_dict, font_size):
        # tm[5] is the text-space y translation (fpdf2 emits an identity page
        # CTM, so it is the absolute y from the page bottom).
        if text and text.strip() and tm[5] >= cutoff:
            parts.append(text)

    page.extract_text(visitor_text=_visit)
    return " ".join(parts)


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
        # Non-platform, no logo -> the name-only slot now draws NOTHING (the
        # provider block is the single name), so y is returned unchanged
        # (like the cross-company None case) instead of advancing under a
        # slot-drawn name that overprinted the provider block.
        y = draw_logo(self._fresh_pdf(), self.other, y=10.0)
        self.assertEqual(y, 10.0)

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

    def test_name_only_header_emits_company_name_once(self):
        # Regression: a non-platform company with NO logo used to have its
        # name drawn twice in the header — 16pt in the logo slot AND 11pt in
        # the provider block — at nearly the same coordinates, so the two
        # overprinted ("Bright Facilities" collided with itself). The header
        # band must now carry the provider name exactly once.
        company = Company.objects.create(
            name="Bright Facilities", slug="bright-once-inv"
        )
        pdf = render_invoice_pdf(self._invoice(company))
        self.assertTrue(pdf.startswith(b"%PDF"))
        header = _page1_header_text(pdf)
        self.assertEqual(header.count("Bright Facilities"), 1, header)

    def test_render_non_osius_company_logo_invoice_is_pdf(self):
        company = Company.objects.create(name="Logo Co", slug="logo-inv")
        company.logo = SimpleUploadedFile(
            "logo.png", _png_bytes(), content_type="image/png"
        )
        company.save()
        pdf = render_invoice_pdf(self._invoice(company))
        self.assertTrue(pdf.startswith(b"%PDF"))
