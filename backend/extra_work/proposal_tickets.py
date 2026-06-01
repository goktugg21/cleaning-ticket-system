"""
Sprint 28 Batch 8 — proposal approval -> ticket spawn service.

When a `Proposal` lands in `CUSTOMER_APPROVED` (customer-driven OR
provider-overridden approval), EXACTLY ONE operational `tickets.Ticket`
is spawned for the parent `ExtraWorkRequest` (Sprint 6A — collapsed
from one-per-line), summarizing every `ProposalLine` that has
`is_approved_for_spawn=True`. The customer's per-line
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
    TicketScheduleStatus,
    TicketStatus,
    TicketStatusHistory,
)

from .instant_tickets import earliest_requested_start

from .models import (
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkStatus,
    Proposal,
    ProposalLine,
    ProposalStatus,
)
from .proposal_state_machine import TransitionError


def _proposal_line_summary(line: ProposalLine) -> str:
    """One-line human label for a proposal line. Mirrors the line's
    `__str__` shape."""
    if line.service is not None:
        return f"{line.service.name} × {line.quantity}"
    if (line.description or "").strip():
        return f"{line.description.strip()} × {line.quantity}"
    return f"Extra work line × {line.quantity}"


def _build_proposal_title(
    request, lines: List[ProposalLine]
) -> str:
    """Sprint 6A — derive ONE Ticket title summarizing the whole
    proposal. Prefer the parent request's title; if blank, derive from
    the first line; append a count suffix when more than one line."""
    base = (request.title or "").strip()
    if not base:
        base = _proposal_line_summary(lines[0]) if lines else "Extra work"
    if len(lines) > 1:
        base = f"{base} (+{len(lines) - 1} more)"
    return base


def _build_proposal_line_block(line: ProposalLine) -> str:
    """Per-line description block: line label + the customer-visible
    `customer_explanation`. The provider-only `internal_note` is NEVER
    included — that is the H-11 / spec §6 dual-note privacy guarantee.
    """
    parts: List[str] = [_proposal_line_summary(line)]
    if line.customer_explanation and line.customer_explanation.strip():
        parts.append(
            f"Proposal explanation: {line.customer_explanation.strip()}"
        )
    return "\n".join(parts)


def _build_proposal_description(
    request, lines: List[ProposalLine]
) -> str:
    """Sprint 6A — compose ONE Ticket description summarizing ALL
    approved-for-spawn proposal lines. The parent request description
    appears once at the top, then one block per line.

    The provider-only `internal_note` is NEVER included.
    """
    parts: List[str] = []
    if request.description and request.description.strip():
        parts.append(request.description.strip())
    for line in lines:
        parts.append(_build_proposal_line_block(line))
    return "\n\n".join(parts)


def spawn_tickets_for_proposal(
    proposal: Proposal, *, actor
) -> List[Ticket]:
    """
    Sprint 6A — spawn EXACTLY ONE operational Ticket for the parent
    ExtraWorkRequest of a CUSTOMER_APPROVED proposal, summarizing every
    `is_approved_for_spawn=True` line. The ticket links
    `extra_work_request` (CANONICAL) + `proposal_line` = the FIRST
    approved-for-spawn line (back-compat for the origin payload).

    Returns `[ticket]` when it creates the single ticket, or `[]` on an
    idempotent re-run (a ticket already exists for the request) OR when
    there are zero approved-for-spawn lines (nothing to spawn).

    Caller MUST hold an active transaction so a failure rolls every
    side effect back together.
    """
    if proposal.status != ProposalStatus.CUSTOMER_APPROVED:
        raise TransitionError(
            "spawn_tickets_for_proposal called on a proposal not in "
            f"CUSTOMER_APPROVED (current={proposal.status!r}).",
            code="proposal_spawn_wrong_status",
        )

    request = proposal.extra_work_request

    # Sprint 6A — request-level idempotency.
    if Ticket.objects.filter(extra_work_request=request).exists():
        return []

    spawn_lines = [
        line
        for line in proposal.lines.all().order_by("id")
        if line.is_approved_for_spawn
    ]
    if not spawn_lines:
        # No approved-for-spawn lines -> nothing to spawn.
        return []

    # Back-compat legacy link: FIRST approved-for-spawn line.
    first_line = spawn_lines[0]

    # Sprint 9B — seed the operational schedule from the EW's cart
    # `line_items` requested_date (NOT the proposal lines — ProposalLine
    # has no requested_date). None -> ticket stays UNSCHEDULED.
    seed_start = earliest_requested_start(request)
    seed_schedule_status = (
        TicketScheduleStatus.SCHEDULED
        if seed_start is not None
        else TicketScheduleStatus.UNSCHEDULED
    )

    ticket = Ticket.objects.create(
        company=request.company,
        building=request.building,
        customer=request.customer,
        created_by=actor,
        title=_build_proposal_title(request, spawn_lines),
        description=_build_proposal_description(request, spawn_lines),
        priority=TicketPriority.NORMAL,
        status=TicketStatus.OPEN,
        extra_work_request=request,
        proposal_line=first_line,
        scheduled_start_at=seed_start,
        schedule_status=seed_schedule_status,
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

    return [ticket]


# ---------------------------------------------------------------------------
# Sprint 30 Batch 30.1 — legacy pricing-flow spawn
# ---------------------------------------------------------------------------
def _ew_line_summary(item: ExtraWorkRequestItem) -> str:
    """One-line human label for a cart line."""
    if item.service is not None:
        return f"{item.service.name} × {item.quantity}"
    return f"Extra work line × {item.quantity}"


def _build_ew_title(
    ew: ExtraWorkRequest, items: List[ExtraWorkRequestItem]
) -> str:
    """Sprint 6A — derive ONE Ticket title summarizing the whole
    request. Prefer the parent EW title; if blank, derive from the
    first line; append a count suffix when more than one line."""
    base = (ew.title or "").strip()
    if not base:
        base = _ew_line_summary(items[0]) if items else "Extra work"
    if len(items) > 1:
        base = f"{base} (+{len(items) - 1} more)"
    return base


def _build_ew_line_block(item: ExtraWorkRequestItem) -> str:
    """Per-line description block: line label, customer_note, and the
    Service catalog description if linked."""
    parts: List[str] = [_ew_line_summary(item)]
    if item.customer_note and item.customer_note.strip():
        parts.append(f"Line note: {item.customer_note.strip()}")
    if (
        item.service is not None
        and item.service.description
        and item.service.description.strip()
    ):
        parts.append(f"Service: {item.service.description.strip()}")
    return "\n".join(parts)


def _build_ew_description(
    ew: ExtraWorkRequest, items: List[ExtraWorkRequestItem]
) -> str:
    """Sprint 6A — compose ONE Ticket description summarizing ALL cart
    lines. The parent EW description appears once at the top, then one
    block per line. Mirrors `instant_tickets._build_description` so
    legacy-pricing and instant-route tickets read identically.
    """
    parts: List[str] = []
    if ew.description and ew.description.strip():
        parts.append(ew.description.strip())
    for item in items:
        parts.append(_build_ew_line_block(item))
    return "\n\n".join(parts)


def spawn_tickets_for_extra_work_request(
    ew: ExtraWorkRequest, *, actor
) -> List[Ticket]:
    """
    Sprint 30 Batch 30.1 — legacy pricing-flow ticket spawn.

    Invoked from `extra_work.state_machine.apply_transition` AFTER
    the EW lands in `CUSTOMER_APPROVED` via the legacy pricing path
    (`PRICING_PROPOSED -> CUSTOMER_APPROVED`, customer-driven OR
    provider-overridden). Sprint 6A — spawns EXACTLY ONE
    `tickets.Ticket` for the whole request, summarizing all cart
    lines, linking `extra_work_request` (CANONICAL) +
    `extra_work_request_item` = the FIRST cart line (back-compat). The
    parent-EW auto-sync hook in `tickets.state_machine.apply_transition`
    drives the operational segment (CUSTOMER_APPROVED -> IN_PROGRESS ->
    COMPLETED) when the spawned ticket starts moving.

    Caller MUST hold an active transaction so a failure rolls every
    side effect back together. `apply_transition` is already
    `@transaction.atomic`-wrapped.

    Idempotent on `Ticket.objects.filter(extra_work_request=ew)`:
    returns `[ticket]` on a fresh spawn and `[]` on a re-run. Used by
    the retry endpoint `POST /api/extra-work/<id>/spawn/` to recover
    stuck EWs that were customer-approved before this fix shipped.

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

    # Sprint 6A — request-level idempotency. One ticket per request.
    if Ticket.objects.filter(extra_work_request=ew).exists():
        return []

    items = list(ew.line_items.all().order_by("id"))

    # Back-compat legacy link: FIRST cart line.
    first_item = items[0] if items else None

    # Sprint 9B — seed the operational schedule from the earliest cart
    # `line_items` requested_date. None -> ticket stays UNSCHEDULED.
    seed_start = earliest_requested_start(ew)
    seed_schedule_status = (
        TicketScheduleStatus.SCHEDULED
        if seed_start is not None
        else TicketScheduleStatus.UNSCHEDULED
    )

    ticket = Ticket.objects.create(
        company=ew.company,
        building=ew.building,
        customer=ew.customer,
        created_by=actor,
        title=_build_ew_title(ew, items),
        description=_build_ew_description(ew, items),
        priority=TicketPriority.NORMAL,
        status=TicketStatus.OPEN,
        extra_work_request=ew,
        extra_work_request_item=first_item,
        scheduled_start_at=seed_start,
        schedule_status=seed_schedule_status,
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

    return [ticket]
