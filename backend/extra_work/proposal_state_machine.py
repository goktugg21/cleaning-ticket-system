"""
Sprint 28 Batch 8 — proposal state machine.

Distinct from `extra_work.state_machine` (which drives the parent
`ExtraWorkRequest`). This module owns transitions on the
`Proposal` lifecycle.

Allowed transitions:

  DRAFT             -> SENT                 (provider operator scoped to the parent EW's building)
  DRAFT             -> CANCELLED            (provider operator)
  SENT              -> CUSTOMER_APPROVED    (customer with approve_* OR provider override + reason)
  SENT              -> CUSTOMER_REJECTED    (customer with approve_* OR provider override + reason)
  SENT              -> CANCELLED            (provider operator; coerced to is_override + reason required)

After `CUSTOMER_REJECTED` the operator does NOT transition the row
back to DRAFT — instead they POST a fresh DRAFT proposal under the
same parent. The partial UniqueConstraint on `Proposal` allows 1:N
parent->proposals across history while blocking parallel open
drafts.

Override semantics mirror Sprint 27F-B1 (tickets) +
extra_work.state_machine: when a provider-side actor drives a
customer-decision transition, `is_override` is coerced to True and a
non-empty `override_reason` is required (HTTP 400 stable code
`override_reason_required`). Provider-driven SENT->CANCELLED also
coerces to override+reason — withdrawing a sent proposal is a
significant act that the audit trail must explain.

Parent-EW coupling:
  * SENT: when the parent is `UNDER_REVIEW` it auto-advances to
    `PRICING_PROPOSED`. We bypass `extra_work.state_machine.
    apply_transition` deliberately — the pricing_line_items_required
    precondition there targets the legacy `ExtraWorkPricingLineItem`
    flow and is not applicable to the proposal-line flow. The bypass
    writes the status field + an `ExtraWorkStatusHistory` row
    directly inside our atomic block. Defensive: if the parent is
    not in `UNDER_REVIEW` the auto-advance is skipped (idempotent).
  * CUSTOMER_APPROVED / CUSTOMER_REJECTED: when the parent is
    `PRICING_PROPOSED` it advances to the matching parent status.
  * Ticket spawn on customer approval is delegated to
    `extra_work.proposal_tickets.spawn_tickets_for_proposal`.
"""
from __future__ import annotations

from typing import Optional

from django.db import transaction
from django.utils import timezone

from accounts.models import UserRole
from accounts.permissions_v2 import user_has_osius_permission
from customers.permissions import user_can

from .models import (
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
    Proposal,
    ProposalLine,
    ProposalStatus,
    ProposalStatusHistory,
    ProposalTimelineEvent,
    ProposalTimelineEventType,
)
from .pricing import resolve_price


ALLOWED_TRANSITIONS: set[tuple[str, str]] = {
    (ProposalStatus.DRAFT, ProposalStatus.SENT),
    (ProposalStatus.DRAFT, ProposalStatus.CANCELLED),
    (ProposalStatus.SENT, ProposalStatus.CUSTOMER_APPROVED),
    (ProposalStatus.SENT, ProposalStatus.CUSTOMER_REJECTED),
    (ProposalStatus.SENT, ProposalStatus.CANCELLED),
}


class TransitionError(Exception):
    """Raised when a proposal transition is rejected. Mirrors the
    `extra_work.state_machine.TransitionError` shape."""

    def __init__(self, message: str, code: str = "invalid_transition"):
        super().__init__(message)
        self.code = code


def _is_provider_operator(user) -> bool:
    return user.role in {
        UserRole.SUPER_ADMIN,
        UserRole.COMPANY_ADMIN,
        UserRole.BUILDING_MANAGER,
    }


