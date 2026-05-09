from django.db.models import Exists, OuterRef

from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from tickets.models import Ticket

from .models import UserRole


def _is_anonymous(user):
    return user is None or not getattr(user, "is_authenticated", False)


def company_ids_for(user):
    if _is_anonymous(user):
        return Company.objects.none().values_list("id", flat=True)

    if user.role == UserRole.SUPER_ADMIN:
        return Company.objects.values_list("id", flat=True)

    if user.role == UserRole.COMPANY_ADMIN:
        return CompanyUserMembership.objects.filter(user=user).values_list("company_id", flat=True)

    if user.role == UserRole.BUILDING_MANAGER:
        return BuildingManagerAssignment.objects.filter(user=user).values_list("building__company_id", flat=True)

    if user.role == UserRole.CUSTOMER_USER:
        return CustomerUserMembership.objects.filter(user=user).values_list("customer__company_id", flat=True)

    return Company.objects.none().values_list("id", flat=True)


def building_ids_for(user):
    if _is_anonymous(user):
        return Building.objects.none().values_list("id", flat=True)

    if user.role == UserRole.SUPER_ADMIN:
        return Building.objects.values_list("id", flat=True)

    if user.role == UserRole.COMPANY_ADMIN:
        company_ids = CompanyUserMembership.objects.filter(user=user).values_list("company_id", flat=True)
        return Building.objects.filter(company_id__in=company_ids).values_list("id", flat=True)

    if user.role == UserRole.BUILDING_MANAGER:
        return BuildingManagerAssignment.objects.filter(user=user).values_list("building_id", flat=True)

    if user.role == UserRole.CUSTOMER_USER:
        # Sprint 14: a customer-user only sees buildings explicitly granted
        # via CustomerUserBuildingAccess, never the customer's legacy
        # `building` FK. A customer-user with a CustomerUserMembership but
        # zero access rows sees zero buildings.
        return CustomerUserBuildingAccess.objects.filter(
            membership__user=user
        ).values_list("building_id", flat=True)

    return Building.objects.none().values_list("id", flat=True)


def customer_ids_for(user):
    if _is_anonymous(user):
        return Customer.objects.none().values_list("id", flat=True)

    if user.role == UserRole.SUPER_ADMIN:
        return Customer.objects.values_list("id", flat=True)

    if user.role == UserRole.COMPANY_ADMIN:
        company_ids = CompanyUserMembership.objects.filter(user=user).values_list("company_id", flat=True)
        return Customer.objects.filter(company_id__in=company_ids).values_list("id", flat=True)

    if user.role == UserRole.BUILDING_MANAGER:
        # Sprint 14: a building manager sees a customer if any of the
        # customer's M:N building links is one of the manager's assigned
        # buildings. We OR with the legacy single-building anchor so a
        # customer that has not yet been re-linked through the new admin
        # UI still appears for managers (the backfill covers existing
        # rows; this is defence in depth).
        building_ids = list(
            BuildingManagerAssignment.objects.filter(user=user).values_list(
                "building_id", flat=True
            )
        )
        via_membership = CustomerBuildingMembership.objects.filter(
            building_id__in=building_ids
        ).values_list("customer_id", flat=True)
        via_legacy = Customer.objects.filter(
            building_id__in=building_ids
        ).values_list("id", flat=True)
        return Customer.objects.filter(
            id__in=list(via_membership) + list(via_legacy)
        ).values_list("id", flat=True)

    if user.role == UserRole.CUSTOMER_USER:
        return CustomerUserMembership.objects.filter(user=user).values_list("customer_id", flat=True)

    return Customer.objects.none().values_list("id", flat=True)


def scope_companies_for(user):
    if _is_anonymous(user):
        return Company.objects.none()
    if user.role == UserRole.SUPER_ADMIN:
        return Company.objects.all()
    # Non-super-admin reads are limited to active tenants. Super admins still
    # see archived rows so they can re-activate or audit them.
    return Company.objects.filter(
        id__in=list(company_ids_for(user)),
        is_active=True,
    ).distinct()


def scope_buildings_for(user):
    if _is_anonymous(user):
        return Building.objects.none()
    if user.role == UserRole.SUPER_ADMIN:
        return Building.objects.all()
    return Building.objects.filter(
        id__in=list(building_ids_for(user)),
        is_active=True,
    ).distinct()


def scope_customers_for(user):
    if _is_anonymous(user):
        return Customer.objects.none()
    if user.role == UserRole.SUPER_ADMIN:
        return Customer.objects.all()
    return Customer.objects.filter(
        id__in=list(customer_ids_for(user)),
        is_active=True,
    ).distinct()


def scope_tickets_for(user):
    """
    Return the queryset of tickets visible to `user`.

    Sprint 12: every code path filters `deleted_at__isnull=True`. A
    soft-deleted ticket disappears from list, detail, search, messages,
    attachments, stats, and reports for every role.

    Sprint 14: CUSTOMER_USER scoping is now the *intersection* of
    customer membership and per-building access. A user with
    CustomerUserMembership(customer=X) and CustomerUserBuildingAccess
    rows pointing at buildings B1, B3 sees tickets only where
    `(ticket.customer, ticket.building) == (X, B1)` or `(X, B3)` —
    not `(X, B2)`, even though B2 might be linked to customer X via
    CustomerBuildingMembership for some other user. The pair-check is
    enforced by an Exists subquery so a multi-customer user with
    different building access per customer cannot accidentally see a
    ticket whose pair isn't theirs.
    """
    if _is_anonymous(user):
        return Ticket.objects.none()

    if user.role == UserRole.SUPER_ADMIN:
        return Ticket.objects.filter(deleted_at__isnull=True)

    if user.role == UserRole.COMPANY_ADMIN:
        company_ids = CompanyUserMembership.objects.filter(user=user).values_list("company_id", flat=True)
        return Ticket.objects.filter(deleted_at__isnull=True, company_id__in=company_ids)

    if user.role == UserRole.BUILDING_MANAGER:
        building_ids = BuildingManagerAssignment.objects.filter(user=user).values_list("building_id", flat=True)
        return Ticket.objects.filter(deleted_at__isnull=True, building_id__in=building_ids)

    if user.role == UserRole.CUSTOMER_USER:
        access_pair_exists = CustomerUserBuildingAccess.objects.filter(
            membership__user=user,
            membership__customer_id=OuterRef("customer_id"),
            building_id=OuterRef("building_id"),
        )
        return (
            Ticket.objects.filter(deleted_at__isnull=True)
            .annotate(_has_access=Exists(access_pair_exists))
            .filter(_has_access=True)
        )

    return Ticket.objects.none()


def _user_in_actor_company(actor, target_user):
    """
    True if `target_user` has any membership in any of `actor`'s companies.

    Used by CanManageUser. Encapsulates the company-overlap check so callers
    do not duplicate the union-of-three-membership-types query.
    """
    actor_company_ids = list(
        CompanyUserMembership.objects.filter(user=actor).values_list("company_id", flat=True)
    )
    if not actor_company_ids:
        return False

    if CompanyUserMembership.objects.filter(
        user=target_user, company_id__in=actor_company_ids
    ).exists():
        return True
    if BuildingManagerAssignment.objects.filter(
        user=target_user, building__company_id__in=actor_company_ids
    ).exists():
        return True
    if CustomerUserMembership.objects.filter(
        user=target_user, customer__company_id__in=actor_company_ids
    ).exists():
        return True
    return False
