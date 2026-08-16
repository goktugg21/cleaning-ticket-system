from rest_framework import serializers

from .models import User, UserRole
from .scoping import (
    building_ids_for,
    company_ids_for,
    customer_ids_for,
)


# Sprint 2c follow-up — customer access-role hierarchy. The global Users
# list shows ONE badge = the user's highest effective customer access role.
_ACCESS_ROLE_RANK = {
    "CUSTOMER_USER": 1,
    "CUSTOMER_LOCATION_MANAGER": 2,
    "CUSTOMER_COMPANY_ADMIN": 3,
}


class UserListSerializer(serializers.ModelSerializer):
    scope_summary = serializers.SerializerMethodField()
    customer_access_role = serializers.SerializerMethodField()
    companies = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            # Sprint 154 §I.1 — the admin Users list shows a phone column.
            "phone",
            "role",
            "language",
            "is_active",
            "deleted_at",
            "scope_summary",
            # Sprint 187B §1a — WHICH companies, beside scope_summary's
            # HOW MANY. A sibling field, not an extension; see
            # `get_companies` for the reasoning.
            "companies",
            "customer_access_role",
        ]
        read_only_fields = fields

    def get_scope_summary(self, obj):
        """
        Sprint 28 Batch 15.5 — short scope tag for the admin Users list.

        Returns {"label": str, "count": int}. SUPER_ADMIN returns the
        sentinel {"label": "all", "count": -1} which the frontend renders
        as "All companies". The reverse accessors are eager-loaded by
        ``UserViewSet.get_queryset`` via ``prefetch_related`` so a list
        of N users only fires the four membership SELECTs once.
        """
        role = obj.role
        if role == UserRole.SUPER_ADMIN:
            return {"label": "all", "count": -1}
        if role == UserRole.COMPANY_ADMIN:
            return {
                "label": "companies",
                "count": obj.company_memberships.count(),
            }
        if role == UserRole.BUILDING_MANAGER:
            return {
                "label": "buildings",
                "count": obj.building_assignments.count(),
            }
        if role == UserRole.STAFF:
            return {
                "label": "buildings",
                "count": obj.building_visibility.count(),
            }
        if role == UserRole.CUSTOMER_USER:
            return {
                "label": "customers",
                "count": obj.customer_memberships.count(),
            }
        return {"label": "all", "count": -1}

    def get_companies(self, obj):
        """Sprint 187B §1a — WHICH companies this user belongs to.

        Returns ``{"all": bool, "names": [str, ...]}``. The SUPER_ADMIN
        sentinel is ``{"all": True, "names": []}``, which the frontend
        renders as "All companies" exactly as the scope chip already
        does for that role.

        ## Why a sibling field and not an extension of `scope_summary`

        The prompt preferred extending `scope_summary`. Two things ruled
        it out, and the second is the real one:

        1. `accounts.tests.test_sprint28_user_scope_summary` pins that
           field with **exact dict equality** in six places
           (`assertEqual(row["scope_summary"], {"label": ..., "count":
           ...})`), not a subset check. Adding a key breaks all six.

        2. More importantly, `scope_summary` answers ONE question per
           role and the axis changes with the role: for a BUILDING_MANAGER
           its `count` is a number of BUILDINGS. Putting company names
           inside that object would make a single dict where `count`
           counts buildings and `names` names companies — two different
           axes in one field, which is exactly how a field starts meaning
           whatever its reader assumes. `scope_summary` stays "how many,
           of the thing that dominates this role"; `companies` is "which
           companies", for every role, and the two cannot drift because
           neither derives from the other.

        ## Where the names come from, per role

        Mirrors `accounts.scoping.company_ids_for` so the column and the
        `?company=` filter agree about what "belongs to" means:

          * COMPANY_ADMIN  — CompanyUserMembership
          * BUILDING_MANAGER — the companies of their assigned buildings
          * STAFF — the companies of their visible buildings
          * CUSTOMER_USER — the provider companies behind their customers

        A CUSTOMER_USER's provider company is included deliberately: the
        page's question is "whose people am I looking at", and for a
        customer user the answer is the provider that serves them. It is
        not customer linkage — no customer is named.

        ## No N+1

        Every accessor read here is prefetched by
        ``UserViewSet.get_queryset``, and that prefetch was extended in
        the same change to `select_related` the company on each one, so
        naming a company costs a JOIN inside a query that already ran
        rather than one SELECT per row. `assertNumQueries` pins it.
        """
        role = obj.role
        if role == UserRole.SUPER_ADMIN:
            return {"all": True, "names": []}

        if role == UserRole.COMPANY_ADMIN:
            names = [m.company.name for m in obj.company_memberships.all()]
        elif role == UserRole.BUILDING_MANAGER:
            names = [
                a.building.company.name for a in obj.building_assignments.all()
            ]
        elif role == UserRole.STAFF:
            names = [
                v.building.company.name for v in obj.building_visibility.all()
            ]
        elif role == UserRole.CUSTOMER_USER:
            names = [
                m.customer.company.name for m in obj.customer_memberships.all()
            ]
        else:
            names = []

        # De-duplicated and sorted in Python, NOT with .distinct(): the rows
        # are already in memory from the prefetch, and a queryset-level
        # distinct here would throw away that prefetch and fire a query per
        # row. A BM assigned to eight buildings in one company must name
        # that company once — `company_ids_for` carries a .distinct() for
        # the same fan-out, on the same relations.
        return {"all": False, "names": sorted(set(names))}

    def get_customer_access_role(self, obj):
        """
        Sprint 2c follow-up — the user's single HIGHEST effective customer
        access role for the global Users admin list
        (CUSTOMER_COMPANY_ADMIN > CUSTOMER_LOCATION_MANAGER > CUSTOMER_USER),
        or ``None`` for provider-side users and for any customer user with
        no in-scope active grant.

        Company-scoped to the VIEWER: a COMPANY_ADMIN only sees access roles
        from customers in their own provider company. The view passes the
        allowed company-id set via ``customer_access_company_ids`` in the
        serializer context (``None`` = SUPER_ADMIN, unrestricted); a grant
        whose ``membership.customer.company_id`` is outside that set is
        ignored. This prevents a cross-company leak where one viewer would
        see roles a user holds under a different provider's customers.

        Inactive grants are excluded (the resolver denies them). Computed in
        Python over the rows prefetched by ``UserViewSet.get_queryset``
        (list action; ``customer_memberships`` select_relates ``customer``
        for the company_id check) so there is no N+1.
        """
        scope = self.context.get("customer_access_company_ids")
        best_role = None
        best_rank = 0
        for membership in obj.customer_memberships.all():
            if scope is not None and membership.customer.company_id not in scope:
                continue
            # SoT Addendum A.1 — a company-wide Customer Company Admin
            # (the membership `is_company_admin` flag) is CCA across all
            # buildings, with no per-building access row. CCA is the top
            # rank, so it always wins — surface it directly.
            if membership.is_company_admin:
                return "CUSTOMER_COMPANY_ADMIN"
            for access in membership.building_access.all():
                if not access.is_active:
                    continue
                rank = _ACCESS_ROLE_RANK.get(access.access_role, 0)
                if rank > best_rank:
                    best_rank = rank
                    best_role = access.access_role
        return best_role


