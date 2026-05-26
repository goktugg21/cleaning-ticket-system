from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response

from accounts.models import User, UserRole
from accounts.permissions import (
    CanManageCustomerSideUsers,
    IsSuperAdminOrCompanyAdminForCompany,
)
from buildings.models import Building
from config.pagination import UnboundedPagination

from .models import (
    Customer,
    CustomerBuildingMembership,
    CustomerCompanyPolicy,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from .permissions import user_can
from .serializers_memberships import (
    CustomerBuildingMembershipSerializer,
    CustomerCompanyPolicySerializer,
    CustomerUserBuildingAccessSerializer,
    CustomerUserBuildingAccessUpdateSerializer,
    CustomerUserMembershipSerializer,
)


# ---------------------------------------------------------------------------
# B4 — shared CCA-guard helpers used by the four user-management endpoints
# below. CCA admit logic lives on the DRF permission class
# (`CanManageCustomerSideUsers`); these helpers add the per-action guards
# the spec requires:
#   * CCA cannot touch a target user who currently holds a CCA access row
#     under this customer (membership delete + access PATCH/DELETE).
#   * CCA per-building manage check (CCA may grant / edit / revoke access
#     only at buildings where their `customer.users.manage` resolves true).
# ---------------------------------------------------------------------------
def _target_has_cca_access(customer, user_id) -> bool:
    """B4 — True if the (user_id, customer) target carries at least one
    active `CustomerUserBuildingAccess` row at `access_role=
    CUSTOMER_COMPANY_ADMIN`. A CCA actor must never touch another CCA's
    rows or membership; this helper centralises the check.
    """
    return CustomerUserBuildingAccess.objects.filter(
        membership__customer=customer,
        membership__user_id=user_id,
        access_role=(
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
        ),
    ).exists()


def _cca_actor(request) -> bool:
    """True iff the request actor is a CUSTOMER_USER role user (i.e. a
    CCA admitted by `CanManageCustomerSideUsers`). SA / COMPANY_ADMIN
    return False — they have their own paths and are NOT subject to the
    CCA-only B4 guards."""
    return request.user.role == UserRole.CUSTOMER_USER


def _cca_has_building_manage(actor, customer_id: int, building_id: int) -> bool:
    """B4 — True iff a CCA actor holds `customer.users.manage` at the
    specific (customer, building) pair via `user_can`. Called by the
    CUBA create / patch / delete views before the row is touched.
    """
    return user_can(
        actor, customer_id, building_id, "customer.users.manage"
    )


# ---------------------------------------------------------------------------
# B5 — Super Admin-controlled policy gate that disables Provider Company
# Admin's authority to manage Customer Company Admin users/permissions.
#
# Two helpers, mirroring the B4 shape:
#
#   * `_company_admin_cca_policy_blocks_target` — target-level. Used by
#     endpoints that operate on a (customer, user) tuple rather than a
#     specific access row: membership delete + access create. If the
#     target user holds any CCA access row under this customer AND the
#     policy is disabled, COMPANY_ADMIN is blocked with 403.
#
#   * `_company_admin_cca_policy_blocks_access_row` — row-level. Used by
#     the per-access PATCH and DELETE endpoints. If the access row's
#     current `access_role` is CUSTOMER_COMPANY_ADMIN AND the policy is
#     disabled, COMPANY_ADMIN is blocked with 403. This catches
#     edit / demote / revoke of an existing CCA row even though those
#     operations do not pass `access_role=CCA` in the payload (so the
#     serializer-layer grant gate would not otherwise fire).
#
# SUPER_ADMIN always bypasses both helpers — they remain the single role
# authorised to manage CCA-tier users when the policy is off. Other roles
# (BM / STAFF / CUSTOMER_USER) are rejected earlier by the class-level
# `CanManageCustomerSideUsers` admit (CCA actors are admitted but the B4
# CCA-cannot-manage-CCA guards reject them separately).
#
# The grant gate on `CustomerUserBuildingAccessUpdateSerializer.
# validate_access_role` still owns the "set access_role=CCA" rejection
# (returns 400). The view-layer helpers below are NEW surface — they
# cover edit / demote / revoke / extend-reach of CCA targets, which the
# serializer-layer grant gate alone does not reach.
# ---------------------------------------------------------------------------
def _company_admin_cca_policy_blocks_target(request, customer, user_id):
    """B5 — return a 403 Response when COMPANY_ADMIN tries to operate on
    a user who currently holds any CCA access row under this customer
    while `provider_admin_may_manage_customer_company_admins` is False. Returns
    None to indicate the actor may proceed (SA always, COMPANY_ADMIN
    when policy=True, non-CCA targets, non-COMPANY_ADMIN actors).
    """
    actor = request.user
    if actor.role != UserRole.COMPANY_ADMIN:
        return None
    if not _target_has_cca_access(customer, user_id):
        return None
    if customer.company.provider_admin_may_manage_customer_company_admins:
        return None
    return Response(
        {
            "detail": (
                "Super Admin has disabled Provider Company Admin's "
                "ability to manage Customer Company Admin users on "
                "this provider company. Only a Super Admin may operate "
                "on this user's membership or access rows."
            ),
            "code": "cca_policy_disabled",
        },
        status=status.HTTP_403_FORBIDDEN,
    )


def _company_admin_cca_policy_blocks_access_row(request, access):
    """B5 — return a 403 Response when COMPANY_ADMIN tries to mutate or
    delete a CCA-tier access row while
    `provider_admin_may_manage_customer_company_admins` is False. Returns None
    when the actor may proceed.
    """
    actor = request.user
    if actor.role != UserRole.COMPANY_ADMIN:
        return None
    if access.access_role != (
        CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
    ):
        return None
    company = access.membership.customer.company
    if company.provider_admin_may_manage_customer_company_admins:
        return None
    return Response(
        {
            "detail": (
                "Super Admin has disabled Provider Company Admin's "
                "ability to manage Customer Company Admin access rows "
                "on this provider company. Only a Super Admin may "
                "edit, demote, or revoke this access."
            ),
            "code": "cca_policy_disabled",
        },
        status=status.HTTP_403_FORBIDDEN,
    )


class CustomerUserListCreateView(generics.ListCreateAPIView):
    # B4 — admits SA, COMPANY_ADMIN, and CCA-with-`customer.users.manage`.
    # CCA's customer-level admit is verified by `CanManageCustomerSideUsers`;
    # per-action guards (no CCA-on-CCA, etc.) live inline below.
    permission_classes = [CanManageCustomerSideUsers]
    serializer_class = CustomerUserMembershipSerializer
    pagination_class = UnboundedPagination

    def _get_customer(self):
        customer = get_object_or_404(Customer, pk=self.kwargs["customer_id"])
        self.check_object_permissions(self.request, customer)
        return customer

    def get_queryset(self):
        customer = self._get_customer()
        return (
            CustomerUserMembership.objects.filter(customer=customer)
            .select_related("user")
            .order_by("-created_at")
        )

    def create(self, request, *args, **kwargs):
        customer = self._get_customer()
        user_id = request.data.get("user_id")
        if not user_id:
            return Response(
                {"user_id": "This field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = get_object_or_404(
            User, pk=user_id, is_active=True, deleted_at__isnull=True
        )
        if user.role != UserRole.CUSTOMER_USER:
            return Response(
                {"user_id": "User must have the customer-user role."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # B4 CCA self-link guard — a CCA must not link themselves as a
        # new customer-user under their own customer (defence in depth;
        # the H-7 grant gate already prevents elevating self to CCA via
        # access_role, but a CCA could otherwise add a fresh membership
        # row at the default CUSTOMER_USER tier on themselves).
        if _cca_actor(request) and request.user.id == user.id:
            return Response(
                {"detail": "You cannot manage your own membership."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # B4 CCA cannot-touch-another-CCA guard. A target who already
        # carries a CCA access row under this customer is off-limits to
        # a CCA actor — only SUPER_ADMIN (and COMPANY_ADMIN, today)
        # can manage CCA-tier targets.
        if _cca_actor(request) and _target_has_cca_access(customer, user.id):
            return Response(
                {
                    "detail": (
                        "Customer Company Admin cannot manage another "
                        "Customer Company Admin."
                    ),
                    "code": "cca_cannot_manage_cca",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        membership, created = CustomerUserMembership.objects.get_or_create(
            customer=customer, user=user
        )
        return Response(
            CustomerUserMembershipSerializer(membership).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class CustomerUserDeleteView(generics.GenericAPIView):
    # B4 — admits SA, COMPANY_ADMIN, and CCA-with-`customer.users.manage`.
    permission_classes = [CanManageCustomerSideUsers]

    def delete(self, request, customer_id, user_id):
        customer = get_object_or_404(Customer, pk=customer_id)
        self.check_object_permissions(request, customer)

        # B5 — COMPANY_ADMIN policy gate. When the provider Company's
        # `provider_admin_may_manage_customer_company_admins` is False,
        # COMPANY_ADMIN cannot delete a CCA-tier user's membership.
        # SA always passes; non-CCA targets always pass.
        blocked = _company_admin_cca_policy_blocks_target(
            request, customer, user_id
        )
        if blocked is not None:
            return blocked

        # B4 CCA cannot delete themselves nor any other CCA membership.
        if _cca_actor(request):
            if request.user.id == int(user_id):
                return Response(
                    {"detail": "You cannot remove your own membership."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if _target_has_cca_access(customer, user_id):
                return Response(
                    {
                        "detail": (
                            "Customer Company Admin cannot remove another "
                            "Customer Company Admin."
                        ),
                        "code": "cca_cannot_manage_cca",
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        # Sprint 14: deleting the parent membership cascades to all of
        # this user's per-building access rows under this customer
        # (CustomerUserBuildingAccess has on_delete=CASCADE on its
        # membership FK, so the DB does this for us — documented here
        # so reviewers do not look for explicit cleanup).
        deleted, _ = CustomerUserMembership.objects.filter(
            customer=customer, user_id=user_id
        ).delete()
        if deleted == 0:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ===========================================================================
# Sprint 14 — Customer ↔ Buildings (M:N) management
# ===========================================================================


class CustomerBuildingListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/customers/<customer_id>/buildings/      list linked buildings
    POST /api/customers/<customer_id>/buildings/      {building_id} → link
    """

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]
    serializer_class = CustomerBuildingMembershipSerializer
    pagination_class = UnboundedPagination

    def _get_customer(self):
        customer = get_object_or_404(Customer, pk=self.kwargs["customer_id"])
        self.check_object_permissions(self.request, customer)
        return customer

    def get_queryset(self):
        customer = self._get_customer()
        return (
            CustomerBuildingMembership.objects.filter(customer=customer)
            .select_related("building")
            .order_by("building__name")
        )

    def create(self, request, *args, **kwargs):
        customer = self._get_customer()
        building_id = request.data.get("building_id")
        if not building_id:
            return Response(
                {"building_id": "This field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        building = get_object_or_404(Building, pk=building_id)

        # Building must belong to the same company as the customer; we
        # do not let an admin link a customer to a building that lives
        # in a different tenant.
        if building.company_id != customer.company_id:
            return Response(
                {"building_id": "Building does not belong to the customer's company."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not building.is_active:
            return Response(
                {"building_id": "Building is inactive."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        link, created = CustomerBuildingMembership.objects.get_or_create(
            customer=customer, building=building
        )
        return Response(
            CustomerBuildingMembershipSerializer(link).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class CustomerBuildingDeleteView(generics.GenericAPIView):
    """
    DELETE /api/customers/<customer_id>/buildings/<building_id>/

    Sprint 14: removing a customer↔building link also revokes any
    per-user building access rows that pointed at the same
    (customer, building) pair. Without this cascade the access rows
    would be orphaned (still referenced by `building` but no longer
    valid for this customer because the parent link is gone), and
    the scope subquery would still match them.
    """

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]

    @transaction.atomic
    def delete(self, request, customer_id, building_id):
        customer = get_object_or_404(Customer, pk=customer_id)
        self.check_object_permissions(request, customer)

        link = CustomerBuildingMembership.objects.filter(
            customer=customer, building_id=building_id
        ).first()
        if link is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        # Cascade-revoke any per-user access for this customer/building.
        CustomerUserBuildingAccess.objects.filter(
            membership__customer=customer, building_id=building_id
        ).delete()

        link.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ===========================================================================
# Sprint 14 — per-customer-user building access
# ===========================================================================


class CustomerUserAccessListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/customers/<customer_id>/users/<user_id>/access/
    POST /api/customers/<customer_id>/users/<user_id>/access/  {building_id}
    """

    # B4 — admits SA, COMPANY_ADMIN, and CCA-with-`customer.users.manage`.
    # CCA per-building manage check + CCA-cannot-touch-CCA-target check are
    # done inline in `create()`.
    permission_classes = [CanManageCustomerSideUsers]
    serializer_class = CustomerUserBuildingAccessSerializer
    pagination_class = UnboundedPagination

    def _get_membership(self):
        customer = get_object_or_404(Customer, pk=self.kwargs["customer_id"])
        self.check_object_permissions(self.request, customer)
        membership = get_object_or_404(
            CustomerUserMembership,
            customer=customer,
            user_id=self.kwargs["user_id"],
        )
        return membership

    def get_queryset(self):
        membership = self._get_membership()
        return (
            CustomerUserBuildingAccess.objects.filter(membership=membership)
            .select_related("building", "membership__user")
            .order_by("building__name")
        )

    def create(self, request, *args, **kwargs):
        membership = self._get_membership()

        # B5 defense-in-depth — POST cannot be used as a CCA-grant
        # smuggle path. The create endpoint historically ignores
        # `access_role` in the request body (the row is materialised
        # at the model default), but we explicitly reject the payload
        # when a COMPANY_ADMIN actor passes `access_role=CCA` and the
        # provider Company's policy toggle is False. SA bypasses;
        # non-COMPANY_ADMIN actors fall through to the existing
        # "silently ignore body's access_role" behaviour (the
        # serializer-layer H-7 guard still owns the PATCH grant path).
        payload_access_role = request.data.get("access_role")
        if (
            payload_access_role == (
                CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
            )
            and request.user.role == UserRole.COMPANY_ADMIN
            and not (
                membership.customer.company
                .provider_admin_may_manage_customer_company_admins
            )
        ):
            return Response(
                {
                    "detail": (
                        "Super Admin has disabled Provider Company "
                        "Admin's ability to grant the Customer Company "
                        "Admin access role on this provider company."
                    ),
                    "code": "cca_policy_disabled",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        building_id = request.data.get("building_id")
        if not building_id:
            return Response(
                {"building_id": "This field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        building = get_object_or_404(Building, pk=building_id)

        # Sprint 14 invariant: a customer-user can only be granted
        # access to a building that is currently linked to the parent
        # customer. If the operator wants to add an access for a
        # not-yet-linked building they have to add the customer↔building
        # link first; the admin UI does this in one flow.
        if not CustomerBuildingMembership.objects.filter(
            customer=membership.customer, building=building
        ).exists():
            return Response(
                {"building_id": "Building is not linked to this customer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not building.is_active:
            return Response(
                {"building_id": "Building is inactive."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # B5 — COMPANY_ADMIN policy gate. Extending a CCA target's
        # building reach (even at the default CUSTOMER_USER tier on a
        # new building) counts as "managing CCA permissions/access"
        # under the disabled-toggle reading. SA always passes;
        # non-CCA targets always pass.
        blocked = _company_admin_cca_policy_blocks_target(
            request, membership.customer, membership.user_id
        )
        if blocked is not None:
            return blocked

        # B4 — CCA self / CCA-target / per-building manage guards. CCA
        # cannot touch their own access rows nor another CCA's rows,
        # AND CCA cannot grant access at a building where their
        # `customer.users.manage` does not resolve to True.
        if _cca_actor(request):
            if request.user.id == membership.user_id:
                return Response(
                    {"detail": "You cannot manage your own access row."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if _target_has_cca_access(membership.customer, membership.user_id):
                return Response(
                    {
                        "detail": (
                            "Customer Company Admin cannot manage another "
                            "Customer Company Admin's access."
                        ),
                        "code": "cca_cannot_manage_cca",
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            if not _cca_has_building_manage(
                request.user, membership.customer_id, building.id
            ):
                return Response(
                    {
                        "detail": (
                            "Customer Company Admin does not have "
                            "`customer.users.manage` at this building."
                        ),
                        "code": "cca_lacks_building_manage",
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        access, created = CustomerUserBuildingAccess.objects.get_or_create(
            membership=membership, building=building
        )
        return Response(
            CustomerUserBuildingAccessSerializer(access).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class CustomerUserAccessDeleteView(generics.GenericAPIView):
    """
    DELETE /api/customers/<customer_id>/users/<user_id>/access/<building_id>/
    PATCH  /api/customers/<customer_id>/users/<user_id>/access/<building_id>/

    Sprint 23C — PATCH accepts `{"access_role": <choice>}` and
    re-uses `CustomerUserBuildingAccessUpdateSerializer` for
    validation. The class-level permission gate
    (`IsSuperAdminOrCompanyAdminForCompany`) is checked twice: once
    by `has_permission` against the role (rejects everyone except
    SUPER_ADMIN / COMPANY_ADMIN), once by `has_object_permission`
    against the Customer (rejects a company admin acting on a
    customer outside their own company).

    Audit logging for the role change is handled by the existing
    accounts/audit signal keyed on the model's editable fields
    (Sprint 23A), so this view does not write AuditLog rows itself.
    """

    # B4 — admits SA, COMPANY_ADMIN, and CCA-with-`customer.users.manage`.
    # CCA-cannot-touch-CCA-target + per-building manage check live inline
    # in `patch()` and `delete()`.
    permission_classes = [CanManageCustomerSideUsers]

    def _get_access(self, request, customer_id, user_id, building_id):
        customer = get_object_or_404(Customer, pk=customer_id)
        self.check_object_permissions(request, customer)
        access = get_object_or_404(
            CustomerUserBuildingAccess,
            membership__customer=customer,
            membership__user_id=user_id,
            building_id=building_id,
        )
        return access

    def _cca_guard_for_existing_access(self, request, access) -> Response | None:
        """B4 — pre-mutation guard for CCA actors on an existing
        access row. Returns a 403 Response when the actor is a CCA
        and one of these is true:

          * the row's current `access_role` is `CUSTOMER_COMPANY_ADMIN`
            (CCA cannot edit / remove another CCA),
          * the actor does not hold `customer.users.manage` at the
            row's specific building.

        Returns None to indicate "proceed" — SA / COMPANY_ADMIN actors
        always proceed here; their gates ran earlier.
        """
        if not _cca_actor(request):
            return None
        if access.access_role == (
            CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
        ):
            return Response(
                {
                    "detail": (
                        "Customer Company Admin cannot edit or remove "
                        "another Customer Company Admin's access row."
                    ),
                    "code": "cca_cannot_manage_cca",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        if not _cca_has_building_manage(
            request.user, access.membership.customer_id, access.building_id
        ):
            return Response(
                {
                    "detail": (
                        "Customer Company Admin does not have "
                        "`customer.users.manage` at this building."
                    ),
                    "code": "cca_lacks_building_manage",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def patch(self, request, customer_id, user_id, building_id):
        # Sprint 27C self-edit guard: nobody can edit their own
        # access_role, permission_overrides, or is_active via this
        # endpoint — even SUPER_ADMIN. The guard runs BEFORE
        # _get_access so we don't reveal whether the row exists
        # to someone attempting to mutate themselves.
        if request.user.id == int(user_id):
            return Response(
                {
                    "detail": "You cannot edit your own customer access row.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        access = self._get_access(request, customer_id, user_id, building_id)
        # B4 CCA guards (no-op for SA / COMPANY_ADMIN actors).
        guard = self._cca_guard_for_existing_access(request, access)
        if guard is not None:
            return guard

        # B5 — COMPANY_ADMIN policy gate. When the provider Company's
        # toggle is False, COMPANY_ADMIN cannot edit, demote, or
        # otherwise mutate a CCA-tier access row. The serializer-layer
        # H-7 grant gate only fires when the payload sets
        # `access_role=CCA`; this view-layer gate is what catches the
        # demote (set access_role=lower) + `permission_overrides` edit
        # + `is_active=False` revoke paths on an existing CCA row.
        blocked = _company_admin_cca_policy_blocks_access_row(request, access)
        if blocked is not None:
            return blocked

        # Sprint 27A — pass request through so the
        # CustomerUserBuildingAccessUpdateSerializer.validate_access_role
        # guard can read actor.role from context. Without this the
        # guard would reject every PATCH (actor would be None).
        # The same serializer's H-7 guard ALSO blocks a CCA actor from
        # setting access_role=CUSTOMER_COMPANY_ADMIN in the payload
        # (only SA may do that), so payload-based CCA escalation is
        # blocked at the serializer layer.
        serializer = CustomerUserBuildingAccessUpdateSerializer(
            access,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # Refresh + re-serialize via the read serializer so the response
        # carries the joined building / user fields the frontend uses
        # to render the row.
        access.refresh_from_db()
        return Response(
            CustomerUserBuildingAccessSerializer(access).data,
            status=status.HTTP_200_OK,
        )

    def delete(self, request, customer_id, user_id, building_id):
        # B4 — block CCA self-delete on access rows. SA / COMPANY_ADMIN
        # may still delete arbitrarily (existing behaviour preserved).
        if _cca_actor(request) and request.user.id == int(user_id):
            return Response(
                {"detail": "You cannot remove your own customer access row."},
                status=status.HTTP_403_FORBIDDEN,
            )

        customer = get_object_or_404(Customer, pk=customer_id)
        self.check_object_permissions(request, customer)

        # B4 CCA guards on an EXISTING row: resolve the row first,
        # then apply CCA-cannot-manage-CCA + per-building manage
        # guards. Existing SA / COMPANY_ADMIN behaviour unchanged.
        existing = CustomerUserBuildingAccess.objects.filter(
            membership__customer=customer,
            membership__user_id=user_id,
            building_id=building_id,
        ).select_related("membership", "building").first()
        if existing is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        guard = self._cca_guard_for_existing_access(request, existing)
        if guard is not None:
            return guard

        # B5 — COMPANY_ADMIN policy gate. When the toggle is False,
        # COMPANY_ADMIN cannot revoke (DELETE) a CCA-tier access row.
        blocked = _company_admin_cca_policy_blocks_access_row(request, existing)
        if blocked is not None:
            return blocked

        existing.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ===========================================================================
# Sprint 27E — CustomerCompanyPolicy read/write endpoint
# ===========================================================================


class CustomerCompanyPolicyView(generics.GenericAPIView):
    """
    GET   /api/customers/<customer_id>/policy/   read the policy row.
    PATCH /api/customers/<customer_id>/policy/   update one or more booleans.

    Permission gate is `IsSuperAdminOrCompanyAdminForCompany`
    (the same one used for the surrounding membership endpoints).
    SUPER_ADMIN may act on any customer; COMPANY_ADMIN only on
    customers inside their own provider company; BUILDING_MANAGER /
    STAFF / CUSTOMER_USER never reach the view.

    The PATCH PATH is the only write surface for the new permission-
    policy booleans (Sprint 27C/27D) and for the three legacy
    `show_assigned_staff_*` mirrors. Audit coverage is owned by the
    existing Sprint 27C signal trio on `CustomerCompanyPolicy`; this
    view does not write to `AuditLog` itself.
    """

    permission_classes = [IsSuperAdminOrCompanyAdminForCompany]
    serializer_class = CustomerCompanyPolicySerializer

    def _get_policy(self, request, customer_id):
        customer = get_object_or_404(Customer, pk=customer_id)
        self.check_object_permissions(request, customer)
        # The Sprint 27C post_save signal + backfill migration
        # together guarantee every Customer has a policy row, so
        # this is a get(), not a get_or_create().
        return get_object_or_404(CustomerCompanyPolicy, customer=customer)

    def get(self, request, customer_id):
        policy = self._get_policy(request, customer_id)
        return Response(
            CustomerCompanyPolicySerializer(policy).data,
            status=status.HTTP_200_OK,
        )

    def patch(self, request, customer_id):
        policy = self._get_policy(request, customer_id)
        serializer = CustomerCompanyPolicySerializer(
            policy, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        policy.refresh_from_db()
        return Response(
            CustomerCompanyPolicySerializer(policy).data,
            status=status.HTTP_200_OK,
        )
