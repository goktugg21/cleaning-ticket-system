import logging

from django.db import transaction
from django.utils import timezone

from accounts.models import UserRole
from buildings.models import BuildingManagerAssignment
from companies.models import CompanyUserMembership
from customers.models import CustomerUserBuildingAccess

from .models import Ticket, TicketStatus, TicketStatusHistory


logger = logging.getLogger(__name__)


# Sprint 25C — staff completion-evidence rule.
#
# When a STAFF user moves a ticket from IN_PROGRESS to
# WAITING_CUSTOMER_APPROVAL (or to WAITING_MANAGER_REVIEW via the
# Sprint 28 Batch 11 route), at least one of the following MUST be
# true on the ticket:
#   1. The transition carries a non-empty note (note.strip()), or
#   2. The ticket already has ≥1 visible attachment, where "visible"
#      mirrors the existing customer-side attachment filter in
#      tickets/views.py:TicketAttachmentListCreateView — i.e. the row
#      itself is not is_hidden=True AND it is not attached to an
#      internal-note or is_hidden TicketMessage.
#
# Photos are strongly encouraged in the UI but the rule treats them
# as equivalent to a note: empty completion (no note + no visible
# attachment) is the only forbidden case for STAFF.
#
# B1 (system-business-logic-and-workflows.md §4.4): the rule applies
# ONLY when the actor is STAFF. Managers and admins driving the same
# transition (e.g. a BM completing a job on behalf of the staff
# member, or a SUPER_ADMIN closing out a stuck ticket) bypass the
# evidence gate. Sprint 25C's earlier "applies independently of
# role/scope" stance was wrong per the canonical business doc.
COMPLETION_EVIDENCE_TRANSITIONS = {
    (TicketStatus.IN_PROGRESS, TicketStatus.WAITING_CUSTOMER_APPROVAL),
    # Sprint 28 Batch 11 — STAFF default-route completion (sends the
    # ticket to manager review) is the same kind of "work-is-done"
    # transition and must carry the same evidence requirement so the
    # BM has something to review.
    (TicketStatus.IN_PROGRESS, TicketStatus.WAITING_MANAGER_REVIEW),
}


def _ticket_has_visible_attachment(ticket):
    """
    True iff the ticket has at least one TicketAttachment that a
    customer user would see. Imported locally to avoid a circular
    import between state_machine.py and models.py.
    """
    from .models import TicketAttachment, TicketMessageType

    qs = TicketAttachment.objects.filter(ticket=ticket, is_hidden=False)
    qs = qs.exclude(message__is_hidden=True)
    qs = qs.exclude(message__message_type=TicketMessageType.INTERNAL_NOTE)
    return qs.exists()


SCOPE_ANY = "any"
SCOPE_COMPANY_MEMBER = "company_member"
SCOPE_BUILDING_ASSIGNED = "building_assigned"
SCOPE_CUSTOMER_LINKED = "customer_linked"
# Sprint 28 Batch 11 — STAFF scope for the two new completion routes.
# A STAFF user may drive `IN_PROGRESS -> WAITING_MANAGER_REVIEW` (and,
# when the BSV flag is set, `IN_PROGRESS -> WAITING_CUSTOMER_APPROVAL`)
# only when they hold a `TicketStaffAssignment` row for the ticket.
# The routing-flag check inside `apply_transition` then decides which
# of the two STAFF-permitted targets is actually reachable.
SCOPE_STAFF_ASSIGNED = "staff_assigned"


