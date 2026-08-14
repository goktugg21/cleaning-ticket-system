"""
Sprint 178 §2 — the ticket report, and how long each one took.

    GET /api/reports/ticket-report/?from=&to=

One row per ticket in the period: status, building, customer, when it was
opened, when it reached a terminal state, and **how long it took** —
computed from `TicketStatusHistory`, not from a column.

## Why the duration is derived and not stored

This is the same argument the product docs make about the reference
system's eleven date columns, and it is the reason there is no
`closed_at` on `Ticket`:

  * a flattened date cannot say WHO closed something, or whether it went
    backwards. `TicketStatusHistory` says both, because it records every
    transition with its actor;
  * a ticket that is reopened and closed again has two closes. A column
    holds the last one and silently forgets the first; the history holds
    both, so "how long did it take" stays answerable — this report uses
    the FIRST arrival at a terminal status, because that is when the work
    was done. A later reopen is a new episode, not a longer one;
  * a stored duration is a cache of a query, and a cache nothing
    invalidates goes wrong the first time a status is corrected.

The cost is one extra query for the history of the tickets in the period.
That is one query, not one per ticket — pinned by `assertNumQueries`.

## Which statuses end the clock

`APPROVED`, `CLOSED` and `REJECTED`. A rejected ticket took however long
it took to be rejected; treating it as unfinished forever would leave a
growing pile of rows whose age means nothing.

`WAITING_CUSTOMER_APPROVAL` deliberately does NOT stop the clock — the
provider is still on the hook, and a report that stopped counting there
would flatter the numbers exactly where an operator would want them
honest.

## Scoping

`scope_tickets_for`, the same helper the ticket list uses. No second
scoping path — a report that computed its own visibility would be a
second answer to "what may this actor see", and the two would drift.

Sprint 180 §1 adds the Reports page's own `?company=` / `?building=`
narrowing ON TOP of that, never instead of it: `reports.scoping.
resolve_scope` has already refused (403) any company or building the
actor may not reach, so by the time a `ResolvedScope` arrives here it can
only ever make the answer SMALLER.
"""
from __future__ import annotations

from datetime import date, timedelta

from tickets.models import Ticket, TicketStatus, TicketStatusHistory

# The statuses that stop the clock. Named here rather than inline so the
# CSV, the PDF and the JSON cannot disagree about what "finished" means.
TERMINAL_STATUSES = (
    TicketStatus.APPROVED,
    TicketStatus.CLOSED,
    TicketStatus.REJECTED,
)


def _period(date_from: date, date_to: date) -> tuple[date, date]:
    return (date_from, date_to) if date_from <= date_to else (date_to, date_from)


def _scoped_tickets(user, date_from: date, date_to: date, scope=None):
    """The tickets of the period the actor may read, optionally narrowed.

    One function, so the report and its summary card cannot be looking at
    two different sets of tickets.
    """
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


def _first_terminal_by_ticket(ticket_ids) -> dict:
    """`{ticket_id: when it FIRST reached a terminal status}`.

    ONE query for every relevant transition, then bucketed in Python. A
    per-ticket history lookup would be the N+1 the query-count test
    exists to catch. Shared by the report and its summary so "finished"
    means one thing.
    """
    first_terminal: dict[int, object] = {}
    if not ticket_ids:
        return first_terminal
    history = (
        TicketStatusHistory.objects.filter(
            ticket_id__in=ticket_ids,
            new_status__in=TERMINAL_STATUSES,
        )
        .values_list("ticket_id", "created_at")
        .order_by("created_at")
    )
    for ticket_id, changed_at in history:
        # FIRST arrival wins — see the module docstring. `order_by` makes
        # the first one seen the earliest.
        first_terminal.setdefault(ticket_id, changed_at)
    return first_terminal


def _duration_days(created_at, ended) -> int:
    """Whole days, floor. Half a day is not a unit anybody in this
    business talks in, and rounding up would make every same-day ticket
    read as "1 day"."""
    return max(0, (ended.date() - created_at.date()).days)


def build_ticket_report(user, date_from: date, date_to: date, scope=None):
    """One row per ticket created in the period, with its duration."""
    date_from, date_to = _period(date_from, date_to)

    tickets = list(
        _scoped_tickets(user, date_from, date_to, scope)
        .select_related("building", "customer")
        .order_by("-created_at")
    )
    first_terminal = _first_terminal_by_ticket([ticket.id for ticket in tickets])

    rows = []
    finished = 0
    total_days = 0
    for ticket in tickets:
        ended = first_terminal.get(ticket.id)
        duration_days = None
        if ended is not None:
            duration_days = _duration_days(ticket.created_at, ended)
            finished += 1
            total_days += duration_days
        rows.append(
            {
                "id": ticket.id,
                "ticket_no": ticket.ticket_no,
                "title": ticket.title,
                "status": ticket.status,
                "building": ticket.building_id,
                "building_name": ticket.building.name if ticket.building_id else None,
                "customer": ticket.customer_id,
                "customer_name": (
                    ticket.customer.name if ticket.customer_id else None
                ),
                "created_at": ticket.created_at.isoformat(),
                "finished_at": ended.isoformat() if ended is not None else None,
                "duration_days": duration_days,
            }
        )

    return {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "rows": rows,
        "total": len(rows),
        "finished": finished,
        # None rather than 0 when nothing finished: an average of zero
        # days would read as "everything was instant".
        "average_duration_days": (
            round(total_days / finished, 1) if finished else None
        ),
    }


def build_ticket_report_summary(user, date_from: date, date_to: date, scope=None):
    """The three figures the ticket card shows, without the rows.

    Sprint 180 §2. The same two queries the full report costs, but it
    fetches two columns instead of joining the building and the customer
    and building a dict per ticket — a summary that loads on every visit
    to the Reports page has no business dragging the whole table across.

    It shares `_scoped_tickets`, `_first_terminal_by_ticket` and
    `_duration_days` with the report, so the card and the report it opens
    cannot report a different number of finished tickets.
    """
    date_from, date_to = _period(date_from, date_to)

    rows = list(
        _scoped_tickets(user, date_from, date_to, scope).values_list(
            "id", "created_at"
        )
    )
    first_terminal = _first_terminal_by_ticket([row[0] for row in rows])

    finished = 0
    total_days = 0
    for ticket_id, created_at in rows:
        ended = first_terminal.get(ticket_id)
        if ended is None:
            continue
        finished += 1
        total_days += _duration_days(created_at, ended)

    return {
        "total": len(rows),
        "finished": finished,
        "open": len(rows) - finished,
        # None rather than 0 when nothing finished, exactly as the report
        # does: an average of zero days would read as "everything was
        # instant".
        "average_duration_days": (
            round(total_days / finished, 1) if finished else None
        ),
    }


def default_period() -> tuple[date, date]:
    from django.utils import timezone

    today = timezone.localdate()
    return today - timedelta(days=27), today
