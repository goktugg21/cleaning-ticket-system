"""
Sprint 28 Batch 14 — Proposal PDF export tests.

The 11 cases below pin:

  * Scope (SUPER_ADMIN can fetch; cross-tenant customer 404s; STAFF
    inherits the parent EW 404).
  * DRAFT invisibility for customers (proposal-detail parity).
  * Privacy lock: `internal_note` is NEVER present in the rendered
    PDF — for ANY caller. (Two tests prove this for both the provider
    and customer audience.) RF-15 embedded a Unicode TTF, which stores
    text as glyph IDs, so sentinel PRESENCE is now proven against the
    pypdf-extracted page text; sentinel ABSENCE is asserted on both
    the extracted text AND the raw bytes (defense in depth).
  * Provider-only override block (override_reason is rendered for
    provider; stripped for customer).
  * Read-only contract: no `ProposalTimelineEvent` is emitted on a
    customer PDF read of a SENT proposal — even though
    `ProposalDetailView` DOES emit `CUSTOMER_VIEWED` for the same
    customer + same proposal.
  * Unicode rendering: the embedded DejaVu face renders `€` and the
    full charset (Turkish characters) instead of mapping them away.

Fixture mirrors `test_sprint28_proposal.py` to keep the surface
familiar.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from pypdf import PdfReader
from rest_framework.test import APIClient

from extra_work.proposal_pdf import render_proposal_pdf

from accounts.models import UserRole
from buildings.models import Building
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from extra_work.models import (
    ExtraWorkCategory,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkStatus,
    Proposal,
    ProposalStatus,
    ProposalTimelineEvent,
    Service,
    ServiceCategory,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"

# Sentinel strings the privacy-lock tests search for in the rendered
# PDF (extracted text for presence; extracted text + raw bytes for
# absence).
EXPLANATION_SENTINEL = "EXPLANATION-PUBLIC-XYZ"
INTERNAL_SENTINEL = "SECRET-PROVIDER-XYZ"
OVERRIDE_SENTINEL = "OVERRIDE-REASON-ABC123"


def _pdf_text(data: bytes) -> str:
    """All page text of `data`, extracted via pypdf. The embedded
    DejaVu font writes a ToUnicode CMap, so extraction round-trips the
    original strings (including € and Turkish characters)."""
    reader = PdfReader(BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class ProposalPdfFixtureMixin:
    """Shared fixture, modelled on `ProposalFixtureMixin` in
    `test_sprint28_proposal.py`. Single Customer + Building +
    Service; one SENT proposal with one line whose
    `customer_explanation` and `internal_note` carry the sentinel
    strings the privacy-lock tests grep for."""

    @classmethod
    def _setup_fixture(cls):
        cls.company = Company.objects.create(
            name="Proposal Provider PDF", slug="prov-b14"
        )
        cls.other_company = Company.objects.create(
            name="Other Provider PDF", slug="prov-other-b14"
        )
        cls.building = Building.objects.create(
            company=cls.company, name="Building-B14"
        )
        cls.other_building = Building.objects.create(
            company=cls.other_company, name="Other-Building-B14"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            name="Customer-B14",
            building=cls.building,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.other_customer = Customer.objects.create(
            company=cls.other_company,
            name="Other-Customer-B14",
            building=cls.other_building,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.other_customer, building=cls.other_building
        )

        cls.super_admin = _mk(
            "super-b14@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("admin-b14@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )
        cls.staff = _mk("staff-b14@example.com", UserRole.STAFF)

        cls.cust_user = _mk("cust-b14@example.com", UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=cls.building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        # Cross-tenant customer used by the cross-tenant 404 test.
        cls.other_cust_user = _mk(
            "other-cust-b14@example.com", UserRole.CUSTOMER_USER
        )
        other_membership = CustomerUserMembership.objects.create(
            customer=cls.other_customer, user=cls.other_cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=other_membership,
            building=cls.other_building,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        cls.service_cat = ServiceCategory.objects.create(name="Cat-B14")
        cls.service = Service.objects.create(
            category=cls.service_cat,
            company=cls.company,
            name="Window cleaning B14",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _make_ew(
        self,
        *,
        status: str = ExtraWorkStatus.UNDER_REVIEW,
    ) -> ExtraWorkRequest:
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title="PDF fixture EW",
            description="parent description for PDF",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=status,
        )
        # B2 (system-business-logic-and-workflows.md §7.0) — cart-line
        # quantity must match the proposal-line quantity in
        # `_line_payload` ("2.00") so the SEND coverage gate passes.
        # No PDF test asserts cart quantity directly.
        ExtraWorkRequestItem.objects.create(
            extra_work_request=ew,
            service=self.service,
            quantity=Decimal("2.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=date(2026, 6, 15),
            customer_note="",
        )
        return ew

    def _pdf_url(self, ew_id: int, pid: int) -> str:
        return f"/api/extra-work/{ew_id}/proposals/{pid}/pdf/"

    def _line_payload(self, **overrides) -> dict:
        payload = {
            "service": self.service.id,
            "quantity": "2.00",
            "unit_type": ExtraWorkPricingUnitType.HOURS,
            "unit_price": "50.00",
            "vat_pct": "21.00",
            "customer_explanation": EXPLANATION_SENTINEL,
            "internal_note": INTERNAL_SENTINEL,
        }
        payload.update(overrides)
        return payload

    def _create_proposal(self, ew: ExtraWorkRequest) -> Proposal:
        response = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/proposals/",
            {"lines": [self._line_payload()]},
            format="json",
        )
        assert response.status_code == 201, response.data
        return Proposal.objects.get(pk=response.data["id"])

    def _send(self, ew: ExtraWorkRequest, proposal: Proposal):
        response = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/transition/",
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        assert response.status_code == 200, response.data


class ProposalPdfTests(ProposalPdfFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    # ------------------------------------------------------------------
    # 1. Happy path — provider
    # ------------------------------------------------------------------
    def test_pdf_200_for_super_admin(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        self._send(ew, proposal)

        response = self._api(self.super_admin).get(
            self._pdf_url(ew.id, proposal.id)
        )
        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertGreater(len(response.content), 200)

    # ------------------------------------------------------------------
    # 2. Happy path — customer on SENT
    # ------------------------------------------------------------------
    def test_pdf_200_for_customer_user_on_sent(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        self._send(ew, proposal)

        response = self._api(self.cust_user).get(
            self._pdf_url(ew.id, proposal.id)
        )
        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertTrue(response.content.startswith(b"%PDF"))

    # ------------------------------------------------------------------
    # 3. DRAFT invisibility for customer
    # ------------------------------------------------------------------
    def test_pdf_404_for_customer_user_on_draft(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        # Proposal is DRAFT — customers must not see it via the PDF
        # endpoint either, mirroring the parity lock on
        # `_resolve_proposal_or_404`.
        response = self._api(self.cust_user).get(
            self._pdf_url(ew.id, proposal.id)
        )
        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------
    # 4. Staff is excluded
    # ------------------------------------------------------------------
    def test_pdf_403_for_staff(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        self._send(ew, proposal)
        # STAFF cannot see the parent EW (scope_extra_work_for returns
        # .none() for STAFF), so the PDF endpoint 404s — matching how
        # `ProposalDetailView` answers STAFF on the same fixture.
        response = self._api(self.staff).get(
            self._pdf_url(ew.id, proposal.id)
        )
        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------
    # 5. Cross-tenant customer 404
    # ------------------------------------------------------------------
    def test_pdf_404_cross_tenant_customer(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        self._send(ew, proposal)
        # The "other" customer belongs to a different Customer + Company.
        response = self._api(self.other_cust_user).get(
            self._pdf_url(ew.id, proposal.id)
        )
        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------
    # 6. Privacy lock — provider read
    # ------------------------------------------------------------------
    def test_pdf_strips_internal_note_for_provider(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        self._send(ew, proposal)

        response = self._api(self.super_admin).get(
            self._pdf_url(ew.id, proposal.id)
        )
        self.assertEqual(response.status_code, 200)
        text = _pdf_text(response.content)
        # internal_note is NEVER rendered, even for the provider —
        # absent from the extracted text AND the raw bytes.
        self.assertNotIn(INTERNAL_SENTINEL, text)
        self.assertNotIn(INTERNAL_SENTINEL.encode(), response.content)
        # The customer-visible explanation IS rendered for the provider.
        self.assertIn(EXPLANATION_SENTINEL, text)

    # ------------------------------------------------------------------
    # 7. Privacy lock — customer read
    # ------------------------------------------------------------------
    def test_pdf_strips_internal_note_for_customer(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        self._send(ew, proposal)

        response = self._api(self.cust_user).get(
            self._pdf_url(ew.id, proposal.id)
        )
        self.assertEqual(response.status_code, 200)
        text = _pdf_text(response.content)
        self.assertNotIn(INTERNAL_SENTINEL, text)
        self.assertNotIn(INTERNAL_SENTINEL.encode(), response.content)
        self.assertIn(EXPLANATION_SENTINEL, text)

    # ------------------------------------------------------------------
    # 8. Override block — visible to provider
    # ------------------------------------------------------------------
    def test_pdf_includes_override_reason_for_provider_when_set(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        self._send(ew, proposal)
        proposal.override_reason = OVERRIDE_SENTINEL
        proposal.override_by = self.admin
        proposal.save(update_fields=["override_reason", "override_by"])

        response = self._api(self.super_admin).get(
            self._pdf_url(ew.id, proposal.id)
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(OVERRIDE_SENTINEL, _pdf_text(response.content))

    # ------------------------------------------------------------------
    # 9. Override block — stripped for customer
    # ------------------------------------------------------------------
    def test_pdf_omits_override_reason_for_customer_when_set(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        self._send(ew, proposal)
        proposal.override_reason = OVERRIDE_SENTINEL
        proposal.override_by = self.admin
        proposal.save(update_fields=["override_reason", "override_by"])

        response = self._api(self.cust_user).get(
            self._pdf_url(ew.id, proposal.id)
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(OVERRIDE_SENTINEL, _pdf_text(response.content))
        self.assertNotIn(OVERRIDE_SENTINEL.encode(), response.content)

    # ------------------------------------------------------------------
    # 10. Read-only contract — no CUSTOMER_VIEWED event from PDF reads
    # ------------------------------------------------------------------
    def test_pdf_emits_no_timeline_event(self):
        ew = self._make_ew()
        proposal = self._create_proposal(ew)
        self._send(ew, proposal)
        before = ProposalTimelineEvent.objects.count()

        response = self._api(self.cust_user).get(
            self._pdf_url(ew.id, proposal.id)
        )
        self.assertEqual(response.status_code, 200)
        # The PDF endpoint is read-only — unlike ProposalDetailView,
        # which emits CUSTOMER_VIEWED on first customer GET of a SENT
        # proposal, the PDF endpoint must NOT mutate the timeline.
        self.assertEqual(ProposalTimelineEvent.objects.count(), before)

    # ------------------------------------------------------------------
    # 11. Unicode rendering — € + full charset (RF-15)
    # ------------------------------------------------------------------
    def test_pdf_handles_unicode_safely(self):
        ew = self._make_ew()
        # RF-15 — the embedded DejaVu face must RENDER the euro sign
        # and Turkish characters (the old Latin-1 core font mapped €
        # to "EUR" and Turkish glyphs to "?").
        proposal = Proposal.objects.create(
            extra_work_request=ew,
            created_by=self.admin,
        )
        # Bypass the API to drop a glyph-heavy explanation directly
        # onto the line model.
        from extra_work.models import ProposalLine

        ProposalLine.objects.create(
            proposal=proposal,
            service=self.service,
            # B2 — quantity must match the cart item created by
            # `_make_ew` (2.00) so apply_proposal_transition's SEND
            # coverage gate passes. Unit price kept at 50.00; the
            # totals are not asserted in this unicode-render test.
            quantity=Decimal("2.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            unit_price=Decimal("50.00"),
            vat_pct=Decimal("21.00"),
            customer_explanation="Şükrü's Café — İş ğüşiöç € 50",
            internal_note="should-not-render-XYZ",
        )
        proposal.recompute_totals()
        # Drive to SENT so the response would be valid for either viewer.
        from extra_work.proposal_state_machine import (
            apply_proposal_transition,
        )

        apply_proposal_transition(
            proposal, self.admin, ProposalStatus.SENT
        )

        response = self._api(self.super_admin).get(
            self._pdf_url(ew.id, proposal.id)
        )
        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertTrue(response.content.startswith(b"%PDF"))
        text = _pdf_text(response.content)
        # Real glyphs survive the render + extraction round-trip.
        self.assertIn("Şükrü's Café", text)
        self.assertIn("İş ğüşiöç € 50", text)
        # Money strings use the real euro sign, not the "EUR" fallback.
        self.assertIn("€ 50,00", text)


class ProposalPdfWidthFitTest(TestCase):
    """RF-10 (2026-06-24) — the humanized Dutch qty+unit label must fit
    inside the fixed-width Qty column at any realistic quantity. The old
    code wrote the RAW unit enum (e.g. '1.00 x SQUARE_METERS') into a 22mm
    cell with no width fitting, overflowing into the Unit-price column.

    RF-15 — probes with the embedded DejaVu face (the font the renderer
    actually uses), whose metrics are wider than core Helvetica, so the
    worst-case width check stays meaningful after the rebrand."""

    def test_qty_unit_label_fits_qty_column(self):
        from fpdf import FPDF

        from config.pdf_branding import FONT_FAMILY, register_fonts
        from extra_work.models import ProposalLine
        from extra_work.proposal_pdf import (
            QTY_COL_WIDTH,
            _fit_font_size,
            _fmt_qty_unit,
        )

        pdf = FPDF(unit="mm", format="A4")
        register_fonts(pdf)
        pdf.add_page()
        pdf.set_font(FONT_FAMILY, "", 9)

        # Longest unit label (m²) with large, thousands-grouped quantities.
        for qty in ("2.00", "12.00", "99999.99"):
            line = ProposalLine(
                quantity=Decimal(qty),
                unit_type=ExtraWorkPricingUnitType.SQUARE_METERS,
            )
            label = _fmt_qty_unit(line)
            # Humanized Dutch label, not the raw enum.
            self.assertNotIn("SQUARE_METERS", label)
            self.assertTrue(label.endswith("m²"))
            size = _fit_font_size(pdf, label, QTY_COL_WIDTH, 9.0, 6.0)
            pdf.set_font_size(size)
            self.assertLessEqual(
                pdf.get_string_width(label),
                QTY_COL_WIDTH - 1.2,
                f"qty label {label!r} overflows the {QTY_COL_WIDTH}mm column",
            )

        # Dutch number formatting: '.' thousands, ',' decimals.
        line = ProposalLine(
            quantity=Decimal("1234.50"),
            unit_type=ExtraWorkPricingUnitType.ITEM,
        )
        self.assertEqual(_fmt_qty_unit(line), "1.234,50 stuks")

        # #108 Part B — a custom unit label replaces the enum label as
        # the unit text ("overig" never appears), and a realistic custom
        # label at a large grouped quantity still width-fits the Qty
        # column via _fit_font_size (same realistic-bounds convention as
        # the m² probes above — _fitted_cell shrinks, it never truncates).
        line = ProposalLine(
            quantity=Decimal("2.00"),
            unit_type=ExtraWorkPricingUnitType.OTHER,
            custom_unit_label="m³",
        )
        self.assertEqual(_fmt_qty_unit(line), "2,00 m³")
        pallet_line = ProposalLine(
            quantity=Decimal("1234.50"),
            unit_type=ExtraWorkPricingUnitType.OTHER,
            custom_unit_label="pallet",
        )
        label = _fmt_qty_unit(pallet_line)
        self.assertEqual(label, "1.234,50 pallet")
        self.assertNotIn("overig", label)
        size = _fit_font_size(pdf, label, QTY_COL_WIDTH, 9.0, 6.0)
        pdf.set_font_size(size)
        self.assertLessEqual(
            pdf.get_string_width(label),
            QTY_COL_WIDTH - 1.2,
            f"custom-unit label {label!r} overflows the qty column",
        )


class ProposalPdfBrandingTests(ProposalPdfFixtureMixin, TestCase):
    """Change 2 — company-aware branding on the proposal PDF. The fixture
    company (`prov-b14`) is NON-platform by default (neutral / name-only
    header); overriding PLATFORM_BRAND_SLUG to its slug exercises the OSIUS
    branded path. Both must still render valid %PDF bytes (behaviour, not
    pixels)."""

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def _built_proposal(self):
        ew = self._make_ew()
        return self._create_proposal(ew)

    def test_render_non_platform_proposal_is_pdf(self):
        pdf = render_proposal_pdf(
            self._built_proposal(), viewer_is_customer=False
        )
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1000)

    @override_settings(PLATFORM_BRAND_SLUG="prov-b14")
    def test_render_platform_proposal_is_pdf(self):
        # Treat the fixture company AS the platform -> OSIUS branded path.
        pdf = render_proposal_pdf(
            self._built_proposal(), viewer_is_customer=False
        )
        self.assertTrue(pdf.startswith(b"%PDF"))