ALLOWED_TRANSITIONS = {
    (TicketStatus.OPEN, TicketStatus.IN_PROGRESS): {
        UserRole.SUPER_ADMIN: SCOPE_ANY,
        UserRole.COMPANY_ADMIN: SCOPE_COMPANY_MEMBER,
        UserRole.BUILDING_MANAGER: SCOPE_BUILDING_ASSIGNED,
    },
    # Sprint 28 Batch 11 — STAFF default-route completion path. The
    # `apply_transition` routing-flag check below decides which of the
    # two STAFF-permitted IN_PROGRESS targets a given staff actually
    # reaches; provider operators may drive either target on-behalf
    # without going through the flag.
    (TicketStatus.IN_PROGRESS, TicketStatus.WAITING_MANAGER_REVIEW): {
        UserRole.SUPER_ADMIN: SCOPE_ANY,
        UserRole.COMPANY_ADMIN: SCOPE_COMPANY_MEMBER,
        UserRole.BUILDING_MANAGER: SCOPE_BUILDING_ASSIGNED,
        UserRole.STAFF: SCOPE_STAFF_ASSIGNED,
    },
    (TicketStatus.IN_PROGRESS, TicketStatus.WAITING_CUSTOMER_APPROVAL): {
        UserRole.SUPER_ADMIN: SCOPE_ANY,
        UserRole.COMPANY_ADMIN: SCOPE_COMPANY_MEMBER,
        UserRole.BUILDING_MANAGER: SCOPE_BUILDING_ASSIGNED,
        # Sprint 28 Batch 11 — gated by routing-flag in apply_transition.
        UserRole.STAFF: SCOPE_STAFF_ASSIGNED,
    },
    # Sprint 28 Batch 11 — BM accepts a staff completion and forwards
    # it to the customer for approval. STAFF cannot drive this leg;
    # H-5 (STAFF cannot approve customer-side decisions) extends here
    # to "STAFF cannot decide that their own work is good enough to
    # show the customer."
    (TicketStatus.WAITING_MANAGER_REVIEW, TicketStatus.WAITING_CUSTOMER_APPROVAL): {
        UserRole.SUPER_ADMIN: SCOPE_ANY,
        UserRole.COMPANY_ADMIN: SCOPE_COMPANY_MEMBER,
        UserRole.BUILDING_MANAGER: SCOPE_BUILDING_ASSIGNED,
    },
    # Sprint 28 Batch 11 — BM rejects a staff completion and sends it
    # back to IN_PROGRESS. A non-empty note is required (enforced at
    # both serializer + state-machine layer below).
    (TicketStatus.WAITING_MANAGER_REVIEW, TicketStatus.IN_PROGRESS): {
        UserRole.SUPER_ADMIN: SCOPE_ANY,
        UserRole.COMPANY_ADMIN: SCOPE_COMPANY_MEMBER,
        UserRole.BUILDING_MANAGER: SCOPE_BUILDING_ASSIGNED,
    },
    (TicketStatus.WAITING_CUSTOMER_APPROVAL, TicketStatus.APPROVED): {
        UserRole.SUPER_ADMIN: SCOPE_ANY,
        UserRole.COMPANY_ADMIN: SCOPE_COMPANY_MEMBER,
        # B1 (system-business-logic-and-workflows.md §4.3 + §6 + §7.2):
        # Building Manager may approve on behalf of the customer for
        # tickets in their assigned building. This is a provider-side
        # override and apply_transition coerces is_override=True +
        # demands override_reason for BM drivers — see the
        # `provider_driven_customer_decision` block below.
        UserRole.BUILDING_MANAGER: SCOPE_BUILDING_ASSIGNED,
        UserRole.CUSTOMER_USER: SCOPE_CUSTOMER_LINKED,
    },
    (TicketStatus.WAITING_CUSTOMER_APPROVAL, TicketStatus.REJECTED): {
        UserRole.SUPER_ADMIN: SCOPE_ANY,
        UserRole.COMPANY_ADMIN: SCOPE_COMPANY_MEMBER,
        # B1 mirror: BM reject-on-behalf, same override + reason gate.
        UserRole.BUILDING_MANAGER: SCOPE_BUILDING_ASSIGNED,
        UserRole.CUSTOMER_USER: SCOPE_CUSTOMER_LINKED,
    },
    (TicketStatus.REJECTED, TicketStatus.IN_PROGRESS): {
        UserRole.SUPER_ADMIN: SCOPE_ANY,
        UserRole.COMPANY_ADMIN: SCOPE_COMPANY_MEMBER,
        UserRole.BUILDING_MANAGER: SCOPE_BUILDING_ASSIGNED,
    },
    (TicketStatus.APPROVED, TicketStatus.CLOSED): {
        UserRole.SUPER_ADMIN: SCOPE_ANY,
        UserRole.COMPANY_ADMIN: SCOPE_COMPANY_MEMBER,
    },
    (TicketStatus.CLOSED, TicketStatus.REOPENED_BY_ADMIN): {
        UserRole.SUPER_ADMIN: SCOPE_ANY,
        UserRole.COMPANY_ADMIN: SCOPE_COMPANY_MEMBER,
    },
    (TicketStatus.REOPENED_BY_ADMIN, TicketStatus.IN_PROGRESS): {
        UserRole.SUPER_ADMIN: SCOPE_ANY,
        UserRole.COMPANY_ADMIN: SCOPE_COMPANY_MEMBER,
        UserRole.BUILDING_MANAGER: SCOPE_BUILDING_ASSIGNED,
    },
}


