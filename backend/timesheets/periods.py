"""
Sprint 152.2 — period parsing for the timesheets module.

Mirrors the SHAPE of `reports/scoping.py::parse_date_range` but imports
nothing from it: this module is independent by design, and a shared
parser would be the first thread tying it back to the ticket reporting
stack.

It also differs from that function in one deliberate way. `parse_date_
range` DEFAULTS to a 30-day window when the params are absent. These
endpoints must not: `/entries/`, `/summary/` and `/summary/export.csv`
legitimately answer "everything ever recorded", and quietly imposing a
window would make an admin's unfiltered total silently wrong — the worst
kind of wrong, because it looks like an answer. Absent or empty stays
"no filter"; `None` is returned and the caller skips the filter.

## The bug this closes

`views_entries._apply_entry_filters` passed the raw strings straight
into `.filter(date__gte=...)`. The DB layer's own coercion raises
`django.core.exceptions.ValidationError`, which DRF does NOT translate
into a 400 — so any unparseable value was an unhandled 500, on all three
endpoints at once because they share that helper. A date typed by hand
into a URL, or a `<input type=date>` cleared to an empty-ish value by a
browser that formats differently, was enough.
"""
from __future__ import annotations

import datetime as dt

from rest_framework import serializers


# Stable error code for every malformed / contradictory period.
ERR_PERIOD_INVALID = "timesheet_period_invalid"

DATE_FORMAT = "%Y-%m-%d"


def _invalid(field: str, message: str):
    return serializers.ValidationError(
        {
            field: [
                serializers.ErrorDetail(message, code=ERR_PERIOD_INVALID)
            ]
        }
    )


def parse_optional_date(raw, field_name: str):
    """Parse one `YYYY-MM-DD` param. Returns `None` for absent/empty.

    `strptime` rather than a regex or `date.fromisoformat`: it rejects
    `2026-02-30` — correctly SHAPED and not a date — which a regex would
    wave through and the DB would then 500 on. (`fromisoformat` also
    rejects it, but it accepts other ISO-8601 spellings this API has
    never documented; one exact format is the narrower contract.)
    """
    if raw is None or raw == "":
        return None
    try:
        return dt.datetime.strptime(raw, DATE_FORMAT).date()
    except (TypeError, ValueError):
        raise _invalid(
            field_name,
            f"Invalid date for '{field_name}'. Expected YYYY-MM-DD.",
        )


def parse_period(query_params):
    """Read `?date_from=` / `?date_to=` into `(from_date, to_date)`.

    Either half may be `None`, meaning "unbounded on that side" — a
    caller may legitimately ask for "everything up to today" or
    "everything since January".

    A REVERSED range is rejected rather than allowed to return nothing:
    an empty result reads as "nobody worked in this period", which is a
    different and much more alarming statement than "your two dates are
    the wrong way round".
    """
    from_date = parse_optional_date(query_params.get("date_from"), "date_from")
    to_date = parse_optional_date(query_params.get("date_to"), "date_to")

    if from_date is not None and to_date is not None and from_date > to_date:
        raise _invalid(
            "date_from",
            "Invalid period: 'date_from' must not be after 'date_to'.",
        )
    return from_date, to_date


def iso_week_exists(iso_year: int, iso_week: int) -> bool:
    """True iff `(iso_year, iso_week)` names a real ISO week.

    A week number inside 1..53 is NOT proof the week exists: most years
    have 52 ISO weeks and only some have 53 (2025 has 52, 2026 has 53).
    `date.fromisocalendar` is the authority — it raises for a pair that
    does not resolve to a day.

    Only the CLOSE / REOPEN / STATUS endpoints need this, because they
    are the only places an ISO week arrives from a client. Everywhere
    else the pair was derived from a stored `TimeEntry.date`, so it
    exists by construction — which is why `weeks.week_bounds` is left
    alone rather than defensively guarded.
    """
    try:
        dt.date.fromisocalendar(iso_year, iso_week, 1)
    except ValueError:
        return False
    return True
