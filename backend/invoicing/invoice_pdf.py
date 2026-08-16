"""
Invoicing — the invoice PDF renderer, and (Sprint 180 §1) the FREEZE.

Pure rendering layer (mirrors `extra_work.proposal_pdf.render_proposal_pdf`).
The HTTP wrappers live in `invoicing.views`.

    render_invoice_pdf(invoice)  -> bytes          (always renders fresh)
    freeze_invoice_pdf(invoice)  -> Invoice        (render once, store, digest)
    invoice_pdf_bytes(invoice)   -> bytes          (what the endpoints serve)

LOCKED decisions this renders (see docs/product/sot-addendum-b-invoicing.md):

  * DUTCH-ONLY, like the proposal PDF + the emails. Static labels/status and
    money/quantity use Dutch formatting ("€ 1.234,56", comma decimals). We
    REUSE the shared brand assets (`config.pdf_branding`: logo, embedded
    DejaVu font with the real euro sign, accent rule) and the canonical
    proposal-PDF formatters (`_fmt_money` / `_nl_number` / `_safe_pdf_text`)
    so the two families cannot drift. The annex reuses `_fitted_cell` from
    the same source for its own table.
  * PAGE 1 IS THE SUMMARY, PAGE 2 ONWARD IS THE SPECIFICATION (Sprint 180
    §2). Page 1: branded header; number or "CONCEPT" while unnumbered;
    customer + optional building; dates; period; the optional free-text fee;
    ONE summary line — "3 meerwerken - Zie bijlage voor specificatie" — and
    the totals. Page 2+: the annex, grouped building -> department -> work
    type, over as many pages as it takes. That is the document the owner's
    father assembles by hand today; see `invoicing.annex`.

    This REPLACED a fixed second page carrying a flat per-line table with
    quantity / unit price / VAT% columns. The owner's own invoices do not
    carry those: the specification lists what was done, when, and the amount
    excluding VAT, and the VAT is summarised once on page 1. Keeping both
    would have meant printing the same money twice in two different shapes.
  * DRAFT marker: while status==DRAFT a "CONCEPT" marker is shown on every
    page (header band) + in the number slot + a prominent page-1 banner, so
    a printed draft is unmistakable. ISSUED/SENT show the real number and no
    marker.
  * A reversal (is_reversal=True) is titled "Creditnota" and its amounts are
    already negative in the data — they simply render negative. Its annex
    references the original invoice number rather than re-listing work,
    because `reverse_invoice` mirrors lines with `extra_work=None` and there
    is no work there to list (Sprint 180 §1a).

**THE FREEZE.** Until Sprint 180 this module was called on every download
and the document was re-rendered from live data each time, so a SENT
invoice could render differently later if anything behind it changed. An
invoice is an artefact, not a view. `freeze_invoice_pdf` renders once,
stores the bytes on `Invoice.pdf_file`, and records their SHA-256 and page
count; `send_invoice` calls it inside its own atomic block. From then on
`invoice_pdf_bytes` serves the stored bytes and never re-renders. A DRAFT
(or ISSUED-but-unsent) invoice keeps rendering fresh — it is still changing,
and its preview is taken from it.
"""
from __future__ import annotations

import hashlib

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from fpdf import FPDF

from config.pdf_branding import (
    FONT_FAMILY,
    LOGO_WIDTH_MM,
    accent_rgb_for,
    accent_rule,
    accent_tint_for,
    draw_logo,
    register_fonts,
)

# REUSE the canonical Dutch formatters + width-safe cell from the proposal
# PDF so money/label rendering cannot drift between the two PDF families.
from extra_work.proposal_pdf import (
    _fmt_money,
    _nl_number,
    _safe_pdf_text,
)

from .annex import build_annex, draw_annex, summary_line
from .models import Invoice

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


def _group_label(invoice: Invoice) -> str:
    """Sprint 132 — "<department> - <work type>" derived at RENDER time
    from the FKs (never stored pre-joined). Handles all four shapes: both
    set, either alone, or "" when neither is set (the caller skips the row
    entirely rather than print a stray "-" or an empty value)."""
    parts = [
        invoice.department.name if invoice.department_id else None,
        invoice.work_type.name if invoice.work_type_id else None,
    ]
    return " - ".join(p for p in parts if p)


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


