from django.db import transaction
from django.utils import timezone

from accounts.models import UserRole
from buildings.models import BuildingManagerAssignment
from companies.models import CompanyUserMembership
from customers.models import CustomerUserMembership

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
        UserRole.CUSTOMER_USER: SCOPE_CUSTOMER_LINKED,
    },
    (TicketStatus.WAITING_CUSTOMER_APPROVAL, TicketStatus.REJECTED): {
        UserRole.SUPER_ADMIN: SCOPE_ANY,
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


TIMESTAMP_ON_ENTER = {
    TicketStatus.WAITING_CUSTOMER_APPROVAL: "sent_for_approval_at",
    TicketStatus.APPROVED: "approved_at",
    TicketStatus.REJECTED: "rejected_at",
    TicketStatus.CLOSED: "closed_at",
}


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
        return CustomerUserMembership.objects.filter(user=user, customer_id=ticket.customer_id).exists()
    return False


def can_transition(user, ticket, to_status):
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
    timestamp_field = TIMESTAMP_ON_ENTER.get(to_status)
    if timestamp_field:
        setattr(locked, timestamp_field, timezone.now())
        update_fields.append(timestamp_field)

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
    return [
        to_status
        for (from_status, to_status), role_scopes in ALLOWED_TRANSITIONS.items()
        if from_status == ticket.status
        and user.role in role_scopes
        and _user_passes_scope(user, ticket, role_scopes[user.role])
    ]
