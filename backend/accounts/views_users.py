from django.db.models import Exists, OuterRef, Prefetch, Q
from django.shortcuts import get_object_or_404
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from buildings.models import (
    Building,
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
from companies.models import CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)

from .effective_actions import (
    compute_effective_actions,
    compute_endpoint_notes,
    compute_overrides,
    compute_role_defaults,
    compute_scope,
)
from .models import User, UserRole
from .permissions import CanManageUser, IsSuperAdmin
from .permissions_effective import effective_permissions as compose_effective_permissions
from .serializers_users import (
    UserDetailSerializer,
    UserListSerializer,
    UserUpdateSerializer,
)


class UserViewSet(viewsets.ModelViewSet):
    permission_classes = [CanManageUser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["email", "full_name"]
    ordering_fields = ["email", "full_name", "role", "is_active"]
    ordering = ["email"]
    http_method_names = ["get", "patch", "delete", "post", "head", "options"]
    # POST is rejected with 405 except for the `reactivate` detail action;
    # users come into the system through the invitation flow only.

    def get_queryset(self):
        actor = self.request.user
        is_super = actor.role == UserRole.SUPER_ADMIN
        is_active_param = self.request.query_params.get("is_active")

        # The Users admin page navigates to /admin/users/:id from both the
        # active and inactive lists, but does not pass ?is_active=false. Without
        # this branch the inactive-user detail (and the Reactivate button it
        # gates) is unreachable.
        if is_super and self.action in ("retrieve", "reactivate"):
            qs = User.objects.all()
        elif is_active_param is not None and is_active_param.lower() == "false":
            qs = User.objects.filter(is_active=False)
        else:
            qs = User.objects.filter(is_active=True, deleted_at__isnull=True)

        if is_super:
            base = qs
        elif actor.role == UserRole.COMPANY_ADMIN:
            actor_company_ids = list(
                CompanyUserMembership.objects.filter(user=actor).values_list(
                    "company_id", flat=True
                )
            )
            if not actor_company_ids:
                return User.objects.none()
            in_scope_user_ids = (
                CompanyUserMembership.objects.filter(
                    company_id__in=actor_company_ids
                ).values_list("user_id", flat=True)
            )
            in_scope_user_ids = set(in_scope_user_ids).union(
                BuildingManagerAssignment.objects.filter(
                    building__company_id__in=actor_company_ids
                ).values_list("user_id", flat=True)
            )
            in_scope_user_ids = in_scope_user_ids.union(
                CustomerUserMembership.objects.filter(
                    customer__company_id__in=actor_company_ids
                ).values_list("user_id", flat=True)
            )
            # Sprint 24A — STAFF users with visibility on any of the
            # actor's buildings are in scope. Pairs with the
            # `_user_in_actor_company` extension in scoping.py so the
            # Users admin page surfaces the company's STAFF persona
            # alongside the Sprint-7 membership rows.
            in_scope_user_ids = in_scope_user_ids.union(
                BuildingStaffVisibility.objects.filter(
                    building__company_id__in=actor_company_ids
                ).values_list("user_id", flat=True)
            )
            base = qs.filter(id__in=in_scope_user_ids)
        else:
            return User.objects.none()

        role_filter = self.request.query_params.get("role")
        if role_filter:
            roles = [r.strip() for r in role_filter.split(",") if r.strip()]
            base = base.filter(role__in=roles)

        # Company scope for the customer-access surfaces: SUPER_ADMIN is
        # unrestricted (None); a COMPANY_ADMIN is limited to their own
        # provider companies. (Other roles never reach here.)
        scope_company_ids = None if is_super else actor_company_ids

        # Sprint 2c follow-up — ?access_role= filters by the EFFECTIVE
        # (single highest) customer access role, company-scoped to the
        # viewer. Single value, NOT comma-multi. An unknown value yields an
        # empty result (mirroring the role filter's "no match"). Each
        # per-role subquery is an Exists keyed on OuterRef("pk") so the
        # building_access fan-out cannot duplicate User rows. "Effective LM"
        # means an LM grant exists AND no higher (CCA) grant; "effective CU"
        # means a CU grant exists and no LM/CCA grant.
        AccessRole = CustomerUserBuildingAccess.AccessRole
        access_role_filter = self.request.query_params.get("access_role")
        if access_role_filter:
            requested = access_role_filter.strip()

            def _grant_exists(role):
                sub = CustomerUserBuildingAccess.objects.filter(
                    membership__user=OuterRef("pk"),
                    access_role=role,
                    is_active=True,
                )
                if scope_company_ids is not None:
                    sub = sub.filter(
                        membership__customer__company_id__in=scope_company_ids
                    )
                return Exists(sub)

            if requested == AccessRole.CUSTOMER_COMPANY_ADMIN:
                base = base.filter(
                    _grant_exists(AccessRole.CUSTOMER_COMPANY_ADMIN)
                )
            elif requested == AccessRole.CUSTOMER_LOCATION_MANAGER:
                base = base.filter(
                    _grant_exists(AccessRole.CUSTOMER_LOCATION_MANAGER)
                ).filter(~_grant_exists(AccessRole.CUSTOMER_COMPANY_ADMIN))
            elif requested == AccessRole.CUSTOMER_USER:
                base = (
                    base.filter(_grant_exists(AccessRole.CUSTOMER_USER))
                    .filter(~_grant_exists(AccessRole.CUSTOMER_LOCATION_MANAGER))
                    .filter(~_grant_exists(AccessRole.CUSTOMER_COMPANY_ADMIN))
                )
            else:
                # Unknown value -> no match (mirror ?role=).
                base = base.none()

        # Sprint 28 Batch 15.5 — prefetch the four scope tables the list
        # serializer's `scope_summary` counts against, so a list of N
        # users does not fire 4*N extra SELECTs. Scoped to the list
        # action because the detail / update / reactivate paths read
        # the membership rows through their own helpers and would just
        # pay the prefetch cost for nothing.
        # Sprint 2c follow-up — prefetch customer_memberships with their
        # `customer` (select_related, for the per-grant company_id scope
        # check) and `building_access` rows, for the list serializer's
        # `customer_access_role` projection (no N+1).
        if self.action == "list":
            base = base.prefetch_related(
                "company_memberships",
                "building_assignments",
                "building_visibility",
                Prefetch(
                    "customer_memberships",
                    queryset=CustomerUserMembership.objects.select_related(
                        "customer"
                    ).prefetch_related("building_access"),
                ),
            )
        return base.order_by(*self.ordering)

    def get_serializer_class(self):
        if self.action == "list":
            return UserListSerializer
        if self.action == "retrieve":
            return UserDetailSerializer
        return UserUpdateSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        # Sprint 2c follow-up — pass the viewer's provider-company scope so
        # the list serializer's `customer_access_role` only reflects access
        # grants under customers in the viewer's own company. None =
        # SUPER_ADMIN (unrestricted). Only the list action needs it.
        if self.action == "list":
            actor = self.request.user
            if actor.role == UserRole.SUPER_ADMIN:
                context["customer_access_company_ids"] = None
            else:
                context["customer_access_company_ids"] = list(
                    CompanyUserMembership.objects.filter(
                        user=actor
                    ).values_list("company_id", flat=True)
                )
        return context

    def create(self, request, *args, **kwargs):
        return Response(
            {"detail": "Create users via the invitation flow at /api/auth/invitations/."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def perform_destroy(self, instance):
        instance.soft_delete(deleted_by=self.request.user)

    @action(detail=True, methods=["post"], permission_classes=[IsSuperAdmin])
    def reactivate(self, request, pk=None):
        user = get_object_or_404(User, pk=pk)
        user.is_active = True
        user.deleted_at = None
        user.deleted_by = None
        user.save(update_fields=["is_active", "deleted_at", "deleted_by"])
        return Response(UserDetailSerializer(user).data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["get"],
        url_path="effective-permissions",
        permission_classes=[CanManageUser],
    )
    def effective_permissions(self, request, pk=None):
        """
        B3 — "Given this user, this customer, and optionally this
        building, what can this user actually do?"

        Single source of truth for frontend permission-overview
        screens (Customer Permissions page, Customer Users tab, User
        detail page, future premium permission UIs). Read-only. No
        side effects. No new permission keys.

        Caller authorization (re-uses `CanManageUser`):

          * SUPER_ADMIN can query anyone.
          * COMPANY_ADMIN can query users whose role is NOT
            SUPER_ADMIN / COMPANY_ADMIN, AND who are in the actor's
            own provider company. COMPANY_ADMIN can also GET their
            own row (the `obj.id == actor.id` branch of CanManageUser).
          * BUILDING_MANAGER / STAFF / CUSTOMER_USER → 403 at
            `has_permission` (they are not in
            `IsSuperAdminOrCompanyAdmin`'s admit set).

        Additional inline customer-scope check: a COMPANY_ADMIN
        querying a customer whose company is NOT the actor's own
        provider company gets 403. This guards against URL-typed
        cross-company customer access on an otherwise valid target
        user.

        Required query params:
          * customer_id (int) — the customer context for capability
            computation.

        Optional query params:
          * building_id (int) — narrows the context to a specific
            building. When omitted, capabilities are computed at the
            customer level.
        """
        target = self.get_object()  # CanManageUser; 403/404 on caller out of scope.

        # ---- query-param validation ----------------------------------
        customer_id_raw = request.query_params.get("customer_id")
        if not customer_id_raw:
            return Response(
                {
                    "detail": "customer_id is required.",
                    "code": "customer_id_required",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            customer_id = int(customer_id_raw)
        except (TypeError, ValueError):
            return Response(
                {
                    "detail": "customer_id must be an integer.",
                    "code": "customer_id_invalid",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        building_id_raw = request.query_params.get("building_id")
        building_id = None
        if building_id_raw not in (None, ""):
            try:
                building_id = int(building_id_raw)
            except (TypeError, ValueError):
                return Response(
                    {
                        "detail": "building_id must be an integer.",
                        "code": "building_id_invalid",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # ---- fetch customer + COMPANY_ADMIN scope guard ---------------
        customer = get_object_or_404(Customer, pk=customer_id)
        if request.user.role == UserRole.COMPANY_ADMIN:
            if not CompanyUserMembership.objects.filter(
                user=request.user, company_id=customer.company_id
            ).exists():
                # Cross-company customer access. Match the project
                # convention of `IsSuperAdminOrCompanyAdminForCompany`
                # (403, not 404 — the customer's existence is implied
                # by reaching this point, but only an actor with at
                # least one CompanyUserMembership has done so).
                self.permission_denied(
                    request,
                    message="Customer is outside your provider company.",
                )

        # ---- fetch + validate building --------------------------------
        building = None
        if building_id is not None:
            building = get_object_or_404(Building, pk=building_id)
            if building.company_id != customer.company_id:
                return Response(
                    {
                        "detail": (
                            "Building does not belong to the customer's "
                            "provider company."
                        ),
                        "code": "customer_building_mismatch",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not CustomerBuildingMembership.objects.filter(
                customer=customer, building=building
            ).exists():
                return Response(
                    {
                        "detail": (
                            "Building is not linked to this customer."
                        ),
                        "code": "customer_building_not_linked",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # ---- compute the response -------------------------------------
        scope_block = compute_scope(target, customer, building)
        role_defaults_block = compute_role_defaults(target, customer, building)
        overrides_block = compute_overrides(target, customer, building)
        effective_permissions_dict = compose_effective_permissions(
            target,
            customer_id=customer.id,
            building_id=building.id if building is not None else None,
        )
        effective_actions = compute_effective_actions(target, customer, building)
        notes = compute_endpoint_notes(target, customer, building)

        return Response(
            {
                "user": {
                    "id": target.id,
                    "email": target.email,
                    "role": target.role,
                    "is_active": target.is_active,
                },
                "context": {
                    "customer_id": customer.id,
                    "building_id": building.id if building is not None else None,
                    "company_id": customer.company_id,
                },
                "scope": scope_block,
                "role_defaults": role_defaults_block,
                "overrides": overrides_block,
                "effective_permissions": effective_permissions_dict,
                "effective_actions": effective_actions,
                "notes": notes,
            },
            status=status.HTTP_200_OK,
        )
