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

    B7 narrows the PROVIDER_INTERNAL note visibility path to
    `is_provider_management_role` (excludes STAFF). The remaining
    `is_staff_role` call sites in tickets/ are the operational
    completion-evidence / first-response gates where STAFF should
    continue to be admitted as a provider-side actor.
    """
    return getattr(user, "role", None) in (
        UserRole.SUPER_ADMIN,
        UserRole.COMPANY_ADMIN,
        UserRole.BUILDING_MANAGER,
        UserRole.STAFF,
    )


def is_provider_management_role(user):
    """
    B7 — True iff `user` is a provider-side **management** role.

    The three roles that may see and author `TicketMessageType.
    INTERNAL_NOTE` (i.e. the PROVIDER_INTERNAL tier from the
    canonical four-tier note taxonomy in §9 of
    `docs/product/system-business-logic-and-workflows.md`):

      * SUPER_ADMIN  — global.
      * COMPANY_ADMIN — provider company scope.
      * BUILDING_MANAGER — assigned building scope.

    STAFF is deliberately excluded: a STAFF user (field worker) is a
    provider-side actor for operational purposes (`is_staff_role`)
    but must NOT see PROVIDER_INTERNAL commercial / management
    notes (per §9.2). The two staff-facing note tiers
    (STAFF_OPERATIONAL, STAFF_COMPLETION) are governed separately
    and remain reachable by STAFF.

    CUSTOMER_USER and unauthenticated users always return False.
    """
    return getattr(user, "role", None) in (
        UserRole.SUPER_ADMIN,
        UserRole.COMPANY_ADMIN,
        UserRole.BUILDING_MANAGER,
    )


def is_super_admin(user):
    """True iff `user` is the global SUPER_ADMIN role.

    M1 B5 needs SUPER_ADMIN distinguished FROM the other two management
    roles (which `is_provider_management_role` lumps together): SA keeps a
    forensic read of EVERY message tier (incl. the customer-only
    CUSTOMER_INTERNAL), whereas COMPANY_ADMIN / BUILDING_MANAGER must NOT
    see CUSTOMER_INTERNAL.
    """
    return getattr(user, "role", None) == UserRole.SUPER_ADMIN


def is_customer_side(user):
    """True iff `user` is a customer-side principal (role CUSTOMER_USER).

    Covers both plain customer users and company-wide Customer Company
    Admins (the `is_company_admin` membership flag is carried on a
    CUSTOMER_USER-role user, so they share this role). M1 B5 uses this to
    gate PUBLIC_REPLY / CUSTOMER_INTERNAL posting and the customer-only
    RESTRICTED rule.
    """
    return getattr(user, "role", None) == UserRole.CUSTOMER_USER


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


class IsSuperAdminOrCompanyAdminOrBuildingManagerReadCustomer(
    IsAuthenticatedAndActive
):
    """
    Sprint 28 Batch 12 — BM read-only customer/contact gate.

    A permission that admits BUILDING_MANAGER on **safe methods only**
    (GET / HEAD / OPTIONS), and otherwise defers to the existing
    `IsSuperAdminOrCompanyAdminForCompany` semantics for unsafe methods
    (POST / PATCH / PUT / DELETE → SUPER_ADMIN or COMPANY_ADMIN of the
    customer's company; BM gets 403).

    For BM safe-method access, the customer must be in
    `scope_customers_for(request.user)` — i.e. linked to at least one
    of the BM's assigned buildings (either via the new M:N
    `CustomerBuildingMembership` or the legacy `Customer.building`
    anchor; the scope helper checks both). Out-of-scope customers
    yield 404 at the view layer's queryset filter, not 403, to avoid
    leaking customer existence to a BM.

    Behaviour for other roles is unchanged from the existing
    `IsSuperAdminOrCompanyAdminForCompany`:
      - STAFF / CUSTOMER_USER / anonymous → 403 on every method.
      - SUPER_ADMIN → passes everything.
      - COMPANY_ADMIN → passes only for customers in their company.

    No new `osius.*` keys are introduced — this is a deliberate
    re-use of the existing scope helpers (`scope_customers_for`,
    which already encodes the BM building-assignment branch) +
    DRF's SAFE_METHODS semantics.
    """

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        # Admins always pass; BM passes ONLY on safe methods. Unsafe
        # methods for BM fall through to False here so the view's
        # write actions return 403 just like they did pre-Batch-12.
        if request.user.role in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN):
            return True
        if request.user.role == UserRole.BUILDING_MANAGER:
            from rest_framework.permissions import SAFE_METHODS

            return request.method in SAFE_METHODS
        return False

    def has_object_permission(self, request, view, obj):
        from buildings.models import Building
        from companies.models import Company, CompanyUserMembership
        from customers.models import Customer

        if request.user.role == UserRole.SUPER_ADMIN:
            return True

        if request.user.role == UserRole.COMPANY_ADMIN:
            if isinstance(obj, Company):
                company_id = obj.id
            elif isinstance(obj, (Building, Customer)):
                company_id = obj.company_id
            else:
                return False
            return CompanyUserMembership.objects.filter(
                user=request.user, company_id=company_id
            ).exists()

        if request.user.role == UserRole.BUILDING_MANAGER:
            # Defence in depth: only Customer objects are reachable
            # through this gate today (the contacts endpoints look up
            # the URL-bound Customer and call `check_object_permissions`
            # against it). For anything else, deny — matches the
            # admin-gate's branching shape.
            from rest_framework.permissions import SAFE_METHODS

            if request.method not in SAFE_METHODS:
                return False
            if not isinstance(obj, Customer):
                return False
            # `scope_customers_for` is the single source of truth for
            # BM customer visibility (via `customer_ids_for` BM branch
            # → M:N CustomerBuildingMembership ∪ legacy
            # Customer.building anchor). Reuse it so the gate cannot
            # drift from the queryset.
            from accounts.scoping import scope_customers_for

            return scope_customers_for(request.user).filter(pk=obj.pk).exists()

        return False


class CanManageStaffMember(IsAuthenticatedAndActive):
    """
    Sprint 24A — gate for the StaffProfile + BuildingStaffVisibility
    admin endpoints under `/api/users/<user_id>/staff-*/`.

    has_permission: SUPER_ADMIN or COMPANY_ADMIN passes; others 403.

    has_object_permission(target_user):
      - target_user.role must be STAFF (the editor is the staff admin
        surface — non-staff users get 400 from the view layer, but
        the permission still rejects them defensively).
      - SUPER_ADMIN can act on any STAFF user.
      - COMPANY_ADMIN can act only on STAFF users that are in their
        own company's scope as resolved by `_user_in_actor_company`.
        Sprint 24A extends that helper to include BuildingStaffVisibility
        so a STAFF user with at least one visibility row in the
        actor's company is reachable.
      - BUILDING_MANAGER / STAFF / CUSTOMER_USER never pass.
    """

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return request.user.role in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN)

    def has_object_permission(self, request, view, obj):
        if getattr(obj, "role", None) != UserRole.STAFF:
            return False
        actor = request.user
        if actor.role == UserRole.SUPER_ADMIN:
            return True
        if actor.role != UserRole.COMPANY_ADMIN:
            return False
        from .scoping import _user_in_actor_company

        return _user_in_actor_company(actor, obj)


class CanManageUserProperties(IsAuthenticatedAndActive):
    """
    M2 P3 — gate for the custom-profile-property admin endpoints under
    `/api/users/<user_id>/properties/`.

    Sibling of `CanManageStaffMember` (deliberately NOT a modification
    of it), with two differences:

      - the target may be ANY user: staff AND customer users carry
        custom properties (SoT Addendum A.3.2), so there is no
        role==STAFF object filter;
      - COMPANY_ADMIN reaches targets via the same
        `_user_in_actor_company` union, which already includes
        CustomerUserMembership→customer→company, so customer users in
        the admin's provider-company scope are reachable.

    has_permission: SUPER_ADMIN or COMPANY_ADMIN passes; others 403.
    Customer-side roles get NO access — these endpoints are a
    management surface; the only customer-facing reads are the
    resolver-gated ticket payload and document download.
    """

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return request.user.role in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN)

    def has_object_permission(self, request, view, obj):
        actor = request.user
        if actor.role == UserRole.SUPER_ADMIN:
            return True
        if actor.role != UserRole.COMPANY_ADMIN:
            return False
        from .scoping import _user_in_actor_company

        return _user_in_actor_company(actor, obj)


class CanManageCustomerSideUsers(IsAuthenticatedAndActive):
    """
    B4 — gate for the customer-user management endpoints that admits a
    Customer Company Admin (a CUSTOMER_USER role user holding an active
    `CustomerUserBuildingAccess` row with `access_role=
    CUSTOMER_COMPANY_ADMIN` AND whose row resolves
    `customer.users.manage` to True for the URL-bound customer) in
    addition to the existing SUPER_ADMIN / COMPANY_ADMIN admit set.

    has_permission:
      - SUPER_ADMIN passes.
      - COMPANY_ADMIN passes (object check narrows to own provider company).
      - CUSTOMER_USER passes (object check narrows to "is a CCA with
        customer.users.manage in scope on the URL-bound customer").
      - other roles 403.

    has_object_permission(obj=Customer):
      - SUPER_ADMIN -> True.
      - COMPANY_ADMIN -> CompanyUserMembership in `customer.company_id`.
      - CUSTOMER_USER -> at least one active `CustomerUserBuildingAccess`
        row under this customer whose `access_has_permission` resolves
        `customer.users.manage` to True (i.e. customer-level scope).
      - other roles -> False.

    Per-building scope (e.g. when CCA grants access for a specific
    building) is enforced by the view layer in addition to this gate.
    No new permission key is introduced — the gate re-uses the
    existing `customer.users.manage` key from
    `customers.permissions.CUSTOMER_PERMISSION_KEYS`.
    """

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return request.user.role in (
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.CUSTOMER_USER,
        )

    def has_object_permission(self, request, view, obj):
        from companies.models import CompanyUserMembership
        from customers.models import (
            Customer,
            CustomerUserBuildingAccess,
            CustomerUserMembership,
        )
        from customers.permissions import access_has_permission

        actor = request.user
        if actor.role == UserRole.SUPER_ADMIN:
            return True
        if not isinstance(obj, Customer):
            return False

        if actor.role == UserRole.COMPANY_ADMIN:
            return CompanyUserMembership.objects.filter(
                user=actor, company_id=obj.company_id
            ).exists()

        if actor.role == UserRole.CUSTOMER_USER:
            # SoT Addendum A.1 — a company-wide Customer Company Admin
            # (the membership `is_company_admin` flag) is admitted with
            # NO per-building CUBA row required. The flag is the
            # authoritative top customer-side status; without this check
            # the 0010 migration (which deletes the legacy per-building
            # CCA rows) would strip a company-wide CCA's user-management
            # capability.
            if CustomerUserMembership.objects.filter(
                user=actor, customer=obj, is_company_admin=True
            ).exists():
                return True
            # B4 CCA admit. Must hold at least one active CUBA row
            # under THIS customer that resolves `customer.users.manage`
            # to True (default for `access_role=CUSTOMER_COMPANY_ADMIN`,
            # or any access_role whose `permission_overrides` grant
            # the key explicitly).
            for access in CustomerUserBuildingAccess.objects.filter(
                membership__user=actor,
                membership__customer=obj,
                is_active=True,
            ).select_related("membership"):
                if access_has_permission(access, "customer.users.manage"):
                    return True
            return False

        return False


class CanReadCustomerEmployees(IsAuthenticatedAndActive):
    """
    Read gate for the customer Employees directory
    (`GET /api/customers/<cid>/employees/`).

    Admits the roles that may VIEW a customer's people:
      - SUPER_ADMIN  — any customer.
      - COMPANY_ADMIN — customers in their provider company.
      - CUSTOMER_USER — a customer they belong to. ALL customer access
        roles (CCA / CLM / CU) may READ the directory; CLM / CU are
        read-only on the UI, and the access-role EDIT is gated separately by
        `CanManageCustomerSideUsers` (which only a CCA passes), so admitting
        CUSTOMER_USER here grants read, never write.

    Rejects (403): BUILDING_MANAGER and STAFF — they are provider field
    roles, not customer-side people, and have no business reading a
    customer's directory (the Employees RBAC matrix excludes them).

    The per-customer object scope (which <cid> is visible) is enforced in
    the view via `get_object_or_404(scope_customers_for(viewer), pk=cid)`,
    so a cross-tenant <cid> transparently 404s (no 403 leak) — a
    COMPANY_ADMIN cannot reach a customer outside their company and a
    CUSTOMER_USER cannot reach any customer but their own.
    """

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return request.user.role in (
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.CUSTOMER_USER,
        )


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


class IsProviderRosterReader(IsAuthenticatedAndActive):
    """
    Sprint 13C — read gate for the provider-side STAFF roster
    (Employees page backend, `GET /api/staff/`).

    Admits the three provider-management roles:
      - SUPER_ADMIN  — sees every STAFF user across all providers.
      - COMPANY_ADMIN — sees STAFF visible in their company's buildings.
      - BUILDING_MANAGER — sees STAFF visible in their assigned
        building(s).

    Rejects (403):
      - CUSTOMER_USER — never reads the provider roster.
      - STAFF — no existing rule lets a field worker list the roster;
        they read their own profile via `/api/auth/me/`.

    The viewer-scope narrowing (which STAFF rows are returned, and which
    `building_visibility` sub-rows are exposed) is enforced in the view
    layer via `building_ids_for`; this class only decides admittance.
    """

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return request.user.role in (
            UserRole.SUPER_ADMIN,
            UserRole.COMPANY_ADMIN,
            UserRole.BUILDING_MANAGER,
        )
