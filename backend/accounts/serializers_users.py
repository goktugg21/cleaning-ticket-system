from rest_framework import serializers

from .models import User, UserRole
from .scoping import (
    building_ids_for,
    company_ids_for,
    customer_ids_for,
)


class UserListSerializer(serializers.ModelSerializer):
    scope_summary = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "role",
            "language",
            "is_active",
            "deleted_at",
            "scope_summary",
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
        fields = ["full_name", "language", "role", "is_active"]

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
