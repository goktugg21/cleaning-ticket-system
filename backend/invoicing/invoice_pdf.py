"""
Invoicing — Phase 3: the two-page invoice PDF renderer.

Pure rendering layer (mirrors `extra_work.proposal_pdf.render_proposal_pdf`).
The HTTP wrapper lives in `invoicing.views.InvoicePdfView`.

    render_invoice_pdf(invoice) -> bytes

LOCKED decisions this renders (see the checklist Invoicing section):

  * DUTCH-ONLY, like the proposal PDF + the emails. Static labels/status and
    money/quantity use Dutch formatting ("€ 1.234,56", comma decimals). We
    REUSE the shared brand assets (`config.pdf_branding`: logo, embedded
    DejaVu font with the real euro sign, accent rule) and the canonical
    proposal-PDF formatters (`_fmt_money` / `_nl_number` / `_safe_pdf_text` /
    `_fitted_cell`) so the two families cannot drift.
  * TWO PAGES. Page 1 = the SUMMARY (branded header; number or "CONCEPT"
    while draft; customer + optional building; dates; period; the optional
    free-text fee; and the invoice totals). Page 2 = the ITEMIZED DETAIL:
    one width-safe row per InvoiceLine with "EW-maand / uitgevoerd werk /
    datum" + the money columns, and a totals footer.
  * DRAFT marker: while status==DRAFT a "CONCEPT" marker is shown on every
    page (header band) + in the number slot + a prominent page-1 banner, so
    a printed draft is unmistakable. ISSUED/SENT show the real number and no
    marker.
  * A reversal (is_reversal=True) is titled "Creditnota" and its amounts are
    already negative in the data — they simply render negative.

Page-1 SUMMARY is v1 (auto-composed from the invoice's own figures). The
fully hand-editable page-1 summary line + line editing is the Phase-4 UI.
"""
from __future__ import annotations

from decimal import Decimal

from django.utils import timezone
from fpdf import FPDF

from config.pdf_branding import (
    ACCENT_RGB,
    ACCENT_TINT_RGB,
    FONT_FAMILY,
    LOGO_WIDTH_MM,
    accent_rule,
    draw_logo,
    register_fonts,
)

# REUSE the canonical Dutch formatters + width-safe cell from the proposal
# PDF so money/label rendering cannot drift between the two PDF families.
from extra_work.proposal_pdf import (
    _fitted_cell,
    _fmt_money,
    _nl_number,
    _safe_pdf_text,
)

from .models import Invoice

# Page-2 detail table column widths (mm). Sum = 189, within the 190mm usable
# width of A4 at fpdf2's default 10mm side margins. Width-fitted cells mean
# no realistic value overflows its column.
_COL_MONTH = 18.0
_COL_WORK = 45.0
_COL_DATE = 20.0
_COL_QTY = 16.0
_COL_UNIT = 24.0
_COL_VATPCT = 13.0
_COL_SUBTOTAL = 18.0
_COL_VAT = 16.0
_COL_TOTAL = 19.0

_TABLE_BORDER_RGB = (208, 200, 206)
_DRAFT_GREY = (200, 195, 198)


def _fmt_period(year, month) -> str:
    """(year, month) -> "MM-YYYY"; "-" when unset."""
    if not year or not month:
        return "-"
    return f"{int(month):02d}-{int(year)}"


def _fmt_date(value) -> str:
    if value is None:
        return "-"
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)


def _fmt_qty(value: Decimal) -> str:
    return _nl_number(value if value is not None else Decimal("0"), 2)