class UserDetailSerializer(serializers.ModelSerializer):
    company_ids = serializers.SerializerMethodField()
    building_ids = serializers.SerializerMethodField()
    customer_ids = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "phone",
            "role",
            "language",
            "is_active",
            "deleted_at",
            "company_ids",
            "building_ids",
            "customer_ids",
        ]
        read_only_fields = fields

    # Use the raw *_ids_for helpers so admin readers see every membership
    # row attached to the user, including ones on inactive entities. The
    # scope_*_for helpers (used by MeSerializer) hide inactive rows for
    # non-super-admin viewers, which is the wrong shape for an admin view
    # whose whole point is editing memberships.
    def get_company_ids(self, obj):
        return list(company_ids_for(obj))

    def get_building_ids(self, obj):
        return list(building_ids_for(obj))

    def get_customer_ids(self, obj):
        return list(customer_ids_for(obj))


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["full_name", "phone", "language", "role", "is_active"]

    def to_representation(self, instance):
        # PATCH/PUT must return the canonical detail shape so the
        # response equals what GET /api/users/<id>/ returns. The four
        # writable fields above stay the input contract; the response
        # is delegated to UserDetailSerializer so it carries id, email,
        # deleted_at, and the *_ids membership arrays. Without this the
        # frontend gets back a partial body and has to compensate with
        # `?? []` guards on every consumer.
        return UserDetailSerializer(instance, context=self.context).data

    def validate_role(self, value):
        actor = self.context["request"].user
        target = self.instance
        if not target:
            return value
        if value == target.role:
            return value
        # Self-target rule: a user cannot change their own role.
        if target.id == actor.id:
            raise serializers.ValidationError("You cannot change your own role.")
        if actor.role == UserRole.SUPER_ADMIN:
            return value
        # COMPANY_ADMIN rules: cannot manage SUPER_ADMIN or COMPANY_ADMIN.
        if value in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN):
            raise serializers.ValidationError(
                "Only a super admin can promote to this role."
            )
        if target.role in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN):
            raise serializers.ValidationError(
                "Only a super admin can change this role."
            )
        return value