def _address_lines(customer) -> list[tuple[str, str]]:
    """Sprint 185 §1 — the customer's billing address, as printable rows.

    Dutch convention: street on one line, then "1234 AB City", then the
    country only when one is recorded (a domestic invoice does not carry
    "Nederland", and printing it would make every normal invoice look
    like an export).

    Returns an empty list when there is nothing to print, so the caller
    renders NOTHING rather than an empty labelled row — which is what a
    reader would take for a broken template.

    A list of (label, value) rather than a formatted block because the
    header and the summary page draw their rows differently, and one
    formatter that returned pre-joined text would force one of them to
    take the other's layout.
    """
    if customer is None:
        return []
    street = (getattr(customer, "address", "") or "").strip()
    postal = (getattr(customer, "postal_code", "") or "").strip()
    city = (getattr(customer, "city", "") or "").strip()
    country = (getattr(customer, "country", "") or "").strip()

    rows: list[tuple[str, str]] = []
    if street:
        rows.append(("Adres:", street))
    locality = " ".join(part for part in (postal, city) if part)
    if locality:
        # Labelled only when it is the FIRST line, so a two-line address
        # reads as an address block rather than as two unrelated facts.
        rows.append(("" if rows else "Adres:", locality))
    if country:
        rows.append(("" if rows else "Adres:", country))
    return rows


def _draw_header(
    pdf, *, company, brand_accent, company_name, doc_title, number_text, status_text
):
    """Branded header: logo top-left, provider block, doc title + number
    right-aligned, accent rule underneath. Company-aware — the platform
    (OSIUS) logo/pink only for the platform company; any other company uses
    its own logo (or a name-only header) + the neutral accent. Mirrors
    proposal_pdf's header."""
    logo_bottom = draw_logo(pdf, company, y=10.0)

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
    pdf.set_text_color(*brand_accent)
    pdf.cell(80, 8, _safe_pdf_text(number_text), align="R")
    pdf.set_text_color(0, 0, 0)
    pdf.set_xy(meta_x, 18.5)
    pdf.set_font(FONT_FAMILY, "", 9.5)
    pdf.cell(80, 5, _safe_pdf_text(status_text), align="R")

    rule_y = max(logo_bottom, 25.0) + 3.0
    accent_rule(pdf, rule_y, brand_accent)
    pdf.set_y(rule_y + 5.0)


_STATUS_LABELS_NL = {
    "DRAFT": "Concept",
    "ISSUED": "Uitgegeven",
    "SENT": "Verzonden",
}


def _vat_display(invoice: Invoice, lines) -> str:
    """"21%" when every line carries the same VAT rate, else the AMOUNT.

    The owner's page-1 line reads "157,40 + 21% = 190,45". That shorthand is
    only truthful when there is one rate on the document; a mixed-rate
    invoice would be misdescribed by any single percentage, so it falls back
    to stating the VAT figure itself rather than picking one of the rates.

    An invoice with no lines at all (fee-only) has no rate to quote either.
    """
    rates = {line.vat_pct for line in lines}
    if len(rates) == 1:
        rate = rates.pop()
        return f"{_nl_number(rate, 0 if rate == rate.to_integral_value() else 2)}%"
    return f"{_fmt_money(invoice.vat_amount)} BTW"