class _InvoicePDF(FPDF):
    provider_name: str = ""
    generated_on: str = ""
    is_draft: bool = False

    def header(self) -> None:  # noqa: D401 — fpdf2 hook, runs on every add_page
        # Per-page DRAFT marker so any printed page of a draft is unmistakable
        # (guaranteed present in extracted text on every page).
        if not self.is_draft:
            return
        self.set_font(FONT_FAMILY, "B", 20)
        self.set_text_color(*_DRAFT_GREY)
        self.set_xy(0, 4)
        self.cell(self.w, 8, _safe_pdf_text("C O N C E P T"), align="C")
        self.set_text_color(0, 0, 0)

    def footer(self) -> None:  # noqa: D401 — fpdf2 hook
        self.set_y(-12)
        self.set_font(FONT_FAMILY, "", 7.5)
        self.set_text_color(130, 125, 129)
        third = self.epw / 3.0
        self.cell(third, 6, _safe_pdf_text(f"Pagina {self.page_no()}"))
        self.cell(
            third,
            6,
            _safe_pdf_text(
                f"Gegenereerd op {self.generated_on}" if self.generated_on else ""
            ),
            align="C",
        )
        self.cell(third, 6, _safe_pdf_text(self.provider_name), align="R")
        self.set_text_color(0, 0, 0)


def _draw_header(pdf, *, company_name, doc_title, number_text, status_text):
    """Branded header: logo top-left, provider block, doc title + number
    right-aligned, accent rule underneath. Mirrors proposal_pdf's header."""
    logo_bottom = draw_logo(pdf, y=10.0)

    provider_x = pdf.l_margin + LOGO_WIDTH_MM + 8.0
    pdf.set_xy(provider_x, 11.0)
    pdf.set_font(FONT_FAMILY, "B", 11)
    pdf.cell(80, 6, _safe_pdf_text(company_name))
    pdf.set_xy(provider_x, 17.0)
    pdf.set_font(FONT_FAMILY, "", 8.5)
    pdf.set_text_color(120, 114, 118)
    pdf.cell(80, 4, _safe_pdf_text(doc_title))
    pdf.set_text_color(0, 0, 0)

    meta_x = pdf.w - pdf.r_margin - 80.0
    pdf.set_xy(meta_x, 10.0)
    pdf.set_font(FONT_FAMILY, "B", 15)
    pdf.set_text_color(*ACCENT_RGB)
    pdf.cell(80, 8, _safe_pdf_text(number_text), align="R")
    pdf.set_text_color(0, 0, 0)
    pdf.set_xy(meta_x, 18.5)
    pdf.set_font(FONT_FAMILY, "", 9.5)
    pdf.cell(80, 5, _safe_pdf_text(status_text), align="R")

    rule_y = max(logo_bottom, 25.0) + 3.0
    accent_rule(pdf, rule_y)
    pdf.set_y(rule_y + 5.0)


_STATUS_LABELS_NL = {
    "DRAFT": "Concept",
    "ISSUED": "Uitgegeven",
    "SENT": "Verzonden",
}


