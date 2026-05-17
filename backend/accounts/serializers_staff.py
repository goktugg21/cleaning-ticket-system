"""
Sprint 24A — admin write surface for StaffProfile + BuildingStaffVisibility.

The Sprint 23A models already carry every editable field this admin
needs (phone / internal_note / can_request_assignment / is_active on
the profile; can_request_assignment on the visibility row). Sprint
24A adds the serializers that gate which fields are exposed for
PATCH and which are read-only context for the UI.

Each row is audited by the existing audit/signals.py wiring
(StaffProfile uses the full CRUD trio; BuildingStaffVisibility uses
the membership CREATE/DELETE shape). Nothing here writes AuditLog
rows directly.
"""
from rest_framework import serializers

from buildings.models import BuildingStaffVisibility

from .models import StaffProfile


class StaffProfileSerializer(serializers.ModelSerializer):
    """Read shape for /api/users/<id>/staff-profile/."""

    user_id = serializers.IntegerField(source="user.id", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    user_full_name = serializers.CharField(source="user.full_name", read_only=True)

    class Meta:
        model = StaffProfile
        fields = [
            "id",
            "user_id",
            "user_email",
            "user_full_name",
            "phone",
            "internal_note",
            "can_request_assignment",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class StaffProfileUpdateSerializer(serializers.ModelSerializer):
    """
    PATCH shape. Only the four fields below are writable; the user
    FK and timestamps stay locked. The response is rendered through
    `StaffProfileSerializer` so the joined user_email / user_full_name
    travel back to the caller without an extra GET.
    """

    class Meta:
        model = StaffProfile
        fields = [
            "phone",
            "internal_note",
            "can_request_assignment",
            "is_active",
        ]

    def to_representation(self, instance):
        return StaffProfileSerializer(instance, context=self.context).data


class BuildingStaffVisibilitySerializer(serializers.ModelSerializer):
    """Read shape for /api/users/<id>/staff-visibility/.

    Sprint 28 Batch 10 — exposes the new `visibility_level` enum so
    the frontend can render and edit per-row granularity (ASSIGNED_ONLY
    / BUILDING_READ / BUILDING_READ_AND_ASSIGN).
    """

    building_id = serializers.IntegerField(source="building.id", read_only=True)
    building_name = serializers.CharField(source="building.name", read_only=True)
    building_company_id = serializers.IntegerField(
        source="building.company_id", read_only=True
    )
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = BuildingStaffVisibility
        fields = [
            "id",
            "user_id",
            "user_email",
            "building_id",
            "building_name",
            "building_company_id",
            "can_request_assignment",
            "visibility_level",
            "created_at",
        ]
        read_only_fields = fields


class BuildingStaffVisibilityUpdateSerializer(serializers.ModelSerializer):
    """PATCH shape — toggle `can_request_assignment` and / or
    `visibility_level`.

    Sprint 28 Batch 10 — `visibility_level` is added as a writable
    field. DRF's ModelSerializer derives a `ChoiceField` from the
    model's `choices` automatically, so any value outside the three
    enum members produces a 400 with the standard
    `"is not a valid choice."` shape. The response is rendered through
    `BuildingStaffVisibilitySerializer` so the joined building / user
    context travels back without a follow-up GET.
    """

    class Meta:
        model = BuildingStaffVisibility
        fields = ["can_request_assignment", "visibility_level"]

    def to_representation(self, instance):
        return BuildingStaffVisibilitySerializer(instance, context=self.context).data
