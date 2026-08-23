"""
Sprint 182 §2 — the downloadable PREVIEW document.

SPRINT 183 §5 — WHY IT IS STILL A SECOND LAYOUT
------------------------------------------------
The brief asked to bring this closer to the real invoice PDF or explain
in one line why not. The line:

    `invoice_pdf._render` and `annex.build_annex` both take a SAVED
    invoice and query `invoice.lines`, so rendering a plan through them
    needs either a persisted draft — exactly what §2 forbids — or a
    rewrite of the annex builder every real invoice depends on, which is
    a bigger and riskier change than a preview justifies.

What WAS brought closer, because it costs nothing and is what an
operator actually compares holding the two side by side: the money
formatting (`_fmt_money` mirrors the invoice PDF's Dutch convention),
the branding (the same `config.pdf_branding` helpers, so logo and accent
match), and the row order (the plan is ordered exactly as generation
creates the invoices). What still differs is page furniture — the header
block, table chrome, and the two-page annex structure.

The residual risk is precise: figures cannot drift, because both
documents' numbers come from `preview.plan_invoices`. Only presentation
can, and a preview that looks plainer than the invoice is the safe
direction for that to fail in.

WHY THIS IS NOT `invoice_pdf._render`
-------------------------------------
The real invoice renderer takes a SAVED `Invoice`: it calls
`build_annex(invoice)`, which queries `invoice.lines`. A preview has no
invoice and no lines — nothing is stored, deliberately — so reusing it
would mean either persisting a draft (the exact thing §2 forbids) or
restructuring the annex builder to work on unsaved objects, which is a
change to the document every real invoice is rendered from and not
something to do as a side effect of adding a preview.

So this is a second, deliberately plain layout. What that does and does
not risk is worth being precise about:

  * The MONEY cannot drift. Every figure here comes from the same
    `preview.plan_invoices` the endpoint and `generate_draft_invoices`
    use. There is one calculation, and this file does not do arithmetic
    of its own beyond summing what the plan already computed.
  * The PRESENTATION can drift — this page will not track changes to the
    invoice PDF's layout. That is the accepted trade, and it is the safe
    half: a preview that looks plainer than the real invoice is honest,
    while a preview whose NUMBERS differed would be a document you have
    to argue with.

It reuses the shared branding helpers (`config.pdf_branding`) so the
provider's logo and accent are right, which is the part a reader uses to
tell whose document they are holding.

WHAT IS STAMPED
---------------
Three layers on EVERY page, so no crop or screenshot of any page can
pass for an invoice (W17 — the owner's spec: the preview is something
you look at in the app, and nothing else):

  * a large diagonal VOORBEELD watermark behind the content;
  * a banner across the top: CONCEPT / VOORBEELD — GEEN FACTUUR;
  * the footer: PREVIEW, no invoice number, plus the moment it was
    computed.

Page 1 additionally carries the full disclaimer block above the
numbers. And no number anywhere: `PlannedInvoice` has no number to
render, so there is nothing here that could accidentally print one.
Numbering happens at Send and must stay gapless.
"""
from __future__ import annotations

from decimal import Decimal

from fpdf import FPDF

from config.pdf_branding import (
    FONT_FAMILY,
    accent_rgb_for,
    accent_tint_for,
    draw_logo,
    register_fonts,
)


def _fmt_money(value) -> str:
    """Dutch money formatting: 1.234,56. Mirrors the invoice PDF's own
    convention so the two documents read the same way."""
    value = value or Decimal("0.00")
    whole = f"{value:,.2f}"
    return whole.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _safe(text) -> str:
    """fpdf2 with a TTF handles unicode, but a stray None must not render
    as the string "None" on a financial document."""
    return "" if text is None else str(text)


