"""
Invoicing — Sprint 180 §2: the SPECIFICATION annex.

The pages the owner's father assembles by hand today. His invoice's page 1
is a summary — one line, "3 meerwerken - Zie bijlage voor specificatie",
with the total — and from page 2 onward the per-building extra-works detail
is appended, page after page. An invoice can run to eight pages. Until this
sprint a human stapled that together.

    Page 1   INVOICE - summary
             "3 meerwerken - Zie bijlage voor specificatie"  157,40 + 21% = 190,45
    Page 2+  SPECIFICATIE, grouped building -> department -> work type
             #  Titel                              Week  Uitgevoerd    Excl. BTW
             1  Louis + Atrium // B.3               27   03-07-2026       110,18
             2  The Sheryl                          28   07-07-2026        31,48

**Why this is its own module and not more of `invoice_pdf.py`.** The two
halves answer different questions and are tested differently: the summary is
one page of invoice-level facts, the annex is an arbitrary number of pages of
grouped LINE facts with its own pagination. Splitting them also lets the
grouping be tested as data — `build_annex(invoice)` returns plain dataclasses,
no PDF involved — which is the half where the bugs live.

**Why not `reports/exports.py`.** That module builds a different document
family with different VAT treatment, different branding, different gating and
a different data source. Sharing it would couple an invoicing change to a
reporting one.

**No new PDF library.** Everything is drawn with the `fpdf2` instance the
invoice renderer already owns, through the shared brand helpers in
`config.pdf_branding` and the canonical Dutch formatters in
`extra_work.proposal_pdf`. Both are read-only to this module.

**Privacy.** The annex reads NOTHING from an Extra Work request except its
building, department and work-type NAMES — all three of which the customer
invoice serializer already exposes, and all three of which are the customer's
own taxonomy. The row's title is `InvoiceLine.description`, which is already
rendered to customers on the existing detail page. No EW description, no
internal note, no cost price, no margin is read here, and the per-page privacy
tests assert their absence on EVERY page rather than only on page 1 — an annex
that leaks an internal note onto page 4 is the same failure as leaking it on
page 1.
"""
from __future__ import annotations

import dataclasses
from decimal import Decimal

from config.pdf_branding import FONT_FAMILY
from extra_work.proposal_pdf import _fitted_cell, _fmt_money, _safe_pdf_text

# Column widths (mm). Sum = 190 = the usable width of A4 at fpdf2's default
# 10mm side margins. Width-fitted cells mean no realistic value overflows.
_COL_INDEX = 10.0
_COL_TITLE = 92.0
_COL_WEEK = 16.0
_COL_DONE = 30.0
_COL_AMOUNT = 42.0

_ROW_H = 6.0
_TABLE_BORDER_RGB = (208, 200, 206)

#: Sorts an unset label after every real one instead of before it (an empty
#: string sorts first). "Not filled in" belongs at the bottom of a list.
_LAST = "￿"


@dataclasses.dataclass(frozen=True)
class AnnexRow:
    """One extra work on the specification."""

    #: 1-based and CONTINUOUS across the whole annex, not restarted per
    #: group — the operator reads "item 7 of 12", and a number that restarts
    #: makes two different rows both "1".
    index: int
    title: str
    #: ISO week of the completion date, or "-" when the work has no date.
    week: str
    completed: str
    #: Excluding VAT. Taken from the INVOICE LINE, never re-derived from the
    #: extra work: the invoice is the source of truth for its own money.
    subtotal: Decimal


@dataclasses.dataclass(frozen=True)
class AnnexGroup:
    building: str
    department: str
    work_type: str
    rows: tuple[AnnexRow, ...]

    @property
    def subtotal(self) -> Decimal:
        return sum((r.subtotal for r in self.rows), Decimal("0.00"))

    def heading(self) -> str:
        """"B1 Amsterdam" / "B1 Amsterdam - Schoonmaak" / "... - Ramen".

        Only the parts that exist. A heading that prints "B1 - - " for an
        untagged group tells the reader nothing and looks like a bug.
        """
        return " - ".join(
            part for part in (self.building, self.department, self.work_type) if part
        )


@dataclasses.dataclass(frozen=True)
class Annex:
    groups: tuple[AnnexGroup, ...]
    #: Set ONLY for a credit note. `reverse_invoice` mirrors every line with
    #: `extra_work=None`, so a credit note HAS no extra works to list — its
    #: annex references the original invoice number instead of inventing line
    #: data that is not there. (Sprint 180 §1a, a decision, not an omission.)
    reverses_number: str | None = None

    @property
    def row_count(self) -> int:
        return sum(len(g.rows) for g in self.groups)

    @property
    def subtotal(self) -> Decimal:
        return sum((g.subtotal for g in self.groups), Decimal("0.00"))


def _week_of(value) -> str:
    if value is None:
        return "-"
    try:
        return str(value.isocalendar()[1])
    except (AttributeError, ValueError):
        return "-"


def _nl_date(value) -> str:
    """"03-07-2026" — the shape on the owner's own invoices."""
    if value is None:
        return "-"
    try:
        return f"{value.day:02d}-{value.month:02d}-{value.year}"
    except AttributeError:
        return str(value)


