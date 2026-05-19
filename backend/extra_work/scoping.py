"""
Extra Work scoping.

Mirrors `accounts.scoping.scope_tickets_for` but for the
`ExtraWorkRequest` queryset. Customer-side keys are
`customer.extra_work.view_*` (vs ticket's `customer.ticket.view_*`).
Provider-side scope is identical to tickets (company / building /
super-admin gates) since the operational tenancy hierarchy is the
same.

Sprint 29 Batch 29.8 — STAFF visibility now reuses the ticket
scope. A STAFF user sees every Extra Work request whose spawned
tickets they can see (via either the cart-item path
`ExtraWorkRequestItem.spawned_tickets` or the proposal-line path
`ProposalLine.spawned_tickets_for_proposal_line`). No new
permission key is introduced — the gate is the existing
`scope_tickets_for(STAFF)` which composes TicketStaffAssignment
plus BuildingStaffVisibility (BUILDING_READ / BUILDING_READ_AND_ASSIGN).
EW rows without any spawned ticket the STAFF can see remain
invisible, preserving H-1 / H-4 by construction.
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
        # Sprint 29 Batch 29.8 — STAFF visibility is derived from the
        # tickets they can already see. An EW is visible to STAFF iff
        # AT LEAST ONE of its spawned tickets is in their
        # `scope_tickets_for` queryset. Two spawn paths exist:
        #   1) Cart-item path  -- Ticket.extra_work_request_item ->
        #      ExtraWorkRequestItem.extra_work_request_id (the FK is
        #      named `extra_work_request`, not `extra_work`).
        #   2) Proposal-line path -- Ticket.proposal_line ->
        #      ProposalLine.proposal -> Proposal.extra_work_request_id.
        # The two visible-EW id sets are unioned; the EW row is then
        # fetched (filtering soft-deleted out).
        from tickets.models import Ticket
        from accounts.scoping import scope_tickets_for

        visible_ticket_ids = scope_tickets_for(user).values_list(
            "id", flat=True
        )
        ew_ids_from_line_items = Ticket.objects.filter(
            id__in=visible_ticket_ids,
            extra_work_request_item__isnull=False,
        ).values_list(
            "extra_work_request_item__extra_work_request_id", flat=True
        )
        ew_ids_from_proposal_lines = Ticket.objects.filter(
            id__in=visible_ticket_ids,
            proposal_line__isnull=False,
        ).values_list(
            "proposal_line__proposal__extra_work_request_id", flat=True
        )
        visible_ew_ids = set(ew_ids_from_line_items) | set(
            ew_ids_from_proposal_lines
        )
        if not visible_ew_ids:
            return ExtraWorkRequest.objects.none()
        return ExtraWorkRequest.objects.filter(
            deleted_at__isnull=True,
            id__in=visible_ew_ids,
        )

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
