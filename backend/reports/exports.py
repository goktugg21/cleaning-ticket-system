"""
CSV + PDF export helpers for the Sprint 5 report dimensions.

Each `build_*_csv` function takes the same payload shape that the JSON
endpoint returned (computed in `dimensions.py`) and emits a `bytes`
buffer ready for an HttpResponse. CSV columns are stable contracts —
the tests in `tests/test_dimensions_export.py` pin them.

PDFs use `fpdf2` (pure Python, ~1MB, no system deps; chosen over
reportlab because reportlab pulls in extra weight the project does
not need for these table-first reports). RF-15 gave them the shared
formal branding (`config.pdf_branding`): Osius logo header, embedded
DejaVu Sans, accent rule, tinted table headers, page footer with the
generation timestamp. Still intentionally table-first:
- A4 portrait
- Branded header, period + scope summary
- Single table with the same logical columns as the CSV
"""
from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Iterable

from fpdf import FPDF

from config.pdf_branding import (
    FONT_FAMILY,
    LOGO_WIDTH_MM,
    NEUTRAL_ACCENT_RGB,
    NEUTRAL_TINT_RGB,
    accent_rule,
    draw_logo,
    register_fonts,
)

# Sprint 131 — the department report is DUTCH-ONLY (the one deliverable the
# owner compares directly against a real reference document), so it reuses
# the canonical Dutch formatters + width-safe cell already proven on the
# invoice/proposal PDFs rather than this module's own English `_new_pdf` /
# `_draw_table` pair used by every other report in this file.
from extra_work.proposal_pdf import _fitted_cell, _fmt_money, _safe_pdf_text


CSV_BOM = "﻿"  # Excel-friendly UTF-8 marker.


