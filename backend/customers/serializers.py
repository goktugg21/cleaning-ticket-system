from rest_framework import serializers

from accounts.models import UserRole

from .models import Customer, CustomerBuildingMembership, CustomerUserBuildingAccess


def compute_customer_actions(user, customer) -> dict:
    """
    Per-current-user, per-customer capability block. Used by the
    Customer detail endpoint and the membership-management endpoints.

    Surfaces three derived facts so the frontend can render a
    writable role dropdown + permission-management surface without
    re-deriving the rules:

      * `can_manage_customer_users` — mirrors
        `accounts.effective_actions.compute_effective_actions
        ["can_manage_customer_users"]` for the (viewer, customer) pair.
      * `can_manage_customer_company_admins` — mirrors the B5 toggle:
        SA always; CA in scope only when the provider Company's
        `provider_admin_may_manage_customer_company_admins` is True.
      * `allowed_target_customer_access_roles` — the set of
        `CustomerUserBuildingAccess.AccessRole` values the viewer may
        SET on a target customer-side user under this customer. Driven
        by the same H-7 grant gate the
        `CustomerUserBuildingAccessUpdateSerializer.validate_access_role`
        applies on PATCH.

    The action booleans are SAFE for an unauthenticated caller —
    every field returns its False / empty value when `user` is None or
    not authenticated. In practice this serializer is only reached
    behind authenticated gates, but defence in depth here means a
    future read path that drops the request context cannot leak
    capability hints.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return {
            "can_manage_customer_users": False,
            "can_manage_customer_company_admins": False,
            "allowed_target_customer_access_roles": [],
        }

    # Inline imports keep the customers app load order tolerant of the
    # accounts ↔ customers ↔ companies cycle (already exercised by
    # `customers.permissions`).
    from accounts.scoping import _user_in_actor_company
    from companies.models import CompanyUserMembership
    from .permissions import user_can

    role = getattr(user, "role", None)
    company = customer.company

    is_super = role == UserRole.SUPER_ADMIN
    is_ca_in = role == UserRole.COMPANY_ADMIN and CompanyUserMembership.objects.filter(
        user=user, company_id=company.id
    ).exists()

    # `can_manage_customer_users` — SA always; CA in scope always;
    # CUSTOMER_USER whose customer-level `customer.users.manage`
    # resolves True (CCA default). Mirrors B4 admit shape.
    if is_super or is_ca_in:
        can_manage_customer_users = True
    elif role == UserRole.CUSTOMER_USER:
        can_manage_customer_users = user_can(
            user, customer.id, None, "customer.users.manage"
        )
    else:
        can_manage_customer_users = False

    # `can_manage_customer_company_admins` — SA always; CA in scope
    # only when the policy is True. This mirrors
    # `effective_actions.compute_effective_actions` verbatim.
    if is_super:
        can_manage_customer_company_admins = True
    elif is_ca_in:
        can_manage_customer_company_admins = (
            company.provider_admin_may_manage_customer_company_admins
        )
    else:
        can_manage_customer_company_admins = False

    # `allowed_target_customer_access_roles` — what the viewer may
    # SET on a target user's CUBA row (PATCH `access_role`). H-7
    # restricts CCA-grant to SA, plus CA when B5 policy=True. Lower
    # tiers (CUSTOMER_USER, CUSTOMER_LOCATION_MANAGER) are reachable
    # by anyone who can manage customer users at all.
    #
    # Frontend renders a role dropdown directly from this list.
    lower_tiers = [
        CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER,
    ]
    cca_tier = CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
    if is_super:
        allowed_target_customer_access_roles = lower_tiers + [cca_tier]
    elif is_ca_in:
        if company.provider_admin_may_manage_customer_company_admins:
            allowed_target_customer_access_roles = lower_tiers + [cca_tier]
        else:
            allowed_target_customer_access_roles = list(lower_tiers)
    elif role == UserRole.CUSTOMER_USER and can_manage_customer_users:
        # CCA holder in scope may manage lower customer users but may
        # NEVER set access_role=CCA (H-7).
        allowed_target_customer_access_roles = list(lower_tiers)
    else:
        allowed_target_customer_access_roles = []

    return {
        "can_manage_customer_users": can_manage_customer_users,
        "can_manage_customer_company_admins": can_manage_customer_company_admins,
        "allowed_target_customer_access_roles": allowed_target_customer_access_roles,
    }


class CustomerSerializer(serializers.ModelSerializer):
    """
    Sprint 14 hotfix — expose `linked_building_ids` so the ticket-create
    page can offer customers whose only link to a building lives in the
    new M:N CustomerBuildingMembership table (i.e. consolidated
    customers like B Amsterdam, where `Customer.building` is NULL).

    Behaviour:

      - `linked_building_ids` is the de-duplicated, sorted list of
        building IDs linked to this customer via
        CustomerBuildingMembership.
      - For legacy safety: when a customer has *no* membership rows but
        DOES have a non-null `Customer.building`, that legacy id is
        included so pre-Sprint-14 customers without a backfilled M:N
        row still match in the frontend filter. (After the standard
        0003 migration backfill this fallback is unused — every legacy
        row has its own membership entry — but defence in depth.)

    Scope/permission contract:

      The list / detail endpoints already wrap their queryset in
      `scope_customers_for(user)` (see customers/views.py), so a
      caller never sees a customer outside their scope. The
      linked_building_ids list returned for a *visible* customer is
      the FULL set of buildings linked to that customer — it is NOT
      filtered to the caller's allowed buildings. That is on purpose:

        - The frontend Location dropdown is already filtered by
          `building_ids_for(user)` (a CUSTOMER_USER like Amanda only
          sees buildings she has CustomerUserBuildingAccess for).
        - The ticket-create endpoint validates the caller's
          per-(customer, building) access on the server. The frontend
          filter is convenience only.

      Returning the full linked-building list keeps this serializer
      simple and lets a CUSTOMER_USER who picks an in-scope building
      correctly find the customer in the dropdown.
    """

    linked_building_ids = serializers.SerializerMethodField()
    # Per-current-user, per-customer capability block. Frontend reads
    # this to render writable role dropdowns (via
    # `allowed_target_customer_access_roles`) and to gate the
    # user-management / CCA-management UI surfaces without
    # re-implementing the H-7 / B4 / B5 rules.
    actions = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            "id",
            "company",
            # Sprint 14: legacy `building` is optional. New consolidated
            # customers can be created without an anchor building and
            # later linked to many buildings via CustomerBuildingMembership.
            "building",
            "linked_building_ids",
            "name",
            "contact_email",
            "phone",
            "language",
            "is_active",
            # Sprint 23B — assigned-staff contact-visibility policy.
            # The CustomerViewSet permission gate is already
            # IsSuperAdminOrCompanyAdmin for write operations, so
            # only OSIUS-side admins can flip these flags. Customer
            # users hitting GET /api/customers/ never list this
            # customer at all (queryset gate) so leaking the bool
            # values back to a customer-side caller is impossible.
            "show_assigned_staff_name",
            "show_assigned_staff_email",
            "show_assigned_staff_phone",
            "created_at",
            "updated_at",
            "actions",
        ]
        read_only_fields = [
            "id",
            "linked_building_ids",
            "is_active",
            "actions",
            "created_at",
            "updated_at",
        ]
        # `building` is left writable but allow_null/required propagate
        # automatically from the model field (Sprint 14 made it
        # null=True/blank=True). Listed here for clarity:
        extra_kwargs = {
            "building": {"required": False, "allow_null": True},
        }

    def get_linked_building_ids(self, obj: Customer) -> list[int]:
        # When the view's queryset has prefetched
        # `building_memberships`, the iteration below uses the cached
        # list — no additional DB hit per row. The customer list
        # endpoint adds the prefetch in views.py to avoid N+1.
        ids = sorted(
            {m.building_id for m in obj.building_memberships.all()}
        )
        if ids:
            return ids
        # Legacy fallback for an unmigrated row.
        if obj.building_id is not None:
            return [obj.building_id]
        return []

    def get_actions(self, obj: Customer) -> dict:
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        return compute_customer_actions(user, obj)
