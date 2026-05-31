"""
Sprint 28 Batch 7 — instant-ticket spawn service.

When an `ExtraWorkRequest` is submitted and the cart routing decision
resolves to `INSTANT` (every line item has an active customer-specific
`CustomerServicePrice`), this module spawns EXACTLY ONE operational
`tickets.Ticket` for the whole request (Sprint 6A — collapsed from the
former one-ticket-per-line model) and drives the parent request from
`REQUESTED` straight to `CUSTOMER_APPROVED`. The customer's submission
IS the approval — no proposal phase is needed because the price is
already agreed by contract (master plan §6 Batch 7).

Contract:
  * **Caller MUST hold an active transaction.** The serializer's
    `ExtraWorkRequestCreateSerializer.create()` invokes us inside its
    existing `transaction.atomic()` block. We do not open a new one
    so a per-line abort rolls the whole submission (parent +
    line-items + tickets) back together.
  * **Idempotent.** A request that already has a spawned ticket
    (`Ticket.objects.filter(extra_work_request=request).exists()`) is
    a no-op that returns an empty list.
  * **Defensive abort.** Each line's `resolve_price()` is re-called at
    spawn time. If any line now returns `None` (a contract row was
    deactivated or its valid window edited between Batch 6 routing-
    decision computation and this call), we raise `TransitionError`
    with code `instant_spawn_price_lost`. The outer atomic() rolls
    everything back.
  * **System-only state transition.** The parent
    `REQUESTED → CUSTOMER_APPROVED` transition is guarded by the
    state machine to forbid user-driven access (no role can drive it
    via the API). This module bypasses the role gate by writing the
    status + history row directly with `is_override=False` — it is
    the customer's own act of submission, not a provider override.
  * **Permission anchor.** `actor` is the user who created the
    request (customer self-service OR provider operator who composed
    on behalf). The actor is stamped on each new Ticket's
    `created_by` field and on the parent's `ExtraWorkStatusHistory`
    `changed_by` field so the audit trail attributes the spawn to a
    real user.

Returns a list of the `Ticket` instances created on this call. Empty
list ⇒ idempotent re-run (everything was already spawned).
"""
from __future__ import annotations

from typing import List

from django.db import transaction
from django.utils import timezone

from tickets.models import Ticket, TicketPriority, TicketStatus, TicketStatusHistory

from .models import (
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkRoutingDecision,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
)
from .pricing import resolve_price
from .state_machine import TransitionError


def _line_summary(item: ExtraWorkRequestItem) -> str:
    """One-line human label for a cart line. Mirrors the line's
    `__str__` shape."""
    if item.service is not None:
        return f"{item.service.name} × {item.quantity}"
    return f"Extra work line × {item.quantity}"


def _build_title(request: ExtraWorkRequest, items: List[ExtraWorkRequestItem]) -> str:
    """Sprint 6A — derive ONE Ticket title summarizing the whole
    request. Prefer the request's own title; if blank, derive from the
    first line; append a count suffix when more than one line exists.
    """
    base = (request.title or "").strip()
    if not base:
        base = _line_summary(items[0]) if items else "Extra work"
    if len(items) > 1:
        base = f"{base} (+{len(items) - 1} more)"
    return base


def _build_line_block(item: ExtraWorkRequestItem) -> str:
    """Per-line description block: the line label, its customer_note,
    and the Service catalog description (provider-side reference text
    that survives the catalog -> ticket boundary). Empty parts are
    dropped."""
    parts: List[str] = [_line_summary(item)]
    if item.customer_note and item.customer_note.strip():
        parts.append(f"Line note: {item.customer_note.strip()}")
    if (
        item.service is not None
        and item.service.description
        and item.service.description.strip()
    ):
        parts.append(f"Service: {item.service.description.strip()}")
    return "\n".join(parts)


def _build_description(
    request: ExtraWorkRequest, items: List[ExtraWorkRequestItem]
) -> str:
    """Sprint 6A — compose ONE Ticket description summarizing ALL cart
    lines. The request-level description appears once at the top,
    followed by one block per line. Sections separated by a blank line.
    """
    parts: List[str] = []
    if request.description and request.description.strip():
        parts.append(request.description.strip())
    for item in items:
        parts.append(_build_line_block(item))
    return "\n\n".join(parts)


