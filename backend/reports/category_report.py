"""
Sprint 185 E §1 — meldingen per CATEGORY per BUILDING, per period.

    GET /api/reports/meldingen-by-category/?from=&to=&company=&building=

This is the report the owner asked for in these words: the monthly
customer review is *"how many meldingen per category per building"*, and
until Sprint 185 no tenant could answer it — there was no field holding
the kind of WORK at all (`Ticket.type` holds the kind of MESSAGE).

## The shape: buildings outside, categories inside

One bucket per building, each holding one row per category. That is the
way the question is asked — a building is a customer conversation, and
the review walks through them one at a time — and it is the way the
sibling `employee-hours-by-building` report is already shaped, so the
Reports page renders it with the machinery it has.

## Counting, not listing

Every other report on this page lists rows. This one COUNTS them, which
is the whole request: "how many". So it is two aggregates, not a row
list bucketed in Python, and it stays two whatever the period holds —
pinned by `assertNumQueries`. A report that got slower as a tenant got
busier would stop being opened.

## UNCATEGORISED is a row, not a gap

A melding with no category is counted under a `category_id` of `None`.
Dropping it would make the report's total disagree with the number of
meldingen in the period, which is the first thing an operator checks and
the fastest way to lose their trust in the rest of it. It is also the
number that tells them how much of the month is still untagged — the
figure that says whether the taxonomy is being used at all.

The same argument applies to a melding with no BUILDING: it is bucketed
under `building_id: None` rather than dropped.

## Scoping

`scope_tickets_for`, the same helper the ticket list and the ticket
report use. No second scoping path — a report that computed its own
visibility would be a second answer to "what may this actor see", and
the two would drift. The Reports page's own `?company=` / `?building=`
narrowing runs ON TOP of it, never instead: `reports.scoping.
resolve_scope` has already refused (403) anything the actor may not
reach, so a `ResolvedScope` arriving here can only make the answer
smaller.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Count, Q

from tickets.models import Ticket


def meldingen_by_category_default_period() -> tuple[date, date]:
    """The last 30 days, the default every period report on this page
    uses. Named here so the JSON, the CSV and the PDF cannot disagree
    about what "no period given" means."""
    today = date.today()
    return today - timedelta(days=30), today


def _period(date_from: date, date_to: date) -> tuple[date, date]:
    return (date_from, date_to) if date_from <= date_to else (date_to, date_from)


def _scoped_tickets(user, date_from: date, date_to: date, scope=None):
    """The meldingen of the period this actor may read, optionally
    narrowed. One function, so the report and any future summary card
    cannot be looking at two different sets of tickets."""
    from accounts.scoping import scope_tickets_for

    tickets = scope_tickets_for(user).filter(
        created_at__date__gte=date_from, created_at__date__lte=date_to
    )
    if scope is not None:
        if scope.company is not None:
            tickets = tickets.filter(company_id=scope.company.id)
        if scope.building is not None:
            tickets = tickets.filter(building_id=scope.building.id)
    return tickets


def build_meldingen_by_category(user, date_from: date, date_to: date, scope=None):
    """Meldingen counted per (building, category) for the period.

    Two queries, flat:

      1. the grouped counts, `values(...).annotate(Count)`;
      2. the per-building totals, from the same queryset.

    The second is not derivable from the first without trusting Python
    arithmetic over a database aggregate, and the two must agree — so
    both come from the database and a mismatch is impossible rather than
    unlikely.
    """
    date_from, date_to = _period(date_from, date_to)
    tickets = _scoped_tickets(user, date_from, date_to, scope)

    grouped = (
        tickets.values(
            "building_id",
            "building__name",
            "category_id",
            "category__name",
        )
        .annotate(count=Count("id"))
        .order_by("building__name", "category__name")
    )

    per_building_totals = {
        row["building_id"]: row["count"]
        for row in tickets.values("building_id").annotate(count=Count("id"))
    }

    buildings: list[dict] = []
    index: dict[int | None, dict] = {}
    total = 0
    uncategorised = 0
    for row in grouped:
        building_id = row["building_id"]
        bucket = index.get(building_id)
        if bucket is None:
            bucket = {
                "building": building_id,
                "building_name": row["building__name"],
                "total": per_building_totals.get(building_id, 0),
                "categories": [],
            }
            index[building_id] = bucket
            buildings.append(bucket)
        count = row["count"]
        total += count
        if row["category_id"] is None:
            uncategorised += count
        bucket["categories"].append(
            {
                "category": row["category_id"],
                # `None` and not a translated word: the reader's language
                # is a client concern, and the CSV and the PDF pick their
                # own dash. A server-side "Uncategorised" would be an
                # English string in a Dutch export.
                "category_name": row["category__name"],
                "count": count,
            }
        )

    return {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "buildings": buildings,
        "total": total,
        # The number that says whether the taxonomy is being used at all.
        # Reported beside the total rather than left for the reader to
        # add up, because "how much of last month is still untagged" is
        # the question this answers on the way to the real one.
        "uncategorised": uncategorised,
    }


def build_meldingen_by_category_summary(
    user, date_from: date, date_to: date, scope=None
) -> dict:
    """What the report CARD says before it is opened.

    Two aggregates, and they come from the same `_scoped_tickets` the
    report itself uses — a card saying 41 and the report it opens saying
    38 is the one failure that would make the whole panel untrustworthy,
    so there is no second query path to drift.
    """
    date_from, date_to = _period(date_from, date_to)
    tickets = _scoped_tickets(user, date_from, date_to, scope)

    totals = tickets.aggregate(
        total=Count("id"),
        uncategorised=Count("id", filter=Q(category__isnull=True)),
    )
    distinct = tickets.aggregate(
        categories=Count("category", distinct=True),
        buildings=Count("building", distinct=True),
    )
    return {
        "total": totals["total"] or 0,
        "uncategorised": totals["uncategorised"] or 0,
        "categories": distinct["categories"] or 0,
        "buildings": distinct["buildings"] or 0,
    }
