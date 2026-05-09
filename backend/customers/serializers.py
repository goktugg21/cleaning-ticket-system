from rest_framework import serializers

from .models import Customer


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = [
            "id",
            "company",
            # Sprint 14: legacy `building` is optional. New consolidated
            # customers can be created without an anchor building and
            # later linked to many buildings via CustomerBuildingMembership.
            "building",
            "name",
            "contact_email",
            "phone",
            "language",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_active", "created_at", "updated_at"]
        # `building` is left writable but allow_null/required propagate
        # automatically from the model field (Sprint 14 made it
        # null=True/blank=True). Listed here for clarity:
        extra_kwargs = {
            "building": {"required": False, "allow_null": True},
        }