def _provider_in_building_scope(user, building_id: int) -> bool:
    """SUPER_ADMIN bypasses; COMPANY_ADMIN / BUILDING_MANAGER must
    resolve `osius.ticket.view_building` for the EW's building.
    Reused for every provider-driven transition (DRAFT->SENT,
    DRAFT->CANCELLED, SENT->CUSTOMER_*, SENT->CANCELLED)."""
    if user.role == UserRole.SUPER_ADMIN:
        return True
    return user_has_osius_permission(
        user,
        "osius.ticket.view_building",
        building_id=building_id,
    )


def _user_can_drive_proposal_transition(
    user, proposal: Proposal, to_status: str
) -> bool:
    """
    Return True iff `user` may drive `proposal` into `to_status`. The
    (from, to) pair MUST already be in `ALLOWED_TRANSITIONS` — this
    function only decides the role / scope gate.

    Provider-driven transitions (DRAFT->SENT, DRAFT->CANCELLED,
    SENT->CANCELLED, SENT->CUSTOMER_*): SUPER_ADMIN always; COMPANY_
    ADMIN / BUILDING_MANAGER scoped via `osius.ticket.view_building`
    on the parent EW's building (mirror `extra_work.state_machine`
    precedent — same key reuse rule as Sprint 26B).

    Customer-driven transitions (SENT -> CUSTOMER_APPROVED /
    CUSTOMER_REJECTED): customer must hold an active
    `CustomerUserBuildingAccess` for (parent.customer,
    parent.building) AND resolve `customer.extra_work.approve_own`
    (if they are the creator of the parent EW) OR
    `customer.extra_work.approve_location`.

    STAFF: always False.
    """
    extra_work = proposal.extra_work_request
    from_status = proposal.status

    # Provider operator path. Provider-driven SENT->CUSTOMER_* is
    # allowed but the apply_proposal_transition wrapper coerces
    # is_override + requires reason; we just need to gate scope here.
    if _is_provider_operator(user):
        if to_status in {
            ProposalStatus.SENT,
            ProposalStatus.CANCELLED,
        } and from_status in {
            ProposalStatus.DRAFT,
            ProposalStatus.SENT,
        }:
            return _provider_in_building_scope(user, extra_work.building_id)
        if from_status == ProposalStatus.SENT and to_status in {
            ProposalStatus.CUSTOMER_APPROVED,
            ProposalStatus.CUSTOMER_REJECTED,
        }:
            return _provider_in_building_scope(user, extra_work.building_id)
        return False

    if user.role == UserRole.CUSTOMER_USER:
        if from_status == ProposalStatus.SENT and to_status in {
            ProposalStatus.CUSTOMER_APPROVED,
            ProposalStatus.CUSTOMER_REJECTED,
        }:
            # approve_own: must be the creator AND have the key.
            if extra_work.created_by_id == user.id and user_can(
                user,
                extra_work.customer_id,
                extra_work.building_id,
                "customer.extra_work.approve_own",
            ):
                return True
            if user_can(
                user,
                extra_work.customer_id,
                extra_work.building_id,
                "customer.extra_work.approve_location",
            ):
                return True
        return False

    return False


def emit_proposal_event(
    proposal: Proposal,
    *,
    event_type: str,
    actor,
    customer_visible: bool = True,
    metadata: Optional[dict] = None,
) -> ProposalTimelineEvent:
    """
    Append a timeline event row for `proposal`. The status-history
    row captures the bare transition; the timeline event captures
    the same fact plus optional `metadata` (provider-only — stripped
    by the customer-facing serializer).
    """
    return ProposalTimelineEvent.objects.create(
        proposal=proposal,
        event_type=event_type,
        actor=actor,
        customer_visible=customer_visible,
        metadata=metadata or {},
    )


