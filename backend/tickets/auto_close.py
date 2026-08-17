"""
Sprint 180 §1 — customer approval closes the ticket.

The owner's instruction: **when the customer approves the work, the
ticket becomes CLOSED automatically.**

Why this is a money bug and not a convenience
---------------------------------------------
The Extra Work auto-sync in `tickets/state_machine.py` treats
`{APPROVED, CLOSED}` as terminal, so an Extra Work advances to
COMPLETED as soon as its spawned tickets reach *either*. But
invoiceability (`extra_work/billing.py::is_earned`) demands CLOSED
**specifically**, and the billing month (`billing_month`) is read off
`ticket.closed_at`, which `TIMESTAMP_ON_ENTER[CLOSED]` is the only
writer of.

So before this module, an Extra Work could read "Completed" on screen,
be genuinely finished, and never become invoiceable — silently, with
nobody warned. Closing on customer approval closes most of that hole:
the approval leg is how finished work actually finishes.

What triggers the close
-----------------------
Exactly one leg: `WAITING_CUSTOMER_APPROVAL -> APPROVED`. That is *the*
customer-decision transition, whether the customer drove it themselves
or a provider operator recorded it on their behalf (the on-behalf route
already exists, already coerces `is_override=True`, and already demands
an `override_reason`; this module does not touch it and does not
rebuild it).

Any OTHER route into APPROVED — a SUPER_ADMIN correcting a stuck ticket
straight from OPEN, say — is NOT a customer approval and does NOT close.
That distinction is the whole point of keying on `old_status` rather
than on the destination alone.

Who the closing actor is
------------------------
Nobody: `changed_by=None`. The customer approved; the *system* closed.
Recording a CLOSED transition against a customer user who has no
authority to close would make the audit trail name a person for an
action they did not take. `tickets.models.TicketStatusHistory.changed_by`
is nullable for exactly this (see its comment), mirroring
`ExtraWorkStatusHistory.changed_by`.

Best-effort, never fatal
------------------------
`apply_transition` is `@transaction.atomic`. If the close failed *hard*
it would roll back the customer's approval too — losing the decision to
protect the bookkeeping. So a failure here is logged and swallowed: the
ticket stays APPROVED (exactly the pre-Sprint-180 behaviour) and a
provider admin can still close it by hand. Same contract as
`sub_task_rollup.maybe_auto_complete_ticket_on_subtasks` and the Extra
Work auto-sync hook.
"""
from __future__ import annotations

import logging

from .models import TicketStatus

logger = logging.getLogger(__name__)


# The note on the system-authored history row. It is what the timeline
# renders under "System", so it has to explain itself to a reader who
# has never heard of this module.
AUTO_CLOSE_NOTE = (
    "Closed automatically because the customer approved the completed work."
)


# Sprint 180 §1 (edge case: work the customer never responds to).
#
# A ticket sitting in WAITING_CUSTOMER_APPROVAL is, by definition, work
# that is DONE and unbillable — `is_earned` needs CLOSED and CLOSED is
# downstream of the approval. Auto-close fixes the case where the
# customer answers; it does nothing for the case where they never do,
# which is the case that stays invisible.
#
# We deliberately do NOT auto-approve on a timer. Approving on the
# customer's behalf is a decision with money attached and the system
# already has a route for it — the provider override, which demands a
# written reason and writes an audit row. Silently manufacturing that
# decision after N days would be H-11 territory (a workflow override
# with no operator and no reason).
#
# What we do instead is make it VISIBLE: `TicketFilter
# .awaiting_customer_approval_days` ages the queue, and the dashboard
# surfaces the count as an attention row that deep-links into it. The
# provider then chases the customer, or records the approval on their
# behalf through the existing reasoned override.
#
# 14 days is a default, not a rule: the filter takes any number of days,
# and the constant is only what the dashboard's attention row asks for.
STALLED_CUSTOMER_APPROVAL_DAYS = 14


def should_auto_close(ticket, old_status) -> bool:
    """
    True iff `ticket` just completed the customer-decision approval leg.

    Both halves matter:
      * `old_status` WAITING_CUSTOMER_APPROVAL — this was a customer
        decision, not an administrative correction;
      * current status APPROVED — the decision was "approve", not
        "reject".

    Deliberately NOT included:
      * REJECTED — rejected work goes back to IN_PROGRESS for rework.
        It is live work, and closing it would destroy the loop.
      * any other entry into APPROVED (e.g. a SUPER_ADMIN moving a
        ticket straight from OPEN) — no customer was involved, so
        there is no approval to close on. Such a ticket stays APPROVED
        and an admin closes it by hand exactly as before.
    """
    return (
        str(old_status) == str(TicketStatus.WAITING_CUSTOMER_APPROVAL)
        and str(ticket.status) == str(TicketStatus.APPROVED)
    )


def maybe_auto_close_after_customer_approval(ticket, old_status):
    """
    Best-effort `APPROVED -> CLOSED` after a customer approval.

    Returns the CLOSED ticket when it fired, otherwise the ticket
    unchanged — so the caller can simply return the result and every
    caller of `apply_transition` sees the ticket's true final state
    rather than an intermediate one.

    Called from the tail of `tickets.state_machine.apply_transition`,
    AFTER the Extra Work auto-sync hook. The ordering is load-bearing:
    the sync hook freezes `final_*` amounts on entry to APPROVED
    (Sprint 8B), and that freeze must happen while the ticket is still
    APPROVED. The nested `apply_transition` below re-runs the sync hook
    for the CLOSED leg, which is harmless — by then the parent Extra
    Work is no longer IN_PROGRESS, so rule 2 no-ops.

    No recursion risk: this fires only on entry to APPROVED, and the
    transition it drives enters CLOSED.
    """
    if not should_auto_close(ticket, old_status):
        return ticket

    # Imported here, not at module scope: `state_machine` imports THIS
    # module (lazily, from inside apply_transition) and importing it
    # back at module scope would close the cycle.
    from .state_machine import TransitionError, apply_transition

    try:
        return apply_transition(
            ticket,
            None,  # system actor — see the module docstring.
            TicketStatus.CLOSED,
            note=AUTO_CLOSE_NOTE,
        )
    except TransitionError as exc:
        # Swallowed on purpose: the customer's approval must survive a
        # failed close. The ticket stays APPROVED (pre-Sprint-180
        # behaviour) and remains closable by hand.
        logger.warning(
            "Sprint 180 auto-close skipped for ticket #%s: %s (code=%s)",
            getattr(ticket, "pk", None),
            exc,
            getattr(exc, "code", None),
        )
        return ticket
