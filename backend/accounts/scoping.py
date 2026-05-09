from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import Customer, CustomerUserMembership
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
        return CustomerUserMembership.objects.filter(user=user).values_list("customer__building_id", flat=True)

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
        building_ids = BuildingManagerAssignment.objects.filter(user=user).values_list("building_id", flat=True)
        return Customer.objects.filter(building_id__in=building_ids).values_list("id", flat=True)

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
    # Sprint 12: every code path below filters deleted_at__isnull=True.
    # A soft-deleted ticket disappears from list, detail, search,
    # messages, attachments, stats, and reports for every role
    # (including SUPER_ADMIN — there is no archived-view UI yet, and
    # showing a deleted ticket in normal views would surprise the
    # operator). Hard SQL access in the Django admin or a future
    # archived-view endpoint can still see the row.
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
        customer_ids = CustomerUserMembership.objects.filter(user=user).values_list("customer_id", flat=True)
        return Ticket.objects.filter(deleted_at__isnull=True, customer_id__in=customer_ids)

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