# Each entry stamps the field with the most-recent timestamp on entry to that
# status. Loop transitions (REJECTED -> IN_PROGRESS -> WAITING_CUSTOMER_APPROVAL
# -> APPROVED again) overwrite the value. For first/last/duration analytics use
# TicketStatusHistory, which records every transition.
TIMESTAMP_ON_ENTER = {
    TicketStatus.WAITING_CUSTOMER_APPROVAL: "sent_for_approval_at",
    # Sprint 28 Batch 11 — stamped when a STAFF (or provider operator
    # acting on-behalf) completes work that routes through the manager
    # review interstitial.
    TicketStatus.WAITING_MANAGER_REVIEW: "manager_review_at",
    TicketStatus.APPROVED: "approved_at",
    TicketStatus.REJECTED: "rejected_at",
    TicketStatus.CLOSED: "closed_at",
}

# resolved_at means "work is done, awaiting close" and is stamped on entry to
# APPROVED. Same loop-overwrite semantics as TIMESTAMP_ON_ENTER.
RESOLVED_AT_ON_STATUS = {TicketStatus.APPROVED}


class TransitionError(Exception):
    def __init__(self, message, code="invalid_transition"):
        super().__init__(message)
        self.code = code


def _user_passes_scope(user, ticket, scope):
    if scope == SCOPE_ANY:
        return True
    if scope == SCOPE_COMPANY_MEMBER:
        return CompanyUserMembership.objects.filter(user=user, company_id=ticket.company_id).exists()
    if scope == SCOPE_BUILDING_ASSIGNED:
        return BuildingManagerAssignment.objects.filter(user=user, building_id=ticket.building_id).exists()
    if scope == SCOPE_CUSTOMER_LINKED:
        # Sprint 15: customer-user transitions (approve / reject) require
        # the EXACT (customer, building) pair access, not just any
        # CustomerUserMembership for the customer. A user with membership
        # to Customer X but only CustomerUserBuildingAccess for B3 must
        # not be able to approve a B1 ticket of the same customer. This
        # mirrors accounts/scoping.py::scope_tickets_for so visibility
        # and action authority stay aligned.
        return CustomerUserBuildingAccess.objects.filter(
            membership__user=user,
            membership__customer_id=ticket.customer_id,
            building_id=ticket.building_id,
        ).exists()
    if scope == SCOPE_STAFF_ASSIGNED:
        # Sprint 28 Batch 11 — STAFF may drive a completion only when
        # they hold an explicit `TicketStaffAssignment` row for the
        # ticket. The follow-on routing-flag check in `apply_transition`
        # then picks the right target between WAITING_MANAGER_REVIEW
        # and WAITING_CUSTOMER_APPROVAL.
        from .models import TicketStaffAssignment

        return TicketStaffAssignment.objects.filter(
            ticket=ticket, user=user
        ).exists()
    return False


def can_transition(user, ticket, to_status):
    # SUPER_ADMIN_CAN_TRANSITION_ANY_STATUS
    if getattr(user, "role", None) == UserRole.SUPER_ADMIN:
        return str(to_status) != str(ticket.status)

    key = (ticket.status, to_status)
    role_scopes = ALLOWED_TRANSITIONS.get(key)
    if role_scopes is None:
        return False
    scope = role_scopes.get(user.role)
    if scope is None:
        return False
    return _user_passes_scope(user, ticket, scope)


