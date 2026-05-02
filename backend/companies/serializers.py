from rest_framework import serializers

from .models import Company


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = [
            "id",
            "name",
            "slug",
            "default_language",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
