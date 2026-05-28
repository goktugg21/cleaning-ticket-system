from rest_framework import serializers

from accounts.permissions_v2 import BM_REVOCABLE_PERMISSION_KEYS

from .models import BuildingManagerAssignment


class BuildingManagerAssignmentSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    user_full_name = serializers.CharField(source="user.full_name", read_only=True)
    user_role = serializers.CharField(source="user.role", read_only=True)

    class Meta:
        model = BuildingManagerAssignment
        fields = [
            "id",
            "building",
            "user_id",
            "user_email",
            "user_full_name",
            "user_role",
            "assigned_at",
            # B6 — read exposure of the per-(BM, building) override map.
            # The full BM revocable key set lives in
            # `accounts.permissions_v2.BM_REVOCABLE_PERMISSION_KEYS`;
            # the write surface is the paired
            # `BuildingManagerAssignmentUpdateSerializer` below.
            "permission_overrides",
        ]
        read_only_fields = fields


class BuildingManagerAssignmentUpdateSerializer(serializers.ModelSerializer):
    """
    B6 — write-side serializer for
    `PATCH /api/buildings/<bid>/managers/<uid>/`.

    Only `permission_overrides` is writable; all other fields stay
    read-only. The validator enforces:

      * payload must be a dict,
      * every key must be in
        `accounts.permissions_v2.BM_REVOCABLE_PERMISSION_KEYS`
        (other `osius.*` / `customer.*` keys are explicitly rejected
        to prevent scope-bleed via the override map),
      * every value must be a real Python `bool` — ints (0/1), strings,
        None, lists, and dicts are rejected. The strict `type(v) is bool`
        check mirrors the customer-side
        `CustomerUserBuildingAccessUpdateSerializer.validate_permission_overrides`
        shape so the audit diff carries clean before/after JSON.

    Full-replacement semantics: the PATCH body's `permission_overrides`
    dict overwrites the previous one in full. Operators wanting to
    clear an override should send the new full dict explicitly (e.g.
    `{"permission_overrides": {}}`).
    """

    class Meta:
        model = BuildingManagerAssignment
        fields = ["permission_overrides"]

    def validate_permission_overrides(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "permission_overrides must be a JSON object."
            )
        for key, override_value in value.items():
            if key not in BM_REVOCABLE_PERMISSION_KEYS:
                raise serializers.ValidationError(
                    f"Unknown BM-revocable permission key: {key!r}. "
                    "Only the two B6 keys "
                    "(`osius.building_manager.override_customer_decision`, "
                    "`osius.building_manager.prepare_extra_work_proposal`) "
                    "may be set through this endpoint."
                )
            # Reject ints (0/1), strings, None, lists, dicts. The
            # `bool is int` Python quirk means `isinstance(True, int)`
            # is True, so the type check must use `type(v) is bool`.
            if type(override_value) is not bool:  # noqa: E721
                raise serializers.ValidationError(
                    f"Value for {key!r} must be a boolean, got "
                    f"{type(override_value).__name__}."
                )
        return value
