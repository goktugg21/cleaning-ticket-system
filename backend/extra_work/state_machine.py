"""
Extra Work state machine.

Allowed transitions (customer-pricing loop — Sprint 26B):

  REQUESTED         -> UNDER_REVIEW         (provider operator)
  REQUESTED         -> CANCELLED            (creator-only, no provider review yet)
  UNDER_REVIEW      -> PRICING_PROPOSED     (provider operator, requires >=1 line item)
  UNDER_REVIEW      -> CANCELLED            (provider operator OR creator)
  PRICING_PROPOSED  -> CUSTOMER_APPROVED    (customer with approve_* permission OR provider override)
  PRICING_PROPOSED  -> CUSTOMER_REJECTED    (customer with approve_* permission OR provider override)
  PRICING_PROPOSED  -> UNDER_REVIEW         (provider operator wants to revise pricing)
  PRICING_PROPOSED  -> CANCELLED            (provider operator OR creator)
  CUSTOMER_REJECTED -> UNDER_REVIEW         (provider can revise after rejection)
  CUSTOMER_APPROVED -> CANCELLED            (provider override — needs reason)
  REQUESTED         -> CUSTOMER_APPROVED    (SYSTEM-ONLY — Sprint 28 Batch 7
                                             instant-ticket spawn; never
                                             reachable via the user-facing
                                             transition endpoint)

Operational segment (Sprint 29 Batch 29.8):

  CUSTOMER_APPROVED -> IN_PROGRESS          (SYSTEM auto when first spawned
                                             ticket goes IN_PROGRESS; or
                                             provider manual override)
  IN_PROGRESS       -> COMPLETED            (SYSTEM auto when all spawned
                                             tickets are terminal; or
                                             provider manual)
  IN_PROGRESS       -> CANCELLED            (provider override — needs reason)
  COMPLETED         -> IN_PROGRESS          (edge-recovery, provider-only,
                                             needs reason)

The CUSTOMER_APPROVED -> IN_PROGRESS and IN_PROGRESS -> COMPLETED
pairs are also listed in `SYSTEM_AUTO_TRANSITIONS` so the auto-sync
hook in `tickets.state_machine.apply_transition` can drive them
with `user=None` without tripping the role gate.

Commercial-execution statuses (FULFILLED / BILLED) remain
deferred to a follow-up sprint.

Sprint 28 Batch 7 system-only transition
----------------------------------------
The `(REQUESTED, CUSTOMER_APPROVED)` pair is the instant-route auto-
approval written by `extra_work.instant_tickets.spawn_tickets_for_request`.
It is intentionally NOT reachable via the user-facing
`POST /api/extra-work/<id>/transition/` endpoint: customers must not be
able to skip the proposal phase by hand-rolling a transition payload,
and providers must not be able to drive it without writing the override
reason on the existing PRICING_PROPOSED path. `_user_can_drive_transition`
returns False for this pair regardless of actor role; the spawn service
writes the status + history row directly, bypassing `apply_transition`.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from accounts.models import UserRole
from accounts.permissions_v2 import user_has_osius_permission
from customers.permissions import user_can

from .models import (
    ExtraWorkPricingLineItem,
    ExtraWorkRequest,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
)


# Allowed (from_status, to_status) tuples. Permission gate is
# evaluated separately by `_user_can_drive_transition` so the same
# transition can be driven by different roles in different scopes.
ALLOWED_TRANSITIONS: set[tuple[str, str]] = {
    (ExtraWorkStatus.REQUESTED, ExtraWorkStatus.UNDER_REVIEW),
    (ExtraWorkStatus.REQUESTED, ExtraWorkStatus.CANCELLED),
    (ExtraWorkStatus.UNDER_REVIEW, ExtraWorkStatus.PRICING_PROPOSED),
    (ExtraWorkStatus.UNDER_REVIEW, ExtraWorkStatus.CANCELLED),
    (ExtraWorkStatus.PRICING_PROPOSED, ExtraWorkStatus.CUSTOMER_APPROVED),
    (ExtraWorkStatus.PRICING_PROPOSED, ExtraWorkStatus.CUSTOMER_REJECTED),
    (ExtraWorkStatus.PRICING_PROPOSED, ExtraWorkStatus.UNDER_REVIEW),
    (ExtraWorkStatus.PRICING_PROPOSED, ExtraWorkStatus.CANCELLED),
    (ExtraWorkStatus.CUSTOMER_REJECTED, ExtraWorkStatus.UNDER_REVIEW),
    (ExtraWorkStatus.CUSTOMER_APPROVED, ExtraWorkStatus.CANCELLED),
    # Sprint 28 Batch 7 — instant-route auto-approval. System-only:
    # `_user_can_drive_transition` returns False for this pair, so the
    # public `/transition/` endpoint cannot reach it. The spawn service
    # writes the status + history row directly (see
    # `extra_work.instant_tickets.spawn_tickets_for_request`).
    (ExtraWorkStatus.REQUESTED, ExtraWorkStatus.CUSTOMER_APPROVED),
    # Sprint 29 Batch 29.8 — operational segment. The first two pairs
    # are also driven automatically by the auto-sync hook in
    # `tickets.state_machine.apply_transition` (see
    # `SYSTEM_AUTO_TRANSITIONS` below).
    (ExtraWorkStatus.CUSTOMER_APPROVED, ExtraWorkStatus.IN_PROGRESS),
    (ExtraWorkStatus.IN_PROGRESS, ExtraWorkStatus.COMPLETED),
    (ExtraWorkStatus.IN_PROGRESS, ExtraWorkStatus.CANCELLED),
    # Edge-recovery: a provider can reopen a wrongly-COMPLETED EW. Provider-
    # only and requires an override_reason (see `_user_can_drive_transition`
    # + `apply_transition` reason gate).
    (ExtraWorkStatus.COMPLETED, ExtraWorkStatus.IN_PROGRESS),
}


# Sprint 28 Batch 7 — pairs that must never be reachable via the public
# transition endpoint. `_user_can_drive_transition` short-circuits on
# any pair in this set so no role / scope combination can drive them
# via the API. The `extra_work.instant_tickets` spawn service writes
# these transitions directly, bypassing `apply_transition`.
SYSTEM_ONLY_TRANSITIONS: set[tuple[str, str]] = {
    (ExtraWorkStatus.REQUESTED, ExtraWorkStatus.CUSTOMER_APPROVED),
}


# Sprint 29 Batch 29.8 — operational-segment transitions that the
# `tickets.state_machine.apply_transition` auto-sync hook drives with
# `user=None`. `_user_can_drive_transition` admits a `None` actor only
# for pairs in this set; the same pairs remain available to qualified
# providers as manual transitions (the gate also returns True for
# SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER with the right scope).
SYSTEM_AUTO_TRANSITIONS: set[tuple[str, str]] = {
    (ExtraWorkStatus.CUSTOMER_APPROVED, ExtraWorkStatus.IN_PROGRESS),
    (ExtraWorkStatus.IN_PROGRESS, ExtraWorkStatus.COMPLETED),
}


class TransitionError(Exception):
    """Raised when a transition is rejected (mirrors Ticket pattern)."""

    def __init__(self, message: str, code: str = "invalid_transition"):
        super().__init__(message)
        self.code = code


def _is_provider_operator(user) -> bool:
    """SUPER_ADMIN, COMPANY_ADMIN, or BUILDING_MANAGER — the three
    roles that can drive provider-side transitions on Extra Work."""
    return user.role in {
        UserRole.SUPER_ADMIN,
        UserRole.COMPANY_ADMIN,
        UserRole.BUILDING_MANAGER,
    }


def _user_can_drive_transition(
    user, extra_work: ExtraWorkRequest, to_status: str
) -> bool:
    """
    Return True if `user` is allowed to drive `extra_work` into
    `to_status`. The (from, to) pair MUST already be in
    ALLOWED_TRANSITIONS — this function only decides the role/scope
    layer.

    Provider-side transitions:
      * SUPER_ADMIN: always.
      * COMPANY_ADMIN: in their own provider company.
      * BUILDING_MANAGER: only for tickets in their assigned
        buildings (proxy via `osius.ticket.view_building` — same
        scope shape as ticket reviews; we deliberately reuse this
        key in MVP so we don't introduce new permission keys this
        sprint per the Sprint 26B "do not rename osius.*" rule).

    Customer-side transitions (CUSTOMER_APPROVED / CUSTOMER_REJECTED
    from PRICING_PROPOSED):
      * Must have an active CustomerUserBuildingAccess row for
        (extra_work.customer, extra_work.building) AND that row
        must resolve `customer.extra_work.approve_own` (creator)
        or `customer.extra_work.approve_location`.

    Creator-self CANCEL on REQUESTED is allowed even without
    approval rights (you can always cancel something you haven't
    yet asked the provider to price).

    Sprint 29 Batch 29.8 — operational-segment transitions:
      * CUSTOMER_APPROVED -> IN_PROGRESS: SUPER_ADMIN / COMPANY_ADMIN
        (of EW's company) / BUILDING_MANAGER (of EW's building).
        STAFF and customer roles cannot drive manually. Also
        admitted with `user=None` (system auto-sync hook).
      * IN_PROGRESS -> COMPLETED: same provider roles as above.
        Also admitted with `user=None`.
      * IN_PROGRESS -> CANCELLED: same provider roles. Caller must
        supply override_reason (enforced in `apply_transition`).
      * COMPLETED -> IN_PROGRESS: SUPER_ADMIN / COMPANY_ADMIN only
        (edge-recovery). Requires override_reason.
    """
    from_status = extra_work.status

    # Sprint 28 Batch 7 — system-only transitions (e.g. the
    # instant-route REQUESTED -> CUSTOMER_APPROVED auto-approval) are
    # never reachable via the user-facing transition endpoint. The
    # spawn service writes them directly, bypassing apply_transition.
    if (from_status, to_status) in SYSTEM_ONLY_TRANSITIONS:
        return False

    # Sprint 29 Batch 29.8 — system-auto transitions driven by the
    # `tickets.state_machine.apply_transition` hook with `user=None`.
    # Admitted only for pairs in `SYSTEM_AUTO_TRANSITIONS`; provider
    # operators with the right scope still fall through to the role
    # branches below for the same pair.
    if user is None:
        return (from_status, to_status) in SYSTEM_AUTO_TRANSITIONS

    if user.role == UserRole.SUPER_ADMIN:
        # Super admin can drive any allowed transition globally.
        return True

    if _is_provider_operator(user):
        # Provider operator transitions: UNDER_REVIEW,
        # PRICING_PROPOSED (forward), back-to-UNDER_REVIEW, and
        # CANCELLED at any provider-driven moment.
        if to_status in {
            ExtraWorkStatus.UNDER_REVIEW,
            ExtraWorkStatus.PRICING_PROPOSED,
            ExtraWorkStatus.CANCELLED,
        }:
            if user.role == UserRole.COMPANY_ADMIN:
                # COMPANY_ADMIN must be a member of the provider
                # company that owns this ExtraWork row.
                return user_has_osius_permission(
                    user,
                    "osius.ticket.view_building",
                    building_id=extra_work.building_id,
                )
            if user.role == UserRole.BUILDING_MANAGER:
                return user_has_osius_permission(
                    user,
                    "osius.ticket.view_building",
                    building_id=extra_work.building_id,
                )
        # Provider override path — approve or reject as the
        # customer. Allowed but the caller must supply
        # override_reason; the view enforces that, not us.
        if to_status in {
            ExtraWorkStatus.CUSTOMER_APPROVED,
            ExtraWorkStatus.CUSTOMER_REJECTED,
        } and from_status == ExtraWorkStatus.PRICING_PROPOSED:
            if user.role == UserRole.COMPANY_ADMIN:
                return user_has_osius_permission(
                    user,
                    "osius.ticket.view_building",
                    building_id=extra_work.building_id,
                )
            if user.role == UserRole.BUILDING_MANAGER:
                return user_has_osius_permission(
                    user,
                    "osius.ticket.view_building",
                    building_id=extra_work.building_id,
                )

        # Sprint 29 Batch 29.8 — operational segment manual transitions.
        # CUSTOMER_APPROVED -> IN_PROGRESS, IN_PROGRESS -> COMPLETED,
        # IN_PROGRESS -> CANCELLED: SUPER_ADMIN / COMPANY_ADMIN / BM with
        # building scope.
        if (from_status, to_status) in {
            (ExtraWorkStatus.CUSTOMER_APPROVED, ExtraWorkStatus.IN_PROGRESS),
            (ExtraWorkStatus.IN_PROGRESS, ExtraWorkStatus.COMPLETED),
            (ExtraWorkStatus.IN_PROGRESS, ExtraWorkStatus.CANCELLED),
        }:
            if user.role in {UserRole.COMPANY_ADMIN, UserRole.BUILDING_MANAGER}:
                return user_has_osius_permission(
                    user,
                    "osius.ticket.view_building",
                    building_id=extra_work.building_id,
                )

        # Sprint 29 Batch 29.8 — edge-recovery COMPLETED -> IN_PROGRESS.
        # SUPER_ADMIN already returned True at the top. COMPANY_ADMIN with
        # building scope may also drive it; BUILDING_MANAGER may NOT (the
        # corrective intent here is intentionally limited to admins).
        if (
            from_status == ExtraWorkStatus.COMPLETED
            and to_status == ExtraWorkStatus.IN_PROGRESS
        ):
            if user.role == UserRole.COMPANY_ADMIN:
                return user_has_osius_permission(
                    user,
                    "osius.ticket.view_building",
                    building_id=extra_work.building_id,
                )

    if user.role == UserRole.CUSTOMER_USER:
        # Creator can cancel their own REQUESTED row even without
        # approve_* — they've never asked the provider to spend
        # time on it yet. Same shape as a normal ticket: the
        # person who opened it can withdraw it before any provider
        # work happens.
        if (
            from_status == ExtraWorkStatus.REQUESTED
            and to_status == ExtraWorkStatus.CANCELLED
            and extra_work.created_by_id == user.id
        ):
            return True

        # Customer approve / reject on PRICING_PROPOSED.
        if from_status == ExtraWorkStatus.PRICING_PROPOSED and to_status in {
            ExtraWorkStatus.CUSTOMER_APPROVED,
            ExtraWorkStatus.CUSTOMER_REJECTED,
        }:
            # approve_own: must be creator AND have approve_own.
            if extra_work.created_by_id == user.id and user_can(
                user,
                extra_work.customer_id,
                extra_work.building_id,
                "customer.extra_work.approve_own",
            ):
                return True
            # approve_location: anyone at the (customer, building)
            # with the location-approval permission.
            if user_can(
                user,
                extra_work.customer_id,
                extra_work.building_id,
                "customer.extra_work.approve_location",
            ):
                return True

    return False


@transaction.atomic
def apply_transition(
    extra_work: ExtraWorkRequest,
    user,
    to_status: str,
    *,
    note: str = "",
    is_override: bool = False,
    override_reason: str = "",
) -> ExtraWorkRequest:
    """
    Drive an Extra Work request from its current status to
    `to_status`. Raises TransitionError with a stable `.code`
    attribute on rejection. On success, writes a row to
    ExtraWorkStatusHistory and updates the cached timestamp
    columns. Wrapped in transaction.atomic with select_for_update
    so a concurrent transition cannot race past us.
    """
    if to_status not in ExtraWorkStatus.values:
        raise TransitionError(
            f"Unknown status '{to_status}'.", code="unknown_status"
        )

    if extra_work.status == to_status:
        raise TransitionError(
            f"Extra Work is already in status '{to_status}'.",
            code="no_op_transition",
        )

    key = (extra_work.status, to_status)
    if key not in ALLOWED_TRANSITIONS:
        raise TransitionError(
            f"Transition {extra_work.status} -> {to_status} is not allowed.",
            code="invalid_transition",
        )

    if not _user_can_drive_transition(user, extra_work, to_status):
        raise TransitionError(
            f"Not allowed to move Extra Work to '{to_status}'.",
            code="forbidden_transition",
        )

    # PRICING_PROPOSED requires at least one pricing line item — the
    # customer has nothing to approve otherwise.
    if to_status == ExtraWorkStatus.PRICING_PROPOSED:
        if not ExtraWorkPricingLineItem.objects.filter(
            extra_work=extra_work
        ).exists():
            raise TransitionError(
                "At least one pricing line item is required before "
                "proposing a price to the customer.",
                code="pricing_line_items_required",
            )

    # Provider override path — when a provider-side actor drives a
    # customer-decision transition, it is ALWAYS an override, even if
    # the client forgot to send is_override=true. This closes the
    # unsafe path where a provider could approve/reject a customer
    # pricing proposal without a written reason.
    #
    # When `user is None` (Sprint 29 Batch 29.8 system auto-sync hook)
    # the override-coercion below is skipped — system-driven
    # transitions are never customer-decision overrides.
    user_role = getattr(user, "role", None)
    provider_driven_customer_decision = (
        user_role
        in {
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        }
        and extra_work.status == ExtraWorkStatus.PRICING_PROPOSED
        and to_status
        in {
            ExtraWorkStatus.CUSTOMER_APPROVED,
            ExtraWorkStatus.CUSTOMER_REJECTED,
        }
    )
    if provider_driven_customer_decision:
        is_override = True

    # Sprint 29 Batch 29.8 — operational-segment override pairs that
    # always require an override_reason regardless of whether the
    # client sent `is_override=True`:
    #   IN_PROGRESS -> CANCELLED  (corrective cancel of in-flight work)
    #   COMPLETED  -> IN_PROGRESS (edge-recovery reopen)
    # System-driven transitions (`user is None`) are never these pairs;
    # `SYSTEM_AUTO_TRANSITIONS` only contains the two forward pairs.
    operational_provider_override = user is not None and (
        extra_work.status,
        to_status,
    ) in {
        (ExtraWorkStatus.IN_PROGRESS, ExtraWorkStatus.CANCELLED),
        (ExtraWorkStatus.COMPLETED, ExtraWorkStatus.IN_PROGRESS),
    }
    if operational_provider_override:
        is_override = True

    if is_override:
        if not override_reason.strip():
            raise TransitionError(
                "Override reason is required when a provider operator "
                "drives a customer-decision transition.",
                code="override_reason_required",
            )

    locked = ExtraWorkRequest.objects.select_for_update().get(pk=extra_work.pk)
    if locked.status != extra_work.status:
        raise TransitionError(
            "Extra Work status changed concurrently; please reload.",
            code="stale_status",
        )

    old_status = locked.status
    locked.status = to_status
    update_fields = ["status", "updated_at"]

    now = timezone.now()
    if to_status == ExtraWorkStatus.PRICING_PROPOSED:
        locked.pricing_proposed_at = now
        update_fields.append("pricing_proposed_at")
    if to_status in {
        ExtraWorkStatus.CUSTOMER_APPROVED,
        ExtraWorkStatus.CUSTOMER_REJECTED,
    }:
        locked.customer_decided_at = now
        update_fields.append("customer_decided_at")

    if is_override:
        locked.override_by = user
        locked.override_reason = override_reason
        locked.override_at = now
        update_fields.extend(["override_by", "override_reason", "override_at"])

    locked.save(update_fields=update_fields)

    ExtraWorkStatusHistory.objects.create(
        extra_work=locked,
        old_status=old_status,
        new_status=to_status,
        changed_by=user,
        note=note or "",
        is_override=is_override,
    )

    # Sprint 30 Batch 30.1 — legacy pricing-flow ticket spawn.
    # When an EW lands in CUSTOMER_APPROVED via the legacy pricing path
    # (PRICING_PROPOSED -> CUSTOMER_APPROVED, customer-driven OR
    # provider-overridden), spawn one operational Ticket per cart line
    # so the operational dashboard / scope filters surface the work
    # immediately. The new Proposal flow bypasses apply_transition and
    # owns its own spawn via `proposal_state_machine.
    # apply_proposal_transition`; this hook only fires on the legacy
    # path. Idempotency on `extra_work_request_item` guarantees a
    # no-op if proposal-flow tickets already exist (unusual but
    # defensive).
    #
    # Error propagation: any failure here bubbles up — the spawn IS
    # part of the customer-approval contract. The surrounding atomic
    # block rolls back the EW status + history row together.
    if (
        old_status == ExtraWorkStatus.PRICING_PROPOSED
        and to_status == ExtraWorkStatus.CUSTOMER_APPROVED
    ):
        # Lazy import to avoid a load-time cycle:
        # proposal_tickets imports proposal_state_machine which
        # imports models which imports state_machine.
        from .proposal_tickets import spawn_tickets_for_extra_work_request

        spawn_tickets_for_extra_work_request(locked, actor=user)

    return locked


def allowed_next_statuses(user, extra_work: ExtraWorkRequest) -> list[str]:
    """Return the list of statuses `user` may currently drive
    `extra_work` into. Used by the frontend to render only the
    buttons the actor is actually allowed to click."""
    return [
        to_status
        for (from_status, to_status) in ALLOWED_TRANSITIONS
        if from_status == extra_work.status
        and _user_can_drive_transition(user, extra_work, to_status)
    ]
