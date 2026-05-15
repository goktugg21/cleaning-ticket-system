from rest_framework import serializers

from accounts.models import UserRole

from .models import (
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from .permissions import CUSTOMER_PERMISSION_KEYS


class CustomerUserMembershipSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    user_full_name = serializers.CharField(source="user.full_name", read_only=True)
    user_role = serializers.CharField(source="user.role", read_only=True)

    class Meta:
        model = CustomerUserMembership
        fields = [
            "id",
            "customer",
            "user_id",
            "user_email",
            "user_full_name",
            "user_role",
            "created_at",
        ]
        read_only_fields = fields


class CustomerBuildingMembershipSerializer(serializers.ModelSerializer):
    """Sprint 14 — list/inspect customer↔building links."""

    building_id = serializers.IntegerField(source="building.id", read_only=True)
    building_name = serializers.CharField(source="building.name", read_only=True)
    building_address = serializers.CharField(
        source="building.address", read_only=True
    )

    class Meta:
        model = CustomerBuildingMembership
        fields = [
            "id",
            "customer",
            "building_id",
            "building_name",
            "building_address",
            "created_at",
        ]
        read_only_fields = fields


class CustomerUserBuildingAccessSerializer(serializers.ModelSerializer):
    """
    Sprint 14 — list/inspect a customer-user's per-building access.

    Sprint 23B exposes the Sprint 23A fields (access_role,
    permission_overrides, is_active) as READ-ONLY so the admin UI
    can render an at-a-glance access matrix. Sprint 23C adds a
    paired write serializer below that accepts `access_role` only;
    permission_overrides + is_active editing stays deferred until
    the matching UI lands.
    """

    membership_id = serializers.IntegerField(source="membership.id", read_only=True)
    user_id = serializers.IntegerField(source="membership.user.id", read_only=True)
    user_email = serializers.CharField(
        source="membership.user.email", read_only=True
    )
    building_id = serializers.IntegerField(source="building.id", read_only=True)
    building_name = serializers.CharField(source="building.name", read_only=True)

    class Meta:
        model = CustomerUserBuildingAccess
        fields = [
            "id",
            "membership_id",
            "user_id",
            "user_email",
            "building_id",
            "building_name",
            # Sprint 23B: read-only exposure of the Sprint 23A
            # fields. Sprint 23C adds write support via
            # CustomerUserBuildingAccessUpdateSerializer below.
            "access_role",
            "is_active",
            "permission_overrides",
            "created_at",
        ]
        read_only_fields = fields


class CustomerUserBuildingAccessUpdateSerializer(serializers.ModelSerializer):
    """
    Write-side serializer for CustomerUserBuildingAccess.

    Sprint 23C originally accepted `access_role` only. Sprint 27C
    closes RBAC gap G-B2 by adding write support for the other two
    Sprint 23A editable fields: `permission_overrides` (JSON dict
    of customer.* keys → bool) and `is_active` (bool). All three
    fields are independently validated:

      * `access_role` — Sprint 27A guard: only SUPER_ADMIN may
        grant `CUSTOMER_COMPANY_ADMIN`.

      * `permission_overrides` — Sprint 27C rules:
        - must be a dict,
        - every key must be in `CUSTOMER_PERMISSION_KEYS`
          (provider-side osius.* keys are explicitly rejected to
          prevent scope-bleed via the override map),
        - every value must be a true Python bool (rejecting ints,
          strings, None, lists, nested dicts),
        - full-replacement semantics: the PATCH body's value
          overwrites the previous override dict entirely.

      * `is_active` — the field's BooleanField type already
        coerces booleans; no extra guard needed.

    Save audit for all three fields is emitted by the existing
    accounts/audit signal handler keyed on `_CUBA_TRACKED_FIELDS`,
    so this serializer does not write AuditLog rows itself — it
    just makes the fields writable through the endpoint.

    The self-edit guard (actor cannot edit their own access row)
    is enforced one layer up at
    `customers.views_memberships.CustomerUserAccessDeleteView.patch`
    because it requires comparing `request.user.id` with the URL
    `user_id` kwarg — information the serializer doesn't see.
    """

    class Meta:
        model = CustomerUserBuildingAccess
        fields = ["access_role", "permission_overrides", "is_active"]

    def validate_access_role(self, value):
        """Sprint 27A guard (H-7 in
        docs/architecture/sprint-27-rbac-matrix.md): only
        SUPER_ADMIN may grant `CUSTOMER_COMPANY_ADMIN`. Provider
        COMPANY_ADMIN can still grant the two narrower customer-
        side roles — the endpoint's class-level permission already
        excludes everyone else.
        """
        if value == CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN:
            request = self.context.get("request")
            actor = getattr(request, "user", None)
            if getattr(actor, "role", None) != UserRole.SUPER_ADMIN:
                raise serializers.ValidationError(
                    "Only a Super Admin may grant the Customer Company "
                    "Admin access role.",
                )
        return value

    def validate_permission_overrides(self, value):
        """Sprint 27C: allow-list + boolean-only validation."""
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "permission_overrides must be a JSON object."
            )
        for key, override_value in value.items():
            if key not in CUSTOMER_PERMISSION_KEYS:
                raise serializers.ValidationError(
                    f"Unknown customer permission key: {key!r}. "
                    "Provider-side osius.* keys cannot be granted "
                    "via this endpoint."
                )
            # Reject ints (0/1), strings, None, lists, dicts. The
            # `bool is int` Python quirk means `isinstance(True, int)`
            # is True, so the type check must use `type(...) is bool`
            # to avoid accepting integer 0/1 through the back door.
            if type(override_value) is not bool:  # noqa: E721
                raise serializers.ValidationError(
                    f"Value for {key!r} must be a boolean, got "
                    f"{type(override_value).__name__}."
                )
        return value