@transaction.atomic
def apply_transition(
    ticket,
    user,
    to_status,
    note="",
    *,
    is_override: bool = False,
    override_reason: str = "",
):
    if to_status not in TicketStatus.values:
        raise TransitionError(f"Unknown status '{to_status}'.", code="unknown_status")

    if ticket.status == to_status:
        raise TransitionError(
            f"Ticket is already in status '{to_status}'.", code="no_op_transition"
        )

    if not can_transition(user, ticket, to_status):
        raise TransitionError(
            f"Transition {ticket.status} -> {to_status} not allowed for role {user.role}.",
            code="forbidden_transition",
        )

    # Sprint 27F-B1 + B1 (system-business-logic-and-workflows.md §4.3
    # + §6) — provider-driven customer-decision transition is ALWAYS an
    # override. Mirrors `extra_work/state_machine.py` coercion. If a
    # SUPER_ADMIN, COMPANY_ADMIN, or BUILDING_MANAGER drives
    # WAITING_CUSTOMER_APPROVAL -> APPROVED / REJECTED, that is by
    # definition a workflow override of the customer's decision, even
    # when the client forgot the flag. We coerce here BEFORE the
    # override-reason gate so the reason requirement still fires.
    # B1 added BUILDING_MANAGER to this coercion set because the
    # business doc explicitly admits BM to act on behalf of the
    # customer (typical case: customer approves verbally / by phone).
    provider_driven_customer_decision = (
        getattr(user, "role", None)
        in {
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        }
        and str(ticket.status) == str(TicketStatus.WAITING_CUSTOMER_APPROVAL)
        and str(to_status)
        in {str(TicketStatus.APPROVED), str(TicketStatus.REJECTED)}
    )
    if provider_driven_customer_decision:
        # B6 — BM customer-decision override is revocable per-(BM,
        # building) via the new `osius.building_manager.
        # override_customer_decision` key. The resolver checks the
        # BM's BuildingManagerAssignment row's `permission_overrides`;
        # when the key is explicitly `False`, the BM can no longer
        # approve / reject on behalf of the customer on this building.
        # SA and COMPANY_ADMIN always resolve True (their power is not
        # revocable through this surface).
        if getattr(user, "role", None) == UserRole.BUILDING_MANAGER:
            from accounts.permissions_v2 import user_has_osius_permission

            if not user_has_osius_permission(
                user,
                "osius.building_manager.override_customer_decision",
                building_id=ticket.building_id,
            ):
                raise TransitionError(
                    "Building Manager's customer-decision override "
                    "has been disabled for this building. Contact a "
                    "Provider Admin to re-enable it.",
                    code="bm_override_disabled",
                )
        is_override = True

    if is_override and not override_reason.strip():
        raise TransitionError(
            "Override reason is required when a provider operator "
            "drives a customer-decision transition.",
            code="override_reason_required",
        )

    # Sprint 28 Batch 11 — STAFF completion routing-flag check.
    # The per-(staff, building) flag on BuildingStaffVisibility decides
    # which of the two STAFF-permitted IN_PROGRESS -> {WAITING_MANAGER_REVIEW,
    # WAITING_CUSTOMER_APPROVAL} transitions is actually reachable.
    # Mismatch -> 400 with a stable code. Provider operators driving the
    # same transition on-behalf bypass this gate — the flag is a STAFF-only
    # routing policy.
    if (
        getattr(user, "role", None) == UserRole.STAFF
        and str(ticket.status) == str(TicketStatus.IN_PROGRESS)
        and str(to_status) in {
            str(TicketStatus.WAITING_MANAGER_REVIEW),
            str(TicketStatus.WAITING_CUSTOMER_APPROVAL),
        }
    ):
        from buildings.models import BuildingStaffVisibility

        bsv = BuildingStaffVisibility.objects.filter(
            user=user, building_id=ticket.building_id
        ).first()
        routes_to_customer = bool(
            bsv and bsv.staff_completion_routes_to_customer
        )
        expected_target = (
            TicketStatus.WAITING_CUSTOMER_APPROVAL
            if routes_to_customer
            else TicketStatus.WAITING_MANAGER_REVIEW
        )
        if str(to_status) != str(expected_target):
            raise TransitionError(
                "Staff completion route does not match the configured "
                "routing for this building.",
                code="staff_completion_route_mismatch",
            )

    # Sprint 28 Batch 11 — BM rejection of a staff completion requires a
    # non-empty note (mirrors the CUSTOMER_USER reject-note rule).
    # Defensive: also enforced at serializer layer (TicketStatusChangeSerializer);
    # this catches programmatic callers (Celery, management commands, etc.).
    if (
        str(ticket.status) == str(TicketStatus.WAITING_MANAGER_REVIEW)
        and str(to_status) == str(TicketStatus.IN_PROGRESS)
        and not (note and note.strip())
    ):
        raise TransitionError(
            "A note explaining the rejection is required when sending a "
            "staff-completed ticket back to in-progress.",
            code="rejection_note_required",
        )

    # Sprint 25C + B1 — staff-completion evidence rule. The role + scope
    # checks above already ran, so a 400 here is only ever returned to
    # an actor who would otherwise have been permitted to perform the
    # transition. Internal/hidden artefacts do not satisfy the rule —
    # they can't be shown to the customer, so they are not "evidence
    # the work happened" from the customer's standpoint.
    #
    # B1 (system-business-logic-and-workflows.md §4.4): the gate fires
    # ONLY for STAFF actors. Managers and admins driving the same
    # completion transition (BM closing out a job on behalf of an
    # absent staff member, SUPER_ADMIN unblocking a stuck ticket)
    # bypass the rule.
    if (
        getattr(user, "role", None) == UserRole.STAFF
        and (str(ticket.status), str(to_status))
        in {(str(a), str(b)) for (a, b) in COMPLETION_EVIDENCE_TRANSITIONS}
    ):
        if not (note and note.strip()) and not _ticket_has_visible_attachment(ticket):
            raise TransitionError(
                "Please leave a completion note or attach a photo of the "
                "completed work before sending this ticket for customer "
                "approval.",
                code="completion_evidence_required",
            )

    locked = Ticket.objects.select_for_update().get(pk=ticket.pk)
    if locked.status != ticket.status:
        raise TransitionError(
            "Ticket status changed concurrently; please reload.", code="stale_status"
        )

    old_status = locked.status
    locked.status = to_status

    update_fields = ["status", "updated_at"]
    now = timezone.now()
    timestamp_field = TIMESTAMP_ON_ENTER.get(to_status)
    if timestamp_field:
        setattr(locked, timestamp_field, now)
        update_fields.append(timestamp_field)
    if to_status in RESOLVED_AT_ON_STATUS:
        locked.resolved_at = now
        update_fields.append("resolved_at")

    locked.save(update_fields=update_fields)
    locked.mark_first_response_if_needed()

    TicketStatusHistory.objects.create(
        ticket=locked,
        old_status=old_status,
        new_status=to_status,
        changed_by=user,
        note=note or "",
        is_override=is_override,
        override_reason=override_reason if is_override else "",
    )

    # Sprint 29 Batch 29.8 — sync parent EW state.
    _sync_parent_extra_work_after_ticket_transition(locked, old_status, to_status)

    return locked


