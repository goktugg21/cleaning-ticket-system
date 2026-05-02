from rest_framework.permissions import BasePermission

from .models import UserRole


class IsAuthenticatedAndActive(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if not user.is_active:
            return False
        if getattr(user, "deleted_at", None) is not None:
            return False
        return True


class IsSuperAdmin(IsAuthenticatedAndActive):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.role == UserRole.SUPER_ADMIN


class IsCompanyAdmin(IsAuthenticatedAndActive):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.role == UserRole.COMPANY_ADMIN


class IsBuildingManager(IsAuthenticatedAndActive):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.role == UserRole.BUILDING_MANAGER


class IsCustomerUser(IsAuthenticatedAndActive):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.role == UserRole.CUSTOMER_USER


def is_staff_role(user):
    return getattr(user, "role", None) in (
        UserRole.SUPER_ADMIN,
        UserRole.COMPANY_ADMIN,
        UserRole.BUILDING_MANAGER,
    )
