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


def filter_messages_visible_to(qs, user):
    """M1 B2 — the SINGLE chokepoint for TicketMessage read visibility.

    Every read / count / search path for TicketMessage must route through
    this helper so the rule cannot drift or be missed at one site. It AND-s
    two layers; each only ever NARROWS the queryset (it never widens):

      (a) B7 role / is_hidden filtering — byte-equivalent to the pre-B2
          inline `TicketMessageListCreateView.get_queryset` filter:
            * provider management (SA / CA / BM) — every tier including
              INTERNAL_NOTE and is_hidden moderation rows.
            * STAFF — every tier EXCEPT INTERNAL_NOTE; is_hidden dropped.
            * customer-side / other — PUBLIC_REPLY + STAFF_COMPLETION only;
              is_hidden dropped.
      (b) M1 B2 RESTRICTED party filter — applied UNCONDITIONALLY so it
          binds EVERY role, provider management included: a RESTRICTED
          message is visible iff the viewer is the author OR a directed_to
          member. NORMAL messages are unaffected. A non-party admin can
          neither read nor infer a RESTRICTED message anywhere this
          chokepoint is used.

    A userless / unauthenticated caller (defensive — these endpoints are
    auth-gated) is treated as a non-party: layer (a) treats them as
    non-management customer-side, and layer (b) leaves only NORMAL rows.
    """
    from django.db.models import Exists, OuterRef, Q

    from .models import (
        TicketMessage,
        TicketMessageType,
        TicketMessageVisibility,
    )

    user_id = getattr(user, "id", None)

    # (a) B7 role / is_hidden — only management sees every tier + hidden rows.
    if not is_provider_management_role(user):
        qs = qs.filter(is_hidden=False)
        qs = qs.exclude(message_type=TicketMessageType.INTERNAL_NOTE)
        if not is_staff_role(user):
            qs = qs.exclude(message_type=TicketMessageType.STAFF_OPERATIONAL)

    # (b) RESTRICTED party filter — unconditional. Uses Exists (a correlated
    # subquery, NOT a directed_to join) so there is no row fan-out / duplicate
    # rows, and never has to .distinct().
    if user_id is None:
        return qs.filter(visibility_mode=TicketMessageVisibility.NORMAL)

    through = TicketMessage.directed_to.through
    return qs.annotate(
        _directed_to_me=Exists(
            through.objects.filter(
                ticketmessage_id=OuterRef("pk"), user_id=user_id
            )
        )
    ).filter(
        Q(visibility_mode=TicketMessageVisibility.NORMAL)
        | Q(author_id=user_id)
        | Q(_directed_to_me=True)
    )
