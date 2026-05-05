from rest_framework import serializers

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
        ]
        read_only_fields = fields
