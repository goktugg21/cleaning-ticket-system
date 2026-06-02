"""
Sprint 7B — convert a normal Ticket / melding into an Extra Work request.

A provider operator (SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER)
decides that an inbound ticket is really extra (chargeable) work. This
service supersedes the original ticket to the terminal status
`CONVERTED_TO_EXTRA_WORK` and creates a brand-new `ExtraWorkRequest`
anchored to it via `ExtraWorkRequest.source_ticket`. A NEW operational
ticket is spawned by the existing Sprint 6A/6B machinery (immediately
on the INSTANT route, later on the PROPOSAL route) — the original
ticket is NOT reused.

The whole operation runs inside ONE `transaction.atomic()` so a partial
conversion (EW created, source ticket not flipped, or vice versa) is
never observable.
"""
from __future__ import annotations

from typing import List, Tuple

from django.db import transaction

from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail

from tickets.models import Ticket, TicketStatus, TicketStatusHistory

from .classification import (
    ACTOR_PROVIDER,
    IntentValidationError,
    classify_cart,
    classify_line,
    validate_intent_for_cart,
)
from .models import (
    ExtraWorkCategory,
    ExtraWorkLinePriceSource,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkRoutingDecision,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
)


def convert_ticket_to_extra_work(
    ticket: Ticket,
    *,
    actor,
    request_intent: str,
    line_items_data: list,
    customer_visible_note: str = "",
    internal_note: str = "",
) -> Tuple[ExtraWorkRequest, List[Ticket]]:
    """Convert `ticket` into a new `ExtraWorkRequest`.

    `line_items_data` is the validated cart-line list (each a dict with
    keys: `service` (Service or None), `custom_description`, `quantity`,
    `requested_date`, `customer_note`). The caller (the convert endpoint)
    is responsible for the role / scope / convertibility gates; this
    service owns the intent validation, the EW + line-item creation, the
    routing decision, the optional instant spawn, and the source-ticket
    flip.

    Returns `(extra_work_request, spawned_tickets)`. The spawned list is
    non-empty only on the INSTANT route (a single operational ticket);
    on the PROPOSAL route it is empty and tickets are spawned later by
    the proposal flow.
    """
    with transaction.atomic():
        # 1. Classify every cart line, then aggregate.
        per_line = [
            classify_line(
                service=line.get("service"),
                customer=ticket.customer,
                requested_date=line["requested_date"],
                custom_description=(line.get("custom_description") or ""),
            )
            for line in line_items_data
        ]
        cart = classify_cart(per_line)

        # 2. Validate the (intent × cart × actor) tuple. The provider
        # converting a customer's ticket is allowed to drive
        # REQUEST_QUOTE (is_conversion=True) — every other rule is
        # unchanged.
        try:
            validate_intent_for_cart(
                intent=request_intent,
                cart=cart,
                actor_kind=ACTOR_PROVIDER,
                is_conversion=True,
            )
        except IntentValidationError as exc:
            raise serializers.ValidationError(
                {"request_intent": [ErrorDetail(exc.message, code=exc.code)]}
            )

        # 3. Create the parent ExtraWorkRequest from the source ticket.
        source_label = ticket.ticket_no or ticket.id
        ew = ExtraWorkRequest.objects.create(
            company=ticket.company,
            building=ticket.building,
            customer=ticket.customer,
            created_by=actor,
            title=ticket.title,
            description=ticket.description,
            category=ExtraWorkCategory.OTHER,
            category_other_text=f"Converted from ticket {source_label}",
            request_intent=request_intent,
            customer_visible_note=customer_visible_note,
            manager_note=internal_note,
            source_ticket=ticket,
            status=ExtraWorkStatus.REQUESTED,
        )

        # 4. Create one ExtraWorkRequestItem per line, mirroring the
        # create serializer's snapshot loop exactly.
        for line, classification in zip(line_items_data, per_line):
            service = line.get("service")
            if service is None:
                unit_type = ExtraWorkPricingUnitType.OTHER
            else:
                unit_type = service.unit_type
            ExtraWorkRequestItem.objects.create(
                extra_work_request=ew,
                service=service,
                custom_description=(line.get("custom_description") or ""),
                quantity=line["quantity"],
                unit_type=unit_type,
                requested_date=line["requested_date"],
                customer_note=line.get("customer_note", ""),
                line_price_source=classification.source,
                snapshot_unit_price=classification.snapshot_unit_price,
                snapshot_vat_pct=classification.snapshot_vat_pct,
                snapshot_service_name=classification.snapshot_service_name,
                snapshot_service_category_name=(
                    classification.snapshot_service_category_name
                ),
                snapshot_customer_service_price=classification.contract,
            )

        # 5. Routing decision: INSTANT only when every line resolved to
        # an agreed customer price; otherwise PROPOSAL.
        all_agreed = all(
            c.source == ExtraWorkLinePriceSource.AGREED_CUSTOMER_PRICE
            for c in per_line
        )
        ew.routing_decision = (
            ExtraWorkRoutingDecision.INSTANT
            if all_agreed
            else ExtraWorkRoutingDecision.PROPOSAL
        )
        ew.save(update_fields=["routing_decision", "updated_at"])

        # 6. EW-side conversion trace.
        ExtraWorkStatusHistory.objects.create(
            extra_work=ew,
            old_status="",
            new_status=ExtraWorkStatus.REQUESTED,
            changed_by=actor,
            note=(
                f"Converted from ticket {source_label} "
                f"(intent={request_intent})."
            ),
            is_override=False,
        )

        # 7. INSTANT route — spawn the single operational ticket now and
        # advance the EW to CUSTOMER_APPROVED (Sprint 6A machinery).
        spawned: List[Ticket] = []
        if ew.routing_decision == ExtraWorkRoutingDecision.INSTANT:
            # Imported lazily to mirror the serializer's circular-import
            # avoidance.
            from .instant_tickets import spawn_tickets_for_request

            spawned = spawn_tickets_for_request(ew, actor=actor)

        # 8. Flip the SOURCE ticket to the terminal CONVERTED status.
        # NOT routed through `tickets.state_machine.apply_transition`:
        # this is a system conversion action and CONVERTED is
        # intentionally absent from ALLOWED_TRANSITIONS (keeps it
        # terminal). Assignments / attachments / messages are left
        # intact — they are NOT copied to the EW.
        prior_status = ticket.status
        ticket.status = TicketStatus.CONVERTED_TO_EXTRA_WORK
        ticket.save(update_fields=["status", "updated_at"])
        TicketStatusHistory.objects.create(
            ticket=ticket,
            old_status=prior_status,
            new_status=TicketStatus.CONVERTED_TO_EXTRA_WORK,
            changed_by=actor,
            note=(
                f"Converted to Extra Work request #{ew.id} "
                f"(intent={request_intent}; {len(line_items_data)} line(s))."
            ),
            is_override=False,
            override_reason="",
        )

        return ew, spawned