def build_annex(invoice) -> Annex:
    """Group `invoice`'s lines for the specification pages.

    Pure data — no PDF, no request, no I/O beyond the queryset. The grouping
    key is BUILDING -> DEPARTMENT -> WORK TYPE, read from each line's source
    extra work; a hand-added line (no extra work) inherits the invoice's own
    building and carries no labels, which is exactly what it is: money on
    this invoice that is not one of the claimed extra works.

    A credit note returns an EMPTY annex carrying `reverses_number` — see
    `Annex.reverses_number`.
    """
    if invoice.is_reversal:
        original = invoice.reverses
        return Annex(
            groups=(),
            reverses_number=(original.number if original is not None else None),
        )

    lines = list(
        invoice.lines.select_related(
            "extra_work",
            "extra_work__building",
            "extra_work__department",
            "extra_work__work_type",
        ).order_by("ordering", "id")
    )

    invoice_building = (
        invoice.building.name if invoice.building_id else ""
    )

    buckets: dict[tuple[str, str, str], list] = {}
    for line in lines:
        ew = line.extra_work
        if ew is not None:
            building = ew.building.name if ew.building_id else invoice_building
            department = ew.department.name if ew.department_id else ""
            work_type = ew.work_type.name if ew.work_type_id else ""
        else:
            building, department, work_type = invoice_building, "", ""
        buckets.setdefault((building, department, work_type), []).append(line)

    # Sort so an UNSET label lands after every named one within its level.
    ordered_keys = sorted(
        buckets,
        key=lambda k: tuple(part or _LAST for part in k),
    )

    groups: list[AnnexGroup] = []
    counter = 0
    for key in ordered_keys:
        rows = []
        for line in buckets[key]:
            counter += 1
            rows.append(
                AnnexRow(
                    index=counter,
                    title=line.description or "-",
                    week=_week_of(line.performed_on),
                    completed=_nl_date(line.performed_on),
                    subtotal=line.line_subtotal,
                )
            )
        groups.append(
            AnnexGroup(
                building=key[0],
                department=key[1],
                work_type=key[2],
                rows=tuple(rows),
            )
        )
    return Annex(groups=tuple(groups))


def summary_line(annex: Annex) -> str:
    """Page 1's one line — the whole point of the summary page.

    "3 meerwerken - Zie bijlage voor specificatie", or the credit note's
    reference to the invoice it credits. Composed here rather than in the
    renderer so page 1 and the annex cannot disagree about how many items
    there are: both read the same `Annex`.
    """
    if annex.reverses_number is not None:
        return (
            f"Creditering van factuur {annex.reverses_number} - "
            "Zie bijlage"
        )
    count = annex.row_count
    if count == 0:
        return "Geen meerwerken op deze factuur"
    noun = "meerwerk" if count == 1 else "meerwerken"
    return f"{count} {noun} - Zie bijlage voor specificatie"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _draw_column_headers(pdf, *, brand_accent, brand_tint) -> None:
    pdf.set_draw_color(*_TABLE_BORDER_RGB)
    pdf.set_font(FONT_FAMILY, "B", 8.0)
    pdf.set_fill_color(*brand_tint)
    pdf.set_text_color(*brand_accent)
    for label, width, align in (
        ("#", _COL_INDEX, "R"),
        ("Titel", _COL_TITLE, "L"),
        ("Week", _COL_WEEK, "R"),
        ("Uitgevoerd", _COL_DONE, "L"),
        ("Excl. BTW", _COL_AMOUNT, "R"),
    ):
        _fitted_cell(
            pdf, width, 7, label, align=align, border=1, fill=True, base_size=8.0
        )
    pdf.ln(7)
    pdf.set_text_color(0, 0, 0)


def draw_annex(
    pdf,
    invoice,
    annex: Annex,
    *,
    brand_accent,
    brand_tint,
    draw_page_header,
) -> None:
    """Append the specification pages to `pdf`.

    `draw_page_header(pdf, subtitle)` is passed IN rather than imported, so
    this module never has to import back into `invoice_pdf` — the branded
    header stays owned by the renderer and there is no import cycle.

    **Every appended page repeats the branded header AND the column
    headers.** A page that arrives on its own — printed, forwarded, dropped
    on a desk — must still say what it is and what its columns mean.

    Pagination is MANUAL: auto page break is switched off for the duration
    and restored afterwards, so a row can never be split across a boundary
    and a group heading can never be orphaned at the foot of a page with its
    first row overleaf. That is worth the explicit arithmetic; the automatic
    version silently produces both.
    """
    previous_auto = pdf.auto_page_break
    previous_margin = pdf.b_margin
    pdf.set_auto_page_break(auto=False, margin=previous_margin)
    try:
        _draw_annex_body(
            pdf,
            invoice,
            annex,
            brand_accent=brand_accent,
            brand_tint=brand_tint,
            draw_page_header=draw_page_header,
        )
    finally:
        pdf.set_auto_page_break(auto=previous_auto, margin=previous_margin)


