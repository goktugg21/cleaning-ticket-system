"""
Sprint 28 Batch 14 — Proposal PDF renderer.
RF-10 (2026-06-24) — Dutch localization, width-safe layout, professional pass.
RF-15 (2026-06-25) — formal branded pass: Osius logo header, embedded
DejaVu Sans (real euro sign + full charset), accent rule, refined table
header, page footer with generation date.

Pure rendering layer. The HTTP wrapper lives in
`views_proposals.ProposalPdfView`. This module exposes a single
function:

    render_proposal_pdf(proposal, *, viewer_is_customer) -> bytes

Hard rules (mirrored from the Batch 14 brief):

  * `internal_note` is NEVER read or rendered. For ANY caller. Even
    in the provider-side branch. The privacy-lock tests in
    `tests/test_sprint28_proposal_pdf.py` are load-bearing — do not
    introduce a code path that could read the field.
  * Customers do not see the override block (override reason +
    override actor email). Provider operators do.
  * RF-15 replaced the Latin-1 core-font constraint: DejaVu Sans is
    embedded via `config.pdf_branding.register_fonts`, so the real
    euro sign and the full charset (Turkish names included) render
    natively. The privacy tests now extract TEXT via pypdf instead of
    grepping raw bytes, so glyph-ID encoding and stream compression
    are no longer constraints.

RF-10 — the PDF is **Dutch-only** (like the transactional emails):
static labels, status/urgency enums, and unit types render as Dutch
human labels; money/quantity use Dutch number formatting
("€ 1.234,56", comma decimals).
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

from .models import Proposal, ProposalLine


# ---------------------------------------------------------------------------
# Dutch label maps (fallback to the raw enum when unknown, never crash).
# ---------------------------------------------------------------------------
_UNIT_LABELS_NL: dict[str, str] = {
    "HOURS": "uur",
    "SQUARE_METERS": "m²",
    "FIXED": "vast",
    "ITEM": "stuks",
    "OTHER": "overig",
}
_STATUS_LABELS_NL: dict[str, str] = {
    "DRAFT": "Concept",
    "SENT": "Verzonden",
    "CUSTOMER_APPROVED": "Goedgekeurd door klant",
    "CUSTOMER_REJECTED": "Afgewezen door klant",
    "CANCELLED": "Geannuleerd",
}
_URGENCY_LABELS_NL: dict[str, str] = {
    "NORMAL": "Normaal",
    "HIGH": "Hoog",
    "URGENT": "Urgent",
}

# Lines-table column widths (mm). Sum = 189mm, within the 190mm usable
# width of an A4 page at the default fpdf2 10mm side margins. Exposed so the
# width-fit regression test can assert against the real Qty column width.
QTY_COL_WIDTH = 22.0
_COL_LABEL = 60.0
_COL_UNIT_PRICE = 25.0
_COL_VAT_PCT = 15.0
_COL_SUBTOTAL = 22.0
_COL_VAT = 20.0
_COL_TOTAL = 25.0

# Light border tone for the lines table (reset to black afterwards).
_TABLE_BORDER_RGB = (208, 200, 206)


# ---------------------------------------------------------------------------
# Safe-text helper
# ---------------------------------------------------------------------------
# Typographic normalization only — the embedded DejaVu face renders the
# full charset, so nothing is mapped away for font reasons anymore
# (RF-15 deleted the old €->"EUR" mapping and the Latin-1 round-trip).
_GLYPH_SUBSTITUTIONS: tuple[tuple[str, str], ...] = (
    ("–", "-"),      # –  EN DASH
    ("—", "-"),      # —  EM DASH
    ("“", '"'),      # “
    ("”", '"'),      # ”
    ("‘", "'"),      # ‘
    ("’", "'"),      # ’
)


def _safe_pdf_text(value: object) -> str:
    """
    Coerce a user-supplied value into a rendering-safe string:
    None becomes "", and common typographic glyphs are normalized to
    their plain ASCII forms. No charset narrowing happens here — the
    embedded Unicode font renders €, m², Turkish characters, etc.
    """
    if value is None:
        return ""
    text = str(value)
    for needle, replacement in _GLYPH_SUBSTITUTIONS:
        text = text.replace(needle, replacement)
    return text


# ---------------------------------------------------------------------------
# Dutch number / money formatting
# ---------------------------------------------------------------------------
def _nl_number(value: Decimal, places: int = 2) -> str:
    """Format a Decimal in Dutch convention: '.' thousands, ',' decimals.

    e.g. Decimal('1234.5') -> '1.234,50'. Negative sign preserved.
    """
    if value is None:
        value = Decimal("0")
    quant = Decimal(1).scaleb(-places)  # 0.01 for places=2
    q = value.quantize(quant)
    # US grouping first ('1,234.50'), then swap separators via a sentinel.
    us = f"{q:,.{places}f}"
    return us.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _fmt_money(amount: Decimal | None) -> str:
    if amount is None:
        amount = Decimal("0.00")
    return f"€ {_nl_number(amount, 2)}"


def _fmt_qty_unit(line: ProposalLine) -> str:
    """Humanized Dutch 'quantity unit' label, e.g. '12,00 m²'.

    #108 Part B — a line entered via the composer's "Custom…" unit
    carries an operator-supplied `custom_unit_label`; when present it IS
    the unit text (the enum behind it is OTHER, which renders as
    nothing meaningful). `_fitted_cell` width-fits the result, so a long
    custom name shrinks instead of bleeding into the next column.
    """
    if (line.custom_unit_label or "").strip():
        unit = line.custom_unit_label.strip()
    else:
        unit = _UNIT_LABELS_NL.get(line.unit_type, str(line.unit_type))
    return f"{_nl_number(line.quantity, 2)} {unit}"


def _fmt_iso_date(value) -> str:
    if value is None:
        return "-"
    # `value` is a tz-aware datetime (auto_now_add) — render as ISO
    # date for stable test assertions.
    try:
        return value.date().isoformat()
    except AttributeError:
        return str(value)


# ---------------------------------------------------------------------------
# Width-aware cell rendering — no overflow at any realistic quantity.
# ---------------------------------------------------------------------------
def _fit_font_size(
    pdf: FPDF,
    text: str,
    width: float,
    base_size: float,
    min_size: float = 6.0,
    pad: float = 1.2,
) -> float:
    """Largest font size <= base_size (in 0.5 steps, floored at min_size)
    at which `text` fits within `width - pad` mm. Requires the font family
    + style to already be set; only the size is probed."""
    avail = max(width - pad, 1.0)
    size = base_size
    pdf.set_font_size(size)
    while size > min_size and pdf.get_string_width(text) > avail:
        size -= 0.5
        pdf.set_font_size(size)
    return size


def _fitted_cell(
    pdf: FPDF,
    width: float,
    height: float,
    text: str,
    *,
    align: str = "L",
    border: int = 0,
    fill: bool = False,
    base_size: float = 9.0,
    min_size: float = 6.0,
) -> None:
    """Render one table cell, shrinking the font (down to `min_size`) so the
    text never overflows the column. Restores `base_size` afterwards so the
    row stays visually consistent. This is the RF-10 fix for the raw-enum
    overflow bug (a long unit label used to bleed into the next column)."""
    safe = _safe_pdf_text(text)
    _fit_font_size(pdf, safe, width, base_size, min_size)
    pdf.cell(width, height, safe, border=border, align=align, fill=fill)
    pdf.set_font_size(base_size)


# ---------------------------------------------------------------------------
# PDF subclass — footer (page number + generation date + provider name).
# ---------------------------------------------------------------------------
class _ProposalPDF(FPDF):
    provider_name: str = ""
    generated_on: str = ""

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


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------
def render_proposal_pdf(
    proposal: Proposal,
    *,
    viewer_is_customer: bool,
) -> bytes:
    """
    Render `proposal` as a PDF. Read-only — no model mutations, no
    timeline events emitted.

    `viewer_is_customer=True` suppresses the override block. The
    customer-explanation field (per line) IS rendered for both
    audiences. The internal_note field is never read for either.
    """
    extra_work = proposal.extra_work_request
    company_name = getattr(extra_work.company, "name", "") or ""
    customer_name = getattr(extra_work.customer, "name", "") or ""
    building_name = getattr(extra_work.building, "name", "") or ""

    pdf = _ProposalPDF(unit="mm", format="A4")
    register_fonts(pdf)
    pdf.provider_name = company_name
    pdf.generated_on = timezone.localdate().isoformat()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    # ------------------------------------------------------------------
    # Branded header — logo top-left, provider block beside it,
    # proposal meta right-aligned, accent rule underneath.
    # ------------------------------------------------------------------
    logo_bottom = draw_logo(pdf, y=10.0)

    provider_x = pdf.l_margin + LOGO_WIDTH_MM + 8.0
    pdf.set_xy(provider_x, 11.0)
    pdf.set_font(FONT_FAMILY, "B", 11)
    pdf.cell(80, 6, _safe_pdf_text(company_name))
    pdf.set_xy(provider_x, 17.0)
    pdf.set_font(FONT_FAMILY, "", 8.5)
    pdf.set_text_color(120, 114, 118)
    pdf.cell(80, 4, _safe_pdf_text("Prijsvoorstel extra werk"))
    pdf.set_text_color(0, 0, 0)

    status_nl = _STATUS_LABELS_NL.get(proposal.status, str(proposal.status))
    meta_x = pdf.w - pdf.r_margin - 80.0
    pdf.set_xy(meta_x, 10.0)
    pdf.set_font(FONT_FAMILY, "B", 15)
    pdf.set_text_color(*ACCENT_RGB)
    pdf.cell(80, 8, _safe_pdf_text(f"Voorstel #{proposal.pk}"), align="R")
    pdf.set_text_color(0, 0, 0)
    pdf.set_xy(meta_x, 18.5)
    pdf.set_font(FONT_FAMILY, "", 9.5)
    pdf.cell(80, 5, _safe_pdf_text(f"Status: {status_nl}"), align="R")

    rule_y = max(logo_bottom, 25.0) + 3.0
    accent_rule(pdf, rule_y)
    pdf.set_y(rule_y + 5.0)

    # ------------------------------------------------------------------
    # Header block — provider/customer/building (left) +
    # created/sent/decided dates (right).
    # ------------------------------------------------------------------
    def _kv_row(label_l: str, value_l: str, label_r: str, value_r: str) -> None:
        pdf.set_font(FONT_FAMILY, "B", 10)
        pdf.cell(28, 6, _safe_pdf_text(label_l))
        pdf.set_font(FONT_FAMILY, "", 10)
        pdf.cell(67, 6, _safe_pdf_text(value_l))
        pdf.set_font(FONT_FAMILY, "B", 10)
        pdf.cell(38, 6, _safe_pdf_text(label_r))
        pdf.set_font(FONT_FAMILY, "", 10)
        pdf.cell(0, 6, _safe_pdf_text(value_r), new_x="LMARGIN", new_y="NEXT")

    _kv_row(
        "Aanbieder:", company_name,
        "Aangemaakt:", _fmt_iso_date(proposal.created_at),
    )
    _kv_row(
        "Klant:", customer_name,
        "Verzonden:", _fmt_iso_date(proposal.sent_at),
    )
    _kv_row(
        "Gebouw:", building_name,
        "Klantbeslissing:", _fmt_iso_date(proposal.customer_decided_at),
    )
    pdf.ln(4)

    # ------------------------------------------------------------------
    # Parent Extra Work context.
    # ------------------------------------------------------------------
    pdf.set_font(FONT_FAMILY, "B", 10)
    pdf.cell(0, 6, _safe_pdf_text("Aanvraag:"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FONT_FAMILY, "", 10)
    description = (extra_work.description or "")[:200]
    pdf.multi_cell(0, 5, _safe_pdf_text(description))
    pdf.ln(1)

    urgency_nl = _URGENCY_LABELS_NL.get(
        extra_work.urgency, str(extra_work.urgency)
    )
    pdf.set_font(FONT_FAMILY, "B", 10)
    pdf.cell(30, 6, _safe_pdf_text("Urgentie:"))
    pdf.set_font(FONT_FAMILY, "", 10)
    pdf.cell(
        0, 6, _safe_pdf_text(urgency_nl), new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(4)

    # ------------------------------------------------------------------
    # Lines table.
    #
    # NOTE — `line.internal_note` is intentionally NOT referenced in
    # this block. Adding it would break the privacy-lock tests AND the
    # Batch 14 contract.
    # ------------------------------------------------------------------
    # Header row — bold, accent-tinted fill, accent text, numeric
    # columns right-aligned. Light table borders throughout.
    pdf.set_draw_color(*_TABLE_BORDER_RGB)
    pdf.set_font(FONT_FAMILY, "B", 8.5)
    pdf.set_fill_color(*ACCENT_TINT_RGB)
    pdf.set_text_color(*ACCENT_RGB)
    headers = (
        ("Dienst / Omschrijving", _COL_LABEL, "L"),
        ("Aantal", QTY_COL_WIDTH, "R"),
        ("Eenheidsprijs", _COL_UNIT_PRICE, "R"),
        ("BTW %", _COL_VAT_PCT, "R"),
        ("Subtotaal", _COL_SUBTOTAL, "R"),
        ("BTW", _COL_VAT, "R"),
        ("Totaal", _COL_TOTAL, "R"),
    )
    for label, width, align in headers:
        _fitted_cell(
            pdf, width, 7, label, align=align, border=1, fill=True,
            base_size=8.5,
        )
    pdf.ln(7)
    pdf.set_text_color(0, 0, 0)

    pdf.set_font(FONT_FAMILY, "", 9)
    for line in proposal.lines.all().select_related("service"):
        _render_line(pdf, line)
    pdf.set_draw_color(0, 0, 0)

    pdf.ln(4)

    # ------------------------------------------------------------------
    # Totals footer — right-aligned numeric block.
    # ------------------------------------------------------------------
    def _total_row(label: str, amount, *, bold_label: bool, size: int) -> None:
        pdf.set_font(FONT_FAMILY, "B" if bold_label else "", size)
        pdf.cell(140, 6, _safe_pdf_text(label), align="R")
        pdf.set_font(FONT_FAMILY, "", size)
        pdf.cell(
            0, 6, _safe_pdf_text(_fmt_money(amount)),
            align="R", new_x="LMARGIN", new_y="NEXT",
        )

    _total_row("Subtotaal", proposal.subtotal_amount, bold_label=True, size=10)
    _total_row("BTW", proposal.vat_amount, bold_label=True, size=10)
    # Grand total — slightly larger, with a thin accent rule above it.
    pdf.set_draw_color(*ACCENT_RGB)
    ty = pdf.get_y() + 0.5
    pdf.line(pdf.w - pdf.r_margin - 70, ty, pdf.w - pdf.r_margin, ty)
    pdf.set_draw_color(0, 0, 0)
    pdf.ln(1)
    pdf.set_font(FONT_FAMILY, "B", 11)
    pdf.cell(140, 7, _safe_pdf_text("Totaal"), align="R")
    pdf.cell(
        0, 7, _safe_pdf_text(_fmt_money(proposal.total_amount)),
        align="R", new_x="LMARGIN", new_y="NEXT",
    )

    # ------------------------------------------------------------------
    # Override block — provider-only, only when `override_reason` is
    # set on the proposal.
    # ------------------------------------------------------------------
    if (not viewer_is_customer) and (proposal.override_reason or "").strip():
        pdf.ln(6)
        pdf.set_font(FONT_FAMILY, "B", 10)
        pdf.cell(
            0,
            6,
            _safe_pdf_text("Reden override:"),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.set_font(FONT_FAMILY, "", 10)
        pdf.multi_cell(0, 5, _safe_pdf_text(proposal.override_reason))

        override_actor_email = ""
        # Use override_by_id presence to avoid an unconditional FK fetch.
        if proposal.override_by_id:
            try:
                override_actor_email = proposal.override_by.email or ""
            except Exception:  # noqa: BLE001 — defensive only
                override_actor_email = ""
        if override_actor_email:
            pdf.set_font(FONT_FAMILY, "B", 10)
            pdf.cell(35, 6, _safe_pdf_text("Override door:"))
            pdf.set_font(FONT_FAMILY, "", 10)
            pdf.cell(
                0,
                6,
                _safe_pdf_text(override_actor_email),
                new_x="LMARGIN",
                new_y="NEXT",
            )

    output = pdf.output()
    # fpdf2 2.x returns `bytearray`; cast to bytes for the HttpResponse.
    return bytes(output)


# ---------------------------------------------------------------------------
# Per-line rendering
# ---------------------------------------------------------------------------
def _line_label(line: ProposalLine) -> str:
    """Service name when present, otherwise the free-text description."""
    if line.service_id and line.service is not None:
        return line.service.name or ""
    return line.description or ""


def _render_line(pdf: FPDF, line: ProposalLine) -> None:
    """
    Render one proposal line as a row in the lines table, followed by
    an indented `customer_explanation` row when non-empty.

    `line.internal_note` is intentionally NOT read here. See the
    module docstring + the Batch 14 brief for the load-bearing
    privacy contract. Every cell is width-fitted (`_fitted_cell`) so a
    long service name or unit can never bleed into the next column.
    """
    label = _line_label(line)
    _fitted_cell(pdf, _COL_LABEL, 6, label, align="L", border=1)
    _fitted_cell(pdf, QTY_COL_WIDTH, 6, _fmt_qty_unit(line), align="R", border=1)
    _fitted_cell(
        pdf, _COL_UNIT_PRICE, 6, _fmt_money(line.unit_price), align="R", border=1
    )
    _fitted_cell(
        pdf, _COL_VAT_PCT, 6, f"{_nl_number(line.vat_pct, 2)}", align="R", border=1
    )
    _fitted_cell(
        pdf, _COL_SUBTOTAL, 6, _fmt_money(line.line_subtotal), align="R", border=1
    )
    _fitted_cell(pdf, _COL_VAT, 6, _fmt_money(line.line_vat), align="R", border=1)
    _fitted_cell(
        pdf, _COL_TOTAL, 6, _fmt_money(line.line_total), align="R", border=1
    )
    pdf.ln(6)

    explanation = (line.customer_explanation or "").strip()
    if explanation:
        # Indented, full-width secondary row for the customer-visible
        # explanation. `new_x="LMARGIN"` resets x to the page left margin
        # afterwards so the NEXT line's row starts flush — otherwise the
        # residual x offset from the multi_cell shifted every following row
        # rightwards (and clipped it off the page). The internal_note field
        # is never referenced.
        pdf.set_font(FONT_FAMILY, "I", 8)
        pdf.set_x(pdf.l_margin + 2)
        pdf.multi_cell(
            0,
            5,
            _safe_pdf_text(explanation),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.set_font(FONT_FAMILY, "", 9)
