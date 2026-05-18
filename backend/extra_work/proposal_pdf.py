"""
Sprint 28 Batch 14 — Proposal PDF renderer.

Pure rendering layer. The HTTP wrapper lives in
`views_proposals.ProposalPdfView`. This module exposes a single
function:

    render_proposal_pdf(proposal, *, viewer_is_customer) -> bytes

Hard rules (mirrored from the Batch 14 brief):

  * `internal_note` is NEVER read or rendered. For ANY caller. Even
    in the provider-side branch. The privacy-lock byte-search tests
    in `tests/test_sprint28_proposal_pdf.py` are load-bearing — do
    not introduce a code path that could read the field.
  * Customers do not see the override block (override reason +
    override actor email). Provider operators do.
  * No `EUR` glyph (`€`). The default fpdf2 core fonts are
    Latin-1 and `€` triggers a `Character ... not in font`
    crash. We use the ASCII string "EUR" everywhere.
  * No PDF compression — the byte-search tests grep the raw output
    for sentinel strings.
"""
from __future__ import annotations

from decimal import Decimal

from fpdf import FPDF

from .models import Proposal, ProposalLine


# ---------------------------------------------------------------------------
# Safe-text helper
# ---------------------------------------------------------------------------
_GLYPH_SUBSTITUTIONS: tuple[tuple[str, str], ...] = (
    ("€", "EUR"),   # €
    ("–", "-"),      # –  EN DASH
    ("—", "-"),      # —  EM DASH
    ("“", '"'),      # “
    ("”", '"'),      # ”
    ("‘", "'"),      # ‘
    ("’", "'"),      # ’
)