def _sync_parent_extra_work_after_ticket_transition(
    ticket, old_status, new_status
):
    """
    Sprint 29 Batch 29.8 — auto-sync hook.

    Called from inside `apply_transition` AFTER the Ticket row has been
    saved and the TicketStatusHistory row has been written. Resolves
    the ticket's parent ExtraWorkRequest (via either the cart-item
    `extra_work_request_item` FK or the proposal-line FK chain) and
    advances the EW status when the operational rules below fire:

      1. Ticket entered IN_PROGRESS AND parent EW is CUSTOMER_APPROVED
         -> drive EW to IN_PROGRESS (system, user=None).
      2. Ticket entered a terminal state (APPROVED or CLOSED) AND
         parent EW is IN_PROGRESS AND every sibling-ticket of the EW
         (across BOTH spawn paths) is in {APPROVED, CLOSED} -> drive
         EW to COMPLETED.

    By design this helper NEVER re-raises. Any exception is logged
    (`logger.exception`) and swallowed; a transient EW sync failure
    must not roll back a successful ticket transition. The
    `extra_work.state_machine.apply_transition` call itself is
    `@transaction.atomic`-wrapped, so the EW state mutation + EW
    history row remain atomic with respect to each other.
    """
    try:
        # Inline imports defend against circular import risk between
        # the tickets and extra_work apps.
        from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
        from extra_work.state_machine import (
            apply_transition as ew_apply_transition,
        )

        ew_id = None
        if ticket.extra_work_request_item_id is not None:
            # Cart-item path.
            ew_id = (
                Ticket.objects.filter(pk=ticket.pk)
                .values_list(
                    "extra_work_request_item__extra_work_request_id",
                    flat=True,
                )
                .first()
            )
        if ew_id is None and ticket.proposal_line_id is not None:
            # Proposal-line path.
            ew_id = (
                Ticket.objects.filter(pk=ticket.pk)
                .values_list(
                    "proposal_line__proposal__extra_work_request_id",
                    flat=True,
                )
                .first()
            )

        if ew_id is None:
            return  # Ticket is not parented by any EW; nothing to sync.

        ew = ExtraWorkRequest.objects.filter(
            pk=ew_id, deleted_at__isnull=True
        ).first()
        if ew is None:
            return  # Parent EW soft-deleted or missing; bail quietly.

        # Rule 1: first ticket going IN_PROGRESS while EW is
        # CUSTOMER_APPROVED advances EW to IN_PROGRESS.
        if (
            str(new_status) == str(TicketStatus.IN_PROGRESS)
            and ew.status == ExtraWorkStatus.CUSTOMER_APPROVED
        ):
            ew_apply_transition(
                ew,
                None,
                ExtraWorkStatus.IN_PROGRESS,
                note=(
                    "Auto-advanced by ticket transition to IN_PROGRESS "
                    "(Sprint 29 Batch 29.8)."
                ),
            )
            return

        # Rule 2: ticket becoming terminal + EW in IN_PROGRESS + all
        # siblings terminal -> EW to COMPLETED. Sibling enumeration
        # spans both spawn paths and uses set() for natural de-dup.
        terminal_ticket_statuses = {
            str(TicketStatus.APPROVED),
            str(TicketStatus.CLOSED),
        }
        if (
            str(new_status) in terminal_ticket_statuses
            and ew.status == ExtraWorkStatus.IN_PROGRESS
        ):
            sibling_qs = Ticket.objects.filter(
                extra_work_request_item__extra_work_request_id=ew.id
            ) | Ticket.objects.filter(
                proposal_line__proposal__extra_work_request_id=ew.id
            )
            sibling_statuses = set(
                sibling_qs.values_list("status", flat=True)
            )
            # Empty sibling set is impossible — the current ticket is
            # in the set. If every sibling is terminal we advance.
            if sibling_statuses and sibling_statuses.issubset(
                terminal_ticket_statuses
            ):
                ew_apply_transition(
                    ew,
                    None,
                    ExtraWorkStatus.COMPLETED,
                    note=(
                        "Auto-advanced by all spawned tickets reaching "
                        "a terminal state (Sprint 29 Batch 29.8)."
                    ),
                )
    except Exception:  # noqa: BLE001 — never break ticket transitions.
        logger.exception(
            "Sprint 29 Batch 29.8 EW auto-sync failed for ticket %s "
            "(old=%s, new=%s); swallowing.",
            getattr(ticket, "pk", "?"),
            old_status,
            new_status,
        )


