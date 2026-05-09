from rest_framework.permissions import BasePermission

from accounts.models import UserRole
from accounts.permissions import IsAuthenticatedAndActive
from accounts.scoping import scope_tickets_for
from buildings.models import BuildingManagerAssignment
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
    if user.role == UserRole.CUSTOMER_USER:
        # Sprint 15: customer-users need the exact (customer, building)
        # pair access, matching scope_tickets_for. This function is
        # consulted by the messages and attachments serializers, so
        # without the pair check a customer-user with membership to
        # Customer X but no building access for B1 could post a
        # message on a B1 ticket of the same customer.
        return CustomerUserBuildingAccess.objects.filter(
            membership__user=user,
            membership__customer_id=ticket.customer_id,
            building_id=ticket.building_id,
        ).exists()
    return False
