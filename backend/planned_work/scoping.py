"""Planned-work scope helpers (Sprint 11B Batch 3).

Provider-only. RecurringJob templates and their materialized
PlannedOccurrence rows live entirely on the service-provider side, so
STAFF and CUSTOMER_USER resolve to an EMPTY queryset here — there is no
customer-facing planned-work API. Mirrors the company/building anchor
pattern in `accounts.scoping` (CompanyUserMembership /
BuildingManagerAssignment).
"""
from __future__ import annotations

from buildings.models import BuildingManagerAssignment
from companies.models import CompanyUserMembership

from accounts.models import UserRole

from .models import PlannedOccurrence, RecurringJob


def _is_anonymous(user) -> bool:
    return user is None or not getattr(user, "is_authenticated", False)


def scope_recurring_jobs_for(user):
    """Return the RecurringJob queryset visible to `user`.

    SUPER_ADMIN -> all; COMPANY_ADMIN -> jobs in their provider
    companies; BUILDING_MANAGER -> jobs in their assigned buildings;
    STAFF / CUSTOMER_USER / anonymous -> none (provider-only surface).
    """
    if _is_anonymous(user):
        return RecurringJob.objects.none()

    if user.role == UserRole.SUPER_ADMIN:
        return RecurringJob.objects.all()

    if user.role == UserRole.COMPANY_ADMIN:
        company_ids = CompanyUserMembership.objects.filter(
            user=user
        ).values_list("company_id", flat=True)
        return RecurringJob.objects.filter(company_id__in=company_ids)

    if user.role == UserRole.BUILDING_MANAGER:
        building_ids = BuildingManagerAssignment.objects.filter(
            user=user
        ).values_list("building_id", flat=True)
        return RecurringJob.objects.filter(building_id__in=building_ids)

    return RecurringJob.objects.none()


def scope_planned_occurrences_for(user):
    """Return the PlannedOccurrence queryset visible to `user`.

    Same shape as `scope_recurring_jobs_for` on the occurrence's
    denormalized scope FKs. STAFF / CUSTOMER_USER / anonymous -> none.
    """
    if _is_anonymous(user):
        return PlannedOccurrence.objects.none()

    if user.role == UserRole.SUPER_ADMIN:
        return PlannedOccurrence.objects.all()

    if user.role == UserRole.COMPANY_ADMIN:
        company_ids = CompanyUserMembership.objects.filter(
            user=user
        ).values_list("company_id", flat=True)
        return PlannedOccurrence.objects.filter(company_id__in=company_ids)

    if user.role == UserRole.BUILDING_MANAGER:
        building_ids = BuildingManagerAssignment.objects.filter(
            user=user
        ).values_list("building_id", flat=True)
        return PlannedOccurrence.objects.filter(building_id__in=building_ids)

    return PlannedOccurrence.objects.none()
