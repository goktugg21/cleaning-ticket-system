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

from .models import ExtraWorkStatus


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


#: Sprint 182 §3 — statuses that mean "this was called off". An extra
#: work in one of these is not billable no matter what its ticket says.
#:
#: CANCELLED and CUSTOMER_REJECTED are the two ways an extra work stops
#: being work anybody agreed to. `reports.dimensions` already groups
#: exactly this pair as `_EW_TERMINAL_NO_TICKET_LOST`; the same two, for
#: the same reason.
NON_BILLABLE_STATUSES = frozenset(
    {
        ExtraWorkStatus.CANCELLED,
        ExtraWorkStatus.CUSTOMER_REJECTED,
    }
)


def is_billable(ew, ticket) -> bool:
    """Sprint 182 §3 — may this extra work go on an invoice at all?

    **`invoicing.selectors.unbilled_extra_work` must call this**, and as
    of this sprint it does not: it filters on company, customer,
    `deleted_at`, `is_invoiced` and the live-claim predicate, and never
    once on the extra work's own status. Cancel an extra work, let its
    already-spawned ticket run on to CLOSED, and it walks straight into
    the unbilled pool — you would invoice a customer for work you told
    them was cancelled. The selector file belongs to Agent B this round,
    so the predicate lives here and Agent B wires it in.

    TWO conditions, and they are different questions:

      * the extra work was not called off — a CANCELLED or
        CUSTOMER_REJECTED row is not billable however its ticket ended,
        because the ticket only records what was DONE and this records
        whether it was ever OWED;
      * the work is finished — `is_earned`, which reads the ticket, per
        the owner's rule that the month-end job takes only extra works
        whose operational side is COMPLETED.

    Note what this does NOT decide: the AMOUNT. A zero-amount extra work
    is billable and the owner was explicit that it belongs on the
    invoice, written as zero rather than skipped — "nothing to charge
    for this one" is information the customer is owed, and a line that
    silently vanishes is not.

    Nor does it decide the MONTH (`billing_month`) or whether the row is
    already claimed (`is_invoiced` / the live-claim subquery). Those stay
    where they are; this is only the billable/not-billable half that was
    missing.
    """
    if ew.status in NON_BILLABLE_STATUSES:
        return False
    return is_earned(ticket)


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
