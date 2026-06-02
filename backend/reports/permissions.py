from rest_framework.permissions import BasePermission

from accounts.models import UserRole


class IsReportsConsumer(BasePermission):
    """
    Reports are visible to SUPER_ADMIN, COMPANY_ADMIN, and BUILDING_MANAGER.
    CUSTOMER_USER is denied (returns 403). Unauthenticated requests return 401
    (handled by DRF's IsAuthenticated combined upstream).
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.role in {
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        }


class IsRevenueReportConsumer(BasePermission):
    """
    Commercial Extra Work revenue report (Sprint 14A).

    Provider-management only — SUPER_ADMIN, COMPANY_ADMIN, BUILDING_MANAGER.
    STAFF and CUSTOMER_USER are BOTH denied (403): the report exposes
    commercial amounts, which STAFF must never see (privacy floor) and
    which are provider-internal to every customer-side role.

    The admit set is intentionally identical to `IsReportsConsumer` (which
    already excludes STAFF + CUSTOMER_USER); this dedicated class documents
    the stricter commercial-amount intent so a future widening of the
    general reports admit set cannot silently leak revenue to STAFF.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.role in {
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        }