def allowed_next_statuses(user, ticket):
    # SUPER_ADMIN_ALLOWED_NEXT_ALL_STATUSES
    if getattr(user, "role", None) == UserRole.SUPER_ADMIN:
        return [
            status
            for status, _label in TicketStatus.choices
            if str(status) != str(ticket.status)
        ]

    candidates = [
        to_status
        for (from_status, to_status), role_scopes in ALLOWED_TRANSITIONS.items()
        if from_status == ticket.status
        and user.role in role_scopes
        and _user_passes_scope(user, ticket, role_scopes[user.role])
    ]

    # Sprint 28 Batch 11 UX hotfix — STAFF on IN_PROGRESS has TWO
    # structurally-allowed completion targets in `ALLOWED_TRANSITIONS`
    # (`WAITING_MANAGER_REVIEW` and `WAITING_CUSTOMER_APPROVAL`), but
    # only ONE is actually reachable at runtime — picked by the
    # `BuildingStaffVisibility.staff_completion_routes_to_customer`
    # flag and enforced by the routing-flag check in
    # `apply_transition` (`staff_completion_route_mismatch`).
    #
    # Without this narrowing, the API tells the frontend STAFF can
    # drive both targets, the frontend renders both as generic
    # "Move to X" buttons, and clicking the wrong one 400s. The fix
    # is to filter the candidate list to the single route-resolved
    # target so the API never advertises an unreachable transition.
    #
    # Provider operators (SUPER_ADMIN / COMPANY_ADMIN /
    # BUILDING_MANAGER) bypass this narrowing — they bypass the
    # flag check in `apply_transition` too and may drive either
    # target on-behalf.
    if (
        getattr(user, "role", None) == UserRole.STAFF
        and str(ticket.status) == str(TicketStatus.IN_PROGRESS)
    ):
        from buildings.models import BuildingStaffVisibility

        bsv = BuildingStaffVisibility.objects.filter(
            user=user, building_id=ticket.building_id
        ).first()
        routes_to_customer = bool(
            bsv and bsv.staff_completion_routes_to_customer
        )
        wanted = (
            TicketStatus.WAITING_CUSTOMER_APPROVAL
            if routes_to_customer
            else TicketStatus.WAITING_MANAGER_REVIEW
        )
        candidates = [
            target for target in candidates if str(target) == str(wanted)
        ]

    return candidates
