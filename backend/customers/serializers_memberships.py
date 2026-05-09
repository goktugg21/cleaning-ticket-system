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
    """Sprint 14 — list/inspect a customer-user's per-building access."""

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
            "created_at",
        ]
        read_only_fields = fields
