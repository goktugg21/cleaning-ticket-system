"""
Sprint 26B — Extra Work scoping.

Mirrors `accounts.scoping.scope_tickets_for` but for the
`ExtraWorkRequest` queryset. Customer-side keys are
`customer.extra_work.view_*` (vs ticket's `customer.ticket.view_*`).
Provider-side scope is identical to tickets (company / building /
super-admin gates) since the operational tenancy hierarchy is the
same.

STAFF visibility is intentionally MISSING in this MVP: the Sprint
26B brief defers the staff-execution surface (ASSIGNED /
IN_PROGRESS / WAITING_MANAGER_REVIEW / WAITING_CUSTOMER_APPROVAL /
COMPLETED statuses) to a follow-up sprint. Until those statuses
land, STAFF receives an empty queryset — the customer-pricing
loop never reaches STAFF eyes.
"""
from __future__ import annotations

from django.db import models

from accounts.models import UserRole
from buildings.models import BuildingManagerAssignment
from companies.models import CompanyUserMembership
from customers.models import CustomerUserBuildingAccess
from customers.permissions import access_has_permission

from .models import ExtraWorkRequest


def _is_anonymous(user) -> bool:
    return user is None or not getattr(user, "is_authenticated", False)


def scope_extra_work_for(user):
    """
    Return the queryset of ExtraWorkRequest rows visible to `user`.

    Soft-deleted requests (deleted_at IS NOT NULL) are filtered out
    of every list / detail / transition / pricing-item endpoint by
    every role.
    """
    if _is_anonymous(user):
        return ExtraWorkRequest.objects.none()

    if user.role == UserRole.SUPER_ADMIN:
        return ExtraWorkRequest.objects.filter(deleted_at__isnull=True)

    if user.role == UserRole.COMPANY_ADMIN:
        company_ids = CompanyUserMembership.objects.filter(
            user=user
        ).values_list("company_id", flat=True)
        return ExtraWorkRequest.objects.filter(
            deleted_at__isnull=True,
            company_id__in=company_ids,
        )

    if user.role == UserRole.BUILDING_MANAGER:
        building_ids = BuildingManagerAssignment.objects.filter(
            user=user
        ).values_list("building_id", flat=True)
        return ExtraWorkRequest.objects.filter(
            deleted_at__isnull=True,
            building_id__in=building_ids,
        )

    if user.role == UserRole.STAFF:
        # MVP: no staff-execution surface yet. STAFF cannot see any
        # Extra Work request. Will be revisited when ASSIGNED /
        # IN_PROGRESS statuses are added in the follow-up sprint.
        return ExtraWorkRequest.objects.none()

    if user.role == UserRole.CUSTOMER_USER:
        # Mirrors the Sprint 23A CUSTOMER_USER ticket scope but
        # against the `customer.extra_work.view_*` permission keys.
        view_company_customers: set[int] = set()
        view_location_pairs: set[tuple[int, int]] = set()
        view_own_pairs: set[tuple[int, int]] = set()

        for access in (
            CustomerUserBuildingAccess.objects.filter(
                membership__user=user, is_active=True
            )
            .select_related("membership")
            .only(
                "id",
                "access_role",
                "permission_overrides",
                "is_active",
                "building_id",
                "membership__customer_id",
            )
        ):
            cid = access.membership.customer_id
            bid = access.building_id
            if access_has_permission(access, "customer.extra_work.view_company"):
                view_company_customers.add(cid)
            elif access_has_permission(access, "customer.extra_work.view_location"):
                view_location_pairs.add((cid, bid))
            elif access_has_permission(access, "customer.extra_work.view_own"):
                view_own_pairs.add((cid, bid))

        if not (view_company_customers or view_location_pairs or view_own_pairs):
            return ExtraWorkRequest.objects.none()

        q = models.Q()
        if view_company_customers:
            q |= models.Q(customer_id__in=view_company_customers)
        for cid, bid in view_location_pairs:
            q |= models.Q(customer_id=cid, building_id=bid)
        if view_own_pairs:
            own_filter = models.Q()
            for cid, bid in view_own_pairs:
                own_filter |= models.Q(customer_id=cid, building_id=bid)
            q |= own_filter & models.Q(created_by=user)

        return ExtraWorkRequest.objects.filter(deleted_at__isnull=True).filter(q)

    return ExtraWorkRequest.objects.none()
