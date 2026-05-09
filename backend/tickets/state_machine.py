from django.db import transaction
from django.utils import timezone

from accounts.models import UserRole
from buildings.models import BuildingManagerAssignment
from companies.models import CompanyUserMembership
from customers.models import CustomerUserBuildingAccess

from .models import Ticket, TicketStatus, TicketStatusHistory


SCOPE_ANY = "any"
SCOPE_COMPANY_MEMBER = "company_member"
SCOPE_BUILDING_ASSIGNED = "building_assigned"
SCOPE_CUSTOMER_LINKED = "customer_linked"


ALLOWED_TRANSITIONS = {
    (TicketStatus.OPEN, TicketStatus.IN_PROGRESS): {
        UserRole.SUPER_ADMIN: SCOPE_ANY,
        UserRole.COMPANY_ADMIN: SCOPE_COMPANY_MEMBER,
        UserRole.BUILDING_MANAGER: SCOPE_BUILDING_ASSIGNED,
    },
    (TicketStatus.IN_PROGRESS, TicketStatus.WAITING_CUSTOMER_APPROVAL): {
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
def apply_transition(ticket, user, to_status, note=""):
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

    return [
        to_status
        for (from_status, to_status), role_scopes in ALLOWED_TRANSITIONS.items()
        if from_status == ticket.status
        and user.role in role_scopes
        and _user_passes_scope(user, ticket, role_scopes[user.role])
    ]
