"""
Sprint 152 — the timesheets summary computation.

Lives INSIDE the timesheets app rather than in `reports/`, for the same
reason the module has no FK to `tickets`: a report that had to be
registered in another app would make this module depend on that app to
be useful. Only the CODE SHAPE of `reports/exports.py`'s `build_*_csv`
is mirrored (see `exports.py`), not its wiring.

Weighted hours are computed from `multiplier_snapshot`, NEVER from
`hour_type.multiplier`. That is what makes a closed week's totals stable
across a later multiplier edit, and it is why the aggregation below
multiplies two columns of the entry row instead of joining to the type.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, DecimalField, F, Sum
from django.db.models.functions import Coalesce

from .weeks import closed_weeks_for, week_bounds


ZERO = Decimal("0.00")

_DECIMAL_OUT = DecimalField(max_digits=14, decimal_places=2)


def weighted_expr():
    """The weighted-hours expression, DB-side: `hours *
    multiplier_snapshot` — the same rule as `TimeEntry.weighted_hours`,
    written once so the summary, the export and the serializer cannot
    drift apart.

    A FUNCTION returning a fresh expression rather than a module-level
    constant: Django resolves an expression against the query it is used
    in and caches state on the instance, so one shared object reused
    across several queries is not supported.
    """
    return F("hours") * F("multiplier_snapshot")


# Aggregate ALIASES are deliberately prefixed `sum_`, never `hours`.
#
# An `.annotate(hours=Sum("hours"), weighted=... F("hours") ...)` does
# not compute what it reads as: Django resolves annotations in order, so
# by the time `F("hours")` inside the second one is resolved, the alias
# `hours` already exists as an AGGREGATE and `F` binds to that instead
# of to the column. It fails loudly (`FieldError: ... is an aggregate`)
# rather than quietly, which is the only reason this is a comment and
# not a bug report.
def _sum_hours():
    return Coalesce(Sum("hours"), ZERO, output_field=_DECIMAL_OUT)


def _sum_weighted():
    """`Coalesce(Sum(weighted), 0)` — the shape every total in this
    module uses, so an empty bucket reports 0.00 rather than null.
    """
    return Coalesce(
        Sum(weighted_expr(), output_field=_DECIMAL_OUT),
        ZERO,
        output_field=_DECIMAL_OUT,
    )


def _money(value) -> str:
    """Render a Decimal total as a fixed 2-decimal string.

    Named `_money` for the shape, not the meaning — these are HOURS.
    Nothing in this module converts them to currency, and nothing should
    (see the app's module docstring).
    """
    if value is None:
        return str(ZERO)
    return str(Decimal(value).quantize(Decimal("0.01")))


def build_summary(queryset) -> dict:
    """Aggregate an ALREADY-SCOPED `TimeEntry` queryset.

    The caller owns scoping and filtering; this function owns arithmetic
    only. That split is deliberate: every summary consumer (the JSON
    endpoint, the CSV export) passes the same queryset the entries list
    would return, so the totals under a table can never be computed over
    a different set than the table itself.

    Returns the payload the endpoint serializes verbatim.
    """
    totals = queryset.aggregate(
        total_entries=Count("id"),
        total_hours=_sum_hours(),
        total_weighted_hours=_sum_weighted(),
    )

    by_hour_type = [
        {
            "hour_type": row["hour_type_id"],
            "hour_type_name": row["hour_type__name"],
            # The type's CURRENT multiplier, for display only. The
            # weighted total beside it comes from the SNAPSHOTS, so the
            # two can legitimately disagree after a multiplier edit that
            # left closed weeks alone — which is the system working, not
            # a bug. Named `current_multiplier` so nobody reads it as
            # the factor that produced the number next to it.
            "current_multiplier": str(row["hour_type__multiplier"]),
            "entries": row["entries"],
            "hours": _money(row["sum_hours"]),
            "weighted_hours": _money(row["sum_weighted"]),
        }
        for row in queryset.values(
            "hour_type_id", "hour_type__name", "hour_type__multiplier"
        )
        .annotate(
            entries=Count("id"),
            sum_hours=_sum_hours(),
            sum_weighted=_sum_weighted(),
        )
        .order_by("hour_type__sort_order", "hour_type__name", "hour_type_id")
    ]

    week_rows = list(
        queryset.values("company_id", "iso_year", "iso_week")
        .annotate(
            entries=Count("id"),
            sum_hours=_sum_hours(),
            sum_weighted=_sum_weighted(),
        )
        .order_by("-iso_year", "-iso_week")
    )
    # One lock lookup per COMPANY present in the result, not per week.
    closed_by_company = {
        company_id: closed_weeks_for(company_id)
        for company_id in {row["company_id"] for row in week_rows}
    }
    by_week = []
    for row in week_rows:
        monday, sunday = week_bounds(row["iso_year"], row["iso_week"])
        by_week.append(
            {
                "iso_year": row["iso_year"],
                "iso_week": row["iso_week"],
                "week_start": monday.isoformat(),
                "week_end": sunday.isoformat(),
                "is_closed": (row["iso_year"], row["iso_week"])
                in closed_by_company.get(row["company_id"], set()),
                "entries": row["entries"],
                "hours": _money(row["sum_hours"]),
                "weighted_hours": _money(row["sum_weighted"]),
            }
        )

    return {
        "total_entries": totals["total_entries"] or 0,
        "total_hours": _money(totals["total_hours"]),
        "total_weighted_hours": _money(totals["total_weighted_hours"]),
        "by_hour_type": by_hour_type,
        "by_week": by_week,
    }