class _PreviewPDF(FPDF):
    """Stamps every page as a preview, three ways.

    Sprint 182 put the stamp in the footer INSTEAD of a diagonal
    watermark, reasoning that a watermark behind the numbers makes them
    harder to read. W17 re-decided this with the owner's new
    requirement in hand: it must be IMPOSSIBLE to mistake a screenshot
    of any part of this document for an invoice, and a footer is
    exactly what a screenshot crops off. So both, plus a top banner:

      * `header` paints a large diagonal VOORBEELD in a light tint
        FIRST, so the content prints over it — the numbers stay black
        on white and readable, the way a bank's own statement
        watermarks do it;
      * `header` then draws a solid banner across the top of every
        page: CONCEPT / VOORBEELD — GEEN FACTUUR;
      * `footer` keeps the PREVIEW line and the computed-at moment.
    """

    computed_at_label = ""
    accent = (0, 0, 0)
    tint = (240, 240, 240)

    #: The watermark word. One word, as large as the diagonal allows —
    #: "CONCEPT / VOORBEELD" set this large would not fit, so the
    #: banner carries the full phrase and the watermark carries the
    #: unmissable one.
    _WATERMARK = "VOORBEELD"

    def header(self):
        # 1 — the watermark, before anything else so everything else
        # renders on top of it.
        self.set_font(FONT_FAMILY, "B", 92)
        self.set_text_color(*self.tint)
        width = self.get_string_width(self._WATERMARK)
        center_x, center_y = self.w / 2, self.h / 2
        with self.rotation(45, center_x, center_y):
            self.text(center_x - width / 2, center_y, self._WATERMARK)

        # 2 — the banner. All-caps and filled so it survives a
        # screenshot of just the top of the page.
        self.set_xy(self.l_margin, 8)
        self.set_fill_color(*self.tint)
        self.set_text_color(*self.accent)
        self.set_font(FONT_FAMILY, "B", 12)
        self.cell(
            0,
            9,
            _safe("CONCEPT / VOORBEELD — GEEN FACTUUR"),
            align="C",
            fill=True,
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.set_text_color(0, 0, 0)
        # Body content (also on auto-broken pages) starts below the
        # banner, never under it.
        self.set_y(self.get_y() + 3)

    def footer(self):
        self.set_y(-16)
        self.set_font(FONT_FAMILY, "B", 9)
        self.set_text_color(*self.accent)
        self.cell(
            0,
            5,
            _safe(
                "PREVIEW — geen factuur, geen factuurnummer. "
                f"Berekend op {self.computed_at_label}."
            ),
            align="C",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.set_text_color(120, 120, 120)
        self.set_font(FONT_FAMILY, "", 8)
        self.cell(0, 4, f"Pagina {self.page_no()}", align="C")


def render_preview_pdf(
    *, company, customer, planned, period_year, period_month, computed_at
) -> bytes:
    """The preview document for one customer's planned invoices.

    `planned` is the list of `preview.PlannedInvoice` the endpoint
    rendered — passed in rather than recomputed here, so the document and
    the JSON a caller may have just read cannot disagree even by a
    round-trip's worth of elapsed time.
    """
    accent = accent_rgb_for(company)
    tint = accent_tint_for(company)
    computed_label = computed_at.strftime("%d-%m-%Y %H:%M")

    pdf = _PreviewPDF(unit="mm", format="A4")
    register_fonts(pdf)
    pdf.computed_at_label = computed_label
    pdf.accent = accent
    pdf.tint = tint
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.add_page()

    # W17 — the header banner owns the top of every page now, so the
    # logo sits below it instead of at the old y=10.
    y = draw_logo(pdf, company, y=21.0)
    pdf.set_y(max(y, 37))

    pdf.set_font(FONT_FAMILY, "B", 16)
    pdf.set_text_color(*accent)
    pdf.cell(0, 9, _safe("Factuurvoorbeeld"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)

    pdf.set_font(FONT_FAMILY, "", 10)
    pdf.cell(0, 5, _safe(getattr(customer, "name", "")), new_x="LMARGIN",
             new_y="NEXT")
    pdf.cell(
        0,
        5,
        _safe(f"Periode: {period_month:02d}-{period_year}"),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(2)

    # The disclaimer sits ABOVE the numbers, not in small print below
    # them: a reader who only looks at the top of the page must still
    # come away knowing this is not an invoice. W17 — spelled out to
    # the owner's full spec: concept only, computed-moment coverage,
    # not an invoice, no legal number, cannot replace an invoice.
    pdf.set_fill_color(*tint)
    pdf.set_text_color(*accent)
    pdf.set_font(FONT_FAMILY, "B", 10)
    pdf.multi_cell(
        0,
        6,
        _safe(
            "Dit is uitsluitend een concept (voorbeeld) — geen factuur. "
            "Het toont alleen werk dat gereed was op het rekenmoment: "
            f"{computed_label}. Er is geen wettelijk factuurnummer "
            "toegekend en er wordt niets vastgelegd of bewaard. Dit "
            "document kan een factuur niet vervangen; de werkelijke "
            "factuur kan afwijken."
        ),
        border=0,
        align="L",
        fill=True,
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)

    if not planned:
        pdf.set_font(FONT_FAMILY, "", 10)
        pdf.cell(
            0,
            6,
            _safe("Geen onafgerekend extra werk in deze periode."),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        return bytes(pdf.output())

    grand_total = Decimal("0.00")
    for plan in planned:
        # `building_name` lives on the plan so this document and the JSON
        # the endpoint returns label the same plan identically.
        addressee = plan.building_name or "Klantniveau"
        pdf.set_font(FONT_FAMILY, "B", 11)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(
            0,
            7,
            _safe(f"Concept: {addressee}"),
            fill=True,
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.set_font(FONT_FAMILY, "", 9)
        for ew in plan.extra_works:
            from .services import _earned_amounts

            # Sprint 185 E §2 — the customer's PART on a shared building,
            # the whole earned amount everywhere else. Same map the JSON
            # preview reads, so the document and the screen agree.
            _sub, _vat, total = (getattr(plan, "amounts", {}) or {}).get(
                ew.id
            ) or _earned_amounts(ew)
            pdf.cell(140, 5, _safe(ew.title)[:70])
            pdf.cell(
                0,
                5,
                _fmt_money(total),
                align="R",
                new_x="LMARGIN",
                new_y="NEXT",
            )
        pdf.set_font(FONT_FAMILY, "B", 9)
        pdf.cell(140, 6, _safe("Subtotaal / BTW / Totaal"))
        pdf.cell(
            0,
            6,
            _safe(
                f"{_fmt_money(plan.subtotal)} / {_fmt_money(plan.vat)} / "
                f"{_fmt_money(plan.total)}"
            ),
            align="R",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(3)
        grand_total += plan.total

    pdf.set_font(FONT_FAMILY, "B", 12)
    pdf.set_text_color(*accent)
    pdf.cell(140, 8, _safe("Totaal van alle concepten"))
    pdf.cell(0, 8, _fmt_money(grand_total), align="R", new_x="LMARGIN",
             new_y="NEXT")

    return bytes(pdf.output())
