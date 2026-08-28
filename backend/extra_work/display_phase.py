"""
FE-2 (Addendum D §D.4) — the ONE phase a meerwerk is in, per viewer.

The customer follows one object through one lifecycle. Internally that
lifecycle is spread over four facts — the request's status, its routing
decision, its intent, and the spawned ticket's status — and every
screen that re-derived a "phase" from them found a different answer.
This module is the single derivation. It is PRESENTATION ONLY:

  * computed, never stored (zero migrations);
  * never writable (serialized through a SerializerMethodField);
  * never read by backend logic — no selector, no state machine, no
    task may import it for a decision. It exists for screens.

The mapping is EXHAUSTIVE AND CLOSED. `display_phase()` raises on any
combination it does not recognise, and the test suite iterates the full
cross product of inputs so an unmapped combination fails a test rather
than falling through silently. Adding an ExtraWorkStatus value without
extending this mapping is a red test, not a blank banner.

Phase vocabulary (§D.4, presentation enum — NOT a status):

  WAITING_PRICE               the provider owes a price
  WAITING_YOUR_APPROVAL       (customer viewer) the quote waits on YOU
  WAITING_CUSTOMER_APPROVAL   (provider viewer) same state, their side
  SCHEDULED                   agreed; work exists or is being created,
                              nobody has started
  IN_EXECUTION                somebody is doing the work
  WAITING_COMPLETION_APPROVAL the finished work waits on the customer
  DONE                        finished and confirmed
  INVOICED                    finished and on an invoice
  REJECTED                    the customer said no
  CANCELLED                   called off
"""
from __future__ import annotations

from tickets.models import TicketStatus

from .models import (
    ExtraWorkRequestIntent,
    ExtraWorkRoutingDecision,
    ExtraWorkStatus,
)

PHASE_WAITING_PRICE = "WAITING_PRICE"
PHASE_WAITING_YOUR_APPROVAL = "WAITING_YOUR_APPROVAL"
PHASE_WAITING_CUSTOMER_APPROVAL = "WAITING_CUSTOMER_APPROVAL"
PHASE_SCHEDULED = "SCHEDULED"
PHASE_IN_EXECUTION = "IN_EXECUTION"
PHASE_WAITING_COMPLETION_APPROVAL = "WAITING_COMPLETION_APPROVAL"
PHASE_DONE = "DONE"
PHASE_INVOICED = "INVOICED"
PHASE_REJECTED = "REJECTED"
PHASE_CANCELLED = "CANCELLED"

#: Every value `display_phase` may return. The exhaustiveness test
#: asserts membership for the full input cross product.
EXTRA_WORK_PHASES = frozenset(
    {
        PHASE_WAITING_PRICE,
        PHASE_WAITING_YOUR_APPROVAL,
        PHASE_WAITING_CUSTOMER_APPROVAL,
        PHASE_SCHEDULED,
        PHASE_IN_EXECUTION,
        PHASE_WAITING_COMPLETION_APPROVAL,
        PHASE_DONE,
        PHASE_INVOICED,
        PHASE_REJECTED,
        PHASE_CANCELLED,
    }
)


def display_phase(
    *,
    status: str,
    routing_decision: str | None,
    request_intent: str | None,
    ticket_status: str | None,
    is_invoiced: bool,
    viewer_is_customer: bool,
) -> str:
    """The phase for one (request, spawned ticket, viewer) reading.

    `ticket_status` is the status of THE spawned operational ticket
    (one per request by design, lowest id where legacy data holds
    more), or None when none exists. Every argument is a plain value so
    the function is testable without a database row.
    """
    if status == ExtraWorkStatus.CANCELLED:
        return PHASE_CANCELLED
    if status == ExtraWorkStatus.CUSTOMER_REJECTED:
        return PHASE_REJECTED
    if status == ExtraWorkStatus.COMPLETED:
        return PHASE_INVOICED if is_invoiced else PHASE_DONE

    if status == ExtraWorkStatus.IN_PROGRESS:
        # The completion chain runs on the ticket. The one state the
        # CUSTOMER must act on is the finished work sitting at
        # WAITING_CUSTOMER_APPROVAL; the internal manager check before
        # it is execution as far as the requester is concerned.
        if ticket_status == TicketStatus.WAITING_CUSTOMER_APPROVAL:
            return PHASE_WAITING_COMPLETION_APPROVAL
        return PHASE_IN_EXECUTION

    if status == ExtraWorkStatus.CUSTOMER_APPROVED:
        # Agreed. The ticket exists (or is being created); until it
        # moves to IN_PROGRESS the parent stays CUSTOMER_APPROVED, so
        # this whole state reads as "scheduled".
        return PHASE_SCHEDULED

    if status == ExtraWorkStatus.PRICING_PROPOSED:
        # A price exists. Who is being waited on depends on the intent:
        # AUTO_START_AFTER_PRICING never returns to the customer (SoT
        # §5.3 — "It does NOT go back to customer approval"), so the
        # only honest reading is "about to be scheduled". Every other
        # intent waits on the customer's decision.
        if request_intent == ExtraWorkRequestIntent.AUTO_START_AFTER_PRICING:
            return PHASE_SCHEDULED
        return (
            PHASE_WAITING_YOUR_APPROVAL
            if viewer_is_customer
            else PHASE_WAITING_CUSTOMER_APPROVAL
        )

    if status in (ExtraWorkStatus.REQUESTED, ExtraWorkStatus.UNDER_REVIEW):
        # An all-agreed cart routes INSTANT: approved by construction,
        # the spawn is immediate (a REQUESTED+INSTANT row is the spawn
        # mid-flight or a spawn that needs a retry — either way it is
        # agreed work being scheduled, not a price question).
        if (
            status == ExtraWorkStatus.REQUESTED
            and routing_decision == ExtraWorkRoutingDecision.INSTANT
        ):
            return PHASE_SCHEDULED
        return PHASE_WAITING_PRICE

    raise ValueError(f"Unmapped extra-work state: {status!r}")
