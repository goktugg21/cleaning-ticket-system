"""
P-4 — WHO MAY ANSWER THE CUSTOMER'S QUESTION, in one place.

`TicketDetailSerializer.get_actions` has answered
`can_override_customer_decision` per ticket since W11 §1 (SA; CA in
the ticket's company; BM assigned to the building AND holding the B6
revocable key), tightened to the decision phase (WAITING_CUSTOMER_-
APPROVAL with APPROVED / REJECTED reachable in the live machine).
The "Wacht op klant" drawer on My Schedule now surfaces the SAME
action where the work waits, so the rule moved here and both readers
call it. Nothing is widened: the serializer's answer is byte-for-byte
what it was, and the drawer's button renders only where the detail
page's Advanced fold would.
"""
from __future__ import annotations

from accounts.models import UserRole
from accounts.permissions_v2 import user_has_osius_permission
from buildings.models import BuildingManagerAssignment

from .models import TicketStatus

#: The B6 revocable key a Building Manager needs on top of the building
#: assignment. Mirrors `state_machine`'s BM override gate.
BM_OVERRIDE_KEY = "osius.building_manager.override_customer_decision"


def has_customer_decision_override_authority(user, ticket) -> bool:
    """SA anywhere; CA in the ticket's company; BM assigned to the
    building and holding the key. Precise to THIS ticket's building."""
    role = getattr(user, "role", None)
    if role == UserRole.SUPER_ADMIN:
        return True
    if role == UserRole.COMPANY_ADMIN:
        from companies.models import CompanyUserMembership

        return CompanyUserMembership.objects.filter(
            user=user, company_id=ticket.company_id
        ).exists()
    if role == UserRole.BUILDING_MANAGER:
        assigned = BuildingManagerAssignment.objects.filter(
            user=user, building_id=ticket.building_id
        ).exists()
        return bool(assigned) and user_has_osius_permission(
            user, BM_OVERRIDE_KEY, building_id=ticket.building_id
        )
    return False


def can_override_customer_decision(user, ticket, allowed_statuses) -> bool:
    """Authority AND the decision phase: the ticket stands at
    WAITING_CUSTOMER_APPROVAL and APPROVED or REJECTED is reachable in
    the live state machine for this user (`allowed_statuses`)."""
    allowed_set = {str(s) for s in allowed_statuses}
    in_decision_phase = str(ticket.status) == str(
        TicketStatus.WAITING_CUSTOMER_APPROVAL
    ) and (
        str(TicketStatus.APPROVED) in allowed_set
        or str(TicketStatus.REJECTED) in allowed_set
    )
    return in_decision_phase and has_customer_decision_override_authority(
        user, ticket
    )