def render_invoice_pdf(invoice: Invoice) -> bytes:
    """Render `invoice` as a two-page Dutch PDF. Read-only — no mutations."""
    company_name = getattr(invoice.company, "name", "") or ""
    customer_name = getattr(invoice.customer, "name", "") or ""
    building_name = (
        getattr(invoice.building, "name", "") if invoice.building_id else ""
    )
    is_draft = invoice.status == Invoice.Status.DRAFT

    doc_title = "Creditnota" if invoice.is_reversal else "Factuur"
    if is_draft:
        number_text = "CONCEPT"
    elif invoice.number:
        number_text = invoice.number
    else:
        number_text = f"#{invoice.pk}"
    status_text = f"Status: {_STATUS_LABELS_NL.get(invoice.status, invoice.status)}"

    pdf = _InvoicePDF(unit="mm", format="A4")
    register_fonts(pdf)
    pdf.provider_name = company_name
    pdf.generated_on = timezone.localdate().isoformat()
    pdf.is_draft = is_draft
    pdf.set_auto_page_break(auto=True, margin=18)

    # ==================================================================
    # PAGE 1 — SUMMARY
    # ==================================================================
    pdf.add_page()
    _draw_header(
        pdf,
        company_name=company_name,
        doc_title=doc_title + " extra werk",
        number_text=number_text,
        status_text=status_text,
    )

    # Prominent draft banner.
    if is_draft:
        pdf.set_fill_color(*ACCENT_TINT_RGB)
        pdf.set_text_color(*ACCENT_RGB)
        pdf.set_font(FONT_FAMILY, "B", 10)
        pdf.cell(
            0,
            8,
            _safe_pdf_text(
                "CONCEPT — deze factuur is nog niet uitgegeven"
            ),
            border=0,
            align="C",
            fill=True,
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)

    # Header key/value block — customer/building (left) + dates (right).
    def _kv_row(label_l, value_l, label_r, value_r):
        pdf.set_font(FONT_FAMILY, "B", 10)
        pdf.cell(28, 6, _safe_pdf_text(label_l))
        pdf.set_font(FONT_FAMILY, "", 10)
        pdf.cell(67, 6, _safe_pdf_text(value_l))
        pdf.set_font(FONT_FAMILY, "B", 10)
        pdf.cell(38, 6, _safe_pdf_text(label_r))
        pdf.set_font(FONT_FAMILY, "", 10)
        pdf.cell(0, 6, _safe_pdf_text(value_r), new_x="LMARGIN", new_y="NEXT")

    period_text = _fmt_period(invoice.period_year, invoice.period_month)
    _kv_row(
        "Aanbieder:", company_name,
        "Uitgegeven:", _fmt_date(invoice.issued_at.date() if invoice.issued_at else None),
    )
    _kv_row(
        "Klant:", customer_name,
        "Verzonden:", _fmt_date(invoice.sent_at.date() if invoice.sent_at else None),
    )
    _kv_row(
        "Gebouw:", building_name or "Alle gebouwen",
        "Periode:", period_text,
    )
    pdf.ln(4)

    # Summary line — Ramazan's one-line overview.
    pdf.set_font(FONT_FAMILY, "B", 10)
    pdf.cell(0, 6, _safe_pdf_text("Samenvatting:"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FONT_FAMILY, "", 10)
    scope_text = building_name if building_name else "alle gebouwen"
    pdf.multi_cell(
        0,
        5,
        _safe_pdf_text(
            f"Factuur voor {customer_name} ({scope_text}) — periode "
            f"{period_text}. Totaal {_fmt_money(invoice.total_amount)}."
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(3)

    # Optional free-text fee (label + amount), if set.
    if invoice.optional_fee_amount is not None:
        pdf.set_font(FONT_FAMILY, "B", 10)
        pdf.cell(0, 6, _safe_pdf_text("Aanvullende post:"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(FONT_FAMILY, "", 10)
        fee_label = invoice.optional_fee_label or "Aanvullende kosten"
        pdf.cell(140, 6, _safe_pdf_text(fee_label))
        pdf.cell(
            0, 6, _safe_pdf_text(_fmt_money(invoice.optional_fee_amount)),
            align="R", new_x="LMARGIN", new_y="NEXT",
        )
        pdf.ln(2)

    # Invoice totals block.
    def _total_row(label, amount, *, size):
        pdf.set_font(FONT_FAMILY, "B", size)
        pdf.cell(140, 6, _safe_pdf_text(label), align="R")
        pdf.set_font(FONT_FAMILY, "", size)
        pdf.cell(
            0, 6, _safe_pdf_text(_fmt_money(amount)),
            align="R", new_x="LMARGIN", new_y="NEXT",
        )

    pdf.ln(2)
    _total_row("Subtotaal", invoice.subtotal_amount, size=10)
    _total_row("BTW", invoice.vat_amount, size=10)
    pdf.set_draw_color(*ACCENT_RGB)
    ty = pdf.get_y() + 0.5
    pdf.line(pdf.w - pdf.r_margin - 70, ty, pdf.w - pdf.r_margin, ty)
    pdf.set_draw_color(0, 0, 0)
    pdf.ln(1)
    pdf.set_font(FONT_FAMILY, "B", 11)
    pdf.cell(140, 7, _safe_pdf_text("Totaal"), align="R")
    pdf.cell(
        0, 7, _safe_pdf_text(_fmt_money(invoice.total_amount)),
        align="R", new_x="LMARGIN", new_y="NEXT",
    )

    # ==================================================================
    # PAGE 2 — ITEMIZED DETAIL
    # ==================================================================
    pdf.add_page()
    _draw_header(
        pdf,
        company_name=company_name,
        doc_title=doc_title + " — specificatie",
        number_text=number_text,
        status_text=status_text,
    )

    pdf.set_font(FONT_FAMILY, "B", 11)
    pdf.cell(0, 7, _safe_pdf_text("Uitgevoerd werk (specificatie)"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    # Table header row.
    pdf.set_draw_color(*_TABLE_BORDER_RGB)
    pdf.set_font(FONT_FAMILY, "B", 8.0)
    pdf.set_fill_color(*ACCENT_TINT_RGB)
    pdf.set_text_color(*ACCENT_RGB)
    headers = (
        ("EW-maand", _COL_MONTH, "L"),
        ("Uitgevoerd werk", _COL_WORK, "L"),
        ("Datum", _COL_DATE, "L"),
        ("Aantal", _COL_QTY, "R"),
        ("Eenheidsprijs", _COL_UNIT, "R"),
        ("BTW %", _COL_VATPCT, "R"),
        ("Subtotaal", _COL_SUBTOTAL, "R"),
        ("BTW", _COL_VAT, "R"),
        ("Totaal", _COL_TOTAL, "R"),
    )
    for label, width, align in headers:
        _fitted_cell(pdf, width, 7, label, align=align, border=1, fill=True, base_size=8.0)
    pdf.ln(7)
    pdf.set_text_color(0, 0, 0)

    pdf.set_font(FONT_FAMILY, "", 8.5)
    for line in invoice.lines.all():
        _fitted_cell(pdf, _COL_MONTH, 6, _fmt_period(line.period_year, line.period_month), align="L", border=1, base_size=8.5)
        _fitted_cell(pdf, _COL_WORK, 6, line.description or "", align="L", border=1, base_size=8.5)
        _fitted_cell(pdf, _COL_DATE, 6, _fmt_date(line.performed_on), align="L", border=1, base_size=8.5)
        _fitted_cell(pdf, _COL_QTY, 6, _fmt_qty(line.quantity), align="R", border=1, base_size=8.5)
        _fitted_cell(pdf, _COL_UNIT, 6, _fmt_money(line.unit_price), align="R", border=1, base_size=8.5)
        _fitted_cell(pdf, _COL_VATPCT, 6, _nl_number(line.vat_pct, 2), align="R", border=1, base_size=8.5)
        _fitted_cell(pdf, _COL_SUBTOTAL, 6, _fmt_money(line.line_subtotal), align="R", border=1, base_size=8.5)
        _fitted_cell(pdf, _COL_VAT, 6, _fmt_money(line.line_vat), align="R", border=1, base_size=8.5)
        _fitted_cell(pdf, _COL_TOTAL, 6, _fmt_money(line.line_total), align="R", border=1, base_size=8.5)
        pdf.ln(6)
    pdf.set_draw_color(0, 0, 0)
    pdf.ln(4)

    # Detail totals footer (mirrors the invoice totals).
    _total_row("Subtotaal", invoice.subtotal_amount, size=10)
    _total_row("BTW", invoice.vat_amount, size=10)
    pdf.set_font(FONT_FAMILY, "B", 11)
    pdf.cell(140, 7, _safe_pdf_text("Totaal"), align="R")
    pdf.cell(
        0, 7, _safe_pdf_text(_fmt_money(invoice.total_amount)),
        align="R", new_x="LMARGIN", new_y="NEXT",
    )

    return bytes(pdf.output())
