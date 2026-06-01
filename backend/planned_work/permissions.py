"""Planned-work DRF permission classes (Sprint 11B Batch 3).

The planned-work API is PROVIDER-ONLY. `IsProviderManager` rejects
STAFF and CUSTOMER_USER outright (403 on every method, including reads)
so there is no customer-facing planned-work surface and STAFF cannot
create / edit templates or occurrences. Object-level scope mirrors the
`tickets.permissions.CanViewTicket` shape: defer to the relevant scope
helper and check the object is in it.
"""
from __future__ import annotations

from accounts.models import UserRole
from accounts.permissions import IsAuthenticatedAndActive

from .scoping import scope_planned_occurrences_for, scope_recurring_jobs_for


_PROVIDER_MANAGE_ROLES = {
    UserRole.SUPER_ADMIN,
    UserRole.COMPANY_ADMIN,
    UserRole.BUILDING_MANAGER,
}


class IsProviderManager(IsAuthenticatedAndActive):
    """Admit only provider-management roles. STAFF + CUSTOMER_USER 403."""

    def has_permission(self, request, view):
        return (
            super().has_permission(request, view)
            and request.user.role in _PROVIDER_MANAGE_ROLES
        )


class CanManageRecurringJob(IsProviderManager):
    def has_object_permission(self, request, view, obj):
        return (
            scope_recurring_jobs_for(request.user).filter(pk=obj.pk).exists()
        )


class CanManagePlannedOccurrence(IsProviderManager):
    def has_object_permission(self, request, view, obj):
        return (
            scope_planned_occurrences_for(request.user)
            .filter(pk=obj.pk)
            .exists()
        )