def _csv_writer(columns: Iterable[str]) -> "tuple[io.StringIO, csv.DictWriter]":
    buffer = io.StringIO()
    buffer.write(CSV_BOM)
    writer = csv.DictWriter(buffer, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    return buffer, writer


# ---- CSV: tickets-by-type ---------------------------------------------------


TYPE_CSV_COLUMNS = (
    "ticket_type",
    "ticket_type_label",
    "count",
    "period_from",
    "period_to",
)


def build_tickets_by_type_csv(payload: dict) -> bytes:
    buffer, writer = _csv_writer(TYPE_CSV_COLUMNS)
    period_from = payload["from"]
    period_to = payload["to"]
    for bucket in payload["buckets"]:
        writer.writerow(
            {
                "ticket_type": bucket["ticket_type"],
                "ticket_type_label": bucket["ticket_type_label"],
                "count": bucket["count"],
                "period_from": period_from,
                "period_to": period_to,
            }
        )
    return buffer.getvalue().encode("utf-8")


# ---- CSV: tickets-by-origin (Sprint 14A) -----------------------------------


ORIGIN_CSV_COLUMNS = (
    "origin",
    "origin_label",
    "count",
    "period_from",
    "period_to",
)


def build_tickets_by_origin_csv(payload: dict) -> bytes:
    buffer, writer = _csv_writer(ORIGIN_CSV_COLUMNS)
    period_from = payload["from"]
    period_to = payload["to"]
    for bucket in payload["buckets"]:
        writer.writerow(
            {
                "origin": bucket["origin"],
                "origin_label": bucket["origin_label"],
                "count": bucket["count"],
                "period_from": period_from,
                "period_to": period_to,
            }
        )
    return buffer.getvalue().encode("utf-8")


# ---- CSV: extra-work-revenue (Sprint 14A) ----------------------------------


EXTRA_WORK_REVENUE_CSV_COLUMNS = (
    "state",
    "count",
    "subtotal",
    "vat",
    "total",
    "period_from",
    "period_to",
)

# Stable row order — one row per revenue state, always emitted (even at
# count 0) so the CSV shape is fixed regardless of which states have data.
_REVENUE_CSV_STATE_ORDER = ("earned", "in_progress", "quoted_pipeline", "lost")


def build_extra_work_revenue_csv(payload: dict) -> bytes:
    buffer, writer = _csv_writer(EXTRA_WORK_REVENUE_CSV_COLUMNS)
    period_from = payload["from"]
    period_to = payload["to"]
    states = payload["states"]
    for state in _REVENUE_CSV_STATE_ORDER:
        row = states[state]
        writer.writerow(
            {
                "state": state,
                "count": row["count"],
                "subtotal": row["subtotal"],
                "vat": row["vat"],
                "total": row["total"],
                "period_from": period_from,
                "period_to": period_to,
            }
        )
    return buffer.getvalue().encode("utf-8")


# ---- CSV: tickets-by-customer ----------------------------------------------


CUSTOMER_CSV_COLUMNS = (
    "customer_id",
    "customer_name",
    "building_id",
    "building_name",
    "company_id",
    "company_name",
    "count",
    "period_from",
    "period_to",
)


def build_tickets_by_customer_csv(payload: dict) -> bytes:
    buffer, writer = _csv_writer(CUSTOMER_CSV_COLUMNS)
    period_from = payload["from"]
    period_to = payload["to"]
    for bucket in payload["buckets"]:
        writer.writerow(
            {
                "customer_id": bucket["customer_id"],
                "customer_name": bucket["customer_name"],
                "building_id": bucket["building_id"],
                "building_name": bucket["building_name"],
                "company_id": bucket["company_id"],
                "company_name": bucket["company_name"],
                "count": bucket["count"],
                "period_from": period_from,
                "period_to": period_to,
            }
        )
    return buffer.getvalue().encode("utf-8")


# ---- CSV: tickets-by-building ----------------------------------------------


BUILDING_CSV_COLUMNS = (
    "building_id",
    "building_name",
    "company_id",
    "company_name",
    "count",
    "period_from",
    "period_to",
)


def build_tickets_by_building_csv(payload: dict) -> bytes:
    buffer, writer = _csv_writer(BUILDING_CSV_COLUMNS)
    period_from = payload["from"]
    period_to = payload["to"]
    for bucket in payload["buckets"]:
        writer.writerow(
            {
                "building_id": bucket["building_id"],
                "building_name": bucket["building_name"],
                "company_id": bucket["company_id"],
                "company_name": bucket["company_name"],
                "count": bucket["count"],
                "period_from": period_from,
                "period_to": period_to,
            }
        )
    return buffer.getvalue().encode("utf-8")


# ---- CSV: extra-work-revenue-by-building (Sprint 124) ----------------------


REVENUE_BY_BUILDING_CSV_COLUMNS = (
    "building_id",
    "building_name",
    "company_id",
    "company_name",
    "count",
    "subtotal",
    "vat",
    "total",
    "period_from",
    "period_to",
)


def build_extra_work_revenue_by_building_csv(payload: dict) -> bytes:
    buffer, writer = _csv_writer(REVENUE_BY_BUILDING_CSV_COLUMNS)
    period_from = payload["from"]
    period_to = payload["to"]
    for bucket in payload["buckets"]:
        writer.writerow(
            {
                "building_id": bucket["building_id"],
                "building_name": bucket["building_name"],
                "company_id": bucket["company_id"],
                "company_name": bucket["company_name"],
                "count": bucket["count"],
                "subtotal": bucket["subtotal"],
                "vat": bucket["vat"],
                "total": bucket["total"],
                "period_from": period_from,
                "period_to": period_to,
            }
        )
    return buffer.getvalue().encode("utf-8")


# ---- PDF helpers -----------------------------------------------------------


def _scope_summary_lines(scope: dict) -> list:
    """One line per non-null scope/filter so the PDF header reads like
    'Company: Acme · Building: Main' without empty noise."""
    parts = []
    if scope.get("company_name"):
        parts.append(f"Company: {scope['company_name']}")
    if scope.get("building_name"):
        parts.append(f"Building: {scope['building_name']}")
    if scope.get("customer_name"):
        parts.append(f"Customer: {scope['customer_name']}")
    if scope.get("type"):
        parts.append(f"Type: {scope['type']}")
    if scope.get("status"):
        parts.append(f"Status: {scope['status']}")
    return parts or ["Scope: All"]


class _ReportPDF(FPDF):
    """RF-15 — branded report PDF: footer with page number + the
    report's `generated_at` timestamp on every page."""

    generated_on: str = ""

    def footer(self) -> None:  # noqa: D401 — fpdf2 hook
        self.set_y(-12)
        self.set_font(FONT_FAMILY, "", 7.5)
        self.set_text_color(130, 125, 129)
        half = self.epw / 2.0
        self.cell(half, 6, f"Page {self.page_no()}")
        self.cell(half, 6, self.generated_on, align="R")
        self.set_text_color(0, 0, 0)


def _branded_pdf(title: str, generated_at: object) -> _ReportPDF:
    """Shared RF-15 header: title top-left, neutral accent rule. A report is
    CROSS-COMPANY (it spans providers), so it has NO single brand: no logo
    (company=None) and the NEUTRAL accent, never the OSIUS pink/logo."""
    pdf = _ReportPDF(orientation="P", unit="mm", format="A4")
    register_fonts(pdf)
    pdf.generated_on = str(generated_at or "")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    logo_bottom = draw_logo(pdf, None, y=10.0)
    pdf.set_xy(pdf.l_margin + LOGO_WIDTH_MM + 8.0, 12.0)
    pdf.set_font(FONT_FAMILY, "B", 15)
    pdf.cell(0, 8, title)

    rule_y = max(logo_bottom, 25.0) + 3.0
    accent_rule(pdf, rule_y, NEUTRAL_ACCENT_RGB)
    pdf.set_y(rule_y + 5.0)
    return pdf


def _new_pdf(title: str, payload: dict) -> FPDF:
    pdf = _branded_pdf(title, payload["generated_at"])

    pdf.set_font(FONT_FAMILY, "", 10)
    pdf.cell(
        0, 6, f"Period: {payload['from']} -- {payload['to']}",
        new_x="LMARGIN", new_y="NEXT",
    )
    for line in _scope_summary_lines(payload["scope"]):
        pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Total: {payload['total']}", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(2)
    return pdf


def _pdf_bytes(pdf: FPDF) -> bytes:
    out = pdf.output()
    # fpdf2 returns a bytearray; coerce to immutable bytes for HttpResponse.
    return bytes(out)


def _draw_table(pdf: FPDF, headers: list, widths: list, rows: list) -> None:
    # RF-15 — tinted, neutral-accent header row + light borders (cross-company
    # report → never the OSIUS pink).
    pdf.set_draw_color(208, 200, 206)
    pdf.set_fill_color(*NEUTRAL_TINT_RGB)
    pdf.set_text_color(*NEUTRAL_ACCENT_RGB)
    pdf.set_font(FONT_FAMILY, "B", 9.5)
    for header, width in zip(headers, widths):
        pdf.cell(width, 7, header, border=1, fill=True)
    pdf.ln()
    pdf.set_text_color(0, 0, 0)
    pdf.set_font(FONT_FAMILY, "", 9)
    for row in rows:
        for value, width in zip(row, widths):
            text = str(value) if value is not None else ""
            # fpdf2 has no built-in wrap inside cell(); for our table-
            # first reports a hard truncate keeps the layout intact and
            # is acceptable per the brief ("not pixel-perfect").
            if len(text) > 40:
                text = text[:39] + "…"
            pdf.cell(width, 6, text, border=1)
        pdf.ln()
    pdf.set_draw_color(0, 0, 0)


# ---- PDF: tickets-by-type --------------------------------------------------


def build_tickets_by_type_pdf(payload: dict) -> bytes:
    pdf = _new_pdf("Tickets by type", payload)
    rows = [
        [b["ticket_type_label"], b["ticket_type"], b["count"]]
        for b in payload["buckets"]
    ]
    _draw_table(
        pdf,
        headers=["Type label", "Type code", "Count"],
        widths=[80, 60, 30],
        rows=rows,
    )
    return _pdf_bytes(pdf)


# ---- PDF: tickets-by-origin (Sprint 14A) -----------------------------------


def build_tickets_by_origin_pdf(payload: dict) -> bytes:
    pdf = _new_pdf("Tickets by origin", payload)
    rows = [
        [b["origin_label"], b["origin"], b["count"]]
        for b in payload["buckets"]
    ]
    _draw_table(
        pdf,
        headers=["Origin label", "Origin code", "Count"],
        widths=[80, 60, 30],
        rows=rows,
    )
    return _pdf_bytes(pdf)


# ---- PDF: tickets-by-customer ----------------------------------------------


def build_tickets_by_customer_pdf(payload: dict) -> bytes:
    pdf = _new_pdf("Tickets by customer", payload)
    rows = [
        [
            b["customer_name"],
            b["building_name"],
            b["company_name"],
            b["count"],
        ]
        for b in payload["buckets"]
    ]
    _draw_table(
        pdf,
        headers=["Customer", "Building", "Company", "Count"],
        widths=[60, 50, 50, 20],
        rows=rows,
    )
    return _pdf_bytes(pdf)


# ---- PDF: tickets-by-building ----------------------------------------------


def build_tickets_by_building_pdf(payload: dict) -> bytes:
    pdf = _new_pdf("Tickets by building", payload)
    rows = [
        [b["building_name"], b["company_name"], b["count"]]
        for b in payload["buckets"]
    ]
    _draw_table(
        pdf,
        headers=["Building", "Company", "Count"],
        widths=[80, 70, 30],
        rows=rows,
    )
    return _pdf_bytes(pdf)


# ---- PDF: extra-work-revenue (Sprint 14D) ----------------------------------
# Mirrors the JSON / CSV revenue report (same states, same money totals from
# `compute_extra_work_revenue`) so the three formats cannot drift. Closes the
# transcript-backed PDF-export gap (transkript.txt:65 "Bunu bir pdf yapip
# cakiyoruz" / :415 "csv veya pdf"): per-state count + revenue answers
# "kac ekstra is yapmis, ne kadar tutmus".
#
# The revenue payload shape differs from the dimension reports' (it carries a
# `totals` dict + a `states` map, not a flat `buckets` list + int `total`), so
# this builder constructs its own header instead of reusing `_new_pdf`, while
# still sharing `_scope_summary_lines` / `_draw_table` / `_pdf_bytes`.
_REVENUE_STATE_PDF_LABELS = {
    "earned": "Earned (closed)",
    "in_progress": "In progress",
    "quoted_pipeline": "Quoted pipeline",
    "lost": "Lost",
}


def build_extra_work_revenue_pdf(payload: dict) -> bytes:
    pdf = _branded_pdf("Extra Work Revenue", payload["generated_at"])

    pdf.set_font(FONT_FAMILY, "", 10)
    pdf.cell(
        0, 6, f"Period: {payload['from']} -- {payload['to']}",
        new_x="LMARGIN", new_y="NEXT",
    )
    for line in _scope_summary_lines(payload["scope"]):
        pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    totals = payload["totals"]
    pdf.cell(
        0,
        6,
        f"Total: {totals['count']} request(s) / {totals['total']} revenue",
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(2)

    states = payload["states"]
    rows = [
        [
            _REVENUE_STATE_PDF_LABELS.get(state, state),
            states[state]["count"],
            states[state]["subtotal"],
            states[state]["vat"],
            states[state]["total"],
        ]
        for state in _REVENUE_CSV_STATE_ORDER
    ]
    rows.append(
        [
            "TOTAL",
            totals["count"],
            totals["subtotal"],
            totals["vat"],
            totals["total"],
        ]
    )
    _draw_table(
        pdf,
        headers=["State", "Count", "Subtotal", "VAT", "Total"],
        widths=[52, 24, 34, 34, 34],
        rows=rows,
    )
    return _pdf_bytes(pdf)


# ---- PDF: extra-work-revenue-by-building (Sprint 124) ----------------------
# Unlike the flat revenue PDF, this payload IS the standard flat `buckets` +
# `totals` shape (one row per building), so `_new_pdf` fits directly —
# except `_new_pdf` prints `payload["total"]` (a bare int, the ticket-
# dimension convention) where this payload carries a `totals` money dict,
# so the header is built inline instead of via `_new_pdf`.


def build_extra_work_revenue_by_building_pdf(payload: dict) -> bytes:
    pdf = _branded_pdf("Extra Work Revenue by Building", payload["generated_at"])

    pdf.set_font(FONT_FAMILY, "", 10)
    pdf.cell(
        0, 6, f"Period: {payload['from']} -- {payload['to']}",
        new_x="LMARGIN", new_y="NEXT",
    )
    for line in _scope_summary_lines(payload["scope"]):
        pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    totals = payload["totals"]
    pdf.cell(
        0,
        6,
        f"Total: {totals['count']} request(s) / {totals['total']} revenue",
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(2)

    rows = [
        [
            b["building_name"],
            b["company_name"],
            b["count"],
            b["subtotal"],
            b["vat"],
            b["total"],
        ]
        for b in payload["buckets"]
    ]
    _draw_table(
        pdf,
        headers=["Building", "Company", "Count", "Subtotal", "VAT", "Total"],
        widths=[46, 40, 18, 28, 28, 28],
        rows=rows,
    )
    return _pdf_bytes(pdf)


# ---- CSV: extra-work-by-department (Sprint 131) ----------------------------
# One row per LEAF bucket (building x department x work_type) — the same
# "aggregate bucket, not raw row" convention as the by-building CSV above.
# The individual-work listing is the PDF detail section's job, not the CSV's.

DEPARTMENT_CSV_COLUMNS = (
    "building_id",
    "building_name",
    "company_id",
    "company_name",
    "department_id",
    "department_name",
    "work_type_id",
    "work_type_name",
    "count",
    "subtotal",
    "vat",
    "total",
    "period_from",
    "period_to",
)


def build_extra_work_by_department_csv(payload: dict) -> bytes:
    buffer, writer = _csv_writer(DEPARTMENT_CSV_COLUMNS)
    period_from = payload["from"]
    period_to = payload["to"]
    for building in payload["buildings"]:
        for dept in building["departments"]:
            for wt in dept["work_types"]:
                writer.writerow(
                    {
                        "building_id": building["building_id"],
                        "building_name": building["building_name"],
                        "company_id": building["company_id"],
                        "company_name": building["company_name"],
                        "department_id": dept["department_id"],
                        "department_name": dept["department_name"],
                        "work_type_id": wt["work_type_id"],
                        "work_type_name": wt["work_type_name"],
                        "count": wt["count"],
                        "subtotal": wt["subtotal"],
                        "vat": wt["vat"],
                        "total": wt["total"],
                        "period_from": period_from,
                        "period_to": period_to,
                    }
                )
    return buffer.getvalue().encode("utf-8")


# ---- PDF: extra-work-by-department (Sprint 131) ----------------------------
# Reproduces the owner's father's reference "Extra Works by Department"
# report: a Summary section (overall total, then per building a building
# total + one row per department/work-type + department/building
# subtotals), followed by a Detail section (per building, its own page: a
# numbered Title/Week/Completed-at/Excl.-VAT listing per department / work
# type, with the same subtotal ladder).
#
# NOT built from the reference PDF itself — it was not in the repo (asked
# for, not supplied). This is a best-effort rendering of the sprint brief's
# WRITTEN description of that PDF, reusing the Dutch formatters proven on
# the invoice/proposal PDFs. Wording, exact ordering and the choice to
# bracket each building with a total at both the top AND bottom of its
# summary block are this renderer's reading of that brief, not a verified
# pixel match — flagged for a side-by-side check against the real
# reference before this is considered "matched".
#
# Numbering in the Detail section restarts at 1 for each BUILDING (not per
# department / work type) — one continuous numbered list per building page,
# which is the most useful "row N" audit reference across a building's
# whole detail block.
_DEPT_SUMMARY_LABEL_W = 110.0
_DEPT_SUMMARY_COUNT_W = 30.0
_DEPT_SUMMARY_TOTAL_W = 50.0
_DEPT_DETAIL_COLS = (12.0, 88.0, 20.0, 32.0, 38.0)  # # | Titel | Week | Afgerond op | Excl. BTW


def _dept_scope_summary_lines_nl(scope: dict) -> list:
    """Dutch analogue of `_scope_summary_lines` — this report is Dutch-only,
    unlike the English cross-company reports that helper serves."""
    parts = []
    if scope.get("company_name"):
        parts.append(f"Bedrijf: {scope['company_name']}")
    if scope.get("building_name"):
        parts.append(f"Gebouw: {scope['building_name']}")
    if scope.get("customer_name"):
        parts.append(f"Klant: {scope['customer_name']}")
    if scope.get("department_name"):
        parts.append(f"Afdeling: {scope['department_name']}")
    if scope.get("work_type_name"):
        parts.append(f"Werktype: {scope['work_type_name']}")
    return parts or ["Bereik: Alles"]


def _dept_total_line(pdf: FPDF, label: str, count: int, total: str) -> None:
    pdf.set_font(FONT_FAMILY, "B", 10)
    pdf.cell(_DEPT_SUMMARY_LABEL_W, 7, _safe_pdf_text(label))
    pdf.cell(_DEPT_SUMMARY_COUNT_W, 7, str(count), align="R")
    pdf.cell(
        _DEPT_SUMMARY_TOTAL_W, 7, total, align="R", new_x="LMARGIN", new_y="NEXT"
    )


class _DeptReportPDF(_ReportPDF):
    """Dutch-footer variant of `_ReportPDF` ("Pagina N", not "Page N") —
    this is the one report PDF in the module that is Dutch throughout;
    the shared footer stays English for every other (cross-company,
    English) report so this override cannot affect them."""

    def footer(self) -> None:  # noqa: D401 — fpdf2 hook
        self.set_y(-12)
        self.set_font(FONT_FAMILY, "", 7.5)
        self.set_text_color(130, 125, 129)
        half = self.epw / 2.0
        self.cell(half, 6, f"Pagina {self.page_no()}")
        self.cell(half, 6, self.generated_on, align="R")
        self.set_text_color(0, 0, 0)


def _draw_dept_detail_header_row(pdf: FPDF) -> None:
    pdf.set_draw_color(208, 200, 206)
    pdf.set_fill_color(*NEUTRAL_TINT_RGB)
    pdf.set_text_color(*NEUTRAL_ACCENT_RGB)
    pdf.set_font(FONT_FAMILY, "B", 8.5)
    for header, width in zip(
        ("#", "Titel", "Week", "Afgerond op", "Excl. BTW"), _DEPT_DETAIL_COLS
    ):
        pdf.cell(width, 6, header, border=1, fill=True)
    pdf.ln()
    pdf.set_text_color(0, 0, 0)
    pdf.set_font(FONT_FAMILY, "", 8.5)


def _dept_pdf_header(pdf: FPDF) -> float:
    logo_bottom = draw_logo(pdf, None, y=10.0)
    pdf.set_xy(pdf.l_margin + LOGO_WIDTH_MM + 8.0, 12.0)
    pdf.set_font(FONT_FAMILY, "B", 15)
    pdf.cell(0, 8, "Meerwerk per afdeling")
    rule_y = max(logo_bottom, 25.0) + 3.0
    accent_rule(pdf, rule_y, NEUTRAL_ACCENT_RGB)
    return rule_y + 5.0


def build_extra_work_by_department_pdf(payload: dict) -> bytes:
    pdf = _DeptReportPDF(orientation="P", unit="mm", format="A4")
    register_fonts(pdf)
    pdf.generated_on = str(payload.get("generated_at") or "")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_y(_dept_pdf_header(pdf))

    pdf.set_font(FONT_FAMILY, "", 10)
    pdf.cell(
        0,
        6,
        f"Periode: {payload['from']} t/m {payload['to']}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    for line in _dept_scope_summary_lines_nl(payload["scope"]):
        pdf.cell(0, 6, _safe_pdf_text(line), new_x="LMARGIN", new_y="NEXT")

    totals = payload["totals"]
    pdf.ln(1)
    pdf.set_font(FONT_FAMILY, "B", 12)
    pdf.cell(
        0,
        8,
        f"Totaal: {totals['count']} werkzaamheden | "
        f"{_fmt_money(Decimal(totals['total']))}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(2)

    buildings = payload["buildings"]
    if not buildings:
        pdf.set_font(FONT_FAMILY, "", 10)
        pdf.cell(0, 6, "Geen resultaten voor deze periode.")

    # ---- Summary section: per building, its total, then per department
    # a row per work type + a department subtotal, closed by a building
    # total. --------------------------------------------------------------
    for building in buildings:
        pdf.set_font(FONT_FAMILY, "B", 11)
        pdf.cell(
            0,
            7,
            _safe_pdf_text(
                f"{building['building_name']} — gebouwtotaal: "
                f"{building['count']} werkzaamheden | "
                f"{_fmt_money(Decimal(building['total']))}"
            ),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        for dept in building["departments"]:
            dept_label = dept["department_name"] or "Geen afdeling"
            pdf.set_font(FONT_FAMILY, "B", 10)
            pdf.cell(0, 6, _safe_pdf_text(dept_label), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(FONT_FAMILY, "", 9.5)
            for wt in dept["work_types"]:
                wt_label = wt["work_type_name"] or "Geen werktype"
                pdf.cell(_DEPT_SUMMARY_LABEL_W, 6, _safe_pdf_text(f"    {wt_label}"))
                pdf.cell(_DEPT_SUMMARY_COUNT_W, 6, str(wt["count"]), align="R")
                pdf.cell(
                    _DEPT_SUMMARY_TOTAL_W,
                    6,
                    _fmt_money(Decimal(wt["total"])),
                    align="R",
                    new_x="LMARGIN",
                    new_y="NEXT",
                )
            _dept_total_line(
                pdf,
                f"  Subtotaal {dept_label}",
                dept["count"],
                _fmt_money(Decimal(dept["total"])),
            )
        _dept_total_line(
            pdf,
            "Totaal gebouw",
            building["count"],
            _fmt_money(Decimal(building["total"])),
        )
        pdf.ln(3)

    # ---- Detail section: one page per building. ---------------------------
    for building in buildings:
        pdf.add_page()
        pdf.set_font(FONT_FAMILY, "B", 13)
        pdf.cell(
            0, 8, _safe_pdf_text(building["building_name"]), new_x="LMARGIN", new_y="NEXT"
        )
        pdf.ln(1)
        row_no = 0
        for dept in building["departments"]:
            dept_label = dept["department_name"] or "Geen afdeling"
            pdf.set_font(FONT_FAMILY, "B", 11)
            pdf.cell(0, 7, _safe_pdf_text(dept_label), new_x="LMARGIN", new_y="NEXT")
            for wt in dept["work_types"]:
                wt_label = wt["work_type_name"] or "Geen werktype"
                pdf.set_font(FONT_FAMILY, "B", 10)
                pdf.cell(0, 6, _safe_pdf_text(wt_label), new_x="LMARGIN", new_y="NEXT")
                _draw_dept_detail_header_row(pdf)

                for row in wt["rows"]:
                    # A work type with enough rows to outrun the page (a
                    # busy customer can have hundreds under one work type)
                    # would otherwise land bare numbered rows on the
                    # continuation page with no column header and no
                    # department/work-type context above them — check
                    # BEFORE drawing so the repeated context always leads
                    # its rows, never trails them.
                    if pdf.will_page_break(6):
                        pdf.add_page()
                        pdf.set_font(FONT_FAMILY, "B", 10)
                        pdf.cell(
                            0,
                            6,
                            _safe_pdf_text(
                                f"{building['building_name']} — {dept_label} — "
                                f"{wt_label} (vervolg)"
                            ),
                            new_x="LMARGIN",
                            new_y="NEXT",
                        )
                        _draw_dept_detail_header_row(pdf)

                    row_no += 1
                    values = (
                        str(row_no),
                        row["title"],
                        str(row["week_no"]) if row["week_no"] is not None else "-",
                        row["completed_at"] or "-",
                        _fmt_money(Decimal(row["subtotal"])),
                    )
                    aligns = ("R", "L", "R", "R", "R")
                    for value, width, align in zip(values, _DEPT_DETAIL_COLS, aligns):
                        _fitted_cell(
                            pdf,
                            width,
                            6,
                            _safe_pdf_text(value),
                            align=align,
                            border=1,
                            base_size=8.5,
                        )
                    pdf.ln()

                _dept_total_line(
                    pdf,
                    f"  Subtotaal {wt_label}",
                    wt["count"],
                    _fmt_money(Decimal(wt["total"])),
                )
            _dept_total_line(
                pdf,
                f"Subtotaal {dept_label}",
                dept["count"],
                _fmt_money(Decimal(dept["total"])),
            )
        _dept_total_line(
            pdf,
            "Totaal gebouw",
            building["count"],
            _fmt_money(Decimal(building["total"])),
        )

    return _pdf_bytes(pdf)
