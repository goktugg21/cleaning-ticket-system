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

from .models import StaffProfile, User


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
            # Sprint 13C — employee category (read shape).
            "employment_type",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class StaffProfileUpdateSerializer(serializers.ModelSerializer):
    """
    PATCH shape. Only the fields below are writable; the user FK and
    timestamps stay locked. The response is rendered through
    `StaffProfileSerializer` so the joined user_email / user_full_name
    travel back to the caller without an extra GET.

    Sprint 13C — `employment_type` joins the writable surface. DRF's
    ModelSerializer derives a strict `ChoiceField` from the model's
    `EmploymentType.choices`, so any value outside the three enum
    members returns the standard 400 `"is not a valid choice."` shape.
    The gate is `CanManageStaffMember` (SUPER_ADMIN / COMPANY_ADMIN),
    so BUILDING_MANAGER stays read-only for the category (the Part B
    roster is the BM read surface).
    """

    class Meta:
        model = StaffProfile
        fields = [
            "phone",
            "internal_note",
            "can_request_assignment",
            "is_active",
            "employment_type",
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
            # Sprint 28 Batch 11 — STAFF completion routing flag.
            "staff_completion_routes_to_customer",
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
        # Sprint 28 Batch 11 — `staff_completion_routes_to_customer`
        # joins the writable PATCH surface. DRF's ModelSerializer
        # derives a strict BooleanField from the model declaration.
        fields = [
            "can_request_assignment",
            "visibility_level",
            "staff_completion_routes_to_customer",
        ]

    def to_representation(self, instance):
        return BuildingStaffVisibilitySerializer(instance, context=self.context).data


class StaffRosterSerializer(serializers.ModelSerializer):
    """
    Sprint 13C — read-only roster row for the provider/BM Employees
    page (`GET /api/staff/`).

    Privacy floor: this serializer is the BM/CA read surface and MUST
    NOT leak provider-internal fields. It deliberately exposes only the
    employment category + scoped building visibility — never
    `StaffProfile.internal_note`, `StaffProfile.phone`, any customer
    linkage, or any pricing field.

    `building_visibility` is scoped to the viewer: the view passes the
    viewer's building-id set in `context["viewer_building_ids"]` and
    only BSV rows for those buildings are serialized. SUPER_ADMIN gets
    the sentinel `None` (all buildings) so every row is shown.

    N+1 avoidance: the view prefetches `building_visibility__building`,
    so the in-Python filter below touches no extra queries.
    """

    full_name = serializers.CharField(read_only=True)
    has_staff_profile = serializers.SerializerMethodField()
    staff_profile_active = serializers.SerializerMethodField()
    employment_type = serializers.SerializerMethodField()
    building_visibility = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "full_name",
            "email",
            "role",
            "is_active",
            "has_staff_profile",
            "staff_profile_active",
            "employment_type",
            "building_visibility",
        ]
        read_only_fields = fields

    def _profile(self, obj):
        # OneToOne reverse accessor; may be absent for a freshly invited
        # STAFF user that has not been auto-provisioned a profile yet.
        return getattr(obj, "staff_profile", None)

    def get_has_staff_profile(self, obj) -> bool:
        return self._profile(obj) is not None

    def get_staff_profile_active(self, obj):
        profile = self._profile(obj)
        return profile.is_active if profile is not None else None

    def get_employment_type(self, obj):
        profile = self._profile(obj)
        return profile.employment_type if profile is not None else None

    def get_building_visibility(self, obj):
        viewer_building_ids = self.context.get("viewer_building_ids")
        rows = []
        for bsv in obj.building_visibility.all():
            # `None` sentinel = SUPER_ADMIN (no scope narrowing).
            if (
                viewer_building_ids is not None
                and bsv.building_id not in viewer_building_ids
            ):
                continue
            rows.append(
                {
                    "building_id": bsv.building_id,
                    "building_name": bsv.building.name,
                    "visibility_level": bsv.visibility_level,
                }
            )
        return rows
