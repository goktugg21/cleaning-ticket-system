from django.db import transaction
from django.utils import timezone

from accounts.models import UserRole
from buildings.models import BuildingManagerAssignment
from companies.models import CompanyUserMembership
from customers.models import CustomerUserBuildingAccess

from .models import Ticket, TicketStatus, TicketStatusHistory


# Sprint 25C — OSIUS staff completion-evidence rule.
#
# When a ticket moves from IN_PROGRESS to WAITING_CUSTOMER_APPROVAL,
# at least one of the following MUST be true on the ticket:
#   1. The transition carries a non-empty note (note.strip()), or
#   2. The ticket already has ≥1 visible attachment, where "visible"
#      mirrors the existing customer-side attachment filter in
#      tickets/views.py:TicketAttachmentListCreateView — i.e. the row
#      itself is not is_hidden=True AND it is not attached to an
#      internal-note or is_hidden TicketMessage.
#
# Photos are strongly encouraged in the UI but the rule treats them
# as equivalent to a note: empty completion (no note + no visible
# attachment) is the only forbidden case. This matches the OSIUS
# product brief: "note only, photo only, note + photo all OK; no
# note + no photo rejected."
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
        UserRole.CUSTOMER_USER: SCOPE_CUSTOMER_LINKED,
    },
    (TicketStatus.WAITING_CUSTOMER_APPROVAL, TicketStatus.REJECTED): {
        UserRole.SUPER_ADMIN: SCOPE_ANY,
        UserRole.COMPANY_ADMIN: SCOPE_COMPANY_MEMBER,
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

    # Sprint 27F-B1 — provider-driven customer-decision transition is
    # ALWAYS an override. Mirrors `extra_work/state_machine.py:250-265`.
    # If a SUPER_ADMIN or COMPANY_ADMIN drives WAITING_CUSTOMER_APPROVAL
    # -> APPROVED / REJECTED, that is by definition a workflow override
    # of the customer's decision, even when the client forgot the flag.
    # We coerce here BEFORE the override-reason gate so the reason
    # requirement still fires.
    provider_driven_customer_decision = (
        getattr(user, "role", None)
        in {UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN}
        and str(ticket.status) == str(TicketStatus.WAITING_CUSTOMER_APPROVAL)
        and str(to_status)
        in {str(TicketStatus.APPROVED), str(TicketStatus.REJECTED)}
    )
    if provider_driven_customer_decision:
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

    # Sprint 25C — OSIUS staff-completion evidence rule. The role +
    # scope checks above already ran, so a 400 here is only ever
    # returned to an actor who would otherwise have been permitted
    # to perform the transition. Internal/hidden artefacts do not
    # satisfy the rule — they can't be shown to the customer, so
    # they are not "evidence the work happened" from the customer's
    # standpoint.
    if (str(ticket.status), str(to_status)) in {
        (str(a), str(b)) for (a, b) in COMPLETION_EVIDENCE_TRANSITIONS
    }:
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
    return locked


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