def _advance_parent_on_send(
    request: ExtraWorkRequest, *, actor, proposal_id: int
) -> None:
    """Idempotent parent-EW advancement on proposal SEND.

    Drives the parent from `UNDER_REVIEW` to `PRICING_PROPOSED`.
    Bypasses `extra_work.state_machine.apply_transition` deliberately:
    that path enforces `pricing_line_items_required` against the
    legacy `ExtraWorkPricingLineItem` model, which the proposal-flow
    rows do not populate. We write the status field + history row
    directly so the precondition does not apply.
    """
    if request.status != ExtraWorkStatus.UNDER_REVIEW:
        # Defensive idempotency: another parallel proposal already
        # moved the parent forward; do not double-advance.
        return
    now = timezone.now()
    old_status = request.status
    request.status = ExtraWorkStatus.PRICING_PROPOSED
    request.pricing_proposed_at = now
    request.save(
        update_fields=["status", "pricing_proposed_at", "updated_at"]
    )
    ExtraWorkStatusHistory.objects.create(
        extra_work=request,
        old_status=old_status,
        new_status=ExtraWorkStatus.PRICING_PROPOSED,
        changed_by=actor,
        note=f"Proposal #{proposal_id} sent to customer.",
        is_override=False,
    )


def _advance_parent_on_customer_decision(
    request: ExtraWorkRequest,
    *,
    actor,
    proposal_id: int,
    to_status: str,
    is_override: bool,
    override_reason: str,
) -> None:
    """Idempotent parent-EW advancement on customer approve / reject.

    Mirrors the SENT advancement: bypasses
    `extra_work.state_machine.apply_transition`. Sets the matching
    parent status (`CUSTOMER_APPROVED` or `CUSTOMER_REJECTED`),
    stamps `customer_decided_at`, and writes an
    `ExtraWorkStatusHistory` row. When the proposal transition was
    a provider override, the override metadata is mirrored onto the
    parent row + the history row so the parent's audit trail tells
    the same story.
    """
    if request.status != ExtraWorkStatus.PRICING_PROPOSED:
        return
    now = timezone.now()
    old_status = request.status
    # Map proposal->parent status. The proposal enum names match
    # the parent ones exactly.
    request.status = to_status
    request.customer_decided_at = now
    update_fields = ["status", "customer_decided_at", "updated_at"]
    if is_override:
        request.override_by = actor
        request.override_reason = override_reason
        request.override_at = now
        update_fields.extend(
            ["override_by", "override_reason", "override_at"]
        )
    request.save(update_fields=update_fields)
    note_verb = (
        "approved" if to_status == ProposalStatus.CUSTOMER_APPROVED
        else "rejected"
    )
    ExtraWorkStatusHistory.objects.create(
        extra_work=request,
        old_status=old_status,
        new_status=to_status,
        changed_by=actor,
        note=f"Proposal #{proposal_id} {note_verb}.",
        is_override=is_override,
    )


