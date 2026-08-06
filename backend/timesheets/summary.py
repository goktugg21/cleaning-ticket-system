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
# Sprint 152.2 — the "no building recorded" bucket's stable id. A
# SENTINEL, not a label: the API must not choose a display language for
# the client, and `null` alone would force every consumer to invent its
# own name for the same bucket.
NO_BUILDING_MARKER = "__none__"


def _employee_name(row) -> str:
    """The name to show for an employee bucket, falling back to email.

    Same rule as `TimeEntrySerializer.get_employee_name`: `full_name` is
    optional on `User`, and a bucket labelled with an empty string is
    indistinguishable from every other unnamed one.
    """
    return row.get("employee__full_name") or row.get("employee__email") or ""


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

    # Sprint 152.2 — "in this period, who worked in which buildings?" is
    # the owner's actual question and the payload could not answer it.
    # Both breakdowns are purely ADDITIVE: every pre-existing key keeps
    # its name and shape.
    #
    # `restrict_entries_to_self` has already been applied by the caller,
    # so for a STAFF / BUILDING_MANAGER actor `by_employee` contains
    # exactly one row — themselves. That is correct, not a degenerate
    # case to special-case away.
    by_employee = [
        {
            "employee": row["employee_id"],
            "employee_name": _employee_name(row),
            "entries": row["entries"],
            "hours": _money(row["sum_hours"]),
            "weighted_hours": _money(row["sum_weighted"]),
        }
        for row in queryset.values(
            "employee_id", "employee__full_name", "employee__email"
        )
        .annotate(
            entries=Count("id"),
            sum_hours=_sum_hours(),
            sum_weighted=_sum_weighted(),
        )
        .order_by("-sum_weighted", "employee__full_name", "employee_id")
    ]

    by_building = [
        {
            "building": row["building_id"],
            # A NULL building is its own explicit bucket, never dropped:
            # hours with no location recorded are exactly the ones an
            # operator needs to notice. The marker is a stable SENTINEL,
            # not a Dutch string — the frontend translates it, so the API
            # does not pick a language on the client's behalf.
            "building_name": row["building__name"] or NO_BUILDING_MARKER,
            "entries": row["entries"],
            "hours": _money(row["sum_hours"]),
            "weighted_hours": _money(row["sum_weighted"]),
        }
        for row in queryset.values("building_id", "building__name")
        .annotate(
            entries=Count("id"),
            sum_hours=_sum_hours(),
            sum_weighted=_sum_weighted(),
        )
        .order_by("-sum_weighted", "building__name", "building_id")
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
        "by_employee": by_employee,
        "by_building": by_building,
        "by_week": by_week,
    }