def _render(invoice: Invoice) -> tuple[bytes, int]:
    """The renderer proper — bytes AND the page count.

    The page count comes from fpdf2's own page list rather than from re-
    parsing the output with pypdf: the renderer already knows, and a second
    parse is both slower and a second thing that can disagree.
    """
    company = invoice.company
    company_name = getattr(company, "name", "") or ""
    # Company-aware branding — OSIUS pink/logo only for the platform company;
    # any other company uses its own logo (or a name-only header) + neutral.
    brand_accent = accent_rgb_for(company)
    brand_tint = accent_tint_for(company)
    customer_name = getattr(invoice.customer, "name", "") or ""
    building_name = (
        getattr(invoice.building, "name", "") if invoice.building_id else ""
    )
    is_draft = invoice.status == Invoice.Status.DRAFT

    doc_title = "Creditnota" if invoice.is_reversal else "Factuur"
    # Number-at-send: the number slot shows the real number ONLY once one
    # exists (SENT, or a numbered reversal). A numberless invoice — DRAFT OR
    # ISSUED-but-unsent — shows the CONCEPT marker; it must never render
    # "None"/blank. The per-page CONCEPT banner below stays tied to DRAFT so an
    # ISSUED invoice is still distinguishable (its status line reads
    # "Uitgegeven").
    number_text = invoice.number or "CONCEPT"
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
        company=company,
        brand_accent=brand_accent,
        company_name=company_name,
        doc_title=doc_title + " extra werk",
        number_text=number_text,
        status_text=status_text,
    )

    # Prominent draft banner.
    if is_draft:
        pdf.set_fill_color(*brand_tint)
        pdf.set_text_color(*brand_accent)
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
    # Sprint 185 §1 — the BILLING ADDRESS, directly under the customer it
    # belongs to. The owner's decision: an invoice always carries the
    # CUSTOMER's address, whether the invoice is addressed to the
    # building or to the customer, because a building's address is the
    # WORK SITE and not the billing address.
    #
    # Rows print only when they hold something. A blank "Adres:" line
    # reads as a rendering fault; an absent address should simply be
    # absent.
    #
    # NOTE — the refuse-at-SEND guard the sprint asked for is NOT here and
    # is not anywhere yet. It belongs in `invoicing/state_machine.py`,
    # which another agent owns this round, so this branch supplies the
    # predicate (`Customer.has_billing_address`) and the screen warning
    # but cannot install the block itself. See the sprint report.
    for label, value in _address_lines(invoice.customer):
        pdf.set_font(FONT_FAMILY, "B", 10)
        pdf.cell(28, 6, _safe_pdf_text(label))
        pdf.set_font(FONT_FAMILY, "", 10)
        pdf.cell(0, 6, _safe_pdf_text(value), new_x="LMARGIN", new_y="NEXT")

    _kv_row(
        "Gebouw:", building_name or "Alle gebouwen",
        "Periode:", period_text,
    )
    # Sprint 132 — only for an invoice generated at PER_BUILDING_
    # DEPARTMENT_WORK_TYPE granularity; the row is skipped entirely
    # (not printed empty) for every other invoice, matching `_group_label`'s
    # "" for the neither-set shape.
    group_label = _group_label(invoice)
    if group_label:
        pdf.set_font(FONT_FAMILY, "B", 10)
        pdf.cell(28, 6, _safe_pdf_text("Afdeling:"))
        pdf.set_font(FONT_FAMILY, "", 10)
        pdf.cell(0, 6, _safe_pdf_text(group_label), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Summary line — Ramazan's overview. Phase 4a: prefer the hand-written
    # `summary_text` when set; otherwise fall back to the auto-composed line.
    pdf.set_font(FONT_FAMILY, "B", 10)
    pdf.cell(0, 6, _safe_pdf_text("Samenvatting:"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FONT_FAMILY, "", 10)
    hand_summary = (invoice.summary_text or "").strip()
    if hand_summary:
        summary_body = hand_summary
    else:
        scope_text = building_name if building_name else "alle gebouwen"
        summary_body = (
            f"Factuur voor {customer_name} ({scope_text}) — periode "
            f"{period_text}. Totaal {_fmt_money(invoice.total_amount)}."
        )
    pdf.multi_cell(
        0,
        5,
        _safe_pdf_text(summary_body),
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

    # Sprint 180 §2 — THE summary line. One line, the count, and the
    # pointer to the annex, exactly as the owner's own page 1 reads:
    #
    #     3 meerwerken - Zie bijlage voor specificatie   157,40 + 21% = 190,45
    #
    # Both halves are composed from the SAME `Annex` the pages below are
    # drawn from, so the count on page 1 cannot drift from the number of
    # rows overleaf.
    annex = build_annex(invoice)
    lines = list(invoice.lines.all())
    pdf.ln(2)
    pdf.set_fill_color(*brand_tint)
    pdf.set_font(FONT_FAMILY, "B", 10)
    pdf.cell(
        95,
        8,
        _safe_pdf_text(summary_line(annex)),
        border=0,
        fill=True,
    )
    pdf.set_font(FONT_FAMILY, "", 10)
    pdf.cell(
        0,
        8,
        _safe_pdf_text(
            f"{_fmt_money(invoice.subtotal_amount)} + "
            f"{_vat_display(invoice, lines)} = "
            f"{_fmt_money(invoice.total_amount)}"
        ),
        border=0,
        align="R",
        fill=True,
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_fill_color(255, 255, 255)

    pdf.ln(2)
    _total_row("Subtotaal", invoice.subtotal_amount, size=10)
    _total_row("BTW", invoice.vat_amount, size=10)
    pdf.set_draw_color(*brand_accent)
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
    # PAGE 2+ — THE SPECIFICATION ANNEX
    # ==================================================================
    # As many pages as the work takes. `invoicing.annex` owns the grouping,
    # the pagination and the repeated headers; the branded header stays here
    # and is handed in as a callable so the annex never imports back into
    # this module.
    # Sprint 185 §1 — the addressee, repeated on every annex page.
    #
    # Before this, page 3 of a specification carried the PROVIDER's brand
    # and the invoice number and nothing at all about who it was billed
    # to. A page that detaches from its bundle — and in an accounts
    # department they do — could not be put back on the right pile. One
    # compact line fixes that: the customer, and the locality of the
    # address the invoice is addressed to.
    #
    # Deliberately one line, not the full block. The full address belongs
    # once, on the summary page, where the document is addressed; repeating
    # four lines on every page would turn a header into a letterhead.
    addressee_rows = _address_lines(invoice.customer)
    addressee_locality = next(
        (value for label, value in addressee_rows if label == ""), ""
    ) or (addressee_rows[0][1] if addressee_rows else "")

    def _annex_page_header(target_pdf, subtitle: str) -> None:
        _draw_header(
            target_pdf,
            company=company,
            brand_accent=brand_accent,
            company_name=company_name,
            doc_title=f"{doc_title} — {subtitle}",
            number_text=number_text,
            status_text=status_text,
        )
        target_pdf.set_font(FONT_FAMILY, "", 9)
        target_pdf.set_text_color(90, 90, 90)
        line = customer_name
        if addressee_locality:
            line = f"{line} — {addressee_locality}"
        target_pdf.cell(
            0, 5, _safe_pdf_text(line), new_x="LMARGIN", new_y="NEXT"
        )
        target_pdf.set_text_color(0, 0, 0)
        target_pdf.ln(1)

    draw_annex(
        pdf,
        invoice,
        annex,
        brand_accent=brand_accent,
        brand_tint=brand_tint,
        draw_page_header=_annex_page_header,
    )

    return bytes(pdf.output()), len(pdf.pages)


def render_invoice_pdf(invoice: Invoice) -> bytes:
    """Render `invoice` fresh. Read-only — no mutations, no stored bytes.

    Kept as the module's public rendering entry point (several callers and
    tests speak it). Endpoints should call `invoice_pdf_bytes` instead, which
    serves the FROZEN document for a sent invoice.
    """
    return _render(invoice)[0]


# ---------------------------------------------------------------------------
# Sprint 180 §1 — the freeze
# ---------------------------------------------------------------------------


def freeze_invoice_pdf(invoice: Invoice) -> Invoice:
    """Render `invoice` ONCE, store the bytes, and record their digest.

    Idempotent by design: an invoice that already has `pdf_file` is returned
    untouched. That is not an optimisation — it is the whole point. The
    frozen document is the artefact; re-rendering it would defeat the freeze,
    and a caller that asks twice must get the same answer both times.

    Assumes the caller holds the row (it is called from inside
    `send_invoice`'s atomic block, and from `invoice_pdf_bytes` under its own
    `select_for_update`). Saves with `update_fields` so it touches only what
    it wrote.
    """
    if invoice.pdf_file:
        return invoice
    data, page_count = _render(invoice)
    invoice.pdf_sha256 = hashlib.sha256(data).hexdigest()
    invoice.pdf_page_count = page_count
    invoice.pdf_frozen_at = timezone.now()
    # save=False, then ONE save() below: `FieldFile.save()` would issue its
    # own UPDATE of just `pdf_file`, so the four fields would land in two
    # statements and a crash between them could leave a stored file with no
    # digest beside it.
    invoice.pdf_file.save(
        f"factuur-{invoice.number or invoice.pk}.pdf",
        ContentFile(data),
        save=False,
    )
    invoice.save(
        update_fields=[
            "pdf_file",
            "pdf_sha256",
            "pdf_page_count",
            "pdf_frozen_at",
            "updated_at",
        ]
    )
    return invoice


def invoice_pdf_bytes(invoice: Invoice) -> bytes:
    """What the endpoints serve.

    * DRAFT / ISSUED-but-unsent -> rendered FRESH every time. The document is
      still changing and the preview is taken from it.
    * SENT with a frozen file -> the stored bytes, verbatim. Never re-rendered.
    * SENT with NO frozen file -> frozen NOW and then served (Sprint 180 §1b).
      That is every invoice sent before the field existed. The lazy path is
      row-locked and re-checks under the lock, so two concurrent downloads
      cannot each write a file; `manage.py freeze_invoice_pdfs` exists to do
      the same thing deliberately and in bulk instead of by accident of who
      happens to open which invoice first.
    """
    if invoice.status != Invoice.Status.SENT:
        return render_invoice_pdf(invoice)
    if invoice.pdf_file:
        with invoice.pdf_file.open("rb") as fh:
            return fh.read()
    with transaction.atomic():
        locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
        # Re-checked under the lock: another request may have frozen it
        # between our first read and this one.
        if not locked.pdf_file:
            freeze_invoice_pdf(locked)
    locked.refresh_from_db(fields=["pdf_file"])
    with locked.pdf_file.open("rb") as fh:
        return fh.read()