def _validate_proposal_covers_cart(proposal: Proposal) -> None:
    """
    B2 SEND-time gate (system-business-logic-and-workflows.md §7.0).

    A Proposal is the customer's quote for the **submitted cart**, so
    at SEND time the proposal lines must cover the cart exactly:

      * Each cart item must be represented by exactly one proposal
        line with the same `(service_id, unit_type, quantity)` multi-
        set key.
      * Each proposal line must correspond to a cart item — surprise
        lines (provider-added charges that the customer did not put
        in the cart) are rejected. A future surface for travel /
        material / admin fees would introduce a deliberate separate
        line type; until then, SEND refuses extras.

    For every matched proposal line, the helper re-runs
    `extra_work.pricing.resolve_price` against the matched cart
    item's `requested_date` and enforces:

      * **Contract-price floor.** When the resolver returns a row,
        the proposal line's `unit_price` and `vat_pct` MUST equal the
        contract row's. The contract is the only commercial truth
        for that customer/service/date. Operators that need to quote
        a different number must adjust the contract row itself —
        which is auditable — not the per-proposal price field.
      * **Non-contract lines must be priced.** When the resolver
        returns `None` (custom / non-contract line), the proposal
        line's `unit_price` MUST be strictly greater than zero. There
        is no `customer_explanation`-rescues-zero loophole — free /
        promo / compensation lines are a deliberate future feature
        and will be a separate line type, not a price-of-zero with a
        free-text justification.

    Match algorithm (multiset, no FK):
      The current schema does NOT include a `requested_date` column
      on `ProposalLine` (cart→proposal linkage is stored only on the
      parent EW). To keep B2 migration-free, the match key is
      `(service_id, unit_type, quantity)`, and ambiguous matches
      (cart items with identical 3-tuples but different
      `requested_date`s) are resolved by stable iteration order
      (cart-item id ascending). In practice carts rarely contain
      identical-3-tuple-different-date duplicates because each cart
      item is the customer's deliberate per-date pick. If production
      surfaces such ambiguity at scale, the next iteration adds a
      `ProposalLine.extra_work_request_item` FK (one migration) —
      until then the multiset comparison is the spec floor.

    Raises:
      TransitionError with one of:
        - "proposal_has_extra_line"
        - "proposal_does_not_cover_cart"
        - "proposal_contract_price_drift"
        - "proposal_custom_line_missing_price"
    """
    extra_work_request = proposal.extra_work_request
    customer = extra_work_request.customer

    cart_items = list(
        ExtraWorkRequestItem.objects.filter(
            extra_work_request=extra_work_request
        ).order_by("id")
    )
    proposal_lines = list(
        ProposalLine.objects.filter(proposal=proposal).order_by("id")
    )

    # First pass: match each proposal line to a cart item by the
    # (service_id, unit_type, quantity) multiset key. Each cart item
    # is consumed at most once.
    unmatched_cart = list(cart_items)
    matches: list[tuple[ProposalLine, ExtraWorkRequestItem]] = []
    for line in proposal_lines:
        line_key = (
            line.service_id,
            line.unit_type,
            line.quantity,
        )
        match_idx = None
        for idx, item in enumerate(unmatched_cart):
            if (
                item.service_id,
                item.unit_type,
                item.quantity,
            ) == line_key:
                match_idx = idx
                break
        if match_idx is None:
            raise TransitionError(
                "Proposal contains a line that does not correspond to "
                "any item in the customer's submitted cart. Add the "
                "matching cart item or remove the proposal line.",
                code="proposal_has_extra_line",
            )
        matches.append((line, unmatched_cart.pop(match_idx)))

    if unmatched_cart:
        raise TransitionError(
            "Proposal does not cover every item in the customer's "
            "submitted cart. Add a proposal line for each remaining "
            "cart item before sending.",
            code="proposal_does_not_cover_cart",
        )

    # Second pass: contract-price floor + zero-price-with-explanation.
    for line, cart_item in matches:
        contract = resolve_price(
            line.service, customer, on=cart_item.requested_date
        )
        if contract is not None:
            # Contract-priced cart line — proposal must mirror it
            # exactly (price AND VAT). Zero is acceptable iff the
            # contract row itself is zero.
            if (
                line.unit_price != contract.unit_price
                or line.vat_pct != contract.vat_pct
            ):
                raise TransitionError(
                    "Proposal line price does not match the customer's "
                    "contract price for this service. Either match the "
                    "contract or adjust the contract row.",
                    code="proposal_contract_price_drift",
                )
        else:
            # Custom / non-contract line — the provider must enter a
            # real unit price before SEND. `customer_explanation` is
            # customer-visible business text, never a flag, so the B2
            # rule deliberately rejects unit_price=0 regardless of the
            # explanation field. Free / promo / compensation lines
            # are a future deliberate line-type feature; encoding
            # them through a zero-with-text-justification was rejected
            # in the 2026-05-24 clarification.
            if line.unit_price <= 0:
                raise TransitionError(
                    "Non-contract proposal line is missing a price. "
                    "The provider must enter a unit price greater "
                    "than zero before the proposal can be sent.",
                    code="proposal_custom_line_missing_price",
                )


