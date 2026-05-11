from rest_framework import serializers

from .models import (
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)


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
    Sprint 23C — write-side serializer for CustomerUserBuildingAccess.

    Accepts `access_role` only. The choice validator on the model
    field rejects unknown values for free. `permission_overrides`
    and `is_active` editing are still deferred — the override map
    needs a per-permission-key UI and `is_active` has cascade
    implications (it gates every permission to False) that the
    current admin surface does not yet surface to operators.

    Save audit is emitted by the existing accounts/audit signal
    handler keyed on the three Sprint 23A fields, so this
    serializer does not need to write an AuditLog row itself.
    """

    class Meta:
        model = CustomerUserBuildingAccess
        fields = ["access_role"]
