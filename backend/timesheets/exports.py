"""
Sprint 152 — CSV export of the timesheets summary.

Mirrors only the CODE SHAPE of `reports/exports.py`'s `build_*_csv`
family — a `_csv_writer` over a stable column tuple, a UTF-8 BOM so
Excel opens it correctly, `bytes` out — and imports nothing from it. The
module independence rule is the point: `reports` is wired to tickets and
Extra Work, and a shared helper would drag that dependency in through
the back door for the sake of nine lines.

The columns are a stable contract; the test package pins them.

One CSV carries all three sections of the summary payload, tagged by a
`section` column, rather than three downloads. An operator exports this
to check a period's totals against a payroll run — having the grand
total, the per-type split and the per-week split in one file is what
makes that a single comparison instead of three.
"""
from __future__ import annotations

import csv
import io
from typing import Iterable

from .standard_set import render_standard_label


CSV_BOM = "﻿"  # Excel-friendly UTF-8 marker.

SUMMARY_CSV_COLUMNS = (
    "section",
    "key",
    "label",
    "entries",
    "hours",
    "weighted_hours",
    "is_closed",
    "period_from",
    "period_to",
)


def _csv_writer(columns: Iterable[str]):
    buffer = io.StringIO()
    buffer.write(CSV_BOM)
    writer = csv.DictWriter(
        buffer, fieldnames=list(columns), extrasaction="ignore"
    )
    writer.writeheader()
    return buffer, writer


def build_timesheet_summary_csv(payload: dict, language: str | None = None) -> bytes:
    """Render the `summary.build_summary` payload as CSV bytes.

    Row order is TOTAL first, then hour types, then weeks — the same
    order the screen shows them in, so a reader comparing the two does
    not have to re-sort either.

    ## The CSV translates; the JSON does not

    Sprint 152.3 — a DELIBERATE asymmetry, stated here so it does not
    read as an accident. Every JSON payload sends the stored `name` plus
    `standard_slot` and lets the client choose the wording. This file has
    no client: it is a server-generated artefact that lands in a
    downloads folder and is opened by a spreadsheet, so the label has to
    be resolved here or not at all.

    `language` is the DOWNLOADER's (`request.user.language`, the same
    source the standard-set action reads). A file reading in the language
    of the person who asked for it is the correct behaviour — the
    alternative is a Dutch-only export for an English-profile admin, or
    an English-named column an NL admin cannot reconcile with their
    screen.

    Falls back to the stored name for a custom type, and to Dutch for an
    unset or unknown language — the same fallbacks
    `render_standard_label` applies everywhere else.
    """
    buffer, writer = _csv_writer(SUMMARY_CSV_COLUMNS)
    period_from = payload.get("date_from") or ""
    period_to = payload.get("date_to") or ""

    writer.writerow(
        {
            "section": "TOTAL",
            "key": "",
            "label": "Total",
            "entries": payload["total_entries"],
            "hours": payload["total_hours"],
            "weighted_hours": payload["total_weighted_hours"],
            "is_closed": "",
            "period_from": period_from,
            "period_to": period_to,
        }
    )

    for bucket in payload.get("by_hour_type", []):
        writer.writerow(
            {
                "section": "HOUR_TYPE",
                "key": bucket["hour_type"],
                "label": render_standard_label(
                    bucket.get("standard_slot", ""),
                    bucket["hour_type_name"],
                    language,
                ),
                "entries": bucket["entries"],
                "hours": bucket["hours"],
                "weighted_hours": bucket["weighted_hours"],
                "is_closed": "",
                "period_from": period_from,
                "period_to": period_to,
            }
        )

    # Sprint 152.2 — two new sections. APPENDED after HOUR_TYPE and
    # before WEEK, which is a row-ORDER change only: the column tuple is
    # untouched, and `section` is what a consumer keys on. Reordering or
    # renaming the columns would break every saved spreadsheet formula
    # pointed at this file.
    for bucket in payload.get("by_employee", []):
        writer.writerow(
            {
                "section": "EMPLOYEE",
                "key": bucket["employee"],
                "label": bucket["employee_name"],
                "entries": bucket["entries"],
                "hours": bucket["hours"],
                "weighted_hours": bucket["weighted_hours"],
                "is_closed": "",
                "period_from": period_from,
                "period_to": period_to,
            }
        )

    for bucket in payload.get("by_building", []):
        writer.writerow(
            {
                "section": "BUILDING",
                # `key` is empty for the no-building bucket rather than
                # the sentinel: the id column should hold an id or
                # nothing. The LABEL carries the marker, which is what a
                # reader sorts and filters on anyway.
                "key": "" if bucket["building"] is None else bucket["building"],
                "label": bucket["building_name"],
                "entries": bucket["entries"],
                "hours": bucket["hours"],
                "weighted_hours": bucket["weighted_hours"],
                "is_closed": "",
                "period_from": period_from,
                "period_to": period_to,
            }
        )

    for bucket in payload.get("by_week", []):
        writer.writerow(
            {
                "section": "WEEK",
                "key": f"{bucket['iso_year']}-W{bucket['iso_week']:02d}",
                "label": f"{bucket['week_start']} - {bucket['week_end']}",
                "entries": bucket["entries"],
                "hours": bucket["hours"],
                "weighted_hours": bucket["weighted_hours"],
                "is_closed": "true" if bucket["is_closed"] else "false",
                "period_from": period_from,
                "period_to": period_to,
            }
        )

    return buffer.getvalue().encode("utf-8")
