"""
CSV + PDF export helpers for the Sprint 5 report dimensions.

Each `build_*_csv` function takes the same payload shape that the JSON
endpoint returned (computed in `dimensions.py`) and emits a `bytes`
buffer ready for an HttpResponse. CSV columns are stable contracts —
the tests in `tests/test_dimensions_export.py` pin them.

PDFs use `fpdf2` (pure Python, ~1MB, no system deps; chosen over
reportlab because reportlab pulls in extra weight the project does
not need for these table-first reports). The PDFs are intentionally
NOT pixel-perfect:
- A4 portrait, default Helvetica
- Title, period, generated_at, scope summary
- Single table with the same logical columns as the CSV

The fallback reason for picking fpdf2 is documented in
docs/deployment.md / pilot-readiness-roadmap.md when it lands.
"""
from __future__ import annotations

import csv
import io
from typing import Iterable

from fpdf import FPDF


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


def _new_pdf(title: str, payload: dict) -> FPDF:
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("helvetica", "B", 16)
    pdf.cell(0, 10, title, ln=1)

    pdf.set_font("helvetica", "", 10)
    pdf.cell(0, 6, f"Period: {payload['from']} -- {payload['to']}", ln=1)
    pdf.cell(0, 6, f"Generated at: {payload['generated_at']}", ln=1)
    for line in _scope_summary_lines(payload["scope"]):
        pdf.cell(0, 6, line, ln=1)
    pdf.cell(0, 6, f"Total: {payload['total']}", ln=1)

    pdf.ln(2)
    return pdf


def _pdf_bytes(pdf: FPDF) -> bytes:
    out = pdf.output(dest="S")
    # fpdf2 returns a bytearray; coerce to immutable bytes for HttpResponse.
    return bytes(out)


def _draw_table(pdf: FPDF, headers: list, widths: list, rows: list) -> None:
    pdf.set_font("helvetica", "B", 10)
    for header, width in zip(headers, widths):
        pdf.cell(width, 7, header, border=1)
    pdf.ln()
    pdf.set_font("helvetica", "", 9)
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
