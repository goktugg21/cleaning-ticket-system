"""
Sprint 28 Batch 8 — proposal approval -> ticket spawn service.

When a `Proposal` lands in `CUSTOMER_APPROVED` (customer-driven OR
provider-overridden approval), one operational `tickets.Ticket` is
spawned per `ProposalLine` that has `is_approved_for_spawn=True`
and does not already have a spawned Ticket. The customer's per-line
`customer_explanation` is composed into the ticket description; the
provider-only `internal_note` is NEVER copied into the customer-
facing Ticket text.

Contract:
  * **Caller MUST hold an active transaction.**
    `apply_proposal_transition` already wraps in `transaction.atomic`,
    so a partial spawn rolls every side effect back together.
  * **Idempotent.** A line whose `Ticket.objects.filter(
    proposal_line=line).exists()` is True is skipped. Re-running on
    the same proposal returns an empty list.
  * **Per-line opt-out honoured.** Lines with
    `is_approved_for_spawn=False` are skipped (forward-compat for
    per-line UX).
  * **Defensive precondition.** Raises if the caller passes a
    proposal whose `status != CUSTOMER_APPROVED` — that signals a
    caller bug.
"""
from __future__ import annotations

from typing import List

from tickets.models import (
    Ticket,
    TicketPriority,
    TicketStatus,
    TicketStatusHistory,
)

from .models import Proposal, ProposalLine, ProposalStatus
from .proposal_state_machine import TransitionError


def _build_proposal_title(line: ProposalLine) -> str:
    """Derive a Ticket title from a proposal line.

    Prefer the catalog `service.name`, fall back to the line's own
    `description`, and finally a generic placeholder. Mirrors the
    line `__str__` shape.
    """
    if line.service is not None:
        return f"{line.service.name} × {line.quantity}"
    if (line.description or "").strip():
        return f"{line.description.strip()} × {line.quantity}"
    return f"Extra work line × {line.quantity}"


def _build_proposal_description(
    request, line: ProposalLine
) -> str:
    """Compose a Ticket description from the parent EW + line.

    Sections (in order, dropped if blank):
      1. The parent request's `description`.
      2. The line's `customer_explanation` (customer-visible).

    The provider-only `internal_note` is NEVER included — that is
    the H-11 / spec §6 "dual note privacy" guarantee.
    """
    parts: List[str] = []
    if request.description and request.description.strip():
        parts.append(request.description.strip())
    if line.customer_explanation and line.customer_explanation.strip():
        parts.append(
            f"Proposal explanation: {line.customer_explanation.strip()}"
        )
    return "\n\n".join(parts)


def spawn_tickets_for_proposal(
    proposal: Proposal, *, actor
) -> List[Ticket]:
    """
    Spawn one operational Ticket per approved-for-spawn ProposalLine
    on a CUSTOMER_APPROVED proposal. Idempotent (skips lines whose
    Ticket already exists). Returns the list of created Tickets.

    Caller MUST hold an active transaction so a mid-loop failure
    rolls every side effect back together.
    """
    if proposal.status != ProposalStatus.CUSTOMER_APPROVED:
        raise TransitionError(
            "spawn_tickets_for_proposal called on a proposal not in "
            f"CUSTOMER_APPROVED (current={proposal.status!r}).",
            code="proposal_spawn_wrong_status",
        )

    request = proposal.extra_work_request
    created: List[Ticket] = []

    lines = list(proposal.lines.all().order_by("id"))
    for line in lines:
        if not line.is_approved_for_spawn:
            # Forward-compat: per-line approval slot is False, do not
            # spawn for this line (nothing in Batch 8 flips it; UI
            # to mark False lands in a follow-up).
            continue
        if Ticket.objects.filter(proposal_line=line).exists():
            # Idempotency — already spawned on a previous call.
            continue

        ticket = Ticket.objects.create(
            company=request.company,
            building=request.building,
            customer=request.customer,
            created_by=actor,
            title=_build_proposal_title(line),
            description=_build_proposal_description(request, line),
            priority=TicketPriority.NORMAL,
            status=TicketStatus.OPEN,
            proposal_line=line,
        )

        TicketStatusHistory.objects.create(
            ticket=ticket,
            old_status="",
            new_status=TicketStatus.OPEN,
            changed_by=actor,
            note="Spawned from approved Extra Work proposal.",
            is_override=False,
            override_reason="",
        )

        created.append(ticket)

    return created
