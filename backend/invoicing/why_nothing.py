"""
Sprint 183 §2 — why there is nothing to invoice.

THE COMPLAINT
-------------
The owner: *"I cannot generate anything in Due now."* Investigated on
live crmtest and it is not a bug, which is exactly the problem:

  * B Amsterdam has 61 unbilled extra works and **0 of them finished** —
    every ticket is still OPEN, IN_PROGRESS or awaiting the customer.
  * 7 extra works do have a closed ticket, and **all 7 are already
    invoiced**.

So there genuinely is nothing to bill, and the screen expressed that by
doing nothing at all. Software that is working correctly and looks
broken is a defect in the explanation, not in the logic.

WHAT THIS MODULE DOES
---------------------
`diagnose_nothing_to_invoice` answers the question the empty result
raises: *which* kind of nothing is this? Four answers, each with the
count behind it so the operator can act on it:

  NO_EXTRA_WORK       there is no extra work for this customer/period at
                      all — nothing has been requested.
  NONE_FINISHED       there IS extra work, but none of it has reached a
                      closed ticket yet. This is the crmtest case, and
                      the honest sentence is "61 extra works, none
                      finished".
  ALL_INVOICED        everything finished has already been billed. The
                      screen is empty because the work is done, not
                      because something failed.
  NOTHING_TO_EXPLAIN  there IS billable work — the caller should not be
                      asking.

WHY IT IS A SEPARATE MODULE
---------------------------
Two callers need the same sentence: the `/due/` panel (where the
operator presses Generate) and the preview (where they look first). §2
says the same sentence belongs on both, and one function is the only way
to be sure it IS the same sentence rather than two that agree today.

It deliberately does NOT re-derive "billable". The counts come from the
same `_scoped_unbilled_ew_with_tickets` base the real pool uses, and
finishedness from `extra_work.billing.is_earned`. A diagnosis that
disagreed with the thing it is diagnosing would be worse than no
diagnosis.
"""
from __future__ import annotations

from extra_work.billing import is_earned

from .selectors import _scoped_unbilled_ew_with_tickets


NO_EXTRA_WORK = "NO_EXTRA_WORK"
NONE_FINISHED = "NONE_FINISHED"
ALL_INVOICED = "ALL_INVOICED"
# The brief named three reasons; investigating the code turned up a
# fourth. Finished, unclaimed work can still be unbillable in the asked
# period when a provider set an `invoice_date` in a later one. Calling
# that "already invoiced" would be a false statement about money, and
# "none finished" would contradict the finished count beside it.
NOT_IN_PERIOD = "NOT_IN_PERIOD"
NOTHING_TO_EXPLAIN = "NOTHING_TO_EXPLAIN"


def diagnose_nothing_to_invoice(
    actor, company_id, customer_id, *, billable_count
):
    """Why is there nothing to invoice for this customer?

    `billable_count` is what the caller's own pool query returned, passed
    in rather than recomputed so the diagnosis can never contradict the
    number on screen beside it.

    Returns a dict: `{"reason", "unbilled_count", "finished_count",
    "invoiced_count"}`. The counts are what make the sentence actionable
    — "none finished" is a shrug, "61 extra works, none finished" tells
    an operator to go and look at 61 tickets.
    """
    if billable_count:
        return {
            "reason": NOTHING_TO_EXPLAIN,
            "unbilled_count": billable_count,
            "finished_count": billable_count,
            "invoiced_count": 0,
        }

    # The UNCLAIMED pool — everything not yet invoiced, regardless of
    # whether it is finished. This is the same base the real pool query
    # builds on, so "61" here is the same 61 the operator would count by
    # hand on the Extra Work page.
    unclaimed, ticket_map = _scoped_unbilled_ew_with_tickets(
        actor, company_id, customer_id
    )
    unbilled_count = len(unclaimed)
    finished_count = sum(
        1 for ew in unclaimed if is_earned(ticket_map.get(ew.id))
    )

    # Everything already settled, counted separately because "all
    # invoiced" is a genuinely different situation from "nothing exists"
    # and the operator's next move differs: one means look at the
    # invoices, the other means look at the work.
    invoiced_count = _invoiced_count(actor, company_id, customer_id)

    if unbilled_count == 0:
        # Nothing unclaimed. Either everything was invoiced, or there
        # never was anything — a genuinely different situation, and the
        # operator's next move differs: look at the invoices, or look at
        # why no work was requested.
        reason = ALL_INVOICED if invoiced_count else NO_EXTRA_WORK
    elif finished_count == 0:
        # The crmtest case: plenty of extra work, none of it finished.
        reason = NONE_FINISHED
    else:
        # Finished AND unclaimed, and still not billable in the asked
        # period. The remaining way that happens is a provider-set
        # `invoice_date` in a LATER period, which deliberately holds the
        # row back.
        #
        # A fourth reason rather than squeezing it into one of the three
        # the brief named: calling this "already invoiced" would be a
        # false statement about money, and "none finished" would
        # contradict the finished_count sitting next to it.
        reason = NOT_IN_PERIOD

    return {
        "reason": reason,
        "unbilled_count": unbilled_count,
        "finished_count": finished_count,
        "invoiced_count": invoiced_count,
    }


def _invoiced_count(actor, company_id, customer_id) -> int:
    """How much of this customer's extra work is already on an invoice.

    Counted through the same tenant scope as everything else, so an
    actor can never learn the size of another tenant's book from a
    diagnosis message.
    """
    from extra_work.scoping import scope_extra_work_for

    return (
        scope_extra_work_for(actor)
        .filter(
            company_id=company_id,
            customer_id=customer_id,
            deleted_at__isnull=True,
            is_invoiced=True,
        )
        .count()
    )