@transaction.atomic
def apply_proposal_transition(
    proposal: Proposal,
    user,
    to_status: str,
    *,
    note: str = "",
    is_override: bool = False,
    override_reason: str = "",
) -> Proposal:
    """
    Drive `proposal` from its current status to `to_status`. Raises
    `TransitionError` with a stable `.code` attribute on rejection.

    Side effects on success:
      * status + timestamp columns updated on the proposal row,
      * `ProposalStatusHistory` row written,
      * `ProposalTimelineEvent` row written (for SENT / CUSTOMER_* /
        CANCELLED; also `ADMIN_OVERRIDDEN` when a provider drove a
        customer-decision transition),
      * parent `ExtraWorkRequest` advanced on SEND / customer-decision
        (idempotent — see `_advance_parent_on_*` helpers),
      * spawn tickets via `proposal_tickets.spawn_tickets_for_proposal`
        when `to_status == CUSTOMER_APPROVED`.

    Wrapped in `transaction.atomic` with `select_for_update` so a
    concurrent transition cannot race past us.
    """
    if to_status not in ProposalStatus.values:
        raise TransitionError(
            f"Unknown status '{to_status}'.", code="unknown_status"
        )

    if proposal.status == to_status:
        raise TransitionError(
            f"Proposal is already in status '{to_status}'.",
            code="no_op_transition",
        )

    key = (proposal.status, to_status)
    if key not in ALLOWED_TRANSITIONS:
        raise TransitionError(
            f"Transition {proposal.status} -> {to_status} is not allowed.",
            code="invalid_transition",
        )

    if not _user_can_drive_proposal_transition(user, proposal, to_status):
        raise TransitionError(
            f"Not allowed to move proposal to '{to_status}'.",
            code="forbidden_transition",
        )

    # SEND-time precondition: at least one ProposalLine exists.
    if to_status == ProposalStatus.SENT:
        if not ProposalLine.objects.filter(proposal=proposal).exists():
            raise TransitionError(
                "At least one proposal line is required before sending.",
                code="proposal_lines_required",
            )

    # SEND-time parent-status guard. The proposal flow assumes the
    # parent has been moved into UNDER_REVIEW by the operator (the
    # parent_request -> UNDER_REVIEW transition stays on the existing
    # state machine). A REQUESTED parent means the operator hasn't
    # taken ownership yet — bail with a stable code so the UI can
    # explain the precondition.
    if to_status == ProposalStatus.SENT:
        if proposal.extra_work_request.status != ExtraWorkStatus.UNDER_REVIEW:
            raise TransitionError(
                "Parent Extra Work request must be in UNDER_REVIEW "
                "before a proposal can be sent.",
                code="proposal_send_requires_under_review",
            )

    # B2 (system-business-logic-and-workflows.md §7.0) SEND-time gates:
    #
    #   (a) Cart-coverage: the proposal must cover the whole cart and
    #       carry no extra lines. Match is multiset by
    #       (service_id, unit_type, quantity).
    #   (b) Contract-price floor: for every proposal line that resolves
    #       to a contract row at the matched cart item's
    #       requested_date, the proposal's unit_price and vat_pct MUST
    #       equal the contract row's. Operators cannot silently quote
    #       below or above the agreed contract.
    #   (c) Zero-price guard: a non-contract proposal line may carry
    #       unit_price=0 only when customer_explanation is non-blank.
    #       A bare zero-price line on a non-contract item is rejected.
    #
    # All three gates are checked inside `_validate_proposal_covers_cart`
    # before the row is locked for the status transition.
    if to_status == ProposalStatus.SENT:
        _validate_proposal_covers_cart(proposal)

    # Provider-driven customer-decision coercion: ALWAYS an override.
    provider_driven_customer_decision = (
        _is_provider_operator(user)
        and proposal.status == ProposalStatus.SENT
        and to_status in {
            ProposalStatus.CUSTOMER_APPROVED,
            ProposalStatus.CUSTOMER_REJECTED,
        }
    )
    # Provider withdrawing a SENT proposal is also a significant act
    # that needs a reason — same shape as the customer-decision
    # override, applied to CANCELLED from SENT.
    provider_driven_sent_cancel = (
        _is_provider_operator(user)
        and proposal.status == ProposalStatus.SENT
        and to_status == ProposalStatus.CANCELLED
    )
    if provider_driven_customer_decision or provider_driven_sent_cancel:
        is_override = True

    if is_override and not override_reason.strip():
        raise TransitionError(
            "Override reason is required when a provider operator "
            "drives a customer-decision or sent-cancellation transition.",
            code="override_reason_required",
        )

    locked = Proposal.objects.select_for_update().get(pk=proposal.pk)
    if locked.status != proposal.status:
        raise TransitionError(
            "Proposal status changed concurrently; please reload.",
            code="stale_status",
        )

    old_status = locked.status
    locked.status = to_status
    now = timezone.now()
    update_fields = ["status", "updated_at"]

    if to_status == ProposalStatus.SENT:
        locked.sent_at = now
        update_fields.append("sent_at")
    if to_status in {
        ProposalStatus.CUSTOMER_APPROVED,
        ProposalStatus.CUSTOMER_REJECTED,
    }:
        locked.customer_decided_at = now
        update_fields.append("customer_decided_at")

    if is_override:
        locked.override_by = user
        locked.override_reason = override_reason
        locked.override_at = now
        update_fields.extend(["override_by", "override_reason", "override_at"])

    locked.save(update_fields=update_fields)

    ProposalStatusHistory.objects.create(
        proposal=locked,
        old_status=old_status,
        new_status=to_status,
        changed_by=user,
        note=note or "",
        is_override=is_override,
        override_reason=override_reason or "",
    )

    # Timeline events: emit the matching transition event, plus an
    # explicit ADMIN_OVERRIDDEN event when the provider drove a
    # customer-decision transition.
    _event_for_transition = {
        ProposalStatus.SENT: ProposalTimelineEventType.SENT,
        ProposalStatus.CUSTOMER_APPROVED: ProposalTimelineEventType.CUSTOMER_APPROVED,
        ProposalStatus.CUSTOMER_REJECTED: ProposalTimelineEventType.CUSTOMER_REJECTED,
        ProposalStatus.CANCELLED: ProposalTimelineEventType.CANCELLED,
    }
    event_type = _event_for_transition[to_status]
    emit_proposal_event(
        locked,
        event_type=event_type,
        actor=user,
        customer_visible=True,
        metadata={"is_override": is_override} if is_override else None,
    )
    if provider_driven_customer_decision:
        emit_proposal_event(
            locked,
            event_type=ProposalTimelineEventType.ADMIN_OVERRIDDEN,
            actor=user,
            customer_visible=True,
            metadata={
                "override_reason": override_reason,
                "to_status": to_status,
            },
        )

    # Parent-EW propagation.
    if to_status == ProposalStatus.SENT:
        _advance_parent_on_send(
            locked.extra_work_request,
            actor=user,
            proposal_id=locked.pk,
        )
    if to_status in {
        ProposalStatus.CUSTOMER_APPROVED,
        ProposalStatus.CUSTOMER_REJECTED,
    }:
        _advance_parent_on_customer_decision(
            locked.extra_work_request,
            actor=user,
            proposal_id=locked.pk,
            to_status=to_status,
            is_override=is_override,
            override_reason=override_reason,
        )

    # Ticket spawn on customer approval. Covers both customer-driven
    # approval and provider-override approval. The spawn helper
    # itself is idempotent.
    if to_status == ProposalStatus.CUSTOMER_APPROVED:
        # Lazy import to avoid module-load cycle.
        from .proposal_tickets import spawn_tickets_for_proposal

        spawn_tickets_for_proposal(locked, actor=user)

    return locked


def allowed_next_proposal_statuses(user, proposal: Proposal) -> list[str]:
    """Return the list of statuses `user` may currently drive
    `proposal` into. Used by the frontend to gate buttons."""
    return [
        to_status
        for (from_status, to_status) in ALLOWED_TRANSITIONS
        if from_status == proposal.status
        and _user_can_drive_proposal_transition(user, proposal, to_status)
    ]
