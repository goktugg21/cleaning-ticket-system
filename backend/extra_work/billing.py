"""M4 — shared billing-month logic for the Extra Work invoice run.

The month an EW bills in is the provider-set invoice_date if present,
else the spawned operational ticket's completion date (closed_at). This
is deliberately DECOUPLED from customer_decided_at (final approval): work
done May 31 but approved Jun 7 still bills in May. "Earned" mirrors the
revenue report: the spawned operational ticket (Ticket.extra_work_request)
is CLOSED.
"""
from __future__ import annotations

from django.utils import timezone

from tickets.models import Ticket, TicketStatus


def build_ticket_map(ew_ids):
    """ew_id -> spawned operational ticket (lowest-id per EW), mirroring
    reports.dimensions. Loads only the fields the run needs."""
    tickets_by_ew: dict = {}
    if ew_ids:
        for t in (
            Ticket.objects.filter(
                extra_work_request_id__in=ew_ids, deleted_at__isnull=True
            )
            .only("id", "status", "closed_at", "extra_work_request_id")
            .order_by("id")
        ):
            tickets_by_ew.setdefault(t.extra_work_request_id, t)
    return tickets_by_ew


def is_earned(ticket) -> bool:
    """Work is done == the spawned operational ticket is CLOSED (mirrors
    reports.dimensions._classify_extra_work 'earned')."""
    return ticket is not None and ticket.status == TicketStatus.CLOSED


def billing_month(ew, ticket):
    """(year, month) the EW bills in, or None if unresolvable.
    invoice_date (provider override) wins; otherwise ticket.closed_at."""
    if ew.invoice_date is not None:
        return (ew.invoice_date.year, ew.invoice_date.month)
    if ticket is not None and ticket.closed_at is not None:
        # #109 Part C (audit P3-1) — bucket on the Europe/Amsterdam
        # LOCAL date, not the UTC date. A ticket closed 00:30 local on
        # the 1st is 22:30/23:30 UTC on the previous day; naive .date()
        # on the UTC value would bill it a month early.
        d = timezone.localtime(ticket.closed_at).date()
        return (d.year, d.month)
    return None