def _safe_pdf_text(value: object) -> str:
    """
    Coerce a user-supplied string into a form the default Latin-1 PDF
    core font can render without raising `Character ... not in font`.

    1. Explicit substitutions for common typographic glyphs that are
       outside Latin-1 (euro sign, smart quotes, en/em dashes).
    2. Final defensive pass via Latin-1 encode/decode with `errors=
       "replace"` so any remaining non-Latin-1 glyph becomes `?`
       instead of crashing fpdf2 mid-render.
    """
    if value is None:
        return ""
    text = str(value)
    for needle, replacement in _GLYPH_SUBSTITUTIONS:
        text = text.replace(needle, replacement)
    # Final defensive pass — anything still outside Latin-1 becomes
    # a literal "?" via the encode/decode round-trip.
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _fmt_money(amount: Decimal | None) -> str:
    if amount is None:
        amount = Decimal("0.00")
    return f"EUR {amount:.2f}"


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
    pdf = FPDF(unit="mm", format="A4")
    # Disable compression so test byte-search can grep raw PDF bytes.
    # fpdf2 2.8+ exposes both `set_compression()` and the `compress`
    # attribute — use the documented setter.
    pdf.set_compression(False)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ------------------------------------------------------------------
    # Title row — proposal id (left) / status (right).
    # ------------------------------------------------------------------
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(120, 10, _safe_pdf_text(f"Proposal #{proposal.pk}"))
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(
        0,
        10,
        _safe_pdf_text(f"Status: {proposal.status}"),
        align="R",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(2)

    # ------------------------------------------------------------------
    # Header block — provider/customer/building (left) +
    # created/sent/decided dates (right).
    # ------------------------------------------------------------------
    extra_work = proposal.extra_work_request
    company_name = getattr(extra_work.company, "name", "")
    customer_name = getattr(extra_work.customer, "name", "")
    building_name = getattr(extra_work.building, "name", "")

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(95, 6, _safe_pdf_text("Provider:"))
    pdf.cell(0, 6, _safe_pdf_text("Created:"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(95, 6, _safe_pdf_text(company_name))
    pdf.cell(
        0,
        6,
        _safe_pdf_text(_fmt_iso_date(proposal.created_at)),
        new_x="LMARGIN",
        new_y="NEXT",
    )

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(95, 6, _safe_pdf_text("Customer:"))
    pdf.cell(0, 6, _safe_pdf_text("Sent:"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(95, 6, _safe_pdf_text(customer_name))
    pdf.cell(
        0,
        6,
        _safe_pdf_text(_fmt_iso_date(proposal.sent_at)),
        new_x="LMARGIN",
        new_y="NEXT",
    )

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(95, 6, _safe_pdf_text("Building:"))
    pdf.cell(
        0, 6, _safe_pdf_text("Customer decided:"),
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(95, 6, _safe_pdf_text(building_name))
    pdf.cell(
        0,
        6,
        _safe_pdf_text(_fmt_iso_date(proposal.customer_decided_at)),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(4)

    # ------------------------------------------------------------------
    # Parent Extra Work context.
    # ------------------------------------------------------------------
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, _safe_pdf_text("Request:"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    description = (extra_work.description or "")[:200]
    pdf.multi_cell(0, 5, _safe_pdf_text(description))
    pdf.ln(1)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(30, 6, _safe_pdf_text("Urgency:"))
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(
        0,
        6,
        _safe_pdf_text(extra_work.urgency),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(4)

    # ------------------------------------------------------------------
    # Lines table.
    #
    # NOTE — `line.internal_note` is intentionally NOT referenced in
    # this block. Adding it would break the privacy-lock byte-search
    # tests AND the Batch 14 contract.
    # ------------------------------------------------------------------
    pdf.set_font("Helvetica", "B", 9)
    headers = (
        ("Service / Description", 60),
        ("Qty", 22),
        ("Unit price", 25),
        ("VAT %", 15),
        ("Subtotal", 22),
        ("VAT", 20),
        ("Total", 25),
    )
    for label, width in headers:
        pdf.cell(width, 6, _safe_pdf_text(label), border=1)
    pdf.ln(6)

    pdf.set_font("Helvetica", "", 9)
    for line in proposal.lines.all().select_related("service"):
        _render_line(pdf, line)

    pdf.ln(4)

    # ------------------------------------------------------------------
    # Totals footer.
    # ------------------------------------------------------------------
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(140, 6, _safe_pdf_text("Subtotal"), align="R")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(
        0, 6, _safe_pdf_text(_fmt_money(proposal.subtotal_amount)),
        align="R", new_x="LMARGIN", new_y="NEXT",
    )

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(140, 6, _safe_pdf_text("VAT"), align="R")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(
        0, 6, _safe_pdf_text(_fmt_money(proposal.vat_amount)),
        align="R", new_x="LMARGIN", new_y="NEXT",
    )

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(140, 7, _safe_pdf_text("Total"), align="R")
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
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(
            0,
            6,
            _safe_pdf_text("Override reason:"),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5, _safe_pdf_text(proposal.override_reason))

        override_actor_email = ""
        # Use override_by_id presence to avoid an unconditional FK fetch.
        if proposal.override_by_id:
            try:
                override_actor_email = proposal.override_by.email or ""
            except Exception:  # noqa: BLE001 — defensive only
                override_actor_email = ""
        if override_actor_email:
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(35, 6, _safe_pdf_text("Override by:"))
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(
                0,
                6,
                _safe_pdf_text(override_actor_email),
                new_x="LMARGIN",
                new_y="NEXT",
            )

    output = pdf.output(dest="S")
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
    privacy contract.
    """
    label = _line_label(line)
    qty_label = f"{line.quantity:.2f} x {line.unit_type}"
    pdf.cell(60, 6, _safe_pdf_text(label), border=1)
    pdf.cell(22, 6, _safe_pdf_text(qty_label), border=1)
    pdf.cell(25, 6, _safe_pdf_text(_fmt_money(line.unit_price)), border=1)
    pdf.cell(15, 6, _safe_pdf_text(f"{line.vat_pct:.2f}"), border=1)
    pdf.cell(22, 6, _safe_pdf_text(_fmt_money(line.line_subtotal)), border=1)
    pdf.cell(20, 6, _safe_pdf_text(_fmt_money(line.line_vat)), border=1)
    pdf.cell(25, 6, _safe_pdf_text(_fmt_money(line.line_total)), border=1)
    pdf.ln(6)

    explanation = (line.customer_explanation or "").strip()
    if explanation:
        # Indented secondary row for the customer-visible explanation.
        # The internal_note field is never referenced.
        pdf.set_font("Helvetica", "I", 8)
        # Leave a small left indent so the explanation visually attaches
        # to its parent row.
        pdf.cell(5, 5, "")
        pdf.multi_cell(0, 5, _safe_pdf_text(explanation))
        pdf.set_font("Helvetica", "", 9)