def spawn_tickets_for_request(
    request: ExtraWorkRequest, *, actor
) -> List[Ticket]:
    """
    Sprint 6A — atomically spawn EXACTLY ONE Ticket for an
    INSTANT-routed ExtraWorkRequest (collapsed from the former
    one-ticket-per-line model), summarizing all cart lines.

    Caller MUST hold an active transaction (we do not wrap our own
    `transaction.atomic()` block — the parent `serializers.
    ExtraWorkRequestCreateSerializer.create()` flow owns the atomic
    boundary, so a partial failure rolls the whole submission back).

    Idempotent: if the request already has a spawned ticket
    (`Ticket.objects.filter(extra_work_request=request).exists()`),
    this is a no-op that returns an empty list.

    Defensive abort: if any line's `resolve_price()` returns None at
    spawn time (despite `routing_decision == "INSTANT"` having been
    set at Batch 6 submission), raises `TransitionError` with stable
    code `instant_spawn_price_lost` and aborts. The surrounding
    `transaction.atomic()` rolls everything back.

    Returns: a single-element list with the created Ticket, or an
    empty list on an idempotent re-run.
    """
    # Belt-and-braces guard: this service should only ever be called on
    # an INSTANT-routed request. If the caller invokes us on a PROPOSAL
    # row by mistake, abort rather than silently spawning tickets that
    # would bypass the proposal flow.
    if request.routing_decision != ExtraWorkRoutingDecision.INSTANT:
        raise TransitionError(
            "spawn_tickets_for_request called on a non-INSTANT request "
            f"(routing_decision={request.routing_decision!r}).",
            code="instant_spawn_wrong_routing",
        )

    created: List[Ticket] = []
    customer = request.customer

    # Snapshot the line-item set into a list to avoid surprises if
    # downstream code mutates the relation during iteration.
    items = list(request.line_items.all().order_by("id"))

    # Sprint 6A — request-level idempotency. A request spawns exactly
    # ONE ticket; if it already has one, this is a no-op re-run.
    already = Ticket.objects.filter(extra_work_request=request).exists()

    if not already:
        # Defensive abort: re-resolve EVERY line's contract price before
        # creating the single ticket. If any row was deactivated or its
        # window edited between Batch 6 submission and this spawn call,
        # fail the whole submission rather than silently flipping the
        # cart to a free-of-charge operational ticket.
        for item in items:
            price_row = resolve_price(
                item.service,
                customer,
                on=item.requested_date,
            )
            if price_row is None:
                raise TransitionError(
                    "Contract price unavailable for line "
                    f"{item.id} (service={item.service_id}); aborting "
                    "instant-ticket spawn.",
                    code="instant_spawn_price_lost",
                )

        # Back-compat legacy link: FIRST cart line. Does NOT drive
        # canonical origin (that is `extra_work_request`); it only feeds
        # the origin payload's representative service name.
        first_item = items[0] if items else None

        ticket = Ticket.objects.create(
            company=request.company,
            building=request.building,
            customer=request.customer,
            created_by=actor,
            title=_build_title(request, items),
            description=_build_description(request, items),
            priority=TicketPriority.NORMAL,
            status=TicketStatus.OPEN,
            extra_work_request=request,
            extra_work_request_item=first_item,
        )

        # Initial OPEN history row. The Ticket model does NOT auto-write
        # one on creation (only `state_machine.apply_transition()` does),
        # so we mirror the pattern explicitly here. old_status is blank
        # by convention — there is no prior state on a brand-new ticket.
        TicketStatusHistory.objects.create(
            ticket=ticket,
            old_status="",
            new_status=TicketStatus.OPEN,
            changed_by=actor,
            note="Spawned from Extra Work cart (instant route).",
            is_override=False,
            override_reason="",
        )

        created.append(ticket)

    # If we created at least one Ticket, advance the parent request to
    # CUSTOMER_APPROVED. The customer's submission IS the approval on
    # the instant path: the price is contract-locked, so there is no
    # provider proposal step. This transition is guarded as system-
    # only in the state machine (see `_user_can_drive_transition`); we
    # write the row + history directly to bypass the role gate without
    # raising the override flag (this is not a provider override of a
    # customer decision — it is the customer's own decision).
    if created and request.status == ExtraWorkStatus.REQUESTED:
        now = timezone.now()
        old_status = request.status
        request.status = ExtraWorkStatus.CUSTOMER_APPROVED
        request.customer_decided_at = now
        request.save(
            update_fields=["status", "customer_decided_at", "updated_at"]
        )
        ExtraWorkStatusHistory.objects.create(
            extra_work=request,
            old_status=old_status,
            new_status=ExtraWorkStatus.CUSTOMER_APPROVED,
            changed_by=actor,
            note="Instant-route auto-approval (customer-specific contract price).",
            is_override=False,
        )

    return created
