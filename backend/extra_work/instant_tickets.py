"""
Sprint 28 Batch 7 — instant-ticket spawn service.

When an `ExtraWorkRequest` is submitted and the cart routing decision
resolves to `INSTANT` (every line item has an active customer-specific
`CustomerServicePrice`), this module spawns one operational
`tickets.Ticket` per `ExtraWorkRequestItem` and drives the parent
request from `REQUESTED` straight to `CUSTOMER_APPROVED`. The customer's
submission IS the approval — no proposal phase is needed because the
price is already agreed by contract (master plan §6 Batch 7).

Contract:
  * **Caller MUST hold an active transaction.** The serializer's
    `ExtraWorkRequestCreateSerializer.create()` invokes us inside its
    existing `transaction.atomic()` block. We do not open a new one
    so a per-line abort rolls the whole submission (parent +
    line-items + tickets) back together.
  * **Idempotent.** A line whose `spawned_tickets` already exists is
    skipped silently. Re-running on the same request is a no-op that
    returns an empty list.
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


def _build_title(item: ExtraWorkRequestItem) -> str:
    """Derive a short Ticket title from the cart line.

    Service.name is the human-readable catalog label; quantity makes
    the line unambiguous when the same service appears across
    multiple requests. Mirrors the line's `__str__` shape.
    """
    if item.service is not None:
        return f"{item.service.name} × {item.quantity}"
    # Defensive: legacy lines have `service=None` (backfilled by the
    # Batch 6 migration). Those rows always route to PROPOSAL, so the
    # spawn service should never be called for them — but if it is,
    # we still want a sane title.
    return f"Extra work line × {item.quantity}"


def _build_description(
    request: ExtraWorkRequest, item: ExtraWorkRequestItem
) -> str:
    """Compose a readable Ticket description from the cart context.

    Combines (in order):
      1. The request-level free-text description.
      2. The line-level customer_note, if any.
      3. The Service catalog row's description, if any (provider-side
         reference text that survives the catalog -> ticket boundary).

    Empty parts are dropped; sections are separated by a blank line.
    """
    parts: List[str] = []
    if request.description and request.description.strip():
        parts.append(request.description.strip())
    if item.customer_note and item.customer_note.strip():
        parts.append(f"Line note: {item.customer_note.strip()}")
    if item.service is not None and item.service.description and item.service.description.strip():
        parts.append(f"Service: {item.service.description.strip()}")
    return "\n\n".join(parts)


def spawn_tickets_for_request(
    request: ExtraWorkRequest, *, actor
) -> List[Ticket]:
    """
    Sprint 28 Batch 7 — atomically spawn one Ticket per
    ExtraWorkRequestItem for an INSTANT-routed ExtraWorkRequest.

    Caller MUST hold an active transaction (we do not wrap our own
    `transaction.atomic()` block — the parent `serializers.
    ExtraWorkRequestCreateSerializer.create()` flow owns the atomic
    boundary, so a partial failure rolls the whole submission back).

    Idempotent: items whose `spawned_tickets` queryset already contains
    a Ticket are skipped.

    Defensive abort: if any line's `resolve_price()` returns None at
    spawn time (despite `routing_decision == "INSTANT"` having been
    set at Batch 6 submission), raises `TransitionError` with stable
    code `instant_spawn_price_lost` and aborts. The surrounding
    `transaction.atomic()` rolls everything back.

    Returns: list of created Ticket instances (empty if all items
    were already spawned — the idempotent re-run case).
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

    for item in items:
        # Idempotency — already spawned on a previous call.
        if Ticket.objects.filter(extra_work_request_item=item).exists():
            continue

        # Defensive abort: re-resolve the line's contract price. If the
        # row was deactivated or its window edited between Batch 6
        # submission and this spawn call, fail the whole submission
        # rather than silently flipping the cart to a free-of-charge
        # operational ticket.
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

        ticket = Ticket.objects.create(
            company=request.company,
            building=request.building,
            customer=request.customer,
            created_by=actor,
            title=_build_title(item),
            description=_build_description(request, item),
            priority=TicketPriority.NORMAL,
            status=TicketStatus.OPEN,
            extra_work_request_item=item,
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
