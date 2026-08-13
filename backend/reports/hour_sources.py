"""
Sprint 173 §1 — turning an hour's `(source_type, source_id)` into a
title an operator can read.

## Why the resolution lives here and not on the model

`timesheets` imports nothing from `tickets` or `extra_work`, so a
`TimeEntry` carries a type and an id and resolves neither. `reports/`
is the app that may read across — `hours_comparison.py` already reaches
into two modules for exactly this reason — so the resolver lives here
and the hours module stays independent.

## Two things this handles rather than discovers later

**An id that no longer resolves.** A ticket can be soft-deleted after
its hours were logged. `resolve_sources` returns no title for it and
every caller falls back to a plain label like "Ticket #41". A report
that raised, or rendered blank, would turn a deleted ticket into a
broken screen.

**Scoping.** The id is stored on a row the actor can already read, but
the TITLE is data from another module and must not leak. Resolution
goes through the same scoping helpers the ticket and extra-work lists
use, so an actor who could not open the ticket gets no title — the same
answer a fictional id gives. That equivalence is the H-1 shape: out of
scope must be indistinguishable from nonexistent.

## One query per type, never per row

Two queries for a whole report, whatever its size. A per-row lookup
would be the N+1 the `assertNumQueries` tests exist to catch.
"""
from __future__ import annotations

from timesheets.models import HourSource


def resolve_sources(user, pairs) -> dict[tuple[str, int], str]:
    """`{(source_type, source_id): title}` for everything `user` may see.

    `pairs` is any iterable of `(source_type, source_id)`. Anything the
    actor cannot see, and anything that no longer exists, is simply
    absent from the result — callers treat both the same way, which is
    what makes the two indistinguishable.
    """
    wanted: dict[str, set[int]] = {}
    for source_type, source_id in pairs:
        if not source_id:
            continue
        wanted.setdefault(source_type, set()).add(source_id)

    titles: dict[tuple[str, int], str] = {}

    ticket_ids = wanted.get(HourSource.TICKET)
    if ticket_ids:
        from accounts.scoping import scope_tickets_for

        for ticket in scope_tickets_for(user).filter(id__in=ticket_ids).only(
            "id", "ticket_no", "title"
        ):
            titles[(HourSource.TICKET, ticket.id)] = (
                f"{ticket.ticket_no} — {ticket.title}"
            )

    extra_ids = wanted.get(HourSource.EXTRA_WORK)
    if extra_ids:
        from extra_work.scoping import scope_extra_work_for

        for request in (
            scope_extra_work_for(user).filter(id__in=extra_ids).only("id", "title")
        ):
            titles[(HourSource.EXTRA_WORK, request.id)] = request.title

    # CONTRACT and OTHER carry no resolvable record: CONTRACT hours are
    # the standing agreement itself (there is no single row to name),
    # and OTHER means nobody said. Both render from their type alone.
    return titles


def available_sources(user, *, query: str = "", limit: int = 50) -> list[dict]:
    """The jobs `user` may log hours AGAINST — the list direction.

    Sprint 177 §7. `resolve_sources` above turns a stored pair into a
    title; this offers the pairs in the first place, so an operator picks
    the job from a list and `(source_type, source_id)` travels with the
    hours instead of being typed twice.

    That was the actual gap. Sprint 173 added the column, Sprint 174
    added the filter and taught the week-grid endpoint to ACCEPT a source
    per cell — but nothing ever supplied one, so every row read as
    untagged and "employee hours by extra work" was a report over a
    column nobody fills.

    Here for the same reason `resolve_sources` is: `timesheets` imports
    nothing from `tickets` or `extra_work`, and `reports/` is the app
    that may read across. The picker is a cross-module READ, so it lives
    on this side of the line and the hours module stays independent.

    Scoping is the same shape and matters MORE here than on the resolve
    path, because this endpoint enumerates. It goes through the same two
    scoping helpers the ticket and extra-work lists use, so it can never
    offer a job the actor could not already open — offering one would be
    an existence oracle for another tenant's work (H-1).

    Only OPEN work is offered: nobody logs hours against a job that is
    finished, cancelled or rejected, and a picker listing every ticket
    ever closed is a picker nobody can use.

    Two queries, never one per row.
    """
    from accounts.scoping import scope_tickets_for
    from extra_work.models import ExtraWorkStatus
    from extra_work.scoping import scope_extra_work_for

    query = (query or "").strip()
    results: list[dict] = []

    # Extra work first: it is the reason this exists — §5's third report
    # asks "who worked on this extra work, and how much".
    extra = scope_extra_work_for(user).exclude(
        status__in=(
            ExtraWorkStatus.COMPLETED,
            ExtraWorkStatus.CUSTOMER_REJECTED,
            ExtraWorkStatus.CANCELLED,
        )
    )
    if query:
        extra = extra.filter(title__icontains=query)
    for request in extra.only("id", "title", "building_id").order_by("-id")[
        :limit
    ]:
        results.append(
            {
                "source_type": HourSource.EXTRA_WORK,
                "source_id": request.id,
                "title": request.title,
                "building": request.building_id,
            }
        )

    from tickets.models import TicketStatus

    tickets = scope_tickets_for(user)
    # Expressed as "not terminal" rather than a list of open statuses, so
    # a newly added terminal status does not silently start appearing.
    terminal = [
        status
        for status in (
            getattr(TicketStatus, "CLOSED", None),
            getattr(TicketStatus, "CANCELLED", None),
            getattr(TicketStatus, "REJECTED", None),
        )
        if status is not None
    ]
    if terminal:
        tickets = tickets.exclude(status__in=terminal)
    if query:
        tickets = tickets.filter(title__icontains=query)
    for ticket in tickets.only("id", "ticket_no", "title", "building_id").order_by(
        "-id"
    )[:limit]:
        results.append(
            {
                "source_type": HourSource.TICKET,
                "source_id": ticket.id,
                "title": f"{ticket.ticket_no} — {ticket.title}",
                "building": ticket.building_id,
            }
        )

    return results


def source_label(source_type: str, source_id, titles) -> str | None:
    """The display label for one entry's source, or `None` for OTHER.

    A resolvable id gives its title; an id that did not resolve gives
    the type and the number, which is honest and never blank. `None`
    means "no source was recorded", which the UI shows as an em dash —
    different from "recorded but gone".
    """
    if source_type == HourSource.OTHER and not source_id:
        return None
    if not source_id:
        return str(HourSource(source_type).label)
    resolved = titles.get((source_type, source_id))
    if resolved:
        return resolved
    return f"{HourSource(source_type).label} #{source_id}"
