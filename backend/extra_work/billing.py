"""M4 — shared billing-month logic for the Extra Work invoice run.

The month an EW bills in is the provider-set invoice_date if present,
else the moment the work became EARNED (`earned_at`). This is
deliberately DECOUPLED from customer_decided_at (final approval): work
done May 31 but approved Jun 7 still bills in May.

Sprint W1-B (item 14, "the billing cutoff") — WHAT "EARNED" MEANS NOW
--------------------------------------------------------------------
Until this sprint "earned" was exactly one thing: the spawned
operational ticket (`Ticket.extra_work_request`) is CLOSED. And CLOSED
is reachable ONLY from APPROVED, which is reachable ONLY from
WAITING_CUSTOMER_APPROVAL (`tickets/state_machine.py`
ALLOWED_TRANSITIONS). So work the customer had not yet approved was not
merely dated wrong — it was **excluded from the billing pool
entirely**, and `invoice_date` could not rescue it, because
`invoice_date` only relocates the month of work that is already earned.

The owner's case, in the owner's words: the customer bills on 30
August, the work is completed 29 August, the customer approves on 4
September. The August run misses it and it turns up in September
attached to work that was really done in August.

So there is a SECOND arm: work is also earned when its ticket sits at
WAITING_CUSTOMER_APPROVAL with `sent_for_approval_at` stamped — that
timestamp is written by `TIMESTAMP_ON_ENTER[WAITING_CUSTOMER_APPROVAL]`
and is the moment the provider handed the finished work to the customer.

WHERE THE CUTOFF ITSELF LIVES
-----------------------------
Nowhere in this module, and that is deliberate. The rule is "sent for
approval on or before the customer's billing cutoff", and the invoice
run is what supplies the cutoff: `invoicing.tasks.run_daily_invoice_run`
fires on `schedule.is_billing_day` — the customer's cutoff day — and
asks for everything billable in this period OR EARLIER
(`unbilled_extra_work_through`). Work sent for approval on or before
that day has a resolved billing month at or before that period and is
swept in; work sent for approval after it does not exist yet when the
run reads the pool, and is swept by the NEXT run instead. The cutoff
comparison therefore falls out of WHEN the run happens, exactly, with
no second copy of the schedule rule to drift from
`invoicing/schedule.py`.

A customer with no billing schedule set is never automatically
invoiced (`is_billing_day` is False for them), so the cutoff arm simply
never fires for them through the run; a hand-driven `generate` for an
explicit period still picks their work up on the same rule.

WAITING_MANAGER_REVIEW MUST NEVER QUALIFY
-----------------------------------------
That state is staff saying "done" with nobody having checked it.
Billing it would bill unverified work. It is not in either arm below
and it must not be added to one — the guard is the whole point of the
change, not a detail of it.

The rejection case needs nothing new: a SENT invoice is immutable, and
reversal releases the Extra Work back to the unbilled pool via
`invoice__reversed_by__isnull=True` in `invoicing/selectors.py`. Reject
after billing -> reverse, credit note, the work returns for the next
cycle.

`reports.dimensions._classify_extra_work` classifies the same "earned"
and calls `is_earned` rather than re-testing the status, so revenue
reporting and billing cannot diverge.
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
            # `sent_for_approval_at` joined the list with the cutoff arm
            # of `is_earned` / `earned_at`. Leaving it out would not fail
            # — Django would fetch it lazily — it would issue one extra
            # query PER ROW inside the invoice run's pool loop.
            .only(
                "id",
                "status",
                "closed_at",
                "sent_for_approval_at",
                "extra_work_request_id",
            )
            .order_by("id")
        ):
            tickets_by_ew.setdefault(t.extra_work_request_id, t)
    return tickets_by_ew


def earned_at(ticket):
    """The moment the work became earned, or None.

    The ONE anchor. `billing_month` buckets on it, `invoicing.services`
    stamps `InvoiceLine.performed_on` from it, and the Extra Work
    revenue report prints it as "Completed At" — three readings of one
    date instead of three copies of the rule.

    WAITING_CUSTOMER_APPROVAL prefers `sent_for_approval_at` over
    `closed_at` rather than falling back to it. A ticket that was closed,
    reopened by an admin and worked again carries a STALE `closed_at`
    from the first pass; the date that matters for the second pass is
    when this pass was handed to the customer. Every other status keeps
    reading `closed_at` exactly as it always did.
    """
    if ticket is None:
        return None
    if str(ticket.status) == str(TicketStatus.WAITING_CUSTOMER_APPROVAL):
        return ticket.sent_for_approval_at
    return ticket.closed_at


def is_earned(ticket) -> bool:
    """Is the operational side of this work finished enough to bill?

    Two arms, and only two (see the module docstring):

      * the spawned ticket is CLOSED — the original rule, unchanged,
        status-only. It does NOT additionally require `closed_at`: an
        earned-but-unresolvable row has always been possible and
        `invoicing.selectors.unbilled_extra_work_through` already guards
        for it. Tightening it here would silently drop legacy rows.
      * the spawned ticket is at WAITING_CUSTOMER_APPROVAL and
        `sent_for_approval_at` is stamped — the cutoff arm. The
        timestamp IS required here, because without it there is no date
        to bill against; a NULL means the row never went through the
        transition (a hand-set fixture or a legacy row) rather than that
        it happened at an unknown time. Same reading
        `TicketFilter.awaiting_customer_approval_days` takes.

    WAITING_MANAGER_REVIEW is in neither arm and must stay out of both.
    """
    if ticket is None:
        return False
    if str(ticket.status) == str(TicketStatus.CLOSED):
        return True
    if str(ticket.status) == str(TicketStatus.WAITING_CUSTOMER_APPROVAL):
        return ticket.sent_for_approval_at is not None
    return False

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

    `invoice_date` (the provider override) wins; otherwise the month the
    work became earned (`earned_at`) — `closed_at` for a closed ticket,
    `sent_for_approval_at` for one sitting at WAITING_CUSTOMER_APPROVAL
    under the cutoff arm. Both readings come from the same helper so the
    month can never disagree with `is_earned` about which date it is
    talking about.
    """
    if ew.invoice_date is not None:
        return (ew.invoice_date.year, ew.invoice_date.month)
    anchor = earned_at(ticket)
    if anchor is not None:
        # #109 Part C (audit P3-1) — bucket on the Europe/Amsterdam
        # LOCAL date, not the UTC date. A ticket closed 00:30 local on
        # the 1st is 22:30/23:30 UTC on the previous day; naive .date()
        # on the UTC value would bill it a month early.
        d = timezone.localtime(anchor).date()
        return (d.year, d.month)
    return None
