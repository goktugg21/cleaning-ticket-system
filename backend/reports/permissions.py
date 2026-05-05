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
