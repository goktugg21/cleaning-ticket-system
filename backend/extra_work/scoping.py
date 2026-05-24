"""
Extra Work scoping.

Mirrors `accounts.scoping.scope_tickets_for` but for the
`ExtraWorkRequest` queryset. Customer-side keys are
`customer.extra_work.view_*` (vs ticket's `customer.ticket.view_*`).
Provider-side scope is identical to tickets (company / building /
super-admin gates) since the operational tenancy hierarchy is the
same.

STAFF visibility on `ExtraWorkRequest` is INTENTIONALLY EMPTY. Per
the 2026-05-20 business-logic decision (A4): STAFF must not list or
open parent Extra Work records through `/api/extra-work/`. STAFF
only sees operational work AFTER it has become an assigned ticket;
the parent EW remains commercial workflow that STAFF must not
reach. The Ticket detail surface carries an
`extra_work_origin` field which exposes a safe subset (parent id,
title, status, item id, service name) so STAFF can see "this
ticket came from EW #N" without ever touching the EW endpoints.

NOTE: Sprint 29 Batch 29.8 briefly widened STAFF scope here to
"any EW whose spawned ticket the staff can see". That widening was
reverted in the P0 staff-privacy patch (post-2026-05-20 audit) once
it was confirmed every EW + Proposal serializer gated only on
`_is_customer(user)` and therefore leaked provider-only fields
(`internal_cost_note`, `manager_note`, `override_*`, ProposalLine
`internal_note`, ProposalTimelineEvent `metadata`) to STAFF. The
chosen fix is "STAFF never reaches these endpoints" — narrower than
field stripping and removes a whole class of future drift bugs.
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
        # P0 staff-privacy fix (post-2026-05-20): STAFF must not reach
        # any parent Extra Work record. See module docstring above.
        # Operational visibility for STAFF lives on the spawned Ticket;
        # `Ticket.extra_work_origin` surfaces the small, safe metadata
        # subset.
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
