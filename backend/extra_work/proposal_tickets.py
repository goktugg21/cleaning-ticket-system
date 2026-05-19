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

Sprint 30 Batch 30.1 — legacy pricing-flow ticket spawn
-------------------------------------------------------
`spawn_tickets_for_extra_work_request(ew, actor)` mirrors the shape
of `extra_work.instant_tickets.spawn_tickets_for_request` but is
invoked AFTER a `PRICING_PROPOSED -> CUSTOMER_APPROVED` transition
(customer-driven OR provider-overridden) on an EW that has at least
one `ExtraWorkPricingLineItem` (the legacy pricing flow) and zero
`Proposal` rows. Tickets are spawned one-per-`ExtraWorkRequestItem`
(cart line) and link back via the existing
`Ticket.extra_work_request_item` FK so the parent-EW auto-sync hook
in `tickets.state_machine.apply_transition` already drives the
operational segment (CUSTOMER_APPROVED -> IN_PROGRESS -> COMPLETED).

Idempotent on the `extra_work_request_item` FK existence check;
defensive precondition mirrors the proposal-flow helper above.
Errors propagate so a partial spawn rolls every side effect back
together via the surrounding `apply_transition` atomic block.
"""
from __future__ import annotations

from typing import List

from tickets.models import (
    Ticket,
    TicketPriority,
    TicketStatus,
    TicketStatusHistory,
)

from .models import (
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkStatus,
    Proposal,
    ProposalLine,
    ProposalStatus,
)
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


# ---------------------------------------------------------------------------
# Sprint 30 Batch 30.1 — legacy pricing-flow spawn
# ---------------------------------------------------------------------------
def _build_ew_title(item: ExtraWorkRequestItem, *, fallback_title: str) -> str:
    """Derive a Ticket title from a cart line, falling back to the
    parent EW title when the cart line has no Service link (legacy
    backfill row)."""
    if item.service is not None:
        return f"{item.service.name} × {item.quantity}"
    if fallback_title.strip():
        return f"{fallback_title.strip()} × {item.quantity}"
    return f"Extra work line × {item.quantity}"


def _build_ew_description(
    ew: ExtraWorkRequest, item: ExtraWorkRequestItem
) -> str:
    """Compose a readable Ticket description for a legacy-flow spawn.

    Sections (dropped if blank):
      1. Parent EW `description`.
      2. Line-level `customer_note`.
      3. `Service.description` if the cart line has a Service link.

    Mirrors `instant_tickets._build_description` so legacy-pricing
    and instant-route tickets read identically on the operational
    timeline.
    """
    parts: List[str] = []
    if ew.description and ew.description.strip():
        parts.append(ew.description.strip())
    if item.customer_note and item.customer_note.strip():
        parts.append(f"Line note: {item.customer_note.strip()}")
    if (
        item.service is not None
        and item.service.description
        and item.service.description.strip()
    ):
        parts.append(f"Service: {item.service.description.strip()}")
    return "\n\n".join(parts)


def spawn_tickets_for_extra_work_request(
    ew: ExtraWorkRequest, *, actor
) -> List[Ticket]:
    """
    Sprint 30 Batch 30.1 — legacy pricing-flow ticket spawn.

    Invoked from `extra_work.state_machine.apply_transition` AFTER
    the EW lands in `CUSTOMER_APPROVED` via the legacy pricing path
    (`PRICING_PROPOSED -> CUSTOMER_APPROVED`, customer-driven OR
    provider-overridden). Spawns one `tickets.Ticket` per
    `ExtraWorkRequestItem` (cart line) on the request and links each
    Ticket back via `extra_work_request_item` so the existing
    parent-EW auto-sync hook in
    `tickets.state_machine.apply_transition` can drive the
    operational segment (CUSTOMER_APPROVED -> IN_PROGRESS ->
    COMPLETED) when the spawned tickets start moving.

    Caller MUST hold an active transaction so a mid-loop failure
    rolls every side effect back together. `apply_transition` is
    already `@transaction.atomic`-wrapped.

    Idempotent: items whose `Ticket.objects.filter(
    extra_work_request_item=item).exists()` is True are skipped.
    Re-running returns an empty list. Used by the retry endpoint
    `POST /api/extra-work/<id>/spawn/` to recover stuck EWs that
    were customer-approved before this fix shipped.

    Defensive precondition: raises `TransitionError` with code
    `ew_spawn_wrong_status` when called on an EW not in
    CUSTOMER_APPROVED. Mirrors the
    `instant_spawn_wrong_routing` guard.
    """
    from .state_machine import TransitionError as EwTransitionError

    if ew.status != ExtraWorkStatus.CUSTOMER_APPROVED:
        raise EwTransitionError(
            "spawn_tickets_for_extra_work_request called on an EW not "
            f"in CUSTOMER_APPROVED (current={ew.status!r}).",
            code="ew_spawn_wrong_status",
        )

    created: List[Ticket] = []
    items = list(ew.line_items.all().order_by("id"))

    for item in items:
        if Ticket.objects.filter(extra_work_request_item=item).exists():
            # Idempotency — already spawned (e.g. an INSTANT-route row
            # being retried, or a manual re-fire of the retry endpoint).
            continue

        ticket = Ticket.objects.create(
            company=ew.company,
            building=ew.building,
            customer=ew.customer,
            created_by=actor,
            title=_build_ew_title(item, fallback_title=ew.title),
            description=_build_ew_description(ew, item),
            priority=TicketPriority.NORMAL,
            status=TicketStatus.OPEN,
            extra_work_request_item=item,
        )

        TicketStatusHistory.objects.create(
            ticket=ticket,
            old_status="",
            new_status=TicketStatus.OPEN,
            changed_by=actor,
            note="Spawned from approved Extra Work request (legacy pricing flow).",
            is_override=False,
            override_reason="",
        )

        created.append(ticket)

    return created
