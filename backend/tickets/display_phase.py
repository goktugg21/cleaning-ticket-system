"""
FE-2 (Addendum D §D.4) — the customer-facing phase of a ticket.

The melding surface answers one question: where is my report? Eleven
workflow statuses collapse onto six phase words a customer can read.
Presentation only — computed, never stored, never writable, never read
by backend logic. Same closed-mapping rule as
`extra_work/display_phase.py`: an unmapped status raises, and the test
suite iterates every TicketStatus so a new status fails a test rather
than rendering a blank banner.

  RECEIVED                    we have it, nobody has planned it yet
  PLANNED                     seen and scheduled, work not started
  IN_EXECUTION                being carried out (incl. our own checks)
  WAITING_YOUR_APPROVAL       (customer) the finished work waits on YOU
  WAITING_CUSTOMER_APPROVAL   (provider) same state, their side
  WAITING_MANAGER_CHECK       (provider) the worker reported it done and
                              a manager has not checked it -- P-3: the
                              manager reads the truth ("Gemeld als klaar
                              -- wacht op uw controle"); the customer
                              keeps "being carried out" for the same
                              status, because the provider's own
                              double-check is not a phase they wait on
  DONE                        finished and confirmed
  REJECTED                    rejected
  CONVERTED                   continued as a meerwerk
"""
from __future__ import annotations

from .models import TicketStatus

TICKET_PHASE_RECEIVED = "RECEIVED"
TICKET_PHASE_PLANNED = "PLANNED"
TICKET_PHASE_IN_EXECUTION = "IN_EXECUTION"
TICKET_PHASE_WAITING_YOUR_APPROVAL = "WAITING_YOUR_APPROVAL"
TICKET_PHASE_WAITING_CUSTOMER_APPROVAL = "WAITING_CUSTOMER_APPROVAL"
TICKET_PHASE_WAITING_MANAGER_CHECK = "WAITING_MANAGER_CHECK"
TICKET_PHASE_DONE = "DONE"
TICKET_PHASE_REJECTED = "REJECTED"
TICKET_PHASE_CONVERTED = "CONVERTED"

TICKET_PHASES = frozenset(
    {
        TICKET_PHASE_RECEIVED,
        TICKET_PHASE_PLANNED,
        TICKET_PHASE_IN_EXECUTION,
        TICKET_PHASE_WAITING_YOUR_APPROVAL,
        TICKET_PHASE_WAITING_CUSTOMER_APPROVAL,
        TICKET_PHASE_WAITING_MANAGER_CHECK,
        TICKET_PHASE_DONE,
        TICKET_PHASE_REJECTED,
        TICKET_PHASE_CONVERTED,
    }
)


def ticket_display_phase(*, status: str, viewer_is_customer: bool) -> str:
    if status == TicketStatus.OPEN:
        return TICKET_PHASE_RECEIVED
    if status == TicketStatus.ACKNOWLEDGED:
        return TICKET_PHASE_PLANNED
    if status == TicketStatus.WAITING_MANAGER_REVIEW:
        # P-3 — TWO READERS, TWO TRUTHS. The customer reads "wordt
        # uitgevoerd": the manager's check is the provider's own
        # double-check, not a phase the customer waits on. The provider
        # reads what is actually true — the worker says it is done and
        # nobody on their side has confirmed it — because "being carried
        # out" on the manager's own screen hid the one step that was
        # theirs to take (the billing chain breaks exactly there, §D.11
        # G4).
        return (
            TICKET_PHASE_IN_EXECUTION
            if viewer_is_customer
            else TICKET_PHASE_WAITING_MANAGER_CHECK
        )
    if status in (
        TicketStatus.IN_PROGRESS,
        # A pause or a redo — from the requester's chair both are
        # "wordt uitgevoerd".
        TicketStatus.ON_HOLD,
        TicketStatus.REOPENED_BY_ADMIN,
    ):
        return TICKET_PHASE_IN_EXECUTION
    if status == TicketStatus.WAITING_CUSTOMER_APPROVAL:
        return (
            TICKET_PHASE_WAITING_YOUR_APPROVAL
            if viewer_is_customer
            else TICKET_PHASE_WAITING_CUSTOMER_APPROVAL
        )
    if status in (TicketStatus.APPROVED, TicketStatus.CLOSED):
        return TICKET_PHASE_DONE
    if status == TicketStatus.REJECTED:
        return TICKET_PHASE_REJECTED
    if status == TicketStatus.CONVERTED_TO_EXTRA_WORK:
        return TICKET_PHASE_CONVERTED
    raise ValueError(f"Unmapped ticket status: {status!r}")
