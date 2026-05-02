from rest_framework import serializers

from .models import Building


class BuildingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Building
        fields = [
            "id",
            "company",
            "name",
            "address",
            "city",
            "country",
            "postal_code",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
