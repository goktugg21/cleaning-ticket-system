"""
Sprint 26B — Extra Work state machine (MVP customer-pricing loop).

Allowed transitions:

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

Operational-execution statuses (ASSIGNED / IN_PROGRESS /
WAITING_MANAGER_REVIEW / WAITING_CUSTOMER_APPROVAL / COMPLETED) are
NOT covered here per the Sprint 26B brief. They land with the
staff-execution sprint that follows.
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
    """
    from_status = extra_work.status

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
    provider_driven_customer_decision = (
        user.role
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
