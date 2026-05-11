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
    can render an at-a-glance access matrix. Editing those values
    via the admin UI is deferred to Sprint 23C — that surface
    needs careful per-permission-key toggles and is out of scope
    for the 23B "make foundation visible" pass.
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
            # fields. The admin UI renders these as badges /
            # summary; mutation lives in Sprint 23C.
            "access_role",
            "is_active",
            "permission_overrides",
            "created_at",
        ]
        read_only_fields = fields
