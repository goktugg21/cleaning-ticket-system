from rest_framework.permissions import BasePermission

from accounts.models import UserRole
from accounts.permissions import (
    IsAuthenticatedAndActive,
    is_provider_management_role,
    is_staff_role,
)
from accounts.scoping import company_admin_customer_ids, scope_tickets_for
from buildings.models import BuildingManagerAssignment, BuildingStaffVisibility
from companies.models import CompanyUserMembership
from customers.models import CustomerUserBuildingAccess


class CanViewTicket(IsAuthenticatedAndActive):
    def has_object_permission(self, request, view, obj):
        return scope_tickets_for(request.user).filter(pk=obj.pk).exists()


class CanCreateTicket(IsAuthenticatedAndActive):
    """
    Any authenticated active user can attempt creation; per-row validation
    (must have scope on the chosen building/customer) lives in the serializer.
    """

    pass


class CanPostMessage(IsAuthenticatedAndActive):
    def has_permission(self, request, view):
        return super().has_permission(request, view)

    def has_object_permission(self, request, view, obj):
        # obj is the parent Ticket. The viewset enforces the parent lookup.
        return scope_tickets_for(request.user).filter(pk=obj.pk).exists()


def user_has_scope_for_ticket(user, ticket):
    if user.role == UserRole.SUPER_ADMIN:
        return True
    if user.role == UserRole.COMPANY_ADMIN:
        return CompanyUserMembership.objects.filter(user=user, company_id=ticket.company_id).exists()
    if user.role == UserRole.BUILDING_MANAGER:
        return BuildingManagerAssignment.objects.filter(user=user, building_id=ticket.building_id).exists()
    if user.role == UserRole.STAFF:
        # Sprint 23A: STAFF gets ticket scope via either an explicit
        # assignment (TicketStaffAssignment) OR a building-wide
        # visibility row. This mirrors the union scope_tickets_for
        # computes for STAFF — keeping this helper in sync prevents
        # the messages / attachments serializers from over-blocking
        # staff who DO have read access to the ticket.
        from tickets.models import TicketStaffAssignment

        if TicketStaffAssignment.objects.filter(
            ticket=ticket, user=user
        ).exists():
            return True
        return BuildingStaffVisibility.objects.filter(
            user=user, building_id=ticket.building_id
        ).exists()
    if user.role == UserRole.CUSTOMER_USER:
        # SoT Addendum A.1 — a company-wide Customer Company Admin (the
        # membership `is_company_admin` flag) is in scope for EVERY ticket
        # of every customer they administer, with no per-building access
        # row required. Mirrors the company_admin_customer_ids union in
        # scope_tickets_for so the two helpers stay in lockstep (a CCA can
        # post messages / attachments + drive transitions on any ticket).
        if ticket.customer_id in company_admin_customer_ids(user):
            return True
        # Sprint 23A (corrected before PR #50): mirror the resolver
        # logic in `accounts.scoping.scope_tickets_for`. The two
        # helpers MUST agree — anything visible on the list endpoint
        # is actionable here (messages, attachments, status); anything
        # hidden from the list is also blocked here.
        #
        # Resolution order on each active access row:
        #   - view_company  → grants pair scope for ANY building of
        #                     the customer.
        #   - view_location → grants pair scope at the access row's
        #                     building.
        #   - view_own      → grants pair scope at the access row's
        #                     building, but ONLY if the user created
        #                     the ticket.
        from customers.permissions import access_has_permission

        accesses = list(
            CustomerUserBuildingAccess.objects.filter(
                membership__user=user,
                membership__customer_id=ticket.customer_id,
                is_active=True,
            ).select_related("membership")
        )
        if not accesses:
            return False
        for access in accesses:
            if access_has_permission(access, "customer.ticket.view_company"):
                return True
        for access in accesses:
            if access.building_id != ticket.building_id:
                continue
            if access_has_permission(access, "customer.ticket.view_location"):
                return True
            if access_has_permission(
                access, "customer.ticket.view_own"
            ) and ticket.created_by_id == user.id:
                return True
        return False
    return False


def message_type_visible_to_user(user, message_type):
    """ROLE-based read visibility for a `TicketMessage.message_type`.

    Mirrors the role branches of
    `TicketMessageListCreateView.get_queryset` (B7 four-tier taxonomy):

      * provider management (SA / COMPANY_ADMIN / BUILDING_MANAGER) —
        every tier, including INTERNAL_NOTE.
      * STAFF — every tier EXCEPT INTERNAL_NOTE.
      * customer-side / anyone else — PUBLIC_REPLY + STAFF_COMPLETION only.

    This is the ROLE gate only. Ticket SCOPE (scope_tickets_for /
    user_has_scope_for_ticket) is checked separately by callers. Used by
    M1 B1 to (a) validate `directed_to` targets and (b) belt-and-suspenders
    filter notification recipients so an INTERNAL_NOTE / STAFF_OPERATIONAL
    can never notify a role that cannot read it.
    """
    # Local import: tickets.models may import this module transitively;
    # keep the enum reference lazy to avoid an import-time cycle.
    from tickets.models import TicketMessageType

    if is_provider_management_role(user):
        return True
    if is_staff_role(user):  # STAFF only — management handled above.
        return message_type != TicketMessageType.INTERNAL_NOTE
    return message_type in (
        TicketMessageType.PUBLIC_REPLY,
        TicketMessageType.STAFF_COMPLETION,
    )