def _draw_annex_body(
    pdf, invoice, annex, *, brand_accent, brand_tint, draw_page_header
) -> None:
    # The last y a row may START at. `b_margin` is fpdf2's bottom margin;
    # the page footer lives inside it.
    bottom = pdf.h - pdf.b_margin - _ROW_H

    def new_page() -> None:
        pdf.add_page()
        draw_page_header(pdf, "specificatie")
        pdf.set_font(FONT_FAMILY, "B", 11)
        pdf.cell(
            0,
            7,
            _safe_pdf_text("Bijlage - specificatie meerwerk"),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(1)
        _draw_column_headers(pdf, brand_accent=brand_accent, brand_tint=brand_tint)

    new_page()

    # A credit note has no work to list — see `Annex.reverses_number`.
    if annex.reverses_number is not None or not annex.groups:
        pdf.set_font(FONT_FAMILY, "", 9.5)
        if annex.reverses_number is not None:
            body = (
                f"Deze creditnota crediteert factuur "
                f"{annex.reverses_number}. De specificatie van het "
                f"uitgevoerde werk staat bij die factuur; deze nota is de "
                f"tegenboeking en herhaalt die regels niet."
            )
        else:
            body = "Er zijn geen meerwerkregels op deze factuur."
        pdf.multi_cell(0, 5, _safe_pdf_text(body), new_x="LMARGIN", new_y="NEXT")
        return

    for group in annex.groups:
        heading = group.heading()
        # Heading + one row + the group's own subtotal must fit, or the
        # heading is orphaned.
        if heading and pdf.get_y() + (_ROW_H * 3) > bottom:
            new_page()
        if heading:
            pdf.ln(2)
            pdf.set_font(FONT_FAMILY, "B", 9.5)
            pdf.set_text_color(*brand_accent)
            pdf.cell(
                0,
                6,
                _safe_pdf_text(heading),
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.set_text_color(0, 0, 0)

        pdf.set_font(FONT_FAMILY, "", 8.5)
        pdf.set_draw_color(*_TABLE_BORDER_RGB)
        for row in group.rows:
            if pdf.get_y() > bottom:
                new_page()
                # The continuation page repeats WHOSE rows these are, or the
                # reader has a table of numbers belonging to nothing.
                if heading:
                    pdf.set_font(FONT_FAMILY, "B", 9.5)
                    pdf.set_text_color(*brand_accent)
                    pdf.cell(
                        0,
                        6,
                        _safe_pdf_text(f"{heading} (vervolg)"),
                        new_x="LMARGIN",
                        new_y="NEXT",
                    )
                    pdf.set_text_color(0, 0, 0)
                pdf.set_font(FONT_FAMILY, "", 8.5)
                pdf.set_draw_color(*_TABLE_BORDER_RGB)
            _fitted_cell(
                pdf, _COL_INDEX, _ROW_H, str(row.index), align="R", border=1,
                base_size=8.5,
            )
            _fitted_cell(
                pdf, _COL_TITLE, _ROW_H, row.title, align="L", border=1,
                base_size=8.5,
            )
            _fitted_cell(
                pdf, _COL_WEEK, _ROW_H, row.week, align="R", border=1,
                base_size=8.5,
            )
            _fitted_cell(
                pdf, _COL_DONE, _ROW_H, row.completed, align="L", border=1,
                base_size=8.5,
            )
            _fitted_cell(
                pdf, _COL_AMOUNT, _ROW_H, _fmt_money(row.subtotal), align="R",
                border=1, base_size=8.5,
            )
            pdf.ln(_ROW_H)

        # Per-group subtotal — the number the operator checks a building's
        # pages against.
        if pdf.get_y() > bottom:
            new_page()
        pdf.set_font(FONT_FAMILY, "B", 8.5)
        pdf.cell(
            _COL_INDEX + _COL_TITLE + _COL_WEEK + _COL_DONE,
            _ROW_H,
            _safe_pdf_text("Subtotaal"),
            align="R",
        )
        pdf.cell(
            _COL_AMOUNT,
            _ROW_H,
            _safe_pdf_text(_fmt_money(group.subtotal)),
            align="R",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.set_draw_color(0, 0, 0)

    # Annex grand total. Deliberately labelled "specificatie" and NOT
    # "factuur": when the invoice carries an optional fee, this figure is the
    # work only, and the invoice subtotal on page 1 is this plus that fee.
    # Calling both "Subtotaal" would make two different numbers look like a
    # contradiction.
    if pdf.get_y() + _ROW_H * 2 > bottom:
        new_page()
    pdf.ln(2)
    pdf.set_font(FONT_FAMILY, "B", 10)
    pdf.cell(
        _COL_INDEX + _COL_TITLE + _COL_WEEK + _COL_DONE,
        7,
        _safe_pdf_text("Totaal specificatie (excl. BTW)"),
        align="R",
    )
    pdf.cell(
        _COL_AMOUNT,
        7,
        _safe_pdf_text(_fmt_money(annex.subtotal)),
        align="R",
        new_x="LMARGIN",
        new_y="NEXT",
    )
