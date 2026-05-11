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
    """
    True iff `user` is a service-provider-side ("OSIUS-side") user.

    Used by tickets.views / tickets.serializers as the gate for
    staff-only behaviours: internal notes, hidden attachments,
    first-response stamping, the assignable-managers endpoint, and
    the "did a staff actor act on this ticket" branch of the
    change_status gate.

    Sprint 23A: STAFF is added here so the new field-staff role
    inherits the OSIUS-side ticket behaviour. Without this, STAFF
    users would be silently treated as customers in every call
    site — they would not be able to post internal notes, would
    not stamp first_response_at, and would be blocked from the
    staff branch of the status-change gate.
    """
    return getattr(user, "role", None) in (
        UserRole.SUPER_ADMIN,
        UserRole.COMPANY_ADMIN,
        UserRole.BUILDING_MANAGER,
        UserRole.STAFF,
    )


class IsSuperAdminOrCompanyAdmin(IsAuthenticatedAndActive):
    """
    Either super admin or company admin role. Object-level scope is enforced
    by the entity-specific classes below.
    """

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return request.user.role in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN)


class IsSuperAdminOrCompanyAdminForCompany(IsAuthenticatedAndActive):
    """
    Object-level: SUPER_ADMIN passes; COMPANY_ADMIN passes only if they are a
    member of the company being acted on. Resolves the company via the model
    class: Company.id directly, or Building/Customer.company_id.
    """

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return request.user.role in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN)

    def has_object_permission(self, request, view, obj):
        from buildings.models import Building
        from companies.models import Company, CompanyUserMembership
        from customers.models import Customer

        if request.user.role == UserRole.SUPER_ADMIN:
            return True
        if request.user.role != UserRole.COMPANY_ADMIN:
            return False

        if isinstance(obj, Company):
            company_id = obj.id
        elif isinstance(obj, (Building, Customer)):
            company_id = obj.company_id
        else:
            return False

        return CompanyUserMembership.objects.filter(
            user=request.user, company_id=company_id
        ).exists()


class CanManageUser(IsAuthenticatedAndActive):
    """
    Permission for User write operations.

    - has_permission: SUPER_ADMIN or COMPANY_ADMIN passes; others 403.
    - has_object_permission enforces:
      - A user cannot edit their own row (writes only); GET on self is allowed.
      - SUPER_ADMIN can act on anyone.
      - COMPANY_ADMIN can act only on users that overlap their company scope
        AND whose role is not SUPER_ADMIN or COMPANY_ADMIN (those roles are
        SUPER_ADMIN-managed only).
    """

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return request.user.role in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN)

    def has_object_permission(self, request, view, obj):
        actor = request.user
        if obj.id == actor.id:
            if request.method in ("GET", "HEAD", "OPTIONS"):
                return True
            return False
        if actor.role == UserRole.SUPER_ADMIN:
            return True
        if actor.role != UserRole.COMPANY_ADMIN:
            return False
        if obj.role in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN):
            return False
        from .scoping import _user_in_actor_company

        return _user_in_actor_company(actor, obj)
